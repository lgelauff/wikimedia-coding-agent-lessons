#!/usr/bin/env python3
"""Run the research vault's ingest.py, or add a pending.txt block, under one lock.

Why (Lodewijk, 2026-11-03): agent sessions may run ingest.py as long as runs do
not clash. Two things clash today:
  * two ingest.py runs at once (both rewrite index.json and pending.txt);
  * an append to inbox/pending.txt while a run is going: ingest.py reads the
    file at the start and rewrites it whole at the end, so the new block is lost.
Both go through this script. It takes an exclusive lock, says who holds it when
it is busy, and logs every run to RUNS.tsv (the "reservation" record).

usage:
  vault_ingest.py run --session "<name>" -- --collect --auto [--project P]
  vault_ingest.py run --session "<name>" -- --audit | --dry-run
  vault_ingest.py add-pending --session "<name>" --query "..." [--doi D] [--url U] [--project P]
  vault_ingest.py status
  options: --wait SECONDS (default 0 = fail fast when busy), --vault PATH

Exit: 0 ok, 1 busy (another holder, named), 2 refused (bad args), else ingest.py's code.
Hand edits of index.json and pdfs/ stay forbidden; this script never edits them itself.
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_VAULT = Path.home() / "Documents" / "GitHub" / "research-vault"
STATE_DIR = Path(os.environ.get("VAULT_INGEST_STATE", Path.home() / "agent" / "locks"))
LOCK = STATE_DIR / "research-vault.lock"
RUNS = STATE_DIR / "research-vault-RUNS.tsv"

# ingest.py flags an agent may pass. Anything else is refused: no --force, no --pdf
# from arbitrary paths without --auto, no interactive run (it would hang a session).
ALLOWED = {"--collect", "--audit", "--dry-run", "--auto", "--project"}
WRITING = {"--collect"}


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_ingest_args(args: list[str]) -> str | None:
    """Return a refusal reason, or None if the ingest.py arguments are allowed."""
    if not args:
        return "no ingest.py arguments; pass --collect --auto, --audit or --dry-run"
    i = 0
    while i < len(args):
        a = args[i]
        if a not in ALLOWED:
            return "flag %r not allowed for agents (allowed: %s)" % (a, ", ".join(sorted(ALLOWED)))
        if a == "--project":
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                return "--project needs a name"
            i += 1
        i += 1
    if set(args) & WRITING and "--auto" not in args:
        return "--collect needs --auto (an interactive prompt would hang the session)"
    return None


def acquire(wait: float, holder: str):
    """Take the lock. Returns the open fd, or (None, current holder text) when busy."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.lseek(fd, 0, 0)
                held = os.read(fd, 500).decode("utf-8", "replace").strip() or "unknown holder"
                os.close(fd)
                return None, held
            time.sleep(2)
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, 0)
    os.write(fd, holder.encode("utf-8"))
    os.fsync(fd)
    return fd, holder


def release(fd: int) -> None:
    os.ftruncate(fd, 0)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def log_run(fields: list[str]) -> None:
    new = not RUNS.exists()
    with open(RUNS, "a", encoding="utf-8") as f:
        if new:
            f.write("start\tend\tsession\taction\targs\texit\n")
        f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in fields) + "\n")


def pending_block(a) -> str:
    lines = ["query:     " + a.query.strip()]
    for k in ("url", "doi", "project"):
        v = getattr(a, k)
        if v:
            lines.append("%s:     %s" % (k, v.strip()))
    lines += ["status:     pending", "added:     " + datetime.date.today().isoformat(),
              "requested_by:     " + a.session.strip()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ingest_args: list[str] = []
    if "--" in argv:
        k = argv.index("--")
        argv, ingest_args = argv[:k], argv[k + 1:]
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["run", "add-pending", "status"])
    p.add_argument("--session", default="")
    p.add_argument("--wait", type=float, default=0.0)
    p.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    p.add_argument("--query"); p.add_argument("--doi"); p.add_argument("--url"); p.add_argument("--project")
    a = p.parse_args(argv)

    if a.action == "status":
        fd, held = acquire(0, "status probe %s" % now())
        if fd is None:
            print("BUSY: " + held); return 1
        release(fd); print("free"); return 0

    if not a.session.strip():
        print("REFUSED: --session is required (who holds the lock)", file=sys.stderr); return 2
    ingest = a.vault / "ingest.py"
    pending = a.vault / "inbox" / "pending.txt"

    if a.action == "run":
        why = check_ingest_args(ingest_args)
        if why:
            print("REFUSED: " + why, file=sys.stderr); return 2
        if not ingest.is_file():
            print("REFUSED: no ingest.py at %s" % ingest, file=sys.stderr); return 2
    else:
        if ingest_args:
            print("REFUSED: add-pending takes no ingest.py arguments", file=sys.stderr); return 2
        if not (a.query and (a.doi or a.url)):
            print("REFUSED: add-pending needs --query and --doi or --url", file=sys.stderr); return 2
        if not pending.is_file():
            print("REFUSED: no pending.txt at %s" % pending, file=sys.stderr); return 2

    start = now()
    holder = "%s | %s | %s %s | pid %d" % (start, a.session.strip(), a.action, " ".join(ingest_args), os.getpid())
    fd, held = acquire(a.wait, holder)
    if fd is None:
        print("BUSY: the vault is held by: %s. Try again later or pass --wait SECONDS." % held, file=sys.stderr)
        return 1
    rc = 0
    try:
        if a.action == "run":
            # tests set VAULT_INGEST_PYTHON to run a fake ingest.py without uv
            runner = os.environ.get("VAULT_INGEST_PYTHON")
            cmd = ([runner] if runner else ["uv", "run", "--project", str(a.vault)]) + [str(ingest)] + ingest_args
            rc = subprocess.run(cmd, cwd=str(a.vault), stdin=subprocess.DEVNULL).returncode
        else:
            block = pending_block(a)
            text = pending.read_text(encoding="utf-8")
            sep = "" if not text.strip() else ("---\n" if text.endswith("\n") else "\n---\n")
            with open(pending, "a", encoding="utf-8") as f:
                f.write(sep + block + "\n")
                f.flush(); os.fsync(f.fileno())
            print("appended:\n" + block)
    finally:
        log_run([start, now(), a.session.strip(), a.action, " ".join(ingest_args) or (a.query or ""), str(rc)])
        release(fd)
    return rc


if __name__ == "__main__":
    sys.exit(main())
