#!/usr/bin/env python3
"""PostToolUse adapter: warn when WebFetch returns suspiciously little content.

Thin Claude adapter. The decision ("is this content too short to trust?") lives
in the agent-agnostic policy `policies/content_too_short.py`. This file's only
job: read Claude's PostToolUse event, pull out the tool response, ask the policy,
and surface a flag as a warning. Advisory only — fails OPEN (a malformed event
or short content never blocks the tool; the security SSH guard fails closed, this
one fails open, and that asymmetry is intentional).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "policies"))
from content_too_short import too_short  # noqa: E402

try:
    d = json.load(sys.stdin)
except (json.JSONDecodeError, EOFError, ValueError):
    sys.exit(0)  # advisory hook: never crash the tool on a bad event

reason = too_short(str(d.get("tool_response", "")))
if reason:
    print(f"HOOK WARNING: {reason}")
