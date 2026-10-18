#!/usr/bin/env python3
"""Tests for scripts/check_public_text.py.

Every rule gets a case that must FIRE and, where the rule has an allowlist, a case
that must not. The forbidden strings are assembled at run time ("/Us" + "ers/…"),
so this file does not itself trip the guard when the repo is audited with --all.
Diff-mode cases run against throwaway git repos.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check_public_text.py"

HOME = "/Us" + "ers/realperson/notes/x.md"
SRVHOME = "/ho" + "me/agent/GitHub/repo"
HUB = "~" + "/agent/notes/STATE.md"
MAIL = "jane.doe" + "@" + "university.edu"
LOGID = "see " + "E" + "475 for details"
SESSION = "local_" + "6752e8b0-152f-4b91-b30d-4c06b448e73f"
IP = "10." + "4.2.17"
TOKEN = "gh" + "p_" + "A" * 36
HOST = "zorbhost"


def run(*args: str, stdin: str = "", env_extra: dict | None = None, cwd: str | None = None):
    env = dict(os.environ)
    env.pop("PUBLIC_TEXT_DENYLIST", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                          capture_output=True, text=True, env=env, cwd=cwd)


class FileMode(unittest.TestCase):
    def scan(self, text: str, denylist: str | None = None):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "doc.md"
            f.write_text(text, encoding="utf-8")
            args = [str(f), "--root", td]
            if denylist is not None:
                d = Path(td) / "deny.txt"
                d.write_text(denylist, encoding="utf-8")
                args += ["--denylist", str(d)]
            return run(*args)

    def assertFires(self, text: str, rule: str, **kw):
        r = self.scan(text, **kw)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(f"[{rule}]", r.stdout)
        return r

    def assertClean(self, text: str, **kw):
        r = self.scan(text, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_home_path_fires(self):
        self.assertFires(f"Copied to `{HOME}`.\n", "home-path")
        self.assertFires(f"repo at {SRVHOME}\n", "home-path")

    def test_home_path_placeholders_and_urls_pass(self):
        self.assertClean("/Us" + "ers/someone/notes.md and /ho" + "me/<you>/x\n")
        self.assertClean("https://ec.europa.eu/commission/presscorner/ho" + "me/en\n")

    def test_agent_hub_fires(self):
        self.assertFires(f"Read {HUB} first.\n", "agent-hub")

    def test_email_fires_and_allowlist_passes(self):
        self.assertFires(f"Mail {MAIL}.\n", "email")
        self.assertClean("UA (you" + "@example.org); Co-Authored-By: x <noreply" + "@anthropic.com>\n")

    def test_log_id_fires_but_noqa_codes_pass(self):
        self.assertFires(LOGID + "\n", "log-id")
        self.assertClean("import x  # noqa: " + "E" + "402\n")

    def test_session_id_fires(self):
        self.assertFires(f"ask {SESSION}\n", "session-id")

    def test_ipv4_fires_and_safe_addresses_pass(self):
        self.assertFires(f"ssh to {IP}\n", "ipv4")
        self.assertClean("bind 127.0.0.1 or 192.0.2.10; version 1.2.300.4\n")

    def test_token_fires_and_is_masked(self):
        r = self.assertFires(f"token = {TOKEN}\n", "token")
        self.assertNotIn(TOKEN, r.stdout)
        self.assertIn("(masked)", r.stdout)

    def test_denylist_whole_word_case_insensitive(self):
        self.assertFires(f"copy it to {HOST.upper()}:/srv\n", "denylist", denylist=f"# hosts\n{HOST}\n")
        self.assertClean(f"{HOST}s and pre{HOST} are other words\n", denylist=f"{HOST}\n")

    def test_denylist_regex_entry(self):
        self.assertFires("on box-07 tonight\n", "denylist", denylist="re:box-\\d+\n")

    def test_missing_denylist_warns_loudly(self):
        r = self.scan("nothing here\n", denylist=None)
        self.assertEqual(r.returncode, 0)
        self.assertIn("NOT checked", r.stderr)

    def test_skip_mark_suppresses_one_line(self):
        self.assertClean(f"fixture {MAIL}  <!-- public-text: ok -->\n")
        self.assertFires(f"fixture {MAIL}  <!-- public-text: ok -->\nand {MAIL}\n", "email")

    def test_unreadable_file_is_exit_2(self):
        r = run("/nonexistent/definitely/missing.md")
        self.assertEqual(r.returncode, 2, r.stderr)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class DiffMode(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo = Path(self.td.name)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t" + "@example.org")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "old.md").write_text(f"legacy text with {MAIL}\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        self.td.cleanup()

    def commit(self, path: str, text: str, msg: str = "change") -> str:
        p = self.repo / path
        p.write_text(text, encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", msg)
        return git(self.repo, "rev-parse", "HEAD")

    def test_only_added_lines_are_checked(self):
        """The pre-existing address in old.md must not block an unrelated push."""
        head = self.commit("new.md", "clean line\n")
        r = run("--range", f"{self.base}..{head}", "--root", str(self.repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_added_line_fires_with_location(self):
        head = self.commit("new.md", f"line one\nsee {HUB}\n")
        r = run("--range", f"{self.base}..{head}", "--root", str(self.repo))
        self.assertEqual(r.returncode, 1)
        self.assertIn("new.md:2: [agent-hub]", r.stdout)

    def test_commit_message_is_checked(self):
        head = self.commit("new.md", "clean\n", msg=f"fix it, per {LOGID}")
        r = run("--range", f"{self.base}..{head}", "--root", str(self.repo))
        self.assertEqual(r.returncode, 1)
        self.assertIn("message", r.stdout)
        self.assertIn("[log-id]", r.stdout)

    def test_pre_push_existing_ref(self):
        head = self.commit("new.md", f"{IP}\n")
        stdin = f"refs/heads/main {head} refs/heads/main {self.base}\n"
        r = run("--pre-push", "--root", str(self.repo), stdin=stdin)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("[ipv4]", r.stdout)

    def test_pre_push_new_ref_uses_merge_base(self):
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.base)
        head = self.commit("new.md", f"{SESSION}\n")
        stdin = f"refs/heads/feat {head} refs/heads/feat {'0' * 40}\n"
        r = run("--pre-push", "--root", str(self.repo), stdin=stdin)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("[session-id]", r.stdout)
        self.assertNotIn("old.md", r.stdout)

    def test_pre_push_new_ref_without_base_is_exit_2(self):
        head = self.commit("new.md", "clean\n")
        stdin = f"refs/heads/feat {head} refs/heads/feat {'0' * 40}\n"
        r = run("--pre-push", "--root", str(self.repo), stdin=stdin)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_pre_push_delete_publishes_nothing(self):
        stdin = f"(delete) {'0' * 40} refs/heads/old {self.base}\n"
        r = run("--pre-push", "--root", str(self.repo), stdin=stdin)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_bad_range_is_exit_2(self):
        r = run("--range", "nosuch..alsonot", "--root", str(self.repo))
        self.assertEqual(r.returncode, 2)

    def test_default_denylist_lives_in_git_info(self):
        info = self.repo / ".git" / "info"
        info.mkdir(exist_ok=True)
        (info / "public-text-denylist").write_text(f"{HOST}\n", encoding="utf-8")
        head = self.commit("new.md", f"scp x {HOST}:/tmp\n")
        r = run("--range", f"{self.base}..{head}", "--root", str(self.repo))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("[denylist]", r.stdout)

    def test_all_mode_reports_existing_text(self):
        r = run("--all", "--root", str(self.repo))
        self.assertEqual(r.returncode, 1)
        self.assertIn("old.md:1: [email]", r.stdout)


if __name__ == "__main__":
    unittest.main()
