#!/usr/bin/env python3
"""Offline checks for the cross-session rate budget (no network, isolated state)."""
import subprocess
import os
import sys
import tempfile
import time

SCRIPTS = "/Users/lodewijk/Documents/GitHub/wikimedia-coding-agent-lessons/agent-tooling/scripts"
sys.path.insert(0, SCRIPTS)

STATE = tempfile.mkdtemp(prefix="ratebudget-")
os.environ["AGENT_RATE_STATE_DIR"] = STATE

import rate_budget as rb  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name} {detail}")
    if not cond:
        fails.append(name)


# --- pure refill -------------------------------------------------------------
check("refill accrues", rb.refill(0, 0, 80, burst=8, refill_seconds=40) == 2.0)
check("refill caps at burst", rb.refill(0, 0, 100000, burst=8, refill_seconds=40) == 8.0)
check("backwards clock mints nothing",
      rb.refill(3, 1000, 500, burst=8, refill_seconds=40) == 3.0)

# --- burst then throttle -----------------------------------------------------
b = rb.RateBudget("test", burst=3, refill_seconds=40, hour_cap=95)
took = 0
for _ in range(5):
    try:
        b.acquire(model="m")
        took += 1
    except rb.RateBudgetExceeded as e:
        wait = e.wait_seconds
        break
check("burst limited to capacity", took == 3, f"took {took}")
check("refusal reports a wait", 0 < wait <= 40, f"{wait:.1f}s")
check("ledger recorded the calls", b.calls_last_hour() == 3, str(b.calls_last_hour()))

# --- hourly backstop overrides available tokens ------------------------------
b2 = rb.RateBudget("cap", burst=50, refill_seconds=0.001, hour_cap=4)
n = 0
try:
    for _ in range(10):
        b2.acquire(model="m")
        n += 1
except rb.RateBudgetExceeded:
    pass
check("hour cap enforced despite tokens", n == 4, f"allowed {n}")

# --- wait=True paces instead of failing --------------------------------------
b3 = rb.RateBudget("wait", burst=1, refill_seconds=1.0, hour_cap=95)
b3.acquire(model="m")
t0 = time.time()
b3.acquire(model="m", wait=True)
dt = time.time() - t0
check("wait=True paced the second call", 0.3 <= dt <= 3.0, f"{dt:.2f}s")

# --- max_wait refuses rather than sleeping forever ---------------------------
b4 = rb.RateBudget("maxwait", burst=1, refill_seconds=600, hour_cap=95)
b4.acquire(model="m")
try:
    b4.acquire(model="m", wait=True, max_wait=2)
    check("max_wait respected", False)
except rb.RateBudgetExceeded:
    check("max_wait respected", True)


# --- concurrency: separate PROCESSES cannot take the same token --------------
# Real subprocesses (not multiprocessing: macOS 'spawn' re-imports this file).
WORKER = os.path.join(STATE, "worker.py")
with open(WORKER, "w") as fh:
    fh.write(f'''import os, sys
os.environ["AGENT_RATE_STATE_DIR"] = {STATE!r}
sys.path.insert(0, {SCRIPTS!r})
import rate_budget as r
b = r.RateBudget("conc", burst=6, refill_seconds=600, hour_cap=95)
got = 0
for _ in range(10):
    try:
        b.acquire(model="m")
        got += 1
    except r.RateBudgetExceeded:
        break
print(got)
''')
procs = [subprocess.Popen([sys.executable, WORKER], stdout=subprocess.PIPE, text=True)
         for _ in range(4)]
total = sum(int(p.communicate()[0].strip() or 0) for p in procs)
check("4 processes shared one 6-token bucket exactly", total == 6, f"total {total}")

# --- status reporting --------------------------------------------------------
s = rb.RateBudget("conc").status()
check("status counts the hour", s["calls_last_hour"] == 6, str(s["calls_last_hour"]))
check("status attributes callers", len(s["by_caller"]) >= 1, str(s["by_caller"]))
b.record("429", model="m", retry_after=30)
check("429s recorded separately", rb.RateBudget("test").status()["rate_limited_last_hour"] == 1)

# --- corrupt state recovers, truncated ledger line tolerated -----------------
with open(rb.RateBudget("corrupt").bucket_path, "w") as fh:
    fh.write("{not json")
rb.RateBudget("corrupt", burst=2, refill_seconds=40).acquire(model="m")
check("corrupt bucket state recovers", True)
with open(rb.RateBudget("corrupt").ledger_path, "a") as fh:
    fh.write('{"ts": "broken\n')
check("truncated ledger line skipped", rb.RateBudget("corrupt").calls_last_hour() == 1)

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
print(f"(state dir: {STATE})")
sys.exit(1 if fails else 0)
