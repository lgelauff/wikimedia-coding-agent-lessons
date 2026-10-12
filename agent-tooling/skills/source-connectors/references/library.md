# Connector library (dated per item)

Referenced from `../SKILL.md` §4. Each row is a dated claim, not a guarantee: re-check `explain`/robots before relying on a cell.

## Contents
- Dutch government / open data
- Scholarly & archive
- Deliberation & civic research
- Wikimedia community infrastructure
- Media & web

Each row is a connector, and **carries its own `Verified` date** — a dated claim, not a
guarantee (dates are **month-granularity**; the library isn't re-verified daily). Re-check `explain`/robots before relying on a cell. The **Fallback** column is what
to reach for when *this* connector is down, blocked, or throttled. `(live)` = the
endpoint/robots were exercised; `(docs)` = read from documentation/robots only. "free (art. 11)"
= Dutch *Auteurswet* art. 11: no copyright on laws/decisions/ordinances of a public authority.

### Dutch government / open data

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **KOOP Officiële Bekendmakingen** | SRU 2.0 · `repository.overheid.nl/sru` | none | crawler `Disallow: /` — API **documented & preferred**; ~1 req/s, page 1000 | free (art. 11); `/noindex/` = privacy | `explain` → indexes; FRBR `…/frbr/…/xml/…` = artifact; front-end `zoek.officielebekendmakingen.nl` can 504 | Internet Archive (permanent deeplinks) | 2026-08 (live) |
| **CVDR** (decentrale regelgeving) | SRU / FRBR · `lokaleregelgeving.overheid.nl` | none | server page open; polite | free (art. 11) | FRBR-XML may 404 → server-rendered page; SRU indexes differ from KOOP | KOOP bekendmakingen; IA | 2026-08 (live) |
| **wetten.overheid.nl** (BWB, consolidated law) | HTML/XML · `wetten.overheid.nl` | none | catch-all `Allow: /`; **named AI bots** `Disallow: /`; `/*/informatie/xml` off; polite | free (art. 11) | honour the AI-block intent: not live; BWB bulk download or Internet Archive captures | BWB bulk download; Internet Archive | 2026-08 (live robots) |
| **open.overheid.nl / OPP** (PLOOI successor) | *aanlever only* | (client creds) | — | Woo / free | **no public read API** | KOOP (the read path) | 2026-08 (docs) |
| **data.overheid.nl** | CKAN v3 · `data.overheid.nl/data/api/3/action/` | none | `Disallow: /data/` (covers the API path); polite | CC0 | dataset / metadata discovery | the dataset's own host | 2026-08 (live) |
| **CBS StatLine** | OData · v3 `opendata.cbs.nl/ODataApi`; v4 host *(unverified)* | none | v3 paths disallowed; v4 TBD; polite | free + attrib "Bron: CBS" | prefer v4; `$metadata` for fields | `cbsodata` client libs (R/Py) | 2026-08 (docs) |
| **Rechtspraak Open Data** | REST/XML · `data.rechtspraak.nl/uitspraken/{zoeken,content}` | none | no robots served (allow); ≤10 req/s, no full dump | court output, pseudonymised | 2-step: `/uitspraken/zoeken` (ECLI index) → `/uitspraken/content?id=ECLI:…` | Internet Archive snapshot | 2026-08 (live: `/zoeken` 200; bare `/uitspraken/` 404s) |

### Scholarly & archive

| Connector | Protocol · endpoint | Auth | Access policy | Reuse | Notes | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **OpenAlex** | REST · `api.openalex.org` | free key (credit budget) | polite pool via `mailto` | CC0 metadata | **200 + error body** under load; prefer DOI/filter over `?search` | Crossref (metadata); Unpaywall (OA copies) | 2026-08 (live) |
| **Crossref** | REST · `api.crossref.org` | none (mailto polite pool) | polite | metadata open | DOI metadata; `query.*` filters; send `mailto` for the polite pool | OpenAlex; DataCite | 2026-08 (live) |
| **arXiv** | Atom XML · `export.arxiv.org/api/query` | none | robots `Disallow: /` — the API is the sanctioned door; manual asks for a **3 s delay** | mostly CC BY 4.0 (per paper) | `search_query`/`id_list`; version suffix immutable — keep in citations | Semantic Scholar; OpenAlex | 2026-08 (live) |
| **Semantic Scholar** | REST · `api.semanticscholar.org/graph/v1` | free key raises the limit | anon pool tight — a **single request can 429**; 1 req/s unauth vs 100 keyed | research metadata (API terms) | IDs `arXiv:<id>`/`DOI:<doi>`; `fields=`; batch endpoint | Crossref; arXiv (full text) | 2026-08 (live: 429 seen) |
| **Internet Archive / Wayback** | REST · `archive.org/wayback/available`, `web.archive.org/web/<ts>id_/<url>` | none (IA keys raise throttle) | robots allows all except `/control`, `/report` | per-item | `id_` = raw snapshot; use `curl` if the fetcher blocks web.archive.org | the live source itself | 2026-08 (live) |

### Deliberation & civic research

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **Stanford Deliberative Democracy Lab** | HTTPS/HTML · `deliberation.stanford.edu` | none | `User-agent: *` **`Crawl-delay: 30`** — one request per 30 s, and mean it. Content paths (`/news/…`, `/results-…`) are allowed; `/admin/`, `/user/*`, `/search`, `/*/printable/print` disallowed. Only `FemtosearchBot` and `SemrushBot` are banned outright — **no AI bot is named**. A honeypot path is published: `/honeypot-for-misbehaving-crawlers-do-not-enter/` — never request it, directly or by following a link | Stanford / DDL content, all rights reserved unless a page says otherwise — cite and link, don't republish | `curl -A "<descriptive UA with contact>"`; **Claude's WebFetch is `403`-ed here, curl with our own UA gets `200`** (see *Access-policy patterns*). Cache every page on first fetch: at 30 s apart, refetching is the real cost | Wayback (`archive.org/wayback/available`, then `web.archive.org/web/<ts>id_/<url>`); the DDL publishes most results as PDF reports — prefer the report over the news page | 2026-09 (live: robots 200, `/results-…` 200, WebFetch 403) |

### Wikimedia community infrastructure

> ⚠️ **Read-only, unauthenticated, and that is the whole posture.** Never file, comment,
> edit, claim, assign or re-prioritise a task on anyone's behalf. Produce the material — a
> draft task body, reproduction steps, evidence — and hand it over; **Lodewijk files his own
> tasks**, our output is inspiration only. Security issues *never* go in a public task
> (`security@wikimedia.org` or form 75). Anything AI-assisted that a human does post is
> policy-bound to be verified claim by claim first: *"you are fully responsible for its
> content … must be accurate, factually correct, and represent your own understanding."*

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **Wikimedia Phabricator** (read) | HTTPS/HTML · `phabricator.wikimedia.org/T…`; comment text `…/transactions/raw/{PHID}/`; Conduit `…/api/` | **none for reads.** Conduit is token-gated. A token is best owned by a **registered bot with a named human owner** (`#Phabricator-Bot-Requests`); Wikimedia's bot guidance treats a personal account used for repetitive automation as inappropriate, and it may be **disabled or deleted**. *(Personal tokens do exist — the `phabricator-conduit` skill uses one — so this is a norm, not a hard gate.)* Anonymous Conduit returns `ERR-INVALID-SESSION` *(unverified — docs only)*, which is expected, not a bug | `robots.txt` **disallows `/conduit` and `/api`** *(read from an archived robots.txt)* — the API is nonetheless the documented, publisher-sanctioned path (see *Access-policy patterns*); hit only those endpoints. Wikimedia **Robot policy**, stricter than most rows here: **concurrency 1**, **≥1 s between requests**, **pause ≥15 min on any 5xx**. Descriptive UA per WMF UA policy; honour `429` + `Retry-After`. Limits are global across Wikimedia properties; WMCS/Toolforge exempt | Public by default — assume everything is public, permanent and attributable. **Never republish** `acl*security` / `PermanentlyPrivate` content, logs carrying IPs, emails, tokens or session data, or NDA/vetted material. Prefer `@username` over real names | *(Unverified — docs only:* plain `GET /T12345` works unauthenticated; PHIDs (`PHID-XACT-TASK-…`) are embedded in the task page's Javelin init data; `/transactions/raw/{PHID}/` returns comment text as plain text; the search UI is JS-only, so public HTML contains no task IDs.*)* → find tasks via web search or Gerrit's `bug:T12345` reverse lookup, not by crawling | Wayback; Gerrit `bug:` reverse lookup; for high volume the documented routes are OAuth 2.0 + bot flag, WMCS hosting, or `bot-traffic@wikimedia.org` | 2026-09 (docs) |

### Media & web

| Connector | Protocol · endpoint | Auth | Access policy | Reuse | Notes | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **Flickr** (read-only) | REST · `api.flickr.com/services/rest` | API key (read methods) | metadata quota per key; **image CDN `live.staticflickr.com` blocks fast per-IP bursts** | per-photo licence; only free licences → Commons | `nojsoncallback=1`, `per_page=500`; on CDN 429 **pause, go quiet, don't probe** (probing extends the block) | Wayback CDX for `live.staticflickr.com/…` | 2026-08 (endpoint; block behaviour field-observed, not tested here) |
| **WordPress.com** (VIP blogs, e.g. Diff) | REST · `public-api.wordpress.com/rest/v1.1/sites/<domain>/posts/` | none | no published rate limit; polite paged pulls | per-site (Diff = CC BY-SA) | native `wp-json` may be disabled — the public sibling stays open; `fields=`, `number`≤100, `after`/`before` | site `sitemap.xml`; self-hosted `wp-json` if enabled | 2026-08 (live) |

