#!/usr/bin/env python3
"""PostToolUse hook: warn when WebFetch returns suspiciously little content.

A very short response usually means a redirect, login wall, or error page
rather than the expected resource — so flag it as UNVERIFIED. This is a small
self-contained heuristic, not a reusable policy. Advisory only: fails OPEN (a
malformed event or short content never blocks the tool).
"""
import json
import sys

MIN_CHARS = 300

try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError, ValueError):
    sys.exit(0)  # advisory hook: never crash the tool on a bad event

n = len(str(d.get("tool_response", "")))
if n < MIN_CHARS:
    print(
        f"HOOK WARNING: WebFetch returned very little content ({n} chars). Likely a "
        "redirect, login wall, or error page rather than the expected resource. "
        "Treat as UNVERIFIED; verify another way (git remote, DNS, curl, ask the "
        "user) before relying on it."
    )
