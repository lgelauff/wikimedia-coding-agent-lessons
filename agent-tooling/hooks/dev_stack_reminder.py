#!/usr/bin/env python3
"""UserPromptSubmit hook: remind about a still-running dev stack when you sign off.

Generalized from wiki-polis's inline farewell-detector. When the prompt looks
like a goodbye AND a configured dev-stack container is still running, surface a
one-line reminder with the stop command. Config-driven so it's reusable: reads
./.claude/dev-stack.json in the project; if absent, it's a silent no-op. Always
fails open — never blocks a prompt.

  ./.claude/dev-stack.json:
    { "container_filter": "particiapp-docker",
      "stop_command": "docker compose -f ... down (from particiapp-docker dir)" }
"""
import json
import os
import re
import subprocess
import sys

FAREWELL = re.compile(r"\b(bye|good ?night|goodnight|ciao|see you|ttyl|signing off|that's all)\b", re.I)


def should_remind(prompt: str, config: dict | None) -> dict | None:
    """Pure decision: returns the config if a reminder is warranted, else None.
    (Container-running check is done by the caller — this stays testable.)

    Only fires on a *short* prompt that is genuinely a sign-off — otherwise a
    long message that merely contains "see you" or "that's all" would trip it.
    """
    if not config or not config.get("container_filter") or not config.get("stop_command"):
        return None
    p = (prompt or "").strip()
    if len(p) > 60 or not FAREWELL.search(p):   # a real goodbye is brief
        return None
    return config


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return 0

    cfg_path = os.path.join(".claude", "dev-stack.json")
    config = None
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0

    cfg = should_remind(d.get("prompt", ""), config)
    if not cfg:
        return 0

    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", f"name={cfg['container_filter']}", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 0
    if not out:
        return 0

    n = len(out.splitlines())
    print(json.dumps({
        "systemMessage": f"Dev stack: {n} '{cfg['container_filter']}' container(s) still "
                         f"running. Stop with: {cfg['stop_command']}"
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
