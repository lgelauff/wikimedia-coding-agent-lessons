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
    """Return the candidate annotated with x_verdict/x_score/x_reason."""
    try:
        raw = query_llm(_prompt(focus, c), system=SYSTEM)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        v = json.loads(m.group(0)) if m else {}
        verdict = str(v.get("verdict", "maybe")).lower()
        if verdict not in ("keep", "maybe", "drop"):
            verdict = "maybe"
        score = int(v.get("score", 0))
    except Exception as e:  # a bad LLM reply shouldn't lose the candidate
        verdict, score, v = "maybe", 0, {"reason": f"score-failed: {str(e)[:80]}"}
    return {**c, "x_verdict": verdict, "x_score": max(0, min(100, score)),
            "x_reason": str(v.get("reason", ""))[:200]}


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

    focus = a.focus or (open(a.focus_file, encoding="utf-8").read().strip() if a.focus_file else None)
    if not focus:
        ap.error("provide --focus or --focus-file")

    cands = [json.loads(ln) for ln in open(a.infile, encoding="utf-8") if ln.strip()]
    scored = run(cands, focus, a.limit)
    if a.keep_only:
        scored = [c for c in scored if c["x_verdict"] == "keep"]

    lines = [json.dumps(c, ensure_ascii=False) for c in scored]
    if a.out:
        open(a.out, "w", encoding="utf-8").write("\n".join(lines) + ("\n" if lines else ""))
        kept = sum(1 for c in scored if c["x_verdict"] == "keep")
        print(f"{len(scored)} scored ({kept} keep) -> {a.out}", file=sys.stderr)
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
