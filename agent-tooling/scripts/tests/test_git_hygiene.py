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


def test_summarize_flags_no_upstream():
    r = {"uncommitted": 0, "untracked": 0, "stashes": 0, "unpushed": 4,
         "no_upstream": True, "dirty_worktrees": []}
    assert "4 unpushed (no upstream)" in g.summarize(r)


def test_format_report_notes_partial_scan():
    r = {"is_repo": True, "uncommitted": 1, "untracked": 0, "stashes": 0, "unpushed": 0,
         "branch": "main", "repo": "/r", "dirty_worktrees": [], "partial_scan": True}
    assert "partial" in g.format_report([r])


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


# --- ignored-content detection (the `git status` blind spot) --------------------------------

def test_is_noise_filters_regenerable_dirs_but_keeps_real_paths():
    assert g._is_noise("a/__pycache__/x.pyc")
    assert g._is_noise("node_modules/pkg/index.js")
    # Scratch dirs holding real deliverables must NOT be filtered — this is the whole point.
    assert not g._is_noise(".claude/audit-2026-08-09/scan.json")
    assert not g._is_noise("data/interim/s1_full/")


def test_human_readable_sizes():
    assert g._human(512) == "512B"
    assert g._human(1536).endswith("KB")
    assert g._human(5 * 1024 ** 3).endswith("GB")


def test_worktree_with_only_ignored_content_counts_as_dirty():
    """The regression this capability exists for.

    A worktree with 0 uncommitted and 0 untracked is INVISIBLE to a tracked-state-only scan,
    yet may hold the only copy of real work. Observed live: a worktree carrying a bug detector
    and its 367-file scan output in an ignored scratch dir was collapsed mid-session.
    """
    base = {"is_repo": True, "uncommitted": 0, "untracked": 0, "stashes": 0,
            "unpushed": 0, "dirty_worktrees": []}
    assert not g.is_dirty(base)
    wt = {"path": "/repo/wt-a", "uncommitted": 0, "untracked": 0,
          "ignored": [{"path": ".claude/", "bytes": 97_000_000, "files": 12, "dir": True}]}
    assert g.is_dirty({**base, "dirty_worktrees": [wt]})


def test_at_risk_ignored_excludes_main_checkout():
    """Main-checkout ignored content is the normal data store — reported, never at-risk."""
    wt = {"path": "/repo/wt-a", "uncommitted": 0, "untracked": 0,
          "ignored": [{"path": "scratch/", "bytes": 10, "files": 1, "dir": True}]}
    r = {"is_repo": True, "uncommitted": 0, "untracked": 0, "stashes": 0, "unpushed": 0,
         "dirty_worktrees": [wt],
         "ignored_main": [{"path": "data/", "bytes": 88_000_000_000, "files": 4000, "dir": True}]}
    at_risk = g.at_risk_ignored(r)
    assert len(at_risk) == 1
    assert at_risk[0]["path"] == "scratch/"
    assert all(row["path"] != "data/" for row in at_risk)


def test_report_names_the_biggest_ignored_path():
    wt = {"path": "/repo/wt-a", "uncommitted": 0, "untracked": 0,
          "ignored": [{"path": ".claude/", "bytes": 97_000_000, "files": 12, "dir": True}]}
    r = {"is_repo": True, "repo": "/repo", "branch": "main", "uncommitted": 0, "untracked": 0,
         "stashes": 0, "unpushed": 0, "dirty_worktrees": [wt], "ignored_main": []}
    out = g.format_report([r])
    assert "GITIGNORED" in out and ".claude/" in out
    assert "invisible to git status" in out


# --- regressions: "could not verify" must never render as "verified clean" -------------------

def test_noise_matching_is_component_anchored_not_substring():
    """Unanchored substring matching dropped real content whose name merely CONTAINED a token."""
    for real in ("analysis/.toxicity_scores/results.json",      # contains ".tox"
                 "corpus.toxicity/data.json",                   # contains ".tox"
                 "docs/node_modules_scrape_2026/README.md",     # contains "node_modules"
                 "notes/my.gradlenotes/data.csv",               # contains ".gradle"
                 "cache/reproducibility.venv-snapshot/env.lock"):  # contains ".venv"
        assert not g._is_noise(real), f"real content wrongly filtered as noise: {real}"
    for noise in ("a/__pycache__/x.pyc", "node_modules/pkg/i.js", ".venv/lib/py", "x/.tox/py39/z"):
        assert g._is_noise(noise), f"genuine noise leaked through: {noise}"


def test_git_records_failure_instead_of_silently_returning_empty():
    """A failed git call must be distinguishable from a genuinely empty result."""
    errs = []
    out = g._git("/definitely/not/a/repo", "status", "--porcelain", timeout=5.0, errors=errs)
    assert out == ""
    assert len(errs) == 1, "failure was swallowed — this is the false-all-clear bug"
    assert "args" in errs[0] and "why" in errs[0]


def test_scan_failed_and_report_refuse_to_claim_clean():
    """The core contract: inability to verify is NOT verified-clean."""
    r = {"repo": "/x", "is_repo": True, "branch": "main", "uncommitted": 0, "untracked": 0,
         "stashes": 0, "unpushed": 0, "dirty_worktrees": [], "ignored_main": [],
         "errors": [{"repo": "/x", "args": ["status", "--porcelain"], "why": "timeout after 5.0s"}],
         "scan_complete": False}
    assert g.scan_failed(r)
    assert not g.is_dirty(r)          # nothing was OBSERVED dirty ...
    out = g.format_report([r])
    assert out, "a failed scan produced an empty report — reads as clean"
    assert "SCAN INCOMPLETE" in out and "UNVERIFIED" in out


def test_clean_scan_still_reports_nothing():
    """No false alarms: a genuinely clean, complete scan stays silent."""
    r = {"repo": "/x", "is_repo": True, "branch": "main", "uncommitted": 0, "untracked": 0,
         "stashes": 0, "unpushed": 0, "dirty_worktrees": [], "ignored_main": [],
         "errors": [], "scan_complete": True}
    assert not g.scan_failed(r) and not g.is_dirty(r)
    assert g.format_report([r]) == ""
