# Connector library (dated per item)

Referenced from `../SKILL.md` §4. Each row is a dated claim, not a guarantee: re-check `explain`/robots before relying on a cell.

## Contents
- Dutch government / open data
- EU law
- Official statistics
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

### EU law

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **EU Publications Office (Cellar)**: EU legislation, OJ and case law behind EUR-Lex | SPARQL · `publications.europa.eu/webapi/rdf/sparql`; REST · `publications.europa.eu/resource/celex/{CELEX}` (also `/resource/eli/…`) | none | documented public API *(robots of this host not yet checked: Internet Archive offline 2026-10-15)*; ~1 req/s, back off on 429/5xx. **EUR-Lex web pages are not a route**: Wayback captures of the EUR-Lex robots file (2026-10-12..14) are HTTP 202 text/html, a bot-challenge page, so EUR-Lex HTML is closed to scripts | EU documents: reuse with attribution (Commission Decision 2011/833/EU) *(unverified here)* | find the work by CELEX (e.g. `32024R0903` = Regulation (EU) 2024/903) via SPARQL, then fetch a language expression by content negotiation on the `/resource/celex/…` URI (`Accept: application/xhtml+xml` or `application/pdf`, `Accept-Language: eng`) *(unverified)* | Internet Archive captures of EUR-Lex `legal-content/EN/…?uri=CELEX:…` or OJ pages | 2026-10 (docs) |

### Official statistics

| Connector | Protocol · endpoint | Auth | Access policy (robots · rate) | Reuse | Retrieval recipe | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **OECD Data API** | SDMX · `sdmx.oecd.org` | registration encouraged, not required: **Lodewijk registers** (pending 2026-10-16); until then anonymous | API offered as-is, rate-limited without published numbers: 1 req/s; **`oecd.ai` stays excluded** (robots block recorded) | acknowledge the OECD | SDMX data queries per dataflow | Wayback | 2026-10 (terms + docs) |

### Scholarly & archive

| Connector | Protocol · endpoint | Auth | Access policy | Reuse | Notes | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **OpenAlex** | REST · `api.openalex.org` | free key (credit budget) | polite pool via `mailto` | CC0 metadata | **200 + error body** under load; prefer DOI/filter over `?search` | Crossref (metadata); Unpaywall (OA copies) | 2026-08 (live) |
| **Crossref** | REST · `api.crossref.org` | none (mailto polite pool) | polite | metadata open | DOI metadata; `query.*` filters; send `mailto` for the polite pool | OpenAlex; DataCite | 2026-08 (live) |
| **arXiv** | Atom XML · `export.arxiv.org/api/query` | none | robots `Disallow: /` — the API is the sanctioned door; manual asks for a **3 s delay** | mostly CC BY 4.0 (per paper) | `search_query`/`id_list`; version suffix immutable — keep in citations | Semantic Scholar; OpenAlex | 2026-08 (live) |
| **Semantic Scholar** | REST · `api.semanticscholar.org/graph/v1` | free key raises the limit | anon pool tight — a **single request can 429**; 1 req/s unauth vs 100 keyed | research metadata (API terms) | IDs `arXiv:<id>`/`DOI:<doi>`; `fields=`; batch endpoint | Crossref; arXiv (full text) | 2026-08 (live: 429 seen) |
| **Internet Archive / Wayback** | REST · `archive.org/wayback/available`, `web.archive.org/web/<ts>id_/<url>` | none (IA keys raise throttle) | robots allows all except `/control`, `/report` | per-item | `id_` = raw snapshot; use `curl` if the fetcher blocks web.archive.org | the live source itself | 2026-08 (live) |
| **Europe PMC** | REST · `www.ebi.ac.uk/europepmc/webservices/rest/` | none | docs offer REST + "automated, bulk download"; ebi robots `Crawl-Delay: 10` for crawlers, stay ≤1 req/s; only the `/europepmc/` paths of this shared EBI host | full text only for the open-access subset | `search?query=DOI:…&format=json`; `{PMCID}/fullTextXML` for OA | NCBI E-utilities; Wayback | 2026-10 (docs; terms page 403) |
| **NCBI E-utilities** | REST · `eutils.ncbi.nlm.nih.gov/entrez/eutils/` | none; docs ask for `tool` + `email` params: `tool=WikimediaAnalysis`, and the `email` value needs **Lodewijk's yes** (flagged 2026-10-16); an API key (registration encouraged) is **Lodewijk's** to register | docs: ≤3 req/s, large jobs weekends or 21:00–05:00 US Eastern; robots `Disallow: /` overridden by the documented API | per record (PMC OA subset reusable) | `esearch` → `efetch`/`esummary`; ids PMID/PMCID | Europe PMC | 2026-10 (docs) |
| **doi.org content negotiation** | HTTPS · `doi.org/{DOI}` with an `Accept` header | none | **metadata only**: never follow the redirect to publisher pages; robots permissive | metadata | `Accept:` CSL-JSON (`application/vnd.citationstyles.csl` `+json`) or BibTeX (`application/x-bibtex`); for Crossref DOIs prefer the Crossref API, use this for DataCite and other registries | Crossref; DataCite | 2026-10 (docs, Crossref CN page) |
| **IA Scholar / fatcat** (aggregator) | REST · `api.fatcat.wiki/v0/`; search UI `scholar.archive.org` | none for reads | aggregator rule; IA manners (1 req/s, back off); `scholar.archive.org` robots disallows `/search`: use the API, not search pages | metadata free to reuse; files per source | release lookup by DOI → `files` → archived PDF URLs; check the host is up first (refused 2026-10-16) | Wayback | 2026-10 (docs 2024 capture) |
| **DataCite** | REST · `api.datacite.org` | none for the public API | "accessed without authentication"; documented limit 500 req / 5 min per IP unidentified (1000 with an e-mail in UA or `mailto=`): our 1 req/s fits the unidentified tier, so no e-mail is sent; back off on 429; public endpoints only, not member endpoints | CC0 waiver covers data retrieved via the APIs (Data File Use Policy) | `/dois/{DOI}`, `/dois?query=` | doi.org CN; Crossref | 2026-10 (live: rate-limit page, use policy) |
| **Zenodo** | REST · `zenodo.org/api/` | none (guest) | docs: guest 60/min, 2000/h, search 30/min; robots `Disallow: /api` overridden by the documented API (files under `/api/records/*/files` are allowed anyway) | per record licence | `/api/records/{id}`; download each file once and verify its checksum | Wayback; DataCite | 2026-10 (docs) |
| **Hugging Face Hub** | REST · `huggingface.co/api/` + file resolve URLs | none for public reads; tokens only from the agent-secrets store | HF-wide rate limits; robots `Allow: /`; **writes and uploads never without Lodewijk's yes per upload** | per repo licence | `/api/datasets/{id}`, `/{repo}/resolve/{rev}/{file}` | the source repo | 2026-10 (docs) |

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
| **Wikimedia public data & archives**: dumps, analytics datasets, mailing-list archives, Diff blog | HTTPS · `dumps.wikimedia.org`, `analytics.wikimedia.org`, `lists.wikimedia.org`, `diff.wikimedia.org` | none | Wikimedia **Robot policy** as for Phabricator: **concurrency 1**, **≥1 s between requests**, pause ≥15 min on any 5xx, descriptive UA, honour `429` + `Retry-After`. Dumps: bulk files, so download each once, resume with `Range`, never re-fetch; prefer a mirror for big pulls *(robots of each host not yet checked)* | Wikimedia content licences (mostly CC BY-SA / CC0 for data); mailing-list archives are public but carry names and e-mail addresses: counts and links only, never republish | dumps: `dumps.wikimedia.org/<wiki>/<date>/` index → file + `*-sha1sums.txt`; analytics: `analytics.wikimedia.org/published/datasets/…`; lists: `lists.wikimedia.org/hyperkitty/list/<list>/…` thread pages; Diff: post URLs | Wayback; dump mirrors; for pageviews/edits use the Analytics REST API (wikimedia-analytics) | 2026-10 (docs) |

### Media & web

| Connector | Protocol · endpoint | Auth | Access policy | Reuse | Notes | Fallback | Verified |
|---|---|---|---|---|---|---|---|
| **Flickr** (read-only) | REST · `api.flickr.com/services/rest` | API key (read methods) | metadata quota per key; **image CDN `live.staticflickr.com` blocks fast per-IP bursts** | per-photo licence; only free licences → Commons | `nojsoncallback=1`, `per_page=500`; on CDN 429 **pause, go quiet, don't probe** (probing extends the block) | Wayback CDX for `live.staticflickr.com/…` | 2026-08 (endpoint; block behaviour field-observed, not tested here) |
| **WordPress.com** (VIP blogs, e.g. Diff) | REST · `public-api.wordpress.com/rest/v1.1/sites/<domain>/posts/` | none | no published rate limit; polite paged pulls | per-site (Diff = CC BY-SA) | native `wp-json` may be disabled — the public sibling stays open; `fields=`, `number`≤100, `after`/`before` | site `sitemap.xml`; self-hosted `wp-json` if enabled | 2026-08 (live) |


## Kept out of the library

Routes decided against or deferred, with the date and the reason, so they can be revisited.
Hosts named here are **not** approved (the registry guard stops reading at this heading).
Re-check with the `route-vetting` skill before changing a verdict.

| Route | Decision (date) | Why |
|---|---|---|
| Google Scholar (`scholar.google.com`) | against (2026-10-16) | robots (live 2026-10-16) for all agents: "Disallow: /scholar", "Disallow: /search", "Disallow: /citations?"; no API. Human use only; OpenAlex `locations` give the "all versions" effect |
| Scraping services (SerpAPI, Apify "Scholar APIs" and similar) | against (2026-10-16, Lodewijk agrees) | anything explicitly called, or clearly operating as, a scraping service is not what we intend: they fetch paths the source's robots disallows, the same access through a third party |
| Academia.edu | against (2026-10-16) | robots (live 2026-10-16): `User-agent: *` "Disallow: /"; GPTBot, Google-Extended, Applebot-Extended disallowed; no public API found; terms page 403 |
| ResearchGate | ASK, not against (2026-10-16) | robots (live 2026-10-16) is permissive: `User-agent: *` "Allow: /" with a few paths blocked, no AI crawlers named; but no public API found and the terms page returns 403 with no Wayback capture, so the terms are unread. Corrected from an earlier from-memory "against" |
| Publisher TDM APIs (Elsevier, Springer, Wiley) | against for now (2026-10-16) | need institutional keys and agreements; paywalled papers go through Lodewijk's Stanford access as PDF drops |
| SSRN | against (2026-10-16) | no public API; use OpenAlex metadata or Wayback |
| Unpaywall (`api.unpaywall.org`) | deferred (2026-10-16) | OpenAlex already carries its open-access locations; requires an `email=` parameter. Revisit if OpenAlex misses OA copies |
| CORE (`api.core.ac.uk`) | deferred (2026-10-16) | needs a licence/key (Lodewijk's task); vault triage expects little gain. Revisit after a month of the vault trickle |
| Madrid open data (`datos.madrid.es`) | dropped (2026-10-16) | too specific (Lodewijk); robots also disallows `/api/`, downloads and query strings (Crawl-delay 10). One-off downloads by Lodewijk |
| Helsinki Region Infoshare (`hri.fi`) | dropped (2026-10-16) | too specific (Lodewijk) |
| Pabulib (`pabulib.org`) | manual only (2026-10-16) | robots disallows `/download` and `/api`; no API docs or licence. Lodewijk downloads; optionally ask the maintainers |
| `oecd.ai` | against (2026-10-16) | robots block recorded in the vault; the OECD data API (`sdmx.oecd.org`) is the approved door |
| EUR-Lex web pages (`eur-lex.europa.eu`) | against (2026-10-15) | bot-challenge page instead of robots; the Publications Office Cellar API is the approved door |
| Munich participation site (`unser.muenchen.de`, CONSUL) | against (2026-10-12) | robots disallow-all plus named AI-crawler bans; documented API needs a city-issued token |
| Legifrance (PISTE API), Polish ISAP | undecided (2026-10-16) | APIs exist but keys/terms unchecked; only 2 + 3 failed vault items. Vet with `route-vetting` when needed |
| Eurostat, Harvard Dataverse, OSF | under investigation (2026-10-16) | Eurostat: only a copyright notice found so far; Dataverse: robots and rate limits unread; OSF: docs unreadable, robots `Disallow: /` |
