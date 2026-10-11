#!/usr/bin/env python3
"""mac_watchdog.py — one check of the Mac's memory and disk, run every 30 s by launchd.

Why it exists: on 2026-10-10 08:29 the Mac (8 GB RAM) panicked with a watchdog timeout. A single `git` process started by
a Claude Code session (an agent Bash pipeline `git … | cut | head`) had grown to a 19.3 GB footprint; free memory was
~14 MB, swap was nearly full and the disk 98% full (AGENT-LOG E263). Nothing warned beforehand.

What it does, and nothing more:
  1. NOTIFY (macOS notification + log line, at most once per 15 min per kind) when swap use is above SWAP_WARN or free
     disk is below DISK_WARN_GB.
  2. KILL exactly one class of process: a `git` whose physical footprint exceeds GIT_KILL_GB AND whose ancestor chain
     contains a Claude Code / Claude desktop process. git never legitimately needs that much here; everything else —
     Claude sessions, browsers, python jobs — is only ever reported, never touched. SIGTERM, then SIGKILL after 5 s.

  mac_watchdog.py              one check (what launchd runs)
  mac_watchdog.py --dry-run    report what it would do, change nothing
  MAC_WATCHDOG_GIT_KILL_GB=0 mac_watchdog.py --only-pid N   live test of the kill path on one chosen pid
State and log: ~/agent/logs/mac-watchdog.log, ~/agent/state/mac-watchdog.json (notification rate limit).
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

SWAP_WARN = 0.80
DISK_WARN_GB = 15
GIT_KILL_GB = float(os.environ.get("MAC_WATCHDOG_GIT_KILL_GB", "3"))  # env override for tests only
NOTIFY_EVERY_S = 15 * 60
HOME = Path.home()
LOG = HOME / "agent/logs/mac-watchdog.log"
STATE = HOME / "agent/state/mac-watchdog.json"
CLAUDE_MARKERS = ("/Claude/claude-code/", "Claude.app/", "/claude-code/")


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(time.strftime("%Y-%m-%dT%H:%M:%S%z ") + msg + "\n")


def swap_fraction() -> float | None:
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", out)
    if not m or float(m.group(1)) == 0:
        return None
    return float(m.group(2)) / float(m.group(1))


def free_disk_gb(path=HOME) -> float:
    return shutil.disk_usage(str(path)).free / 1024**3


class _RusageV2(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins", "wired_size", "resident_size",
        "phys_footprint", "proc_start_abstime", "proc_exit_abstime", "child_user_time", "child_system_time",
        "child_pkg_idle_wkups", "child_interrupt_wkups", "child_pageins", "child_elapsed_abstime",
        "diskio_bytesread", "diskio_byteswritten")]


_libproc = None


def footprint_bytes(pid: int, rss_kb: int) -> int:
    """Physical footprint (includes compressed/swapped pages) via proc_pid_rusage; falls back to RSS."""
    global _libproc
    try:
        if _libproc is None:
            _libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        buf = _RusageV2()
        if _libproc.proc_pid_rusage(pid, 2, ctypes.byref(buf)) == 0:
            return max(int(buf.phys_footprint), rss_kb * 1024)
    except OSError:
        pass
    return rss_kb * 1024


def process_table():
    """{pid: (ppid, rss_kb, command)} for every process."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,command="], capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit():
            table[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    return table


def under_claude(pid: int, table) -> bool:
    seen = set()
    while pid in table and pid not in seen and pid > 1:
        seen.add(pid)
        ppid, _, cmd = table[pid]
        if any(m in cmd for m in CLAUDE_MARKERS):
            return True
        pid = ppid
    return False


def is_git(cmd: str) -> bool:
    exe = cmd.split(None, 1)[0] if cmd else ""
    return os.path.basename(exe) == "git"


def decide(table, swap, disk_gb, footprint=footprint_bytes):
    """Pure decision: returns (notifications, kills). kills = [(pid, footprint_bytes, command)]."""
    notes, kills = [], []
    if swap is not None and swap > SWAP_WARN:
        notes.append(("swap", f"swap {swap:.0%} used (warn above {SWAP_WARN:.0%})"))
    if disk_gb < DISK_WARN_GB:
        notes.append(("disk", f"only {disk_gb:.1f} GB free on the Mac disk (warn below {DISK_WARN_GB} GB)"))
    for pid, (_, rss_kb, cmd) in table.items():
        if not is_git(cmd):
            continue
        fp = footprint(pid, rss_kb)
        if fp > GIT_KILL_GB * 1024**3 and under_claude(pid, table):
            kills.append((pid, fp, cmd))
    return notes, kills


def notify(title: str, msg: str) -> None:
    subprocess.run(["osascript", "-e", f'display notification {json.dumps(msg)} with title {json.dumps(title)}'],
                   capture_output=True)


def main(argv):
    dry = "--dry-run" in argv
    only = int(argv[argv.index("--only-pid") + 1]) if "--only-pid" in argv else None  # live test: act on one pid only
    table = process_table()
    swap, disk = swap_fraction(), free_disk_gb()
    notes, kills = decide(table, swap, disk)
    if only is not None:
        kills, notes = [k for k in kills if k[0] == only], []
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    now = time.time()
    for pid, fp, cmd in kills:
        msg = f"KILL runaway git pid {pid} footprint {fp / 1024**3:.1f} GB (> {GIT_KILL_GB} GB, under Claude): {cmd[:200]}"
        if dry:
            print("would " + msg); continue
        log(msg)
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                time.sleep(0.5)
                os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
            log(f"pid {pid} needed SIGKILL")
        except ProcessLookupError:
            pass
        notify("Mac watchdog: killed a runaway git", f"pid {pid}, {fp / 1024**3:.1f} GB. See ~/agent/logs/mac-watchdog.log")
    for kind, msg in notes:
        if dry:
            print("would notify: " + msg); continue
        if now - state.get(kind, 0) >= NOTIFY_EVERY_S:
            log("WARN " + msg)
            notify("Mac watchdog", msg)
            state[kind] = now
    if not dry:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
    else:
        print(f"swap {swap if swap is None else f'{swap:.0%}'}, disk free {disk:.1f} GB, {len(table)} processes; "
              f"{len(kills)} kill(s), {len(notes)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
