"""Tests for pre_archive_check: every check is shown to CATCH its failure class.

Each test builds throwaway git repos in a temp dir; nothing here touches a real repo. Git runs
with global and system config switched off, so a user's global excludes file or hooks cannot
change what a test sees.
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import pre_archive_check as pac  # noqa: E402

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
}


def sh(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Repo(unittest.TestCase):
    """A clean repo with a bare remote and everything pushed."""

    def setUp(self):
        self._env = mock.patch.dict(os.environ, GIT_ENV)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.tmp = pathlib.Path(os.path.realpath(tempfile.mkdtemp(prefix="pac-")))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = self.tmp / "remote.git"
        self.repo = self.tmp / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / "README").write_text("x\n")
        (self.repo / ".gitignore").write_text(
            "results/\nanalysis/**/out/\nprivate/\n.venv/\nnode_modules/\ntmp/\nbig/\n")
        sh(self.repo, "add", "-A")
        sh(self.repo, "commit", "-q", "-m", "init")
        sh(self.repo, "remote", "add", "origin", str(self.remote))
        sh(self.repo, "push", "-q", "origin", "main")

    def check(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pac.main(["--path", str(self.repo), "--json", *extra])
        report = json.loads(out.getvalue())
        self.assertEqual(report["exit"], code)
        return code, report

    def statuses(self, report, check):
        return [r["status"] for r in report["results"] if r["check"] == check]

    def items(self, report, check):
        return [i for r in report["results"] if r["check"] == check for i in r["items"]]

    def write(self, rel, data=b"data\n"):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def manifest(self, entries):
        """A durable store: copy each (src, data) into store/ and write store/SHA256SUMS."""
        store = self.tmp / "store"
        store.mkdir(exist_ok=True)
        lines = []
        for name, data in entries:
            (store / name).write_bytes(data)
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
        (store / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        return store / "SHA256SUMS"


class TestPass(Repo):
    def test_clean_tree_passes(self):
        code, r = self.check()
        self.assertEqual(code, 0, r["results"])
        self.assertEqual(r["verdict"], "PASS")

    def test_text_output_ends_with_verdict_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pac.main(["--path", str(self.repo)])
        last = out.getvalue().strip().splitlines()[-1]
        self.assertRegex(last, r"^pre-archive check: PASS \(\d{4}-\d\d-\d\dT")

    def test_cache_only_ignored_dirs_pass(self):
        self.write(".venv/lib/site.py")
        self.write("node_modules/x/index.js")
        self.write("tmp/scratch.txt")
        self.write("results/.venv/lib/x.py")   # a cache inside an output dir is still a cache
        code, r = self.check()
        self.assertEqual(code, 0, r["results"])


class TestUncommitted(Repo):
    def test_modified_file_fails(self):
        (self.repo / "README").write_text("changed\n")
        code, r = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(self.items(r, "uncommitted"), ["README"])

    def test_untracked_file_fails(self):
        self.write("notes/new.md")
        code, r = self.check()
        self.assertEqual(code, 1)
        self.assertIn("notes/new.md", self.items(r, "uncommitted"))


class TestUnpushed(Repo):
    def _commit(self):
        self.write("a.txt")
        sh(self.repo, "add", "a.txt")
        sh(self.repo, "commit", "-q", "-m", "local only")
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_unpushed_commit_fails(self):
        head = self._commit()
        code, r = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(self.items(r, "unpushed"), [head])

    def test_handed_over_commit_passes(self):
        head = self._commit()
        code, r = self.check("--handed-over", head[:10])
        self.assertEqual(code, 0, r["results"])

    def test_short_handed_over_prefix_is_refused(self):
        head = self._commit()
        code, r = self.check("--handed-over", head[:4])
        self.assertEqual(code, 2)   # could not check: a 4-char prefix vouches for too much

    def test_no_remote_at_all_fails(self):
        sh(self.repo, "remote", "remove", "origin")
        code, _ = self.check()
        self.assertEqual(code, 1)


class TestOutputs(Repo):
    DATA = b"model output\n" * 100

    def test_output_without_manifest_fails(self):
        self.write("results/table.csv", self.DATA)
        code, r = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(self.items(r, "outputs"), ["results/table.csv"])

    def test_nested_paper_dir_is_an_output(self):
        # The near-miss shape: outputs under private/paper2/.../out, not at the top level.
        self.write("private/paper2/editor-flows/out/model.npz", self.DATA)
        code, r = self.check()
        self.assertEqual(code, 1)
        self.assertIn("private/paper2/editor-flows/out/model.npz", self.items(r, "outputs"))

    def test_analysis_out_glob(self):
        self.write("analysis/a/b/out_v5/x.parquet", self.DATA)
        self.assertEqual(self.check()[0], 1)

    def test_output_with_matching_manifest_passes(self):
        self.write("results/table.csv", self.DATA)
        m = self.manifest([("table-copy.csv", self.DATA)])   # saved under another name: counts
        code, r = self.check("--manifest", str(m))
        self.assertEqual(code, 0, r["results"])

    def test_mismatched_sha_fails(self):
        self.write("results/table.csv", self.DATA)
        m = self.manifest([("table.csv", self.DATA + b"older version\n")])
        code, r = self.check("--manifest", str(m))
        self.assertEqual(code, 1)
        self.assertEqual(self.items(r, "outputs"), ["results/table.csv"])

    def test_manifest_listing_without_durable_copy_fails(self):
        self.write("results/table.csv", self.DATA)
        m = self.manifest([("table.csv", self.DATA)])
        (m.parent / "table.csv").unlink()      # the manifest claims a copy that is not there
        code, r = self.check("--manifest", str(m))
        self.assertEqual(code, 1)
        self.assertIn("missing or no longer matches", " ".join(
            x["reason"] for x in r["results"] if x["check"] == "outputs"))

    def test_malformed_manifest_cannot_check(self):
        self.write("results/table.csv", self.DATA)
        m = self.tmp / "SHA256SUMS"
        m.write_text("not a sha  table.csv\n")
        self.assertEqual(self.check("--manifest", str(m))[0], 2)

    def test_custom_output_glob_replaces_defaults(self):
        self.write("big/run1.bin", self.DATA)
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.check("--output-glob", "big/")[0], 1)

    def test_large_ignored_data_warns_without_failing(self):
        self.write("big/blob.bin", b"\0" * (2 * 1024 * 1024))
        code, r = self.check("--warn-mb", "1")
        self.assertEqual(code, 0)
        self.assertEqual(self.statuses(r, "ignored-size"), ["warn"])
        self.assertTrue(self.items(r, "ignored-size")[0].startswith("big/"))

    def test_large_dependency_cache_does_not_warn(self):
        self.write(".venv/blob.bin", b"\0" * (2 * 1024 * 1024))
        _, r = self.check("--warn-mb", "1")
        self.assertEqual(self.statuses(r, "ignored-size"), [])


class TestGlobs(unittest.TestCase):
    def test_directory_glob_needs_something_inside(self):
        self.assertTrue(pac.matches_output("paper2/fig.pdf", ["paper*/"]))
        self.assertTrue(pac.matches_output("x/paper2/fig.pdf", ["paper*/"]))
        self.assertFalse(pac.matches_output("notes/paper.md", ["paper*/"]))
        self.assertFalse(pac.matches_output("x/paper2/fig.pdf", ["/paper*/"]))

    def test_cache_kind(self):
        self.assertEqual(pac.cache_kind("a/venv-3.12/x.py"), "dep")
        self.assertEqual(pac.cache_kind(".venv/"), "dep")
        self.assertEqual(pac.cache_kind("tmp/run.log"), "scratch")
        self.assertIsNone(pac.cache_kind("results/tmp"))   # a FILE named tmp is not a cache dir


@unittest.skipUnless(shutil.which("lsof"), "lsof not installed")
class TestOpenFiles(Repo):
    def test_open_handle_from_child_process_fails(self):
        target = self.write("held.txt")
        sh(self.repo, "add", "held.txt")
        sh(self.repo, "commit", "-q", "-m", "held")
        sh(self.repo, "push", "-q", "origin", "main")
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys,time; f=open(sys.argv[1]); print('ready', flush=True); time.sleep(120)",
             str(target)], stdout=subprocess.PIPE, text=True, cwd=str(self.tmp))
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        code, r = self.check()
        self.assertEqual(code, 1, r["results"])
        self.assertTrue(any(i.startswith(f"pid {child.pid} ") for i in self.items(r, "open-files")))

    def test_lsof_timeout_is_could_not_check(self):
        with mock.patch.object(pac, "LSOF_TIMEOUT", 0.0001), \
                mock.patch.object(pac.subprocess.Popen, "communicate",
                                  side_effect=[subprocess.TimeoutExpired("lsof", 0), ("", "")]):
            with self.assertRaises(pac.CheckError):
                pac.check_open_files(str(self.repo))


class TestCouldNotCheck(Repo):
    def test_not_a_repo_exits_2(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = pac.main(["--path", str(plain)])
        self.assertEqual(code, 2)
        self.assertTrue(out.getvalue().strip().splitlines()[-1].startswith(
            "pre-archive check: FAIL ("))

    def test_missing_lsof_exits_2_not_pass(self):
        with mock.patch.object(pac.shutil, "which", return_value=None):
            code, r = self.check()
        self.assertEqual(code, 2)
        self.assertEqual(self.statuses(r, "open-files"), ["error"])

    def test_fail_wins_over_could_not_check(self):
        (self.repo / "README").write_text("changed\n")
        with mock.patch.object(pac.shutil, "which", return_value=None):
            self.assertEqual(self.check()[0], 1)

    def test_no_results_is_not_a_pass(self):
        self.assertEqual(pac.verdict([]), ("FAIL", 2))


class TestWholeTree(Repo):
    def test_stash_on_branch_is_reported(self):
        (self.repo / "README").write_text("stashed\n")
        sh(self.repo, "stash", "push", "-q", "-m", "wip")   # the test's own throwaway repo
        code, r = self.check("--whole-tree")
        self.assertEqual(self.statuses(r, "stashes"), ["warn"])
        self.assertEqual(code, 0)   # a stash outlives the worktree: reported, not a FAIL
        _, r = self.check()
        self.assertEqual(self.statuses(r, "stashes"), [])   # only in --whole-tree mode

    def test_other_worktree_on_same_commit_is_reported(self):
        other = self.tmp / "wt2"
        sh(self.repo, "worktree", "add", "-q", "--detach", str(other))
        _, r = self.check("--whole-tree")
        self.assertEqual(self.items(r, "shared-branch"), [f"{other} (same commit)"])


class TestState(Repo):
    def test_state_not_modified_today_fails(self):
        st = self.tmp / "STATE.md"
        st.write_text("x")
        old = time.time() - 3 * 86400
        os.utime(st, (old, old))
        self.assertEqual(self.check("--state", str(st))[0], 1)

    def test_state_modified_today_passes(self):
        st = self.tmp / "STATE.md"
        st.write_text("x")
        self.assertEqual(self.check("--state", str(st))[0], 0)

    def test_missing_state_fails(self):
        self.assertEqual(self.check("--state", str(self.tmp / "nope.md"))[0], 1)

    def test_date_comparison(self):
        st = self.tmp / "STATE.md"
        st.write_text("x")
        self.assertEqual(pac.check_state(str(st), today=dt.date(2000, 1, 1))[0]["status"], "fail")


class TestReadOnly(unittest.TestCase):
    def test_mutating_git_is_refused(self):
        for args in (("stash",), ("stash", "push"), ("worktree", "remove", "x"), ("commit",),
                     ("checkout", "x"), ("gc",)):
            with self.assertRaises(pac.UnsafeGitCommand):
                pac.git("/nonexistent", *args)


if __name__ == "__main__":
    unittest.main()
