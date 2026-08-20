#!/usr/bin/env python3
"""Measure whether a cheap model can SUBSTITUTE for an expensive one as a reviewer.

Reviewing a diff, a paragraph, or a paper has no ground truth. Our own bug-fix
commits are not gold either: they are one developer's judgement at one moment,
and commit messages routinely misdescribe what was actually wrong. Inventing a
ground truth there would manufacture precision that does not exist.

So this measures agreement, not correctness -- and reports the one number that
makes agreement interpretable: **the ceiling**.

  If the two reference models agree with each other at kappa=0.40, then a
  subject model at kappa=0.35 is as good as any rater, and the honest reading
  is "nobody agrees about this task", not "the small model is bad."

Most agreement studies omit that ceiling. Without it a low subject score is
uninterpretable.

Three things it reports:
  1. pairwise Cohen's kappa between every pair of raters (chance-corrected --
     raw agreement % is meaningless when 90% of items are 'no issue')
  2. reference-vs-reference kappa: THE CEILING
  3. invented-issue rate on null-control items that are functionally identical
     by construction, so any issue flagged is a false positive

Raters are whatever `llm_provider` backends are configured; use at least two
reference families (claude-code + mistral/openrouter). Same-family references
are near-worthless -- their errors correlate (see feedback/liftwing.md,
"agreement-as-confidence: REFUTED").

Usage:
  bench_agreement.py collect --repo ~/Documents/GitHub/dp --n 40 --out items.jsonl
  bench_agreement.py rate --items items.jsonl --rater liftwing:llm-qwen3-14b \
                          --rater claude-code: --out ratings.jsonl
  bench_agreement.py score --ratings ratings.jsonl \
                          --reference claude-code: --reference mistral:
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import re
import subprocess
import sys

CATEGORIES = ["correctness", "security", "performance", "style", "none"]

SYSTEM = ("You review code changes. You reply with one JSON object and nothing "
          "else -- no prose, no markdown fence.")

PROMPT = """\
Review this change.

```diff
{diff}
```

Reply with exactly this JSON:
{{"issue_present": true or false,
  "category": one of {cats},
  "severity": integer 1-5 (1 = trivial, 5 = critical; use 1 if no issue),
  "one_line": "at most 15 words"}}

Only report an issue you can point to in this diff. If the change looks fine,
say issue_present false and category "none"."""


# ---------------------------------------------------------------------------
# Item collection
# ---------------------------------------------------------------------------

def git(repo, *args):
    """Never raises on a binary blob — repos contain images, fonts, archives."""
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True).stdout
    return out.decode("utf-8", errors="replace")


def collect(args):
    """Real diffs, plus null controls that cannot contain a real issue.

    Null controls are built by renaming a local identifier consistently through
    an unchanged file, producing a diff that is functionally identical by
    construction. Anything flagged on those is invented.
    """
    rng = random.Random(args.seed)
    per_repo = max(1, args.n // len(args.repo))
    items = []
    for repo in args.repo:
        shas = [l.split()[0] for l in
                git(repo, "log", "--no-merges", "--format=%H %s",
                    f"-{per_repo * 8}").splitlines() if l.strip()]
        rng.shuffle(shas)
        got = 0
        for sha in shas:
            if got >= per_repo:
                break
            diff = git(repo, "show", "--format=%s", "--unified=6", sha)
            if not (args.min_chars <= len(diff) <= args.max_chars):
                continue
            if diff.count("diff --git") != 1:      # single-file changes only
                continue
            # binary blobs and replacement chars carry no reviewable content
            if "Binary files" in diff or "\ufffd" in diff:
                continue
            got += 1
            items.append({"id": f"real:{os.path.basename(repo)}:{sha[:10]}",
                          "kind": "real", "repo": os.path.basename(repo),
                          "_path": repo, "_sha": sha, "diff": diff})

    # --- null controls ---
    # Prefer rename-nulls: they LOOK like substantive changes, so they actually
    # test whether a reviewer invents problems. A blank-line null is trivially
    # obvious and every rater passes it, which measures nothing — those are
    # tagged separately and reported apart.
    nulls, kinds = 0, []
    for pass_ in ("rename", "blank"):
        for it in list(items):
            if nulls >= args.nulls or it["kind"] != "real":
                continue
            if any(k["id"] == "null:" + it["id"][5:] for k in items if k["kind"] != "real"):
                continue
            null = (_rename_ident(it["diff"], rng, it.get("_path"), it.get("_sha"))
                    if pass_ == "rename" else _blank_line_noop(it["diff"]))
            if null:
                items.append({"id": f"null:{it['id'][5:]}", "kind": "null",
                              "null_kind": pass_, "repo": it["repo"], "diff": null})
                kinds.append(pass_)
                nulls += 1

    with open(args.out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps({k: v for k, v in it.items()
                                 if not k.startswith("_")},
                                ensure_ascii=False) + "\n")
    import collections as _c
    kc = _c.Counter(kinds)
    print(f"wrote {args.out}: {len(items)-nulls} real + {nulls} null-control "
          f"items ({dict(kc)})")
    if kc.get("blank"):
        print(f"  NOTE: {kc['blank']} nulls are blank-line inserts — trivially "
              f"obvious, so they test little. The {kc.get('rename',0)} rename "
              f"nulls are the real false-positive probe.")
    return 0


# Assignment/binding forms across the languages in these repos.
_IDENT = re.compile(
    r"^\+\s*(?:const|let|var|final|my)?\s*(\w+)\s*(?:=[^=]|:=)"
    r"|^\+\s*(?:def|function|func)\s+(\w+)\s*\(")

_KEYWORDS = {"if", "for", "while", "return", "else", "with", "try", "self",
             "this", "true", "false", "null", "none", "import", "from"}


def _rename_ident(diff, rng, repo=None, sha=None):
    """Rename an identifier consistently — ONLY when provably safe.

    An earlier version renamed on +/- lines only and left context lines alone.
    That silently created undefined-variable bugs: a parameter declared on a
    context line kept its old name while the body referenced the new one. The
    "null control" then contained a genuine severe defect, and a model that
    correctly reported it would have been scored as inventing an issue —
    penalising the better model. Caught by qwen36-27b on 2026-08-15.

    Two conditions now make the rename safe:
      1. every occurrence of the identifier in the whole file at that revision
         is inside this diff (so nothing outside can break), and
      2. the substitution is applied to EVERY line of the diff, context lines
         included.
    If the file cannot be read to verify (1), no rename null is produced.
    """
    if not (repo and sha):
        return None
    path = None
    for line in diff.splitlines():
        m = re.match(r"\+\+\+ b/(.+)", line)
        if m:
            path = m.group(1)
            break
    if not path:
        return None
    full = git(repo, "show", f"{sha}:{path}")
    if not full:
        return None

    names = []
    for line in diff.splitlines():
        m = _IDENT.match(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        if name and len(name) > 3 and not name.isupper() and name.lower() not in _KEYWORDS:
            names.append(name)
    rng.shuffle(names)

    diff_body = "\n".join(l for l in diff.splitlines()
                          if l.startswith(("+", "-", " "))
                          and not l.startswith(("+++", "---")))
    for old in names:
        pat = rf"\b{re.escape(old)}\b"
        in_file = len(re.findall(pat, full))
        in_added = len(re.findall(pat, "\n".join(
            l for l in diff.splitlines()
            if l.startswith("+") and not l.startswith("+++"))))
        # Every occurrence in the post-image file must be one we are rewriting.
        if in_file == 0 or in_file != in_added:
            continue
        out = []
        for line in diff.splitlines():
            if line.startswith(("+", "-", " ")) and not line.startswith(("+++", "---")):
                line = re.sub(pat, f"{old}_r", line)
            out.append(line)
        return "\n".join(out)
    return None


def _blank_line_noop(diff):
    """Fallback: keep only context, re-emitted as an added blank line + context.

    Produces a diff whose sole effect is inserting one empty line — a change no
    correctness, security, or performance review can legitimately object to.
    """
    lines = diff.splitlines()
    head = [l for l in lines if l.startswith(("diff --git", "index ", "--- ", "+++ "))]
    ctx = [l for l in lines if l.startswith(" ")][:12]
    if len(head) < 2 or len(ctx) < 4:
        return None
    hunk = f"@@ -1,{len(ctx)} +1,{len(ctx)+1} @@"
    mid = len(ctx) // 2
    body = ctx[:mid] + ["+"] + ctx[mid:]
    return "\n".join(head + [hunk] + body)


def _make_noop_diff(diff, rng):
    """A diff that is functionally identical by construction.

    Anything a reviewer flags here as a correctness/security/performance issue
    is invented. (Style objections are excluded from the false-positive count —
    "this comment is unnecessary" is an opinion, not a hallucinated bug.)
    """
    return _rename_ident(diff, rng) or _blank_line_noop(diff)


# ---------------------------------------------------------------------------
# Rating
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
    if "issue_present" not in o:
        return None
    cat = str(o.get("category", "none")).lower().strip()
    return {"issue_present": bool(o["issue_present"]),
            "category": cat if cat in CATEGORIES else "none",
            "severity": int(o["severity"]) if str(o.get("severity", "")).isdigit() else 1,
            "one_line": str(o.get("one_line", ""))[:120]}


def rate(args):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from llm_provider import query_llm

    items = [json.loads(l) for l in open(args.items, encoding="utf-8") if l.strip()]
    # Only a SUCCESSFUL rating counts as done. Recording an error and then
    # skipping it on resume means fixing the cause changes nothing — the
    # re-run quietly keeps the failures. (Bit us 2026-08-15: both reference
    # raters failed on config, and a re-run would have skipped all 152.)
    done = set()
    if os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("verdict"):
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
            prompt = PROMPT.format(diff=it["diff"][:args.max_chars],
                                   cats=CATEGORIES)
            try:
                raw = query_llm(prompt, SYSTEM, timeout=args.timeout)
                err = None
            except Exception as e:  # noqa: BLE001 — record, never abort
                raw, err = "", f"{type(e).__name__}: {e}"
            v = parse(raw)
            fh.write(json.dumps({"rater": spec, "id": it["id"], "kind": it["kind"],
                                 "null_kind": it.get("null_kind"),
                                 "verdict": v, "error": err,
                                 "raw": raw[:300]}, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", file=sys.stderr)
    fh.close()
    return 0


# ---------------------------------------------------------------------------
# Agreement statistics
# ---------------------------------------------------------------------------

def cohen_kappa(a, b):
    """Chance-corrected agreement between two raters over paired labels."""
    labels = sorted(set(a) | set(b))
    n = len(a)
    if n == 0 or len(labels) < 2:
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def fleiss_kappa(matrix):
    """Multi-rater nominal agreement. matrix[item][label] = count of raters."""
    n_items = len(matrix)
    if not n_items:
        return float("nan")
    n_raters = sum(matrix[0])
    if n_raters < 2:
        return float("nan")
    p_j = [sum(row[j] for row in matrix) / (n_items * n_raters)
           for j in range(len(matrix[0]))]
    P_i = [(sum(c * c for c in row) - n_raters) / (n_raters * (n_raters - 1))
           for row in matrix]
    P_bar = sum(P_i) / n_items
    P_e = sum(p * p for p in p_j)
    return (P_bar - P_e) / (1 - P_e) if P_e < 1 else float("nan")


def interpret(k):
    if k != k:
        return "n/a"
    for t, s in ((0.81, "almost perfect"), (0.61, "substantial"), (0.41, "moderate"),
                 (0.21, "fair"), (0.01, "slight")):
        if k >= t:
            return s
    return "none/worse than chance"


def score(args):
    recs = [json.loads(l) for l in open(args.ratings, encoding="utf-8") if l.strip()]
    raters = sorted({r["rater"] for r in recs})
    refs = [r for r in args.reference if r in raters]
    subjects = [r for r in raters if r not in refs]

    by = {(r["rater"], r["id"]): r for r in recs}
    ids = sorted({r["id"] for r in recs})
    real = [i for i in ids if i.startswith("real:")]
    nulls = [i for i in ids if i.startswith("null:")]

    def labels(rater, id_list, field="issue_present"):
        out = []
        for i in id_list:
            v = by.get((rater, i), {}).get("verdict")
            out.append(str(v[field]) if v else "PARSE-FAIL")
        return out

    MIN_PARSE = 0.5

    def usable(rater):
        """A rater below half-parsed cannot be compared to anything.

        Without this the scorer happily prints kappa +0.000 against a column
        of PARSE-FAIL and labels it "worse than chance" -- presenting a broken
        API key as a model result.
        """
        got = [by.get((rater, i)) for i in ids]
        ok = sum(1 for g in got if g and g.get("verdict"))
        return ok / len(ids) >= MIN_PARSE if ids else False

    print(f"raters: {len(raters)}   items: {len(real)} real, {len(nulls)} null")
    print(f"references: {refs or '(none given -- pass --reference)'}")
    print(f"subjects:   {subjects}")

    # --- coverage / parse reliability ---
    print(f"\n{'='*70}\nRESPONSE RELIABILITY")
    for r in raters:
        got = [by.get((r, i)) for i in ids]
        ok = sum(1 for g in got if g and g.get("verdict"))
        print(f"  {r:<28} parsed {ok}/{len(ids)} ({ok/len(ids):.0%})")

    # --- THE CEILING ---
    print(f"\n{'='*70}\nCEILING — reference vs reference (issue_present, real items)")
    ceiling = float("nan")
    refs_ok = [r for r in refs if usable(r)]
    dead = [r for r in refs if r not in refs_ok]
    if dead:
        print(f"  EXCLUDED (parsed <{MIN_PARSE:.0%}): {dead}")
        print("  These raters produced no usable verdicts -- a transport/config")
        print("  failure, not a model result. Fix and re-rate; do not interpret.")
    if len(refs_ok) >= 2:
        ks = []
        for x, y in itertools.combinations(refs_ok, 2):
            k = cohen_kappa(labels(x, real), labels(y, real))
            ks.append(k)
            print(f"  {x} <-> {y}:  kappa {k:+.3f}  ({interpret(k)})")
        ceiling = sum(ks) / len(ks)
        print(f"\n  CEILING (mean reference-reference kappa): {ceiling:+.3f}")
        print("  Read every subject score against this, not against 1.0.")
    else:
        print("  NOT COMPUTABLE — need >=2 reference raters from different families.")
        print("  Without it, subject kappas below are UNINTERPRETABLE.")

    # --- subjects vs references ---
    print(f"\n{'='*70}\nSUBSTITUTABILITY — subject vs each reference (real items)")
    if not refs_ok:
        print("  SKIPPED — no usable reference rater. Subject kappas would be")
        print("  computed against failures and would mean nothing.")
    subjects_ok = [s for s in subjects if usable(s)]
    for s in [x for x in subjects if x not in subjects_ok]:
        print(f"  {s:<28} EXCLUDED (parsed <{MIN_PARSE:.0%}) — no verdict issued")
    # A ceiling this low means the raters barely agree with EACH OTHER, so
    # "% of ceiling" divides by near-zero and yields nonsense (a subject at
    # kappa 0.21 against a 0.138 ceiling reads as "150% — SUBSTITUTABLE").
    CEILING_FLOOR = 0.20
    if refs_ok and ceiling == ceiling and ceiling < CEILING_FLOOR:
        print(f"\n  !! CEILING {ceiling:+.3f} IS BELOW {CEILING_FLOOR:.2f} — NO VERDICT ISSUED.")
        print("  The reference raters barely agree with each other, so there is no")
        print("  stable signal to substitute FOR. Percent-of-ceiling would divide by")
        print("  near-zero and manufacture a confident answer from noise.")
        print("  Read this as 'the task as posed is not measurable', not as a")
        print("  result about any model.\n")
    for s in (subjects_ok if refs_ok else []):
        ks = []
        for ref in refs_ok:
            k = cohen_kappa(labels(s, real), labels(ref, real))
            ks.append(k)
            print(f"  {s:<28} vs {ref:<20} kappa {k:+.3f}  ({interpret(k)})")
        if ks and ceiling == ceiling:
            m = sum(ks) / len(ks)
            if ceiling < CEILING_FLOOR:
                print(f"  {'':<28} mean {m:+.3f}   (no verdict — ceiling too low)\n")
            else:
                pct = m / ceiling
                verdict = ("SUBSTITUTABLE" if pct >= 0.85 else
                           "partial" if pct >= 0.6 else "NOT substitutable")
                print(f"  {'':<28} mean {m:+.3f} = {pct:.0%} of ceiling  -> {verdict}\n")

    # --- all-rater agreement ---
    print(f"{'='*70}\nALL-RATER AGREEMENT (Fleiss kappa, issue_present, real items)")
    mat = []
    for i in real:
        row = [0, 0]
        for r in raters:
            v = by.get((r, i), {}).get("verdict")
            if v:
                row[1 if v["issue_present"] else 0] += 1
        if sum(row) == len(raters):
            mat.append(row)
    if mat:
        print(f"  Fleiss kappa {fleiss_kappa(mat):+.3f} over {len(mat)} complete items")

    # --- the null control ---
    print(f"\n{'='*70}\nNULL CONTROL — invented-issue rate")
    if not nulls:
        print("  no null items; re-collect with --nulls N")
    else:
        print("  These diffs are functionally identical by construction.")
        print("  A flagged correctness/security/performance issue is INVENTED.")
        print("  Style objections are excluded — an opinion is not a hallucination.\n")
        substantive = {"correctness", "security", "performance"}
        rename_ids = [i for i in nulls
                      if (by.get((raters[0], i)) or {}).get("null_kind") == "rename"]
        if rename_ids:
            print(f"  ({len(rename_ids)} of {len(nulls)} are rename-nulls — the "
                  f"ones that look substantive and actually probe this)\n")
        for r in raters:
            vs = [by.get((r, i), {}).get("verdict") for i in nulls]
            vs = [v for v in vs if v]
            if not vs:
                continue
            bad = [v for v in vs if v["issue_present"] and v["category"] in substantive]
            style = sum(1 for v in vs if v["issue_present"] and v["category"] not in substantive)
            sev = [v["severity"] for v in bad]
            print(f"  {r:<28} invented {len(bad)/len(vs):.0%} "
                  f"({len(bad)}/{len(vs)})   style-only {style}"
                  + (f"   mean severity {sum(sev)/len(sev):.1f}" if sev else ""))
        print("\n  A reviewer that flags clean changes costs more time than it saves.")
        print("  This will NOT show up in the kappa numbers if every rater is")
        print("  equally trigger-happy -- high agreement on invented issues is")
        print("  still high agreement.")

    # --- flag rate, for context on the kappas ---
    print(f"\n{'='*70}\nFLAG RATE on real items (context for the kappas above)")
    for r in raters:
        vs = [by.get((r, i), {}).get("verdict") for i in real]
        vs = [v for v in vs if v]
        if vs:
            print(f"  {r:<28} flags {sum(1 for v in vs if v['issue_present'])/len(vs):.0%}")
    rates = {}
    for r in raters:
        vs = [v for v in (by.get((r, i), {}).get("verdict") for i in real) if v]
        if vs:
            rates[r] = sum(1 for v in vs if v["issue_present"]) / len(vs)
    if rates and min(rates.values()) > 0 and max(rates.values()) / min(rates.values()) >= 3:
        hi = max(rates, key=rates.get)
        lo = min(rates, key=rates.get)
        print(f"\n  !! CONFOUND: flag rates differ {max(rates.values())/min(rates.values()):.1f}x "
              f"({hi} {rates[hi]:.0%} vs {lo} {rates[lo]:.0%}).")
        print("  Cohen's kappa between raters with very different base rates is")
        print("  structurally near zero REGARDLESS of judgement quality. The low")
        print("  kappas above are substantially explained by this, not by the")
        print("  raters disagreeing case by case.")

    print(f"\n{'='*70}\nHigh agreement means SUBSTITUTABLE, not CORRECT. Both models")
    print("can be confidently wrong together -- see the correlated-error result in")
    print("feedback/liftwing.md. Keep those two claims apart when writing this up.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bench_agreement.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect")
    c.add_argument("--repo", action="append", required=True,
                   help="repo path (repeatable — more repos yield more rename-nulls)")
    c.add_argument("--n", type=int, default=40)
    c.add_argument("--nulls", type=int, default=10)
    c.add_argument("--min-chars", type=int, default=300)
    c.add_argument("--max-chars", type=int, default=6000)
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--out", default="items.jsonl")
    c.set_defaults(func=collect)

    r = sub.add_parser("rate")
    r.add_argument("--items", required=True)
    r.add_argument("--rater", action="append", required=True,
                   help="provider:model (repeatable), e.g. liftwing:llm-qwen3-14b")
    r.add_argument("--out", default="ratings.jsonl")
    r.add_argument("--max-chars", type=int, default=6000)
    r.add_argument("--timeout", type=int, default=180)
    r.set_defaults(func=rate)

    s = sub.add_parser("score")
    s.add_argument("--ratings", required=True)
    s.add_argument("--reference", action="append", default=[],
                   help="rater specs to treat as references (repeatable)")
    s.set_defaults(func=score)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
