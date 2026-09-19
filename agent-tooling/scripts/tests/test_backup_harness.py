#!/usr/bin/env python3
"""Tests for scripts/backup_harness.py.

A backup that silently omits the gitignored working notes, or silently includes the
disposable 663 MB refs tree and the delivery outbox, is worse than none: the first
loses the thing it exists to protect, the second copies data that should not travel.
These pin both directions.
"""
from __future__ import annotations

import importlib.util
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "backup_harness.py"


def load_module():
    spec = importlib.util.spec_from_file_location("backup_harness", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_module()


class TestBackup(unittest.TestCase):
    def test_includes_state_excludes_refs_and_outbox(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            (repo / "agent-tooling").mkdir(parents=True)
            (repo / "agent-tooling" / "keep.py").write_text("x", encoding="utf-8")
            (repo / ".claude" / "refs").mkdir(parents=True)
            (repo / ".claude" / "refs" / "thirdparty.html").write_text("x", encoding="utf-8")
            (repo / ".claude" / "note.md").write_text("note", encoding="utf-8")
            (repo / "agent-tooling" / "__pycache__").mkdir()
            (repo / "agent-tooling" / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")

            agent = root / "agent"
            agent.mkdir()
            (agent / "machine.json").write_text("{}", encoding="utf-8")
            (agent / "outbox").mkdir()
            (agent / "outbox" / "delivered.txt").write_text("data", encoding="utf-8")
            (agent / "backups").mkdir()
            (agent / "backups" / "old.tar.gz").write_text("old", encoding="utf-8")

            out = root / "b.tar.gz"
            M.build_archive(M.collect(repo, agent), out)
            with tarfile.open(out) as tar:
                names = tar.getnames()

            self.assertTrue(any(n.endswith("keep.py") for n in names), names)
            self.assertTrue(any(n.endswith(".claude/note.md") for n in names), names)
            self.assertTrue(any(n.endswith("machine.json") for n in names), names)
            self.assertFalse(any("refs" in n for n in names), names)
            self.assertFalse(any("outbox" in n for n in names), names)
            self.assertFalse(any("backups" in n for n in names), names)
            self.assertFalse(any(n.endswith(".pyc") for n in names), names)

    def test_nothing_to_back_up(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(M.collect(root / "nope", root / "also-nope"), [])


if __name__ == "__main__":
    unittest.main()
