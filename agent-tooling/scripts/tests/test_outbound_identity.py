"""outbound_identity: private values come only from env/secrets; unset ones drop out cleanly."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import outbound_identity as oi  # noqa: E402

REPO_FILE = oi.DEFAULT_FILE


class OutboundIdentity(unittest.TestCase):
    def setUp(self):
        self.cfg = oi.load(REPO_FILE)
        patcher = mock.patch.dict(os.environ, {"AGENT_SECRETS_FILE": "/nonexistent"}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CONTACT_MAILTO", None)

    def test_repo_file_holds_no_email_address(self):
        self.assertNotRegex(REPO_FILE.read_text(), r"[\w.+-]+@[\w-]+\.[\w.]+")

    def test_unset_contact_is_anonymous(self):
        ua = oi.user_agent("crossref", self.cfg)
        self.assertNotIn("mailto", ua)
        self.assertIn("https://github.com/lgelauff/wikimedia-analysis", ua)
        self.assertEqual(oi.params("crossref", self.cfg), {})

    def test_set_contact_is_sent_where_approved(self):
        os.environ["CONTACT_MAILTO"] = "test@example.org"
        self.assertIn("mailto:test@example.org", oi.user_agent("openalex", self.cfg))
        self.assertEqual(oi.params("crossref", self.cfg), {"mailto": "test@example.org"})
        # not sent to services without an approved field
        self.assertNotIn("test@example.org", oi.user_agent("liftwing", self.cfg))
        self.assertNotIn("test@example.org", json.dumps(oi.params("ncbi-eutils", self.cfg)))

    def test_unknown_service_gets_default(self):
        self.assertEqual(oi.user_agent("no-such-service", self.cfg),
                         "WikimediaAnalysis/1.0 (personal research project; "
                         "https://github.com/lgelauff/wikimedia-analysis)")

    def test_unknown_identity_is_an_error(self):
        with self.assertRaises(KeyError):
            oi.render("{nobody}", self.cfg)


if __name__ == "__main__":
    unittest.main()
