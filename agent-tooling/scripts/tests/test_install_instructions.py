#!/usr/bin/env python3
"""Tests for the `instructions` key that adapters/opencode/install.py manages.

install.py puts the absolute paths of agent-tooling/OPERATING-NOTES.md and
adapters/opencode/SESSION.md, in that order, into OpenCode's `instructions` list, so every
OpenCode session loads the operating notes and the session contract (Lodewijk,
2026-09-26). Unlike the other owned keys, `instructions` is owned PER ENTRY: the user may
list their own files there, and a deploy must keep them. These tests prove, for EACH owned
entry:

  * the built config carries both entries, as the correct absolute paths, in order;
  * user entries survive a merge, and only install.py's own entries are added/replaced;
  * duplicates of an owned entry collapse, and a stale copy (another checkout) is replaced;
  * --check names each missing or stale entry, and passes when they sit among user entries;
  * a missing OPERATING-NOTES.md or SESSION.md is refused rather than written as a
    dangling instruction;
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
EXPECTED_NOTES = str(REPO / "agent-tooling" / "OPERATING-NOTES.md")
EXPECTED_SESSION = str(REPO / "agent-tooling" / "adapters" / "opencode" / "SESSION.md")
EXPECTED = [EXPECTED_NOTES, EXPECTED_SESSION]            # the owned entries, in order

# (display name, expected absolute path, repo-relative suffix, install.py global)
OWNED = (
    ("OPERATING-NOTES.md", EXPECTED_NOTES, "/agent-tooling/OPERATING-NOTES.md",
     "OPERATING_NOTES_MD"),
    ("SESSION.md", EXPECTED_SESSION, "/agent-tooling/adapters/opencode/SESSION.md",
     "SESSION_MD"),
)


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


def others(path):
    """The owned entries other than `path`, in owned order."""
    return [e for e in EXPECTED if e != path]


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*a, **kw), buf.getvalue()


def exit_and_output(fn, *a):
    """Run fn expecting SystemExit; return (exit code, captured stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            fn(*a)
        except SystemExit as e:
            return e.code, buf.getvalue()
    raise AssertionError(f"{fn.__name__} did not exit; output:\n{buf.getvalue()}")


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


def merged_instructions(live_value):
    merged, _ = M.compute_merged(MACHINE, {"instructions": live_value})
    return merged["instructions"]


@contextlib.contextmanager
def patched(**attrs):
    """Temporarily set install.py module globals (e.g. OPERATING_NOTES_MD)."""
    saved = {k: getattr(M, k) for k in attrs}
    for k, v in attrs.items():
        setattr(M, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(M, k, v)


class TestBuiltConfigCarriesEntries(unittest.TestCase):
    def test_both_entries_appear_in_order(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertEqual(owned.get("instructions"), EXPECTED)
        # Spelled out, so a swapped order cannot pass by comparing two wrong lists.
        self.assertTrue(owned["instructions"][0].endswith("/agent-tooling/OPERATING-NOTES.md"))
        self.assertTrue(owned["instructions"][1].endswith("/opencode/SESSION.md"))

    def test_each_entry_is_an_absolute_existing_file(self):
        _, owned = M.compute_merged(MACHINE)
        for e in owned["instructions"]:
            with self.subTest(entry=e):
                self.assertTrue(os.path.isabs(e))
                self.assertTrue(Path(e).is_file())

    def test_merged_onto_empty_config_has_only_our_entries_in_order(self):
        merged, _ = M.compute_merged(MACHINE, {})
        self.assertEqual(merged["instructions"], EXPECTED)

    def test_instructions_is_an_owned_key(self):
        self.assertIn("instructions", M.OWNED_OPENCODE_KEYS)


class TestMergePreservesUserEntries(unittest.TestCase):
    def test_user_entries_kept_in_order_ours_appended_in_order(self):
        self.assertEqual(merged_instructions(list(USER_ENTRIES)), USER_ENTRIES + EXPECTED)

    def test_both_present_left_in_place(self):
        live = [USER_ENTRIES[0], EXPECTED_NOTES, USER_ENTRIES[1], EXPECTED_SESSION]
        self.assertEqual(merged_instructions(list(live)), live)

    def test_each_present_entry_left_in_place_other_appended(self):
        for name, path, _, _ in OWNED:
            with self.subTest(present=name):
                live = [USER_ENTRIES[0], path, USER_ENTRIES[1]]
                self.assertEqual(merged_instructions(list(live)), live + others(path))

    def test_upgrade_from_session_only_appends_notes_after_it(self):
        # The deployed state before OPERATING-NOTES.md existed. A present entry is not
        # moved, so the notes land after SESSION.md; pinned here so the order is a choice.
        live = [USER_ENTRIES[0], EXPECTED_SESSION]
        self.assertEqual(merged_instructions(list(live)),
                         [USER_ENTRIES[0], EXPECTED_SESSION, EXPECTED_NOTES])

    def test_each_duplicate_own_entry_collapsed(self):
        for name, path, _, _ in OWNED:
            with self.subTest(duplicated=name):
                live = [path, USER_ENTRIES[0], path]
                self.assertEqual(merged_instructions(live),
                                 [path, USER_ENTRIES[0]] + others(path))

    def test_both_duplicated_collapse_to_one_each(self):
        live = EXPECTED + [USER_ENTRIES[0]] + EXPECTED
        self.assertEqual(merged_instructions(live), EXPECTED + [USER_ENTRIES[0]])

    def test_each_stale_own_entry_replaced_unrelated_same_basename_kept(self):
        for name, _, suffix, _ in OWNED:
            with self.subTest(stale=name):
                stale = "/old/checkout" + suffix
                unrelated = "/Users/someone/notes/" + name     # same basename, not ours
                self.assertEqual(
                    merged_instructions([stale, unrelated, USER_ENTRIES[0]]),
                    [unrelated, USER_ENTRIES[0]] + EXPECTED)

    def test_stale_operating_notes_entry_replaced(self):
        stale = "/gone/worktree/agent-tooling/OPERATING-NOTES.md"
        out = merged_instructions([USER_ENTRIES[0], stale, EXPECTED_SESSION])
        self.assertNotIn(stale, out)
        self.assertEqual(out, [USER_ENTRIES[0], EXPECTED_SESSION, EXPECTED_NOTES])

    def test_merge_is_idempotent(self):
        once = merged_instructions([USER_ENTRIES[0], "/old/agent-tooling/OPERATING-NOTES.md",
                                    EXPECTED_SESSION, USER_ENTRIES[1]])
        self.assertEqual(merged_instructions(list(once)), once)

    def test_scalar_string_is_kept_as_a_list(self):
        self.assertEqual(merged_instructions(USER_ENTRIES[0]), [USER_ENTRIES[0]] + EXPECTED)

    def test_unmergeable_value_is_refused_not_overwritten(self):
        with self.assertRaises(SystemExit) as cm:
            quiet(M.compute_merged, MACHINE, {"instructions": {"a": 1}})
        self.assertEqual(cm.exception.code, 2)


class TestCheckInstructions(unittest.TestCase):
    def test_clean_is_zero(self):
        rc, out = run_check(clean_live())
        self.assertEqual(rc, 0, out)

    def test_check_names_which_entry_is_missing(self):
        for name, path, _, _ in OWNED:
            with self.subTest(missing=name):
                live = clean_live()
                live["instructions"] = USER_ENTRIES + others(path)
                rc, out = run_check(live)
                self.assertEqual(rc, 1, out)
                self.assertIn(f"instructions (missing entry {path})", out)
                for o in others(path):
                    self.assertNotIn(f"missing entry {o}", out)
                self.assertIn("1 key(s) differ", out)

    def test_both_missing_reported_separately(self):
        live = clean_live()
        live["instructions"] = list(USER_ENTRIES)
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        for path in EXPECTED:
            self.assertIn(f"instructions (missing entry {path})", out)
        self.assertIn("2 key(s) differ", out)

    def test_absent_key_reports_both_missing(self):
        live = clean_live()
        del live["instructions"]
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        for path in EXPECTED:
            self.assertIn(f"instructions (missing entry {path})", out)

    def test_present_alongside_user_entries_is_clean(self):
        live = clean_live()
        live["instructions"] = [USER_ENTRIES[0], EXPECTED_NOTES, USER_ENTRIES[1],
                                EXPECTED_SESSION]
        rc, out = run_check(live)
        self.assertEqual(rc, 0, out)
        self.assertIn("config: in sync", out)

    def test_upgraded_order_is_clean(self):
        # What a deploy onto a SESSION.md-only config writes must check clean.
        live = clean_live()
        live["instructions"] = merged_instructions([EXPECTED_SESSION])
        rc, out = run_check(live)
        self.assertEqual(rc, 0, out)

    def test_each_stale_own_entry_is_drift_and_named(self):
        for name, _, suffix, _ in OWNED:
            with self.subTest(stale=name):
                live = clean_live()
                stale = "/gone/worktree" + suffix
                live["instructions"] = EXPECTED + [stale]
                rc, out = run_check(live)
                self.assertEqual(rc, 1, out)
                self.assertIn(f"instructions (stale {name} entry {stale}", out)


class TestMissingFilesRefused(unittest.TestCase):
    def test_each_missing_file_refuses_build_merge_and_check(self):
        for name, _, _, attr in OWNED:
            with self.subTest(missing=name), tempfile.TemporaryDirectory() as td:
                gone = Path(td) / name                       # never created
                with patched(**{attr: gone}):
                    for fn, args in ((M.build_config, (MACHINE,)),
                                     (M.compute_merged, (MACHINE, {})),
                                     (run_check, ({},))):
                        code, out = exit_and_output(fn, *args)
                        self.assertNotIn(code, (0, None), fn.__name__)
                        if fn is not run_check:      # run_check captures its own stdout
                            self.assertIn(f"REFUSED: {gone} does not exist.", out,
                                          fn.__name__)

    def test_missing_operating_notes_refused(self):
        with tempfile.TemporaryDirectory() as td:
            gone = Path(td) / "OPERATING-NOTES.md"
            with patched(OPERATING_NOTES_MD=gone):
                code, out = exit_and_output(M.build_config, MACHINE)
        self.assertEqual(code, 1)
        self.assertIn(f"REFUSED: {gone} does not exist.", out)
        self.assertNotIn("SESSION.md does not exist", out)

    def test_both_missing_both_named(self):
        with tempfile.TemporaryDirectory() as td:
            notes, session = Path(td) / "OPERATING-NOTES.md", Path(td) / "SESSION.md"
            with patched(OPERATING_NOTES_MD=notes, SESSION_MD=session):
                code, out = exit_and_output(M.build_config, MACHINE)
        self.assertEqual(code, 1)
        self.assertIn(f"REFUSED: {notes} does not exist.", out)
        self.assertIn(f"REFUSED: {session} does not exist.", out)

    def test_existing_files_are_accepted_positive_control(self):
        with tempfile.TemporaryDirectory() as td:
            notes, session = Path(td) / "OPERATING-NOTES.md", Path(td) / "SESSION.md"
            for p in (notes, session):
                p.write_text("x", encoding="utf-8")
            with patched(OPERATING_NOTES_MD=notes, SESSION_MD=session):
                _, owned = M.compute_merged(MACHINE)
        self.assertEqual(owned["instructions"], [str(notes), str(session)])


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
        self.assertEqual(merged["instructions"], USER_ENTRIES + EXPECTED)

    def test_absent_provider_control_still_preserved(self):
        m = {k: v for k, v in MACHINE.items() if k != "enabled_providers"}
        merged, _ = M.compute_merged(m, {"enabled_providers": ["openrouter"]})
        self.assertEqual(merged["enabled_providers"], ["openrouter"])

    def test_hand_edited_permission_still_drift_with_instructions_clean(self):
        live = clean_live()
        live["instructions"] = [USER_ENTRIES[0]] + EXPECTED
        live["permission"]["bash"]["sudo *"] = "allow"
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)
        self.assertIn("permission.bash.sudo *", out)
        self.assertNotIn("instructions (", out)

    def test_extra_list_entry_in_owned_key_still_drift(self):
        live = clean_live()
        live["enabled_providers"] = ["a", "extra"]
        rc, out = run_check(live)
        self.assertEqual(rc, 1, out)


if __name__ == "__main__":
    unittest.main()
