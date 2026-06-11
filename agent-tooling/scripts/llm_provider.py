#!/usr/bin/env python3
"""Provider-agnostic single-shot LLM call, selected by a GLOBAL env var.

The pipeline calls `query_llm(...)` and never names a provider. Which backend
runs is decided by one global variable, so you switch the whole machine's LLM
usage in one place:

    AGENT_LLM_PROVIDER = claude-code   (DEFAULT) — uses your Claude Code
                                        subscription via `claude -p`. No API key,
                                        no per-token billing.
                       = openrouter    — needs OPENROUTER_API_KEY
                       = mistral        — needs MISTRAL_API_KEY
    AGENT_LLM_MODEL    optional model override for the chosen provider.

For now we stay within the Claude Code subscription (the default). To move to a
paid API later, set AGENT_LLM_PROVIDER (e.g. export it in ~/.claude/settings env
or your shell) — nothing in the calling code changes.

  query_llm("Generate 3 search queries for: ...", system="You are a librarian")
"""
import json
import os
import subprocess
import sys
import urllib.request


def _provider() -> str:
    return os.environ.get("AGENT_LLM_PROVIDER", "claude-code").lower()


def _model(default: str | None = None) -> str | None:
    return os.environ.get("AGENT_LLM_MODEL") or default


def query_llm(prompt: str, system: str | None = None, *,
              model: str | None = None, timeout: int = 180) -> str:
    """Single-shot completion. Returns the model's text. Raises on failure."""
    p = _provider()
    if p == "claude-code":
        return _claude_code(prompt, system, _model(model), timeout)
    if p == "openrouter":
        return _http_chat("https://openrouter.ai/api/v1/chat/completions",
                          "OPENROUTER_API_KEY", _model(model) or "anthropic/claude-3.5-haiku",
                          prompt, system, timeout)
    if p == "mistral":
        return _http_chat("https://api.mistral.ai/v1/chat/completions",
                          "MISTRAL_API_KEY", _model(model) or "mistral-small-latest",
                          prompt, system, timeout)
    raise ValueError(f"unknown AGENT_LLM_PROVIDER: {p!r} (claude-code|openrouter|mistral)")


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
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise RuntimeError(
            f"claude -p failed ({r.returncode}): {(r.stderr or r.stdout).strip()[:300]}. "
            "If this is an auth error, confirm `claude -p \"hi\"` works in a plain "
            "terminal, or set AGENT_LLM_PROVIDER=openrouter|mistral.")
    return r.stdout.strip()


def _http_chat(url: str, key_env: str, model: str, prompt: str,
               system: str | None, timeout: int) -> str:
    key = os.environ.get(key_env)
    if not key:
        raise RuntimeError(f"{key_env} not set (required for AGENT_LLM_PROVIDER={_provider()})")
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    body = json.dumps({"model": model, "messages": msgs}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


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
