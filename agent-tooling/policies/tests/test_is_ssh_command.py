"""Tests for the is_ssh_command policy (pure decision logic; narrowed 2026)."""
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
        'rsync -avz -e "ssh" ./ user@host:/srv',   # quoted -e ssh still caught
        "cd /tmp && ssh host uptime",              # after a separator
        "echo hi | ssh host cat",                   # after a pipe
        "x=$(ssh host hostname)",                    # command substitution
        "`ssh host id`",                             # backtick substitution
        "(ssh host uptime)",                         # subshell
        "true & ssh host uptime",                    # single-& background
        "sudo ssh host",                             # prefix command — must NOT bypass
    ]:
        assert p.is_ssh(cmd), f"should block: {cmd}"


def test_allows_non_ssh():
    for cmd in [
        "ls -la",
        "git push origin main",
        "echo ssherlock",                    # 'ssh' as a substring, not a command
        "python3 dssh.py",                   # not a bare ssh token
        "rsync -avz ./ /backup",             # local rsync, no -e ssh
        "",
        'echo "=== just the ssh one now ==="',   # ssh MENTIONED in a quoted string — the FP
        "git commit -m 'notes about ssh setup'",  # ssh in a quoted commit message
    ]:
        assert p.is_ssh(cmd) is None, f"should allow: {cmd}"
