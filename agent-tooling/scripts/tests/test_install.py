#!/usr/bin/env python3
"""Tests for adapters/opencode/install.py — the drift logic behind `--check`.

`--check` exists because a hand-edit to the generated config used to be invisible: the
old check compared symlinks only. These tests must prove the new logic CATCHES a changed,
missing, or extra key — a guard that only ever reports clean is worse than none, because
it is trusted. The last test reproduces the exact failure the handoff named: one key
corrupted by hand must be reported by name.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent.parent
          / "adapters" / "opencode" / "install.py")


def load_module():
    spec = importlib.util.spec_from_file_location("install", SCRIPT)
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


class TestNameDiffs(unittest.TestCase):
    def test_identical_is_empty(self):
        self.assertEqual(M.name_diffs({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2}}), [])

    def test_changed_leaf_is_named(self):
        self.assertEqual(M.name_diffs({"a": {"b": 1}}, {"a": {"b": 2}}), ["a.b"])

    def test_missing_key_is_named(self):
        self.assertEqual(M.name_diffs({"a": 1}, {}), ["a (missing)"])

    def test_extra_key_is_named_as_removable(self):
        out = M.name_diffs({"a": 1}, {"a": 1, "b": 2})
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("b (extra"), out)

    def test_type_mismatch_is_named_at_the_parent(self):
        self.assertEqual(M.name_diffs({"a": {"b": 1}}, {"a": 1}), ["a"])


class TestPinnedVersion(unittest.TestCase):
    def test_shared_config_pins_a_version(self):
        v = M.pinned_version()
        self.assertIsNotNone(v, "opencode_version missing from opencode.shared.json")
        self.assertRegex(v, r"^\d+\.\d+")


class TestComputeMerged(unittest.TestCase):
    def test_owns_only_declared_keys(self):
        merged, owned = M.compute_merged(MACHINE)
        self.assertTrue(set(owned) <= M.OWNED_OPENCODE_KEYS, owned)
        self.assertIn("permission", owned)
        self.assertIn("$schema", merged)
        self.assertNotIn("provider", owned)

    def test_hand_edit_one_key_is_reported_by_name(self):
        """The exact failure the old --check missed."""
        _, owned = M.compute_merged(MACHINE)
        live = json.loads(json.dumps(owned))
        live["permission"]["bash"]["sudo *"] = "allow"
        diffs: list[str] = []
        for k in sorted(owned):
            diffs += M.name_diffs(owned[k], live.get(k), k)
        self.assertIn("permission.bash.sudo *", diffs)


class TestBashBoundaryDenies(unittest.TestCase):
    """The bash-scoped boundary denies (pr-check item 1) must be emitted, and the
    .env.example exception must sit AFTER the deny it carves out — last-match-wins
    means an exception placed before its deny is silently overwritten."""

    def test_sensitive_patterns_denied(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["permission"]["bash"]
        for pat in ("*.env*", "*.key*", "*.pem*", "*voice-samples*", "*/.ssh/*"):
            self.assertEqual(bash.get(pat), "deny", pat)

    def test_exception_ordered_after_its_deny(self):
        _, owned = M.compute_merged(MACHINE)
        keys = list(owned["permission"]["bash"])
        self.assertEqual(owned["permission"]["bash"]["*.env.example*"], "allow")
        self.assertLess(keys.index("*.env*"), keys.index("*.env.example*"))

    def test_denies_ordered_after_the_allows_they_overrule(self):
        _, owned = M.compute_merged(MACHINE)
        keys = list(owned["permission"]["bash"])
        for allow in ("rg *", "ls *"):
            self.assertLess(keys.index(allow), keys.index("*.env*"), allow)

    def test_data_root_deny_dropped_when_absent(self):
        _, owned = M.compute_merged(MACHINE)  # MACHINE has no data_root
        self.assertFalse(any("data_root" in k for k in owned["permission"]["bash"]))

    def test_data_root_deny_emitted_when_set(self):
        m = dict(MACHINE, data_root="/tmp/pii")
        _, owned = M.compute_merged(m)
        self.assertEqual(owned["permission"]["bash"]["*/tmp/pii*"], "deny")


class TestGitCSubcommands(unittest.TestCase):
    """`git -C *` was a blanket allow that defeated `git push`/`commit` asks and the
    reset/clean denies (pr-check item 2). It must be gone, replaced by read-only
    subcommands, with asks/denies ordered after them (last-match-wins)."""

    def test_blanket_allow_removed(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertNotIn("git -C *", owned["permission"]["bash"])

    def test_read_only_subcommands_allowed(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["permission"]["bash"]
        for pat in ("git -C * status *", "git -C * diff *", "git -C * log *"):
            self.assertEqual(bash.get(pat), "allow", pat)

    def test_write_asks_and_destructive_denies_present(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["permission"]["bash"]
        self.assertEqual(bash.get("git -C * push *"), "ask")
        self.assertEqual(bash.get("git -C * commit *"), "ask")
        self.assertEqual(bash.get("git -C * reset *"), "deny")
        self.assertEqual(bash.get("git -C * clean *"), "deny")

    def test_asks_and_denies_ordered_after_read_only_allows(self):
        _, owned = M.compute_merged(MACHINE)
        keys = list(owned["permission"]["bash"])
        self.assertLess(keys.index("git -C * status *"), keys.index("git -C * push *"))
        self.assertLess(keys.index("git -C * status *"), keys.index("git -C * reset *"))


class TestAgentProfilesPortable(unittest.TestCase):
    """Agent permission rules merge LAST and win, so a machine path or a trailing
    boundary deny in a profile breaks every other machine (pr-check item 4)."""

    def test_no_machine_paths_or_boundary_blocks(self):
        agents = sorted((SCRIPT.parent / "agents").glob("*.md"))
        self.assertTrue(agents, "no agent profiles found")
        for a in agents:
            body = a.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", body, f"{a.name} hardcodes a machine path")
            self.assertNotIn("external_directory", body, f"{a.name} re-declares the boundary")


class TestBuildFastLane(unittest.TestCase):
    """The build profile widens mechanical commands, but must never carry a
    catch-all allow: agent rules merge LAST, so a trailing '*' would override the
    global ssh/sudo denies and fail OPEN (trap #2/#7). `find` is not allowlisted —
    `find * -exec`/`-delete` is arbitrary mutation, not a read."""

    def test_build_mechanical_allows_present(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["agent"]["build"]["permission"]["bash"]
        for pat in ("mkdir *", "cp *", "mv *", "jq *", "node --check *"):
            self.assertEqual(bash.get(pat), "allow", pat)

    def test_no_catch_all_in_build(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertNotIn("*", owned["agent"]["build"]["permission"]["bash"])

    def test_sed_in_place_denied_after_the_allow(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["agent"]["build"]["permission"]["bash"]
        keys = list(bash)
        self.assertEqual(bash["sed -i *"], "deny")
        self.assertLess(keys.index("sed *"), keys.index("sed -i *"))

    def test_find_is_not_allowlisted(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["agent"]["build"]["permission"]["bash"]
        self.assertFalse(any(k.startswith("find ") for k in bash))


class TestRemovedOwnedKey(unittest.TestCase):
    """A key install.py owns but machine.json no longer specifies is normally REMOVED,
    not preserved (pr-check #6a). Exception: `enabled_providers` is preserved when
    absent, because deleting a provider allow-list widens access (fail open); and
    `enabled_providers: []` is an explicit deny-all, not "absent"."""

    def test_removed_owned_key_is_dropped_and_non_owned_kept(self):
        m = {k: v for k, v in MACHINE.items() if k != "default_model"}
        live = {"model": "old/model", "keep_me": {"a": 1}}
        merged, owned = M.compute_merged(m, live)
        self.assertNotIn("model", merged)
        self.assertEqual(merged["keep_me"], {"a": 1})

    def test_absent_provider_control_is_preserved_fail_closed(self):
        m = {k: v for k, v in MACHINE.items() if k != "enabled_providers"}
        live = {"enabled_providers": ["openrouter"]}
        merged, owned = M.compute_merged(m, live)
        self.assertEqual(merged.get("enabled_providers"), ["openrouter"],
                         "removing the provider allow-list on absence fails open")

    def test_empty_provider_control_is_emitted_as_deny_all(self):
        m = dict(MACHINE, enabled_providers=[])
        _, owned = M.compute_merged(m)
        self.assertEqual(owned["enabled_providers"], [])


class TestCheckSymlinksRoots(unittest.TestCase):
    """A live symlink pointing INTO our source tree but absent from it is stale (a
    removed/excluded skill, a hand-added link) and must be reported; one pointing
    elsewhere (e.g. ~/agent/skills) is not ours and must not be (pr-check #6b)."""

    def test_stale_reported_foreign_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            (src / "keep").mkdir(parents=True)
            (src / "keep" / "SKILL.md").write_text("x", encoding="utf-8")
            live = root / "live"
            live.mkdir()
            os.symlink(src / "keep", live / "keep")     # in sync
            os.symlink(src / "gone", live / "gone")     # stale: points into src
            foreign = root / "foreign"
            foreign.mkdir()
            os.symlink(foreign, live / "other")         # not ours
            n, problems = M.check_symlinks_roots([("skills", live, src)])
            self.assertEqual(n, 1, problems)
            self.assertTrue(any("gone" in p for p in problems), problems)
            self.assertFalse(any("other" in p for p in problems), problems)


class TestPhaseCheck(unittest.TestCase):
    """test_install never exercised phase_check, so a regression back to symlink-only
    checking would pass green (review should-fix). These call it against a temp HOME."""

    def _run(self, live_cfg, live_settings, machine=MACHINE):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / "opencode.json").write_text(json.dumps(live_cfg), encoding="utf-8")
            (home / "settings.json").write_text(json.dumps(live_settings), encoding="utf-8")
            saved = (M.OPENCODE_HOME, M.CLAUDE_HOME, M.probe_opencode_version, M.check_symlinks)
            M.OPENCODE_HOME = M.CLAUDE_HOME = home
            M.probe_opencode_version = lambda: M.pinned_version()
            M.check_symlinks = lambda: (0, [])
            try:
                return M.phase_check(machine)
            finally:
                (M.OPENCODE_HOME, M.CLAUDE_HOME,
                 M.probe_opencode_version, M.check_symlinks) = saved

    def test_clean_config_is_zero(self):
        _, owned = M.compute_merged(MACHINE)
        rc = self._run(owned, {"env": {"AGENT_TOOLING_ROOT": str(M.REPO_ROOT / "agent-tooling")}})
        self.assertEqual(rc, 0)

    def test_hand_edited_key_is_reported(self):
        _, owned = M.compute_merged(MACHINE)
        broken = json.loads(json.dumps(owned))
        broken["permission"]["bash"]["sudo *"] = "allow"
        rc = self._run(broken, {"env": {"AGENT_TOOLING_ROOT": str(M.REPO_ROOT / "agent-tooling")}})
        self.assertEqual(rc, 1)

    def test_extra_owned_key_absent_from_machine_is_reported(self):
        _, owned = M.compute_merged(MACHINE)
        live = json.loads(json.dumps(owned))
        live["enabled_providers"] = ["stale"]          # machine.json dropped it
        m = {k: v for k, v in MACHINE.items() if k != "enabled_providers"}
        rc = self._run(live, {"env": {"AGENT_TOOLING_ROOT": str(M.REPO_ROOT / "agent-tooling")}}, m)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
