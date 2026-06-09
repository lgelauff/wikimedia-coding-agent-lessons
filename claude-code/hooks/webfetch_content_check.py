#!/usr/bin/env python3
"""
PostToolUse hook: warn when WebFetch returns suspiciously little content.

A very short response usually means a redirect, login wall, or error page
rather than the expected resource. Claude should treat it as unverified.
"""
import json
import sys

d = json.load(sys.stdin)
r = str(d.get("tool_response", ""))
if len(r) < 300:
    print(
        "HOOK WARNING: WebFetch returned very little content. Treat as UNVERIFIED. "
        "Do not assume the expected resource exists. Find another way to verify "
        "(git remote, DNS lookup, curl, ask the user) or explicitly flag it as unconfirmed."
    )
