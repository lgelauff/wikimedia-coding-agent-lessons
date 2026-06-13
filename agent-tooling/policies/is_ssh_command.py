#!/usr/bin/env python3
"""Policy: does a shell command invoke SSH / a remote shell?

Agent-agnostic decision executable — knows nothing about any agent's event
format. The fact it judges is a single shell command string.

  is_ssh_command.py "ssh host uptime"     -> prints reason, exit 1 (block)
  echo "ls -la" | is_ssh_command.py        -> exit 0 (allow)

Contract: exit 0 = allow, exit 1 = block; on block, a neutral human-readable
reason is printed to stdout. An adapter (e.g. a Claude PreToolUse hook) feeds
the command in and translates the exit/reason into the host's decision format.
"""
import re
import sys

# start-or-separator, then an ssh-family invocation, then arg-or-end.
# The leading class must include every shell metachar that can begin a command:
# whitespace, ; & |, command-substitution `$(`/backtick, and a `(` subshell — else
# `$(ssh …)`, `` `ssh …` ``, `(ssh …)`, `cmd & ssh` slip past the gate.
SSH_RE = re.compile(
    r"(?:^|[\s;&|`(])"
    r"(?:ssh|scp|sftp|rsync\s+.*-e\s+['\"]?ssh|autossh)"
    r"(?:\s|$)",
    re.MULTILINE,
)


def is_ssh(command: str) -> str | None:
    """Return a reason string if the command invokes SSH, else None."""
    if SSH_RE.search(command or ""):
        return (
            "Command invokes SSH / a remote shell (ssh, scp, sftp, rsync-over-ssh, "
            "autossh). SSH must be initiated manually by the user, never by an "
            "automated agent. Present the command for the user to run instead."
        )
    return None


def main() -> int:
    command = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    reason = is_ssh(command)
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
