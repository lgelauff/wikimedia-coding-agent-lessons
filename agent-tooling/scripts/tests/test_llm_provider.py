"""Offline tests for llm_provider dispatch (no real LLM calls)."""
import json
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


def test_liftwing_needs_no_key_and_sends_no_auth_header(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "liftwing")
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    cap = {}

    def fake_http(url, key_env, model, prompt, system, timeout):
        cap.update(url=url, key_env=key_env, model=model)
        return "ok"

    monkeypatch.setattr(lp, "_http_chat", fake_http)
    assert lp.query_llm("hi") == "ok"
    assert cap["key_env"] is None                      # keyless: no Bearer at all
    assert cap["model"] == lp.LIFTWING_DEFAULT_MODEL
    # the model name appears in the URL path as well as the body
    assert cap["url"].endswith("/models/llm-qwen3-14b/openai/v1/chat/completions")
    assert cap["url"].startswith("https://api.wikimedia.org/")


def test_liftwing_model_override_flows_into_url(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "liftwing")
    monkeypatch.setenv("AGENT_LLM_MODEL", "llm-qwen36-27b")
    cap = {}
    monkeypatch.setattr(lp, "_http_chat",
                        lambda u, k, m, p, s, t: (cap.update(url=u, model=m), "ok")[1])
    lp.query_llm("hi")
    assert cap["model"] == "llm-qwen36-27b"
    assert "/models/llm-qwen36-27b/openai/" in cap["url"]


def test_strip_reasoning_removes_only_leading_think_block():
    assert lp.strip_reasoning("<think>weighing it</think>Answer: 42") == "Answer: 42"
    assert lp.strip_reasoning("  <think>a\nb</think>\n\nfinal") == "final"
    assert lp.strip_reasoning("plain answer") == "plain answer"
    # a later </think> is content, not a reasoning wrapper — don't eat the answer
    kept = lp.strip_reasoning("Answer mentions </think> inline")
    assert kept == "Answer mentions </think> inline"


def test_http_chat_sets_user_agent_and_omits_auth_when_keyless(monkeypatch):
    cap = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "<think>x</think>hi"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        cap["headers"] = dict(req.headers)
        return FakeResp()

    monkeypatch.setattr(lp.urllib.request, "urlopen", fake_urlopen)
    out = lp._http_chat("https://example.invalid/v1/chat", None, "m", "p", None, 10)
    assert out == "hi"                                   # reasoning block stripped
    hdrs = {k.lower(): v for k, v in cap["headers"].items()}
    assert "authorization" not in hdrs
    assert hdrs["user-agent"] == lp.USER_AGENT


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
