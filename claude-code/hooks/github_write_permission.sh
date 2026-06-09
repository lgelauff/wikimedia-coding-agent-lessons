#!/usr/bin/env bash
# PreToolUse hook: block GitHub write operations (POST/PATCH/DELETE) until approved.
# Covers: gh api -X POST/PATCH/DELETE, gh pr review, gh pr comment,
#         gh pr merge, gh pr close, gh issue comment, gh issue close/reopen.

set -euo pipefail

INPUT=$(cat)

COMMAND=$(printf '%s' "$INPUT" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null) || COMMAND=""

# Only care about gh commands
if ! printf '%s' "$COMMAND" | grep -qE '^\s*gh '; then
    exit 0
fi

# Detect write operations
IS_WRITE=0

# gh api with explicit write method
if printf '%s' "$COMMAND" | grep -qE 'gh api' && \
   printf '%s' "$COMMAND" | grep -qE '(-X|--method)\s*(POST|PATCH|PUT|DELETE)'; then
    IS_WRITE=1
fi

# gh pr / gh issue write subcommands
if printf '%s' "$COMMAND" | grep -qE 'gh (pr|issue) (review|comment|merge|close|reopen|edit|create)'; then
    IS_WRITE=1
fi

# gh release create
if printf '%s' "$COMMAND" | grep -qE 'gh release (create|delete|edit)'; then
    IS_WRITE=1
fi

if [ "$IS_WRITE" -eq 0 ]; then
    exit 0
fi

# Block and ask for approval
cat <<EOF
╔══════════════════════════════════════════════════════╗
║       GitHub Write Operation — Approval Required     ║
╠══════════════════════════════════════════════════════╣
║  Command : $(printf '%s' "$COMMAND" | cut -c1-50)
╠══════════════════════════════════════════════════════╣
║  This will write to GitHub (post, comment, merge,    ║
║  close, or modify). Explicit approval is required.   ║
║                                                      ║
║  Tell me: "yes, post it" / "go ahead" / "approved"  ║
╚══════════════════════════════════════════════════════╝
EOF
exit 2
