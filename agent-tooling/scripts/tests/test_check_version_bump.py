"""Tests for check_version_bump: content changes must carry a version bump."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import check_version_bump as cvb  # noqa: E402

MANIFEST = "agent-tooling/.claude-plugin/plugin.json"


def _repo(tmp_path, version="0.1.0"):
    """A throwaway repo with one committed plugin manifest + one skill file."""
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True,
                                    capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.org")
    run("config", "user.name", "t")
    d = tmp_path / "agent-tooling" / ".claude-plugin"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"name": "agent-tooling",
                                               "version": version}))
    skills = tmp_path / "agent-tooling" / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    return run


def _main(tmp_path, *argv):
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        return cvb.main(["--base", "HEAD~1", *argv])
    finally:
        os.chdir(cwd)


def test_content_change_without_bump_is_blocked(tmp_path, capsys):
    run = _repo(tmp_path)
    (tmp_path / "agent-tooling" / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: changed\n---\n")
    run("commit", "-qam", "edit skill, forget the bump")
    assert _main(tmp_path) == 1
    assert "BLOCKED" in capsys.readouterr().err


def test_content_change_with_bump_passes(tmp_path, capsys):
    run = _repo(tmp_path)
    m = tmp_path / MANIFEST
    m.write_text(json.dumps({"name": "agent-tooling", "version": "0.2.0"}))
    (tmp_path / "agent-tooling" / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: changed\n---\n")
    run("commit", "-qam", "edit skill and bump")
    assert _main(tmp_path) == 0
    assert "0.1.0 -> 0.2.0" in capsys.readouterr().out


def test_untouched_plugin_needs_no_bump(tmp_path):
    run = _repo(tmp_path)
    (tmp_path / "README.md").write_text("unrelated\n")
    run("add", "-A")
    run("commit", "-qm", "docs only")
    assert _main(tmp_path) == 0


def test_missing_base_ref_is_a_usage_error(tmp_path, capsys):
    _repo(tmp_path)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert cvb.main(["--base", "no/such/ref"]) == 2
    finally:
        os.chdir(cwd)
    assert "ERROR" in capsys.readouterr().err
