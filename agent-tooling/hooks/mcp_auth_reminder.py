#!/usr/bin/env python3
"""UserPromptSubmit hook: when a prompt links to an MCP server that needs auth,
surface the exact login command.

The failure this prevents: a user pastes a Jam recording link, the tool call
fails because the server was never authorized, and the agent reports "this needs
authorization and I can't run the OAuth flow" — true, useless, and a dead end.
The remedy (`claude mcp login <name>`) is one line in `claude mcp --help` that
nobody looks up mid-task.

So: only when the prompt actually contains a URL belonging to a configured MCP
server, check that server's auth status and, if it needs authenticating, inject
the command. No matching URL means no work and no output — this must not add
latency or noise to ordinary prompts.

Never blocks. Fails open on every error path: a broken reminder must not cost
the user a prompt.
"""
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

CLAUDE_JSON = os.path.expanduser("~/.claude.json")
URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def configured_servers(claude_json_path: str = CLAUDE_JSON) -> dict:
    """Map hostname -> server name for user-scoped HTTP/SSE MCP servers."""
    try:
        with open(claude_json_path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    out = {}
    for name, cfg in (data.get("mcpServers") or {}).items():
        url = (cfg or {}).get("url")
        if not url:
            continue
        host = urlparse(url).hostname or ""
        if not host:
            continue
        # mcp.jam.dev -> also match jam.dev, so a shared recording link
        # (jam.dev/c/xxxx) matches the server at mcp.jam.dev.
        out[host] = name
        parts = host.split(".")
        if len(parts) > 2:
            out[".".join(parts[-2:])] = name
    return out


def servers_mentioned(prompt: str, servers: dict) -> list[str]:
    """Which configured MCP servers does this prompt link to? Order-stable."""
    found: list[str] = []
    for url in URL_RE.findall(prompt or ""):
        host = (urlparse(url).hostname or "").lower()
        if not host:
            continue
        for candidate in (host, ".".join(host.split(".")[-2:])):
            name = servers.get(candidate)
            if name and name not in found:
                found.append(name)
    return found


def needs_auth(name: str) -> bool:
    """Ask the CLI. Only called when a URL actually matched, so the cost is rare."""
    try:
        proc = subprocess.run(
            ["claude", "mcp", "get", name],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "needs authentication" in (proc.stdout + proc.stderr).lower()


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return 0

    prompt = d.get("prompt") or ""
    if "http" not in prompt:            # cheapest possible early exit
        return 0

    try:
        pending = [n for n in servers_mentioned(prompt, configured_servers())
                   if needs_auth(n)]
    except Exception:                    # noqa: BLE001 — reminders never block
        return 0

    if not pending:
        return 0

    for name in pending:
        print(
            f"[mcp-auth] This prompt links to '{name}', whose MCP server is "
            f"configured but not authenticated, so the tool call will fail.\n"
            f"Tell the user to run:  claude mcp login {name}\n"
            f"(add --no-browser for SSH/headless; the grant is user-scoped, so "
            f"one login covers every repo, and a running session only picks it "
            f"up after a restart). Do not run the login flow on their behalf."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
