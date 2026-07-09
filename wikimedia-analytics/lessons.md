# Wikimedia analytics lessons

## Docs to fetch at project start

- 🤖 https://www.mediawiki.org/wiki/API:Revisions
- 🤖 https://www.mediawiki.org/wiki/API:Parsing_wikitext
- 🤖 https://wikitech.wikimedia.org/wiki/PAWS

---

## MediaWiki API

- **Use `action=parse` instead of raw wikitext for pages with templates.** Raw wikitext (`action=query&prop=revisions`) returns unexpanded templates, making date and content extraction unreliable. `action=parse` returns rendered HTML — strip it to get clean text.
- **Use `formatversion=2`** for cleaner structured JSON. The default (v1) has legacy quirks like wrapping single items in objects.

## Mailing list archives

- Wikimedia mailing list archives are available as gzip-compressed monthly plain text files at `lists.wikimedia.org/pipermail/<listname>/YYYY-Mon.txt.gz`. HTTP 404 means no archive for that month — handle gracefully and skip.
- Past months are immutable — safe to cache permanently.

## PAWS

- PAWS gives direct SQL access to Wikimedia analytics databases, including edit history, actor IDs, and retention data not exposed via the action API. Use `wmpaws.run_sql()` — returns pandas DataFrames.
- PAWS is designed for and currently accessible to all Wikimedia community members.
- Only accessible from within the PAWS environment itself, not locally. Design code to fall back gracefully.

## User-Agent convention

- Wikimedia servers expect a descriptive `User-Agent` header identifying your tool and contact point. Without it you risk being rate-limited or blocked. Conventional format: `ProjectName/1.0 (https://github.com/you/repo; brief description)`.

## Archival bot activity inflates page counts in recent years

When counting `DISTINCT rev_page` per year from the `revision` table, archival/maintenance bots that touch old pages in a given year will inflate that year's page count — the old pages were not opened that year, they were just touched. Fix: group by the **first edit per page** (`MIN(rev_timestamp)`) and aggregate by that, so each page is counted once in the year it was created:

```sql
SELECT LEFT(first_edit, 6) AS ym, COUNT(*) AS new_pages
FROM (
    SELECT rev_page, MIN(rev_timestamp) AS first_edit
    FROM revision r JOIN page p ON r.rev_page = p.page_id
    WHERE <filters>
    GROUP BY rev_page
) sub
GROUP BY 1 ORDER BY 1
```

Known instance: English Wikipedia `Requests_for_comment/%` pages show a 3–6× spike in `distinct_pages` for 2021–2022 due to a bot touching thousands of old user-conduct RfC pages (1 edit each).

## Replica link-table schema (linktarget migration)

- The link tables were **normalized to a shared `linktarget` table**. `categorylinks.cl_to` was **removed**; category/link/template joins now go through `*_target_id → linktarget.lt_namespace / lt_title`: `categorylinks.cl_target_id`, `pagelinks.pl_target_id`, `templatelinks.tl_target_id`. Queries written against the old `cl_to` / `pl_namespace` / `pl_title` columns will error or return nothing. **Verify the current schema before writing link queries** (`DESCRIBE categorylinks;`).
- **No cross-database joins** on the replicas — querying two wikis (or wiki + Wikidata) is a two-step app-side join, not one SQL statement.
- Replicas reflect **current state only** — no historical/point-in-time link or category membership. For history you must reconstruct from revision wikitext (or dumps).

## Dumps — availability & retention

- Dumps are **files**, mounted on Toolforge/PAWS at `/public/dumps` — read/streamed, not a queryable DB.
- **Retention is short:** `dumps.wikimedia.org` (and the mount) keep only ~the **last 6–7 monthly runs**. There is **no multi-year archive of dated dumps** — you cannot get a 2010 SQL table state.
- History is **cumulative**: the *latest* `pages-meta-history` dump contains every revision back to 2001. So pin ONE recent full-history dump as the source of truth for a time series, rather than chasing dated dumps.
- **`stub-meta-history`** carries per-revision metadata (page, `<ns>`, revid, timestamp) with **no wikitext** — tiny. Stream it to build a namespace-filtered, per-date revision inventory cheaply, then fetch content only for selected revids.
- **No bz2 multistream byte-offset index for history dumps** (only for `pages-articles-multistream`, i.e. current article text). Random access by revid into history isn't available — use the API by revid, or stream the relevant part file (history is split by page-id range).
- Deleted pages/revisions are **redacted from public dumps and replicas** — a dump captures pages that existed at dump time, but content deleted before that is unrecoverable.

## PAWS SQL — MariaDB gotchas

- **`year_month` is a reserved word in MariaDB** — using it as a column alias causes a syntax error. Use a non-reserved alias (e.g. `ym`) or reference columns by position (`GROUP BY 1 ORDER BY 1`) instead of by alias.
- Avoid SQL aliases that shadow MariaDB reserved words; when in doubt, use `GROUP BY 1` / `ORDER BY 1` for computed columns.

## Wikimedia Enterprise API auth

- Login and token-refresh are **separate endpoints with different response
  shapes**, not one endpoint with a `grant_type` param like typical OAuth: login is
  `POST auth.enterprise.wikimedia.com/v1/login` with `{username, password}`, returning
  `id_token`, `access_token`, `refresh_token`, `expires_in`; refresh is
  `POST .../v1/token-refresh` with `{username, refresh_token}` (no password), and its
  response has **no `refresh_token` field** — keep reusing the one from login. Don't
  assume `expires_in` is a fixed 24h either; read it from whichever response you got
  (observed shorter on refresh in the docs' own example).
- Refresh tokens last 90 days and are good for **up to 90 refreshes** — track a
  refresh count, not just the expiry, or you'll get a rejected refresh well before the
  90-day mark on a chatty caller.
- The **password is only needed at login and again once the refresh token expires/
  exhausts** — refresh only takes `username` + `refresh_token`. That makes an
  interactive prompt (not a stored secret) the right default: the annoyance is rare
  (~every 90 days), so it's not worth keeping a password at rest for.
- **The login `username` is case-sensitive and must be lowercase** — even if the
  account name is normally capitalized elsewhere (e.g. matches a Wikipedia username
  with a capital first letter). Sending it as typed/capitalized gets a generic
  `401 Incorrect username or password`, which reads like a wrong password, not a
  case mismatch. `wikimedia_enterprise_auth.py` fails fast on an uppercase first
  letter with an explicit message rather than silently lowercasing it — a login
  username is exact/user-supplied, so surface the mismatch instead of guessing.
- Tooling: `agent-tooling/scripts/wikimedia_enterprise_auth.py` (+ Claude Code skill
  `agent-tooling/skills/wikimedia-enterprise/`) implements the cache/refresh/login
  cascade described above.

## Phabricator bug reports

- Follow the standard template: **Steps to replicate**, **What happens**, **What should have happened instead**, **Other information**. Skip sections that don't apply — don't add a "Requested action" section, that's not the convention.
- Include a minimal reproduction script in Steps to replicate. Cross-validate with a second data source (e.g. AQS API) to isolate whether the bug is in the pipeline or the raw data.
- If you can identify the likely root cause from source code, add it to Other information — include the specific file and field. This gives the team a precise starting point without over-prescribing the fix.
- Tag with the relevant project (e.g. `Analytics`, `Differential-Privacy`) so the right team sees it. Skip priority unless you have strong justification.
- Known issue example: T426559 — Netherlands missing from `country_project_page` DP dataset since 2023-11-09, traced to a JOIN on `canonical_data.countries.data_risk_classification` in `country_project_page_gaussian.py`.
