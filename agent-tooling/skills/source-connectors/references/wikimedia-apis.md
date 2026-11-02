# Wikimedia APIs: one inventory

Every public Wikimedia API, where it lives, what governs it, and whether agents may call it
(registry: `agent-tooling/settings/mandated-services.json`). Inventory started from Wikimedia's
own list (mediawiki.org "Wikimedia APIs", edited 2026-06-15) and extended with the services
that list leaves out (query services, dumps, media). Checked 2026-10-20.

## What governs all of them

All Wikimedia APIs fall under Wikimedia policy (Lodewijk, 2026-10-20), in this order:

1. **Robot policy** (wikitech "Robot policy", modified 2026-03-16). Unauthenticated limits:
   Action API 1 concurrent request and under 5 req/s; REST APIs 3 concurrent and under 5 req/s;
   media (`upload.wikimedia.org`) at most 2 concurrent and 25 Mbps; other resources (Gerrit,
   GitLab, Phabricator) 1 concurrent with at least 1 s between requests. A request that takes
   over 1 s to serve means waiting 5 s before the next. Request gzip; on 429 wait the
   `Retry-After` delay; identify the client per the User-Agent policy.
2. **Wikimedia APIs / Rate limits** (mediawiki.org, modified 2026-10-15): Action and REST APIs
   on all sites: 200 req/min for a bot with a compliant User-Agent, 10 req/min without; at most 3
   concurrent. WMCS/Toolforge, flagged bot accounts and known clients are exempt from the API
   limit, not from the Robot policy.
3. **robots.txt** governs crawling of pages. It disallows `/w/` and `/api/` for `*`, but the
   Robot policy documents and limits API use, so documented API calls follow (1) and (2).

Our User-Agent comes from `agent-tooling/settings/outbound-identity.json` (project UA, no e-mail
unless Lodewijk approves).
4. **User-Agent policy** (foundation.wikimedia.org, modified 2026-03-27): format
   `<client>/<version> (<contact>) <library>/<version>`; contact is an e-mail, a website or
   `User:<name>`; bots "should also include 'bot'"; generic agents such as `curl` are refused
   (HTTP 403) or blocked without notice. Our UA names a public repository as contact (checked
   2026-10-20); it does not yet say "bot" or name the library (proposal below).
5. **API etiquette** (mediawiki.org API:Etiquette, modified 2026-05-13): requests in series,
   not parallel; `maxlag` for non-interactive work; batch with `titles=A|B|C` and generators
   instead of one request per item; `Accept-Encoding: gzip`; JSON; GET for reads (POST reads are
   uncacheable; if unavoidable send `Promise-Non-Write-API-Action: true`); cache what can be
   reused; `oldid`, not `revid`; on `ratelimited` back off exponentially; bulk data comes from
   dumps, not the Action API.

## Inventory

Registry column: **yes** = agents may call it now; **added 10-20** = prepared on 2026-10-20,
live after Lodewijk's yes and a push; **no** = not registered, with the reason.

| API | Host · path | What it gives | Auth | Limits beyond the policy above | Registry |
|---|---|---|---|---|---|
| MediaWiki Action API | every wiki · `/w/api.php` | content, revisions, metadata, search | none for reads | `maxlag=5`; paginate on `continue` (skill `mediawiki-action-api`) | yes: `*.wikipedia.org` and the other project suffixes, `www.wikidata.org`, `commons.wikimedia.org`, `meta.wikimedia.org`, `wikimania.wikimedia.org`; added 10-20: `www.wikifunctions.org`, `species.wikimedia.org`, `foundation.wikimedia.org`, `incubator.wikimedia.org`, `outreach.wikimedia.org` |
| MediaWiki REST API | every wiki · `/w/rest.php/v1/…` | page source/HTML, history, search | none for reads | REST row of the Robot policy | yes, same hosts as the Action API |
| Wikimedia REST API (RESTBase) | every wiki · `/api/rest_v1/…` | page summaries, mobile HTML, feeds | none | REST row | yes, same hosts |
| Wikidata REST API | `www.wikidata.org/w/rest.php/wikibase/v1/…` | items, properties, statements | none for reads | REST row | yes (`www.wikidata.org`) |
| Wikidata Query Service | `query.wikidata.org/sparql`; scholarly articles split out to `query-scholarly.wikidata.org/sparql` since 2025-05-09 | SPARQL over Wikidata | none | 60 s query timeout, per-agent throttling (skill `wikidata-sparql`) | yes (`query.wikidata.org`); added 10-20: `query-scholarly.wikidata.org` |
| Commons Query Service | `commons-query.wikimedia.org` | SPARQL over structured data on Commons | **OAuth with a Commons account** ("restricted behind OAuth authentication") | limited resources, weekly reload downtime | **no**: needs an account, which is Lodewijk's call |
| Analytics API (AQS) | `wikimedia.org/api/rest_v1/metrics/…` | pageviews, unique devices, edits, editors | none | REST row (skill `wikimedia-analytics-api`) | yes (`wikimedia.org`) |
| Wikimedia API Portal / Core REST, Wikifeeds, Link Recommendation, Lift Wing | `api.wikimedia.org` (`/core/v1/…`, `/feed/v1/…`, `/service/linkrecommendation/…`, `/service/lw/inference/…`) | page content, featured feeds, link suggestions, ML predictions | none for reads (Lift Wing: 100 req/h anonymous) | REST row; Lift Wing per playbook `liftwing-llm` | yes (`api.wikimedia.org`) |
| Page Description API | every wiki, REST | short page descriptions | none for reads | REST row | yes, same hosts |
| Wikifunctions API | `www.wikifunctions.org` · Action API | function catalogue and calls | none for reads | Action row | added 10-20 |
| EventStreams | `stream.wikimedia.org/v2/stream/{name}` (SSE) | live recent changes, page creates/deletes | none | meant for "small scale external tool developers"; 15-min connection timeout, resume with `Last-Event-ID`; history about 7-31 days; discard canary events; **one stream connection at a time** | added 10-20 |
| Media files | `upload.wikimedia.org` | original files and thumbnails | none | Robot policy media row: at most 2 concurrent, 25 Mbps; no gzip needed | added 10-20 |
| Dumps | `dumps.wikimedia.org` | full XML/SQL/JSON dumps | none | dumps' own limits (connector row "Wikimedia public data & archives") | yes |
| Wikimedia Enterprise | `api.enterprise.wikimedia.com` (+ auth, site) | structured content, snapshots | account + token (skill `wikimedia-enterprise`) | per Enterprise plan | yes |
| Phabricator (Conduit) | `phabricator.wikimedia.org/api/` | tasks, comments | none for reads | Robot policy "other resources" row | yes, read-only |
| Attribution API (beta) | per the API portal | data for crediting content | unread | unread | no: beta, docs unread |
| API Sandbox | per wiki `Special:RestSandbox` | human tool for trying requests | n/a | n/a | n/a (for people) |

## Notes

- **Wikispecies** lives at `species.wikimedia.org`; the registry's `.wikispecies.org` suffix
  covers only the redirecting domain [concluded], hence the explicit host.
- New Wikimedia content wikis go in the Action API entry when work needs them; the policy above
  already governs them.

## Getting more headroom (cheapest first)

What raises our limits or lowers our request count, in Wikimedia's own terms. Items 1-3 cost
nothing; 4-6 need an account or infrastructure and are Lodewijk's call.

1. **Fewer requests, same data.** Batch (`titles=` with `|`, generators, `prop=` combined in one
   call), cache, request gzip, use GET. Most slowdowns are request count, not the limit.
2. **A fully compliant User-Agent** keeps us in the 200 req/min tier instead of 10 req/min
   (Rate limits page). Proposal: add the library and the word "bot", e.g.
   `WikimediaAnalysis/1.0 (https://github.com/lgelauff/wikimedia-analysis; research bot) python-requests/<v>`.
   A `User:<name>` contact would identify Lodewijk's account: his yes first.
3. **Bulk from dumps or Enterprise snapshots**, not page-by-page API calls: dumps
   (`dumps.wikimedia.org`, approved) and the Enterprise Snapshot API (account exists) avoid the
   API limits entirely.
4. **Authenticate with an owner-only OAuth 2 consumer** (mediawiki.org OAuth/Owner-only
   consumers, modified 2026-09-25): registered at meta.wikimedia.org
   `Special:OAuthConsumerRegistration/propose/oauth2`, ticking "for use only by you"; it
   "does not need to be reviewed"; requests carry `Authorization: Bearer <token>` and must
   return cookies (the CDN uses them; dropping them invites strict limits). Robot policy limits
   rise from 1 to 3 concurrent and from under 5 to 10 req/s on the Action API, and to 10 req/s on
   REST. Requests are then tied to Lodewijk's account, so request read-only grants only (grant
   list not yet read). Registering is **Lodewijk's task**; the token goes in the agent-secrets
   store.
5. **Run in Wikimedia Cloud Services / Toolforge**: server-side requests from WMCS with a
   compliant UA are exempt from the API rate limit (still bound by the Robot policy). Fits
   long-running collection jobs; needs a Toolforge tool account.
6. **A bot flag** on a wiki exempts that account from the API rate limit, but needs community
   approval per wiki and is meant for editing bots: not worth it for read-only research.
