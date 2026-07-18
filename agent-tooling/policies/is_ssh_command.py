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

# quoted spans (echo/prose text) — stripped before the plain check so an `ssh`
# merely *mentioned* in a string doesn't trip the gate (the false positive a
# security+AI panel flagged). Real command-position ssh stays outside quotes.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")

# plain ssh-family at a command position. Keep bare whitespace in the leading
# class so `sudo ssh` / `time ssh` are still caught (dropping it would open a
# bypass — worse than the cosmetic FP). Run on QUOTE-STRIPPED text.
SSH_PLAIN = re.compile(
    r"(?:^|[\s;&|`(])(?:ssh|scp|sftp|autossh)(?:\s|$)", re.MULTILINE)

# rsync-over-ssh: matched on the ORIGINAL command, because the `ssh` in
# `-e "ssh"` is usually quoted (so quote-stripping would miss it).
RSYNC_SSH = re.compile(r"\brsync\b.*-e\s+['\"]?ssh", re.MULTILINE)


def is_ssh(command: str) -> str | None:
    """Return a reason string if the command invokes SSH, else None."""
    cmd = command or ""
    if SSH_PLAIN.search(_QUOTED.sub(" ", cmd)) or RSYNC_SSH.search(cmd):
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
