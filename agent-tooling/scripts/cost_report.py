#!/usr/bin/env python3
"""Report skill run cost by PR type, from the record_run.py log.

Reads the JSONL written by record_run.py and aggregates per (skill, PR type),
where PR type = the sorted scope-flag set. Optionally converts to dollars given
a $/Mtok rate, and predicts an unseen PR type from history + diff size.

Usage:
  cost_report.py                                  # table over all history
  cost_report.py --skill pr-check --rate 3.0      # $ at $3 / Mtok
  cost_report.py --predict --flags TEMPLATES_CSS,JS,RUNTIME --diff-lines 800
"""
import argparse
import json
import os
import sys
from statistics import mean, median


def pr_type(flags):
    return "+".join(sorted(f for f in (flags or []) if f)) or "NONE"


def load(path):
    rows = []
    try:
        for line in open(path):
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def aggregate(rows, skill=None):
    """-> {(skill, pr_type): {n, tokens[list], diffs[list]}}."""
    agg = {}
    for r in rows:
        if skill and r.get("skill") != skill:
            continue
        key = (r.get("skill", "?"), pr_type(r.get("flags")))
        a = agg.setdefault(key, {"n": 0, "tokens": [], "diffs": []})
        a["n"] += 1
        a["tokens"].append(int(r.get("subagent_tokens") or 0))
        if r.get("diff_lines") is not None:
            a["diffs"].append(int(r["diff_lines"]))
    return agg


def predict(rows, flags, diff_lines):
    """Rough a-priori estimate for an unseen PR type.

    Exact flag-set seen -> its mean. Else same flag-count -> mean of those,
    scaled by diff ratio. Else overall mean scaled by diff ratio. Honest & rough.
    """
    want = pr_type(flags)
    same_type = [r for r in rows if pr_type(r.get("flags")) == want]
    if same_type:
        return mean(int(r.get("subagent_tokens") or 0) for r in same_type), "exact PR-type history"
    n_flags = len([f for f in (flags or []) if f])
    same_count = [r for r in rows if len(r.get("flags") or []) == n_flags]
    pool = same_count or rows
    if not pool:
        return None, "no history yet"
    base = mean(int(r.get("subagent_tokens") or 0) for r in pool)
    diffs = [int(r["diff_lines"]) for r in pool if r.get("diff_lines")]
    if diff_lines and diffs:
        base *= diff_lines / max(1, mean(diffs))
    why = f"same flag-count (n={len(same_count)})" if same_count else f"overall mean (n={len(pool)})"
    return base, why + (", diff-scaled" if diff_lines and diffs else "")


def fmt_tokens(t):
    return f"{t/1000:.0f}k" if t else "0"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default=os.environ.get("SKILL_RUN_LOG") or
                    os.path.expanduser("~/.claude/skill-run-cost.jsonl"))
    ap.add_argument("--skill")
    ap.add_argument("--rate", type=float, help="$ per million tokens, to show cost")
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--flags", default="")
    ap.add_argument("--diff-lines", type=int)
    a = ap.parse_args()

    rows = load(a.log)
    if not rows:
        print(f"No runs logged yet at {a.log}. Run a skill that calls record_run.py first.")
        return

    if a.predict:
        rows_s = [r for r in rows if not a.skill or r.get("skill") == a.skill]
        est, why = predict(rows_s, a.flags.split(","), a.diff_lines)
        if est is None:
            print(why); return
        line = f"Predicted for [{pr_type(a.flags.split(','))}] diff={a.diff_lines or '?'}: ~{fmt_tokens(est)} subagent tokens ({why})"
        if a.rate:
            line += f"  ≈ ${est/1e6*a.rate:.2f}"
        print(line)
        return

    print(f"Skill run cost by PR type  ({len(rows)} runs, {a.log})\n")
    hdr = f"{'skill':<14} {'PR type':<34} {'n':>3} {'avg tok':>8} {'median':>8} {'avg diff':>8}"
    if a.rate:
        hdr += f" {'$avg':>7}"
    print(hdr)
    for (sk, pt), v in sorted(aggregate(rows, a.skill).items(), key=lambda kv: -mean(kv[1]["tokens"])):
        avg = mean(v["tokens"]); med = median(v["tokens"])
        ad = f"{mean(v['diffs']):.0f}" if v["diffs"] else "-"
        row = f"{sk:<14} {pt:<34} {v['n']:>3} {fmt_tokens(avg):>8} {fmt_tokens(med):>8} {ad:>8}"
        if a.rate:
            row += f" {'$'+format(avg/1e6*a.rate, '.2f'):>7}"
        print(row)


if __name__ == "__main__":
    main()
