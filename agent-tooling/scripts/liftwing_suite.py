#!/usr/bin/env python3
"""LiftWing LLM benchmark suite — fully automated, single-file, stdlib-only.

Designed to be BUNDLED (see bundle_liftwing_suite.py) into one standalone file
that is uploaded to Toolforge ONCE and run with one command. No pip install, no
repo checkout, no second upload: the gold data travels inside the file.

Runs the whole sequence unattended:
  - every task in playbooks/liftwing-bench-suite.md that can be scored
    mechanically, on both models
  - probe A (context rot / position)
  - probe B (batching efficiency: 1, 10, 50, 100 items per request)
  - writes results.jsonl (resumable) + report.txt + report.json

Rate control, as requested: starts at 1 request/second, ramps to 2/s after a
clean run of calls, halves on 429 and re-ramps. Every 429 body is logged --
LiftWing open question #1 (the anonymous 429 boundary) has never been observed
because a local bucket always bound first.

Usage on Toolforge:
    python3 liftwing_suite_standalone.py                 # full suite, both models
    python3 liftwing_suite_standalone.py --smoke         # 20 calls, verify first
    python3 liftwing_suite_standalone.py --resume        # continue after a stop
    python3 liftwing_suite_standalone.py --score-only    # re-score existing results

Exit 0 = suite completed. Exit 1 = completed with task failures. Exit 2 = aborted.
"""
from __future__ import annotations

import argparse
import base64
import collections
import csv
import io
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import zlib

# Filled in by the bundler with a zlib+base64 blob of the gold data.
_DATA_BLOB = ""

BASE = ("https://api.wikimedia.org/service/lw/inference/v1/models/"
        "{model}/openai/v1/chat/completions")
MODELS = ["llm-qwen3-14b", "llm-qwen36-27b"]
CTX = {"llm-qwen3-14b": 16000, "llm-qwen36-27b": 32000}
USER_AGENT = os.environ.get(
    "LIFTWING_UA",
    "WikimediaAnalysis/1.0 (benchmark suite; https://github.com/lgelauff/wikimedia-analysis)")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data access — embedded blob when bundled, local repo when developing
# ---------------------------------------------------------------------------

_LOCAL = os.path.expanduser("~/Documents/GitHub/wikimedia-analysis/"
                            "wikipedia-policy-change/data/exploration")
DATA_FILES = [
    "runs/de__wikipedia_dritte_meinung.statements.csv",
    "runs/de__wikipedia_neutraler_standpunkt.statements.csv",
    "runs/en__wikipedia_neutral_point_of_view.statements.csv",
    "runs/en__wikipedia_requests_for_comment.statements.csv",
    "runs/de__wikipedia_neutraler_standpunkt.clean.txt",
    "runs/en__wikipedia_neutral_point_of_view.clean.txt",
    "runs/en__wikipedia_requests_for_comment.clean.txt",
    "runs/de__wikipedia_dritte_meinung.clean.txt",
    "runs/align_de_en_npov.csv",
    "runs/align_de_en_npov_review.csv",
    "nlwiki_stemprocedure/04_statements.csv",
    "nlwiki_stemgerechtigde_gebruikers/04_statements.csv",
]

_cache: dict = {}


def data(rel: str) -> str:
    if not _cache:
        if _DATA_BLOB:
            _cache.update(json.loads(zlib.decompress(base64.b64decode(_DATA_BLOB)).decode()))
        else:
            for f in DATA_FILES:
                p = os.path.join(_LOCAL, f)
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as fh:
                        _cache[f] = fh.read()
    if rel not in _cache:
        raise SystemExit(f"missing bundled data: {rel}")
    return _cache[rel]


def rows(rel: str) -> list:
    return list(csv.DictReader(io.StringIO(data(rel))))


def statements() -> list:
    """All gold statements across pages, with provenance."""
    out = []
    for f in DATA_FILES:
        if not f.endswith("statements.csv"):
            continue
        for r in rows(f):
            r["_src"] = f
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Rate control: 1/s -> 2/s ramp, halve on 429
# ---------------------------------------------------------------------------

class Rate:
    """Token-bucket pacing with a success-driven ramp and 429 backoff.

    Starts deliberately slow (1/s). Toolforge lifts the anonymous 100/h cap but
    the real server limit has never been observed, so the ramp is the probe:
    climb only after sustained success, retreat immediately on 429.
    """

    def __init__(self, start=1.0, target=2.0, ramp_after=60):
        self.rate = start
        self.target = target
        self.ramp_after = ramp_after
        self.streak = 0
        self.next_at = 0.0
        self.events = []

    def wait(self):
        now = time.time()
        if now < self.next_at:
            time.sleep(self.next_at - now)
        self.next_at = time.time() + (1.0 / self.rate)

    def ok(self):
        self.streak += 1
        if self.rate < self.target and self.streak >= self.ramp_after:
            old, self.rate, self.streak = self.rate, min(self.target, self.rate * 2), 0
            self.events.append({"t": time.time(), "event": "ramp",
                                "from": old, "to": self.rate})
            log(f"  rate ramp {old:.2f} -> {self.rate:.2f} req/s")

    def throttled(self, body: str):
        old, self.rate, self.streak = self.rate, max(0.25, self.rate / 2), 0
        self.events.append({"t": time.time(), "event": "429", "from": old,
                            "to": self.rate, "body": body[:500]})
        log(f"  !! 429 — rate {old:.2f} -> {self.rate:.2f} req/s; body: {body[:200]}")
        time.sleep(5)


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class Caller:
    def __init__(self, rate: Rate, timeout=180, retries=3):
        self.rate, self.timeout, self.retries = rate, timeout, retries
        self.calls = 0

    def __call__(self, model: str, system: str, prompt: str, max_tokens=1024):
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.0,
        }).encode()
        last = None
        for attempt in range(self.retries + 1):
            self.rate.wait()
            req = urllib.request.Request(
                BASE.format(model=model), data=payload,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode())
                self.calls += 1
                self.rate.ok()
                raw = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                return {
                    "raw": raw,
                    "text": _THINK.sub("", raw).strip(),
                    "think": "<think>" in raw.lower(),
                    "latency_s": round(time.time() - t0, 2),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "error": None,
                }
            except urllib.error.HTTPError as e:
                text = e.read().decode(errors="replace")
                last = f"HTTP {e.code}: {text[:200]}"
                if e.code == 429:
                    self.rate.throttled(text)
                    continue
                if e.code < 500:
                    break            # 4xx other than 429 will not fix itself
                time.sleep(2 ** attempt + random.random())
            except Exception as e:  # noqa: BLE001 — network; retry
                last = f"{type(e).__name__}: {e}"
                time.sleep(2 ** attempt + random.random())
        return {"raw": "", "text": "", "think": False, "latency_s": None,
                "prompt_tokens": None, "completion_tokens": None, "error": last}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

ONE_LETTER = ("You classify governance rules from Wikipedia policy pages. "
              "You answer with the requested token and nothing else.")
JSON_SYS = ("You extract structured data from Wikipedia policy text. "
            "You output only valid JSON. No prose, no markdown fence.")

DEONTIC = ["obligation", "prohibition", "permission", "condition",
           "principle", "definition", "procedure"]
GOVERNANCE = ["content", "user-user", "user-admin"]
SEGMENT = ["rule", "procedure", "summary", "meta", "principle", "definition"]
PROMINENCE = ["central", "supporting", "context"]


def task_deontic():
    items = [s for s in statements() if s.get("deontic_type") in DEONTIC]
    def prompt(s):
        return (f"Statement: {s['statement_en']}\n\n"
                f"Which one describes it?\n" +
                "\n".join(f"- {d}" for d in DEONTIC) +
                "\n\nAnswer with one word from the list. Nothing else.")
    return {"id": "deontic_type", "tier": "T1", "system": ONE_LETTER,
            "items": items, "prompt": prompt, "gold": lambda s: s["deontic_type"],
            "labels": DEONTIC, "max_tokens": 8, "kind": "label",
            "baseline": "majority", "focus_recall": None}


def task_governance():
    items = [s for s in statements() if s.get("governance_class") in GOVERNANCE]
    def prompt(s):
        return (f"Statement: {s['statement_en']}\n\n"
                "Who does this rule govern?\n"
                "- content: what articles must contain or look like\n"
                "- user-user: how editors treat each other\n"
                "- user-admin: admin/bot powers, procedures, enforcement\n\n"
                "Answer with one of: content, user-user, user-admin. Nothing else.")
    return {"id": "governance_class", "tier": "T1", "system": ONE_LETTER,
            "items": items, "prompt": prompt,
            "gold": lambda s: s["governance_class"], "labels": GOVERNANCE,
            "max_tokens": 8, "kind": "label", "baseline": "majority",
            # asymmetric error: losing user-admin erases the admin-machinery finding
            "focus_recall": "user-admin"}


def task_segment_json():
    items = [s for s in statements()
             if s.get("segment_type") in SEGMENT and s.get("prominence")]
    def prompt(s):
        return (f"Statement: {s['statement_en']}\n\n"
                f"segment_type must be one of: {', '.join(SEGMENT)}\n"
                f"prominence must be one of: {', '.join(PROMINENCE)}\n\n"
                'Return exactly: {"segment_type": "...", "prominence": "..."}')
    return {"id": "segment_json", "tier": "T2", "system": JSON_SYS,
            "items": items, "prompt": prompt,
            "gold": lambda s: {"segment_type": s["segment_type"],
                               "prominence": s["prominence"]},
            "labels": SEGMENT, "max_tokens": 64, "kind": "json",
            "fields": ["segment_type", "prominence"],
            "baseline": "majority", "focus_recall": None}


def task_alignment_canary():
    rev = {r["src_id"]: r["equivalent?"].strip()
           for r in rows("runs/align_de_en_npov_review.csv")}
    al = {r["src_id"]: r for r in rows("runs/align_de_en_npov.csv")}
    items = [dict(al[k], gold=v) for k, v in rev.items() if v in ("y", "p", "n")]
    def prompt(s):
        return (f"Statement A (German Wikipedia): {s['src_statement_en']}\n"
                f"Statement B (English Wikipedia): {s['best_tgt_statement_en']}\n\n"
                "y = same rule   p = related but not the same   n = not the same\n"
                "Answer with one letter. Nothing else.")
    return {"id": "alignment_canary", "tier": "T1", "system": ONE_LETTER,
            "items": items, "prompt": prompt, "gold": lambda s: s["gold"],
            "labels": ["y", "p", "n"], "max_tokens": 4, "kind": "label",
            "baseline": "majority", "focus_recall": None,
            "note": "REGRESSION CANARY — known FAIL (macro-F1 collapse, zero 'n'). "
                    "A sudden pass means a harness bug until proven otherwise."}


TASKS = [task_deontic, task_governance, task_segment_json, task_alignment_canary]


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def probe_position(call, model, sink, limit=12):
    """Probe A — does accuracy fall when the target sits inside a long page?

    Same question at three input sizes; report the DROP from isolated, since the
    absolute number is confounded by task difficulty.
    """
    page = data("runs/en__wikipedia_neutral_point_of_view.clean.txt")
    pad = data("runs/en__wikipedia_requests_for_comment.clean.txt")
    items = [s for s in rows("runs/en__wikipedia_neutral_point_of_view.statements.csv")
             if s.get("governance_class") in GOVERNANCE][:limit]

    for s in items:
        q = (f"\n\nQuestion: for the rule \"{s['statement_en']}\", who does it govern?\n"
             "Answer with one of: content, user-user, user-admin. Nothing else.")
        variants = {"P0_isolated": s["statement_en"] + q,
                    "P1_page": page + q}
        if CTX[model] > 20000:
            for pos, ctx in (("P2_pad_start", pad + "\n\n" + page),
                             ("P2_pad_end", page + "\n\n" + pad)):
                variants[pos] = ctx + q
        for variant, text in variants.items():
            r = call(model, ONE_LETTER, text, max_tokens=8)
            sink({"probe": "position", "variant": variant, "model": model,
                  "src_id": s.get("statement_id"), "gold": s["governance_class"],
                  "pred": norm_label(r["text"], GOVERNANCE),
                  "input_chars": len(text), **strip(r)})


def probe_batching(call, model, sink, n=100):
    """Probe B — same work, different packing. Sets the request shape for all
    later bulk jobs. Alignment failures are disqualifying at any quality."""
    items = [s for s in statements() if s.get("governance_class") in GOVERNANCE][:n]
    for size in (1, 10, 50, 100):
        t0 = time.time()
        for start in range(0, len(items), size):
            chunk = items[start:start + size]
            listing = "\n".join(f"{i+1}. {s['statement_en']}"
                                for i, s in enumerate(chunk))
            p = (f"For each numbered rule, say who it governs "
                 f"(content, user-user, or user-admin).\n\n{listing}\n\n"
                 f"Answer with exactly {len(chunk)} lines, each "
                 f"'<number>. <label>'. No other text.")
            r = call(model, ONE_LETTER, p, max_tokens=16 * len(chunk) + 32)
            preds = parse_numbered(r["text"], len(chunk))
            sink({"probe": "batching", "batch_size": size, "model": model,
                  "chunk_start": start, "n_in": len(chunk),
                  "n_out": sum(1 for p_ in preds if p_ is not None),
                  "aligned": len(preds) == len(chunk),
                  "golds": [s["governance_class"] for s in chunk],
                  "preds": [norm_label(p_, GOVERNANCE) if p_ else None for p_ in preds],
                  "elapsed_total_s": round(time.time() - t0, 1), **strip(r)})


def parse_numbered(text, n):
    """Pull '<i>. <label>' lines. Missing entries stay None so misalignment is
    visible rather than silently shifting every label by one."""
    out = [None] * n
    for line in (text or "").splitlines():
        m = re.match(r"\s*(\d+)\s*[.):-]\s*(.+)", line)
        if m:
            i = int(m.group(1)) - 1
            if 0 <= i < n:
                out[i] = m.group(2).strip()
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def norm_label(text, labels):
    t = (text or "").strip().strip(".,;:!\"'`*").lower()
    if t in labels:
        return t
    for lab in sorted(labels, key=len, reverse=True):
        if re.search(rf"\b{re.escape(lab)}\b", t):
            return lab
    return None


def strip(r):
    return {k: r[k] for k in ("latency_s", "think", "error",
                              "prompt_tokens", "completion_tokens")}


def macro_f1(pairs, labels):
    """Unweighted mean F1 over labels present in gold. Primary metric: it
    penalises a model that collapses onto a frequent class, which plain
    accuracy does not."""
    scores, per = [], {}
    for lab in labels:
        tp = sum(1 for g, p in pairs if g == lab and p == lab)
        fp = sum(1 for g, p in pairs if g != lab and p == lab)
        fn = sum(1 for g, p in pairs if g == lab and p != lab)
        if tp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[lab] = {"precision": round(prec, 3), "recall": round(rec, 3),
                    "f1": round(f1, 3), "n": tp + fn}
        scores.append(f1)
    return (sum(scores) / len(scores) if scores else 0.0), per


def score_all(recs):
    report, results = [], {}
    W = report.append

    tasks = sorted({r["task"] for r in recs if r.get("task")})
    for task in tasks:
        for model in sorted({r["model"] for r in recs if r.get("task") == task}):
            rs = [r for r in recs if r.get("task") == task and r["model"] == model]
            if not rs:
                continue
            labels = rs[0].get("labels") or []
            pairs = [(r["gold"], r["pred"]) for r in rs if isinstance(r["gold"], str)]
            key = f"{task}::{model}"
            W(f"\n{'='*66}\n{task}  [{model}]  n={len(rs)}")
            note = rs[0].get("note")
            if note:
                W(f"  NOTE: {note}")

            if rs[0].get("kind") == "json":
                valid = sum(1 for r in rs if r.get("schema_ok"))
                W(f"  schema-validity   {valid/len(rs):7.1%}   "
                  f"({valid}/{len(rs)} parsed and conformed)")
                for f in rs[0].get("fields", []):
                    fp = [(r["gold"][f], (r["pred"] or {}).get(f))
                          for r in rs if r.get("schema_ok") and isinstance(r["gold"], dict)]
                    if fp:
                        acc = sum(1 for g, p in fp if g == p) / len(fp)
                        W(f"  value-accuracy [{f}]  {acc:7.1%}   (of schema-valid only)")
                results[key] = {"schema_validity": valid / len(rs)}
                continue

            if not pairs:
                continue
            acc = sum(1 for g, p in pairs if g == p) / len(pairs)
            mf1, per = macro_f1(pairs, labels)
            unparsed = sum(1 for r in rs if r["pred"] is None)
            maj = collections.Counter(g for g, _ in pairs).most_common(1)[0]
            used = len({p for _, p in pairs if p})

            W(f"  macro-F1 (PRIMARY) {mf1:7.3f}")
            W(f"  accuracy           {acc:7.1%}   "
              f"(majority baseline {maj[1]/len(pairs):.1%} = always '{maj[0]}')")
            W(f"  parse-failure      {unparsed/len(rs):7.1%}")
            W(f"  labels used        {used}/{len(labels)}"
              + ("   <-- COLLAPSE: model never used some labels" if used < len(labels) else ""))
            fr = rs[0].get("focus_recall")
            if fr and fr in per:
                W(f"  recall[{fr}] {per[fr]['recall']:7.3f}   "
                  f"(asymmetric error — pass >= 0.70)")
            W("  per class:")
            for lab, v in sorted(per.items(), key=lambda kv: -kv[1]["n"]):
                W(f"    {lab:<14} n={v['n']:<4} P={v['precision']:.2f} "
                  f"R={v['recall']:.2f} F1={v['f1']:.2f}")
            results[key] = {"macro_f1": mf1, "accuracy": acc,
                            "majority": maj[1] / len(pairs),
                            "labels_used": used, "of": len(labels),
                            "parse_failure": unparsed / len(rs), "per_class": per}

    # --- probe A ---
    pos = [r for r in recs if r.get("probe") == "position"]
    if pos:
        W(f"\n{'='*66}\nPROBE A — context rot / position")
        for model in sorted({r["model"] for r in pos}):
            base = None
            for variant in ("P0_isolated", "P1_page", "P2_pad_start", "P2_pad_end"):
                v = [r for r in pos if r["model"] == model and r["variant"] == variant]
                if not v:
                    continue
                acc = sum(1 for r in v if r["pred"] == r["gold"]) / len(v)
                if variant == "P0_isolated":
                    base = acc
                drop = f"  drop {base-acc:+.1%}" if base is not None and variant != "P0_isolated" else ""
                W(f"  {model:<16} {variant:<14} acc {acc:6.1%}  "
                  f"~{v[0]['input_chars']//4:>6,} tok{drop}")

    # --- probe B ---
    bat = [r for r in recs if r.get("probe") == "batching"]
    if bat:
        W(f"\n{'='*66}\nPROBE B — batching efficiency")
        W("  adopt the largest batch within 1 SE of size-1 AND with 0 alignment failures")
        for model in sorted({r["model"] for r in bat}):
            for size in sorted({r["batch_size"] for r in bat if r["model"] == model}):
                v = [r for r in bat if r["model"] == model and r["batch_size"] == size]
                pairs = [(g, p) for r in v for g, p in zip(r["golds"], r["preds"])]
                mf1, _ = macro_f1(pairs, GOVERNANCE)
                misaligned = sum(1 for r in v if not r["aligned"])
                toks = sum(r["prompt_tokens"] or 0 for r in v)
                W(f"  {model:<16} batch={size:<4} macro-F1 {mf1:.3f}  "
                  f"calls={len(v):<4} in-tok={toks:<8,} "
                  f"misaligned={misaligned}"
                  + ("  <-- DISQUALIFIED" if misaligned else ""))

    # --- operational ---
    lat = sorted(r["latency_s"] for r in recs if r.get("latency_s"))
    W(f"\n{'='*66}\nOPERATIONAL")
    if lat:
        W(f"  latency  median {lat[len(lat)//2]:.2f}s  "
          f"p90 {lat[int(len(lat)*0.9)]:.2f}s  max {lat[-1]:.2f}s")
    W(f"  <think> blocks seen: {sum(1 for r in recs if r.get('think'))}/{len(recs)}"
      "   (open question 3 — stripper never met a real preamble)")
    errs = [r["error"] for r in recs if r.get("error")]
    W(f"  errors: {len(errs)}" + (f" — first: {errs[0][:140]}" if errs else ""))
    return "\n".join(report), results


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="liftwing_suite")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--report", default="report.txt")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--rate", type=float, default=1.0, help="starting req/s")
    ap.add_argument("--rate-target", type=float, default=2.0, help="ramp ceiling")
    ap.add_argument("--ramp-after", type=int, default=60,
                    help="consecutive successes before doubling the rate")
    ap.add_argument("--smoke", action="store_true",
                    help="~20 calls end to end; verify before the real run")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--skip-probes", action="store_true")
    args = ap.parse_args(argv)

    if args.score_only:
        with open(args.out, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        text, results = score_all(recs)
        print(text)
        open(args.report, "w", encoding="utf-8").write(text)
        json.dump(results, open(args.report.replace(".txt", ".json"), "w"), indent=2)
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rate = Rate(args.rate, args.rate_target, args.ramp_after)
    call = Caller(rate)

    done = set()
    if args.resume and os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    done.add((r.get("task") or r.get("probe"), r.get("model"),
                              str(r.get("src_id")), r.get("variant"),
                              r.get("batch_size"), r.get("chunk_start")))
        log(f"resuming — {len(done)} records already present")

    fh = open(args.out, "a", encoding="utf-8")
    def sink(rec):
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()

    t_start = time.time()
    try:
        for model in models:
            for factory in TASKS:
                t = factory()
                items = t["items"][:5] if args.smoke else t["items"]
                log(f"\n=== {t['id']} [{model}] {len(items)} items ({t['tier']}) ===")
                for i, s in enumerate(items, 1):
                    sid = s.get("statement_id") or s.get("src_id") or str(i)
                    if (t["id"], model, str(sid), None, None, None) in done:
                        continue
                    r = call(model, t["system"], t["prompt"](s), t["max_tokens"])
                    gold = t["gold"](s)
                    if t["kind"] == "json":
                        pred, ok = parse_json(r["text"], t["fields"])
                    else:
                        pred, ok = norm_label(r["text"], t["labels"]), None
                    rec = {"task": t["id"], "tier": t["tier"], "model": model,
                           "src_id": sid, "gold": gold, "pred": pred,
                           "labels": t["labels"], "kind": t["kind"],
                           "fields": t.get("fields"), "schema_ok": ok,
                           "focus_recall": t.get("focus_recall"),
                           "note": t.get("note"), "raw": r["raw"][:300], **strip(r)}
                    sink(rec)
                    if i % 25 == 0 or i == len(items):
                        log(f"  {i}/{len(items)}  rate={rate.rate:.2f}/s  "
                            f"calls={call.calls}  elapsed={time.time()-t_start:.0f}s")
            if not args.skip_probes:
                log(f"\n=== probe A: position [{model}] ===")
                probe_position(call, model, sink, limit=3 if args.smoke else 12)
                log(f"\n=== probe B: batching [{model}] ===")
                probe_batching(call, model, sink, n=10 if args.smoke else 100)
    except KeyboardInterrupt:
        log("\ninterrupted — re-run with --resume")
        fh.close()
        return 2
    finally:
        fh.close()

    with open(args.out, encoding="utf-8") as f2:
        recs = [json.loads(l) for l in f2 if l.strip()]
    text, results = score_all(recs)
    text += (f"\n\nrate events: {json.dumps(rate.events)[:1500]}"
             f"\ntotal calls: {call.calls}   wall-clock: {time.time()-t_start:.0f}s")
    print(text)
    open(args.report, "w", encoding="utf-8").write(text)
    json.dump(results, open(args.report.replace(".txt", ".json"), "w"), indent=2)
    log(f"\nwrote {args.out}, {args.report}")
    return 0


def parse_json(text, fields):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        return None, False
    try:
        obj = json.loads(m.group())
    except json.JSONDecodeError:
        return None, False
    return obj, all(f in obj for f in fields)


if __name__ == "__main__":
    sys.exit(main())
