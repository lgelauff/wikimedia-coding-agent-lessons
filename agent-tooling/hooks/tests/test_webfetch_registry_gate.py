"""The Claude WebFetch gate blocks unapproved hosts and paths, allows approved ones, and
fails closed on an unreadable event: shown against the real registry."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "webfetch_registry_gate.py"


def run(event) -> subprocess.CompletedProcess:
    data = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True)


def fetch(url: str) -> subprocess.CompletedProcess:
    return run({"tool_name": "WebFetch", "tool_input": {"url": url, "prompt": "x"}})


class WebFetchRegistryGate(unittest.TestCase):
    def test_approved_host_allowed(self):
        self.assertEqual(fetch("https://api.openalex.org/works?search=polis").returncode, 0)

    def test_unapproved_host_blocked(self):
        r = fetch("https://example.com/")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in the Mandated Services Registry", r.stderr)

    def test_disallowed_path_on_approved_host_blocked(self):
        self.assertEqual(fetch("https://scholar.google.com/citations?user=abc").returncode, 0)
        r = fetch("https://scholar.google.com/scholar?q=polis")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not this path", r.stderr)

    def test_lookalike_host_blocked(self):
        self.assertEqual(fetch("https://api.openalex.org.evil.com/").returncode, 2)

    def test_unparseable_event_fails_closed(self):
        self.assertEqual(run("not json").returncode, 2)

    def test_other_tools_ignored(self):
        self.assertEqual(run({"tool_name": "Bash", "tool_input": {"command": "ls"}}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
