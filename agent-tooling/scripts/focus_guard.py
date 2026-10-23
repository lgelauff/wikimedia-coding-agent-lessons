#!/usr/bin/env python3
"""focus_guard.py — pause registered agent background jobs on the Mac while a macOS Focus is on.

Run by a macOS Shortcuts personal automation ("When any Focus turns on/off"), and by agents
(`register` / `unregister`). See agent-tooling/playbooks/focus-guard.md.

  focus_guard.py on                       # flag + SIGSTOP every registered, alive, matching job
  focus_guard.py off                      # remove flag + SIGCONT exactly the jobs `on` stopped
  focus_guard.py metered on|off           # same mechanism, for a metered connection (phone hotspot):
                                          # pauses only jobs registered with --kind big-transfer
  focus_guard.py status                   # focus and metered on/off, registered jobs, which are stopped
  focus_guard.py register <name> <pid> [--owner <session>] [--kind big-transfer]
  focus_guard.py unregister <name>
      [--state-dir DIR] [--log FILE]      # default: state/ and logs/focus-guard.log in the agent hub

Layout under the state dir: `focus-on` (flag, ISO timestamp), `pausable/<name>.json` (pid, command,
started, owner, kind), `focus-stopped.json` (the jobs this tool stopped: the only ones `off` resumes).
`metered on` writes `metered-on` and `metered-stopped.json` the same way. A job held by both a Focus and
a metered pause is resumed only when the last of the two ends. Who runs `metered on|off`: an agent or
Lodewijk, after `machine_check.py` reports the connection as metered; nothing detects it automatically.

Safety
  * Only registered jobs are signalled; nothing else, ever. Only SIGSTOP and SIGCONT; nothing that ends a process.
  * A job is signalled only if its pid is alive AND `ps` still shows the command recorded at
    register time (pid reuse guard). A dead or reused pid is a stale entry and is pruned on every call.
  * Anything with "claude" in its command (the Claude app, Claude Code) is refused at register and
    skipped at `on`, even if a registration file was written by hand.
  * Idempotent: `on` twice and `off` twice are safe.

Exit 0 = ok, 1 = error (bad input, cannot register).
"""
import argparse
import datetime as _dt
import json
import os
import pathlib
import signal
import subprocess
import sys

DEFAULT_STATE = pathlib.Path.home() / "agent" / "state"
DEFAULT_LOG = pathlib.Path.home() / "agent" / "logs" / "focus-guard.log"
PS_TIMEOUT = 10.0
FORBIDDEN = "claude"  # case-insensitive substring of the command
METERED_KIND = "big-transfer"


def now():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Guard:
    def __init__(self, state_dir, log, reason="focus"):
        self.state_dir, self.log_arg = state_dir, log
        self.reason = reason
        self.state = pathlib.Path(state_dir)
        self.log_path = pathlib.Path(log)
        self.flag = self.state / f"{reason}-on"
        self.pausable = self.state / "pausable"
        self.stopped_file = self.state / f"{reason}-stopped.json"

    def sibling(self):
        return Guard(self.state_dir, self.log_arg, "metered" if self.reason == "focus" else "focus")

    def selects(self, job):
        """Focus pauses every registered job; a metered connection only the big transfers."""
        return self.reason == "focus" or job.get("kind") == METERED_KIND

    def held_by_sibling(self, name, rec):
        """True if the other reason is still on and stopped this same process."""
        sib = self.sibling()
        held = sib.load_stopped().get(name)
        return sib.flag.exists() and bool(held) and held.get("pid") == rec["pid"]

    # -- helpers -------------------------------------------------------------------------
    def log(self, msg):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(f"{now()} {msg}\n")

    @staticmethod
    def command_of(pid):
        """The command line of a live pid, or None. Zombies count as gone."""
        try:
            out = subprocess.run(["ps", "-o", "stat=,command=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=PS_TIMEOUT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        if not out:
            return None
        stat, _, command = out.partition(" ")
        if stat.startswith("Z"):
            return None
        return command.strip()

    @staticmethod
    def state_of(pid):
        try:
            out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=PS_TIMEOUT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
        return out

    def load_jobs(self):
        jobs = {}
        if self.pausable.is_dir():
            for p in sorted(self.pausable.glob("*.json")):
                try:
                    d = json.loads(p.read_text())
                    d["pid"] = int(d["pid"])
                    d["command"] = str(d["command"])
                    jobs[p.stem] = d
                except (OSError, ValueError, KeyError, TypeError):
                    self.log(f"prune {p.stem}: unreadable registration")
                    p.unlink(missing_ok=True)
        return jobs

    def matches(self, job):
        """True if the pid is alive and still runs the recorded command."""
        return self.command_of(job["pid"]) == job["command"]

    def load_stopped(self):
        try:
            return json.loads(self.stopped_file.read_text())
        except (OSError, ValueError):
            return {}

    def save_stopped(self, stopped):
        if stopped:
            self.state.mkdir(parents=True, exist_ok=True)
            self.stopped_file.write_text(json.dumps(stopped, indent=2) + "\n")
        else:
            self.stopped_file.unlink(missing_ok=True)

    def prune(self):
        """Drop registrations whose pid is dead or now runs something else. Returns live jobs."""
        live = {}
        stopped = self.load_stopped()
        for name, job in self.load_jobs().items():
            if self.matches(job):
                live[name] = job
                continue
            alive = self.command_of(job["pid"]) is not None
            self.log(f"prune {name} pid {job['pid']}: " + ("pid reused by another command" if alive
                                                           else "process gone"))
            (self.pausable / f"{name}.json").unlink(missing_ok=True)
            stopped.pop(name, None)
        self.save_stopped(stopped)
        return live

    # -- commands ------------------------------------------------------------------------
    def register(self, name, pid, owner, kind=""):
        if not name or "/" in name or name.startswith("."):
            return self.fail(f"bad job name {name!r}")
        command = self.command_of(pid)
        if command is None:
            return self.fail(f"pid {pid} is not running")
        if FORBIDDEN in command.lower():
            self.log(f"refuse register {name} pid {pid}: command contains {FORBIDDEN!r}")
            return self.fail(f"refusing to register pid {pid}: its command contains {FORBIDDEN!r}")
        self.pausable.mkdir(parents=True, exist_ok=True)
        rec = {"pid": pid, "command": command, "started": now(), "owner": owner, "kind": kind}
        (self.pausable / f"{name}.json").write_text(json.dumps(rec, indent=2) + "\n")
        self.log(f"register {name} pid {pid}")
        self.prune()
        print(f"registered {name} (pid {pid})")
        return 0

    def unregister(self, name):
        p = self.pausable / f"{name}.json"
        existed = p.exists()
        p.unlink(missing_ok=True)
        for g in (self, self.sibling()):
            stopped = g.load_stopped()
            if name in stopped:
                # Do not orphan a job we stopped: resume it, then forget it.
                g.resume(name, stopped.pop(name), force=True)
                g.save_stopped(stopped)
        self.log(f"unregister {name}" + ("" if existed else " (was not registered)"))
        self.prune()
        print(f"unregistered {name}" if existed else f"{name} was not registered")
        return 0

    def on(self):
        self.state.mkdir(parents=True, exist_ok=True)
        if not self.flag.exists():
            self.flag.write_text(now() + "\n")
            self.log(f"{self.reason} on: flag created")
        else:
            self.log(f"{self.reason} on: flag already present")
        stopped = self.load_stopped()
        for name, job in self.prune().items():
            if FORBIDDEN in job["command"].lower():
                self.log(f"skip {name} pid {job['pid']}: command contains {FORBIDDEN!r}")
                continue
            if not self.selects(job):
                continue
            if name in stopped:
                continue  # already stopped by us
            try:
                os.kill(job["pid"], signal.SIGSTOP)
            except OSError as e:
                self.log(f"stop {name} pid {job['pid']} failed: {e}")
                continue
            stopped[name] = {"pid": job["pid"], "command": job["command"], "stopped": now()}
            self.log(f"SIGSTOP {name} pid {job['pid']}")
            self.save_stopped(stopped)
        self.save_stopped(stopped)
        print(f"{self.reason} on: {len(stopped)} job(s) stopped")
        return 0

    def resume(self, name, rec, force=False):
        if not force and self.held_by_sibling(name, rec):
            self.log(f"keep {name} pid {rec['pid']} stopped: {self.sibling().reason} is still on")
            return False
        if self.command_of(rec["pid"]) != rec["command"]:
            self.log(f"skip resume {name} pid {rec['pid']}: gone or pid reused")
            return False
        try:
            os.kill(rec["pid"], signal.SIGCONT)
        except OSError as e:
            self.log(f"resume {name} pid {rec['pid']} failed: {e}")
            return False
        self.log(f"SIGCONT {name} pid {rec['pid']}")
        return True

    def off(self):
        if self.flag.exists():
            self.flag.unlink()
            self.log(f"{self.reason} off: flag removed")
        else:
            self.log(f"{self.reason} off: flag already absent")
        stopped = self.load_stopped()
        resumed = sum(1 for name, rec in stopped.items() if self.resume(name, rec))
        self.save_stopped({})
        self.prune()
        print(f"{self.reason} off: {resumed} job(s) resumed")
        return 0

    def status(self):
        jobs = self.prune()
        sib = self.sibling()
        stopped = {**sib.load_stopped(), **self.load_stopped()}
        for g in (self, sib):
            print(f"{g.reason}: " + ("ON since " + g.flag.read_text().strip() if g.flag.exists() else "off"))
        if not jobs:
            print("no registered jobs")
        for name, job in jobs.items():
            st = "STOPPED" if name in stopped else "running"
            kind = job.get("kind") or "-"
            print(f"  {name}\tpid {job['pid']}\t{st}\towner={job.get('owner') or '-'}\tkind={kind}\t{job['command'][:60]}")
        return 0

    @staticmethod
    def fail(msg):
        print(f"focus_guard: {msg}", file=sys.stderr)
        return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE))
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("on")
    sub.add_parser("off")
    sub.add_parser("status")
    m = sub.add_parser("metered")
    m.add_argument("state", choices=["on", "off"])
    r = sub.add_parser("register")
    r.add_argument("name")
    r.add_argument("pid", type=int)
    r.add_argument("--owner", default="")
    r.add_argument("--kind", default="", choices=["", METERED_KIND])
    u = sub.add_parser("unregister")
    u.add_argument("name")
    a = ap.parse_args(argv)
    g = Guard(a.state_dir, a.log, "metered" if a.cmd == "metered" else "focus")
    if a.cmd == "metered":
        return getattr(g, a.state)()
    if a.cmd == "register":
        return g.register(a.name, a.pid, a.owner, a.kind)
    if a.cmd == "unregister":
        return g.unregister(a.name)
    return getattr(g, a.cmd)()


if __name__ == "__main__":
    sys.exit(main())
