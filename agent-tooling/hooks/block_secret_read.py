#!/usr/bin/env python3
"""PreToolUse guard: stop the agent from reading secret VALUES.

Scripts should read keys themselves (env / central secrets file); the agent that
invokes them must never see the values. This denies the obvious ways an agent
would surface a secret:
  - Read tool on a real secret file (.env, *secrets*, *.pem, id_rsa, the central
    agent-secrets store) — but NOT .env.example/.sample/.template.
  - Bash that cats/greps/copies such a file, or dumps a secret-shaped env var
    (printenv/echo $X_KEY|$X_SECRET|$X_TOKEN, IA_ACCESS_KEY, OPENROUTER_API_KEY…).

Fails OPEN on a bad event; denies (not just asks) so the agent self-corrects.
Decision logic is the pure `verdict()` for testability.
"""
import json
import os
import re
import sys

_ALLOW = re.compile(r"\.(example|sample|template|dist)$|example", re.IGNORECASE)
_SECRET_PATH = re.compile(
    r"(^|/)\.env(\.[\w.-]+)?$"            # .env, .env.local, .env.production
    r"|secret|credential"                 # *secrets*, credentials
    r"|/\.config/agent-secrets/"          # the central store
    r"|(^|/)\.?(id_rsa|id_ed25519|id_dsa)\b"
    r"|\.(pem|key|p12|pfx|keystore)$",
    re.IGNORECASE)
_READ_VERB = re.compile(
    r"\b(cat|bat|less|more|head|tail|nl|xxd|od|strings|grep|egrep|rg|ag|awk|sed|"
    r"cp|rsync|scp|pbcopy|open|view|vi|vim|nano|emacs|code)\b")
_SECRET_ENV = re.compile(
    r"\b(IA_ACCESS_KEY|IA_SECRET_KEY|OPENROUTER_API_KEY|ANTHROPIC_API_KEY|"
    r"[A-Z][A-Z0-9_]*(?:_KEY|_SECRET|_TOKEN|_PASSWORD|_PASSWD))\b")
_ENV_DUMP = re.compile(r"\b(printenv|env)\b")
_ECHO_VAR = re.compile(r"(echo|printf)\b[^|;&]*\$\{?\s*([A-Z][A-Z0-9_]*)\b")


def _is_secret_path(p: str) -> bool:
    return bool(p) and bool(_SECRET_PATH.search(p)) and not _ALLOW.search(os.path.basename(p))


def verdict(tool_name: str, tool_input: dict) -> str | None:
    """Return a deny-reason if this would expose a secret, else None."""
    if tool_name in ("Read", "Edit", "NotebookEdit"):
        if _is_secret_path(str(tool_input.get("file_path", ""))):
            return ("Reading a secret file would expose its values to the agent. "
                    "Don't read it — have the script load it itself (env / central "
                    "secrets file). Use .env.example for structure.")
        return None
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        # a read utility touching a secret-ish path
        if _READ_VERB.search(cmd) and any(_is_secret_path(tok)
                                          for tok in re.split(r"[\s'\"=]+", cmd)):
            return ("This command reads a secret file; its values would reach the "
                    "agent. Let the script read it from env / the central secrets file.")
        # dumping secret-shaped env vars
        if _ENV_DUMP.search(cmd) and _SECRET_ENV.search(cmd):
            return "Dumping secret env vars would expose their values — don't."
        m = _ECHO_VAR.search(cmd)
        if m and _SECRET_ENV.search(m.group(2)):
            return "Echoing a secret env var would expose its value — don't."
    return None


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        return 0
    reason = verdict(d.get("tool_name", ""), d.get("tool_input", {}) or {})
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
