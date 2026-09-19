#!/usr/bin/env python3
"""Tests for scripts/bash_shape.py — the shape normaliser and the wildcard port.

A logger that leaks an argument, or a matcher that disagrees with OpenCode, is worse
than none: the report would drive the allowlist with wrong data. These tests pin both.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bash_shape.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bash_shape", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_module()


class TestShape(unittest.TestCase):
    def test_git_c_status(self):
        self.assertEqual(M.shape("git -C /repo status"), ("git status", False))

    def test_git_status_with_args(self):
        self.assertEqual(M.shape("git status --short"), ("git status", True))

    def test_commit_message_never_logged(self):
        sh, _ = M.shape("git commit -m 'secret token abc'")
        self.assertEqual(sh, "git commit")
        self.assertNotIn("secret", sh)

    def test_python_script_basename(self):
        self.assertEqual(
            M.shape("python3 agent-tooling/scripts/scope.py --json"),
            ("python3 scope.py", True),
        )

    def test_env_prefix_skipped(self):
        self.assertEqual(M.shape("FOO=bar mkdir -p a/b"), ("mkdir", True))

    def test_pipe_takes_first_segment(self):
        self.assertEqual(M.shape("cat x | jq ."), ("cat", True))

    def test_bare_and_flagged_ls(self):
        self.assertEqual(M.shape("ls"), ("ls", False))
        self.assertEqual(M.shape("ls -la"), ("ls", True))

    def test_empty_never_raises(self):
        self.assertEqual(M.shape(""), ("?", False))


class TestWildcard(unittest.TestCase):
    def test_trailing_star_is_optional(self):
        self.assertTrue(M.wildcard_match("ls", "ls *"))
        self.assertTrue(M.wildcard_match("git status", "git status *"))

    def test_middle_star_requires_text(self):
        self.assertTrue(M.wildcard_match("git -C /repo status", "git -C * status *"))
        self.assertFalse(M.wildcard_match("git status", "git -C * status *"))

    def test_dot_is_literal(self):
        self.assertTrue(M.wildcard_match("rg KEY .env", "*.env*"))
        self.assertFalse(M.wildcard_match("rg KEY .env", "*.key*"))

    def test_deny_after_allow(self):
        rules = [("rg *", "allow"), ("*.env*", "deny")]
        self.assertEqual(M.evaluate_action("rg KEY .env", rules), "deny")
        self.assertEqual(M.evaluate_action("rg KEY foo", rules), "allow")


if __name__ == "__main__":
    unittest.main()
