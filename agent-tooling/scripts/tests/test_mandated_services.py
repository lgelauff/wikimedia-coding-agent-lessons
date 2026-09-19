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
        hosts = M.parse_connector_hosts(REPO_ROOT / "agent-tooling/skills/source-connectors/SKILL.md")
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
        (root / "agent-tooling/skills/source-connectors").mkdir(parents=True)
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
