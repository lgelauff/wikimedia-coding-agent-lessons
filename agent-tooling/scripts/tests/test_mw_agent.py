"""Tests for mw_agent.py's guard: read-only commands pass, writes/auth/unbounded streams refuse.

Only check() is exercised: no network, no mw binary needed. Each refusal case is a real
failure class (a write verb, a body or header, a non-Wikimedia host, an unbounded stream).

Run: python3 -m unittest agent-tooling.scripts.tests.test_mw_agent
"""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "mw_agent.py"
spec = importlib.util.spec_from_file_location("mw_agent", SCRIPT)
mw_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw_agent)


def refused(cmd):
    try:
        mw_agent.check(cmd.split())
    except SystemExit as e:
        return e.code == 2
    return False


ALLOWED = [
    "codesearch search --output json onPageSaveComplete",
    "gerrit api changes/?q=bug:T1&n=5",
    "analytics pageviews Earth --project en.wikipedia.org",
    "wiki page get Earth --wiki en.wikipedia.org",
    "wiki page info Earth --wiki en.wikipedia.org",
    "wiki page history Earth --wiki en.wikipedia.org",
    "wiki api query -f titles=Earth -f prop=info --wiki en.wikipedia.org",
    "wiki rest get /v1/page/Earth/bare --wiki en.wikipedia.org",
    "api metrics/pageviews/top/nl.wikipedia.org/all-access/2025/01/01",
    "api https://en.wikipedia.org/w/rest.php/v1/search/page -X GET -f q=Earth",
    "events list --output json",
    "events info mediawiki.page-create",
]

REFUSED = [
    # writes
    "wiki page put Sandbox",
    "wiki page delete Sandbox",
    "wiki page move A B",
    "wiki api edit --method POST --token csrf -f title=X",
    "wiki api query -X POST",
    "wiki rest post /v1/page",
    "api metrics/x -f a=b",                      # fields select POST by default
    "api metrics/x -X POST",
    "api metrics/x --input body.json",
    "gerrit review 123",
    "gerrit changes wip 123",
    "gerrit changes reviewers add 123",
    "gerrit changes abandon 123",
    "phabricator task status T1 r",
    # auth, saved logins, credentials
    "wiki auth login",
    "wiki api query -f titles=X --profile me",
    "wiki api query -f titles=X --username Me",
    "api metrics/x -H Authorization:Bearer",
    "enterprise articles Earth",
    "phabricator task create",
    # other hosts, unbounded streams, unknown wiki doors
    "api https://example.org/x",
    "api https://en.wikipedia.org.example.com/x",
    "events tail recentchange",
    "wiki bulk",
    "wiki file upload x.png",
    "toolforge shell",
]


class TestGuard(unittest.TestCase):
    def test_allowed(self):
        for cmd in ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertFalse(refused(cmd), f"should pass: {cmd}")

    def test_refused(self):
        for cmd in REFUSED:
            with self.subTest(cmd=cmd):
                self.assertTrue(refused(cmd), f"should refuse: {cmd}")


if __name__ == "__main__":
    unittest.main()
