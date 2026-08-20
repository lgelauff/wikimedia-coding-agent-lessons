#!/usr/bin/env python3
"""check_registration.py — keep the READMEs and the tree honest about each other.

Three drift bugs were live in this repo at once, all of the same shape and none
catchable by a test suite:

  - README advertised a `deep-research` skill that did not exist,
  - `source-connectors` was added and never mentioned in any README,
  - `latex-change-review` likewise.

A skill nobody documents is a skill nobody finds; a documented skill that does
not exist is a promise the repo cannot keep. This checks both directions.

Checks
  1. every skill directory on disk is named in at least one README
  2. every relative markdown link in a README resolves to a real path
  3. every backticked name on a line mentioning "skill" exists on disk
     (the `deep-research` class — advertised in prose, never linked)

Usage:
    python3 check_registration.py            # repo root inferred from this file
    python3 check_registration.py --root DIR
    python3 check_registration.py --quiet    # only failures

Exit: 0 clean, 1 drift found, 2 usage error.
"""
import argparse
import os
import re
import sys

SKILL_GLOBS = ("agent-tooling/skills", "cowork-skills", "flushing-dataviz")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")
# Only the shapes that actually advertise a skill: "Skill: `x`" or "`x` skill".
# A looser rule (any backticked name on a line mentioning "skill") fires on
# playbook names and prose, which trains people to ignore the check.
PHANTOM_RE = re.compile(
    r"[Ss]kills?:\s*`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`"
    r"|`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`\s+skill\b")
# Skills that ship with other plugins; naming them is correct, not drift.
EXTERNAL_SKILLS = {"skill-creator"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "worktrees", ".pytest_cache"}


def find_skills(root):
    """Return {skill_name: path} for every SKILL.md in the tree."""
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "SKILL.md" in files:
            out[os.path.basename(base)] = os.path.relpath(base, root)
    return out


def find_readmes(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower() in ("readme.md", "todo.md") or f == "conventions.md":
                out.append(os.path.join(base, f))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--root", default=os.path.abspath(os.path.join(here, "..", "..")))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    root = a.root
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    skills = find_skills(root)
    readmes = find_readmes(root)
    if not skills:
        print(f"no SKILL.md found under {root} — wrong --root?", file=sys.stderr)
        return 2

    blobs = {}
    for r in readmes:
        try:
            blobs[r] = open(r, encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    joined = "\n".join(blobs.values())

    problems = []

    # 1. skill on disk, absent from every README
    for name, path in sorted(skills.items()):
        if name not in joined:
            problems.append(f"UNREGISTERED  skill '{name}' ({path}) is named in no README")

    # 2. broken relative links
    for r, text in blobs.items():
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(r), target))
            if not os.path.exists(resolved):
                problems.append(
                    f"BROKEN LINK   {os.path.relpath(r, root)} -> {target}")

    # 3. a backticked hyphenated name on a "skill" line that is not on disk.
    # TODO.md is exempt: naming things that do not exist yet is what a backlog is for.
    for r, text in blobs.items():
        if os.path.basename(r).lower() == "todo.md":
            continue
        for line in text.splitlines():
            for grp_colon, grp_trailing in PHANTOM_RE.findall(line):
                tok = grp_colon or grp_trailing
                if tok in skills or tok in EXTERNAL_SKILLS:
                    continue
                # a real file or directory of that name is not a phantom skill
                if os.path.exists(os.path.join(root, tok)):
                    continue
                problems.append(
                    f"PHANTOM       {os.path.relpath(r, root)} names skill "
                    f"'{tok}' which does not exist")

    problems = sorted(set(problems))
    if problems:
        print(f"{len(problems)} registration problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1

    if not a.quiet:
        print(f"registration clean — {len(skills)} skills, {len(blobs)} docs checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
