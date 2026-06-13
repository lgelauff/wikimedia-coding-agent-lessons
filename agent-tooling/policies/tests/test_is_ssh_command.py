"""Tests for the is_ssh_command policy (pure decision logic)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import is_ssh_command as p  # noqa: E402


def test_blocks_ssh_family():
    for cmd in [
        "ssh user@host",
        "scp file user@host:/tmp",
        "sftp host",
        "autossh -M 0 host",
        "rsync -avz -e ssh ./ user@host:/srv",
        "cd /tmp && ssh host uptime",      # after a separator
        "echo hi | ssh host cat",           # after a pipe
        "x=$(ssh host hostname)",           # command substitution
        "`ssh host id`",                    # backtick substitution
        "(ssh host uptime)",                # subshell
        "true & ssh host uptime",           # single-& background
    ]:
        assert p.is_ssh(cmd), f"should block: {cmd}"


def test_allows_non_ssh():
    for cmd in [
        "ls -la",
        "git push origin main",
        "echo ssherlock",                   # 'ssh' as a substring, not a command
        "python3 dssh.py",                  # not a bare ssh token
        "rsync -avz ./ /backup",            # local rsync, no -e ssh
        "",
    ]:
        assert p.is_ssh(cmd) is None, f"should allow: {cmd}"


def test_main_exit_codes(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["is_ssh_command.py", "ssh", "host"])
    assert p.main() == 1
    assert "SSH" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["is_ssh_command.py", "ls", "-la"])
    assert p.main() == 0
