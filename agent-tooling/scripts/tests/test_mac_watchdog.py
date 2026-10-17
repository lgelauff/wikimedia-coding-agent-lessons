#!/usr/bin/env python3
"""Tests for scripts/mac_watchdog.py — the guard against the 2026-10-10 runaway-git panic.

A watchdog that never fires is trusted and useless; one that kills the wrong thing is worse. So these pin both
directions: the 10-10 shape (git under a Claude Code process, huge footprint) is killed, and every near miss is not.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "mac_watchdog.py"
spec = importlib.util.spec_from_file_location("mac_watchdog", SCRIPT)
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

GB = 1024**3
CLAUDE = "/Users/x/Library/Application Support/Claude/claude-code/2.1.293/abc/claude.app/Contents/MacOS/claude --output-format stream-json"


def table(extra):
    t = {1: (0, 10, "/sbin/launchd"), 100: (1, 50000, CLAUDE), 101: (100, 2000, "/bin/zsh -c source snap.sh && git status")}
    t.update(extra)
    return t


def fp_from(sizes):
    return lambda pid, rss_kb: sizes.get(pid, rss_kb * 1024)


class Decide(unittest.TestCase):
    def test_kills_the_10_10_shape(self):
        t = table({102: (101, 4000, "/opt/homebrew/bin/git -C repo log --all"), 103: (101, 10, "cut -c1-80")})
        _, kills = W.decide(t, 0.5, 100, fp_from({102: int(19.3 * GB)}))
        self.assertEqual([k[0] for k in kills], [102])

    def test_spares_git_not_under_claude(self):
        t = table({200: (1, 4000, "/usr/bin/zsh"), 201: (200, 4000, "git gc --aggressive")})
        _, kills = W.decide(t, 0.5, 100, fp_from({201: 10 * GB}))
        self.assertEqual(kills, [])

    def test_spares_small_git_under_claude(self):
        t = table({102: (101, 4000, "git status")})
        _, kills = W.decide(t, 0.5, 100, fp_from({102: 2 * GB}))
        self.assertEqual(kills, [])

    def test_spares_big_non_git_under_claude(self):
        t = table({102: (101, 4000, ".venv/bin/python -m analysis.big_job"), 103: (101, 1, "/opt/homebrew/bin/gitk")})
        _, kills = W.decide(t, 0.5, 100, fp_from({102: 12 * GB, 103: 12 * GB}))
        self.assertEqual(kills, [])

    def test_never_kills_claude_itself(self):
        _, kills = W.decide(table({}), 0.5, 100, fp_from({100: 20 * GB}))
        self.assertEqual(kills, [])

    def test_warnings(self):
        notes, _ = W.decide(table({}), 0.91, 9.6, fp_from({}))
        self.assertEqual(sorted(k for k, _ in notes), ["disk", "swap"])
        notes, _ = W.decide(table({}), 0.50, 40, fp_from({}))
        self.assertEqual(notes, [])

    def test_unknown_swap_is_not_a_warning(self):
        notes, _ = W.decide(table({}), None, 40, fp_from({}))
        self.assertEqual(notes, [])

    def test_parent_cycle_terminates(self):
        t = {5: (6, 1, "git x"), 6: (5, 1, "zsh")}
        self.assertFalse(W.under_claude(5, t))


if __name__ == "__main__":
    unittest.main()
