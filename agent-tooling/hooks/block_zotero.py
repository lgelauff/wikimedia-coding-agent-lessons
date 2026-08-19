#!/usr/bin/env python3
"""
PreToolUse hook: block any access to Zotero files/directories.

Zotero (database and library files) must never be read, written, edited,
or modified by Claude without explicit user permission each time.
"""
import json
import re
import sys

ZOTERO_RE = re.compile(
    r"(?:"
    r"~/Zotero"
    r"|/Users/[^/]+/Zotero"
    r"|zotero\.sqlite"
    r"|Library/Application Support/Zotero"
    r")",
    re.IGNORECASE,
)

try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError, ValueError):
    sys.exit(0)  # fail open for parse errors (not a security-critical guard)

# Bash commands and file-path tools alike: the docstring says Zotero must never
# be read, written, edited, or modified, so a Bash-only guard was a hole.
FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit")

tool_name = d.get("tool_name", "")
tool_input = d.get("tool_input", {}) or {}
if tool_name == "Bash":
    target = str(tool_input.get("command", ""))
elif tool_name in FILE_TOOLS:
    target = " ".join(
        str(tool_input.get(k, "")) for k in ("file_path", "notebook_path", "path"))
else:
    sys.exit(0)

if ZOTERO_RE.search(target):
    sys.stderr.write(
        "\n"
        "🚫 BLOCKED: ZOTERO ACCESS NOT PERMITTED\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Claude attempted to access Zotero files or directories.\n"
        "This requires explicit user permission each time.\n"
        "\n"
        f"Blocked {tool_name}: {target[:200]}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Tell the user what you need from Zotero and ask for\n"
        "explicit permission before retrying.\n"
    )
    print(json.dumps({
        "decision": "block",
        "reason": "Zotero access blocked — requires explicit user permission each time."
    }))
    sys.exit(2)
