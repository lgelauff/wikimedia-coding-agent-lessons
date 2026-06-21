"""Tests for the block_secret_read guard's pure verdict()."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import block_secret_read as g  # noqa: E402


def test_blocks_read_of_secret_files():
    for p in ["~/.config/agent-secrets/.env", "research-vault/.env", "a/.env.local",
              "creds/credentials.json", "keys/id_rsa", "tls/server.pem", "x/my-secrets.txt"]:
        assert g.verdict("Read", {"file_path": p}), p


def test_allows_read_of_examples_and_normal_files():
    for p in [".env.example", ".env.sample", "config.env.template", "app.py", "README.md"]:
        assert g.verdict("Read", {"file_path": p}) is None, p


def test_blocks_bash_cat_grep_of_secret():
    assert g.verdict("Bash", {"command": "cat ~/.config/agent-secrets/.env"})
    assert g.verdict("Bash", {"command": "grep KEY research-vault/.env"})
    assert g.verdict("Bash", {"command": "cp .env /tmp/x"})


def test_allows_bash_on_example_and_unrelated():
    assert g.verdict("Bash", {"command": "cat .env.example"}) is None
    assert g.verdict("Bash", {"command": "ls -la && git status"}) is None


def test_blocks_env_var_dumps():
    assert g.verdict("Bash", {"command": "printenv IA_ACCESS_KEY"})
    assert g.verdict("Bash", {"command": "env | grep OPENROUTER_API_KEY"})
    assert g.verdict("Bash", {"command": "echo $IA_SECRET_KEY"})
    assert g.verdict("Bash", {"command": 'echo "${ANTHROPIC_API_KEY}"'})


def test_allows_nonsecret_env_use():
    assert g.verdict("Bash", {"command": "echo $HOME"}) is None
    assert g.verdict("Bash", {"command": "printenv PATH"}) is None


def test_ignores_other_tools():
    assert g.verdict("WebFetch", {"url": "http://x/.env"}) is None
