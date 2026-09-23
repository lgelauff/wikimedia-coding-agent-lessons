#!/usr/bin/env python3
"""Policy: does a shell command invoke SSH / a remote shell?

Agent-agnostic decision executable — knows nothing about any agent's event
format. The fact it judges is a single shell command string.

  is_ssh_command.py "ssh host uptime"     -> prints reason, exit 1 (block)
  echo "ls -la" | is_ssh_command.py        -> exit 0 (allow)

Contract: exit 0 = allow, exit 1 = block; on block, a neutral human-readable
reason is printed to stdout. An adapter (e.g. a Claude PreToolUse hook) feeds
the command in and translates the exit/reason into the host's decision format.

Matching rule (revised 2026-09-23): ssh is matched as the COMMAND — the head
token of a pipeline segment, after any wrapper words — never as a substring.
Writing *about* ssh (a runbook, a grep pattern, a heredoc) is not running it,
and a guard that blocks documentation teaches agents to route around the guard.
Field false positives that drove this: a heredoc editing a runbook containing
ssh instructions for the human; a `grep -E 'start|ssh |tmux'` pattern; the
policy's own unit tests.
"""
import re
import sys

# Spans that are data, not command position: quoted strings and heredoc bodies.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_HEREDOC = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$",
    re.MULTILINE | re.DOTALL,
)

# Segment separators: a new command can start after any of these.
_SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|[;|&\n(){}`]|\$\()")

SSH_BINARIES = {"ssh", "scp", "sftp", "autossh", "slogin"}

# Wrapper words that precede the real command without being it. `sudo ssh …`
# must still be caught, so these are skipped rather than treated as the head.
_WRAPPERS = {
    "sudo", "doas", "env", "time", "nohup", "command", "exec", "builtin",
    "nice", "ionice", "stdbuf", "setsid", "xargs", "timeout", "caffeinate",
    "script", "watch", "eval",
}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Flags belonging to a wrapper (`timeout -k 5`, `env -i`) — skipped with it.
_FLAGISH = re.compile(r"^-")
# A bare numeric/duration argument to a wrapper (`timeout 30`, `nice 10`).
_WRAPPER_ARG = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")

# rsync-over-ssh: matched on the ORIGINAL text, because the `ssh` in
# `-e "ssh"` is usually quoted (so quote-stripping would miss it).
RSYNC_SSH = re.compile(r"\brsync\b[^\n]*-e\s+['\"]?ssh")

REASON = (
    "Command invokes SSH / a remote shell (ssh, scp, sftp, rsync-over-ssh, "
    "autossh). SSH must be initiated manually by the user, never by an "
    "automated agent. Present the command for the user to run instead."
)


def _head_is_ssh(segment: str) -> bool:
    """True when the first real word of this pipeline segment is an ssh binary."""
    seen_wrapper = False
    for token in segment.split():
        base = token.rsplit("/", 1)[-1]          # /usr/bin/ssh -> ssh
        if _ASSIGNMENT.match(token) or _FLAGISH.match(token):
            continue                             # FOO=bar / -k 5 before the command
        if base in _WRAPPERS:
            seen_wrapper = True
            continue                             # sudo, env, time, …
        if seen_wrapper and _WRAPPER_ARG.match(token):
            continue                             # `timeout -k 5 30 ssh …`
        return base in SSH_BINARIES
    return False


def is_ssh(command: str) -> str | None:
    """Return a reason string if the command invokes SSH, else None."""
    cmd = command or ""
    if RSYNC_SSH.search(cmd):
        return REASON
    # Heredoc bodies and quoted strings are data: strip before looking for a
    # command position. Heredocs first — their bodies may contain stray quotes.
    stripped = _QUOTED.sub(" ", _HEREDOC.sub(" ", cmd))
    for segment in _SEGMENT_SPLIT.split(stripped):
        if _head_is_ssh(segment):
            return REASON
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
