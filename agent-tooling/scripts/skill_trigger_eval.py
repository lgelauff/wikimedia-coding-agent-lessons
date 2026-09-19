#!/usr/bin/env python3
"""skill_trigger_eval.py — does the installed skill library fire correctly?

`conventions.md` §4 asks for `skill-creator` evals on skills with verifiable
output. skill-creator's own trigger eval tests **one skill in isolation** — it
installs a single command file and asks whether a query triggers it. That
measures a description's pull, but it structurally cannot see the failure this
library actually risks: sixteen skills competing, where the wrong one answers.

So this runs each query against the **real installed set** and records *which*
skill fired. Six outcomes:

  HIT      the expected skill fired
  MISS     a skill was expected, none fired          (description too weak)
           — or a playbook was expected and never reached
  CROWDED  a skill was expected, a different one won (descriptions overlap)
           — or a skill fired where a playbook was expected
  OVERFIRE no skill expected, one fired              (description too greedy)
  QUIET    no skill expected, none fired
  PLAYBOOK a playbook was expected and reached, no skill hijacked it

PLAYBOOK exists because a query may expect a playbook rather than a skill (the
D15 demotion moved `liftwing-llm` to `playbooks/liftwing-llm.md`). Without it a
playbook case with no `expect_skill` silently means "no skill should fire" and
never checks the playbook — the opposite of its note.

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


def _route_from_content(items, playbook):
    """Decide routing from one assistant message's content array, or None to keep going.

    Skill outranks prose: a message like `[text("consult playbooks/x.md"), tool_use
    Skill]` is CROWDED, not PLAYBOOK. Scanning items in one pass and returning on the
    first playbook mention would report the opposite of what happened. Pure, so it is
    unit-testable without a live session.
    """
    for item in items:                                   # pass 1: a Skill call wins
        if item.get("type") == "tool_use" and item.get("name") == "Skill":
            return {"fired": item.get("input", {}).get("skill"), "saw_playbook": False}
    for item in items:                                   # pass 2: broken, then reach
        if item.get("type") == "text" and _looks_broken(item.get("text", "")):
            return {"fired": BROKEN, "saw_playbook": False}
        if playbook and (playbook in json.dumps(item.get("input", {}))
                         or playbook in item.get("text", "")):
            return {"fired": None, "saw_playbook": True}
    return None


def which_skill_fires(query, timeout, model=None, cwd=None, plan_mode=False, playbook=None):
    """Run one query; return {"fired": skill|BROKEN|None, "saw_playbook": bool}.

    Returns the *first* Skill tool call. Kills the process immediately after, so
    the task itself never runs. When `playbook` is given (an `expect_playbook`
    case), the target is not a skill: a Skill call means a skill hijacked the
    playbook route, and the run is killed as soon as the playbook path appears in
    a tool input or in prose — so a playbook case does not run the task either.
    """
    # Plan mode looks like the safe choice — the session decides but cannot act.
    # It is not safe for *measurement*: it suppresses routing. Measured on
    # 2026-08-20, the robots.txt query fired agent-tooling:source-connectors
    # without plan mode and fired nothing with it. Running under plan mode
    # produced seven misses that were artifacts of the flag, not of any
    # description. Off by default; --plan-mode exists only to re-check that.
    #
    # The residual risk is what a session does *before* it routes. Observed
    # behaviour is read-only orientation (`git status`), and the process is
    # killed the instant a Skill call appears, so the work itself never runs.
    cmd = ["claude", "-p", query, "--output-format", "stream-json",
           "--verbose", "--include-partial-messages"]
    if plan_mode:
        cmd += ["--permission-mode", "plan"]
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

                # Be patient. A session routinely writes a sentence, or reads a
                # file, before it invokes a skill — an earlier version of this
                # gave up at the first message_stop and scored every query MISS,
                # which read as a total triggering failure and was pure artifact.
                # Only the terminal `result` event ends the search.
                if ev.get("type") == "stream_event":
                    se = ev.get("event", {})
                    t = se.get("type", "")
                    if t == "content_block_start":
                        cb = se.get("content_block", {})
                        if cb.get("type") == "tool_use":
                            pending = cb.get("name")
                            acc = ""
                    elif t == "content_block_delta" and pending:
                        d = se.get("delta", {})
                        if d.get("type") == "input_json_delta":
                            acc += d.get("partial_json", "")
                            if pending == "Skill":
                                name = _skill_from_json(acc)
                                if name:
                                    return {"fired": name, "saw_playbook": False}
                    elif t == "content_block_stop" and pending:
                        if pending == "Skill":
                            name = _skill_from_json(acc)
                            if name:
                                return {"fired": name, "saw_playbook": False}
                        pending = None

                elif ev.get("type") == "assistant":
                    # Precedence (Skill > prose) is decided over the whole message in
                    # _route_from_content, not item-by-item. A broken session answers
                    # every query with an error and no tool call, which scores as MISS
                    # across the board — a harness reporting 0/20 because it cannot run
                    # at all is worse than one that refuses to.
                    routed = _route_from_content(
                        ev.get("message", {}).get("content", []), playbook)
                    if routed:
                        return routed
                elif ev.get("type") == "result":
                    return {"fired": None, "saw_playbook": False}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return {"fired": None, "saw_playbook": False}


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


def classify(expected, fired, expect_playbook=None, saw_playbook=False):
    """Map an expectation and an observation to an outcome.

    A query may expect a *playbook* instead of a skill (the D15 demotion turned
    `liftwing-llm` from a skill into `playbooks/liftwing-llm.md`). A playbook case
    passes only when the playbook is reached and no skill hijacks it; otherwise a
    bare `expect_skill: null` would silently mean "no skill should fire" and the
    case would never check the playbook at all.
    """
    if expect_playbook:
        if fired is not None:
            return "CROWDED"          # a skill fired where a playbook was expected
        return "PLAYBOOK" if saw_playbook else "MISS"
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
    ap.add_argument("--plan-mode", action="store_true",
                    help="run under --permission-mode plan; suppresses routing, see module docstring")
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
        expect_playbook = q.get("expect_playbook")
        votes = [which_skill_fires(q["query"], a.timeout, a.model, a.cwd, a.plan_mode,
                                   expect_playbook)
                 for _ in range(a.runs)]
        fired = Counter(v["fired"] for v in votes).most_common(1)[0][0]
        # Majority, matching `fired`: `any()` would let one lucky run mark a flaky
        # case PLAYBOOK, contradicting the advertised "majority wins".
        saw_playbook = sum(1 for v in votes if v["saw_playbook"]) > len(votes) // 2
        return {"id": q["id"], "expected": q.get("expect_skill"),
                "expect_playbook": expect_playbook,
                "fired": fired, "saw_playbook": saw_playbook, "votes": votes,
                "outcome": classify(q.get("expect_skill"), fired,
                                    expect_playbook, saw_playbook)}

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

    order = {"CROWDED": 0, "OVERFIRE": 1, "MISS": 2, "HIT": 3, "PLAYBOOK": 4, "QUIET": 5}
    results.sort(key=lambda r: (order.get(r["outcome"], 9), r["id"]))

    counts = Counter(r["outcome"] for r in results)
    width = max(len(r["id"]) for r in results)
    print()
    for r in results:
        exp = r["expected"] or r.get("expect_playbook") or "(none)"
        got = r["fired"] or ("playbook" if r.get("saw_playbook") else "(none)")
        flag = "  <-- " if r["outcome"] in ("CROWDED", "OVERFIRE", "MISS") else "      "
        print(f"{r['outcome']:<9} {r['id']:<{width}}  expected={exp:<26} fired={got}{flag}")
    print()
    total = len(results)
    good = counts["HIT"] + counts["QUIET"] + counts["PLAYBOOK"]
    print(f"{good}/{total} correct  |  " + "  ".join(
        f"{k}={counts[k]}" for k in ("HIT", "QUIET", "PLAYBOOK", "MISS", "CROWDED", "OVERFIRE")
        if counts[k]))

    if a.json_out:
        json.dump({"results": results, "counts": dict(counts)},
                  open(a.json_out, "w"), indent=2)
        print(f"wrote {a.json_out}")

    return 0 if good == total else 1


if __name__ == "__main__":
    sys.exit(main())
