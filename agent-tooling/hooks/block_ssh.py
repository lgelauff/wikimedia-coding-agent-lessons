#!/usr/bin/env python3
"""PreToolUse adapter: block any SSH attempt.

Thin Claude adapter. The decision ("is this command an SSH invocation?") lives
in the agent-agnostic policy `policies/is_ssh_command.py`. This file's only job:
read Claude's PreToolUse event, pull out the Bash command, ask the policy, and
translate a block into Claude's format (stderr + exit 2). Fails CLOSED if the
event can't be parsed — an unparseable event might be hiding an SSH command.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "policies"))
from is_ssh_command import is_ssh  # noqa: E402


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.stderr.write(
            "🚫 BLOCKED: SSH guard could not parse hook input — failing closed.\n"
            "Re-run the command so the guard can inspect it.\n"
        )
        return 2

    if d.get("tool_name") != "Bash":
        return 0

    command = d.get("tool_input", {}).get("command", "")
    reason = is_ssh(command)
    if reason:
        sys.stderr.write(
            "\n"
            "🚫 BLOCKED: SSH IS NOT ALLOWED\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{reason}\n"
            "\n"
            f"Blocked command: {command[:200]}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "\n"
            "Do NOT retry this. Tell the user what you were trying to\n"
            "do and ask them to run the SSH command manually instead.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
