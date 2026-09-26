#!/usr/bin/env python3
"""Tests for the `instructions` key that adapters/opencode/install.py manages.

install.py puts the absolute path of adapters/opencode/SESSION.md into OpenCode's
`instructions` list, so every OpenCode session loads the session contract (Lodewijk,
2026-09-26). Unlike the other owned keys, `instructions` is owned PER ENTRY: the user may
list their own files there, and a deploy must keep them. These tests prove that:

  * the built config carries the entry, as the correct absolute path;
  * user entries survive a merge, and only install.py's own entry is added/replaced;
  * --check flags the entry when missing and passes when it sits among user entries;
  * a missing SESSION.md is refused rather than written as a dangling instruction;
  * the other owned keys still behave as before (wholesale ownership, removal on absence).

Self-contained on purpose: nothing is imported from test_install.py.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
SCRIPT = REPO / "agent-tooling" / "adapters" / "opencode" / "install.py"
# Derived independently of install.py, from this test file's own location.
EXPECTED_SESSION = str(REPO / "agent-tooling" / "adapters" / "opencode" / "SESSION.md")


def load_module():
    spec = importlib.util.spec_from_file_location("install_under_test_instructions", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_module()

MACHINE = {
    "machine": "test",
    "repo_root": "/tmp/repo",
    "harness_models": {"code": "a/b"},
    "enabled_providers": ["a"],
    "default_model": "a/b",
    "extra_allowed_paths": [],
}
SETTINGS = {"env": {"AGENT_TOOLING_ROOT": str(M.REPO_ROOT / "agent-tooling")}}
USER_ENTRIES = ["/Users/someone/rules/house-style.md", "docs/*.md"]


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **kw), buf.getvalue()


def run_check(live_cfg, machine=MACHINE):
    """phase_check against a temp HOME. Returns (rc, stdout)."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        (home / "opencode.json").write_text(json.dumps(live_cfg), encoding="utf-8")
        (home / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
        saved = (M.OPENCODE_HOME, M.CLAUDE_HOME, M.probe_opencode_version, M.check_symlinks)
        M.OPENCODE_HOME = M.CLAUDE_HOME = home
        M.probe_opencode_version = lambda: M.pinned_version()
        M.check_symlinks = lambda: (0, [])
        try:
            return quiet(M.phase_check, machine)
        finally:
            (M.OPENCODE_HOME, M.CLAUDE_HOME,
             M.probe_opencode_version, M.check_symlinks) = saved


def clean_live():
    """A live config that is exactly what a deploy onto an empty config would write."""
    merged, _ = M.compute_merged(MACHINE)
    return json.loads(json.dumps(merged))


class TestBuiltConfigCarriesEntry(unittest.TestCase):
    def test_owned_entry_is_the_absolute_session_md(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertEqual(owned.get("instructions"), [EXPECTED_SESSION])
        self.assertTrue(os.path.isabs(owned["instructions"][0]))
        self.assertTrue(Path(owned["instructions"][0]).is_file())

    def test_merged_onto_empty_config_has_only_our_entry(self):
        merged, _ = M.compute_merged(MACHINE, {})
        self.assertEqual(merged["instructions"], [EXPECTED_SESSION])

    def test_instructions_is_an_owned_key(self):
        self.assertIn("instructions", M.OWNED_OPENCODE_KEYS)


class TestMergePreservesUserEntries(unittest.TestCase):
    def test_user_entries_kept_in_order_ours_appended(self):
        merged, _ = M.compute_merged(MACHINE, {"instructions": list(USER_ENTRIES)})
        self.assertEqual(merged["instructions"], USER_ENTRIES + [EXPECTED_SESSION])

    def test_present_entry_left_in_place(self):
        live = [USER_ENTRIES[0], EXPECTED_SESSION, USER_ENTRIES[1]]
        merged, _ = M.compute_merged(MACHINE, {"instructions": list(live)})
        self.assertEqual(merged["instructions"], live)

    def test_duplicate_own_entry_collapsed(self):
        live = [EXPECTED_SESSION, USER_ENTRIES[0], EXPECTED_SESSION]
        merged, _ = M.compute_merged(MACHINE, {"instructions": live})
        self.assertEqual(merged["instructions"], [EXPECTED_SESSION, USER_ENTRIES[0]])

    def test_stale_own_entry_replaced_unrelated_session_md_kept(self):
        stale = "/old/checkout/agent-tooling/adapters/opencode/SESSION.md"
        unrelated = "/Users/someone/notes/SESSION.md"     # same basename, not ours
        merged, _ = M.compute_merged(
            MACHINE, {"instructions": [stale, unrelated, USER_ENTRIES[0]]})
        self.assertEqual(merged["instructions"],
                         [unrelated, USER_ENTRIES[0], EXPECTED_SESSION])

    def test_scalar_string_is_kept_as_a_list(self):
        merged, _ = M.compute_merged(MACHINE, {"instructions": USER_ENTRIES[0]})
        self.assertEqual(merged["instructions"], [USER_ENTRIES[0], EXPECTED_SESSION])

    def test_unmergeable_value_is_refused_not_overwritten(self):
        with self.assertRaises(SystemExit) as cm:
            quiet(M.compute_merged, MACHINE, {"instructions": {"a": 1}})
        self.assertEqual(cm.exception.code, 2)


class TestCheckInstructions(unittest.TestCase):
    def test_clean_is_zero(self):
        rc, out = run_check(clean_live())
        self.assertEqual(rc, 0, out)

    def test_missing_entry_is_drift(self):
        live = clean_live()
        live["instructions"] = list(USER_ENTRIES)
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"instructions (missing entry {EXPECTED_SESSION})", out)

    def test_absent_key_is_drift(self):
        live = clean_live()
        del live["instructions"]
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        self.assertIn("instructions (missing entry", out)

    def test_present_alongside_user_entries_is_clean(self):
        live = clean_live()
        live["instructions"] = [USER_ENTRIES[0], EXPECTED_SESSION, USER_ENTRIES[1]]
        rc, out = run_check(live)
        self.assertEqual(rc, 0, out)
        self.assertIn("config: in sync", out)

    def test_stale_own_entry_is_drift(self):
        live = clean_live()
        live["instructions"] = [EXPECTED_SESSION,
                                "/gone/worktree/agent-tooling/adapters/opencode/SESSION.md"]
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        self.assertIn("stale SESSION.md entry", out)


class TestMissingSessionMdRefused(unittest.TestCase):
    def _with_session(self, path):
        saved = M.SESSION_MD
        M.SESSION_MD = path
        return saved

    def test_missing_file_refuses_build_merge_and_check(self):
        with tempfile.TemporaryDirectory() as td:
            saved = self._with_session(Path(td) / "SESSION.md")   # never created
            try:
                for fn, args in ((M.build_config, (MACHINE,)),
                                 (M.compute_merged, (MACHINE, {})),
                                 (run_check, ({},))):
                    with self.assertRaises(SystemExit) as cm:
                        quiet(fn, *args)
                    self.assertNotEqual(cm.exception.code, 0, fn.__name__)
                    self.assertNotEqual(cm.exception.code, None, fn.__name__)
            finally:
                M.SESSION_MD = saved

    def test_existing_file_is_accepted_positive_control(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SESSION.md"
            p.write_text("x", encoding="utf-8")
            saved = self._with_session(p)
            try:
                _, owned = M.compute_merged(MACHINE)
                self.assertEqual(owned["instructions"], [str(p)])
            finally:
                M.SESSION_MD = saved


class TestOtherOwnedKeysUnchanged(unittest.TestCase):
    def test_owned_set_is_previous_plus_instructions(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertEqual(set(owned),
                         {"permission", "agent", "enabled_providers", "model", "instructions"})

    def test_list_valued_owned_key_still_replaced_wholesale(self):
        merged, _ = M.compute_merged(MACHINE, {"enabled_providers": ["x", "y"]})
        self.assertEqual(merged["enabled_providers"], ["a"])

    def test_removed_owned_key_dropped_non_owned_kept(self):
        m = {k: v for k, v in MACHINE.items() if k != "default_model"}
        live = {"model": "old/model", "keep_me": {"a": 1}, "instructions": list(USER_ENTRIES)}
        merged, _ = M.compute_merged(m, live)
        self.assertNotIn("model", merged)
        self.assertEqual(merged["keep_me"], {"a": 1})

    def test_absent_provider_control_still_preserved(self):
        m = {k: v for k, v in MACHINE.items() if k != "enabled_providers"}
        merged, _ = M.compute_merged(m, {"enabled_providers": ["openrouter"]})
        self.assertEqual(merged["enabled_providers"], ["openrouter"])

    def test_hand_edited_permission_still_drift_with_instructions_clean(self):
        live = clean_live()
        live["instructions"] = [USER_ENTRIES[0], EXPECTED_SESSION]
        live["permission"]["bash"]["sudo *"] = "allow"
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        self.assertIn("permission.bash.sudo *", out)

    def test_extra_list_entry_in_owned_key_still_drift(self):
        live = clean_live()
        live["enabled_providers"] = ["a", "extra"]
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)


if __name__ == "__main__":
    unittest.main()
