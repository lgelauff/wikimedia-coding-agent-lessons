#!/usr/bin/env python3
"""check_skill_vars.py — a bundled path in a skill body must actually resolve.

`check_registration.py` verifies that *named things exist*. Nothing verified that
*paths inside skill bodies resolve*, and a live bug sat in the repo because of it:

  `$SKILL_DIR` was referenced by 4 skills in 7 script invocations and assigned
  nowhere. Unset, `python3 "$SKILL_DIR/../../scripts/capture.py"` expands to
  `python3 "/../../scripts/capture.py"` — an absolute path into `/`. Seven calls
  that could not work, in a repo whose tests all passed.

Claude Code substitutes `${CLAUDE_PLUGIN_ROOT}` into a SKILL.md *before the model
reads it*, so that form arrives carrying an absolute path. Nothing substitutes
`$SKILL_DIR`. That asymmetry is the whole bug, and it is invisible to grep.

## It judges usage, never mention

Every rule here is POSITIONAL: a name is only judged where it leads a bundled
path. `session-close/SKILL.md` legitimately discusses `$SKILL_DIR` in prose to
explain why it is wrong, and documentation that names an anti-pattern must not
trip the guard that enforces it. An earlier draft used name-matched allowlists
(`$HOME`, `$TOKEN`, OData's `/$metadata`…) and flagged ordinary shell examples as
bugs — a guard that cries wolf gets bypassed, and a bypassed guard still carries
the claim of coverage.

Checks
  1. a variable leading a bundled path must be one the harness injects
  2. a bare `agent-tooling/...` path inside a shell block — resolves against the
     *consuming* repo, where that directory does not exist
  3. the target behind `${CLAUDE_PLUGIN_ROOT}/...` must exist on disk
  4. at least one SKILL.md was found, so a layout change cannot pass vacuously

Usage:
    python3 check_skill_vars.py            # repo root inferred from this file
    python3 check_skill_vars.py --root DIR
    python3 check_skill_vars.py --quiet    # only failures

Exit: 0 clean, 1 problems found, 2 usage error.
"""
import argparse
import os
import re
import sys

# Skills sit at differing depths: agent-tooling/skills/<n>/, but also
# cowork-skills/<bundle>/skills/<n>/ and flushing-dataviz/skills/<n>/. Walk rather
# than assume a depth — an earlier draft silently checked 11 of 16.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "worktrees",
             ".pytest_cache"}

# Substituted into the skill body by Claude Code before the model reads it.
INJECTED = {"CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA"}

# Names that are wrong specifically as a bundled-path root, with the reason.
RETIRED = {
    "SKILL_DIR": "set by nothing in any harness; expands to a path into /",
    "AGENT_TOOLING_ROOT": "not substituted into skill bodies; OpenCode-side only",
}

# The bug class: a variable used as the root of a bundled path.
BUNDLED_RE = re.compile(
    r"\$\{?(\w+)\}?/(?:\.\./)*(?:scripts|playbooks|policies|hooks|skills)/")

# A bundled path with no root at all, e.g. `python3 agent-tooling/scripts/x.py`.
# Only meaningful inside a shell block — prose may name the path legitimately.
BARE_RE = re.compile(r"(?<![\w/`])agent-tooling/(?:scripts|playbooks|policies)/\S+")

# What ${CLAUDE_PLUGIN_ROOT} points at, so a target can be resolved on disk.
PLUGIN_ROOT_REL = "agent-tooling"
TARGET_RE = re.compile(
    r"\$\{?CLAUDE_PLUGIN_ROOT\}?/((?:scripts|playbooks|policies|hooks|skills)/[\w./-]+)")

FENCE_RE = re.compile(r"^\s*```")


def find_skill_files(root):
    """Every SKILL.md, plus the reference files a skill loads alongside it."""
    out = []
    for base, dirs, files in os.walk(root, followlinks=True):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if "SKILL.md" in files:
            out.append(os.path.join(base, "SKILL.md"))
            ref = os.path.join(base, "references")
            if os.path.isdir(ref):
                for rb, rd, rf in os.walk(ref, followlinks=True):
                    rd[:] = [d for d in rd if d not in SKIP_DIRS]
                    out.extend(os.path.join(rb, f) for f in rf
                               if f.endswith((".md", ".py", ".js", ".sh")))
    return sorted(out)


def check_file(path, root):
    problems = []
    rel = os.path.relpath(path, root)
    in_shell_block = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            if FENCE_RE.match(line):
                in_shell_block = not in_shell_block
                continue

            for m in BUNDLED_RE.finditer(line):
                name = m.group(1)
                if name in INJECTED:
                    continue
                why = RETIRED.get(name, "no harness injects it")
                problems.append(
                    f"UNRESOLVED  {rel}:{lineno} ${name} roots a bundled path — {why}; "
                    f"use ${{CLAUDE_PLUGIN_ROOT}}")

            if in_shell_block:
                for m in BARE_RE.finditer(line):
                    problems.append(
                        f"BARE PATH   {rel}:{lineno} '{m.group(0)}' resolves against the "
                        f"consuming repo, which has no agent-tooling/; "
                        f"use ${{CLAUDE_PLUGIN_ROOT}}")

            for m in TARGET_RE.finditer(line):
                target = os.path.join(root, PLUGIN_ROOT_REL, m.group(1))
                if not os.path.exists(target):
                    problems.append(
                        f"MISSING     {rel}:{lineno} ${{CLAUDE_PLUGIN_ROOT}}/{m.group(1)} "
                        f"does not exist")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    files = find_skill_files(root)
    skills = [f for f in files if os.path.basename(f) == "SKILL.md"]
    if not skills:
        # Fail closed: a layout change that hides every skill must not read as clean.
        print(f"no SKILL.md found under {root} — refusing to report clean")
        return 1

    problems = []
    for f in files:
        problems.extend(check_file(f, root))

    problems = sorted(set(problems), key=lambda p: p.split()[1])
    if problems:
        print(f"{len(problems)} skill path problem(s):")
        for p in problems:
            print(f"  {p}")
        return 1

    if not a.quiet:
        print(f"skill paths clean — {len(skills)} SKILL.md "
              f"(+{len(files) - len(skills)} reference files) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
