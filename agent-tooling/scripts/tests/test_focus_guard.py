#!/usr/bin/env python3
"""Tests for scripts/focus_guard.py — pause registered Mac background jobs while a Focus is on.

Real `sleep` children, a temp state dir. Each safety property has its own test, and the dangerous
direction (touching something that is not ours) is pinned as hard as the happy path.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "focus_guard.py"
spec = importlib.util.spec_from_file_location("focus_guard", SCRIPT)
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state"
        self.log = self.tmp / "logs" / "focus-guard.log"
        self.procs = []
        self.groups = set()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in self.procs:  # our own test children only
            if p.poll() is None:
                try:
                    if p.pid in self.groups:
                        os.killpg(p.pid, signal.SIGCONT)
                        os.killpg(p.pid, signal.SIGKILL)
                    else:
                        p.send_signal(signal.SIGCONT)
                        p.kill()
                except OSError:
                    pass
            p.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sleeper(self, secs="300"):
        p = subprocess.Popen(["sleep", secs])
        self.procs.append(p)
        return p

    def shell_job(self, argv0):
        """A job whose command line names `argv0`; own session so cleanup can end its sleep child too."""
        p = subprocess.Popen(["sh", "-c", "sleep 300; :", argv0], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        self.groups.add(p.pid)
        return p

    def run_cmd(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = F.main(["--state-dir", str(self.state), "--log", str(self.log), *args])
        return rc, out.getvalue(), err.getvalue()

    def wait_state(self, pid, letter, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end:
            if F.Guard.state_of(pid).startswith(letter):
                return True
            time.sleep(0.05)
        return False

    def is_stopped(self, pid):
        return self.wait_state(pid, "T")

    def is_running(self, pid):
        return not F.Guard.state_of(pid).startswith("T") and F.Guard.state_of(pid) != ""

    def reg(self, name, proc, *extra):
        rc, _, err = self.run_cmd("register", name, str(proc.pid), *extra)
        self.assertEqual(rc, 0, err)

    def jobfile(self, name):
        return self.state / "pausable" / f"{name}.json"


class TestPauseResume(Base):
    def test_on_stops_and_off_resumes(self):
        p = self.sleeper()
        self.reg("job", p, "--owner", "sess-1")
        rec = json.loads(self.jobfile("job").read_text())
        self.assertEqual((rec["pid"], rec["owner"]), (p.pid, "sess-1"))
        self.assertIn("sleep", rec["command"])
        self.assertTrue(rec["started"])
        self.assertTrue(self.is_running(p.pid))

        self.assertEqual(self.run_cmd("on")[0], 0)
        self.assertTrue((self.state / "focus-on").read_text().strip())  # ISO timestamp
        self.assertTrue(self.is_stopped(p.pid))
        self.assertIn("STOPPED", self.run_cmd("status")[1])
        self.assertIn("ON since", self.run_cmd("status")[1])

        self.assertEqual(self.run_cmd("off")[0], 0)
        self.assertFalse((self.state / "focus-on").exists())
        self.assertTrue(self.wait_state(p.pid, "S"))
        self.assertTrue(self.is_running(p.pid))
        self.assertNotIn("STOPPED", self.run_cmd("status")[1])
        self.assertFalse((self.state / "focus-stopped.json").exists())

    def test_log_records_each_action_with_timestamp(self):
        p = self.sleeper()
        self.reg("job", p)
        self.run_cmd("on")
        self.run_cmd("off")
        lines = self.log.read_text().splitlines()
        text = "\n".join(lines)
        for needle in ("register job", "SIGSTOP job", "SIGCONT job", "flag created", "flag removed"):
            self.assertIn(needle, text)
        self.assertTrue(all(l[:4].isdigit() and "T" in l.split()[0] for l in lines), lines)

    def test_on_twice_and_off_twice_are_safe(self):
        p = self.sleeper()
        self.reg("job", p)
        self.assertEqual(self.run_cmd("on")[0], 0)
        self.assertEqual(self.run_cmd("on")[0], 0)
        self.assertTrue(self.is_stopped(p.pid))
        self.assertEqual(self.run_cmd("off")[0], 0)  # one SIGCONT is enough after two stops
        self.assertTrue(self.wait_state(p.pid, "S"))
        self.assertEqual(self.run_cmd("off")[0], 0)
        self.assertTrue(self.is_running(p.pid))

    def test_off_only_resumes_what_on_stopped(self):
        """A job the user stopped by hand (not registered when `on` ran) stays stopped."""
        ours, theirs = self.sleeper(), self.sleeper()
        self.reg("ours", ours)
        self.run_cmd("on")
        self.reg("theirs", theirs)  # registered after `on`: never stopped by us
        os.kill(theirs.pid, signal.SIGSTOP)  # stopped by someone else
        self.assertTrue(self.is_stopped(theirs.pid))
        self.run_cmd("off")
        self.assertTrue(self.wait_state(ours.pid, "S"))
        self.assertTrue(self.is_stopped(theirs.pid))  # still stopped: not in our stopped-list

    def test_job_registered_while_focus_is_on_is_paused_by_next_on(self):
        p = self.sleeper()
        self.run_cmd("on")
        self.reg("late", p)
        self.assertTrue(self.is_running(p.pid))
        self.run_cmd("on")
        self.assertTrue(self.is_stopped(p.pid))


class TestSafety(Base):
    def test_unregistered_process_never_touched(self):
        reg, bystander = self.sleeper(), self.sleeper()
        self.reg("job", reg)
        self.run_cmd("on")
        self.assertTrue(self.is_stopped(reg.pid))
        self.assertTrue(self.is_running(bystander.pid))
        self.run_cmd("off")
        self.assertTrue(self.is_running(bystander.pid))

    def test_pid_reuse_mismatched_command_not_touched(self):
        p = self.sleeper()
        self.reg("job", p)
        rec = json.loads(self.jobfile("job").read_text())
        rec["command"] = "/usr/bin/python3 some_other_job.py"  # what the pid used to be
        self.jobfile("job").write_text(json.dumps(rec))
        self.run_cmd("on")
        self.assertTrue(self.is_running(p.pid))
        self.assertFalse(self.jobfile("job").exists())  # stale entry pruned
        self.assertIn("pid reused", self.log.read_text())

    def test_stale_stopped_entry_with_reused_pid_not_resumed(self):
        p = self.sleeper()
        self.reg("job", p)
        self.run_cmd("on")
        self.assertTrue(self.is_stopped(p.pid))
        stopped = json.loads((self.state / "focus-stopped.json").read_text())
        stopped["job"]["command"] = "something else"
        (self.state / "focus-stopped.json").write_text(json.dumps(stopped))
        os.kill(p.pid, signal.SIGCONT)  # undo our stop so we can tell whether `off` signals it
        self.assertTrue(self.wait_state(p.pid, "S"))
        os.kill(p.pid, signal.SIGSTOP)  # a stop that is not ours
        self.assertTrue(self.is_stopped(p.pid))
        self.run_cmd("off")
        time.sleep(0.3)
        self.assertTrue(self.is_stopped(p.pid))
        self.assertIn("pid reused", self.log.read_text())

    def test_dead_pid_pruned_on_every_call(self):
        p = self.sleeper("0.1")
        self.reg("short", p)
        keep = self.sleeper()
        self.reg("keep", keep)
        p.wait()
        rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertNotIn("short", out)
        self.assertIn("keep", out)
        self.assertFalse(self.jobfile("short").exists())
        self.assertIn("prune short", self.log.read_text())

    def test_dead_pid_pruned_by_on(self):
        p = self.sleeper("0.1")
        self.reg("short", p)
        p.wait()
        self.assertEqual(self.run_cmd("on")[0], 0)
        self.assertFalse(self.jobfile("short").exists())
        self.assertFalse((self.state / "focus-stopped.json").exists())

    def test_claude_process_refused_at_register(self):
        p = self.shell_job("Claude-app")  # argv[0] of the job names it
        self.procs.append(p)
        time.sleep(0.2)
        rc, _, err = self.run_cmd("register", "app", str(p.pid))
        self.assertEqual(rc, 1)
        self.assertIn("claude", err)
        self.assertFalse(self.jobfile("app").exists())

    def test_claude_process_skipped_by_on_even_if_hand_registered(self):
        p = self.shell_job("claude-app")  # argv[0] of the job names it
        self.procs.append(p)
        time.sleep(0.2)
        cmd = F.Guard.command_of(p.pid)
        self.jobfile("app").parent.mkdir(parents=True)
        self.jobfile("app").write_text(json.dumps({"pid": p.pid, "command": cmd, "started": "x", "owner": ""}))
        self.run_cmd("on")
        time.sleep(0.3)
        self.assertTrue(self.is_running(p.pid))
        self.assertIn("skip app", self.log.read_text())

    def test_never_sigkill(self):
        src = SCRIPT.read_text()
        self.assertNotIn("SIGKILL", src)
        self.assertNotIn("kill -9", src)
        self.assertNotIn("SIGTERM", src)

    def test_register_dead_pid_and_bad_name_rejected(self):
        p = self.sleeper("0.1")
        p.wait()
        self.assertEqual(self.run_cmd("register", "x", str(p.pid))[0], 1)
        q = self.sleeper()
        self.assertEqual(self.run_cmd("register", "../evil", str(q.pid))[0], 1)
        self.assertFalse((self.state / "evil.json").exists())


class TestRegistry(Base):
    def test_unregister_removes_and_is_idempotent(self):
        p = self.sleeper()
        self.reg("job", p)
        self.assertEqual(self.run_cmd("unregister", "job")[0], 0)
        self.assertFalse(self.jobfile("job").exists())
        self.assertEqual(self.run_cmd("unregister", "job")[0], 0)
        self.run_cmd("on")
        self.assertTrue(self.is_running(p.pid))  # no longer registered: untouched

    def test_unregister_resumes_a_job_we_stopped(self):
        p = self.sleeper()
        self.reg("job", p)
        self.run_cmd("on")
        self.assertTrue(self.is_stopped(p.pid))
        self.run_cmd("unregister", "job")
        self.assertTrue(self.wait_state(p.pid, "S"))

    def test_status_when_nothing_registered(self):
        rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertIn("focus: off", out)
        self.assertIn("no registered jobs", out)

    def test_status_cli_runs_as_script(self):
        r = subprocess.run(["python3", str(SCRIPT), "--state-dir", str(self.state), "--log", str(self.log), "status"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("focus: off", r.stdout)


class TestMetered(Base):
    def test_metered_pauses_only_big_transfer_jobs(self):
        big, other, plain = self.sleeper(), self.sleeper(), self.sleeper()
        self.reg("big", big, "--kind", "big-transfer")
        self.reg("other", other)
        self.reg("plain", plain, "--kind", "")
        self.assertEqual(json.loads(self.jobfile("big").read_text())["kind"], "big-transfer")
        self.assertEqual(self.run_cmd("metered", "on")[0], 0)
        self.assertTrue((self.state / "metered-on").read_text().strip())
        self.assertTrue(self.is_stopped(big.pid))
        self.assertTrue(self.is_running(other.pid))
        self.assertTrue(self.is_running(plain.pid))
        self.assertFalse((self.state / "focus-on").exists())
        out = self.run_cmd("status")[1]
        self.assertIn("metered: ON since", out)
        self.assertIn("focus: off", out)
        self.assertEqual(self.run_cmd("metered", "off")[0], 0)
        self.assertTrue(self.wait_state(big.pid, "S"))
        self.assertFalse((self.state / "metered-on").exists())
        self.assertFalse((self.state / "metered-stopped.json").exists())

    def test_focus_still_pauses_every_job_not_just_big_transfers(self):
        other = self.sleeper()
        self.reg("other", other)
        self.run_cmd("on")
        self.assertTrue(self.is_stopped(other.pid))

    def test_metered_on_twice_and_off_twice_are_safe(self):
        p = self.sleeper()
        self.reg("big", p, "--kind", "big-transfer")
        self.assertEqual(self.run_cmd("metered", "on")[0], 0)
        self.assertEqual(self.run_cmd("metered", "on")[0], 0)
        self.assertTrue(self.is_stopped(p.pid))
        self.assertEqual(self.run_cmd("metered", "off")[0], 0)
        self.assertEqual(self.run_cmd("metered", "off")[0], 0)
        self.assertTrue(self.wait_state(p.pid, "S"))

    def test_job_held_by_focus_and_metered_resumes_only_when_both_end(self):
        p = self.sleeper()
        self.reg("big", p, "--kind", "big-transfer")
        self.run_cmd("on")
        self.run_cmd("metered", "on")
        self.run_cmd("metered", "off")
        self.assertTrue(self.is_stopped(p.pid))  # Focus still holds it
        self.run_cmd("off")
        self.assertTrue(self.wait_state(p.pid, "S"))

    def test_focus_off_leaves_metered_held_job_stopped(self):
        p = self.sleeper()
        self.reg("big", p, "--kind", "big-transfer")
        self.run_cmd("metered", "on")
        self.run_cmd("on")
        self.run_cmd("off")
        self.assertTrue(self.is_stopped(p.pid))
        self.run_cmd("metered", "off")
        self.assertTrue(self.wait_state(p.pid, "S"))

    def test_unregister_resumes_a_metered_stopped_job(self):
        p = self.sleeper()
        self.reg("big", p, "--kind", "big-transfer")
        self.run_cmd("metered", "on")
        self.run_cmd("unregister", "big")
        self.assertTrue(self.wait_state(p.pid, "S"))
        self.assertFalse((self.state / "metered-stopped.json").exists())

    def test_metered_never_signals_a_claude_process_or_unregistered_pid(self):
        c = self.shell_job("claude-code-run")
        (self.state / "pausable").mkdir(parents=True)
        cmd = F.Guard.command_of(c.pid)
        (self.state / "pausable" / "hand.json").write_text(
            json.dumps({"pid": c.pid, "command": cmd, "kind": "big-transfer"}))
        unreg = self.sleeper()
        self.run_cmd("metered", "on")
        self.assertTrue(self.is_running(c.pid))
        self.assertTrue(self.is_running(unreg.pid))

    def test_register_rejects_unknown_kind(self):
        p = self.sleeper()
        with self.assertRaises(SystemExit):
            self.run_cmd("register", "x", str(p.pid), "--kind", "bogus")


if __name__ == "__main__":
    unittest.main()
