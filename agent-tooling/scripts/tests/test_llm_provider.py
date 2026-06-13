"""Offline tests for llm_provider dispatch (no real LLM calls)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
import llm_provider as lp  # noqa: E402


def test_default_provider_is_claude_code(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_PROVIDER", raising=False)
    assert lp._provider() == "claude-code"


def test_global_var_selects_provider(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "OpenRouter")  # case-insensitive
    assert lp._provider() == "openrouter"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "bogus")
    try:
        lp.query_llm("hi")
        assert False, "should have raised"
    except ValueError as e:
        assert "bogus" in str(e)


def test_http_provider_requires_key(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "mistral")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    try:
        lp.query_llm("hi")
        assert False, "should have raised"
    except RuntimeError as e:
        assert "MISTRAL_API_KEY" in str(e)


def test_claude_code_strips_routing_env_keeps_oauth(monkeypatch):
    import types
    cap = {}
    def fake_run(cmd, **kw):
        cap["env"] = kw.get("env", {})
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(lp.subprocess, "run", fake_run)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
              "AWS_SECRET_ACCESS_KEY", "CLAUDE_CODE_USE_BEDROCK", "HTTPS_PROXY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    assert lp._claude_code("hi", None, None, 10) == "ok"
    env = cap["env"]
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
              "AWS_SECRET_ACCESS_KEY", "CLAUDE_CODE_USE_BEDROCK", "HTTPS_PROXY"):
        assert k not in env, f"{k} should be stripped"
    assert env.get("CLAUDE_CODE_OAUTH_TOKEN") == "tok"   # subscription token kept


def test_query_llm_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "claude-code")
    monkeypatch.setattr(lp.time, "sleep", lambda s: None)
    n = {"c": 0}
    def flaky(p, s, m, t):
        n["c"] += 1
        if n["c"] < 2:
            raise RuntimeError("429 rate limit")
        return "ok"
    monkeypatch.setattr(lp, "_claude_code", flaky)
    assert lp.query_llm("x", retries=2) == "ok" and n["c"] == 2


def test_query_llm_does_not_retry_bad_provider(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "bogus")
    monkeypatch.setattr(lp.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    try:
        lp.query_llm("x")
        assert False
    except ValueError:
        pass


def test_dispatch_routes_to_claude_code(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "claude-code")
    calls = {}
    monkeypatch.setattr(lp, "_claude_code",
                        lambda p, s, m, t: (calls.__setitem__("hit", (p, s, m)), "ok")[1])
    assert lp.query_llm("prompt", system="sys") == "ok"
    assert calls["hit"][0] == "prompt" and calls["hit"][1] == "sys"
