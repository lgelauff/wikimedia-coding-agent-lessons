"""Offline tests for the secrets resolver (temp file, no real keys)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import secrets as s  # noqa: E402


def _write(tmp_path, body):
    f = tmp_path / ".env"
    f.write_text(body, encoding="utf-8")
    return f


def test_env_wins_over_file(tmp_path, monkeypatch):
    f = _write(tmp_path, "IA_ACCESS_KEY=fromfile\n")
    monkeypatch.setenv("AGENT_SECRETS_FILE", str(f))
    monkeypatch.setenv("IA_ACCESS_KEY", "fromenv")
    assert s.get_secret("IA_ACCESS_KEY") == "fromenv"


def test_falls_back_to_file(tmp_path, monkeypatch):
    f = _write(tmp_path, "# a comment\nIA_ACCESS_KEY=abc123\nexport IA_SECRET_KEY = 'xyz'\n")
    monkeypatch.setenv("AGENT_SECRETS_FILE", str(f))
    monkeypatch.delenv("IA_ACCESS_KEY", raising=False)
    monkeypatch.delenv("IA_SECRET_KEY", raising=False)
    assert s.get_secret("IA_ACCESS_KEY") == "abc123"
    assert s.get_secret("IA_SECRET_KEY") == "xyz"   # export prefix + quotes stripped


def test_missing_returns_default_or_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SECRETS_FILE", str(tmp_path / "nope.env"))
    monkeypatch.delenv("NOSUCH", raising=False)
    assert s.get_secret("NOSUCH") is None
    assert s.get_secret("NOSUCH", default="d") == "d"
    try:
        s.get_secret("NOSUCH", required=True)
        assert False, "should raise"
    except RuntimeError as e:
        assert "NOSUCH" in str(e)


def test_load_into_environ_no_override_then_override(tmp_path, monkeypatch):
    f = _write(tmp_path, "A=1\nB=2\n")
    monkeypatch.setenv("AGENT_SECRETS_FILE", str(f))
    monkeypatch.setenv("A", "preset")
    monkeypatch.delenv("B", raising=False)
    n = s.load_into_environ()
    assert os.environ["A"] == "preset" and os.environ["B"] == "2" and n == 1
    s.load_into_environ(override=True)
    assert os.environ["A"] == "1"


def test_get_secret_never_returns_partial_comment(tmp_path, monkeypatch):
    f = _write(tmp_path, "NOEQUALS line\n  \nK=v\n")
    monkeypatch.setenv("AGENT_SECRETS_FILE", str(f))
    monkeypatch.delenv("K", raising=False)
    assert s.get_secret("K") == "v"
