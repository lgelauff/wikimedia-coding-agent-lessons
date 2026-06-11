#!/usr/bin/env python3
"""Policy: classify a shell command as a GitHub write that needs gating.

Agent-agnostic decision executable. The fact it judges is a single shell
command string. Consolidates the three divergent GitHub guards that had grown
across repos (global / dp / wiki-polis) into one rule.

  classify_github_op.py "gh pr comment 5 -b hi"   -> prints "ask <reason>", exit 1
  classify_github_op.py "gh repo delete foo"        -> prints "deny <reason>", exit 1
  classify_github_op.py "gh pr view 5"              -> exit 0 (read-only, allow)

Contract: stdout first token is the verdict (ask|deny), rest is a neutral
reason; exit 0 = allow (no verdict). An adapter maps ask/deny onto the host's
permission schema. Reads are always allowed.

Verdicts:
  deny  — catastrophic / irreversible; should essentially never run unprompted
          (gh repo delete/archive, gh release delete).
  ask   — any other GitHub write (push, pr/issue create/comment/review/edit/
          close/reopen/merge, release create/edit, workflow run, gist write,
          gh api with a write method) — requires explicit per-action approval.
"""
import re
import sys

DENY = [
    (r"\bgh repo (delete|archive)\b", "Deletes or archives a GitHub repository — irreversible."),
    (r"\bgh release delete\b", "Deletes a GitHub release — irreversible."),
]
ASK = [
    (r"\bgh api\b.*(-X|--method)\s*(POST|PUT|PATCH|DELETE)", "gh api write (POST/PUT/PATCH/DELETE)"),
    (r"\bgh pr (create|comment|review|merge|close|reopen|edit|ready)\b", "writes/changes a pull request"),
    (r"\bgh issue (create|comment|edit|close|reopen|delete|transfer|pin|lock)\b", "writes/changes an issue"),
    (r"\bgh release (create|edit|upload)\b", "creates/edits a GitHub release"),
    (r"\bgh workflow (run|enable|disable)\b", "triggers/toggles a GitHub Actions workflow"),
    (r"\bgh gist (create|edit|delete)\b", "writes a gist"),
    (r"\bgit push\b", "pushes commits to a remote"),
]


def classify(command: str) -> tuple[str, str] | None:
    """Return (verdict, reason) where verdict is 'deny' or 'ask', else None."""
    c = command or ""
    for pat, why in DENY:
        if re.search(pat, c):
            return ("deny", why)
    for pat, why in ASK:
        if re.search(pat, c):
            return ("ask", f"This command {why} — publishes or modifies content on "
                           "GitHub. Explicit approval required before it runs.")
    return None


def main() -> int:
    command = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    verdict = classify(command)
    if verdict:
        print(f"{verdict[0]} {verdict[1]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
