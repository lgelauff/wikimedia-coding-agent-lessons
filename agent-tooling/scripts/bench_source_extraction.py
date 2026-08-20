#!/usr/bin/env python3
"""Source extraction as retrieve-then-rerank, with a gold-free hallucination check.

The task the research pipeline actually needs: given a claim and candidate
passages from a paper, pick the passage that supports it -- and quote it
verbatim. `collect-source` discipline is "only cite claims verified against the
cached primary text", so a model that invents a quote is disqualifying.

## Why this shape, and not "extract the passage from the paper"

Two facts about the available gold forced it (both measured, 2026-08-15):

  * **The gold passages are not verbatim spans of the cached sources.** Only
    3.9% appear as exact substrings; 50.9% survive stripping to alphanumerics.
    They were paraphrased or stitched by whatever produced the mapping. So a
    "did it return the gold span" metric CANNOT be scored against this gold.
  * **29 of 46 papers exceed the 14B's 16K context** (median ~19.7k tokens), so
    whole-paper extraction does not fit at all.

Retrieve-then-rerank fixes both, and matches the published finding that LLMs are
weak few-shot extractors but useful rerankers of a cheap retriever's shortlist.

## Metrics

  1. **rerank accuracy** -- gold chunk chosen from 8 BM25 candidates.
     Baseline **BM25 recall@1 = 30.8%**; ceiling **recall@8 = 77.4%** (the gold
     is absent from the shortlist 22.6% of the time, so 100% is unreachable).
  2. **quote-hallucination rate** -- is the returned quote actually present in
     the chunk it claims to quote? **Needs no gold**, so it scores every item
     including the negatives. This is the number that decides usability.
  3. **abstention** on hard negatives (candidates drawn from a paper that does
     not discuss the claim; correct answer is "none").

Usage:
  bench_source_extraction.py prepare --out items.jsonl
  bench_source_extraction.py rate --items items.jsonl \
      --rater liftwing:llm-qwen3-14b --out ratings.jsonl
  bench_source_extraction.py score --items items.jsonl --ratings ratings.jsonl
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import random
import re
import sys
import unicodedata

MAPPINGS = os.path.expanduser(
    "~/Documents/GitHub/wikimedia-analysis/AI effects/v2/archive")
CACHE = os.path.expanduser("~/Documents/GitHub/research-vault/cache")
K = 8

SYSTEM = ("You locate supporting evidence in academic sources. You reply with "
          "one JSON object and nothing else -- no prose, no markdown fence.")

PROMPT = """\
Claim: {claim}

Below are {k} numbered passages from a paper. Decide which one supports the claim.

{passages}

Reply with exactly this JSON:
{{"choice": <passage number 1-{k}, or 0 if none of them supports the claim>,
  "quote": "<a sentence copied EXACTLY from the passage you chose, or empty if 0>"}}

The quote must be copied character-for-character from the passage. Do not
paraphrase, summarise, or repair it."""


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------

def norm(t: str) -> str:
    """Normalisation for substring checks: whitespace, case, punctuation.

    PDF-extracted text varies in line breaks, hyphenation and quote glyphs, so a
    raw substring test would report hallucination for a faithful quote.
    """
    t = unicodedata.normalize("NFKC", t).lower()
    t = t.replace("’", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"-\s+", "", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def chunk(text: str, target: int = 1200) -> list:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 120]
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) < target:
            buf += ("\n" + p if buf else p)
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def bm25(query: str, docs: list, k1=1.5, b=0.75) -> list:
    tq = norm(query).split()
    td = [norm(d).split() for d in docs]
    N = len(td)
    avg = sum(len(d) for d in td) / max(N, 1)
    df = collections.Counter()
    for d in td:
        df.update(set(d))
    scores = []
    for d in td:
        tf = collections.Counter(d)
        s = 0.0
        for w in tq:
            if w not in tf:
                continue
            idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------

def prepare(args):
    rng = random.Random(args.seed)
    papers = {}
    records = []
    for f in sorted(glob.glob(os.path.join(args.mappings, "claim_mapping_part*.json"))):
        for p in json.load(open(f, encoding="utf-8")):
            path = os.path.join(args.cache, f"{p['citekey']}.txt")
            if not os.path.exists(path):
                continue
            if p["citekey"] not in papers:
                src = open(path, encoding="utf-8", errors="replace").read()
                papers[p["citekey"]] = chunk(src)
            records.append(p)

    items, skipped = [], collections.Counter()
    for p in records:
        cs = papers.get(p["citekey"]) or []
        if len(cs) < K:
            skipped["too_few_chunks"] += 1
            continue
        for c in p.get("claims_mapped") or []:
            claim, passage = c.get("claim_text"), c.get("passage")
            if not (claim and passage):
                skipped["no_passage"] += 1
                continue
            g = norm(passage)[:200]
            gold_idx = next((i for i, x in enumerate(cs) if g and g in norm(x)), None)
            if gold_idx is None:
                skipped["gold_not_locatable"] += 1
                continue
            scores = bm25(claim, cs)                     # claim only — no leak
            order = sorted(range(len(cs)), key=lambda i: -scores[i])[:K]
            items.append({
                "id": f"{p['citekey']}:{c['claim_id']}",
                "kind": "positive",
                "claim": claim,
                "candidates": [cs[i] for i in order],
                "gold_pos": order.index(gold_idx) + 1 if gold_idx in order else 0,
                "bm25_top1_correct": order[0] == gold_idx,
                "gold_in_shortlist": gold_idx in order,
            })

    # Hard negatives: same claim, candidates from a paper that never mapped it.
    keys = list(papers)
    pos = [i for i in items if i["gold_in_shortlist"]]
    for src_item in rng.sample(pos, min(args.negatives, len(pos))):
        claim = src_item["claim"]
        owner = src_item["id"].split(":")[0]
        others = [k for k in keys if k != owner and len(papers[k]) >= K]
        if not others:
            continue
        k = rng.choice(others)
        cs = papers[k]
        order = sorted(range(len(cs)), key=lambda i: -bm25(claim, cs)[i])[:K]
        items.append({
            "id": f"NEG:{k}:{src_item['id'].split(':')[-1]}",
            "kind": "negative",
            "claim": claim,
            "candidates": [cs[i] for i in order],
            "gold_pos": 0, "bm25_top1_correct": False, "gold_in_shortlist": False,
        })

    with open(args.out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    npos = sum(1 for i in items if i["kind"] == "positive")
    inshort = sum(1 for i in items if i["gold_in_shortlist"])
    b1 = sum(1 for i in items if i["bm25_top1_correct"])
    print(f"wrote {args.out}: {npos} positive + {len(items)-npos} negative")
    print(f"  skipped: {dict(skipped)}")
    print(f"  BM25 recall@1 (BASELINE to beat): {b1}/{npos} = {b1/npos:.1%}")
    print(f"  BM25 recall@{K} (CEILING for reranking): {inshort}/{npos} = {inshort/npos:.1%}")
    print(f"  -> the gold is absent from the shortlist {1-inshort/npos:.1%} of the")
    print(f"     time, so a perfect reranker still cannot exceed {inshort/npos:.1%}.")
    return 0


# ---------------------------------------------------------------------------
# rate
# ---------------------------------------------------------------------------

def parse(text):
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None
    try:
        o = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if "choice" not in o:
        return None
    try:
        ch = int(o["choice"])
    except (TypeError, ValueError):
        return None
    return {"choice": ch if 0 <= ch <= K else None,
            "quote": str(o.get("quote") or "")}


def rate(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from llm_provider import query_llm

    items = [json.loads(l) for l in open(args.items, encoding="utf-8") if l.strip()]
    done = set()
    if os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("verdict"):          # only successes count as done
                    done.add((r["rater"], r["id"]))

    fh = open(args.out, "a", encoding="utf-8")
    for spec in args.rater:
        provider, _, model = spec.partition(":")
        todo = [it for it in items if (spec, it["id"]) not in done]
        print(f"\n=== {spec}: {len(todo)} items ===", file=sys.stderr)
        for i, it in enumerate(todo, 1):
            os.environ["AGENT_LLM_PROVIDER"] = provider
            if model:
                os.environ["AGENT_LLM_MODEL"] = model
            else:
                os.environ.pop("AGENT_LLM_MODEL", None)
            passages = "\n\n".join(
                f"[{n}] {c[:args.max_chars]}" for n, c in enumerate(it["candidates"], 1))
            prompt = PROMPT.format(claim=it["claim"], k=K, passages=passages)
            try:
                raw = query_llm(prompt, SYSTEM, timeout=args.timeout)
                err = None
            except Exception as e:  # noqa: BLE001
                raw, err = "", f"{type(e).__name__}: {e}"
            fh.write(json.dumps({"rater": spec, "id": it["id"],
                                 "verdict": parse(raw), "error": err,
                                 "raw": raw[:400]}, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", file=sys.stderr)
    fh.close()
    return 0


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

def score(args):
    items = {i["id"]: i for i in
             (json.loads(l) for l in open(args.items, encoding="utf-8") if l.strip())}
    recs = [json.loads(l) for l in open(args.ratings, encoding="utf-8") if l.strip()]
    by = {(r["rater"], r["id"]): r for r in recs}
    raters = sorted({r["rater"] for r in recs})

    pos = [i for i in items.values() if i["kind"] == "positive"]
    inshort = [i for i in pos if i["gold_in_shortlist"]]
    neg = [i for i in items.values() if i["kind"] == "negative"]
    b1 = sum(1 for i in pos if i["bm25_top1_correct"]) / len(pos) if pos else 0
    ceil = len(inshort) / len(pos) if pos else 0

    print(f"items: {len(pos)} positive ({len(inshort)} with gold in shortlist), "
          f"{len(neg)} negative")
    print(f"BASELINE  BM25 recall@1 : {b1:.1%}")
    print(f"CEILING   BM25 recall@{K} : {ceil:.1%}   (a perfect reranker cannot beat this)")

    for r in raters:
        rows = [(i, by.get((r, i["id"]))) for i in items.values()]
        got = [(i, x["verdict"]) for i, x in rows if x and x.get("verdict")]
        if not got:
            print(f"\n{'='*66}\n{r}: NO USABLE RESPONSES — transport/config failure")
            continue
        print(f"\n{'='*66}\n{r}   parsed {len(got)}/{len(rows)}")

        # --- rerank accuracy, scored only where the gold IS available ---
        sc = [(i, v) for i, v in got if i["kind"] == "positive" and i["gold_in_shortlist"]]
        if sc:
            hit = sum(1 for i, v in sc if v["choice"] == i["gold_pos"])
            acc = hit / len(sc)
            # fair comparison: BM25@1 restricted to the same scoreable subset
            base = sum(1 for i, _ in sc if i["bm25_top1_correct"]) / len(sc)
            # A strict inequality turns a one-item gap into "LOSES TO". Require
            # a margin wider than the ~1 SE binomial noise before calling it.
            se = (base * (1 - base) / len(sc)) ** 0.5
            d = acc - base
            call = ("BEATS" if d > se else "LOSES TO" if d < -se else
                    "INDISTINGUISHABLE FROM")
            print(f"  rerank accuracy      {acc:6.1%}  ({hit}/{len(sc)})")
            print(f"    BM25@1 same subset {base:6.1%}   -> {call} the retriever"
                  f"   (diff {d:+.1%}, 1 SE = {se:.1%})")

        # --- abstention ---
        if neg:
            ng = [(i, v) for i, v in got if i["kind"] == "negative"]
            if ng:
                absta = sum(1 for _, v in ng if v["choice"] == 0) / len(ng)
                print(f"  abstains on negatives {absta:6.1%}  ({sum(1 for _,v in ng if v['choice']==0)}/{len(ng)})")
        pos_abstain = [v for i, v in got if i["kind"] == "positive"]
        if pos_abstain:
            fa = sum(1 for v in pos_abstain if v["choice"] == 0) / len(pos_abstain)
            print(f"  abstains on positives {fa:6.1%}   (over-abstention)")

        # --- the gold-free metric ---
        quoted = [(i, v) for i, v in got if v["choice"] and v["quote"].strip()]
        if quoted:
            bad = 0
            for i, v in quoted:
                ch = i["candidates"][v["choice"] - 1]
                q = norm(v["quote"])
                if len(q) < 25 or q not in norm(ch):
                    bad += 1
            print(f"  QUOTE HALLUCINATION  {bad/len(quoted):6.1%}  ({bad}/{len(quoted)})"
                  f"   <- gold-free; the number that decides usability")
        missing_quote = sum(1 for i, v in got if v["choice"] and not v["quote"].strip())
        if missing_quote:
            print(f"  chose a passage but returned no quote: {missing_quote}")
    print(f"\n{'='*66}\nRerank accuracy is scored only where the gold is in the")
    print("shortlist; items where BM25 missed it entirely are excluded rather than")
    print("counted as model failures. The quote-hallucination rate needs no gold")
    print("and is the metric that transfers to the citation-verification use case.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench_source_extraction.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--mappings", default=MAPPINGS)
    p.add_argument("--cache", default=CACHE)
    p.add_argument("--negatives", type=int, default=30)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--out", default="src_items.jsonl")
    p.set_defaults(func=prepare)

    r = sub.add_parser("rate")
    r.add_argument("--items", required=True)
    r.add_argument("--rater", action="append", required=True)
    r.add_argument("--out", default="src_ratings.jsonl")
    r.add_argument("--max-chars", type=int, default=1400)
    r.add_argument("--timeout", type=int, default=180)
    r.set_defaults(func=rate)

    s = sub.add_parser("score")
    s.add_argument("--items", required=True)
    s.add_argument("--ratings", required=True)
    s.set_defaults(func=score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
