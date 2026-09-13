#!/usr/bin/env python3
"""install.py — generate this machine's OpenCode config from shared + machine parts.

Two inputs, deliberately split:

  opencode.shared.json          in git, identical everywhere, no secrets, no paths
  ~/.config/opencode/machine.json   never committed, never synced: paths, keys,
                                    model choices, which harnesses this box may run

Placeholders `${repo_root}` `${data_root}` `${python}` are substituted from
machine.json. Keys whose name OR value mentions `${data_root}` are DROPPED when
`data_root` is null — a machine that must never hold participant data gets no rule
referring to a directory it does not have.

## Two things this script must never do

**Never sort keys.** OpenCode's permission matching is last-rule-wins, so the
catch-all `"*"` has to come FIRST and specifics after. `json.dumps(sort_keys=True)`
moves `"${data_root}/**": "deny"` ahead of `"*": "allow"` — `$` is 0x24, `*` is
0x2A — and the deny silently becomes an allow. The rule that protects participant
data would be nullified with no error anywhere. `assert_permission_order()` checks
the generated config rather than trusting this comment.

**Never clobber keys it does not own.** A hand-written `opencode.json` can hold the
only copy of a provider block — an API key, and per-model `zdr` / `data_collection`
settings that exist nowhere else. This merges into the existing file and replaces
only OWNED_KEYS. `provider` is machine identity, so it is preserved; declare it in
machine.json if you would rather have it generated.

Usage:
    python3 install.py                 # dry run (the default), prints the diff
    python3 install.py --apply         # write it
    python3 install.py --check         # exit 1 on drift, naming the keys
    python3 install.py --init          # scaffold machine.json, then stop

Exit: 0 clean, 1 drift or refusal, 2 usage error.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# .../agent-tooling/adapters/opencode/install.py -> .../agent-tooling
AGENT_TOOLING = os.path.dirname(os.path.dirname(HERE))
SHARED = os.path.join(HERE, "opencode.shared.json")
EXAMPLE = os.path.join(HERE, "machine.example.json")

CONFIG_DIR = os.path.expanduser("~/.config/opencode")
MACHINE = os.path.join(CONFIG_DIR, "machine.json")
GENERATED = os.path.join(CONFIG_DIR, "opencode.json")
CLAUDE_SKILLS = os.path.expanduser("~/.claude/skills")

# The only top-level keys this script writes. Everything else in an existing
# opencode.json is left exactly as found — see the docstring.
OWNED_KEYS = ("$schema", "permission", "agent")

REQUIRED_MACHINE_KEYS = ("machine", "python", "repo_root", "data_root")


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        die(f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        die(f"{what} is not valid JSON ({path}): {e}")


def substitute(node, subs, drop_data_root):
    """Walk the config, substituting placeholders and dropping data_root rules.

    Order is preserved throughout: dicts are rebuilt by iterating the original,
    never sorted. See the docstring on why that is load-bearing.
    """
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            # Leaf-level only. An earlier version used a recursive search, so a
            # top-level key whose SUBTREE mentioned ${data_root} was dropped — which
            # deleted the entire `permission` block on a machine with data_root null,
            # removing every rule rather than the one that names the data root.
            if drop_data_root and ("${data_root}" in k
                                   or (isinstance(v, str) and "${data_root}" in v)):
                continue
            out[_sub_str(k, subs)] = substitute(v, subs, drop_data_root)
        return out
    if isinstance(node, list):
        return [substitute(v, subs, drop_data_root) for v in node]
    if isinstance(node, str):
        return _sub_str(node, subs)
    return node


def _sub_str(s, subs):
    for k, v in subs.items():
        s = s.replace("${%s}" % k, str(v))
    return s


def build_config(shared, machine):
    cfg = shared.get("config")
    if not isinstance(cfg, dict):
        die(f"{SHARED} has no 'config' object")

    subs = {k: machine.get(k) for k in ("repo_root", "data_root", "python")}
    cfg = substitute(cfg, subs, drop_data_root=machine.get("data_root") is None)

    # Harness profiles: one model per harness, and an explicit disable for any
    # harness this machine may not run.
    agent = {}
    for name, model in (machine.get("harness_models") or {}).items():
        agent[name] = {"model": model}
    for name in (machine.get("disable_harnesses") or []):
        agent.setdefault(name, {})["disable"] = True
    if agent:
        cfg["agent"] = agent
    if machine.get("default_model"):
        cfg["model"] = machine["default_model"]
    return cfg


def assert_permission_order(cfg):
    """Fail if a deny precedes the catch-all in any permission block.

    Last-rule-wins means a deny listed BEFORE `"*"` is overridden by it. This is
    the failure a sorted serialisation produces, so it is checked on the artifact
    rather than asserted in a comment.
    """
    problems = []
    perm = cfg.get("permission")
    if not isinstance(perm, dict):
        return problems
    for block_name, block in perm.items():
        if not isinstance(block, dict):
            continue
        keys = list(block.keys())
        if "*" not in keys:
            continue
        star = keys.index("*")
        for i, k in enumerate(keys[:star]):
            problems.append(
                f"permission.{block_name}: '{k}' precedes the catch-all '*', so the "
                f"catch-all overrides it (last rule wins). Reorder, and never "
                f"serialise this file with sorted keys.")
    return problems


def merge(existing, generated):
    """Replace only OWNED_KEYS; preserve every other key as found."""
    out = dict(existing)
    for k in OWNED_KEYS:
        if k in generated:
            out[k] = generated[k]
    if "model" in generated:
        out["model"] = generated["model"]
    return out


def diff_owned(existing, generated):
    keys = set(OWNED_KEYS) | {"model"}
    return sorted(k for k in keys
                  if json.dumps(existing.get(k)) != json.dumps(generated.get(k))
                  and k in generated)


def check_version(shared):
    want = shared.get("opencode_version")
    if not want:
        return None
    exe = shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
    if not os.path.exists(exe):
        return f"opencode not found; cannot verify version {want}"
    try:
        got = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30).stdout.strip().splitlines()[-1].strip()
    except Exception as e:
        return f"could not run {exe} --version: {e}"
    if got != want:
        return f"opencode {got} installed, shared config expects {want}"
    return None


def plan_links(machine):
    """(source, destination) pairs. Sources must exist; destinations may not."""
    links = []
    for sub in ("agents", "plugins"):
        src = os.path.join(HERE, sub)
        if os.path.isdir(src):
            links.append((src, os.path.join(CONFIG_DIR, sub)))
    skills = os.path.join(AGENT_TOOLING, "skills")
    if os.path.isdir(skills):
        for name in sorted(os.listdir(skills)):
            if os.path.isfile(os.path.join(skills, name, "SKILL.md")):
                links.append((os.path.join(skills, name),
                              os.path.join(CLAUDE_SKILLS, name)))
    return links


def apply_links(links, apply):
    for src, dst in links:
        cur = os.path.realpath(dst) if os.path.islink(dst) else None
        if cur == os.path.realpath(src):
            continue
        if os.path.exists(dst) and not os.path.islink(dst):
            print(f"  SKIP  {dst} exists and is not a symlink — left alone")
            continue
        print(f"  link  {dst} -> {src}")
        if apply:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.islink(dst):
                os.unlink(dst)
            os.symlink(src, dst)


def do_init():
    if os.path.exists(MACHINE):
        die(f"{MACHINE} already exists; not overwriting")
    example = load_json(EXAMPLE, "machine.example.json")
    example.pop("$hague_example", None)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(MACHINE, "w", encoding="utf-8") as fh:
        json.dump(example, fh, indent=2)
        fh.write("\n")
    os.chmod(MACHINE, 0o600)
    print(f"scaffolded {MACHINE} — edit it, then re-run install.py")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write the config (default: dry run)")
    g.add_argument("--check", action="store_true", help="exit 1 on drift, naming the keys")
    g.add_argument("--init", action="store_true", help="scaffold machine.json, then stop")
    a = ap.parse_args()

    if a.init:
        return do_init()

    shared = load_json(SHARED, "shared config")
    if not os.path.exists(MACHINE):
        die(f"{MACHINE} not found. This script guesses no defaults — "
            f"run `install.py --init` to scaffold it, then edit it.")
    machine = load_json(MACHINE, "machine config")

    missing = [k for k in REQUIRED_MACHINE_KEYS if k not in machine]
    if missing:
        die(f"{MACHINE} is missing required key(s): {', '.join(missing)}")

    # Check the SHARED file first: while the key is still the literal
    # `${data_root}/**`, '$' (0x24) sorts before '*' (0x2A), so a sorted
    # serialisation moves the deny ahead of the catch-all. After substitution the
    # key is an absolute path and sorts harmlessly — so the generated config alone
    # would not reveal a shared file that had been reordered at its source.
    problems = assert_permission_order(shared.get("config", {}))
    if problems:
        print(f"refusing to write — {os.path.basename(SHARED)} is misordered:")
        for p in problems:
            print(f"  {p}")
        return 1

    generated = build_config(shared, machine)

    problems = assert_permission_order(generated)
    if problems:
        print("refusing to write — permission ordering would fail OPEN:")
        for p in problems:
            print(f"  {p}")
        return 1

    existing = {}
    if os.path.exists(GENERATED):
        existing = load_json(GENERATED, "existing opencode.json")

    drift = diff_owned(existing, generated)

    if a.check:
        vp = check_version(shared)
        if vp:
            print(f"drift: {vp}")
        if drift:
            print("drift in generated keys: " + ", ".join(drift))
        if drift or vp:
            return 1
        print("opencode config matches this machine's inputs")
        return 0

    vp = check_version(shared)
    if vp:
        die(f"refusing to continue: {vp}")

    merged = merge(existing, generated)
    preserved = [k for k in existing if k not in OWNED_KEYS and k != "model"]

    print(f"machine   {machine['machine']}")
    print(f"target    {GENERATED}")
    if drift:
        print(f"changes   {', '.join(drift)}")
    else:
        print("changes   none — config already matches")
    if preserved:
        print(f"preserved {', '.join(preserved)}  (not owned by install.py)")

    links = plan_links(machine)
    apply_links(links, a.apply)

    if not a.apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        return 0

    os.makedirs(CONFIG_DIR, exist_ok=True)
    # Never sort_keys: see the docstring.
    with open(GENERATED, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
        fh.write("\n")
    os.chmod(GENERATED, 0o600)
    print(f"\nwrote {GENERATED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
