#!/usr/bin/env python3
"""score_candidates.py — LLM relevance triage for discovered sources.

The "prioritize" stage: read candidates.jsonl (from source_discovery.py), ask
the LLM to rate each one against a research focus, and write them back sorted
best-first with a verdict (keep/maybe/drop), a 0-100 score, and a one-line
reason. Mirrors AI-effects find_sources.py `fetch_and_score`, but scores from
the candidate's own title+abstract (no fetch needed for triage).

LLM calls go through llm_provider (global AGENT_LLM_PROVIDER; default = your
Claude Code subscription). One call per candidate, sequential and polite.

Usage:
    score_candidates.py --in candidates.jsonl --focus "Studies that USE or
        analyze Polis conversation data" --out scored.jsonl
    score_candidates.py --in c.jsonl --focus-file focus.txt --keep-only --limit 50

Output adds: x_verdict (keep|maybe|drop), x_score (0-100), x_reason.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_provider import query_llm  # noqa: E402

SYSTEM = ("You are a research librarian triaging candidate academic sources for "
          "a literature review. Judge ONLY relevance to the stated focus, from the "
          "title and abstract. Be strict: 'keep' = clearly on-topic and useful; "
          "'maybe' = plausibly relevant but uncertain; 'drop' = off-topic. "
          "Reply with ONLY a JSON object: "
          '{"verdict":"keep|maybe|drop","score":0-100,"reason":"<=20 words"}')


def _prompt(focus: str, c: dict) -> str:
    return (f"FOCUS: {focus}\n\n"
            f"CANDIDATE\nTitle: {c.get('title','')}\n"
            f"Year: {c.get('year','')}\n"
            f"Abstract: {(c.get('abstract') or '(none)')[:1500]}\n\n"
            "Rate relevance to FOCUS as JSON.")


def score_one(focus: str, c: dict) -> dict:
    """Return the candidate annotated with x_verdict/x_score/x_reason.

    Verdict and score are parsed independently: a malformed *score* ("85.0",
    "~90") must NOT downgrade an otherwise-valid `keep` to maybe/0 (which
    --keep-only would then silently drop). x_score_failed flags a total failure
    (LLM/JSON), so the caller can detect a poisoned batch.
    """
    v, failed = {}, False
    try:
        raw = query_llm(_prompt(focus, c), system=SYSTEM)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            v = json.loads(m.group(0))
        else:                       # model returned no JSON object — non-compliant
            v, failed = {"reason": "score-failed: no JSON in reply"}, True
    except Exception as e:  # LLM call / JSON-parse failure: keep the candidate, flag it
        v, failed = {"reason": f"score-failed: {str(e)[:80]}"}, True

    verdict = str(v.get("verdict", "maybe")).lower()
    if verdict not in ("keep", "maybe", "drop"):
        verdict = "maybe"
    try:
        score = int(float(v.get("score", 0)))   # tolerate "85.0", 85, "85"
    except (TypeError, ValueError):
        score = 0
    return {**c, "x_verdict": verdict, "x_score": max(0, min(100, score)),
            "x_reason": str(v.get("reason", ""))[:200], "x_score_failed": failed}


def run(candidates: list[dict], focus: str, limit: int | None = None) -> list[dict]:
    scored = [score_one(focus, c) for c in (candidates[:limit] if limit else candidates)]
    order = {"keep": 0, "maybe": 1, "drop": 2}
    scored.sort(key=lambda c: (order.get(c["x_verdict"], 1), -c["x_score"]))
    return scored


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", required=True, help="candidates.jsonl")
    ap.add_argument("--focus", help="what counts as relevant")
    ap.add_argument("--focus-file", help="read focus from a file")
    ap.add_argument("--out", help="write scored JSONL here (default stdout)")
    ap.add_argument("--keep-only", action="store_true", help="emit only verdict=keep")
    ap.add_argument("--limit", type=int, help="score at most N candidates")
    a = ap.parse_args()

    if a.focus_file:
        with open(a.focus_file, encoding="utf-8") as f:
            focus = f.read().strip()
    else:
        focus = a.focus
    if not focus:
        ap.error("provide --focus or --focus-file")

    with open(a.infile, encoding="utf-8") as f:
        cands = [json.loads(ln) for ln in f if ln.strip()]
    scored = run(cands, focus, a.limit)
    if a.keep_only:
        scored = [c for c in scored if c["x_verdict"] == "keep"]

    failed = sum(1 for c in scored if c.get("x_score_failed"))
    lines = [json.dumps(c, ensure_ascii=False) for c in scored]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        kept = sum(1 for c in scored if c["x_verdict"] == "keep")
        print(f"{len(scored)} scored ({kept} keep) -> {a.out}", file=sys.stderr)
    else:
        print("\n".join(lines))
    if failed:
        # a rate-limit wall / model outage shouldn't pass silently as 'all maybe'
        print(f"WARNING: {failed} candidate(s) failed to score (LLM/parse) — "
              "results may be incomplete; check AGENT_LLM_PROVIDER / rate limits.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
