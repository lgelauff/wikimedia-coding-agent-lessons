#!/usr/bin/env python3
"""PreToolUse adapter: block WebFetch unless the URL is an approved route (host + path).

Thin Claude adapter. The decision lives in the agent-agnostic policy
`policies/webfetch_mandated.py` (the same executable the OpenCode plugin calls before
`webfetch`), which reads `settings/mandated-services.json`: hosts, host suffixes and
optional `paths` allow/deny rules. This file's only job: read Claude's PreToolUse event,
pull out the URL, ask the policy, and translate a block into Claude's format (stderr +
exit 2), so one registry governs both harnesses.

Failure modes, chosen deliberately:
- unparseable event: fail CLOSED (block). An event we cannot read might carry any URL.
- registry unreadable: allow with a warning, as the policy's own contract says; an
  infrastructure fault must not take out the tool. The permission prompt stays the backstop.
Scope: the WebFetch tool only. Fetches through Bash (curl) are not covered here.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "policies"))
from webfetch_mandated import decide, load_registry  # noqa: E402


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.stderr.write("BLOCKED: WebFetch registry gate could not parse the hook input; "
                         "failing closed. Retry so the gate can inspect the URL.\n")
        return 2
    if event.get("tool_name") != "WebFetch":
        return 0
    url = str((event.get("tool_input") or {}).get("url", ""))
    registry = load_registry()
    if registry is None:
        sys.stderr.write("WARN: mandated-services registry unreadable; WebFetch allowed "
                         "(the permission prompt remains the backstop).\n")
        return 0
    reason = decide(url, registry)
    if reason:
        sys.stderr.write(reason + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
