#!/usr/bin/env python3
"""Guard: no allow rule in a Claude Code settings file may permit arbitrary code.

AGENTS.md: "Never allowlist arbitrary code execution. Not `python:*`, not `npx *`,
not `uv run`, not `make *`, not `docker run`, not `ssh`, not `sudo`. Exact
invocations or bundled script paths only." On 2026-11-02 a setup review found
`Bash(python3 -c ' *)`, `Bash(gh auth *)` and `Bash(git clone *)` in the main
checkout's settings.local.json. They had accumulated from one-off approvals, sat
beside that rule, and nothing noticed. With the first one, a single prompt-free
`python3 -c '...'` could open a socket to any host past every hook.

This guard reads `permissions.allow` in each given settings file and flags a
`Bash(...)` rule when:
  * it is the bare tool (`Bash`, `Bash(*)`), which allows everything;
  * its command starts with an interpreter or a runner (python, node, bash, npx,
    uv, make, docker run, env, xargs, ...) and the rule contains a wildcard;
  * it allows ssh, scp or sudo at all;
  * it is one of the named high-risk wildcards (`git clone *`, `gh auth *`,
    `gh api *`, `curl *`, `wget *`).

Exact invocations such as `python3 -m pytest agent-tooling/policies/tests/ -q` or
`python3 /abs/path/script.py --check` pass: approving exact text is the
sanctioned route.

Usage: audit_allowlist.py [SETTINGS.json ...]
  With no arguments it audits <repo>/.claude/settings.json and
  <repo>/.claude/settings.local.json (missing files are skipped, but at least one
  must exist).

Contract: exit 0 = clean, exit 1 = risky rule found (each printed with a reason),
exit 2 = the audit could not complete (no file found, unreadable or invalid JSON,
no permissions block). Never report clean on a 2.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_FILES = [REPO / ".claude" / "settings.json", REPO / ".claude" / "settings.local.json"]

# A wildcard after any of these runs code the rule text never shows.
INTERPRETERS = {
    "python", "python2", "python3", "pypy", "pypy3", "node", "deno", "bun", "ruby",
    "perl", "php", "lua", "Rscript", "osascript", "bash", "sh", "zsh", "fish", "dash",
    "ksh", "tclsh", "julia",
}
RUNNERS = {
    "npx", "uvx", "pipx", "uv", "make", "gmake", "eval", "exec", "xargs", "env",
    "nohup", "time", "timeout", "caffeinate", "nice", "watch", "parallel", "find",
    "awk", "gawk",
}
# Multi-word runners: the head must match these words exactly.
RUNNER_PHRASES = [("docker", "run"), ("docker", "exec"), ("podman", "run"), ("podman", "exec")]
NEVER = {"ssh", "scp", "sftp", "sudo", "su", "doas"}
# High-risk wildcards by exact rule text (prefix before the first wildcard).
RISKY_WILDCARDS = {
    "git clone": "fetches and checks out arbitrary repositories (hooks, filters, LFS)",
    "gh auth": "can switch or export GitHub credentials",
    "gh api": "can POST to any GitHub endpoint, past the GitHub-write gate",
    "curl": "fetches any host, past the WebFetch registry gate",
    "wget": "fetches any host, past the WebFetch registry gate",
}

BASH_RULE = re.compile(r"^Bash(?:\((?P<inner>.*)\))?$", re.S)
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")


def _head_words(command: str) -> list[str]:
    words = command.strip().split()
    while words and ENV_ASSIGN.match(words[0]):  # FOO=bar python3 ...
        words.pop(0)
    if words:
        words[0] = words[0].rsplit("/", 1)[-1]  # /usr/bin/python3 -> python3
    return words


def _base(word: str) -> str:
    # python3.12 -> python3 ; python3:* -> python3
    word = word.split(":", 1)[0]
    return re.sub(r"(\d)\.\d+$", r"\1", word)


def verdict(rule: str) -> str | None:
    """Return a reason if the allow rule permits arbitrary code, else None."""
    m = BASH_RULE.match(rule.strip())
    if not m:
        return None  # not a Bash rule (Read, Edit, WebFetch, mcp__...)
    inner = m.group("inner")
    if inner is None or inner.strip() in {"", "*", ":*"}:
        return "bare Bash allow: every command runs without asking"
    wildcard = "*" in inner
    words = _head_words(inner)
    if not words:
        return None
    head = _base(words[0])
    if head in NEVER:
        return f"allows {head}, which AGENTS.md forbids allowlisting"
    if wildcard and head in INTERPRETERS:
        return f"wildcard after interpreter {head!r}: runs code the rule never shows"
    if wildcard and head in RUNNERS:
        return f"wildcard after runner {head!r}: runs any command it is given"
    if wildcard and len(words) >= 2:
        for a, b in RUNNER_PHRASES:
            if head == a and words[1] == b:
                return f"wildcard after {a} {b}: runs arbitrary code in a container"
    if wildcard:
        prefix = inner.split("*", 1)[0].strip().rstrip(":")
        if prefix in RISKY_WILDCARDS:
            return f"`{prefix} *`: {RISKY_WILDCARDS[prefix]}"
    return None


def audit(path: Path) -> tuple[list[str], str | None]:
    """Return (findings, error). error is set when the file cannot be audited."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"{path}: cannot read as JSON ({exc})"
    perms = data.get("permissions") if isinstance(data, dict) else None
    if not isinstance(perms, dict):
        return [], f"{path}: no permissions block"
    allow = perms.get("allow", [])
    if not isinstance(allow, list):
        return [], f"{path}: permissions.allow is not a list"
    findings = []
    for i, rule in enumerate(allow):
        if not isinstance(rule, str):
            continue
        reason = verdict(rule)
        if reason:
            shown = rule if len(rule) <= 120 else rule[:117] + "..."
            findings.append(f"{path} allow[{i}] {shown}\n    -> {reason}")
    return findings, None


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] if argv else [p for p in DEFAULT_FILES if p.exists()]
    if not files:
        print("audit_allowlist: no settings file found; NOT verified", file=sys.stderr)
        return 2
    findings, errors = [], []
    for f in files:
        got, err = audit(f)
        findings += got
        if err:
            errors.append(err)
    for line in findings:
        print(line)
    for err in errors:
        print(f"audit_allowlist: {err}", file=sys.stderr)
    if errors:
        print("audit_allowlist: audit incomplete; NOT verified clean", file=sys.stderr)
        return 2
    if findings:
        print(f"audit_allowlist: {len(findings)} risky allow rule(s) in {len(files)} file(s)")
        return 1
    print(f"audit_allowlist: clean ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
