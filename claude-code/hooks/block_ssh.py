#!/usr/bin/env python3
"""
PreToolUse hook: block any SSH attempt.

SSH should never be initiated by Claude or an agent. This hook catches
ssh, scp, sftp, and rsync-over-ssh invocations and hard-blocks them.
"""
import json
import re
import sys

SSH_RE = re.compile(
    r"(?:^|\s|;|&&|\|)"   # start or command separator
    r"(?:ssh|scp|sftp|rsync\s+.*-e\s+['\"]?ssh|autossh)"
    r"(?:\s|$)",
    re.MULTILINE,
)

try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError, ValueError):
    # Security guard: fail CLOSED. If we can't parse the hook input we can't
    # tell whether this is an SSH attempt, so block rather than allow.
    sys.stderr.write(
        "🚫 BLOCKED: SSH guard could not parse hook input — failing closed.\n"
        "Re-run the command so the guard can inspect it.\n"
    )
    sys.exit(2)

if d.get("tool_name") != "Bash":
    sys.exit(0)

command = d.get("tool_input", {}).get("command", "")
if SSH_RE.search(command):
    sys.stderr.write(
        "\n"
        "🚫 BLOCKED: SSH IS NOT ALLOWED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Claude or an agent attempted to run an SSH command.\n"
        "This is never permitted — SSH must always be initiated\n"
        "manually by the user.\n"
        "\n"
        f"Blocked command: {command[:200]}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Do NOT retry this. Tell the user what you were trying to\n"
        "do and ask them to run the SSH command manually instead.\n"
    )
    sys.exit(2)
