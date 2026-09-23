#!/usr/bin/env python3
"""Tests for scripts/script_approval.py — content-bound script approval.

A guard that only ever says yes is worse than none, so these pin the refusals: an
unapproved script, a script edited after approval, a symlink swapped to point at other
code, and a script outside the project must all be refused; only the exact approved bytes
run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "script_approval.py"


class ScriptApprovalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        (self.root / ".git").mkdir(parents=True)
        self.s = self.root / "analysis" / "count.py"
        self.s.parent.mkdir()
        self.s.write_text("import sys\nprint('ran', *sys.argv[1:])\n")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root,
                              capture_output=True, text=True)

    def test_unapproved_is_refused(self):
        r = self.call("run", str(self.s))
        self.assertEqual(r.returncode, 2)
        self.assertIn("not approved", r.stderr)

    def test_approved_runs_with_args(self):
        self.assertEqual(self.call("approve", str(self.s)).returncode, 0)
        r = self.call("run", str(self.s), "--", "a", "b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "ran a b")

    def test_edit_after_approval_is_refused(self):
        self.call("approve", str(self.s))
        self.s.write_text("import os\nprint('something else')\n")
        r = self.call("run", str(self.s))
        self.assertEqual(r.returncode, 2)
        self.assertIn("changed since it was approved", r.stderr)

    def test_reapproval_after_edit_runs(self):
        self.call("approve", str(self.s))
        self.s.write_text("print('v2')\n")
        self.call("approve", str(self.s))
        self.assertEqual(self.call("run", str(self.s)).stdout.strip(), "v2")

    def test_symlink_swapped_to_other_code_is_refused(self):
        other = self.root / "analysis" / "other.py"
        other.write_text("print('not what was approved')\n")
        link = self.root / "analysis" / "entry.py"
        link.symlink_to(self.s)
        self.call("approve", str(link))            # approves the REAL file, count.py
        link.unlink(); link.symlink_to(other)       # swap the link to unapproved code
        r = self.call("run", str(link))
        self.assertEqual(r.returncode, 2)
        self.assertIn("not approved", r.stderr)

    def test_outside_project_is_refused(self):
        outside = Path(self.tmp.name) / "evil.py"
        outside.write_text("print('outside')\n")
        r = self.call("approve", str(outside))
        self.assertEqual(r.returncode, 2)
        self.assertIn("outside the project", r.stderr)

    def test_worktree_uses_main_checkout_ledger(self):
        main = Path(self.tmp.name) / "real"
        subprocess.run(["git", "init", "-q", str(main)], check=True)
        (main / "tool.py").write_text("print('ok')\n")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "-C", str(main), "add", "tool.py"], check=True)
        subprocess.run(["git", "-C", str(main), "commit", "-qm", "x"], check=True, env=env)
        wt = Path(self.tmp.name) / "wt"
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt)], check=True)
        r = subprocess.run([sys.executable, str(SCRIPT), "approve", "tool.py"], cwd=wt,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((main / ".claude" / "script-approvals.json").exists())
        self.assertFalse((wt / ".claude" / "script-approvals.json").exists())
        # the approval made in the worktree is honoured from the main checkout
        r = subprocess.run([sys.executable, str(SCRIPT), "run", "tool.py"], cwd=main,
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "ok", r.stderr)

    def test_revoke_then_refused(self):
        self.call("approve", str(self.s))
        self.call("revoke", str(self.s))
        self.assertEqual(self.call("run", str(self.s)).returncode, 2)


if __name__ == "__main__":
    unittest.main()
