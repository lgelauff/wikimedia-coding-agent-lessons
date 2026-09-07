#!/usr/bin/env python3
"""Policy: does a shell command `cd` somewhere when the tool has a directory flag?

Agent-agnostic decision executable. The fact it judges is a single shell command
string. It exists for a permission reason, not a safety one.

`cd <path> && git ...` is treated by Claude Code as able to execute untrusted
hooks from the target directory, so it is offered with **no "Always allow"** —
only Deny or Allow once. No allowlist entry can ever silence it: it re-prompts
every time, in every session, forever. `git -C <path> ...` does the identical
work and *is* allowlistable, and it doesn't bake a machine-specific path into
the permission rule.

So this is not "that command is unsafe". It is "that spelling of the command
costs the user an approval on every single run, and an equivalent spelling
costs them one, once".

  avoidable_cd.py "cd /r && git grep x"   -> prints rewrite, exit 1 (block)
  avoidable_cd.py "git -C /r grep x"      -> exit 0 (allow)
  echo "cd /r && ./deploy.sh" | avoidable_cd.py  -> exit 0 (no dir flag exists)

Contract: exit 0 = allow, exit 1 = block; on block a neutral human-readable
reason including the suggested rewrite is printed to stdout. An adapter (e.g. a
Claude PreToolUse hook) feeds the command in and translates the exit/reason into
the host's decision format.
"""
import re
import sys

# Tools that accept a directory flag, so a preceding `cd` is avoidable.
# Only tools where the flag is an exact equivalent — no behaviour change.
DIR_FLAG = {
    "git": "git -C {path} {rest}",
    "make": "make -C {path} {rest}",
}

# `cd <path>` followed by `&&` or `;` and then a tool invocation.
# The path may be quoted. Captures: path, separator, remainder.
_CD_CHAIN = re.compile(
    r"""^\s*cd\s+                     # leading cd
        (?P<path>'[^']*'|"[^"]*"|\S+) # the target directory
        \s*(?:&&|;)\s*                # chained, not a bare `cd`
        (?P<rest>.+)$                 # whatever runs there
    """,
    re.VERBOSE | re.DOTALL,
)


def _first_word(s: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9_./-]+)", s)
    return m.group(1).rsplit("/", 1)[-1] if m else ""


def avoidable_cd(command: str) -> str | None:
    """Return a rewrite suggestion if the cd is avoidable, else None."""
    if not command or not command.strip():
        return None

    m = _CD_CHAIN.match(command.strip())
    if not m:
        return None

    path = m.group("path")
    rest = m.group("rest").strip()
    tool = _first_word(rest)

    template = DIR_FLAG.get(tool)
    if not template:
        # cd into a directory to run something with no directory flag
        # (./script.sh, npm, a compiler) is legitimate — leave it alone.
        return None

    # Strip the tool name off the front; the template re-adds it.
    args = re.sub(r"^\s*\S*" + re.escape(tool) + r"\b\s*", "", rest, count=1)

    # More than one command chained after the cd: the later ones may genuinely
    # need the working directory, so don't claim a single clean rewrite.
    multi = re.search(r"(?:&&|;|\|)", args) is not None

    rewrite = template.format(path=path, rest=args).strip()

    reason = (
        f"`cd … && {tool}` cannot be allowlisted. Claude Code treats it as able to "
        f"execute untrusted hooks from the target directory, so it offers no "
        f'"Always allow" — only Deny or Allow once. It will prompt again every '
        f"time, in every session.\n\n"
        f"Use the directory flag instead, which is allowlistable:\n\n"
        f"    {rewrite}\n"
    )
    if multi:
        reason += (
            "\nThis command chains more work after the "
            f"{tool} call. If a later step genuinely needs the working directory, "
            "issue it as a separate tool call rather than re-introducing the cd.\n"
        )
    return reason


def main() -> int:
    command = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    reason = avoidable_cd(command)
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
