#!/usr/bin/env python3
"""Benchmark an LLM provider on cross-wiki atomic-statement alignment.

The task: given a statement extracted from one wiki's policy page and the top-1
candidate from another wiki proposed by embedding similarity, judge equivalence
as y (same norm) / p (partial) / n (not equivalent). This is the semantic
arbiter of the exact -> fuzzy -> semantic attribution cascade — the real
delegated task, not a proxy for it.

Pre-registration (thresholds, baselines, verdict rule) is fixed BEFORE running:
  ../feedback/liftwing-bench-npov-prereg.md

Two arms, same gold labels:
  A  en-en   source statement pre-translated to English — equivalence alone
  B  de-en   original German source — equivalence plus cross-lingual reading

Provider comes from AGENT_LLM_PROVIDER via llm_provider.query_llm, so this
benchmarks whichever backend is selected; it is not LiftWing-specific.

Usage:
  # run one arm (writes JSONL, resumable — completed items are not re-called)
  AGENT_LLM_PROVIDER=liftwing bench_statement_align.py run --arm A --out a.jsonl

  # score against the pre-registered thresholds
  bench_statement_align.py score --results a.jsonl [--results b.jsonl]

  # what would be called, no LLM (verifies joins and prompts)
  bench_statement_align.py run --arm B --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_RUNS = (Path.home() / "Documents/GitHub/wikimedia-analysis/"
                "wikipedia-policy-change/data/exploration/runs")

LABELS = ("y", "p", "n")
# Pre-registered pass marks — see the prereg doc. Changing these after a run
# invalidates the registration.
PASS_ACCURACY = 0.65
PASS_MERGE_PRECISION = 0.80
PASS_PARSE_FAILURE = 0.05
BASELINES = {"random": 0.333, "majority (always n)": 0.517,
             "embedding, oracle-tuned": 0.621}

SYSTEM = (
    "You compare governance rules taken from different Wikipedia language "
    "editions. You answer with exactly one lowercase letter and nothing else."
)

PROMPT = """\
Two statements were extracted from Wikipedia policy pages in different language editions.
Decide whether they express the SAME RULE.

Statement A (from the German Wikipedia policy page):
{src}

Statement B (from the English Wikipedia policy page):
{tgt}

Answer with exactly one letter:
y = same rule: both state the same norm, allowing for wording and translation differences
p = partial: related or overlapping, but not the same norm
n = not the same rule

Answer with the single letter only. No explanation, no punctuation.
"""


def load_items(runs: Path):
    """Join gold labels, embedding candidates, and original German text."""
    def rows(name):
        with open(runs / name, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    gold = {r["src_id"]: r["equivalent?"].strip()
            for r in rows("align_de_en_npov_review.csv")}
    align = {r["src_id"]: r for r in rows("align_de_en_npov.csv")}
    orig = {r["statement_id"]: r.get("statement_orig", "")
            for r in rows("de__wikipedia_neutraler_standpunkt.statements.csv")}

    items = []
    for src_id, a in align.items():
        g = gold.get(src_id, "")
        items.append({
            "src_id": src_id,
            "gold": g if g in LABELS else None,     # None = extension set
            "src_en": a["src_statement_en"],
            "src_de": orig.get(src_id, ""),
            "tgt_id": a["best_tgt_id"],
            "tgt_en": a["best_tgt_statement_en"],
            "score": float(a["best_score"]),
        })
    missing = [i["src_id"] for i in items if not i["src_de"]]
    if missing:
        print(f"warning: no German original for {len(missing)} items "
              f"(arm B will skip them): {missing[:3]}", file=sys.stderr)
    return items


def parse_label(text: str):
    """Extract the verdict. Returns None on anything outside {y,p,n}."""
    t = (text or "").strip().strip(".,;:!\"'`*").lower()
    if t in LABELS:
        return t
    # A model that ignored "one letter only" but still answered first.
    first = t.split()[0].strip(".,;:!\"'`*") if t.split() else ""
    return first if first in LABELS else None


def run(args):
    items = load_items(Path(args.runs))
    arm = args.arm.upper()
    field = "src_en" if arm == "A" else "src_de"
    items = [i for i in items if i[field]]
    if args.only_gold:
        items = [i for i in items if i["gold"]]

    done = set()
    out_path = Path(args.out) if args.out else None
    if out_path and out_path.exists():
        with open(out_path, encoding="utf-8") as fh:
            done = {json.loads(line)["src_id"] for line in fh if line.strip()}
        print(f"resuming: {len(done)} already recorded")

    todo = [i for i in items if i["src_id"] not in done]
    print(f"arm {arm}: {len(todo)} calls "
          f"({sum(1 for i in todo if i['gold'])} scored, "
          f"{sum(1 for i in todo if not i['gold'])} extension)")
    if args.dry_run:
        if todo:
            print("\n--- first prompt ---")
            print(PROMPT.format(src=todo[0][field], tgt=todo[0]["tgt_en"]))
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from llm_provider import query_llm

    fh = open(out_path, "a", encoding="utf-8") if out_path else sys.stdout
    ok = fail = 0
    try:
        for n, item in enumerate(todo, 1):
            prompt = PROMPT.format(src=item[field], tgt=item["tgt_en"])
            t0 = time.time()
            raw, err = "", None
            try:
                raw = query_llm(prompt, SYSTEM, timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001 — record, never abort the batch
                err = f"{type(exc).__name__}: {exc}"
                if type(exc).__name__ == "RateBudgetExceeded":
                    print(f"\nrate budget exhausted at item {n}; "
                          f"re-run to resume", file=sys.stderr)
                    break
            rec = {
                "src_id": item["src_id"], "arm": arm, "gold": item["gold"],
                "pred": parse_label(raw), "raw": raw[:400], "error": err,
                "score": item["score"], "latency_s": round(time.time() - t0, 2),
                "think_block": "<think>" in (raw or "").lower(),
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            ok += rec["pred"] is not None
            fail += rec["pred"] is None
            print(f"  [{n}/{len(todo)}] {item['src_id']} -> "
                  f"{rec['pred'] or 'PARSE-FAIL'} ({rec['latency_s']}s)",
                  file=sys.stderr)
    finally:
        if out_path:
            fh.close()
    print(f"\nparsed {ok}, unparseable {fail}")
    return 0


def score(args):
    recs = []
    for p in args.results:
        with open(p, encoding="utf-8") as fh:
            recs.extend(json.loads(line) for line in fh if line.strip())

    for arm in sorted({r["arm"] for r in recs}):
        rows = [r for r in recs if r["arm"] == arm]
        scored = [r for r in rows if r["gold"]]
        ext = [r for r in rows if not r["gold"]]
        print(f"\n{'='*62}\nARM {arm} — {len(scored)} scored, {len(ext)} extension")
        if not scored:
            continue

        # Parse-failure is measured over every call, scored or not.
        pf = sum(1 for r in rows if r["pred"] is None) / len(rows)
        usable = [r for r in scored if r["pred"]]
        acc = sum(1 for r in usable if r["pred"] == r["gold"]) / len(scored)

        merged = [r for r in usable if r["pred"] in ("y", "p")]
        mp = (sum(1 for r in merged if r["gold"] != "n") / len(merged)
              if merged else float("nan"))

        print(f"\n  3-way accuracy      {acc:6.1%}   "
              f"(pass >= {PASS_ACCURACY:.0%})  {'PASS' if acc >= PASS_ACCURACY else 'FAIL'}")
        print(f"  merge-precision     {mp:6.1%}   "
              f"(pass >= {PASS_MERGE_PRECISION:.0%})  "
              f"{'PASS' if mp >= PASS_MERGE_PRECISION else 'FAIL'}"
              f"   [n={len(merged)} merge calls]")
        print(f"  parse-failure       {pf:6.1%}   "
              f"(pass <= {PASS_PARSE_FAILURE:.0%})  "
              f"{'PASS' if pf <= PASS_PARSE_FAILURE else 'FAIL'}")

        print("\n  vs baselines:")
        for name, b in BASELINES.items():
            print(f"    {name:<26} {b:5.1%}   {'beaten' if acc > b else 'NOT beaten'}")

        print("\n  confusion (gold down, pred across):")
        print("        " + "".join(f"{p:>6}" for p in LABELS) + "  fail")
        for g in LABELS:
            gr = [r for r in scored if r["gold"] == g]
            cells = "".join(f"{sum(1 for r in gr if r['pred'] == p):>6}" for p in LABELS)
            print(f"    {g:<4}{cells}{sum(1 for r in gr if r['pred'] is None):>6}")

        lat = sorted(r["latency_s"] for r in rows)
        if lat:
            print(f"\n  latency  median {lat[len(lat)//2]:.1f}s  "
                  f"p90 {lat[int(len(lat)*0.9)]:.1f}s  max {lat[-1]:.1f}s")
        print(f"  <think> blocks: {sum(1 for r in rows if r['think_block'])}/{len(rows)}")
        errs = [r["error"] for r in rows if r["error"]]
        if errs:
            print(f"  errors: {len(errs)} — first: {errs[0][:120]}")

        print(f"\n  n=29 -> 95% CI is about +/-18 points. This is a screen, "
              f"not a ranking\n  instrument; differences under ~20 points are not evidence.")

    if len({r["arm"] for r in recs}) > 1:
        print(f"\n{'='*62}\nARM A vs B: see the caveat above before reading any gap "
              f"as real.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench_statement_align.py",
                                 description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="call the provider and record results")
    r.add_argument("--arm", choices=["A", "B", "a", "b"], required=True)
    r.add_argument("--out", help="JSONL results file (appends, resumable)")
    r.add_argument("--runs", default=str(DEFAULT_RUNS), help="data directory")
    r.add_argument("--only-gold", action="store_true",
                   help="scored items only; skip the 36 extension items")
    r.add_argument("--timeout", type=int, default=180)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=run)

    s = sub.add_parser("score", help="score against the pre-registered marks")
    s.add_argument("--results", nargs="+", required=True)
    s.set_defaults(func=score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
