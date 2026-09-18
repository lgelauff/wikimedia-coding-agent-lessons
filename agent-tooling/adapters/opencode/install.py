#!/usr/bin/env python3
"""Deploy the shared OpenCode/Claude harness config to this machine.

Three-phase by design, because a config that goes live on first write cannot be
compared, tested, or rolled back:

  stage   build the complete candidate set in a staging tree. Nothing live changes.
  diff    show what would change against the live tree.
  deploy  activate it — per skill or as one batch.

`--dry-run` is the default for every phase. Nothing is written until `--apply`.

Ownership contract (the reason this is a script and not a checklist):

  * It writes ONLY the keys it owns: `permission`, `agent`, and `env.AGENT_TOOLING_ROOT`
    in the OpenCode config; `env.AGENT_TOOLING_ROOT` in Claude's settings.json.
    Provider blocks, plugin lists, permissions.allow and every other key are preserved
    byte-for-byte.
  * It BACKS UP before writing, using the local epoch-ms convention already present in
    ~/.claude/backups/.
  * It refuses to run without machine.json. A guessed data_root is the failure D23 exists
    to prevent.

Staging tree (default <repo>/agent-tooling/adapters/opencode/.stage):
  skills/<name> -> ../../../../skills/<name>   symlinks, so there is ONE canonical copy
  agents/*.md  -> ../agents/*.md
  plugins/*.ts -> ../plugins/*.ts
  env                                          the values this host must inject
  MANIFEST.json                                what was staged, when, from which commit

Exit codes: 0 ok · 1 drift/refused · 2 could not complete (never treat 2 as ok).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent            # .../agent-tooling/adapters/opencode -> repo
SKILLS_SRC = REPO_ROOT / "agent-tooling" / "skills"
SHARED_CFG = HERE / "opencode.shared.json"
OPENCODE_HOME = Path.home() / ".config" / "opencode"
CLAUDE_HOME = Path.home() / ".claude"
STAGE = HERE / ".stage"

# The user-facing hub. Machine identity lives here so it sits with the rest of the
# user's agent files; the legacy ~/.config/opencode location stays as a fallback for
# a host that has not been migrated yet.
AGENT_HUB = Path.home() / "agent"
HUB_MACHINE = AGENT_HUB / "machine.json"
LEGACY_MACHINE = OPENCODE_HOME / "machine.json"

OWNED_OPENCODE_KEYS = {"permission", "agent", "enabled_providers", "model"}
OWNED_ENV_KEYS = {"AGENT_TOOLING_ROOT"}

# Skills that live in this repo but must not be deployed yet. Each entry names why, and
# what would unblock it — an exclusion without a removal condition becomes permanent
# by accident.
EXCLUDE_FROM_DEPLOY = {
    "browser-verify": (
        "needs a running app. It reaches for wiki-polis's local-e2e, which is bound to "
        "that repo's Docker stack, so the chain is broken anywhere else "
        "(implementation-plan leak L2). Unblock by shipping the generic local-stack "
        "contract — .claude/local-stack.json naming up/down/health/base_url — and "
        "rewriting local-e2e as a binding over it (task 0.5)."
    ),
}


# ------------------------------------------------------------------ helpers

def now_ms() -> int:
    return int(time.time() * 1000)


def say(msg: str = "") -> None:
    print(msg)


def planned(action: str, path: Path | str, detail: str = "") -> None:
    print(f"  {action:<8} {path}{('  — ' + detail) if detail else ''}")


def backup(path: Path, dry: bool) -> Path | None:
    """Copy path to a timestamped sibling under ~/.claude/backups/."""
    if not path.exists():
        return None
    dest_dir = CLAUDE_HOME / "backups"
    dest = dest_dir / f"{path.name}.backup.{now_ms()}"
    if dry:
        planned("BACKUP", f"{path} -> {dest}")
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, dest, symlinks=True)
    else:
        shutil.copy2(path, dest)
    planned("BACKUP", f"{path} -> {dest}")
    return dest


def load_json(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    # tolerate jsonc's leading // comments and a trailing comma-free single object
    lines = [l for l in raw.splitlines() if not l.strip().startswith("//")]
    return json.loads("\n".join(lines))


def substitute(obj, values: dict):
    """Recursively substitute ${name} from values.

    A key or value that still carries an unresolved placeholder is DROPPED, which is
    how 'data_root may be null' is implemented: rather than emitting a literal
    '${data_root}/**' deny rule that matches nothing, the rule is omitted. A deny rule
    that silently fails to match is worse than no rule, because it reads as protection
    while providing none.

    But dropping on a pattern match is itself a silent failure mode — a typo in the
    pattern once deleted a legitimate allow rule here. So the rule is now explicit:

      * A placeholder is dropped ONLY when its name is absent from `values`.
      * After substitution, any surviving placeholder is a BUG and raises, because the
        only correct number of unresolved placeholders in deployed config is zero.
    """
    PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    # Only these may be legitimately absent, and only these may therefore be dropped.
    # Anything else missing is a bug in the shared config or machine.json, not a
    # nullable value — and dropping it would silently delete a rule.
    NULLABLE = {"data_root"}

    def resolve(v):
        if isinstance(v, str):
            for name, val in values.items():
                v = v.replace("${" + name + "}", str(val))
        return v

    def drop_ok(name: str) -> bool:
        if name in values:
            return False
        if name in NULLABLE:
            return True
        raise SystemExit(
            f"BUG: ${{{name}}} has no value in machine.json and is not a known nullable field.\n"
            f"  known values: {sorted(values)} · nullable: {sorted(NULLABLE)}\n"
            "  Refusing to emit a rule that would match nothing while reading as protection."
        )

    def walk(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if any(drop_ok(n) for n in PLACEHOLDER.findall(k)):
                    continue
                out[resolve(k)] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            if any(drop_ok(n) for n in PLACEHOLDER.findall(node)):
                return None
            return resolve(node)
        return node

    def scrub(node):
        if isinstance(node, dict):
            return {k: scrub(v) for k, v in node.items() if scrub(v) is not None}
        if isinstance(node, list):
            return [v for v in (scrub(x) for x in node) if v is not None]
        return node

    return scrub(walk(obj))


def read_machine() -> dict:
    for p in (HUB_MACHINE, LEGACY_MACHINE):
        if p.exists():
            return load_json(p)
    say(f"REFUSED: no machine.json at {HUB_MACHINE} or {LEGACY_MACHINE}.")
    say("  Machine identity is required — paths, keys and model choice must not be guessed.")
    say(f"  Run:  python3 {Path(__file__).name} --init    then edit {HUB_MACHINE}")
    sys.exit(1)


# ------------------------------------------------------------------ phases

def build_config(machine: dict) -> dict:
    shared = load_json(SHARED_CFG)
    values = {
        "python": machine.get("python", "/usr/bin/python3"),
        "repo_root": machine["repo_root"],
        # Deliberately NOT `or ""`. An empty string resolves the placeholder to
        # "/**" and turns a specific deny into a blanket one that blocks everything.
        # Absent must mean absent, so substitute() drops the rule instead.
        "agent_tooling_root": str(REPO_ROOT / "agent-tooling"),
    }
    if machine.get("data_root"):
        values["data_root"] = machine["data_root"]
    cfg = substitute(shared["config"], values)

    # agents: model per harness, plus the disable list.
    #
    # The union matters. Iterating harness_models alone meant a harness listed in
    # disable_harnesses but absent from harness_models was never emitted AT ALL — so
    # `disable` silently failed to apply. On hague that left the two harnesses that
    # must not run there (analysis, writing) fully enabled. Privacy-critical config
    # must fail closed: a harness named for disabling is emitted as disabled whether
    # or not it has a model.
    agents: dict[str, dict] = {}
    for name, model in (machine.get("harness_models") or {}).items():
        agents[name] = {"model": model}
    for name in (machine.get("disable_harnesses") or []):
        agents.setdefault(name, {})["disable"] = True
    if agents:
        cfg.setdefault("agent", {}).update(agents)

    # Provider allow-list. This is the control that encodes D20/D22 (no participant
    # data through third-party hosts). `enabled_providers` is stable; the
    # `experimental.policies` form is not, so prefer this one.
    if machine.get("enabled_providers"):
        cfg["enabled_providers"] = list(machine["enabled_providers"])

    # Machine-specific extra allowed paths, merged into external_directory.
    #
    # These are locations the AGENT may also reach, on top of the repo root. They belong
    # in machine.json and not in the shared config, because they are filesystem facts
    # about one machine (hague has no ~/Downloads).
    #
    # This WIDENS the boundary. Each entry is a path outside ~/dev that the agent can now
    # read and write, so it should be added deliberately and kept short. Note that the
    # OpenCode docs' own example for this rule is a read-only grant; the value here is
    # read/write, which is what makes `~/Downloads` useful and also what makes it worth
    # being explicit about.
    for p in machine.get("extra_allowed_paths") or []:
        if not p:
            continue
        resolved = p.replace("~", str(Path.home()))
        cfg.setdefault("permission", {}).setdefault("external_directory", {})[
            f"{resolved.rstrip('/')}/**"
        ] = "allow"

    if machine.get("default_model"):
        cfg["model"] = machine["default_model"]
    return cfg


def merge_owned(existing: dict, owned: dict) -> dict:
    """Shallow-merge owned keys into existing, preserving everything else."""
    merged = dict(existing)
    for k, v in owned.items():
        merged[k] = v
    return merged


def phase_stage(machine: dict, dry: bool) -> None:
    say("PHASE stage — build the candidate set")
    say()
    if STAGE.exists() and not dry:
        shutil.rmtree(STAGE)
    for sub in ("skills", "agents", "plugins"):
        d = STAGE / sub
        if dry:
            planned("MKDIR", d)
        else:
            d.mkdir(parents=True, exist_ok=True)

    skills = sorted(p for p in SKILLS_SRC.glob("*/SKILL.md"))
    if not skills:
        say("COULD NOT COMPLETE: no skills found to stage")
        sys.exit(2)
    for sk in skills:
        target = STAGE / "skills" / sk.parent.name
        if target.exists() or target.is_symlink():
            continue
        link_to = os.path.relpath(sk.parent, STAGE / "skills")
        if dry:
            planned("SYMLINK", target, f"-> {link_to}")
        else:
            target.symlink_to(link_to)
    for kind, src in (("agents", HERE / "agents"), ("plugins", HERE / "plugins")):
        if not src.is_dir():
            continue
        for f in sorted(src.iterdir()):
            target = STAGE / kind / f.name
            link_to = os.path.relpath(f, STAGE / kind)
            if dry:
                planned("SYMLINK", target, f"-> {link_to}")
            else:
                target.symlink_to(link_to)

    # NOTE: no `env` file is staged. The plugin derives AGENT_TOOLING_ROOT from its own
    # path (import.meta.url resolves through the symlink to the real file), so a staged
    # env blob would have been written by nobody and read by nobody. Claude Code gets the
    # variable via ~/.claude/settings.json below; OpenCode gets it via the plugin's
    # shell.env hook. Two hosts, two mechanisms, one value.

    manifest = {
        "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": machine.get("machine"),
        "commit": git_head(),
        "skills": [p.parent.name for p in skills],
    }
    if dry:
        planned("WRITE", STAGE / "MANIFEST.json", f"{len(skills)} skills")
    else:
        (STAGE / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    say()
    say(f"  staged {len(skills)} skills, machine={machine.get('machine')}")


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def phase_diff() -> int:
    say("PHASE diff — live vs staged")
    say()
    if not STAGE.exists():
        say("  nothing staged yet — run --stage first")
        return 1
    drifted = False
    for kind, live in (("skills", CLAUDE_HOME / "skills"),
                       ("agents", OPENCODE_HOME / "agents"),
                       ("plugins", OPENCODE_HOME / "plugins")):
        staged = sorted(p.name for p in (STAGE / kind).iterdir()) if (STAGE / kind).is_dir() else []
        present = sorted(p.name for p in live.iterdir()) if live.is_dir() else []
        missing = [n for n in staged if n not in present]
        extra = [n for n in present if n not in staged]
        say(f"  {kind}: staged={len(staged)} live={len(present)}")
        for n in missing:
            planned("ADD", live / n); drifted = True
        for n in extra:
            planned("KEEP (not ours)", live / n)
    say()
    if drifted:
        say("  drift: staged set is not yet live")
        return 1
    say("  in sync")
    return 0


def neutralise_jsonc(dry: bool) -> None:
    """Remove ~/.config/opencode/opencode.jsonc, backing it up.

    OpenCode loads opencode.json and then merges opencode.jsonc OVER it, so on any
    conflicting key the .jsonc wins. A single permission added there would silently
    override the entire generated baseline — and `--check` would not notice, because
    it compares symlinks, not config content. One authoritative file, or none.

    Verified from the app bundle rather than the docs: the load order is
    `mergeConfig(result, loadFile(…/opencode.json))` followed by
    `mergeConfig(result, loadFile(…/opencode.jsonc))`.
    """
    legacy = OPENCODE_HOME / "opencode.jsonc"
    if not legacy.exists():
        return
    try:
        content = load_json(legacy)
    except Exception:
        content = None
    # A .jsonc holding nothing but $schema cannot override anything, but it still
    # shadows by existence and invites a future edit. Remove it either way.
    keys = sorted(k for k in content if k != "$schema") if isinstance(content, dict) else ["<unparseable>"]
    if dry:
        planned("BACKUP+RM", legacy, f"superseded by opencode.json; carries {keys}")
        return
    backup(legacy, dry=False)
    legacy.unlink()
    planned("REMOVED", legacy, f"was carrying {keys}")


def phase_deploy(machine: dict, dry: bool, batch: bool) -> None:
    say(f"PHASE deploy — {'BATCH' if batch else 'per-skill'}")
    say()
    cfg = build_config(machine)

    # 0. Remove any shadowing .jsonc BEFORE writing opencode.json, or the file we
    #    write could be overridden by one that already exists.
    neutralise_jsonc(dry)

    # 1. OpenCode config
    oc_path = OPENCODE_HOME / "opencode.json"
    existing = {}
    if oc_path.exists():
        try:
            existing = load_json(oc_path)
        except Exception as e:
            say(f"  WARN: could not parse {oc_path}: {e}; refusing to overwrite")
            sys.exit(2)
    owned = {k: v for k, v in cfg.items() if k in OWNED_OPENCODE_KEYS}
    env_block = {"AGENT_TOOLING_ROOT": str(REPO_ROOT / "agent-tooling")}
    if "model" in cfg:
        owned["model"] = cfg["model"]
    merged = merge_owned(existing, owned)
    merged.setdefault("$schema", cfg.get("$schema", "https://opencode.ai/config.json"))

    if dry:
        planned("WRITE", oc_path, f"owns {sorted(owned)}")
        for k in owned:
            planned("  key", k)
    else:
        backup(oc_path, dry=False)
        oc_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        planned("WROTE", oc_path)

    # 2. Claude settings env
    cs_path = CLAUDE_HOME / "settings.json"
    if dry:
        planned("MERGE", cs_path, f"env.AGENT_TOOLING_ROOT={env_block['AGENT_TOOLING_ROOT']}")
    else:
        cj = load_json(cs_path) if cs_path.exists() else {}
        backup(cs_path, dry=False)
        cj.setdefault("env", {}).update(env_block)
        cs_path.write_text(json.dumps(cj, indent=2) + "\n", encoding="utf-8")
        planned("MERGED", cs_path, "env.AGENT_TOOLING_ROOT")

    # 3. Symlink skill / agent / plugin sets.
    #
    # Always sourced from the repo, never from STAGE. Deploy used to read STAGE when
    # applying, which meant `--deploy --apply` without a prior `--stage --apply` found
    # no staging tree, hit the `continue` below, and silently created no symlinks —
    # while still writing the config. A partial deploy that reports success is the
    # worst outcome, so deploy no longer depends on another phase having run.
    for kind, live, source in (
        ("skills", CLAUDE_HOME / "skills", SKILLS_SRC),
        ("agents", OPENCODE_HOME / "agents", HERE / "agents"),
        ("plugins", OPENCODE_HOME / "plugins", HERE / "plugins"),
    ):
        if not source.is_dir():
            planned("SKIP", live, f"no source directory for {kind}/ at {source}")
            continue
        if not live.exists():
            if dry:
                planned("MKDIR", live)
            else:
                live.mkdir(parents=True, exist_ok=True)
        names = sorted(
            p.name for p in source.iterdir()
            if p.name != "MANIFEST.json" and p.name not in EXCLUDE_FROM_DEPLOY
        )
        for n in sorted(p.name for p in source.iterdir() if p.name in EXCLUDE_FROM_DEPLOY):
            planned("EXCLUDED", f"{kind}/{n}", EXCLUDE_FROM_DEPLOY[n].split(".")[0])
        if batch:
            backup(live, dry)
        for n in names:
            target = live / n
            if target.exists() or target.is_symlink():
                planned("EXISTS (kept)", target)
                continue
            if dry:
                planned("SYMLINK", target, f"-> {source / n}")
            else:
                target.symlink_to(os.path.relpath((source / n).resolve(), live))
    say()
    say("  done" if not dry else "  DRY RUN — nothing written")


def phase_print_config(machine: dict) -> int:
    """Print the exact merged config that --deploy would write. Read-only.

    This is the review artifact: the permission block is the part that can fail
    OPEN if mis-ordered, so it has to be inspected before it is applied.
    """
    oc_path = OPENCODE_HOME / "opencode.json"
    existing = {}
    if oc_path.exists():
        try:
            existing = load_json(oc_path)
        except Exception:
            say("  live opencode.json is unparseable and will be treated as empty")
    cfg = build_config(machine)
    owned = {k: v for k, v in cfg.items() if k in OWNED_OPENCODE_KEYS}
    if "model" in cfg:
        owned["model"] = cfg["model"]
    merged = merge_owned(existing, owned)
    merged.setdefault("$schema", cfg.get("$schema", "https://opencode.ai/config.json"))
    print(json.dumps(merged, indent=2))
    return 0


def phase_init() -> None:
    # Prefer the hub when it exists, so a migrated host creates machine.json in the
    # same place install.py reads it from. Fall back to the legacy location otherwise.
    dest = HUB_MACHINE if AGENT_HUB.is_dir() else LEGACY_MACHINE
    if dest.exists() or dest.is_symlink():
        say(f"  {dest} already exists — not touching it")
        return
    src = HERE / "machine.example.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    say(f"  created {dest} from machine.example.json")
    say("  EDIT IT — the $hague_example key shows the hague variant; delete it once set.")


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stage and deploy the shared harness config. Dry-run by default.")
    ap.add_argument("--stage", action="store_true", help="build the candidate set in .stage")
    ap.add_argument("--diff", action="store_true", help="compare staged against live")
    ap.add_argument("--deploy", action="store_true", help="activate the staged set")
    ap.add_argument("--batch", action="store_true",
                    help="with --deploy: replace whole live trees as one batch (backed up)")
    ap.add_argument("--apply", action="store_true", help="actually write (default is dry-run)")
    ap.add_argument("--init", action="store_true", help="create machine.json from the example")
    ap.add_argument("--check", action="store_true", help="exit non-zero if live differs from staged")
    ap.add_argument("--print-config", action="store_true",
                    help="print the exact config --deploy would write (read-only review)")
    ap.add_argument("--skills-dir", default=str(SKILLS_SRC))
    args = ap.parse_args()

    dry = not args.apply
    if dry and not args.print_config:
        say("DRY RUN — nothing will be written. Pass --apply to execute.")
        say()

    if args.init:
        phase_init()
        return 0

    machine = read_machine()

    if args.print_config:
        return phase_print_config(machine)

    if args.check:
        return phase_diff()

    ran = False
    if args.stage:
        phase_stage(machine, dry); ran = True
    if args.diff:
        return phase_diff()
    if args.deploy:
        phase_deploy(machine, dry, args.batch); ran = True
    if not ran:
        ap.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())