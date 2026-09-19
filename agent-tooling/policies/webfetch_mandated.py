#!/usr/bin/env python3
"""Policy: is a `webfetch` URL's host in the Mandated Services Registry?

Agent-agnostic decision executable — knows nothing about any agent's event format. The
fact it judges is a single URL string. The registry it reads is the one allow-list in
`settings/mandated-services.json`, itself checked against the `source-connectors`
connector library by `scripts/mandated_services.py`.

OpenCode 1.18.30 types `webfetch` as Action only (ask|allow|deny), so a config domain
map is impossible; this policy is the enforcement, wired into the plugin's
`tool.execute.before` for `webfetch`. A host not in the registry is denied with an
explicit-request message (what was tried, why, blast radius) — not a one-click prompt.

  webfetch_mandated.py https://api.openalex.org/works   -> exit 0 (allow)
  webfetch_mandated.py https://example.com/             -> prints reason, exit 1 (block)

Contract: exit 0 = allow, exit 1 = block, with a neutral human-readable reason on
stdout. If the registry cannot be read at all, this exits 0 (allow) with a warning on
stderr: an unreadable registry is an infrastructure failure, not a policy decision, and
the config's `webfetch: "ask"` remains the backstop. Failing closed here would take out
the tool on a missing file, which is the failure mode the adapter is written to avoid.

Matching: case-insensitive, trailing dot ignored; exact hosts first, then
`host_suffixes` (a leading dot matches the apex and any subdomain, never a lookalike).
IP literals, localhost, and non-http(s) schemes are never mandated.

Limits, stated rather than hidden: this judges the **requested** host only. A mandated
host that redirects to an unlisted one is not re-checked — `tool.execute.before` cannot
see the redirect target. The registry's `$comment` carries the same caveat.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
import urllib.parse
from pathlib import Path

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "settings" / "mandated-services.json"

REQUEST_TEMPLATE = (
    "BLOCKED: `{host}` is not in the Mandated Services Registry "
    "(agent-tooling/settings/mandated-services.json). webfetch is restricted to declared "
    "sources. To request an exception, write to the human — do not retry, do not route "
    "around it. State: (1) the exact URL and what you tried first (source_fetch, or the "
    "connector for this source); (2) why the mandated sources cannot serve it; (3) the "
    "blast radius — what data leaves, to which host, under which licence/ToS. If the "
    "source is legitimate and durable, add a connector to source-connectors first."
)


def load_registry(path: Path | None = None) -> dict | None:
    p = path or Path(os.environ.get("MANDATED_SERVICES_PATH", DEFAULT_REGISTRY))
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalise_host(url: str) -> str | None:
    # Parser-differential guard. A WHATWG fetcher (what actually leaves) treats `\`
    # as a path separator in special schemes, while Python's urllib treats it as an
    # ordinary userinfo character — so `https://evil.com\@allowed/` resolves to
    # `allowed` here and to `evil.com` in the fetcher. Reject the ambiguity outright;
    # no mandated endpoint contains a backslash.
    if "\\" in url or "%5c" in url.lower():
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    return host or None


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def decide(url: str, registry: dict) -> str | None:
    """Return a block reason for `url`, or None to allow. Pure."""
    host = _normalise_host(url or "")
    if host is None:
        return (
            "BLOCKED: webfetch URL is not an http(s) URL with a host "
            f"({url!r}). The Mandated Services Registry lists http(s) endpoints only."
        )
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")) \
            or _is_ip_literal(host):
        return REQUEST_TEMPLATE.format(host=host)

    hosts: set[str] = set()
    suffixes: set[str] = set()
    for svc in registry.get("services", []):
        hosts.update(str(h).lower() for h in svc.get("hosts", []))
        hosts.update(str(h).lower() for h in svc.get("auxiliary_hosts", []))
        suffixes.update(str(s).lower() for s in svc.get("host_suffixes", []))

    if host in hosts:
        return None
    for suffix in suffixes:
        if suffix.startswith(".") and (host == suffix[1:] or host.endswith(suffix)):
            return None
    return REQUEST_TEMPLATE.format(host=host)


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()
    registry = load_registry()
    if registry is None:
        print("WARN: mandated-services registry unreadable; allowing (webfetch still asks)",
              file=sys.stderr)
        return 0
    reason = decide(url, registry)
    if reason:
        print(reason)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
