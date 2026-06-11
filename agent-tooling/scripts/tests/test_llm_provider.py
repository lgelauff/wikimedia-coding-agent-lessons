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


def test_dispatch_routes_to_claude_code(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "claude-code")
    calls = {}
    monkeypatch.setattr(lp, "_claude_code",
                        lambda p, s, m, t: (calls.__setitem__("hit", (p, s, m)), "ok")[1])
    assert lp.query_llm("prompt", system="sys") == "ok"
    assert calls["hit"][0] == "prompt" and calls["hit"][1] == "sys"
