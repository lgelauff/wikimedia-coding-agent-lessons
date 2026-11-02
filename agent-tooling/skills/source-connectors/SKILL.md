---
name: source-connectors
description: >-
  Collects data from specific web sources (government portals, catalogues, archives,
  scholarly indexes) through declared connectors instead of scraping pages. Use whenever a
  task needs data FROM such a source, a page looks scrapeable, robots.txt or a 403 seems to
  block access, or a fetch tool refuses a host and the Internet Archive route is needed. A
  connector records protocol and endpoint, auth, access policy (robots, ToS, rate, fair
  use), reuse licence and the retrieval recipe, so every fetch uses the host's intended,
  lowest-impact door, politely and cached. Covers API discovery, robots.txt as access
  policy, and recurring gotchas (HTTP 200 with an error body, open-access links that 403
  non-browser clients). Ships a dated connector library. Not for LLM or compute endpoints
  such as LiftWing: see the liftwing-llm playbook.
---

# source-connectors — model each source as a connector, then collect through it

**The idea.** Don't ask "how do I fetch this page" — ask "what is the *connector* for this
source". A **connector** is a small, reusable declaration of one source:

> `source · protocol & endpoint · auth · access policy (robots / ToS / rate / fair-use) · reuse licence · retrieval recipe`

Define it once (the library below holds real examples) and every later fetch is just "use
connector X". That turns ad-hoc scraping into a legible, auditable, reusable layer — and the
same connector powers a one-off lookup or a bulk pass.

Above all it makes you a **good neighbour**. The receiving end is someone's infrastructure,
and their cost, not yours. An API is the host's *own* preferred, lowest-load door: modelling a
source as a connector means you knock on that door — at the intended rate, once — instead of
crawling the whole house. Every part below is, at bottom, about minimizing the burden your
query places on the other end.

## The concept has four parts

A mature connector practice is really four separable concerns. This skill covers all four,
and any can be lifted out on its own (most usefully **the library**, into its own data file):

1. **Govern & enforce** — decide *which* connectors are allowed and how strictly. *The policy.*
2. **Discover & onboard** — figure out the connector for a new source and verify it. *Finding
   the preferred approach.*
3. **Maintain & track** — keep the registry current and provenance-stamped. *Keeping the
   preferred approach.*
4. **The library** — the concrete registry of known connectors. **Drift-prone: every entry is
   dated per item** and treated as possibly-stale until re-checked.

## 1. Govern & enforce — how strict is the registry?

The connector *concept* is identical however a project governs it; only the "may I fetch
this?" gate changes:

- **Sanctioned** — a hard allow-list. Only listed connectors may be used; an unlisted source
  is flagged as a gap, never fetched silently. Strongest containment.
- **Preferred** — a soft steer. Prefer listed connectors; other sources are allowed but
  flagged and recorded. Pragmatic default.
- **Reference** — a shared registry of how each source works, with no enforcement.

Everything below applies to all three.

## 2. Discover & onboard a connector

1. **Find the API the source actually offers.** Check `/developer`, `/api`, an "open data /
   hergebruik" page, and any `Sitemap:` in `robots.txt`. Recognise the standard — **SRU,
   OAI-PMH, REST/OpenAPI, OData, SPARQL, IIIF** — and let it describe itself: SRU
   `?operation=explain&version=2.0` (indexes), OpenAPI `/openapi.json` or `…/ui`, OData
   `/$metadata`. A community "downloader" repo often documents the endpoint, filters, page
   size and fair-use — reuse it.
2. **Read robots.txt / ToS as the access policy** (see *Access-policy patterns*): the
   `Sitemap:`, the disallowed content paths, and the posture toward bots. The access policy is
   *part of* the connector, not an afterthought.
3. **Verify the retrieval path, then write the entry.** Confirm the endpoint returns the real
   artifact, and record the connector: `endpoint · auth · access policy · rate/fair-use ·
   reuse licence · retrieval recipe (+ id scheme) · date verified`.

## 3. Use & maintain

**Use it politely.**
- Descriptive `User-Agent` with a contact (Wikimedia *blocks* generic/absent UAs), one request
  at a time per host (~1 req/s), honour `Retry-After` with exponential backoff on `429`/`503`,
  `Accept-Encoding: gzip`. Authenticate only to raise limits, never to unlock a write path;
  read tokens from the environment and degrade to unauthenticated rather than fail.
- **Retries spend the same budget.** A connector row's daily cap or request budget counts every
  request sent, retries and re-runs after a kill included. Long jobs are chunked with
  checksummed done markers, so a resumed run skips finished chunks instead of re-fetching them
  (Lodewijk, 2026-10-24).
- **Get the artifact, not the announcement.** Prefer the canonical, versioned path the record
  points to (e.g. an FRBR/XML manifestation) over the front-end, which can 504. Structured
  XML/JSON over HTML; `pdftotext` for PDFs (skip binary-only scans → OCR). Follow an
  `extref`/attachment when the record is a thin announcement.
- **The Internet Archive is always a permitted route** (Lodewijk, 2026-10-05), including for
  hosts whose robots.txt blocks AI crawlers or your client: fetching an archived capture is how
  we honour a live host's block, not a way around it. `archive.org/wayback/available?url=<enc>`
  for coverage; `web.archive.org/web/<ts>id_/<url>` for the raw snapshot; project UA, polite
  pacing (~1 req/s, back off on 429/`Retry-After`), cache every capture; `curl` + your UA if the
  fetch tool refuses `web.archive.org`. It does not get you past a login, a paywall or licence
  terms: those still apply to the content.
- **Documentation is always readable** (Lodewijk, 2026-10-16): API docs, terms/licence pages,
  `robots.txt` and robot/bot-policy pages may be fetched directly on any host, with the project
  UA and ~1 req/s; doc paths the host's robots file disallows go through the Internet Archive.
  This covers reading about a source, not calling its API or downloading its data: for a host
  that is not yet approved, use `route-vetting`.
- **A `5xx`/`503` is transient, not a verdict.** Try the connector first; on `503`/`5xx` (maintenance or load) retry with backoff, and if it persists switch to the row's **Fallback** — don't downgrade a connector's dated status for a one-off blip (reserve a status change for a *persistent* failure).

**Maintain the registry — it goes stale.**
- Record provenance per fetch: source + exact endpoint, access method, a content hash (sha256),
  the fetch date, a stable id. A one-line append-only log + a catalogue of what you hold makes
  the collection auditable and re-runnable.
- Treat the library as living: **stamp each entry with its own last-verified date**, re-check on
  use, and mark an entry *stale* rather than trusting an old cell. Access policies (robots,
  rate, auth, licence) change without notice — a dated entry is a claim, not a guarantee.

## Access-policy patterns you'll meet again

- **robots.txt disallows crawlers, but the publisher documents & prefers the API.**
  robots.txt is written for search crawlers, not API clients. Treat the documented,
  publisher-sanctioned endpoint as usable, hit **only** that path, stay within stated
  fair-use, log it — and when in doubt ask the human whose project it is.
- **Named-AI-bot blocks ≠ a block on you.** A host may `Disallow: /` for `GPTBot`,
  `ClaudeBot`, `CCBot`, `Google-Extended`… under a permissive `User-agent: *` catch-all.
  Read the file: if your client isn't named, the catch-all governs — but honour the evident
  intent: when a host clearly does not want AI ingestion, use a sanctioned channel or fetch
  the Internet Archive's captures (always permitted, see above) instead of the live site.
- **No public *read* API — retrieve via the sibling service.** Some portals expose only a
  *submission* API; the readable data lives in a companion register (see open.overheid.nl → KOOP).
- **Native API disabled, public sibling open.** A host can `401` its own `/wp-json/…` while a
  public sibling (`public-api.wordpress.com/…/sites/<domain>/…`) serves the same content
  unauthenticated. Check the public sibling before concluding an API is closed.
- **HTTP 200 with an error body.** Some APIs return `200` with an error payload under load —
  inspect the body, not the status.
- **Your fetch tool's 403 is not the site's policy.** A hosted fetcher can be refused by a
  WAF while the same URL returns `200` to `curl` with a descriptive UA — including
  `/robots.txt` itself, which makes the policy look unreadable and invites the wrong
  conclusion that the host blocks automation. Before declaring a source hostile, retry with
  `curl` and your own UA. Observed on `deliberation.stanford.edu`: WebFetch `403`, curl `200`,
  and a robots.txt that names no AI bot at all.
- **Open-access links that 403 non-browser clients.** A DOI's "open" PDF often sits behind a
  publisher/Cloudflare gate that `403`s `curl` — fall back to DOI/metadata lookup or a human fetch.
- **Front-end flaky, artifact path stable.** The user-facing page 504s while the canonical
  manifestation returns 200 — always take the URL the API record gives you.
- **`explain` / `$metadata` first.** The same standard uses different index/field names per
  deployment; discover them, don't guess.

## 4. The library — example connectors (dated per item)

The registry of real connectors is in [references/library.md](references/library.md):
Dutch government and open data, scholarly and archive, deliberation research, Wikimedia
community infrastructure (Phabricator, read-only posture), media and web. **Read the row
for your source before fetching.** Each row carries its own `Verified` date and a
**Fallback**; a dated row is a claim, not a guarantee.

## Kept out of the library

The library holds *specific* connectors. Three kinds of thing are deliberately excluded:

- **General lessons, not sources** — e.g. "open-access PDF links often `403` non-browser
  clients, fall back to a DOI/metadata lookup". Those live in *Access-policy patterns* above,
  not as a row.
- **Categorical APIs with their own skill** — Wikimedia's own data APIs (MediaWiki Action,
  Wikidata SPARQL, Analytics) are excellent but *categorical* (any wiki / the whole graph)
  and already covered by the `wikimedia-data-collection` skills. **Phabricator used to sit
  in this list and no longer does:** unlike the others it is a social space with a Code of
  Conduct, an etiquette policy and a hard write prohibition, and those constraints have to
  travel with the source rather than live in a data-collection recipe. `phabricator-conduit`
  still owns the *authenticated* Conduit query patterns; the row above owns the access
  policy, the read-only posture and the unauthenticated read paths.
- **Compute, not collection** — LLM inference endpoints (e.g. **LiftWing** on
  `api.wikimedia.org`, ~100 req/hour anonymous, no tool-calling / JSON mode) use the same
  connector *model* but you send work rather than collect data → see the `liftwing-llm`
  playbook (`agent-tooling/playbooks/liftwing-llm.md`).
