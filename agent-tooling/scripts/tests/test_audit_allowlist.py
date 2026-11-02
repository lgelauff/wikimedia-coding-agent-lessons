#!/usr/bin/env python3
"""Tests for scripts/audit_allowlist.py.

Each risky class is shown to be CAUGHT (exit 1), exact invocations are shown to
pass, and an unreadable input is shown to give exit 2, never a false clean.
The three rules found on 2026-11-02 are the first fixtures.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "audit_allowlist.py"
sys.path.insert(0, str(SCRIPT.parent))
import audit_allowlist  # noqa: E402


def run(*files: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, files)],
                          capture_output=True, text=True)


def settings(tmp: Path, allow: list, name: str = "settings.local.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps({"permissions": {"allow": allow}}), encoding="utf-8")
    return p


class Verdicts(unittest.TestCase):
    CAUGHT = [
        # found in the main checkout, 2026-11-02
        "Bash(python3 -c ' *)",
        "Bash(gh auth *)",
        "Bash(git clone *)",
        # AGENTS.md's named examples
        "Bash(python:*)",
        "Bash(npx *)",
        "Bash(uv run *)",
        "Bash(make *)",
        "Bash(docker run *)",
        "Bash(ssh remote-host)",
        "Bash(sudo launchctl list)",
        # other shapes
        "Bash",
        "Bash(*)",
        "Bash(/usr/bin/python3 *)",
        "Bash(python3.12 -c *)",
        "Bash(FOO=1 node *)",
        "Bash(bash -c *)",
        "Bash(xargs *)",
        "Bash(env *)",
        "Bash(gh api *)",
        "Bash(curl *)",
    ]
    PASSES = [
        "Bash(python3 -m pytest agent-tooling/policies/tests/ -q)",
        "Bash(python3 /Users/x/agent-tooling/scripts/lint_skills.py)",
        "Bash(shasum -a 256 -c SHA256SUMS)",
        "Bash(git -C /repo status)",
        "Bash(git status *)",
        "Bash(gh pr view *)",
        "Read(//Users/x/**)",
        "WebFetch(domain:example.org)",
        "mcp__ccd_session__start_session",
    ]

    def test_risky_rules_are_caught(self):
        for rule in self.CAUGHT:
            with self.subTest(rule=rule):
                self.assertIsNotNone(audit_allowlist.verdict(rule), rule)

    def test_exact_and_non_bash_rules_pass(self):
        for rule in self.PASSES:
            with self.subTest(rule=rule):
                self.assertIsNone(audit_allowlist.verdict(rule), rule)


class Cli(unittest.TestCase):
    def test_exit_1_on_risky_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = settings(Path(d), ["Bash(git -C /r status)", "Bash(python3 -c ' *)"])
            r = run(p)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("python3", r.stdout)

    def test_exit_0_on_clean_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = settings(Path(d), ["Bash(git -C /r status)", "Read(//tmp/**)"])
            r = run(p)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_exit_2_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(run(p).returncode, 2)

    def test_exit_2_on_missing_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text(json.dumps({"env": {}}), encoding="utf-8")
            self.assertEqual(run(p).returncode, 2)

    def test_exit_2_when_one_of_two_files_is_unreadable(self):
        # a clean file must not mask a broken one
        with tempfile.TemporaryDirectory() as d:
            good = settings(Path(d), ["Bash(git -C /r status)"])
            bad = Path(d) / "missing.json"
            self.assertEqual(run(good, bad).returncode, 2)


if __name__ == "__main__":
    unittest.main()
