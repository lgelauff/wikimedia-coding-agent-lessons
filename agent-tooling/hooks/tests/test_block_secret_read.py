"""Tests for block_secret_read's narrowed verdict() (post-panel, 2026)."""
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import block_secret_read as g  # noqa: E402


def _read(p): return g.verdict("Read", {"file_path": p})
def _bash(c): return g.verdict("Bash", {"command": c})


def test_blocks_read_of_real_secret_files():
    for p in ["~/.config/agent-secrets/.env", "research-vault/.env", "a/.env.local",
              "prod.env", "creds/credentials.json", "keys/id_rsa", "keys/id_ed25519",
              "tls/server.pem", "x/my-secrets.txt"]:
        assert _read(p), p


def test_allows_examples_source_and_keynote():
    # .env.example templates, source code (incl. this guard's own file), Keynote .key
    for p in [".env.example", ".env.sample", "config.env.template", "app.py",
              "README.md", "hooks/block_secret_read.py", "slides.key"]:
        assert _read(p) is None, p


def test_grep_pattern_mentioning_secret_is_allowed():
    # the confirmed false positive: a grep PATTERN, not a path
    assert _bash("git diff A..B | grep -inE 'API_KEY=x|SECRET=x|password=y'") is None
    assert _bash("grep secret notes.md") is None          # 'secret' is the pattern
    assert _bash("grep -rn credential src/") is None


def test_bash_reading_real_secret_file_flags():
    assert _bash("cat ~/.config/agent-secrets/.env")
    assert _bash("cat my-secrets.txt")
    assert _bash("cp research-vault/.env /tmp/x")


def test_env_dump_narrowed_no_bare_key_or_token():
    assert _bash("printenv IA_ACCESS_KEY")
    assert _bash("env | grep OPENROUTER_API_KEY")
    assert _bash("echo $IA_SECRET_KEY")
    # NOT secrets — bare _KEY / _TOKEN no longer flagged
    assert _bash("printenv CSRF_TOKEN") is None
    assert _bash("echo $PRIMARY_KEY") is None
    assert _bash("printenv PATH") is None
    assert _bash("echo $HOME") is None


def test_main_emits_ask_not_deny(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": "Read", "tool_input": {"file_path": "a/.env"}})))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    g.main()
    assert json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"] == "ask"
