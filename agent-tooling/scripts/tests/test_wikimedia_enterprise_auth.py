"""Smoke tests for wikimedia_enterprise_auth: cache logic + credential lookup,
network calls mocked out."""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import wikimedia_enterprise_auth as wea  # noqa: E402


def _isolated_cache(tmpdir, monkeypatch):
    cache_file = os.path.join(tmpdir, "token.json")
    monkeypatch.setattr(wea, "CACHE_FILE", cache_file)
    return cache_file


def test_missing_credentials_non_interactive_no_gui_exits_nonzero(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_USERNAME", raising=False)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_PASSWORD", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(wea.sys, "platform", "linux")
    try:
        wea.get_credentials()
    except SystemExit as e:
        assert "environment" in str(e)
    else:
        raise AssertionError("expected SystemExit on missing credentials with no terminal/GUI")


def test_missing_credentials_non_interactive_uses_gui_dialog_on_macos(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_USERNAME", raising=False)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_PASSWORD", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(wea.sys, "platform", "darwin")

    prompts = []

    def fake_gui_prompt(message, hidden=False):
        prompts.append((message, hidden))
        return "s3cret" if hidden else "alice"

    monkeypatch.setattr(wea, "gui_prompt", fake_gui_prompt)

    username, password = wea.get_credentials()
    assert (username, password) == ("alice", "s3cret")
    assert prompts[0][1] is False  # username prompt not hidden
    assert prompts[1][1] is True  # password prompt hidden


def test_gui_dialog_cancelled_exits_nonzero(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_USERNAME", raising=False)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_PASSWORD", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(wea.sys, "platform", "darwin")
    monkeypatch.setattr(wea, "gui_prompt", lambda message, hidden=False: None)

    try:
        wea.get_credentials()
    except SystemExit as e:
        assert "cancelled" in str(e)
    else:
        raise AssertionError("expected SystemExit when the GUI dialog is cancelled")


def test_missing_credentials_interactive_prompts_and_does_not_persist_password(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_USERNAME", raising=False)
    monkeypatch.delenv("WIKIMEDIA_ENTERPRISE_PASSWORD", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(wea, "input", lambda prompt="": "alice", raising=False)
    monkeypatch.setattr(wea.getpass, "getpass", lambda prompt="": "s3cret")

    username, password = wea.get_credentials()
    assert (username, password) == ("alice", "s3cret")


def test_env_credentials_skip_prompt(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_USERNAME", "alice")
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_PASSWORD", "s3cret")

    def fail_prompt(prompt=""):
        raise AssertionError("should not prompt when env credentials are present")

    monkeypatch.setattr(wea.getpass, "getpass", fail_prompt)

    assert wea.get_credentials() == ("alice", "s3cret")


def test_username_is_lowercased(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_USERNAME", "Alice")
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_PASSWORD", "s3cret")

    username, password = wea.get_credentials()
    assert username == "alice"
    assert password == "s3cret"  # pragma: allowlist secret


def test_login_caches_tokens(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    monkeypatch.setattr(wea._agent_secrets, "load_into_environ", lambda: None)
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_USERNAME", "alice")
    monkeypatch.setenv("WIKIMEDIA_ENTERPRISE_PASSWORD", "s3cret")

    calls = []

    def fake_post_json(url, payload):
        calls.append((url, payload))
        return {"id_token": "x", "access_token": "AT1", "refresh_token": "RT1", "expires_in": 86400}

    monkeypatch.setattr(wea, "post_json", fake_post_json)

    token = wea.get_access_token()
    assert token == "AT1"
    assert calls[0][0].endswith("/login")
    assert calls[0][1] == {"username": "alice", "password": "s3cret"}  # pragma: allowlist secret

    cache = json.load(open(wea.CACHE_FILE))
    assert cache["access_token"] == "AT1"
    assert cache["refresh_token"] == "RT1"


def test_valid_cached_token_skips_network(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    now = time.time()
    with open(wea.CACHE_FILE, "w") as f:
        json.dump(
            {
                "username": "alice",
                "access_token": "CACHED",
                "access_token_expiry": now + 3600,
                "refresh_token": "RT1",
                "refresh_token_expiry": now + 86400,
                "refresh_count": 0,
            },
            f,
        )

    def fail_post_json(url, payload):
        raise AssertionError("should not hit the network for a valid cached token")

    monkeypatch.setattr(wea, "post_json", fail_post_json)

    assert wea.get_access_token() == "CACHED"


def test_expired_access_token_refreshes_without_login(monkeypatch, tmp_path):
    _isolated_cache(str(tmp_path), monkeypatch)
    now = time.time()
    with open(wea.CACHE_FILE, "w") as f:
        json.dump(
            {
                "username": "alice",
                "access_token": "STALE",
                "access_token_expiry": now - 10,
                "refresh_token": "RT1",
                "refresh_token_expiry": now + 86400,
                "refresh_count": 3,
            },
            f,
        )

    calls = []

    def fake_post_json(url, payload):
        calls.append(url)
        return {"id_token": "x", "access_token": "AT2", "expires_in": 300}

    monkeypatch.setattr(wea, "post_json", fake_post_json)

    token = wea.get_access_token()
    assert token == "AT2"
    assert calls == [f"{wea.AUTH_BASE}/token-refresh"]

    cache = json.load(open(wea.CACHE_FILE))
    assert cache["refresh_count"] == 4
