#!/usr/bin/env python3
"""PreToolUse guard: reduce ACCIDENTAL exposure of secret VALUES to the agent.

IMPORTANT — this is a best-effort TRIPWIRE, not a security boundary. A PreToolUse
hook sees only tool INPUT, so a determined or injected agent can still read a
secret many ways (python -c open, base64, `< file` redirection, printenv, the
Grep tool, MCP file tools, file:// fetch). Real confidentiality needs CONTAINMENT
(secrets outside the agent's env/filesystem reach) plus PostToolUse output
redaction — see the redesign note. This hook only nudges on an accidental read of
an UNAMBIGUOUS secret file or a secret-shaped env dump.

Narrowed after a security+AI panel (2026): match only path-ANCHORED secret shapes
on basename (no bare-word "secret" that blocked `grep secret` and this file's own
edit), an explicit secret-env allowlist (no bare *_KEY/*_TOKEN that blocked
PRIMARY_KEY/CSRF_TOKEN), never treat a grep/regex pattern as a path, and ASK
(let the human decide) rather than hard-deny (which trains route-arounds).
"""
import json
import os
import re
import sys

_ALLOW_SUFFIX = re.compile(r"\.(example|sample|template|dist)$", re.IGNORECASE)
# a token that could plausibly BE a path — no shell metachars, so a regex/glob
# pattern (contains | * $ ( ) < > or a "..." ellipsis) is never treated as one.
_PATHISH = re.compile(r"^[A-Za-z0-9._/~-]+$")

_ENV = re.compile(r"\.env(\.[\w-]+)?$", re.IGNORECASE)               # .env .env.local prod.env
_KEYFILE = re.compile(r"^(id_rsa|id_ed25519|id_dsa)(\.pub)?$", re.IGNORECASE)
_CERT_EXT = re.compile(r"\.(pem|p12|pfx|keystore)$", re.IGNORECASE)  # NOT .key (Keynote)
_SECRET_WORD = re.compile(r"secret|credential", re.IGNORECASE)
_DATA_EXT = re.compile(r"\.(txt|json|ya?ml|csv|tsv|env|cfg|conf|ini|toml|xml|log|bak)$",
                       re.IGNORECASE)  # data, not source (.py/.md/.sh stay editable)

# env vars whose VALUE is a secret — explicit tails only, no bare _KEY / _TOKEN
_SECRET_ENV = re.compile(
    r"\b(IA_ACCESS_KEY|IA_SECRET_KEY|OPENROUTER_API_KEY|ANTHROPIC_API_KEY|"
    r"CLAUDE_CODE_OAUTH_TOKEN|AWS_SECRET_ACCESS_KEY|"
    r"[A-Z][A-Z0-9_]*(?:_API_KEY|_SECRET_KEY|_PRIVATE_KEY|_ACCESS_KEY|_SECRET|"
    r"_PASSWORD|_PASSWD|_OAUTH_TOKEN|_ACCESS_TOKEN))\b")

_READ_VERB = re.compile(
    r"\b(cat|bat|less|more|head|tail|nl|xxd|od|strings|grep|egrep|rg|ag|awk|sed|"
    r"cp|rsync|scp|pbcopy|open|view|vi|vim|nano|emacs|code|base64|dd|tac|jq)\b")
_ENV_DUMP = re.compile(r"\b(printenv|env)\b")
_ECHO_VAR = re.compile(r"(echo|printf)\b[^|;&]*\$\{?\s*([A-Z][A-Z0-9_]*)\b")


def _is_secret_path(tok: str) -> bool:
    """True only for a plausible PATH whose basename is an unambiguous secret file."""
    if not tok or "..." in tok or "*" in tok or not _PATHISH.match(tok):
        return False
    base = os.path.basename(tok.rstrip("/"))
    if not base or _ALLOW_SUFFIX.search(base):
        return False
    if _ENV.search(base) or _KEYFILE.match(base) or _CERT_EXT.search(base):
        return True
    if "/.config/agent-secrets/" in tok:
        return True
    # a filename that both NAMES a secret and is a DATA file (my-secrets.txt,
    # credentials.json) — but NOT source code (block_secret_read.py stays editable)
    return bool(_SECRET_WORD.search(base) and _DATA_EXT.search(base))


def verdict(tool_name: str, tool_input: dict) -> str | None:
    """Reason string if this would expose a secret value, else None."""
    if tool_name in ("Read", "Edit", "NotebookEdit"):
        if _is_secret_path(str(tool_input.get("file_path", ""))):
            return ("That path is an unambiguous secret file; reading it would put its "
                    "values in the agent's context. Have a script load it from env / the "
                    "central secrets store instead (.env.example shows the structure).")
        return None
    if tool_name == "Bash":
        cmd = str(tool_input.get("command", ""))
        if _READ_VERB.search(cmd) and any(
                _is_secret_path(t) for t in re.split(r"[\s'\"=]+", cmd)):
            return ("This reads a secret file; its values would reach the agent. Let a "
                    "script read it from env / the central secrets store instead.")
        if _ENV_DUMP.search(cmd) and _SECRET_ENV.search(cmd):
            return "This dumps a secret-shaped env var; its value would be exposed."
        m = _ECHO_VAR.search(cmd)
        if m and _SECRET_ENV.search(m.group(2)):
            return "This echoes a secret env var; its value would be exposed."
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
            "permissionDecision": "ask",   # tripwire: let the human decide, don't hard-block
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
