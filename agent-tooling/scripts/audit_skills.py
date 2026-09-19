#!/usr/bin/env python3
"""Audit a skill set for internal contradictions.

Not a linter. It looks for the failure modes that only appear once you have SEVERAL
skills and a model choosing between them:

  TRIGGER COLLISION   two skills compete for the same request. The model picks one;
                      which one wins is arbitrary. Detected by overlapping trigger
                      vocabulary between descriptions.
  DUPLICATE NEGATION  two skills both say "use me INSTEAD of <the same thing>", which
                      is an outright contradiction if the things are the same.
  DANGLING REFERENCE  an agent profile names a skill/playbook that does not exist, or a
                      skill names a reference path (`playbooks/…`, `skills/…`) that does
                      not exist. Silent at runtime, and the failure looks like "the agent
                      ignored the process" rather than "the file was wrong".
  ORPHAN              a skill nothing references and that names nothing. It cannot be
                      discovered through cross-reference and is probably dead.

Contract: exit 0 clean, 1 problems found, 2 could not complete. Matches the repo's
other guards: never report clean on a 2.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# Words that carry no discriminating signal for trigger purposes.
STOP = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "by", "with",
    "from", "is", "are", "was", "be", "been", "it", "its", "this", "that", "these",
    "those", "you", "your", "we", "our", "use", "used", "using", "when", "whenever",
    "wants", "want", "asks", "ask", "someone", "something", "any", "all", "not", "no",
    "instead", "before", "after", "into", "out", "up", "down", "over", "under", "then",
    "than", "as", "if", "so", "but", "also", "may", "can", "will", "should", "must",
    "run", "runs", "running", "it's", "its", "a", "run",
}

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
# Stop at a connector word, or two different phrasings of the same target
# ("instead of git diff for X" vs "instead of git diff when Y") never compare equal
# and the contradiction slips through. Two tests exist for exactly that.
INSTEAD_RE = re.compile(
    r"INSTEAD of\s+(.{3,60}?)(?=\s+(?:for|when|if|to|in|on|before|after|as|because|so|and|but)\b|[.,;:—]|$)",
    re.I | re.S,
)
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,}")


def parse_frontmatter(text: str) -> dict:
    m = FM_RE.match(text)
    if not m:
        return {}
    fm: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        if re.match(r"^\s*#", line) or not line.strip():
            continue
        if re.match(r"^[a-zA-Z_]+:", line):
            key, _, val = line.partition(":")
            key = key.strip()
            fm[key] = val.strip()
        elif key:
            fm[key] += " " + line.strip()
    return fm


def tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(text.lower()) if t not in STOP and len(t) > 3}


def discover_roots() -> list[Path]:
    """Every directory that holds a skills/ tree.

    Includes plugin-packaged skills (flushing-dataviz/skills/, cowork-skills/*/skills/)
    because a plugin's skill is reachable by the agent even though it is not in
    agent-tooling/skills/. Missing one of these made the audit report a false
    DANGLING REFERENCE.
    """
    roots: list[Path] = [REPO / "agent-tooling" / "skills"]
    for pat in ("*/skills", "*/*/skills", "cowork-skills/*/skills"):
        roots += sorted(p for p in REPO.glob(pat) if p.is_dir())
    # An out-of-repo marketplace can be named explicitly; never scan it silently,
    # because a private marketplace's skill names must not leak into a public repo's
    # audit output.
    seen: set[Path] = set()
    uniq: list[Path] = []
    for r in roots:
        rp = r.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(rp)
    return uniq


def main() -> int:
    argv = sys.argv[1:]
    roots = [Path(argv[0]).resolve()] if argv else discover_roots()

    skills: dict[str, dict] = {}
    for root in roots:
        for sk in sorted(root.glob("*/SKILL.md")):
            name = sk.parent.name
            try:
                text = sk.read_text(encoding="utf-8")
            except OSError as e:
                sys.stderr.write(f"audit_skills: cannot read {sk}: {e}\n")
                return 2
            fm = parse_frontmatter(text)
            desc = fm.get("description", "")
            skills[name] = {
                "path": sk,
                "description": desc,
                "triggers": tokens(desc),
                "instead": [s.strip().lower() for s in INSTEAD_RE.findall(desc)],
                "body": text,
                "links": set(re.findall(r"`([a-z0-9-]+)`", text)),
            }

    if not skills:
        sys.stderr.write("audit_skills: no skills found\n")
        return 2

    problems: list[str] = []
    names = set(skills)

    # 1. TRIGGER COLLISION — high overlap in discovery vocabulary
    by_name = sorted(skills)
    for i, a in enumerate(by_name):
        for b in by_name[i + 1:]:
            ta, tb = skills[a]["triggers"], skills[b]["triggers"]
            if not ta or not tb:
                continue
            shared = ta & tb
            jac = len(shared) / len(ta | tb)
            if jac >= 0.30 and len(shared) >= 4:
                problems.append(
                    f"TRIGGER COLLISION  {a} <-> {b}  "
                    f"(jaccard={jac:.2f}, {len(shared)} shared: {sorted(shared)[:6]})"
                )

    # 2. DUPLICATE NEGATION — same "use me instead of X"
    seen: dict[str, list[str]] = {}
    for n, s in skills.items():
        for tgt in s["instead"]:
            seen.setdefault(tgt, []).append(n)
    for tgt, owners in seen.items():
        if len(owners) > 1:
            problems.append(f"DUPLICATE NEGATION  {owners} all claim 'INSTEAD of {tgt}'")

    # 3. DANGLING REFERENCE — agent profiles naming skills that do not exist.
    #    This is the check that matters most: a profile that names a non-existent skill
    #    fails at runtime as "the agent ignored the process", not as an error.
    agent_dir = REPO / "agent-tooling" / "adapters" / "opencode" / "agents"
    if agent_dir.is_dir():
        # Names that are legitimate references but are not skills: packages, plugin
        # manifests, config values. Derived from the tree rather than hardcoded, so a
        # new package does not create a false positive.
        non_skill = {
            p.name for p in REPO.iterdir()
            if p.is_dir() and not (p / "SKILL.md").exists()
        }
        non_skill |= {
            "source-collection", "wikimedia-analysis", "personal-skills",
            "webfetch", "source_fetch", "ask", "deny", "allow", "edit", "bash",
            "confirmed", "concluded", "guess", "unverified", "manifest",
        }
        # Directories a path-shaped reference may legitimately point into.
        known_dirs = {"playbooks", "scripts", "policies", "settings", "skills",
                      "agents", "plugins", "git-hooks", "hooks", "adapters",
                      "docs", "references", "assets", "tests"}
        # Filenames a profile may name as something a project WILL have. Their absence
        # from this repo is not a dangling reference.
        prospective = {"uv.lock", "pyproject.toml", "package.json", "opencode.json",
                       "AGENTS.md", "README.md", "SOP.md"}

        def resolves(ref: str) -> bool:
            """Does this backticked reference resolve, or is it a name we cannot judge?

            Deliberately conservative: this should catch a profile naming a skill that
            does not exist, not police every backticked token. An over-eager check gets
            ignored, which is how the previous version became useless.
            """
            if ref in names or ref in non_skill or ref in prospective:
                return True
            if ref.endswith("/"):
                return True                          # a directory reference
            if "/" in ref:
                head, _, tail = ref.partition("/")
                if head not in known_dirs:
                    return True                      # not a repo path, e.g. a command
                if (REPO / ref).exists() or (REPO / "agent-tooling" / ref).exists():
                    return True
                return False                         # known dir, file absent -> dangling
            # A bare name. Only judge it when it looks like a skill name (hyphenated,
            # lowercase) — `curl` and `uv` are commands, not references.
            return not ("-" in ref and ref.islower())

        for af in sorted(agent_dir.glob("*.md")):
            text = af.read_text(encoding="utf-8")
            for ref in re.findall(r"`([a-z][a-z0-9._/-]{2,})`", text):
                if ref.endswith(".py") or ref.endswith(".ts") or ref.endswith(".json"):
                    continue                         # code identifiers, not references
                if not resolves(ref):
                    problems.append(
                        f"DANGLING REFERENCE  {af.name} names `{ref}` which does not resolve")

    # 3b. DANGLING PATH REFERENCE in a skill body — the D15 class: a skill still
    #     pointing at a playbook that was demoted, moved or renamed. Only PATH-shaped
    #     references are judged. Skill bodies are full of legitimate hyphenated prose
    #     (`user-agent`, `crawl-delay`, `all-access`), so applying the profiles'
    #     bare-name rule to them would be a false-positive storm.
    ref_path_re = re.compile(
        r"`((?:agent-tooling/)?(?:playbooks|skills|settings|policies|scripts|agents|hooks|"
        r"git-hooks)/[A-Za-z0-9._/-]+)`")
    for name, s in skills.items():
        for ref in ref_path_re.findall(s["body"]):
            if not ((REPO / "agent-tooling" / ref).exists() or (REPO / ref).exists()):
                problems.append(
                    f"DANGLING REFERENCE  {name}/SKILL.md names `{ref}` which does not resolve")

    # 4. ORPHAN — advisory, not a defect. A leaf skill with no cross-references is
    #    legitimate; it is discovered by description. Reported separately so it never
    #    inflates the failure count.
    referenced: set[str] = set()
    for n, s in skills.items():
        referenced |= {l for l in s["links"] if l in names and l != n}
    orphans = [n for n, s in skills.items()
               if n not in referenced
               and not {l for l in s["links"] if l in names and l != n}]

    print(f"audit_skills: {len(skills)} skills across {len(roots)} root(s)")
    for r in roots:
        print(f"  root: {r.relative_to(REPO) if REPO in r.parents else r}")
    print()
    if orphans:
        print(f"  note: {len(orphans)} skill(s) with no cross-references "
              f"(normal for leaves, just not discoverable by link):")
        for o in sorted(orphans):
            print(f"    - {o}")
        print()
    if problems:
        for p in sorted(problems):
            print(f"  {p}")
        print(f"\n  {len(problems)} problem(s)")
        return 1
    print("  no contradictions found")
    return 0


if __name__ == "__main__":
    sys.exit(main())