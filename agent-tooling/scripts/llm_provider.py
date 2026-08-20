#!/usr/bin/env python3
"""Provider-agnostic single-shot LLM call, selected by a GLOBAL env var.

The pipeline calls `query_llm(...)` and never names a provider. Which backend
runs is decided by one global variable, so you switch the whole machine's LLM
usage in one place:

    AGENT_LLM_PROVIDER = claude-code   (DEFAULT) — uses your Claude Code
                                        subscription via `claude -p`. No API key,
                                        no per-token billing.
                       = liftwing      — Wikimedia LiftWing open-weight models.
                                        No API key. Free. WMF-hosted, so wiki
                                        content stays on Wikimedia infra.
                       = openrouter    — needs OPENROUTER_API_KEY
                       = mistral        — needs MISTRAL_API_KEY
    AGENT_LLM_MODEL    optional model override for the chosen provider.

For now we stay within the Claude Code subscription (the default). To move to a
paid API later, set AGENT_LLM_PROVIDER (e.g. export it in ~/.claude/settings env
or your shell) — nothing in the calling code changes.

LiftWing notes (https://wikitech.wikimedia.org/wiki/Machine_Learning/LiftWing/
Large_Language_Models/Wikimania_2026 — page is a DRAFT; endpoint may move):
  * Models: llm-qwen3-14b (16K ctx, default), llm-qwen36-27b (32K ctx).
  * OpenAI-compatible chat-completions; the model name goes in BOTH the URL
    path and the request body.
  * **100 requests/hour anonymously** — a hard floor, not a soft limit: 1k
    items ≈ 10h minimum. Bulk work over the anonymous endpoint is an
    overnight-run by arithmetic (see playbooks/budget-estimate.md). The
    unlimited tier requires running FROM Toolforge (tool account + Jobs
    framework), which is a user-action request — SSH is human-only here.
  * No tool/function calling, no JSON mode: structured output must be prompted
    and then validated by the caller. Responses may open with a
    <think>…</think> reasoning block, which this module strips.

  query_llm("Generate 3 search queries for: ...", system="You are a librarian")
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Per the project's web-access rules, every HTTP request identifies itself.
USER_AGENT = os.environ.get(
    "AGENT_LLM_USER_AGENT",
    "WikimediaAnalysis/1.0 (personal research project; "
    "https://github.com/lgelauff/wikimedia-analysis)")

LIFTWING_BASE = ("https://api.wikimedia.org/service/lw/inference/v1/models/"
                 "{model}/openai/v1/chat/completions")
LIFTWING_DEFAULT_MODEL = "llm-qwen3-14b"

_THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Drop a leading <think>…</think> block (LiftWing Qwen models emit one).

    Pure + exported so callers that stream or post-process elsewhere can reuse
    it. Only strips a LEADING block: a </think> appearing later is content.
    """
    return _THINK_RE.sub("", text).strip()


def _provider() -> str:
    return os.environ.get("AGENT_LLM_PROVIDER", "claude-code").lower()


def _model(default: str | None = None) -> str | None:
    return os.environ.get("AGENT_LLM_MODEL") or default


def _dispatch(prompt: str, system: str | None, model: str | None, timeout: int) -> str:
    p = _provider()
    if p == "claude-code":
        return _claude_code(prompt, system, _model(model), timeout)
    if p == "liftwing":
        m = _model(model) or LIFTWING_DEFAULT_MODEL
        # Cross-session rate budget: concurrent sessions share one 100/h quota
        # and cannot see each other, so every call passes the file-backed
        # token bucket. AGENT_RATE_WAIT=1 paces instead of failing (scripted /
        # overnight callers); interactive callers fail fast on purpose.
        budget = _liftwing_budget()
        if budget is not None:
            budget.acquire(model=m, wait=os.environ.get("AGENT_RATE_WAIT") == "1")
        # The model name is part of the URL path AND the body for this service.
        return _http_chat(LIFTWING_BASE.format(model=m), None, m,
                          prompt, system, timeout, budget=budget)
    if p == "openrouter":
        return _http_chat("https://openrouter.ai/api/v1/chat/completions",
                          "OPENROUTER_API_KEY", _model(model) or "anthropic/claude-3.5-haiku",
                          prompt, system, timeout)
    if p == "mistral":
        return _http_chat("https://api.mistral.ai/v1/chat/completions",
                          "MISTRAL_API_KEY", _model(model) or "mistral-small-latest",
                          prompt, system, timeout)
    raise ValueError(
        f"unknown AGENT_LLM_PROVIDER: {p!r} (claude-code|liftwing|openrouter|mistral)")


def query_llm(prompt: str, system: str | None = None, *,
              model: str | None = None, timeout: int = 180, retries: int = 2) -> str:
    """Single-shot completion. Returns the model's text. Raises on failure.

    Bounded retry with exponential backoff so a transient rate-limit/5xx wall
    doesn't turn into a silent batch-wide failure at the caller. A ValueError
    (bad provider config) is not retried — it won't fix itself.
    """
    last = None
    for attempt in range(retries + 1):
        try:
            return _dispatch(prompt, system, model, timeout)
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001 — network/CLI/rate-limit, worth a retry
            # A budget refusal is a deliberate decision, not a transient fault:
            # retrying it just burns the backoff and reports the same answer.
            if type(e).__name__ == "RateBudgetExceeded":
                raise
            last = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"query_llm failed after {retries + 1} attempts: {last}")


def _claude_code(prompt: str, system: str | None, model: str | None, timeout: int) -> str:
    """Use the Claude Code subscription via the headless CLI (no API key).

    Runs with a clean env: an outer Claude Code session injects
    ANTHROPIC_BASE_URL (an internal gateway) and may set ANTHROPIC_API_KEY —
    both misroute a spawned `claude -p`, which must use the stored subscription
    OAuth against the real endpoint. We strip them so this works whether invoked
    standalone (a terminal/cron) or nested inside another session.
    """
    cmd = ["claude", "-p", prompt, "--output-format", "text"]
    if system:
        cmd += ["--append-system-prompt", system]
    if model:
        cmd += ["--model", model]
    # Scrub anything that would misroute the spawned CLI off the subscription
    # OAuth: an outer session injects ANTHROPIC_BASE_URL/API_KEY; bedrock/vertex/
    # proxy routing vars would redirect or exfil. Strip by prefix; KEEP
    # CLAUDE_CODE_OAUTH_TOKEN (the subscription token, not an ANTHROPIC_* name).
    _STRIP_PREFIXES = ("ANTHROPIC_", "AWS_", "CLAUDE_CODE_USE_")
    _STRIP_EXACT = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
                    "https_proxy", "all_proxy", "NO_PROXY"}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(_STRIP_PREFIXES) and k not in _STRIP_EXACT}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(
            f"claude -p failed ({r.returncode}): {(r.stderr or r.stdout).strip()[:300]}. "
            "If this is an auth error, confirm `claude -p \"hi\"` works in a plain "
            "terminal, or set AGENT_LLM_PROVIDER=openrouter|mistral.")
    return r.stdout.strip()


def _liftwing_budget():
    """The shared LiftWing rate budget, or None if disabled/unavailable.

    AGENT_RATE_DISABLE=1 turns it off (single-session bulk work that is being
    metered some other way, e.g. running from Toolforge where the cap lifts).
    """
    if os.environ.get("AGENT_RATE_DISABLE") == "1":
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from rate_budget import RateBudget          # local module, same dir
    return RateBudget("liftwing")


def _http_chat(url: str, key_env: str | None, model: str, prompt: str,
               system: str | None, timeout: int, budget=None) -> str:
    """POST an OpenAI-shaped chat completion.

    `key_env` is None for keyless services (LiftWing's public endpoint), in
    which case no Authorization header is sent at all — an empty Bearer is
    worse than none.
    """
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if key_env is not None:
        # env first, then the central secrets store — otherwise a key that IS
        # configured in ~/.config/agent-secrets/.env reads as "not set" in any
        # shell that has not exported it, which is most of them.
        key = os.environ.get(key_env)
        if not key:
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from secrets import get_secret  # local module, same dir
                key = get_secret(key_env)
            except Exception:  # noqa: BLE001 — absent store is not an error here
                key = None
        if not key:
            raise RuntimeError(f"{key_env} not set (required for AGENT_LLM_PROVIDER={_provider()})")
        headers["Authorization"] = f"Bearer {key}"
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": msgs}).encode()
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # 429 is expected on a shared quota, not exceptional: honour
        # Retry-After rather than letting the generic retry hammer the wall,
        # and record it — the ledger is the evidence for tuning the bucket.
        if e.code == 429:
            try:
                wait = float(e.headers.get("Retry-After") or 30)
            except (TypeError, ValueError):
                wait = 30.0
            if budget is not None:
                budget.record("429", model=model, retry_after=wait)
            time.sleep(min(wait, 120.0))
            raise RuntimeError(
                f"rate limited (429) by {url.split('/')[2]}; waited {min(wait, 120.0):.0f}s. "
                "The anonymous pool is shared — for bulk work run from Toolforge.") from e
        if budget is not None:
            budget.record("error", model=model, status=e.code)
        raise
    try:
        return strip_reasoning(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected LLM response shape: {str(data)[:200]}") from e


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="One-shot LLM call via AGENT_LLM_PROVIDER.")
    ap.add_argument("prompt", nargs="?", help="prompt (or read stdin)")
    ap.add_argument("--system")
    ap.add_argument("--model")
    a = ap.parse_args()
    prompt = a.prompt or sys.stdin.read()
    print(query_llm(prompt, a.system, model=a.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
