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


if __name__ == "__main__":
    unittest.main()
