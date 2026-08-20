#!/usr/bin/env python3
"""skill_trigger_eval.py — does the installed skill library fire correctly?

`conventions.md` §4 asks for `skill-creator` evals on skills with verifiable
output. skill-creator's own trigger eval tests **one skill in isolation** — it
installs a single command file and asks whether a query triggers it. That
measures a description's pull, but it structurally cannot see the failure this
library actually risks: sixteen skills competing, where the wrong one answers.

So this runs each query against the **real installed set** and records *which*
skill fired. Five outcomes:

  HIT      the expected skill fired
  MISS     a skill was expected, none fired          (description too weak)
  CROWDED  a skill was expected, a different one won (descriptions overlap)
  OVERFIRE no skill expected, one fired              (description too greedy)
  QUIET    no skill expected, none fired

CROWDED is the one worth building this for. It is invisible to any per-skill
eval, and it is the predictable consequence of adding skills whose descriptions
claim overlapping territory.

Nothing is executed: the run is killed the moment a skill is chosen, so this
measures the routing decision and never the work.

Usage:
    python3 skill_trigger_eval.py --evals ../evals/trigger-evals.json
    python3 skill_trigger_eval.py --evals FILE --runs 3 --workers 4
    python3 skill_trigger_eval.py --evals FILE --only pageview-series

Exit: 0 if every query lands as expected, 1 otherwise, 2 on usage error.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor


BROKEN = "__SESSION_BROKEN__"
_BROKEN_SIGNS = ("failed to authenticate", "oauth access token",
                 "api error: 401", "api error: 403", "credit balance",
                 "usage limit", "rate limit exceeded")


def _looks_broken(text):
    """True when the subprocess could not run the query at all.

    Distinguishing 'the model declined to use a skill' from 'the session never
    worked' matters: both produce zero tool calls, and only one is a finding.
    """
    low = text.lower()
    return any(s in low for s in _BROKEN_SIGNS)


def which_skill_fires(query, timeout, model=None, cwd=None):
    """Run one query; return the skill name that fired, or None.

    Returns the *first* Skill tool call. Kills the process immediately after,
    so the task itself never runs.
    """
    cmd = ["claude", "-p", query, "--output-format", "stream-json",
           "--verbose", "--include-partial-messages"]
    if model:
        cmd += ["--model", model]
    # CLAUDECODE guards interactive nesting; a subprocess run is safe.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            cwd=cwd or os.getcwd(), env=env)
    buf, pending, acc = "", None, ""
    start = time.time()
    try:
        while time.time() - start < timeout:
            if proc.poll() is not None:
                rest = proc.stdout.read()
                if rest:
                    buf += rest.decode("utf-8", errors="replace")
                break
            chunk = proc.stdout.read1(8192) if hasattr(proc.stdout, "read1") else proc.stdout.read(8192)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if ev.get("type") == "stream_event":
                    se = ev.get("event", {})
                    t = se.get("type", "")
                    if t == "content_block_start":
                        cb = se.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            if cb.get("name") == "Skill":
                                pending, acc = "Skill", ""
                            else:
                                # a non-Skill tool call means routing is settled
                                return None
                    elif t == "content_block_delta" and pending:
                        d = se.get("delta", {})
                        if d.get("type") == "input_json_delta":
                            acc += d.get("partial_json", "")
                            if '"' in acc and acc.count('"') >= 4:
                                name = _skill_from_json(acc)
                                if name:
                                    return name
                    elif t in ("content_block_stop", "message_stop"):
                        if pending:
                            return _skill_from_json(acc)
                        if t == "message_stop":
                            return None

                elif ev.get("type") == "assistant":
                    for item in ev.get("message", {}).get("content", []):
                        if item.get("type") == "tool_use" and item.get("name") == "Skill":
                            return item.get("input", {}).get("skill")
                        # A broken session answers every query with an error and no
                        # tool call, which scores as MISS across the board — a
                        # harness reporting 0/20 because it cannot run at all is
                        # worse than one that refuses to.
                        if item.get("type") == "text" and _looks_broken(item.get("text", "")):
                            return BROKEN
                    return None
                elif ev.get("type") == "result":
                    return None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return None


def _skill_from_json(partial):
    """Pull the skill name out of possibly-truncated tool-input JSON."""
    try:
        return json.loads(partial).get("skill")
    except json.JSONDecodeError:
        pass
    marker = '"skill"'
    i = partial.find(marker)
    if i == -1:
        return None
    rest = partial[i + len(marker):]
    j, k = rest.find('"'), None
    if j != -1:
        k = rest.find('"', j + 1)
    return rest[j + 1:k] if k and k > j else None


def classify(expected, fired):
    if expected is None:
        return "QUIET" if fired is None else "OVERFIRE"
    if fired is None:
        return "MISS"
    # plugin-qualified names ("agent-tooling:pr-check") count as a match
    return "HIT" if fired.split(":")[-1] == expected else "CROWDED"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evals", required=True)
    ap.add_argument("--runs", type=int, default=1, help="runs per query (majority wins)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--model", default=None)
    ap.add_argument("--cwd", default=None, help="directory to run in (skills resolve from here)")
    ap.add_argument("--only", default=None, help="run a single query id")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    try:
        spec = json.load(open(a.evals))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read eval set: {e}", file=sys.stderr)
        return 2
    queries = spec.get("queries", [])
    if a.only:
        queries = [q for q in queries if q["id"] == a.only]
    if not queries:
        print("no queries to run", file=sys.stderr)
        return 2

    def one(q):
        votes = [which_skill_fires(q["query"], a.timeout, a.model, a.cwd)
                 for _ in range(a.runs)]
        fired = Counter(votes).most_common(1)[0][0]
        return {"id": q["id"], "expected": q.get("expect_skill"),
                "fired": fired, "votes": votes,
                "outcome": classify(q.get("expect_skill"), fired)}

    print(f"running {len(queries)} queries x{a.runs} ...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(one, queries))

    broken = [r for r in results if r["fired"] == BROKEN]
    if broken:
        print(f"\nABORTED — the eval subprocess could not run "
              f"({len(broken)}/{len(results)} queries returned a session error).\n"
              f"Every query would score MISS, which would look like a library-wide\n"
              f"triggering failure rather than a broken harness. Fix the session\n"
              f"(usually: re-authenticate the CLI) and re-run.", file=sys.stderr)
        return 2

    order = {"CROWDED": 0, "OVERFIRE": 1, "MISS": 2, "HIT": 3, "QUIET": 4}
    results.sort(key=lambda r: (order.get(r["outcome"], 9), r["id"]))

    counts = Counter(r["outcome"] for r in results)
    width = max(len(r["id"]) for r in results)
    print()
    for r in results:
        exp = r["expected"] or "(none)"
        got = r["fired"] or "(none)"
        flag = "  <-- " if r["outcome"] in ("CROWDED", "OVERFIRE", "MISS") else "      "
        print(f"{r['outcome']:<9} {r['id']:<{width}}  expected={exp:<26} fired={got}{flag}")
    print()
    total = len(results)
    good = counts["HIT"] + counts["QUIET"]
    print(f"{good}/{total} correct  |  " + "  ".join(
        f"{k}={counts[k]}" for k in ("HIT", "QUIET", "MISS", "CROWDED", "OVERFIRE") if counts[k]))

    if a.json_out:
        json.dump({"results": results, "counts": dict(counts)},
                  open(a.json_out, "w"), indent=2)
        print(f"wrote {a.json_out}")

    return 0 if good == total else 1


if __name__ == "__main__":
    sys.exit(main())
