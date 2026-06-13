"""Tests for the classify_github_op policy."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import classify_github_op as p  # noqa: E402


def test_deny_catastrophic():
    for cmd in ["gh repo delete lgelauff/foo", "gh repo archive x", "gh release delete v1"]:
        v = p.classify(cmd)
        assert v and v[0] == "deny", cmd


def test_gh_api_delete_repo_is_deny_not_ask():
    for cmd in ["gh api -X DELETE /repos/owner/name",
                "gh api --method DELETE /repos/o/n/releases/12"]:
        v = p.classify(cmd)
        assert v and v[0] == "deny", cmd


def test_ask_writes():
    for cmd in [
        "gh pr comment 5 -b hi",
        "gh pr merge 5 --squash",
        "gh pr create -t x -b y",
        "gh issue close 12",
        "gh issue create -t bug",
        "gh release create v2",
        "gh workflow run ci.yml",
        "git push origin main",
        "gh api -X POST /repos/o/r/issues",
        "gh api --method DELETE /x",
    ]:
        v = p.classify(cmd)
        assert v and v[0] == "ask", cmd


def test_allow_reads():
    for cmd in [
        "gh pr view 5",
        "gh issue list",
        "gh pr diff 5",
        "gh api /repos/o/r",            # no write method
        "git log --oneline",
        "git status",
        "ls -la",
        "",
    ]:
        assert p.classify(cmd) is None, cmd


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["x", "gh", "pr", "merge", "5"])
    assert p.main() == 1
    assert capsys.readouterr().out.startswith("ask ")
    monkeypatch.setattr(sys, "argv", ["x", "gh", "pr", "view", "5"])
    assert p.main() == 0
