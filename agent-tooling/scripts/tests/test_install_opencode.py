"""Tests for adapters/opencode/install.py — the OpenCode config generator.

The two tests that matter most are the trap tests: permission ordering fails
OPEN if the config is ever serialised with sorted keys, and a hand-written
provider block is the only copy of an API key and its ZDR settings. Both are
silent failures, so both are checked against the artifact rather than trusted.
"""
import importlib.util
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INSTALL = os.path.join(_ROOT, "adapters", "opencode", "install.py")

spec = importlib.util.spec_from_file_location("install_opencode", _INSTALL)
install = importlib.util.module_from_spec(spec)
sys.modules["install_opencode"] = install
spec.loader.exec_module(install)


FAKE_KEY = "not-a-real-key"  # pragma: allowlist secret

MACHINE = {
    "machine": "testbox",
    "python": "/usr/bin/python3",
    "repo_root": "/repos",
    "data_root": "/data",
    "default_model": "prov/big",
    "harness_models": {"code": "prov/big", "sources": "prov/small"},
    "disable_harnesses": [],
}

SHARED = {
    "opencode_version": "1.18.30",
    "config": {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "read": {
                "*": "allow",
                "*.env": "deny",
                "${data_root}/**": "deny",
            },
            "external_directory": {
                "*": "deny",
                "${repo_root}/**": "allow",
            },
        },
    },
}


def build(machine_over=None):
    m = dict(MACHINE, **(machine_over or {}))
    return install.build_config(json.loads(json.dumps(SHARED)), m)


# --- substitution and the data_root rule -------------------------------------

def test_placeholders_are_substituted():
    cfg = build()
    assert "/repos/**" in cfg["permission"]["external_directory"]
    assert "/data/**" in cfg["permission"]["read"]


def test_data_root_rules_are_dropped_when_null():
    """A machine that must never hold participant data gets no rule naming a
    directory it does not have."""
    cfg = build({"data_root": None})
    keys = cfg["permission"]["read"].keys()
    assert not any("data_root" in k or k.startswith("/data") for k in keys)
    assert "*.env" in keys           # unrelated rules survive


def test_harness_models_and_disable_are_emitted():
    cfg = build({"disable_harnesses": ["analysis", "writing"]})
    assert cfg["agent"]["code"]["model"] == "prov/big"
    assert cfg["agent"]["analysis"]["disable"] is True
    assert cfg["agent"]["writing"]["disable"] is True


# --- trap: permission ordering fails OPEN ------------------------------------

def test_generated_config_has_the_catch_all_first():
    assert install.assert_permission_order(build()) == []


def test_a_deny_before_the_catch_all_is_caught():
    problems = install.assert_permission_order(
        {"permission": {"read": {"/data/**": "deny", "*": "allow"}}})
    assert problems and "catch-all" in problems[0]


def test_sorting_the_SHARED_file_is_caught():
    """Where the sort hazard actually lives.

    In the shared file the key is still the literal `${data_root}/**`, and '$' is
    0x24 against '*' at 0x2A — so sorting moves the participant-data deny ahead of
    the catch-all, and last-rule-wins turns it into an allow. After substitution
    the key is `/data/**` ('/' is 0x2F) and sorts harmlessly after, which is why
    checking only the generated artifact would miss the bug at its source."""
    shared = json.loads(json.dumps(SHARED))
    read = shared["config"]["permission"]["read"]
    assert sorted(read)[0].startswith("${data_root}")      # the hazard is real
    shared["config"]["permission"]["read"] = dict(sorted(read.items()))
    problems = install.assert_permission_order(install.build_config(shared, MACHINE))
    assert problems and "catch-all" in problems[0]


def test_real_shared_config_passes_the_order_check():
    """The shipped opencode.shared.json must itself be correctly ordered."""
    shared = json.load(open(os.path.join(_ROOT, "adapters", "opencode",
                                         "opencode.shared.json")))
    cfg = install.build_config(shared, MACHINE)
    assert install.assert_permission_order(cfg) == []


# --- trap: clobbering a hand-written provider block --------------------------

def test_merge_preserves_unowned_keys():
    """An existing provider block holds the only copy of an API key and the
    per-model zdr / data_collection settings."""
    existing = {
        "$schema": "old",
        "provider": {"openrouter": {
            "options": {"apiKey": FAKE_KEY},
            "models": {"m": {"options": {"zdr": True}}}}},
    }
    merged = install.merge(existing, build())
    assert merged["provider"]["openrouter"]["options"]["apiKey"] == FAKE_KEY
    assert merged["provider"]["openrouter"]["models"]["m"]["options"]["zdr"] is True
    assert merged["$schema"] == "https://opencode.ai/config.json"   # owned, replaced


def test_merge_is_idempotent():
    gen = build()
    once = install.merge({"provider": {"x": 1}}, gen)
    twice = install.merge(once, gen)
    assert once == twice


# --- drift reporting ---------------------------------------------------------

def test_diff_names_the_drifting_keys():
    gen = build()
    stale = install.merge({}, gen)
    stale["permission"] = {"read": {"*": "deny"}}
    assert "permission" in install.diff_owned(stale, gen)


def test_no_drift_when_identical():
    gen = build()
    assert install.diff_owned(install.merge({}, gen), gen) == []
