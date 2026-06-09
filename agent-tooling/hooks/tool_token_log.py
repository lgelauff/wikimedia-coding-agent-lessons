#!/usr/bin/env python3
"""
PostToolUse hook: append an estimated token-cost line per tool call.

A hook does NOT receive the conversation's real token accounting — only the
tool name, input, and response. So this logs a *proxy*: the byte size of the
call's input + output and an estimate (~chars/4 ≈ tokens). It's not exact model
billing, but it reliably surfaces which tools/skills push the most into context
(the real driver of memory + cost). For exact numbers, parse the transcript's
`usage` fields instead.

Never blocks: always exits 0. Appends JSONL to:
  $TOOL_TOKEN_LOG  (if set), else ~/.claude/tool-token-log.jsonl

Each line: {ts, tool, skill?, in_bytes, out_bytes, est_tokens}
Summaries:
  jq -s 'group_by(.tool)[]|{tool:.[0].tool,calls:length,
         est_tokens:(map(.est_tokens)|add)}' ~/.claude/tool-token-log.jsonl
"""
import json
import os
import sys
from datetime import datetime

CHARS_PER_TOKEN = 4


def main():
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)  # never disrupt the session over logging

    tool = d.get("tool_name", "?")
    tin = d.get("tool_input", {}) or {}
    tout = d.get("tool_response", d.get("tool_result", "")) or ""

    in_bytes = len(json.dumps(tin, default=str))
    out_bytes = len(tout if isinstance(tout, str) else json.dumps(tout, default=str))
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "tool": tool,
        "in_bytes": in_bytes,
        "out_bytes": out_bytes,
        "est_tokens": round((in_bytes + out_bytes) / CHARS_PER_TOKEN),
    }
    # When the tool is a Skill invocation, record which skill (so skill cost is attributable)
    if tool in ("Skill", "Agent", "Task"):
        rec["skill"] = tin.get("skill") or tin.get("subagent_type") or tin.get("description", "")

    path = os.environ.get("TOOL_TOKEN_LOG") or os.path.expanduser("~/.claude/tool-token-log.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # logging must never break the tool call
    sys.exit(0)


if __name__ == "__main__":
    main()
