#!/usr/bin/env python3
"""Tests for policies/webfetch_mandated.py — the webfetch registry guard.

The guard is the enforcement for the Mandated Services Registry (config cannot hold a
`webfetch` domain map in OpenCode 1.18.30). A guard that allows everything is worse
than none, so these tests pin both directions: a mandated host is allowed, and a host
that is not in the registry is denied — including the near-miss lookalikes a naive
`endswith` would let through.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

POLICY = Path(__file__).resolve().parent.parent / "webfetch_mandated.py"
REGISTRY = Path(__file__).resolve().parents[2] / "settings" / "mandated-services.json"


def load_module():
    spec = importlib.util.spec_from_file_location("webfetch_mandated", POLICY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = load_module()


REGISTRY_FIXTURE = {
    "services": [
        {"id": "openalex", "hosts": ["api.openalex.org"], "host_suffixes": []},
        {"id": "wikis", "hosts": ["wikimedia.org"], "host_suffixes": [".wikipedia.org", ".wikimedia.org"]},
    ]
}


class TestDecideAgainstFixture(unittest.TestCase):
    def assert_allowed(self, url):
        self.assertIsNone(P.decide(url, REGISTRY_FIXTURE), f"should allow: {url}")

    def assert_denied(self, url):
        reason = P.decide(url, REGISTRY_FIXTURE)
        self.assertIsNotNone(reason, f"should deny: {url}")
        self.assertIn("Mandated Services Registry", reason)

    def test_exact_host_allowed(self):
        self.assert_allowed("https://api.openalex.org/works")

    def test_case_and_trailing_dot_ignored(self):
        self.assert_allowed("https://API.OPENALEX.ORG./works")

    def test_suffix_matches_subdomain_and_apex(self):
        self.assert_allowed("https://en.wikipedia.org/w/api.php")
        self.assert_allowed("https://de.wikipedia.org/")
        self.assert_allowed("https://wikipedia.org/")
        self.assert_allowed("https://meta.wikimedia.org/")

    def test_lookalikes_denied(self):
        # The failure class a naive `endswith("wikipedia.org")` would miss.
        self.assert_denied("https://notwikipedia.org/")
        self.assert_denied("https://evil-wikipedia.org/")
        self.assert_denied("https://en.wikipedia.org.evil.com/")
        self.assert_denied("https://api.openalex.org.evil.com/")

    def test_unlisted_and_local_denied(self):
        self.assert_denied("https://example.com/")
        self.assert_denied("http://localhost/")
        self.assert_denied("http://127.0.0.1/")
        self.assert_denied("http://[::1]/")
        self.assert_denied("http://10.0.0.5/")

    def test_non_http_scheme_denied(self):
        self.assert_denied("file:///etc/passwd")
        self.assert_denied("ftp://example.com/x")
        self.assert_denied("")
        self.assert_denied("not a url")

    def test_backslash_parser_differential_denied(self):
        """urllib sees the host after `\\`; a WHATWG fetcher sees the host before it.
        The guard must reject the ambiguity rather than allow the wrong host."""
        self.assert_denied(r"https://evil.com\@api.openalex.org/")
        self.assert_denied("https://evil.com%5c@api.openalex.org/")
        self.assert_denied(r"https://api.openalex.org\@evil.com/")

    def test_reason_asks_for_a_written_exception(self):
        reason = P.decide("https://example.com/", REGISTRY_FIXTURE)
        for phrase in ("what you tried first", "blast radius", "do not retry"):
            self.assertIn(phrase, reason)


class TestDecideAgainstRealRegistry(unittest.TestCase):
    """The real guard must catch a non-listed host — the whole point of the guard."""

    @classmethod
    def setUpClass(cls):
        cls.registry = P.load_registry(REGISTRY)
        assert cls.registry, f"could not load {REGISTRY}"

    def test_mandated_hosts_allowed(self):
        for url in [
            "https://api.openalex.org/works",
            "https://query.wikidata.org/sparql",
            "https://en.wikipedia.org/w/api.php",
            "https://api.wikimedia.org/service/lw/inference/v1/models",
            "https://web.archive.org/web/20240101000000id_/https://example.org/",
            "https://phabricator.wikimedia.org/T12345",
        ]:
            self.assertIsNone(P.decide(url, self.registry), f"should allow: {url}")

    def test_non_listed_host_denied(self):
        for url in [
            "https://example.com/",
            "https://en.wikipedia.org.evil.com/",
            "https://notwikipedia.org/",
        ]:
            self.assertIsNotNone(P.decide(url, self.registry), f"should deny: {url}")


if __name__ == "__main__":
    unittest.main()
