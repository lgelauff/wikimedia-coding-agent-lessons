"""Offline tests for git_hygiene pure parsers/formatters (no git calls)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import git_hygiene as g  # noqa: E402


def test_classify_porcelain_splits_tracked_vs_untracked():
    text = " M a.py\nMM b.py\n?? new.txt\n?? other/\nA  staged.py\n"
    tracked, untracked = g._classify_porcelain(text)
    assert tracked == 3 and untracked == 2


def test_parse_worktrees_excludes_main():
    text = ("worktree /repo/main\nHEAD abc\nbranch refs/heads/main\n\n"
            "worktree /repo/wt-a\nHEAD def\n\nworktree /repo/wt-b\nHEAD ghi\n")
    assert g._parse_worktrees(text) == ["/repo/wt-a", "/repo/wt-b"]


def test_is_dirty_true_on_any_signal():
    base = {"is_repo": True, "uncommitted": 0, "untracked": 0, "stashes": 0,
            "unpushed": 0, "dirty_worktrees": []}
    assert not g.is_dirty(base)
    assert g.is_dirty({**base, "unpushed": 2})
    assert g.is_dirty({**base, "dirty_worktrees": [{"path": "/x", "uncommitted": 1, "untracked": 0}]})


def test_summarize_lists_signals():
    r = {"uncommitted": 2, "untracked": 1, "stashes": 0, "unpushed": 3, "dirty_worktrees": []}
    s = g.summarize(r)
    assert "2 uncommitted" in s and "1 untracked" in s and "3 unpushed" in s and "stash" not in s


def test_format_report_empty_when_clean():
    clean = {"is_repo": True, "uncommitted": 0, "untracked": 0, "stashes": 0,
             "unpushed": 0, "dirty_worktrees": [], "branch": "main", "repo": "/r"}
    assert g.format_report([clean]) == ""


def test_format_report_lists_dirty_repo_and_worktrees():
    r = {"is_repo": True, "uncommitted": 1, "untracked": 0, "stashes": 0, "unpushed": 0,
         "branch": "feat", "repo": "/home/u/wiki-polis",
         "dirty_worktrees": [{"path": "/home/u/wiki-polis-wt", "uncommitted": 2, "untracked": 1}]}
    out = g.format_report([r])
    assert "wiki-polis [feat]" in out and "1 uncommitted" in out
    assert "worktree wiki-polis-wt" in out and "2 uncommitted, 1 untracked" in out
