#!/usr/bin/env python3
"""Cross-session rate budget for a shared API quota (LiftWing LLM by default).

The problem: several agent sessions run concurrently, each is a separate OS
process, and none can see the others' API usage. A 100 req/hour ceiling cannot
be honoured by discipline — one session burning the hour strands every other
one. So the budget lives in a FILE that every caller must pass through, guarded
by an flock so concurrent processes cannot race the same token.

Mechanism: a token bucket.

    refill  1 token per REFILL_SECONDS (default 40 s -> 90/hour, headroom
            under the documented 100/hour anonymous cap)
    burst   BURST tokens (default 8) — short bursts are allowed when the quota
            is genuinely idle, but no single session can ever hold more than
            this, which is what stops one session draining the hour.
    backstop  a trailing-60-minute count from the ledger, refused above
            HOUR_CAP (default 95). Cheap, and it catches clock jumps or a
            bucket-math bug against the number that actually matches the docs.

A second file — the ledger — records one line per call for attribution, which
is how you answer "which sessions are using this API":

    {"ts":…, "event":"call"|"429"|"error", "session":…, "project":…,
     "pid":…, "model":…}

Files (override with $AGENT_RATE_STATE_DIR):
    ~/.claude/<name>-bucket.json     enforcement state
    ~/.claude/<name>-usage.jsonl     attribution ledger

Usage:
    rate_budget.py --status                 # who used what, and headroom now
    rate_budget.py --status --json
    rate_budget.py --reset                  # clear bucket + ledger (asks first)

From code:
    from rate_budget import RateBudget, RateBudgetExceeded
    b = RateBudget("liftwing")
    b.acquire(model="llm-qwen3-14b")            # raises if no token
    b.acquire(model="…", wait=True)             # or paces automatically
    b.record("429", model="…", retry_after=30)
"""
import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime

BURST = float(os.environ.get("AGENT_RATE_BURST", 8))
REFILL_SECONDS = float(os.environ.get("AGENT_RATE_REFILL_SECONDS", 40))
HOUR_CAP = int(os.environ.get("AGENT_RATE_HOUR_CAP", 95))
HOUR = 3600.0


class RateBudgetExceeded(RuntimeError):
    """No token available (and the caller asked not to wait)."""

    def __init__(self, msg, wait_seconds):
        super().__init__(msg)
        self.wait_seconds = wait_seconds


def _state_dir():
    d = os.environ.get("AGENT_RATE_STATE_DIR") or os.path.expanduser("~/.claude")
    os.makedirs(d, exist_ok=True)
    return d


def _identity():
    """Best-effort caller identity for the ledger (never fails)."""
    return {
        "session": os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("AGENT_SESSION_ID") or "",
        "project": os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        "pid": os.getpid(),
    }


def refill(tokens, last_refill, now, *, burst=BURST, refill_seconds=REFILL_SECONDS):
    """Pure token-bucket refill — the testable core.

    A clock that moved backwards (sleep/wake, NTP) must never mint tokens, so
    elapsed is floored at 0.
    """
    elapsed = max(0.0, now - last_refill)
    return min(burst, tokens + elapsed / refill_seconds)


class RateBudget:
    def __init__(self, name="liftwing", *, burst=BURST, refill_seconds=REFILL_SECONDS,
                 hour_cap=HOUR_CAP):
        self.name = name
        self.burst = burst
        self.refill_seconds = refill_seconds
        self.hour_cap = hour_cap
        d = _state_dir()
        self.bucket_path = os.path.join(d, f"{name}-bucket.json")
        self.ledger_path = os.path.join(d, f"{name}-usage.jsonl")

    # -- ledger ---------------------------------------------------------
    def _append(self, event, model=None, **extra):
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event,
               "model": model, **_identity(), **extra}
        with open(self.ledger_path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def entries(self, since_seconds=HOUR):
        """Ledger records newer than `since_seconds` (bad lines skipped)."""
        cutoff = time.time() - since_seconds
        out = []
        try:
            with open(self.ledger_path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if datetime.fromisoformat(rec["ts"]).timestamp() >= cutoff:
                            out.append(rec)
                    except (ValueError, KeyError, TypeError):
                        continue          # a truncated tail line is not fatal
        except FileNotFoundError:
            pass
        return out

    def calls_last_hour(self):
        return sum(1 for r in self.entries(HOUR) if r.get("event") == "call")

    # -- enforcement ----------------------------------------------------
    def _try_take(self, model):
        """Atomically take one token. -> (True, 0.0) | (False, wait_seconds).

        The whole read-modify-write sits inside one flock so two concurrent
        sessions cannot both see the same last token.
        """
        with open(self.bucket_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read().strip()
                now = time.time()
                try:
                    st = json.loads(raw) if raw else {}
                    tokens = float(st.get("tokens", self.burst))
                    last = float(st.get("last_refill", now))
                except (ValueError, TypeError):
                    tokens, last = self.burst, now      # corrupt state: reset, don't crash
                tokens = refill(tokens, last, now, burst=self.burst,
                                refill_seconds=self.refill_seconds)

                used = self.calls_last_hour()
                if used >= self.hour_cap:
                    oldest = min((datetime.fromisoformat(r["ts"]).timestamp()
                                  for r in self.entries(HOUR) if r.get("event") == "call"),
                                 default=now)
                    return False, max(1.0, oldest + HOUR - now)

                if tokens < 1.0:
                    return False, (1.0 - tokens) * self.refill_seconds

                tokens -= 1.0
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps({"tokens": tokens, "last_refill": now}))
                fh.flush()
                self._append("call", model=model)
                return True, 0.0
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def acquire(self, *, model=None, wait=False, max_wait=900.0):
        """Consume one token, or raise RateBudgetExceeded.

        wait=True paces instead of failing (for scripted/overnight callers);
        interactive callers should fail fast — a silently sleeping agent looks
        hung.
        """
        deadline = time.time() + max_wait
        while True:
            ok, delay = self._try_take(model)
            if ok:
                return True
            if not wait:
                raise RateBudgetExceeded(
                    f"{self.name}: rate budget exhausted; next token in ~{delay:.0f}s "
                    f"({self.calls_last_hour()} calls in the last hour, cap {self.hour_cap}). "
                    f"Use wait=True to pace, or run bulk work from Toolforge.", delay)
            if time.time() + delay > deadline:
                raise RateBudgetExceeded(
                    f"{self.name}: would wait {delay:.0f}s, past max_wait {max_wait:.0f}s.", delay)
            time.sleep(min(delay, 5.0))

    def record(self, event, model=None, **extra):
        """Log a non-call outcome (429/error) for the feedback trail."""
        self._append(event, model=model, **extra)

    # -- reporting ------------------------------------------------------
    def status(self):
        now = time.time()
        try:
            with open(self.bucket_path) as fh:
                st = json.loads(fh.read() or "{}")
            tokens = refill(float(st.get("tokens", self.burst)),
                            float(st.get("last_refill", now)), now,
                            burst=self.burst, refill_seconds=self.refill_seconds)
        except (FileNotFoundError, ValueError, TypeError):
            tokens = self.burst
        recs = self.entries(HOUR)
        by = {}
        for r in recs:
            if r.get("event") != "call":
                continue
            key = f"{os.path.basename(r.get('project') or '?')}" + \
                  (f" [{r['session'][:8]}]" if r.get("session") else f" (pid {r.get('pid')})")
            by[key] = by.get(key, 0) + 1
        return {
            "name": self.name,
            "tokens_available": round(tokens, 2),
            "burst": self.burst,
            "refill_seconds": self.refill_seconds,
            "calls_last_hour": sum(1 for r in recs if r.get("event") == "call"),
            "hour_cap": self.hour_cap,
            "rate_limited_last_hour": sum(1 for r in recs if r.get("event") == "429"),
            "errors_last_hour": sum(1 for r in recs if r.get("event") == "error"),
            "by_caller": dict(sorted(by.items(), key=lambda kv: -kv[1])),
            "ledger": self.ledger_path,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default="liftwing", help="budget name (default: liftwing)")
    ap.add_argument("--status", action="store_true", help="show headroom + who used it")
    ap.add_argument("--json", action="store_true", help="machine-readable --status")
    ap.add_argument("--reset", action="store_true", help="clear bucket and ledger")
    a = ap.parse_args()
    if not (a.status or a.reset):
        ap.print_usage()
        print("nothing to do: pass --status or --reset", file=sys.stderr)
        return 2

    b = RateBudget(a.name)
    if a.reset:
        resp = input(f"delete {b.bucket_path} and {b.ledger_path}? [y/N] ")
        if resp.strip().lower() != "y":
            print("aborted")
            return 1
        for p in (b.bucket_path, b.ledger_path):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
        print("reset")
        return 0

    s = b.status()
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"{s['name']}: {s['tokens_available']}/{s['burst']} tokens available "
          f"(refill 1 per {s['refill_seconds']:.0f}s)")
    print(f"  calls last hour: {s['calls_last_hour']}/{s['hour_cap']}"
          f"   429s: {s['rate_limited_last_hour']}   errors: {s['errors_last_hour']}")
    if s["by_caller"]:
        print("  by caller:")
        for k, v in s["by_caller"].items():
            print(f"    {v:4d}  {k}")
    else:
        print("  by caller: (none in the last hour)")
    print(f"  ledger: {s['ledger']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
