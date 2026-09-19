#!/usr/bin/env python3
"""bash_shapes_report.py — rank observed bash shapes and the friction they cause.

Reads the log written by `bash_shape.py --record` and answers the only question that
matters for the allowlist: which command *shapes* fall through to `ask`, and how often.

Usage:
    bash_shapes_report.py                         # top 30 shapes, ask-shapes highlighted
    bash_shapes_report.py --log ~/agent/logs/bash-shapes.jsonl --top 50
    bash_shapes_report.py --only-ask              # just the shapes that prompt
    bash_shapes_report.py --json                  # machine-readable aggregate

The log holds only {ts, shape, action}; it never holds a full command, so no argument,
path, or secret can appear here.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

DEFAULT_LOG = os.path.expanduser("~/agent/logs/bash-shapes.jsonl")


def load(log_path: str) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(os.path.expanduser(log_path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict) and row.get("shape"):
                    rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def aggregate(rows: list[dict]) -> list[tuple[str, str, int]]:
    counts: collections.Counter = collections.Counter((r["shape"], r.get("action", "?")) for r in rows)
    return [(shape, action, n) for (shape, action), n in counts.most_common()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--only-ask", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = load(a.log)
    agg = aggregate(rows)
    if a.only_ask:
        agg = [x for x in agg if x[1] == "ask"]

    if a.json:
        print(json.dumps([{"shape": s, "action": ac, "count": n} for s, ac, n in agg], indent=2))
        return 0

    if not rows:
        print(f"no shapes logged yet at {os.path.expanduser(a.log)}")
        print("  (the plugin records on each bash call once deployed)")
        return 0

    asks = sum(n for _, ac, n in aggregate(rows) if ac == "ask")
    print(f"{len(rows)} calls, {len(aggregate(rows))} distinct shapes, {asks} fell through to ask")
    print()
    print(f"{'count':>6}  {'action':<5}  shape")
    for shape, action, n in agg[: a.top]:
        flag = "  <-- prompts" if action == "ask" else ""
        print(f"{n:>6}  {action:<5}  {shape}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
