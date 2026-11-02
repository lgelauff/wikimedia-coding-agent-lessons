"""Tests for detach_run.py: the job survives a SIGTERM to the launching process group, and
the recorded exit code is the job's own, not the launcher's.

Run: python3 -m unittest agent-tooling.scripts.tests.test_detach_run
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "detach_run.py"


def wait_for(path, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if path.exists():
            return path.read_text().strip()
        time.sleep(0.05)
    return None


def launch(run_dir, *cmd, group=False):
    """Start the launcher the way an agent's background tool would: in a process group we can signal."""
    return subprocess.Popen([sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--no-caffeinate", "--", *cmd],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=group)


class DetachRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "run"

    def tearDown(self):
        pgid = self.dir / "pgid"
        if pgid.exists() and not (self.dir / "exit_code").exists():
            try:
                os.killpg(int(pgid.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
        self.tmp.cleanup()

    def test_records_real_nonzero_exit_code(self):
        p = launch(self.dir, "sh", "-c", "echo hi; exit 3")
        self.assertEqual(p.wait(10), 0)
        self.assertEqual(wait_for(self.dir / "exit_code"), "3")
        log = (self.dir / "run.log").read_text()
        self.assertIn("hi", log)
        self.assertIn("exit_code=3", log)

    def test_job_survives_sigterm_to_launching_group(self):
        # The failure this exists for: the agent's tool SIGTERMs its process group.
        p = launch(self.dir, "sh", "-c", "sleep 1.5; echo survived", group=True)
        tool_group = os.getpgid(p.pid)
        job_pgid = int(wait_for(self.dir / "pgid"))
        self.assertNotEqual(job_pgid, tool_group)
        try:
            os.killpg(tool_group, signal.SIGTERM)
        except ProcessLookupError:
            pass  # launcher already returned; the group is gone, which is the point
        self.assertEqual(wait_for(self.dir / "exit_code", 10), "0")
        self.assertIn("survived", (self.dir / "run.log").read_text())

    def test_nohup_pattern_dies_control(self):
        # Control: shows the old pattern fails the same way, so the test above is meaningful.
        out = Path(self.tmp.name) / "nohup.log"
        p = subprocess.Popen(["sh", "-c", "nohup sh -c 'sleep 1.5; echo survived' > %s 2>&1; echo exit $?" % out],
                             start_new_session=True, stdout=subprocess.DEVNULL)
        time.sleep(0.3)
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        p.wait(5)
        time.sleep(1.8)
        self.assertNotIn("survived", out.read_text() if out.exists() else "")

    def test_signal_death_recorded_as_128_plus_n(self):
        launch(self.dir, "sh", "-c", "sleep 30").wait(10)
        job_pgid = int(wait_for(self.dir / "pgid"))
        time.sleep(0.2)
        os.killpg(job_pgid, signal.SIGTERM)
        # The supervisor shares the group but survives SIGTERM, so it records the job's death.
        self.assertEqual(wait_for(self.dir / "exit_code", 5), "143")

    def test_refuses_second_launch_into_live_run_dir(self):
        launch(self.dir, "sh", "-c", "sleep 30").wait(10)
        wait_for(self.dir / "pgid")
        p = launch(self.dir, "true")
        self.assertEqual(p.wait(10), 2)

    def test_usage_errors(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(self.dir)], capture_output=True)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
