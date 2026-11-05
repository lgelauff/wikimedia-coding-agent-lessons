#!/usr/bin/env python3
"""Tests for scripts/vault_ingest.py.

The failure it exists for: ingest.py reads inbox/pending.txt, works, then rewrites
the whole file, so a block appended during a run is silently lost; and two runs
at once both rewrite index.json. The control test shows the loss without the
lock; the others show the lock prevents it, names the holder, and refuses unsafe
flags. A fake ingest.py stands in for the real one (no network, no uv).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "vault_ingest.py"

# Same read-work-rewrite shape as the real ingest.py (_parse_pending/_render_pending).
FAKE_INGEST = textwrap.dedent('''
    import re, sys, time, pathlib
    p = pathlib.Path(__file__).parent / "inbox" / "pending.txt"
    text = p.read_text(encoding="utf-8")
    blocks = [b.strip() for b in re.split(r"\\n---\\n", text) if b.strip()]
    time.sleep(float(pathlib.Path(__file__).with_name("SLEEP").read_text()))
    p.write_text("\\n---\\n".join(blocks) + "\\n", encoding="utf-8")
    sys.exit(0)
''')


def blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n---\n", text) if b.strip()]


class VaultIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.vault = t / "vault"
        (self.vault / "inbox").mkdir(parents=True)
        (self.vault / "ingest.py").write_text(FAKE_INGEST, encoding="utf-8")
        (self.vault / "SLEEP").write_text("3", encoding="utf-8")
        self.pending = self.vault / "inbox" / "pending.txt"
        self.pending.write_text("query:     A\nstatus:     pending\n\n", encoding="utf-8")
        self.env = dict(os.environ, VAULT_INGEST_STATE=str(t / "locks"),
                        VAULT_INGEST_PYTHON=sys.executable)

    def tearDown(self):
        self.tmp.cleanup()

    def cmd(self, *args):
        return [sys.executable, str(SCRIPT), *args[:1], "--vault", str(self.vault), *args[1:]]

    def run_(self, *args, **kw):
        return subprocess.run(self.cmd(*args), env=self.env, capture_output=True, text=True, timeout=60, **kw)

    def start_run(self):
        p = subprocess.Popen(self.cmd("run", "--session", "S-A", "--", "--collect", "--auto"),
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(1.0)  # let it take the lock and read pending.txt
        return p

    def test_control_plain_append_during_a_run_is_lost(self):
        # the failure class: append without the lock while the run sleeps
        p = self.start_run()
        with open(self.pending, "a", encoding="utf-8") as f:
            f.write("---\nquery:     B\nstatus:     pending\n")
        p.communicate(timeout=30)
        self.assertNotIn("query:     B", self.pending.read_text(), "control: the unlocked append should be lost")

    def test_add_pending_during_a_run_is_refused_and_names_holder(self):
        p = self.start_run()
        r = self.run_("add-pending", "--session", "S-B", "--query", "B", "--doi", "10.1/x")
        p.communicate(timeout=30)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("S-A", r.stderr)
        self.assertNotIn("query:     B", self.pending.read_text())

    def test_add_pending_with_wait_survives_the_rewrite(self):
        p = self.start_run()
        r = self.run_("add-pending", "--session", "S-B", "--query", "B", "--doi", "10.1/x", "--wait", "30")
        p.communicate(timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = blocks(self.pending.read_text())
        self.assertEqual(len(got), 2, got)
        self.assertIn("query:     B", got[1])
        self.assertIn("requested_by:     S-B", got[1])

    def test_second_run_is_refused_while_first_holds(self):
        p = self.start_run()
        r = self.run_("run", "--session", "S-B", "--", "--audit")
        p.communicate(timeout=30)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("S-A", r.stderr)

    def test_status_busy_then_free(self):
        p = self.start_run()
        busy = self.run_("status")
        p.communicate(timeout=30)
        free = self.run_("status")
        self.assertEqual((busy.returncode, free.returncode), (1, 0), busy.stdout + free.stdout)

    def test_unsafe_or_missing_args_are_refused(self):
        (self.vault / "SLEEP").write_text("0", encoding="utf-8")
        for args in (["run", "--session", "S", "--", "--collect", "--auto", "--force"],
                     ["run", "--session", "S", "--", "--collect"],
                     ["run", "--session", "S", "--", "--pdf", "/etc/passwd"],
                     ["run", "--session", "S"],
                     ["run", "--", "--audit"],
                     ["add-pending", "--session", "S", "--query", "no doi or url"]):
            with self.subTest(args=args):
                self.assertEqual(self.run_(*args).returncode, 2)

    def test_runs_are_logged(self):
        (self.vault / "SLEEP").write_text("0", encoding="utf-8")
        self.assertEqual(self.run_("run", "--session", "S-log", "--", "--audit").returncode, 0)
        log = (Path(self.env["VAULT_INGEST_STATE"]) / "research-vault-RUNS.tsv").read_text()
        self.assertIn("S-log\trun\t--audit\t0", log)


if __name__ == "__main__":
    unittest.main()
