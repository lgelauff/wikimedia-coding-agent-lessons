"""Tests for handoff.py: prepare on a "server" clone, fetch into a "Mac" clone, push to a bare origin.

Every check that stops a hand-off is exercised with the failure it exists for.
Run: python3 -m unittest agent-tooling.scripts.tests.test_handoff
"""
import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("handoff", HERE.parent / "handoff.py")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


def g(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(path, name, text, msg):
    (Path(path) / name).write_text(text)
    g(path, "add", name)
    g(path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg)


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        t = self.tmp
        self.origin = t / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        seed = t / "seed"
        subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
        commit(seed, "a.txt", "a\n", "base")
        g(seed, "push", "-q", str(self.origin), "main")
        self.server = t / "server"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.server)], check=True)
        g(self.server, "checkout", "-q", "-b", "fix/thing-1")
        commit(self.server, "b.txt", "b\n", "fix: the thing")
        commit(self.server, "c.txt", "c\n", "test: the thing")
        self.mac = t / "mac"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.mac)], check=True)
        self.registry = t / "registry.json"
        self.registry.write_text(json.dumps({"o/proj": {
            "mac_path": str(self.mac), "origin": str(self.origin), "server": str(self.server)}}))
        self.out = t / "handoffs"
        self.said = []

    def prepare(self, **kw):
        a = argparse.Namespace(repo="o/proj", path=str(self.server), branch="fix/thing-1", base="main",
                               test_cmd="pytest", test_result="3 passed", pr_title="Fix the thing",
                               pr_body_file=None, pr_base="main", out=str(self.out))
        for k, v in kw.items():
            setattr(a, k, v)
        self.assertEqual(handoff.prepare(a), 0)
        return self.out / "o__proj__fix__thing-1.json"

    def fetch(self, manifest, answer="y", no_push=False, registry=None):
        a = argparse.Namespace(manifest=str(manifest), registry=str(registry or self.registry), no_push=no_push)
        return handoff.fetch(a, ask=lambda _q: answer, out=self.said.append)

    def remote_has(self, branch):
        r = subprocess.run(["git", "-C", str(self.origin), "rev-parse", "-q", "--verify", f"refs/heads/{branch}"],
                           capture_output=True, text=True)
        return r.returncode == 0

    # --- the happy path
    def test_prepare_writes_commits_in_order(self):
        m = json.loads(self.prepare().read_text())
        self.assertEqual([c["subject"] for c in m["commits"]], ["fix: the thing", "test: the thing"])
        self.assertEqual(m["head_sha"], g(self.server, "rev-parse", "fix/thing-1"))

    def test_fetch_checks_then_pushes_on_yes(self):
        self.assertEqual(self.fetch(self.prepare(), "y"), 0)
        self.assertTrue(self.remote_has("fix/thing-1"))
        self.assertTrue(any("compare/main...fix/thing-1" in s for s in self.said))

    def test_no_means_no_push(self):
        self.assertEqual(self.fetch(self.prepare(), "n"), 0)
        self.assertFalse(self.remote_has("fix/thing-1"))

    # --- every stop
    def test_wrong_clone_stops(self):
        reg = self.tmp / "reg2.json"
        reg.write_text(json.dumps({"o/proj": {"mac_path": str(self.mac), "origin": "https://github.com/o/other.git",
                                              "server": str(self.server)}}))
        with self.assertRaisesRegex(handoff.Stop, "wrong clone"):
            self.fetch(self.prepare(), registry=reg)
        self.assertFalse(self.remote_has("fix/thing-1"))

    def test_unrelated_server_history_stops_and_cleans_up(self):
        other = self.tmp / "other"
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
        commit(other, "x.txt", "x\n", "unrelated")
        g(other, "checkout", "-q", "-b", "fix/thing-1")
        commit(other, "y.txt", "y\n", "unrelated fix")
        m = self.prepare()
        reg = self.tmp / "reg3.json"
        reg.write_text(json.dumps({"o/proj": {"mac_path": str(self.mac), "origin": str(self.origin), "server": str(other)}}))
        with self.assertRaises(handoff.Stop):
            self.fetch(m, registry=reg)
        self.assertFalse(self.remote_has("fix/thing-1"))

    def test_tampered_commit_list_stops(self):
        f = self.prepare()
        m = json.loads(f.read_text())
        m["commits"][0]["subject"] = "something else"
        f.write_text(json.dumps(m))
        with self.assertRaisesRegex(handoff.Stop, "differ from the manifest"):
            self.fetch(f)
        self.assertFalse(self.remote_has("fix/thing-1"))

    def test_server_moved_after_prepare_stops(self):
        f = self.prepare()
        commit(self.server, "d.txt", "d\n", "late commit")
        with self.assertRaisesRegex(handoff.Stop, "server moved"):
            self.fetch(f)

    def test_existing_local_branch_is_never_overwritten(self):
        g(self.mac, "branch", "fix/thing-1", "main")
        with self.assertRaisesRegex(handoff.Stop, "already has a branch"):
            self.fetch(self.prepare())
        self.assertEqual(g(self.mac, "rev-parse", "fix/thing-1"), g(self.mac, "rev-parse", "main"))

    def test_unregistered_repo_stops(self):
        f = self.prepare(repo="o/unknown")
        with self.assertRaisesRegex(handoff.Stop, "not in the registry"):
            self.fetch(self.out / "o__unknown__fix__thing-1.json")

    def test_malformed_manifest_fields_stop(self):
        f = self.prepare()
        for k, v in (("branch", "../../x"), ("repo", "no-slash"), ("head_sha", "abc"), ("pr_base", "a..b")):
            m = json.loads(f.read_text())
            m[k] = v
            bad = self.tmp / f"bad-{k}.json"
            bad.write_text(json.dumps(m))
            with self.assertRaises(handoff.Stop, msg=k):
                self.fetch(bad)

    def test_manifest_cannot_choose_paths(self):
        m = json.loads(self.prepare().read_text())
        m["mac_path"] = "/tmp/elsewhere"; m["server"] = "/tmp/elsewhere"; m["origin"] = "x"
        f = self.tmp / "extra.json"
        f.write_text(json.dumps(m))
        self.assertEqual(self.fetch(f, "y"), 0)          # registry decides; extra keys are ignored
        self.assertTrue(self.remote_has("fix/thing-1"))

    def test_ssh_spec_alias_must_be_registered(self):
        with self.assertRaisesRegex(handoff.Stop, "not a server alias"):
            self.fetch("evilhost:/tmp/m.json")

    def test_agent_session_refused_without_no_push(self):
        from unittest import mock
        m = str(self.prepare())
        os.environ["CLAUDECODE"] = "1"
        try:   # a terminal and a "y" answer: only the agent check may stop it
            with mock.patch.object(handoff.sys.stdin, "isatty", return_value=True), \
                 mock.patch("builtins.input", return_value="y"):
                self.assertEqual(handoff.main(["fetch", m, "--registry", str(self.registry)]), 1)
        finally:
            os.environ.pop("CLAUDECODE", None)
        self.assertFalse(self.remote_has("fix/thing-1"))

    def test_no_push_mode_checks_without_pushing(self):
        self.assertEqual(self.fetch(self.prepare(), no_push=True), 0)
        self.assertFalse(self.remote_has("fix/thing-1"))

    def test_link_issue_is_encoded(self):
        body = self.tmp / "b.md"; body.write_text("line 1\n& more #2")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            handoff.main(["link", "issue", "--repo", "o/proj", "--title", "A & B", "--body-file", str(body)])
        url = buf.getvalue().strip()
        self.assertTrue(url.startswith("https://github.com/o/proj/issues/new?"))
        self.assertIn("title=A+%26+B", url)
        self.assertIn("%23", url)


if __name__ == "__main__":
    unittest.main()
