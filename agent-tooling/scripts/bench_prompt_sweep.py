#!/usr/bin/env python3
"""Did we ask badly? A controlled prompt-specification sweep.

Round 1 scored LiftWing on `deontic_type` with a **bare list of seven words**
and no definitions, no abstention option, and no examples. The failure it
produced looks exactly like an underspecification artefact rather than a
capability limit:

    principle    P=0.14  R=0.91   <- sink: everything lands here
    procedure    P=0.24  R=1.00   <- sink
    obligation   P=1.00  R=0.13   <- starved (largest class, n=127)

Precision 1.00 at recall 0.13 on the biggest class means: when it says
obligation it is always right, but it usually says something vaguer. That is a
boundary problem, not a concept problem. And the one round-1 task that DID get
per-class definitions (`governance_class`) is the one task that cleanly beat its
baseline.

So this sweep varies ONLY the prompt, holding items, model, gold and scoring
fixed, across five rungs:

    1 bare              exact round-1 prompt (replication anchor)
    2 defined           + one-line definition per class
    3 defined_unclear   + an explicit "unclear" escape hatch
    4 defined_fewshot   + k examples per class, held out
    5 defined_boundary  + examples drawn from the confusion cells

## Why the deltas are valid even though the gold is not

The gold labels are LLM-generated and unvalidated (see feedback/liftwing.md,
2026-08-16), so no ARM'S ABSOLUTE SCORE means much. But every arm is scored
against the same labels on the same items, so **differences between arms are
valid regardless of gold quality**. This answers "did we ask badly?" without
waiting for a human-labelled subset.

What it cannot do: tell us the labels were right, or that these definitions are
the project's real codebook. They are reconstructions written from the
labeller's own examples.

Usage:
  bench_prompt_sweep.py prepare --out sweep_items.jsonl
  bench_prompt_sweep.py rate --items sweep_items.jsonl \
      --rater liftwing:llm-qwen3-14b --out sweep_ratings.jsonl
  bench_prompt_sweep.py score --items sweep_items.jsonl --ratings sweep_ratings.jsonl
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import io
import json
import os
import random
import re
import sys

EXPLORE = os.path.expanduser("~/Documents/GitHub/wikimedia-analysis/"
                             "wikipedia-policy-change/data/exploration")

# The round-1 seven. Kept EXACTLY as round 1 had them so arm 1 is a true
# replication anchor -- even though the taxonomy itself is under review (four
# inconsistent variants exist across the corpus; see feedback/liftwing.md).
CLASSES = ["obligation", "prohibition", "permission", "condition",
           "principle", "definition", "procedure"]

# Reconstructed from the labeller's own examples, not invented. The point is to
# test whether ANY definition helps; a project codebook would be the real test.
DEFINITIONS = {
    "obligation":  "something that MUST or SHOULD be done (must, shall, is required, editors consider)",
    "prohibition": "something that must NOT be done, is not allowed, or does not belong",
    "permission":  "something that MAY optionally be done, at the actor's discretion",
    "condition":   "a threshold, trigger or precondition that decides when something applies "
                   "(a percentage, a deadline, 'only if')",
    "principle":   "a general aim or value with no specific action attached "
                   "(what the project is FOR, not what to do)",
    "definition":  "states what something or someone IS -- constitutive, not directive",
    "procedure":   "the mechanical steps by which something happens, including bot actions",
}

# Cells the round-1 confusion matrix showed bleeding into each other.
BOUNDARY_PAIRS = [("obligation", "principle"), ("condition", "procedure"),
                  ("definition", "principle"), ("permission", "condition")]

SYSTEM = ("You classify governance rules from Wikipedia policy pages. "
          "You answer with the requested token and nothing else.")

# The reasoning arm needs its own system message: the default one forbids the
# very thing that arm exists to test. Leaving it in place would have sabotaged
# the arm and produced a false "reasoning does not help" result.
SYSTEM_REASON = ("You classify governance rules from Wikipedia policy pages. "
                 "You may think step by step, then end with the answer line "
                 "exactly as instructed.")


def system_for(arm: str) -> str:
    return SYSTEM_REASON if arm == "defined_reason" else SYSTEM


# Per-arm output budget and how to read the answer back. Round 1 forced 4-12
# tokens on every classification call, which makes deliberation structurally
# impossible -- the model must emit a label on its FIRST token. Published work
# ("Let Me Speak Freely?", arXiv 2408.02442) finds format restriction degrades
# performance, and the round-1 pathology fits: right when easy, nearest-vague-
# label when hard. The `reason` arm removes that constraint; the json arms vary
# input/output structure at a fixed budget so the two effects stay separable.
# Two tracks, deliberately not crossed. The SHOT track is a dose-response
# series (0 -> 1 -> 3 examples per class) holding format fixed; the FORMAT track
# varies output budget and structure holding shots at 0. Crossing them would be
# 27 arms and would make any effect uninterpretable -- the same "keep the two
# effects separable" reasoning as the batching probe.
ARM_SPEC = {
    # anchor
    "bare":             {"max_tokens": 12,  "parse": "label"},   # no defs, 0-shot
    # shot track: definitions held constant, examples vary
    "defined_0shot":    {"max_tokens": 12,  "parse": "label"},
    "defined_1shot":    {"max_tokens": 12,  "parse": "label"},
    "defined_3shot":    {"max_tokens": 12,  "parse": "label"},
    "defined_boundary": {"max_tokens": 12,  "parse": "label"},   # 1/confusion pair
    # format track: 0-shot throughout
    "defined_unclear":  {"max_tokens": 12,  "parse": "label"},
    "defined_reason":   {"max_tokens": 250, "parse": "reason"},
    "defined_json_in":  {"max_tokens": 12,  "parse": "label"},
    "defined_json_io":  {"max_tokens": 40,  "parse": "json"},
}


def build_prompt(arm: str, statement: str, examples=None) -> str:
    unclear = arm == "defined_unclear"
    labels = CLASSES + (["unclear"] if unclear else [])

    if arm == "bare":                      # byte-identical to round 1
        return (f"Statement: {statement}\n\n"
                f"Which one describes it?\n" +
                "\n".join(f"- {d}" for d in CLASSES) +
                "\n\nAnswer with one word from the list. Nothing else.")

    if arm in ("defined_json_in", "defined_json_io"):
        spec = {"task": "deontic_classification",
                "statement": statement,
                "labels": {c: DEFINITIONS[c] for c in CLASSES}}
        body = json.dumps(spec, indent=2, ensure_ascii=False)
        if arm == "defined_json_io":
            return (body + "\n\nReturn exactly: {\"label\": \"<one of the "
                    "keys in labels>\"}\nNo other text.")
        return (body + "\n\nAnswer with one key from labels. Nothing else.")

    lines = [f"- {c}: {DEFINITIONS[c]}" for c in CLASSES]
    if unclear:
        lines.append("- unclear: the statement does not clearly fit any category above")

    head = ""
    if examples:
        shown = "\n".join(f"  {s}  ->  {lab}" for lab, s in examples)
        head = f"Examples:\n{shown}\n\n"

    if arm == "defined_reason":
        tail = ("\n\nThink briefly about which definition fits, then give your "
                "verdict on the LAST line in exactly this form:\nANSWER: <label>")
    elif unclear:
        tail = "\n\nAnswer with one word from the list, or 'unclear'. Nothing else."
    else:
        tail = "\n\nAnswer with one word from the list. Nothing else."
    return (f"{head}Statement: {statement}\n\n"
            "Which one describes it?\n" + "\n".join(lines) + tail)


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def _load_statements(explore):
    out = []
    for f in sorted(glob.glob(os.path.join(explore, "runs", "*.statements.csv"))) + \
             sorted(glob.glob(os.path.join(explore, "nlwiki_*", "04_statements.csv"))):
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("deontic_type") in CLASSES and r.get("statement_en"):
                    out.append({"id": r.get("statement_id") or f"{os.path.basename(f)}:{len(out)}",
                                "statement_en": r["statement_en"],
                                "gold": r["deontic_type"]})
    return out


def prepare(args):
    rng = random.Random(args.seed)
    stmts = _load_statements(args.explore)
    by = collections.defaultdict(list)
    for s in stmts:
        by[s["gold"]].append(s)

    # Stratified hold-out for few-shot examples. These NEVER enter the scored
    # set -- with example selection this is the one way to leak the answer.
    pool, scored = [], []
    for cls, rows in by.items():
        rng.shuffle(rows)
        n_hold = min(args.hold_per_class, max(0, len(rows) - args.min_scored_per_class))
        pool.extend(rows[:n_hold])
        scored.extend(rows[n_hold:])
    rng.shuffle(scored)

    pool_by = collections.defaultdict(list)
    for s in pool:
        pool_by[s["gold"]].append(s)

    def pick(strategy, k=0):
        ex = []
        if strategy == "shot":
            for c in CLASSES:
                ex += [(c, s["statement_en"]) for s in pool_by[c][:k]]
        elif strategy == "boundary":
            for a, b in BOUNDARY_PAIRS:
                for c in (a, b):
                    if pool_by[c]:
                        ex.append((c, pool_by[c][0]["statement_en"]))
        rng.shuffle(ex)
        return ex

    arms = {
        "bare": None,
        "defined_0shot": None,
        "defined_1shot": pick("shot", 1),
        "defined_3shot": pick("shot", 3),
        "defined_boundary": pick("boundary"),
        "defined_unclear": None,
        "defined_reason": None,
        "defined_json_in": None,
        "defined_json_io": None,
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        for arm, ex in arms.items():
            for s in scored:
                fh.write(json.dumps({
                    "id": f"{arm}::{s['id']}", "arm": arm, "item_id": s["id"],
                    "gold": s["gold"],
                    "prompt": build_prompt(arm, s["statement_en"], ex),
                    "max_tokens": ARM_SPEC[arm]["max_tokens"],
                    "parse_mode": ARM_SPEC[arm]["parse"],
                    "system": system_for(arm),
                }, ensure_ascii=False) + "\n")

    hold_ids = {s["id"] for s in pool}
    leak = [s for s in scored if s["id"] in hold_ids]
    print(f"wrote {args.out}")
    print(f"  scored items per arm: {len(scored)}   held out for examples: {len(pool)}")
    print(f"  arms: {list(arms)}")
    print(f"  leak check (held-out ids inside scored set): {len(leak)}  "
          f"{'OK' if not leak else 'FAIL'}")
    print(f"  total prompts: {len(scored) * len(arms)}")
    for c in CLASSES:
        print(f"    {c:<12} scored {sum(1 for s in scored if s['gold']==c):>4}"
              f"   pool {len(pool_by[c]):>3}")
    return 0


# ---------------------------------------------------------------------------
# rate / score
# ---------------------------------------------------------------------------

def extract(raw, mode, labels):
    """Pull the verdict out according to the arm's output contract."""
    if mode == "reason":
        m = re.findall(r"ANSWER\s*:\s*([A-Za-z_-]+)", raw or "")
        return norm_label(m[-1], labels) if m else norm_label(
            (raw or "").strip().splitlines()[-1] if (raw or "").strip() else "", labels)
    if mode == "json":
        t = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            try:
                return norm_label(str(json.loads(m.group()).get("label", "")), labels)
            except json.JSONDecodeError:
                pass
        return norm_label(raw, labels)
    return norm_label(raw, labels)


def norm_label(text, labels):
    t = (text or "").strip().strip(".,;:!\"'`*").lower()
    if t in labels:
        return t
    for lab in sorted(labels, key=len, reverse=True):
        if re.search(rf"\b{re.escape(lab)}\b", t):
            return lab
    return None


def rate(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from llm_provider import query_llm
    items = [json.loads(l) for l in open(args.items, encoding="utf-8") if l.strip()]
    done = set()
    if os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("pred") is not None or r.get("raw"):
                    done.add((r["rater"], r["id"]))
    fh = open(args.out, "a", encoding="utf-8")
    for spec in args.rater:
        provider, _, model = spec.partition(":")
        todo = [i for i in items if (spec, i["id"]) not in done]
        print(f"\n=== {spec}: {len(todo)} prompts ===", file=sys.stderr)
        for n, it in enumerate(todo, 1):
            os.environ["AGENT_LLM_PROVIDER"] = provider
            if model:
                os.environ["AGENT_LLM_MODEL"] = model
            else:
                os.environ.pop("AGENT_LLM_MODEL", None)
            try:
                raw = query_llm(it["prompt"], it.get("system", SYSTEM),
                                timeout=args.timeout)
                err = None
            except Exception as e:  # noqa: BLE001
                raw, err = "", f"{type(e).__name__}: {e}"
            labels = CLASSES + (["unclear"] if it["arm"] == "defined_unclear" else [])
            fh.write(json.dumps({"rater": spec, "id": it["id"], "arm": it["arm"],
                                 "item_id": it["item_id"], "gold": it["gold"],
                                 "pred": extract(raw, it.get("parse_mode", "label"), labels),
                                 "error": err,
                                 "raw": raw[:400]}, ensure_ascii=False) + "\n")
            fh.flush()
            if n % 50 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}", file=sys.stderr)
    fh.close()
    return 0


def macro_f1(pairs, labels):
    fs, per = [], {}
    for lab in labels:
        tp = sum(1 for g, p in pairs if g == lab and p == lab)
        fp = sum(1 for g, p in pairs if g != lab and p == lab)
        fn = sum(1 for g, p in pairs if g == lab and p != lab)
        if tp + fn == 0:
            continue
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn)
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        per[lab] = (pr, rc, f1, tp + fn)
        fs.append(f1)
    return (sum(fs) / len(fs) if fs else 0.0), per


ARM_ORDER = ["bare", "defined_0shot", "defined_1shot", "defined_3shot",
             "defined_boundary", "defined_unclear", "defined_reason",
             "defined_json_in", "defined_json_io"]


def score(args):
    recs = [json.loads(l) for l in open(args.ratings, encoding="utf-8") if l.strip()]
    for rater in sorted({r["rater"] for r in recs}):
        rs = [r for r in recs if r["rater"] == rater]
        print(f"\n{'='*74}\n{rater}")
        print(f"{'arm':<18}{'macroF1':>9}{'Δ vs bare':>11}"
              f"{'oblig R':>9}{'princ P':>9}{'labels':>8}{'unclear':>9}{'parse-fail':>11}")
        base = None
        for arm in ARM_ORDER:
            a = [r for r in rs if r["arm"] == arm]
            if not a:
                continue
            pairs = [(r["gold"], r["pred"]) for r in a]
            mf1, per = macro_f1(pairs, CLASSES)
            if arm == "bare":
                base = mf1
            d = f"{mf1-base:+.3f}" if base is not None and arm != "bare" else "—"
            oR = per.get("obligation", (0, 0, 0, 0))[1]
            pP = per.get("principle", (0, 0, 0, 0))[0]
            used = len({p for _, p in pairs if p and p != "unclear"})
            unc = sum(1 for r in a if r["pred"] == "unclear") / len(a)
            pf = sum(1 for r in a if r["pred"] is None) / len(a)
            print(f"{arm:<18}{mf1:>9.3f}{d:>11}{oR:>9.2f}{pP:>9.2f}"
                  f"{used:>6}/7{unc:>9.0%}{pf:>11.0%}")

        # Did the sinks drain, or just move?
        print("\n  sink check (precision on the two round-1 sink classes):")
        for arm in ARM_ORDER:
            a = [r for r in rs if r["arm"] == arm]
            if not a:
                continue
            _, per = macro_f1([(r["gold"], r["pred"]) for r in a], CLASSES)
            bits = "  ".join(
                f"{c}: P={per.get(c,(0,))[0]:.2f} R={per.get(c,(0,0))[1]:.2f}"
                for c in ("principle", "procedure"))
            print(f"    {arm:<18} {bits}")

    print(f"\n{'='*74}")
    print("The gold is LLM-generated and unvalidated, so ABSOLUTE scores are not")
    print("meaningful. Read the Δ column: same items, same gold, same model —")
    print("only the prompt changed, so the differences are real even if the")
    print("levels are not.")
    print("H1: definitions/examples raise obligation recall and principle")
    print("precision. H0: Δ stays inside noise and the sinks persist — in which")
    print("case the limit is the model, not the prompt.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench_prompt_sweep.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--explore", default=EXPLORE)
    p.add_argument("--k", type=int, default=3, help="few-shot examples per class")
    p.add_argument("--hold-per-class", type=int, default=6)
    p.add_argument("--min-scored-per-class", type=int, default=8)
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--out", default="sweep_items.jsonl")
    p.set_defaults(func=prepare)

    r = sub.add_parser("rate")
    r.add_argument("--items", required=True)
    r.add_argument("--rater", action="append", required=True)
    r.add_argument("--out", default="sweep_ratings.jsonl")
    r.add_argument("--timeout", type=int, default=120)
    r.set_defaults(func=rate)

    s = sub.add_parser("score")
    s.add_argument("--items", required=False)
    s.add_argument("--ratings", required=True)
    s.set_defaults(func=score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
