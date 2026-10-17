#!/usr/bin/env python3
"""Tests for scripts/mandated_services.py — registry validation + connector drift.

The registry and the `source-connectors` connector library must not diverge: a
connector added to the skill but not the registry means the agent is denied a source
it was told to use; the reverse means a stale allow. These tests pin that the drift
check *catches* both, and that the validator rejects the malformed entries that would
otherwise produce a rule matching nothing while reading as protection.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "mandated_services.py"
REPO_ROOT = SCRIPT.parents[2]


def load_module():
    spec = importlib.util.spec_from_file_location("mandated_services", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_module()

SKILL_TABLE = """\
## 4. The library

| Connector | Protocol · endpoint | Auth |
|---|---|---|
| **A** | REST · `api.openalex.org` | none |
| **B** | REST · `api.crossref.org` | none |

## Kept out of the library
"""


def write_skill(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def connector_service(sid: str, host: str) -> dict:
    return {
        "id": sid, "service": sid, "kind": "connector",
        "hosts": [host], "sources": [M.CONNECTOR_LIBRARY], "verified": "2026-09",
    }


class TestParser(unittest.TestCase):
    def test_parses_endpoint_column_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            write_skill(p, SKILL_TABLE)
            self.assertEqual(M.parse_connector_hosts(p),
                             {"api.openalex.org", "api.crossref.org"})

    def test_recipe_column_not_over_collected(self):
        """`zoek.officielebekendmakingen.nl` sits in KOOP's recipe column, not its endpoint."""
        hosts = M.parse_connector_hosts(REPO_ROOT / "agent-tooling/skills/source-connectors/references/library.md")
        self.assertIn("repository.overheid.nl", hosts)
        self.assertNotIn("zoek.officielebekendmakingen.nl", hosts)

    def test_name_column_fallback(self):
        body = ("## 4. The library\n\n| Connector | Protocol · endpoint |\n|---|---|\n"
                "| **open.overheid.nl / OPP** | *aanlever only* |\n\n## Kept out of the library\n")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            write_skill(p, body)
            self.assertEqual(M.parse_connector_hosts(p), {"open.overheid.nl"})


class TestDrift(unittest.TestCase):
    def test_real_registry_is_in_sync(self):
        registry = M.load(M.DEFAULT_REGISTRY)
        self.assertEqual(M.drift(registry, M.DEFAULT_SKILL), [])

    def test_catches_host_added_to_skill(self):
        """The failure class: a new connector row, registry not updated."""
        body = SKILL_TABLE.replace("## Kept out", "| **C** | REST · `api.example.org` | none |\n\n## Kept out")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            write_skill(p, body)
            registry = {"services": [
                connector_service("a", "api.openalex.org"),
                connector_service("b", "api.crossref.org"),
            ]}
            problems = M.drift(registry, p)
            self.assertTrue(any("api.example.org" in x and "not in the registry" in x
                                for x in problems), problems)

    def test_catches_host_removed_from_skill(self):
        """The reverse: a connector removed from the skill, registry left stale."""
        body = SKILL_TABLE.replace("| **B** | REST · `api.crossref.org` | none |\n", "")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            write_skill(p, body)
            registry = {"services": [
                connector_service("a", "api.openalex.org"),
                connector_service("b", "api.crossref.org"),
            ]}
            problems = M.drift(registry, p)
            self.assertTrue(any("api.crossref.org" in x and "not in the library" in x
                                for x in problems), problems)


class TestValidate(unittest.TestCase):
    def _repo(self, td: str) -> Path:
        root = Path(td)
        (root / M.CONNECTOR_LIBRARY).parent.mkdir(parents=True)
        (root / M.CONNECTOR_LIBRARY).write_text("x", encoding="utf-8")
        return root

    def test_clean_fixture_validates(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            registry = {"services": [
                connector_service("a", "api.openalex.org"),
                connector_service("b", "api.crossref.org"),
            ]}
            self.assertEqual(M.validate(registry, root), [])

    def test_duplicate_host_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            registry = {"services": [
                connector_service("a", "api.openalex.org"),
                connector_service("b", "api.openalex.org"),
            ]}
            self.assertTrue(any("already claimed" in x for x in M.validate(registry, root)))

    def test_missing_source_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            svc = connector_service("a", "api.openalex.org")
            svc["sources"] = ["agent-tooling/skills/nope/SKILL.md"]
            registry = {"services": [svc]}
            self.assertTrue(any("does not exist" in x for x in M.validate(registry, root)))

    def test_paths_validated(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            good = connector_service("a", "api.openalex.org")
            good["paths"] = {"allow": ["/works*"], "deny": ["*secret*"]}
            self.assertEqual(M.validate({"services": [good]}, root), [])
            for bad, needle in (({"allow": ["works"]}, "must start with"),
                                ({"allow": "/works"}, "list of strings"),
                                ({"permit": ["/x"]}, "only `allow`/`deny`"),
                                ({}, "is empty")):
                svc = connector_service("a", "api.openalex.org")
                svc["paths"] = bad
                self.assertTrue(any(needle in x for x in M.validate({"services": [svc]}, root)),
                                f"{bad} should be flagged with {needle!r}")

    def test_suffix_overlap_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            a = connector_service("a", "en.wikipedia.org")
            b = connector_service("b", "wikimedia.org")
            b["host_suffixes"] = [".wikipedia.org"]
            registry = {"services": [a, b]}
            self.assertTrue(any("also covered by suffix" in x
                                for x in M.validate(registry, root)))

    def test_bad_verified_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            svc = connector_service("a", "api.openalex.org")
            svc["verified"] = "yesterday"
            registry = {"services": [svc]}
            self.assertTrue(any("verified" in x for x in M.validate(registry, root)))

    def test_calendar_invalid_verified_flagged(self):
        """`2026-13` and `2026-02-30` match the shape but are not dates (review
        should-fix). A verification stamp that is not a day must not read as verified."""
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            for bad in ("2026-13", "2026-00", "2026-02-30", "2026-04-31"):
                svc = connector_service("a", "api.openalex.org")
                svc["verified"] = bad
                self.assertTrue(any("real" in x and "verified" in x
                                    for x in M.validate({"services": [svc]}, root)),
                                f"{bad} should be rejected")

    def test_calendar_valid_verified_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            for good in ("2026-02", "2026-02-28", "2024-02-29"):
                svc = connector_service("a", "api.openalex.org")
                svc["verified"] = good
                self.assertEqual(M.validate({"services": [svc]}, root), [],
                                 f"{good} should be accepted")

    def test_suffix_vs_suffix_overlap_flagged(self):
        """`.api.example.org` and `.example.org` both match the same request under
        different owners — ownership is undefined (review should-fix)."""
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            a = connector_service("a", "alpha.net")
            a["host_suffixes"] = [".api.example.org"]
            b = connector_service("b", "beta.net")
            b["host_suffixes"] = [".example.org"]
            problems = M.validate({"services": [a, b]}, root)
            self.assertTrue(any("suffix `.api.example.org`" in x and "covered by suffix" in x
                                for x in problems), problems)

    def test_nested_suffixes_on_one_service_allowed(self):
        """One service may own both `.example.org` and `.api.example.org` — no ambiguity."""
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            a = connector_service("a", "alpha.net")
            a["host_suffixes"] = [".example.org", ".api.example.org"]
            self.assertEqual(M.validate({"services": [a]}, root), [])

    def test_real_registry_validates(self):
        registry = M.load(M.DEFAULT_REGISTRY)
        self.assertEqual(M.validate(registry, REPO_ROOT), [])

    def test_non_list_sources_is_a_problem_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            svc = connector_service("a", "api.openalex.org")
            svc["sources"] = None
            self.assertTrue(any("`sources` must be a list" in x
                                for x in M.validate({"services": [svc]}, root)))

    def test_empty_sources_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            svc = connector_service("a", "api.openalex.org")
            svc["sources"] = []
            self.assertTrue(any("at least one file" in x
                                for x in M.validate({"services": [svc]}, root)))


if __name__ == "__main__":
    unittest.main()
