"""grant_repo_read: rule lands in the main checkout and every worktree, only for that repo, read only."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grant_repo_read as g  # noqa: E402


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class GrantRepoRead(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.repo = self.root / "repo"
        git("init", "-q", str(self.repo))
        git("-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        self.wt = self.repo / ".claude" / "worktrees" / "wt1"
        git("-C", str(self.repo), "worktree", "add", "-q", str(self.wt))
        other = self.root / "other"
        git("init", "-q", str(other))
        git("-C", str(other), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        # an existing settings file with other content must be kept
        (self.repo / ".claude" / "settings.local.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))

    def allow(self, tree):
        return json.loads((tree / ".claude" / "settings.local.json").read_text())["permissions"]["allow"]

    def test_dry_run_writes_nothing(self):
        g.main([str(self.root)])
        self.assertEqual(self.allow(self.repo), ["Bash(ls)"])
        self.assertFalse((self.wt / ".claude" / "settings.local.json").exists())

    def test_apply_main_and_worktree_read_only_scoped(self):
        g.main([str(self.root), "--apply"])
        rule = f"Read(/{self.repo}/**)"
        self.assertEqual(self.allow(self.repo), ["Bash(ls)", rule])
        self.assertEqual(self.allow(self.wt), [rule])
        self.assertEqual(self.allow(self.root / "other"), [f"Read(/{self.root / 'other'}/**)"])
        for t in (self.repo, self.wt):
            self.assertFalse(any(r.startswith(("Edit", "Write")) for r in self.allow(t)))
        self.assertTrue(any(p.name.startswith("settings.local.json.bak-") for p in (self.repo / ".claude").iterdir()))

    def test_quarantine_denied(self):
        g.main([str(self.root), "--apply"])
        deny = json.loads((self.wt / ".claude" / "settings.local.json").read_text())["permissions"]["deny"]
        self.assertEqual(deny, [f"Read(/{self.repo}/**/.claude/quarantine/**)"])

    def test_outside_worktree_and_symlink_skipped(self):
        outside = Path(tempfile.mkdtemp()).resolve() / "wt-out"
        git("-C", str(self.repo), "worktree", "add", "-q", str(outside))
        second = Path(tempfile.mkdtemp()).resolve()
        (second / "repo-link").symlink_to(self.repo)
        files = [f for f, _, _ in g.plan([self.root, second])]
        self.assertNotIn(outside / ".claude" / "settings.local.json", files)
        self.assertEqual(len(files), len(set(files)))

    def test_idempotent(self):
        g.main([str(self.root), "--apply"])
        self.assertEqual(g.plan([self.root]), [])


if __name__ == "__main__":
    unittest.main()
