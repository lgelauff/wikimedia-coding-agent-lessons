#!/usr/bin/env python3
"""Tests for scripts/check_skill_vars.py.

Runs the guard as a subprocess against throwaway fixtures, so the real skills
tree is never mutated by a failing case.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check_skill_vars.py"


def write_skill(root: Path, name: str, body: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        capture_output=True, text=True,
    )


class TestCheckSkillVars(unittest.TestCase):
    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "good", "Run `${AGENT_TOOLING_ROOT}/scripts/x.py`\n")
            write_skill(root, "alsogood", "Use `$PATH` and `${HOME}` freely.\n")
            r = run(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("2 skills", r.stdout)

    def test_skill_dir_is_flagged(self):
        """The real historical bug: $SKILL_DIR referenced but never injected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "bad", 'python3 "$SKILL_DIR/../../scripts/x.py"\n')
            r = run(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("SKILL_DIR", r.stderr)
            self.assertIn("not defined anywhere", r.stderr)

    def test_braced_and_bare_forms_both_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "bad", "a ${SKILL_DIR} b $SKILL_DIR c\n")
            r = run(root)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stderr.count("SKILL_DIR"), 2)

    def test_host_specific_var_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "bad", 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"\n')
            r = run(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("host-specific", r.stderr)

    def test_unknown_path_shaped_var_is_flagged(self):
        """Catch the general class, not just the two known names."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "bad", "python3 \"$FUTURE_PLUGIN_DIR/x.py\"\n")
            r = run(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("path-shaped", r.stderr)

    def test_non_path_unknown_var_is_not_flagged(self):
        """Deliberately narrow: ordinary shell vars must not create noise."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_skill(root, "ok", "export FOO=1; echo $FOO $PWD ${LANG}\n")
            r = run(root)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_directory_exits_two(self):
        r = run(Path("/nonexistent-skills-dir-xyz"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no such directory", r.stderr)

    def test_empty_tree_exits_two_not_zero(self):
        """An empty scan is unverified, never clean."""
        with tempfile.TemporaryDirectory() as td:
            r = run(Path(td))
            self.assertEqual(r.returncode, 2)
            self.assertIn("no SKILL.md", r.stderr)

    def test_real_skills_tree_is_clean(self):
        """The regression test that matters: the shipped tree must pass."""
        real = SCRIPT.resolve().parent.parent / "skills"
        if not real.is_dir():
            self.skipTest("skills tree not present")
        r = run(real)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
