#!/usr/bin/env python3
"""PreToolUse adapter: gate GitHub write operations.

Thin Claude adapter over policies/classify_github_op.py. Reads Claude's
PreToolUse event, pulls the Bash command, asks the policy, and emits the modern
permission-decision schema: 'ask' (explicit approval) for writes, 'deny' for
catastrophic ops. Reads pass through untouched. Fails OPEN on a bad event.

(Replaces the old github_write_permission.sh, which read the command from the
wrong JSON path — top-level `command` instead of `tool_input.command` — so it
never actually fired.)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "policies"))
from classify_github_op import classify  # noqa: E402


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return 0  # advisory gate: don't crash the tool on a bad event

    if d.get("tool_name") != "Bash":
        return 0
    command = d.get("tool_input", {}).get("command", "")
    verdict = classify(command)
    if not verdict:
        return 0

    decision, reason = verdict  # ('ask'|'deny', reason)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
