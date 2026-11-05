#!/usr/bin/env python3
"""Start a long job fully detached from the agent session, and record its real exit code.

Usage: detach_run.py --run-dir DIR [--no-caffeinate] -- COMMAND [ARGS...]

Why: `caffeinate -i nohup CMD &` launched through an agent's background-task tool stays in
the tool's process group. When the tool or session ends, the group gets SIGTERM, and nohup
only ignores SIGHUP, so the job dies (seen 2026-10-27: exit 143 after ~1h45). A trailing
`echo exit $?` then reported exit 0. This launcher puts the job in its own session (setsid),
so signals to the agent's process group never reach it, and writes the job's own exit code.

Files in DIR:
  run.log     job stdout+stderr (appended), plus 'detach_run: started/ended' lines
  pgid        process-group id of the job; stop it with `kill -TERM -<pgid>`
  exit_code   written only when the job ends: a number, or 128+N when killed by signal N.
              Missing while running. Missing with no live process = the job and this
              launcher were both killed hard (e.g. SIGKILL, reboot): treat as failed.

Exit: 0 = job started (printed pgid and paths), 2 = usage error or a live job already uses DIR.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime


def stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def supervise(run_dir, cmd):
    """Runs in the detached child: start the job, wait, record its exit code."""
    # The supervisor shares the job's process group, so `kill -TERM -<pgid>` reaches it too.
    # A no-op handler (not SIG_IGN, which the job would inherit) keeps it alive to record the code.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda *_: None)
    log_path = os.path.join(run_dir, "run.log")
    with open(log_path, "a", buffering=1) as log:
        log.write("detach_run: started %s pgid=%d cmd=%r\n" % (stamp(), os.getpgrp(), cmd))
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            rc = proc.wait()
        except OSError as exc:
            log.write("detach_run: could not start: %s\n" % exc)
            rc = 127
        code = 128 - rc if rc < 0 else rc
        write_atomic(os.path.join(run_dir, "exit_code"), "%d\n" % code)
        log.write("detach_run: ended %s exit_code=%d\n" % (stamp(), code))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv:
        print("usage: detach_run.py --run-dir DIR [--no-caffeinate] -- COMMAND [ARGS...]")
        return 2
    split = argv.index("--")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--no-caffeinate", action="store_true", help="do not wrap in caffeinate -i")
    args = ap.parse_args(argv[:split])
    cmd = argv[split + 1:]
    if not cmd:
        print("ERROR: no command after --")
        return 2
    run_dir = os.path.abspath(args.run_dir)
    os.makedirs(run_dir, exist_ok=True)
    pgid_path = os.path.join(run_dir, "pgid")
    if os.path.exists(pgid_path) and not os.path.exists(os.path.join(run_dir, "exit_code")):
        try:
            old = int(open(pgid_path).read().strip())
        except ValueError:
            old = 0
        if old and alive(old):
            print("ERROR: a job is still running from %s (pgid %d)" % (run_dir, old))
            return 2
    for name in ("exit_code", "pgid"):
        if os.path.exists(os.path.join(run_dir, name)):
            os.remove(os.path.join(run_dir, name))
    if not args.no_caffeinate and shutil.which("caffeinate"):
        cmd = ["caffeinate", "-i"] + cmd

    pid = os.fork()
    if pid == 0:  # child: new session, then supervise; never return into the caller's code
        try:
            os.setsid()
            devnull = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(devnull, fd)
            write_atomic(pgid_path, "%d\n" % os.getpgrp())
            supervise(run_dir, cmd)
        finally:
            os._exit(0)
    for _ in range(50):  # parent: wait for the child to record its pgid
        if os.path.exists(pgid_path):
            break
        time.sleep(0.1)
    pgid = open(pgid_path).read().strip() if os.path.exists(pgid_path) else "?"
    print("started: pgid %s (own session)\n  log: %s\n  exit code will be written to: %s\n  stop: kill -TERM -%s"
          % (pgid, os.path.join(run_dir, "run.log"), os.path.join(run_dir, "exit_code"), pgid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
