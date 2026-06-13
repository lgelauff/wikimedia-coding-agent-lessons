#!/usr/bin/env python3
"""SessionStart adapter: warn loudly about unsaved/at-risk git work.

Thin Claude adapter over scripts/git_hygiene.py. On session start it scans the
session's repo for uncommitted changes, untracked files, stashes, unpushed
commits, and dirty linked worktrees, and — if any exist — injects a warning via
SessionStart additionalContext so the assistant surfaces it to you immediately.
Silent when the repo is clean (no noise). Never blocks; fails open.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "scripts"))
from git_hygiene import scan_repo, is_dirty, format_report  # noqa: E402


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        d = {}
    repo = d.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    try:
        r = scan_repo(repo)
    except Exception:
        return 0  # advisory: never break session start
    if not is_dirty(r):
        return 0

    msg = (format_report([r]) +
           "\n\nTell the user about this at-risk git work right now, before "
           "anything else, so nothing is accidentally lost or overwritten.")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
