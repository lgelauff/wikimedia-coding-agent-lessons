"""Offline tests for coordinator_takeover (temp files only; never the real ~/agent notes)."""
import hashlib
import io
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import coordinator_takeover as ct  # noqa: E402

LOG = """# Agent log

## Sessions

| id | name | harness | where | role | started | pred | status |
|---|---|---|---|---|---|---|---|
| S001 | Setup | claude-code | mac | coordinator | 2026-09-21 | — | closed |
| S002 | sessions coordinator | claude-code | mac | coordinator | 2026-09-24 | S001 | active |

Rows S001–S002 are backfilled.

## Custody events

| # | date | type | from → to | what | by |
|---|---|---|---|---|---|
| E001 | 2026-09-24 | handoff | S001 → S002 | STATE | S001 |
| E009 | 2026-09-24 | close | S006 | out of order on purpose | S006 |
| E002 | 2026-09-24 | ack | S002 | STATE | S002 |
"""


def _plan(**kw):
    args = dict(log_text=LOG, state_path="/n/STATE.md", state_hash="ab" * 32, pred="S002",
                where="mac/x · repo", name="sessions coordinator", date="2026-09-26")
    args.update(kw)
    return ct.plan(**args)


class PlanTests(unittest.TestCase):
    def test_session_row_follows_last_session_row(self):
        text, srow, _ = _plan()
        lines = text.split("\n")
        self.assertEqual(lines[lines.index(srow) - 1][:6], "| S002")
        self.assertTrue(srow.startswith("| S003 | sessions coordinator |"))
        self.assertIn("| S002 | active |", srow)

    def test_event_row_is_last_event_and_numbered_past_the_max(self):
        text, _, erow = _plan()
        lines = text.split("\n")
        self.assertEqual(lines[lines.index(erow) - 1][:6], "| E002")
        self.assertTrue(erow.startswith("| E010 | 2026-09-26 | ack | S002 → S003 |"))
        self.assertIn("· abababab |", erow)

    def test_only_two_lines_added_and_nothing_else_changed(self):
        text, srow, erow = _plan()
        remaining = [l for l in text.split("\n") if l not in (srow, erow)]
        self.assertEqual(remaining, LOG.split("\n"))

    def test_unknown_pred_refused(self):
        with self.assertRaises(ct.TakeoverError):
            _plan(pred="S999")

    def test_taken_id_refused(self):
        with self.assertRaises(ct.TakeoverError):
            _plan(session_id="S001")

    def test_pipe_in_cell_refused(self):
        with self.assertRaises(ct.TakeoverError):
            _plan(where="mac | evil")

    def test_missing_tables_refused(self):
        with self.assertRaises(ct.TakeoverError):
            _plan(log_text="# empty\n")

    def test_one_table_missing_refused(self):
        only_sessions = LOG.split("## Custody events")[0]
        with self.assertRaises(ct.TakeoverError):
            _plan(log_text=only_sessions)

    def test_pred_that_already_handed_over_refused(self):
        with self.assertRaisesRegex(ct.TakeoverError, "already handed over to S002"):
            _plan(pred="S001")

    def test_malformed_id_and_date_refused(self):
        with self.assertRaises(ct.TakeoverError):
            _plan(session_id="foo")
        with self.assertRaises(ct.TakeoverError):
            _plan(date="2026-09-26 | x")

    def test_row_shaped_lines_in_a_code_block_or_later_section_are_ignored(self):
        log = LOG + "\n## Example\n\n```\n| S001 | x |\n| E001 | x |\n```\n| S050 | stray |\n"
        text, srow, erow = _plan(log_text=log)
        lines = text.split("\n")
        self.assertEqual(lines[lines.index(srow) - 1][:6], "| S002")
        self.assertEqual(lines[lines.index(erow) - 1][:6], "| E002")
        self.assertTrue(srow.startswith("| S003 |"))

    def test_fenced_example_inside_the_sessions_section_is_ignored(self):
        log = LOG.replace("Rows S001–S002 are backfilled.",
                          "Example:\n```\n| S077 | example |\n```")
        text, srow, _ = _plan(log_text=log)
        lines = text.split("\n")
        self.assertEqual(lines[lines.index(srow) - 1][:6], "| S002")
        self.assertTrue(srow.startswith("| S003 |"))

    def test_tables_in_either_order(self):
        head, rest = LOG.split("## Sessions")
        sessions, events = rest.split("## Custody events")
        swapped = head + "## Custody events" + events + "\n## Sessions" + sessions
        text, srow, erow = _plan(log_text=swapped)
        lines = text.split("\n")
        self.assertEqual(lines[lines.index(srow) - 1][:6], "| S002")
        self.assertEqual(lines[lines.index(erow) - 1][:6], "| E002")

    def test_ids_grow_past_three_digits(self):
        log = LOG.replace("| E009 |", "| E999 |").replace("| S002 |", "| S999 |").replace(
            "S001 → S002", "S001 → S999")
        _, srow, erow = _plan(log_text=log, pred="S999")
        self.assertTrue(srow.startswith("| S1000 |"))
        self.assertTrue(erow.startswith("| E1000 |"))

    def test_crlf_log_keeps_crlf(self):
        text, _, _ = _plan(log_text=LOG.replace("\n", "\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.state, self.log = d / "STATE.md", d / "AGENT-LOG.md"
        self.state.write_text("# state\nopen: x\n", encoding="utf-8")
        self.log.write_text(LOG, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = ct.main(["--pred", "S002", "--where", "mac", "--date", "2026-09-26",
                          "--state", str(self.state), "--log", str(self.log), *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_writes_rows_and_prints_state_with_its_hash(self):
        rc, out, _ = self._run()
        self.assertEqual(rc, 0)
        digest = hashlib.sha256(self.state.read_bytes()).hexdigest()
        self.assertIn(digest, out)
        self.assertIn("open: x", out)
        log = self.log.read_text(encoding="utf-8")
        self.assertIn("| S003 |", log)
        self.assertIn("· %s |" % digest[:8], log)

    def test_dry_run_writes_nothing(self):
        rc, out, _ = self._run("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("would append", out)
        self.assertEqual(self.log.read_text(encoding="utf-8"), LOG)

    def test_second_takeover_from_same_pred_refused(self):
        self._run()
        after_first = self.log.read_text(encoding="utf-8")
        rc, _, err = self._run()
        self.assertEqual(rc, 2)
        self.assertIn("already handed over to S003", err)
        self.assertEqual(self.log.read_text(encoding="utf-8"), after_first)

    def test_keeps_file_mode(self):
        os.chmod(str(self.log), 0o644)
        self._run()
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o644)

    def test_symlinked_log_stays_a_symlink(self):
        target = self.log.with_name("real-log.md")
        self.log.rename(target)
        self.log.symlink_to(target)
        self._run()
        self.assertTrue(self.log.is_symlink())
        self.assertIn("| S003 |", target.read_text(encoding="utf-8"))

    def test_undecodable_state_writes_nothing(self):
        self.state.write_bytes(b"\xff\xfe bad")
        with self.assertRaises(UnicodeDecodeError):
            self._run()
        self.assertEqual(self.log.read_text(encoding="utf-8"), LOG)

    def test_refusal_exits_nonzero_and_leaves_log(self):
        rc, _, err = self._run("--id", "S001")
        self.assertEqual(rc, 2)
        self.assertIn("refused", err)
        self.assertEqual(self.log.read_text(encoding="utf-8"), LOG)


if __name__ == "__main__":
    unittest.main()
