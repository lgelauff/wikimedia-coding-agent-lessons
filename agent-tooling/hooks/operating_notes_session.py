#!/usr/bin/env python3
"""SessionStart adapter: put the operating notes into every Claude session.

The notes (agent-tooling/OPERATING-NOTES.md) are working habits shared by every session on every
machine the plugin reaches: batch permission requests, report to the coordinator only what it
needs, label claims. OpenCode loads the same file through its `instructions` setting, so both
harnesses read one source.

They are injected on every session start, so they cost tokens every time: the file is capped
at MAX_BYTES, and anything larger is not injected (a notice is, so the cap can't fail silently).
Fails open: a missing file or any error leaves session start untouched.
"""
from __future__ import annotations

import json
import os
import sys

NOTES = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "OPERATING-NOTES.md")
MAX_BYTES = 4000


def context(path: str = NOTES) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    if len(text.encode("utf-8")) > MAX_BYTES:
        return (f"(operating notes not injected: {os.path.basename(path)} exceeds {MAX_BYTES} bytes; "
                "tell the sessions coordinator it needs trimming)")
    return text.strip() or None


def main() -> int:
    try:
        msg = context()
    except Exception:
        return 0
    if msg:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
