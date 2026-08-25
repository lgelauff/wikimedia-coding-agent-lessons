---
name: wikimedia-enterprise
description: >-
  Get an access token for the Wikimedia Enterprise API (api.enterprise.wikimedia.com)
  and use it to call the On-demand, Snapshot, Realtime, or Metadata endpoints. Use
  whenever the user mentions "Wikimedia Enterprise", asks for a token/credentials for
  enterprise.wikimedia.com, or wants data (structured article content, project dumps,
  live update streams) from that API rather than the free MediaWiki/WDQS/AQS APIs.
---

# wikimedia-enterprise — Enterprise API auth + usage

Claude Code adapter over [`../../scripts/wikimedia_enterprise_auth.py`](../../scripts/wikimedia_enterprise_auth.py), an agent-agnostic script — it also runs standalone from any shell or CI job.

## Get an access token

```bash
python3 "$SKILL_DIR/../../scripts/wikimedia_enterprise_auth.py"
```

Prints a bearer token to stdout (status messages go to stderr, so it's safe to
capture directly, e.g. `TOKEN=$(python3 .../wikimedia_enterprise_auth.py)`).

**The password is never written to disk.** The refresh endpoint only needs
`username` + `refresh_token` — not the password — so a password is only needed
twice: the first login, and again whenever the cached refresh token expires or is
exhausted (every 90 days / 90 refreshes). Because that's rare, the script's default
is to prompt interactively (`getpass`, no echo) right there in the terminal rather
than persist the password anywhere. **Run it yourself in a terminal** when it needs
a fresh login — don't relay a password prompt through chat, and don't ask the user
to paste their password into the conversation.

For non-interactive use (cron/CI, no terminal attached), it'll also accept
`WIKIMEDIA_ENTERPRISE_USERNAME` / `WIKIMEDIA_ENTERPRISE_PASSWORD` from the
environment or the central secrets store (`scripts/agent_secrets.py` —
`~/.config/agent-secrets/.env` / `$AGENT_SECRETS_FILE`) — but that means the
password *does* sit at rest wherever you put it, so prefer the interactive prompt
for normal use and reserve env-var credentials for a real unattended job.

**Caching:** the script caches tokens (not the password) at
`~/.cache/wikimedia-enterprise/token.json` (override with
`WIKIMEDIA_ENTERPRISE_TOKEN_CACHE`), outside the repo. Ask the user before the first
run creates it. Access tokens last 24h; refresh tokens last 90 days and are good for
~90 silent refreshes (no password needed) — so the interactive login prompt only
comes up roughly every 90 days, not every call.

## Using the token

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://api.enterprise.wikimedia.com/v2/articles/Albert_Einstein
```

Base URL: `https://api.enterprise.wikimedia.com/v2/`. Main products (pick per task):

- **On-demand API** (`/v2/articles/{name}`) — query individual articles live,
  returning the raw HTML/text article — best fit for ad hoc lookups.
- **Structured Contents API** (`/v2/structured-contents/{name}`) — the same
  on-demand/snapshot split, but returns *parsed* JSON (infoboxes, sections,
  descriptions, tables, references) instead of raw HTML — prefer this over plain
  On-demand for anything measurement/analytics-oriented; verified live, returns
  `name`, `description`, `main_entity`, `additional_entities`, `infoboxes`,
  `sections`, `tables`, `references`, etc.
- **Snapshot API** — download full project dumps (`tar.gz` of NDJSON articles) for
  bulk/offline analysis; also available as Structured Contents snapshots.
- **Realtime API** — stream article updates, or pull hourly batch files, for
  near-live analytics.
- **Metadata API** — project codes, languages, namespaces (cheap; good for a smoke
  test, e.g. `GET /v2/codes` or `GET /v2/projects` need no body).

Consult `https://enterprise.wikimedia.com/docs/` for exact request/response shapes
per endpoint before building a query — don't guess field names.

## Access tiers

The free account tier (as of 2026-07-01) covers 50,000 On-demand requests/month, 30
Snapshot downloads/month, and Structured Contents Snapshots — often enough on its
own. If that's not enough:

- **Calls made from Wikimedia Cloud Services (PAWS/Toolforge/Cloud VPS) get
  paid-tier limits for free, automatically, with no `Authorization` header at all**
  — access is IP-granted there, not token-granted. Prefer routing a heavy workload
  through Cloud Services over paying, if it can run there.
- Otherwise, "exceptional access" (free paid-tier limits run elsewhere) can be
  requested from `techpartnerships@wikimedia.org` for mission-aligned/non-commercial
  use (academic research, non-profit work) — see
  [`wikimedia-analytics/lessons.md`](../../../wikimedia-analytics/lessons.md) for the
  full criteria.

## Don'ts

- Don't ask the user to type/paste their password in chat — have them run the script
  directly in their own terminal so `getpass` handles the prompt (not logged, not
  echoed, never seen by the conversation).
- Don't write username/password to any file yourself; the script only persists the
  resulting tokens, and only outside the repo.
- Don't add the password to the central secrets store as a matter of habit — it's
  needed so rarely that the interactive prompt is the better default; env-var storage
  is an opt-in for genuinely unattended jobs, not the normal path.
- Don't commit `~/.cache/wikimedia-enterprise/token.json`.
- Don't scrape enterprise.wikimedia.com or fall back to the free APIs to work around
  a credentials issue — if auth fails, surface the error and the fix.
