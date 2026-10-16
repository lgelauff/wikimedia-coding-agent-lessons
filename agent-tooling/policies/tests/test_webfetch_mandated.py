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

    def test_scholar_paths_real_registry(self):
        allow = ["https://scholar.google.com/citations?user=abcDEF123&hl=en",
                 "https://scholar.google.com/citations?view_op=top_venues&hl=en"]
        deny = ["https://scholar.google.com/scholar?q=polis",
                "https://scholar.google.com/scholar?cites=123",
                "https://scholar.google.com/citations?user=abc&cstart=20",
                "https://scholar.google.com/citations/../scholar?q=x"]
        for url in allow:
            self.assertIsNone(P.decide(url, self.registry), f"should allow: {url}")
        for url in deny:
            self.assertIsNotNone(P.decide(url, self.registry), f"should deny: {url}")

    def test_eurostat_api_paths_only(self):
        ok = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/isoc_ci_ifp_iu?geo=NL"
        self.assertIsNone(P.decide(ok, self.registry))
        for url in ["https://ec.europa.eu/eurostat/SDMX/diss-web/rest/data/x",
                    "https://ec.europa.eu/commission/presscorner/home/en",
                    "https://ec.europa.eu/eurostat/api/dissemination/../../web/main/home"]:
            self.assertIsNotNone(P.decide(url, self.registry), f"should deny: {url}")


PATH_FIXTURE = {
    "services": [
        {"id": "scholar", "hosts": ["scholar.google.com"],
         "paths": {"allow": ["/citations?user=*", "/citations?view_op=top_venues*"],
                   "deny": ["*cstart=*"]}},
        {"id": "epmc", "hosts": ["www.ebi.ac.uk"], "paths": {"allow": ["/europepmc/*"]}},
        {"id": "open", "hosts": ["api.openalex.org"]},
    ]
}


class TestPathRules(unittest.TestCase):
    def assert_allowed(self, url):
        self.assertIsNone(P.decide(url, PATH_FIXTURE), f"should allow: {url}")

    def assert_denied(self, url):
        reason = P.decide(url, PATH_FIXTURE)
        self.assertIsNotNone(reason, f"should deny: {url}")
        return reason

    def test_allow_list_paths(self):
        self.assert_allowed("https://scholar.google.com/citations?user=XyZ")
        self.assert_allowed("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=x")

    def test_path_outside_allow_list_denied_with_path_message(self):
        self.assertIn("not this path", self.assert_denied("https://scholar.google.com/scholar?q=x"))
        self.assert_denied("https://www.ebi.ac.uk/ena/browser/")

    def test_deny_beats_allow(self):
        self.assert_denied("https://scholar.google.com/citations?user=XyZ&cstart=20")

    def test_question_mark_is_literal(self):
        # `?` in a pattern must not act as a one-character wildcard
        self.assert_denied("https://scholar.google.com/citationsXuser=XyZ")

    def test_dot_segments_and_encoding_cannot_escape(self):
        self.assert_denied("https://www.ebi.ac.uk/europepmc/../ena/browser/")
        self.assert_denied("https://www.ebi.ac.uk/europepmc/%2e%2e/ena/")

    def test_no_paths_means_any_path(self):
        self.assert_allowed("https://api.openalex.org/anything/at/all")


if __name__ == "__main__":
    unittest.main()
