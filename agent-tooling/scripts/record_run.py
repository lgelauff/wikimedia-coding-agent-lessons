#!/usr/bin/env python3
"""Append one cost record per skill run, tagged by PR type (scope flags).

A skill calls this at the end of a run with the REAL numbers it already has:
the workflow's reported `subagent_tokens` and the scope flags it computed. Over
many runs this builds an empirical "what does skill X cost on this kind of PR"
table — far more accurate than guessing from tool-payload size, because the cost
of a fan-out skill lives in the subagent tokens, which only the run itself sees.

Log: $SKILL_RUN_LOG or ~/.claude/skill-run-cost.jsonl  (JSONL, one row per run).

Usage:
  record_run.py --skill pr-check --pr 174 \
      --flags TEMPLATES_CSS,JS,RUNTIME --diff-lines 1019 \
      --subagent-tokens 465015 --duration-ms 564808
"""
import argparse
import json
import os
import sys
from datetime import datetime


def make_record(skill, flags, subagent_tokens, pr=None, diff_lines=None, duration_ms=None):
    """Pure builder (testable). `flags` iterable of scope-flag strings."""
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "skill": skill,
        "pr": pr,
        "flags": sorted(f for f in (flags or []) if f),
        "diff_lines": diff_lines,
        "subagent_tokens": int(subagent_tokens or 0),
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", required=True)
    ap.add_argument("--flags", default="", help="comma-separated scope flags (the PR type)")
    ap.add_argument("--subagent-tokens", type=int, default=0)
    ap.add_argument("--pr")
    ap.add_argument("--diff-lines", type=int)
    ap.add_argument("--duration-ms", type=int)
    ap.add_argument("--log")
    a = ap.parse_args()

    rec = make_record(a.skill, a.flags.split(","), a.subagent_tokens,
                      pr=a.pr, diff_lines=a.diff_lines, duration_ms=a.duration_ms)
    path = a.log or os.environ.get("SKILL_RUN_LOG") or \
        os.path.expanduser("~/.claude/skill-run-cost.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError as e:
        print(f"record_run: could not write {path}: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"recorded: {rec['skill']} [{'+'.join(rec['flags']) or 'NONE'}] "
          f"{rec['subagent_tokens']} subagent tokens → {path}")


if __name__ == "__main__":
    main()
