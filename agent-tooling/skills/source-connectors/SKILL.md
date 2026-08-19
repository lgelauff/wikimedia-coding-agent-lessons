---
name: source-connectors
description: >-
  Model every data source you collect from as a **connector** — a small, reusable
  declaration of one source: protocol & endpoint, auth, access policy (robots /
  ToS / rate / fair-use), reuse licence, and the retrieval recipe that gets the
  full artifact out. Use whenever a task needs data FROM specific web sources (a
  government portal, catalogue, archive, scholarly index) and you're tempted to
  scrape pages. It is fundamentally about being a **good neighbour** — minimizing
  load and invasiveness for the host by using its intended, lowest-impact door,
  calling it politely, and caching what you fetch. A mature connector practice has
  four separable parts — **govern &
  enforce** (sanctioned allow-list / preferred set / plain reference), **discover
  & onboard** (find the API and its access policy, verify the retrieval path),
  **maintain & track** (provenance; re-verify; date and retire entries), and **the
  library** of known connectors (drift-prone — every entry dated per item). Covers
  API discovery (developer docs / SRU `explain` / `$metadata` / community tools),
  reading robots.txt as the access policy (including hosts that disallow crawlers
  while documenting and PREFERRING their API), polite calling (descriptive UA,
  rate-limit / fair-use, canonical artifact vs flaky front-end, Internet-Archive
  fallback), and the recurring gotchas (HTTP 200 + error body, open-access links
  that 403 non-browser agents, named-AI-bot robots blocks). Ships a dated registry
  of real connectors (Dutch government — KOOP officiële bekendmakingen, CVDR,
  wetten.overheid.nl, data.overheid.nl, CBS, Rechtspraak; scholarly & archive —
  OpenAlex, Crossref, Internet Archive, MediaWiki). LLM / compute connectors such
  as LiftWing are a sibling category (same model, but you send work rather than
  collect data) — kept out of this skill; see `liftwing-llm`.
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
- **Get the artifact, not the announcement.** Prefer the canonical, versioned path the record
  points to (e.g. an FRBR/XML manifestation) over the front-end, which can 504. Structured
  XML/JSON over HTML; `pdftotext` for PDFs (skip binary-only scans → OCR). Follow an
  `extref`/attachment when the record is a thin announcement.
- **Fall back to the Internet Archive when a live fetch is blocked.**
  `archive.org/wayback/available?url=<enc>` for coverage; `web.archive.org/web/<ts>id_/<url>`
  for the raw snapshot; `curl` + your UA if the fetch tool refuses `web.archive.org`. A
  fallback, not a way around a clear "no".

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
  intent, and prefer a sanctioned channel or the Internet Archive when a host clearly does
  not want AI ingestion.
- **No public *read* API — retrieve via the sibling service.** Some portals expose only a
  *submission* API; the readable data lives in a companion register (see open.overheid.nl → KOOP).
- **HTTP 200 with an error body.** Some APIs return `200` with an error payload under load —
  inspect the body, not the status.
- **Open-access links that 403 non-browser clients.** A DOI's "open" PDF often sits behind a
  publisher/Cloudflare gate that `403`s `curl` — fall back to DOI/metadata lookup or a human fetch.
- **Front-end flaky, artifact path stable.** The user-facing page 504s while the canonical
  manifestation returns 200 — always take the URL the API record gives you.
- **`explain` / `$metadata` first.** The same standard uses different index/field names per
  deployment; discover them, don't guess.

## 4. The library — example connectors (dated per item)

Each row is a connector, and **carries its own `Verified` date** — a dated claim, not a
guarantee. Re-check `explain`/robots before relying on a cell. The **Fallback** column is what
to reach for when *this* connector is down, blocked, or throttled. `(live)` = the
endpoint/robots were exercised; `(docs)` = read from documentation/robots only. "free (art. 11)"
= Dutch *Auteurswet* art. 11: no copyright on laws/decisions/ordinances of a public authority.

### Dutch government / open data

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **KOOP Officiële Bekendmakingen** | SRU 2.0 · `repository.overheid.nl/sru` | none | crawler `Disallow: /` — API **documented & preferred**; ~1 req/s, page 1000 | free (art. 11); `/noindex/` = privacy | `explain` → indexes; FRBR `…/frbr/…/xml/…` = artifact; front-end `zoek.officielebekendmakingen.nl` can 504 | Internet Archive (permanent deeplinks) | 2026-08-14 (live) |
| **CVDR** (decentrale regelgeving) | SRU / FRBR · `lokaleregelgeving.overheid.nl` | none | server page open; polite | free (art. 11) | FRBR-XML may 404 → server-rendered page; SRU indexes differ from KOOP | KOOP bekendmakingen; IA | 2026-08-17 (live) |
| **wetten.overheid.nl** (BWB, consolidated law) | HTML/XML · `wetten.overheid.nl` | none | catch-all `Allow: /`; **named AI bots** `Disallow: /`; `/*/informatie/xml` off; polite | free (art. 11) | honour the AI-block intent | BWB bulk download; Internet Archive | 2026-08-15 (live robots) |
| **open.overheid.nl / OPP** (PLOOI successor) | *aanlever only* | (client creds) | — | Woo / free | **no public read API** | KOOP (the read path) | 2026-08-13 (docs) |
| **data.overheid.nl** | CKAN v3 · `data.overheid.nl/data/api/3/action/` | none | `Disallow: /data/` (covers the API path); polite | CC0 | dataset / metadata discovery | the dataset's own host | 2026-08-13 (docs) |
| **CBS StatLine** | OData · v3 `opendata.cbs.nl/ODataApi`; v4 host *(unverified)* | none | v3 paths disallowed; v4 TBD; polite | free + attrib "Bron: CBS" | prefer v4; `$metadata` for fields | `cbsodata` client libs (R/Py) | 2026-08-13 (docs) |
| **Rechtspraak Open Data** | REST/XML · `data.rechtspraak.nl/uitspraken/` | none | no robots served (allow); ≤10 req/s, no full dump | court output, pseudonymised | 2-step: ECLI index → content | Internet Archive snapshot | 2026-08-13 (docs) |

### Scholarly & archive

| Connector | Protocol · endpoint | Auth | Access policy | Reuse | Notes | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **OpenAlex** | REST · `api.openalex.org` | free key (credit budget) | polite pool via `mailto` | CC0 metadata | **200 + error body** under load; prefer DOI/filter over `?search` | Crossref (metadata); Unpaywall (OA copies) | 2026-08-14 (live) |
| **Crossref** | REST · `api.crossref.org` | none (mailto polite pool) | polite | metadata open | DOI metadata; `query.*` filters; send `mailto` for the polite pool | OpenAlex; DataCite | 2026-08-14 (live) |
| **Internet Archive / Wayback** | REST · `archive.org/wayback/available`, `web.archive.org/web/<ts>id_/<url>` | none (IA keys raise throttle) | robots allows all except `/control`, `/report` | per-item | `id_` = raw snapshot; use `curl` if the fetcher blocks web.archive.org | the live source itself | 2026-08-14 (live) |

## Kept out of the library

The library holds *specific* connectors. Three kinds of thing are deliberately excluded:

- **General lessons, not sources** — e.g. "open-access PDF links often `403` non-browser
  clients, fall back to a DOI/metadata lookup". Those live in *Access-policy patterns* above,
  not as a row.
- **Categorical APIs with their own skill** — Wikimedia's own data APIs (MediaWiki Action,
  Wikidata SPARQL, Analytics, Phabricator) are excellent but *categorical* (any wiki / the
  whole graph) and already covered by the `wikimedia-data-collection` skills.
- **Compute, not collection** — LLM inference endpoints (e.g. **LiftWing** on
  `api.wikimedia.org`, ~100 req/hour anonymous, no tool-calling / JSON mode) use the same
  connector *model* but you send work rather than collect data → see the `liftwing-llm` skill.
