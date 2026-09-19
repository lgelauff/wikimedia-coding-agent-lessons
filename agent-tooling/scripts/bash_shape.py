#!/usr/bin/env python3
"""bash_shape.py — reduce a shell command to a secret-free "shape", and record it.

Why this exists: permission prompts are the main friction, and the fix must be driven
by which command *shapes* actually prompt, not by guessing. A shape is the command plus
its subcommand (`git status`, `npm run`, `python3 scope.py`) — never an argument — so a
path, a token, or a commit message can never land in the log.

It also classifies the *real* command against the deployed static ruleset (port of
OpenCode's `Wildcard.match`, `packages/core/src/util/wildcard.ts`) and logs the resulting
action, so the report can rank the shapes that fall through to `ask`.

Usage:
    bash_shape.py "git -C /repo status --short"      -> prints: git status
    bash_shape.py --record "mkdir -p a/b"            -> appends one JSON line to the log
    printf '%s' "$cmd" | bash_shape.py --record -

Log: $BASH_SHAPES_LOG, default ~/agent/logs/bash-shapes.jsonl
Line: {"ts": <epoch-ms>, "shape": "<shape>", "action": "allow|ask|deny|?"}

Contract: never raises, always exits 0. This is instrumentation, and instrumentation
must never break a shell call.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

# Command families whose first following subcommand token is worth recording.
MULTIWORD = {
    "git", "gh", "npm", "yarn", "pnpm", "bun", "cargo", "go", "docker", "kubectl",
    "helm", "aws", "gcloud", "az", "brew", "uv", "pip", "pip3", "conda", "poetry",
    "make", "cmake", "systemctl", "apt", "apt-get", "snap", "terraform", "rustup",
    "gradle", "mvn", "composer", "npx", "pnpx", "ruff", "pytest",
}
# Commands that take a script path first; record the script's basename.
INTERPRETERS = {"python", "python3", "node", "deno", "bun", "ruby", "perl", "bash", "sh", "zsh", "uv"}
# Leading wrappers that are not the command.
PREFIXES = {"sudo", "doas", "time", "env", "nohup", "command", "builtin", "exec"}
BARE_WORD = re.compile(r"^[a-z][a-z0-9_-]*$")
PATHISH = re.compile(r"[./]")
SCRIPTISH = re.compile(r"\.(py|js|mjs|cjs|ts|sh|bash|rb|pl|php|R)$")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SPLIT_OPS = re.compile(r"&&|\|\||;|\|")

DEFAULT_LOG = os.path.expanduser("~/agent/logs/bash-shapes.jsonl")
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "adapters" / "opencode" / "opencode.shared.json"


def _first_segment(command: str) -> str:
    return SPLIT_OPS.split(command or "", maxsplit=1)[0].strip()


def _tokens(segment: str) -> list[str]:
    return [t.strip("'\"") for t in segment.split() if t.strip("'\"")]


def shape(command: str) -> tuple[str, bool]:
    """Return (shape, had_more_args). Never includes an argument value."""
    try:
        toks = _tokens(_first_segment(command))
        i = 0
        while i < len(toks) and (ASSIGN.match(toks[i]) or toks[i] in PREFIXES):
            i += 1
        if i >= len(toks):
            return "?", False
        cmd = os.path.basename(toks[i])
        i += 1
        if cmd in INTERPRETERS:
            j = i
            while j < len(toks) and toks[j].startswith("-"):
                j += 1
            if j < len(toks) and (PATHISH.search(toks[j]) or SCRIPTISH.search(toks[j])):
                return f"{cmd} {os.path.basename(toks[j])}", (j + 1) < len(toks)
            return cmd, i < len(toks)
        if cmd in MULTIWORD:
            j = i
            while j < len(toks):
                if BARE_WORD.match(toks[j]):
                    return f"{cmd} {toks[j]}", (j + 1) < len(toks)
                j += 1
            return cmd, i < len(toks)
        return cmd, i < len(toks)
    except Exception:
        return "?", False


def wildcard_match(value: str, pattern: str) -> bool:
    """Port of OpenCode Wildcard.match: trailing ' *' is OPTIONAL (' .*' -> '( .*)?')."""
    value = value.replace("\\", "/")
    escaped = pattern.replace("\\", "/")
    escaped = re.sub(r"([.+^${}()|\[\]\\])", r"\\\1", escaped)
    escaped = escaped.replace("*", ".*").replace("?", ".")
    if escaped.endswith(" .*"):
        escaped = escaped[:-3] + "( .*)?"
    try:
        return re.match("^" + escaped + "$", value, re.S) is not None
    except re.error:
        return False


def load_bash_rules(config_path: Path) -> list[tuple[str, str]]:
    """Global bash rules, then the build agent's (which merge last and win)."""
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except Exception:
        return []
    cfg = data.get("config", {}) if isinstance(data, dict) else {}
    rules: list[tuple[str, str]] = []

    def add(block) -> None:
        if isinstance(block, dict):
            rules.extend((p, a) for p, a in block.items())

    add(cfg.get("permission", {}).get("bash"))
    add(cfg.get("agent", {}).get("build", {}).get("permission", {}).get("bash"))
    return rules


def evaluate_action(command: str, rules: list[tuple[str, str]]) -> str:
    action = "ask"
    for pattern, act in rules:
        if wildcard_match(command, pattern):
            action = act
    return action


def record(command: str, log_path: str, rules: list[tuple[str, str]]) -> None:
    sh, _ = shape(command)
    entry = {"ts": int(time.time() * 1000), "shape": sh, "action": evaluate_action(command, rules)}
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def main() -> int:
    argv = sys.argv[1:]
    config = Path(os.environ.get("BASH_SHAPES_CONFIG", DEFAULT_CONFIG))
    if argv and argv[0] == "--record":
        rest = argv[1:]
        command = rest[0] if len(rest) == 1 and rest[0] != "-" else (" ".join(rest) if rest and rest != ["-"] else sys.stdin.read())
        log = os.environ.get("BASH_SHAPES_LOG", DEFAULT_LOG)
        try:
            record(command, log, load_bash_rules(config))
        except Exception:
            pass
        return 0
    command = " ".join(argv) if argv else sys.stdin.read()
    print(shape(command)[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
