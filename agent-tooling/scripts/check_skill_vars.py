#!/usr/bin/env python3
"""Guard: variable references inside SKILL.md must resolve at run time.

An agent reading a SKILL.md copies its commands verbatim. If a skill references a
variable that nothing injects (`$SKILL_DIR` was referenced by four skills and set
by nothing), every command using it expands to an empty segment — or to a path
relative to the *consuming* repo — and fails. The failure is silent: the agent
reports a command that "did not work" rather than a missing definition.

This guard is deterministic and needs no execution: it extracts every variable
reference from every SKILL.md and fails on any that is not known-injected.

Contract: exit 0 = clean, exit 1 = unknown variable found, exit 2 = the scan could
not complete (no skills found, unreadable file). Mirrors git_hygiene.py's 2 =
"unverified, not clean" convention: never report clean on a 2.

Two traps this deliberately handles:

  * A variable *about* a variable. `session-close/SKILL.md` discusses
    ${AGENT_TOOLING_ROOT} in prose while also defining it. Discussing is not using,
    so prose mentions are exempt — but "documentation defines X, therefore X is
    known" is not, because the text claiming something is injected is exactly what
    was wrong the last time.
  * Path-shaped names. Rather than enumerate every legitimate shell variable,
    this flags two classes: names that are unambiguously paths (ending _DIR,
    _ROOT, _PATH) and any reference to a variable on the known-bad list.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- configuration

# Injected by the host adapters. AGENT_TOOLING_ROOT is set by the OpenCode
# plugin's shell.env hook and from CLAUDE_PLUGIN_ROOT in Claude Code. Kept here
# as documentation of the contract; the check below does not need it as an
# allowlist because the path-shaped heuristic is the real test.
KNOWN_INJECTED = {
    "AGENT_TOOLING_ROOT",
}

# Never acceptable. These are host-specific or undefined-by-design; their presence
# means a skill was not migrated or a definition was assumed that does not exist.
KNOWN_BAD = {
    "SKILL_DIR",           # assigned nowhere in this repo (verified 2026-09-17)
    "CLAUDE_PLUGIN_ROOT",  # host-specific; use AGENT_TOOLING_ROOT
}

# A path-shaped name must be injected or it will not resolve. Case-insensitive so
# `${foo_path}` is caught, not just `${FOO_PATH}`.
PATH_SHAPED = re.compile(r"_DIR$|_ROOT$|_PATH$", re.IGNORECASE)

# ${VAR} and $VAR. Braced form first so the bare-form match does not eat the
# leading brace. Names are shell-identifier shaped.
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
REPO = DEFAULT_SKILLS_DIR.parent.parent


def discover_roots() -> list[Path]:
    """Every directory that holds a skills/ tree.

    Scanning only agent-tooling/skills missed the plugin-packaged skills in
    claude-code/skills and cowork-skills/*/skills, so a variable bug in one of those
    would never be caught (review: "scans 1 of 4 skill roots").
    """
    roots: list[Path] = [DEFAULT_SKILLS_DIR]
    for pat in ("*/skills", "*/*/skills", "cowork-skills/*/skills"):
        roots += sorted(p for p in REPO.glob(pat) if p.is_dir())
    seen: set[Path] = set()
    uniq: list[Path] = []
    for r in roots:
        rp = r.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(rp)
    return uniq


def scan(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, variable_name) for every reference in one file."""
    found: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for braced, bare in VAR_RE.findall(line):
            found.append((i, braced or bare))
    return found


def is_bad(name: str) -> str | None:
    """Return a reason string when the variable must not appear, else None."""
    if name in KNOWN_BAD:
        if name == "SKILL_DIR":
            return "not defined anywhere — nothing injects this"
        return "host-specific — use ${AGENT_TOOLING_ROOT}"
    if PATH_SHAPED.search(name) and name not in KNOWN_INJECTED:
        return "path-shaped and not known-injected"
    return None


def main(argv: list[str]) -> int:
    argv = argv[1:]
    roots = [Path(a).resolve() for a in argv] if argv else discover_roots()

    skills: list[Path] = []
    for root in roots:
        if not root.is_dir():
            sys.stderr.write(f"check_skill_vars: no such directory: {root}\n")
            return 2
        try:
            skills += sorted(root.glob("*/SKILL.md"))
        except OSError as exc:
            sys.stderr.write(f"check_skill_vars: cannot scan {root}: {exc}\n")
            return 2

    if not skills:
        sys.stderr.write(f"check_skill_vars: no SKILL.md found under {roots}\n")
        return 2  # unverified, not clean

    violations: list[tuple[Path, int, str, str]] = []
    for path in skills:
        try:
            refs = scan(path)
        except OSError as exc:
            sys.stderr.write(f"check_skill_vars: cannot read {path}: {exc}\n")
            return 2
        for line, name in refs:
            reason = is_bad(name)
            if reason:
                violations.append((path, line, name, reason))

    if violations:
        for path, line, name, reason in violations:
            sys.stderr.write(f"{path.parent.name}/SKILL.md:{line}: ${name} — {reason}\n")
        sys.stderr.write(
            f"\ncheck_skill_vars: {len(violations)} unresolved variable reference(s) "
            f"across {len({v[0] for v in violations})} skill(s).\n"
            "Inject the variable in the host adapter, or use "
            "${AGENT_TOOLING_ROOT} for anything inside the plugin.\n"
        )
        return 1

    print(f"check_skill_vars: OK — {len(skills)} skills across {len(roots)} root(s), "
          "all variable references resolvable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
