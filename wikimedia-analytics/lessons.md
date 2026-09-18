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

## robots.txt checks fail CLOSED — "blocked by robots.txt" usually isn't

`urllib.robotparser.RobotFileParser` denies everything when it could not read robots.txt. Its
`can_fetch()` returns `False` while `last_checked == 0`, on the documented principle that an
unread robots.txt means nothing is allowable. So the usual defensive wrapper

```python
rp = urllib.robotparser.RobotFileParser()
rp.set_url(f"{domain}/robots.txt")
try:
    rp.read()
except Exception:
    pass  # "fail-open: if robots.txt unreachable, assume allowed"   <- WRONG
```

fails **closed**, and the comment is a lie the code will happily tell for years. A DNS NXDOMAIN,
a TLS `CERTIFICATE_VERIFY_FAILED`, a connect timeout, and a real `Disallow:` line all surface as
one indistinguishable message. `read()` also maps HTTP **401/403 on robots.txt itself** to
`disallow_all = True` — so a WAF that rejects your client reads as a site-wide prohibition even
when parsing works correctly.

Two consequences:

- **Never record a "site forbids automated access" finding from this message.** Re-test the host
  first — one `requests.get(host + "/robots.txt")` tells you which of the four it was. Measured
  case (2026-08-01, national-curriculum sourcing across 14 government hosts): **11 failures, 0 of
  them an actual robots directive** — 6 network/TLS/DNS, 5 WAF/bot filtering.
- **If you want fail-open, write it explicitly**: treat "robots.txt unreachable" as allowed only
  when the fetch failed for transport reasons, and keep 401/403/`Disallow` as deny. Don't rely on
  the `try/except` around `read()` to produce it.

Reaching for `--ignore-robots` is the wrong repair in both directions: for transport failures the
connection still fails, and for 403s it means pushing past a server actively refusing you.

**Corollary — Latin American government PDF hosts.** In that same measurement, every northern
host (BOE, NCERT, SEP, educ.ar CDN) worked first try, while `curriculumnacional.cl`,
`mineducacion.gov.co`, `mineduc.cl` subdomains, `dof.gob.mx`, `bnm.me.gov.ar` and
`entrama.educacion.gob.ar` failed on DNS, incomplete TLS chains, connect timeouts, or Check
Point/WAF 403s. Budget for a Wayback (`/web/<ts>id_/<url>` returns original bytes) or
different-exit-node route when a collection depends on them.

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

## Parsing SQL dumps: scan tuples, and prove the result is independent of your buffer

A dump is the only way to answer "which items across a whole wiki satisfy property X" — the API
answers "tell me about item X". So parsing them well is worth doing once, properly.

- **Scan the byte stream for parenthesised tuples, quote- and escape-aware.** Do not parse by line.
  Layout is not a property of the format: some wikis emit one tuple per line, others put an entire
  `INSERT` on a single line. A line parser checked on one wiki returned **437 rows from a 75 MB
  file** on another, and reported zero errors, because every line it saw was well-formed — there was
  one. **Anything verified on a single project is verified on a sample of one**, so re-verify per
  wiki and per run rather than treating it as settled.
- **Find the statement end by tracking quotes, not with `find(";")`.** Page titles legally contain
  semicolons, so `AT&T;_Inc` ends the statement early and everything after it is skipped.
- **Assert chunk-invariance in a committed test — on the row count *and* a content digest.** Parse
  the same input at 4 MB, 1 MB, 64 KB and a few odd sizes and require identical results. This is the
  only symptom a boundary bug gives: one real dump read 1,684,707 / 1,684,702 / 1,684,682 rows at
  three buffer sizes and was otherwise perfect. A digest matters because a stable count with
  reshuffled contents passes a count-only test. **A result that moves with an implementation detail
  is a bug in the implementation, by definition.**
- **Have the scanner report how far it got, and keep the remainder.** Cutting the buffer at the last
  `)` loses a tuple per boundary, because that `)` can fall inside a quoted title.
- **Give every pass a floor, not just the one where the last bug was.** When a later pass looks up
  ids that an earlier pass produced, ~100% must resolve — those ids exist by construction, so a miss
  is a parser fault and never a fact about the wiki. A run that guarded only pass 1 shipped eight
  wikis whose passes 4 and 5 resolved **7–16%** of their targets, all exiting 0.
- **Set floors from measurement.** A "sanity" divisor assuming ~10 compressed bytes/row was 500×
  too loose against a measured 3.2–3.9 B/row across 14 real dumps: it fired only below 0.1% of the
  true count. Measure the ratio on the dumps you have, then leave ~5× margin.
- **If you accept an `on_bad` callback, call it.** A parser that took the parameter and never invoked
  it made every "0 unparseable" in every log and manifest a constant rather than a measurement. Give
  it something real to detect — these dumps have a fixed field count per statement, so a tuple whose
  arity differs from the first is a desync worth reporting instead of yielding with its fields
  silently re-indexed.

## Parsing XML dumps: cut only at closing tags, and unescape after splitting

- **Buffer across reads and split only on a complete `</page>`.** The same boundary discipline as
  above; a 100 KB article straddling a 4 MB read is routine.
- **Split the blocks first, then unescape entities.** MediaWiki escapes `<` in element content, so a
  literal `</page>` inside wikitext arrives as `&lt;/page&gt;` and cannot truncate a block — but only
  while unescaping happens *after* the split. Reversing that order makes article text able to end a
  page early.
- **Replace `&amp;` last** when unescaping by successive replacement: none of the other replacements
  can produce a `&`, so nothing can be double-decoded. `&amp;lt;` correctly yields `&lt;`.
- **Read the whole file rather than range-fetching multistream blocks — unless you check the
  arithmetic.** Blocks hold ~100 pages, so wanting a spread 7% of pages touches
  `1 − 0.93¹⁰⁰ ≈ 99.9%` of blocks. The index pays off only for genuinely clustered or tiny selections.
- **On Toolforge read `/public/dumps/public/<project>/<date>/` and transfer nothing.** Streaming the
  15-project wikitext set over HTTP moves ~62 GB; the same files are already on local disk there.
- **Make a long HTTP stream resumable.** A multi-hour pass died on `ConnectionResetError` and lost
  everything. Wrap the response so a dropped read reopens with `Range: bytes=<offset>-`: bz2 requires
  only that its input be contiguous, not that it came from one connection, so the resume is invisible
  to the decompressor. This matters most when the dump is larger than your free disk and "download it
  first" is not available.

## Matching file links across languages: match generically, filter by extension

Every wiki has its own file namespace (`चित्र`, `চিত্র`, `檔案`, `Изображение`, `Fişier`…) and its own
infobox parameter names.

- **Match any `[[<prefix>:<name>.<ext>]]` and require an image extension**, rather than whitelisting
  namespace aliases. A hand-assembled alias list silently found nothing on the wikis it omitted — and
  the extension requirement simultaneously keeps `.ogg`/`.webm` out of an image population (0.45% of
  rows in one real run were national anthems, whose request series is player-driven).
- **A leading colon means "link, don't embed".** `[[:File:X.jpg]]` renders a link to the file page and
  fetches no image; excluding `:` from the prefix class handles it for free.
- **Use a negated delimiter class for template parameter names, not a letter class.** `[A-Za-z0-9_ -]`
  matches `| image =` and nothing on nine of fifteen projects. `\w` is not sufficient either: Python's
  `\w` follows `str.isalnum()`, which excludes nonspacing combining marks, so Devanagari `चित्र` and
  Bengali `চিত্র` still fail on the virama. `[^|{}\[\]<>=\n]` is script-independent by construction.
  Infobox images are lead images, so this class of miss is never uniformly distributed.
- **Mask HTML comments and `nowiki`/`pre`/`syntaxhighlight` before parsing, replacing them with
  spaces rather than deleting them.** A commented-out `== Heading ==` invents a section and shifts
  every later position; a commented-out image becomes a phantom one. Equal-length replacement keeps
  character offsets exact for anything downstream that uses them.
- **`<gallery>` and `<imagemap>` bodies are bare `File:X.jpg|caption` lines with no `[[`** — they need
  their own handling, and they are essentially always below the lead, so missing them skews any
  position statistic.
- **Match headings against the raw line.** A leading space makes a line preformatted text in
  MediaWiki, so ` == A ==` is not a heading; stripping the line first invents one.

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

## Wikimedia Enterprise API — access tiers, and free paid-tier access for volunteers

There's no dedicated "volunteer tier," but three real paths to more than the plain
free-signup tier — worth knowing before assuming you need to pay:

- **Free tier (no request needed):** as of the 2026-07-01 update — 50,000 On-demand
  requests/month, 30 Snapshot downloads/month (1,500 chunks), and Structured Contents
  Snapshots included free. Often enough for a personal research/analytics project;
  check this before assuming you need a paid or exceptional-access path.
- **Wikimedia Cloud Services (PAWS / Toolforge / Cloud VPS) get paid-tier access for
  free, automatically** — calls made *from within* those environments hit the
  Enterprise API with **no `Authorization` header at all** and get full paid-tier
  limits (unlimited requests, daily snapshots, Realtime API). Access is granted by the
  environment's IP range, not by token. If the workload can run there, this is the
  easiest way past the free-tier caps — no application, no waiting.
- **"Exceptional access" request** (for paid-tier limits run *outside* Cloud
  Services): email `techpartnerships@wikimedia.org` answering six things — who you
  are (incl. your Enterprise API username), what exception you're requesting, why the
  free tier is insufficient, whether custom dev/support is needed, how the use case
  aligns with the Movement Strategy Recommendations, and how it aligns with Wikimedia
  values (open knowledge, public benefit). Reviewed at the Foundation's discretion;
  academic research and mission-aligned non-profit work are explicitly named as good
  fits. Source: [meta.wikimedia.org/wiki/Wikimedia_Enterprise/Access](https://meta.wikimedia.org/wiki/Wikimedia_Enterprise/Access).

## Phabricator bug reports

- Follow the standard template: **Steps to replicate**, **What happens**, **What should have happened instead**, **Other information**. Skip sections that don't apply — don't add a "Requested action" section, that's not the convention.
- Include a minimal reproduction script in Steps to replicate. Cross-validate with a second data source (e.g. AQS API) to isolate whether the bug is in the pipeline or the raw data.
- If you can identify the likely root cause from source code, add it to Other information — include the specific file and field. This gives the team a precise starting point without over-prescribing the fix.
- Tag with the relevant project (e.g. `Analytics`, `Differential-Privacy`) so the right team sees it. Skip priority unless you have strong justification.
- Known issue example: T426559 — Netherlands missing from `country_project_page` DP dataset since 2023-11-09, traced to a JOIN on `canonical_data.countries.data_risk_classification` in `country_project_page_gaussian.py`.

## File usage and media requests — five silent failures

*All five produce wrong numbers rather than errors. Found 2026-09-06/07 while building a per-article
image-request measure.*

- ⭐ **`prop=globalusage` returns 0 for locally-uploaded files.** It tracks Commons files across wikis,
  so a non-free local upload (posters, album covers, logos) reports **zero** usage no matter how many
  pages embed it. Verified: `File:Skyfall poster.jpg` → `globalusage` 0, `fileusage` 1. A "used on
  exactly one page" filter built on `globalusage` therefore **silently drops precisely the lead images
  of popular articles**, because those are the non-free ones. Use `max(globalusage, fileusage)`, or the
  `imagelinks` table on the replica, which sidesteps it entirely.

- ⭐ **`prop=imageinfo` now returns `url` with tracking parameters appended** —
  `…/Foo.jpg?utm_source=en.wikipedia.org&utm_campaign=imageinfo&utm_content=original`. Any path built
  from that field verbatim **404s** against the AQS `mediarequests/per-file` endpoint. Strip the query
  string. The same `utm_*` tagging appears on `src` attributes in Parsoid HTML.

- ⭐ **Batching two list-valued props in one query silently drops one of them per title.** A 50-title
  request for `prop=fileusage|categories` returns some titles' `categories` and their `fileusage` in a
  *continuation* you never asked for, so those titles read as having zero usage. A single-prop batch
  of the same 50 titles does **not** reproduce it, which is why it survives testing. Either request one
  list-prop at a time, or follow `continue` to exhaustion.

- ⛔ **`prop=imageinfo`'s `url` is ALREADY percent-encoded — quoting it again 404s only the filenames
  with punctuation, which looks exactly like a data property.** Taking the path out of that `url` and
  passing it through `urllib.parse.quote(..., safe='')` double-encodes it, so AQS (which keys on the
  literal path) returns 404 for any name containing `(`, `'`, `*`, `,` or non-ASCII, and 200 for
  everything else. **The failure is selective, not total**, so it survives spot-checking and reads as
  a property of the upstream data rather than a bug in your code.

  ⚠ **Worked example of how badly this can mislead** (2026-09-06/07): 63 missing series were
  attributed to "AQS suppresses files below a request threshold", a plausible-sounding floor that was
  then written into two documents as a named bias in a published result. On investigation: **52 were
  the double-encoding defect, 9 were files that did not exist yet, 2 were uploaded later, and 0 were
  below any floor.** `NBA Finals logo (2022).svg` returns 200 with 113,977 requests on the literal
  path and 404 on the encoded one. The asymmetry that "confirmed" the bias story **reversed** once all
  absences were counted — it had been tracking filename punctuation, not traffic.

  ⇒ **Before attributing 404s to an upstream policy, round-trip one known-good path by hand.** An
  invented mechanism that explains your missing data is more dangerous than the missing data.

- ⭐ **Image requests never carry the article path.** Wikipedia serves
  `<meta name="referrer" content="origin-when-cross-origin">` and images come from
  `upload.wikimedia.org`, a different origin — so the `Referer` on an image request is
  `https://en.wikipedia.org/` and nothing more. This is why AQS offers project-level referer classes
  and not per-article media requests: it is a property of the data, not an API design choice, and no
  level of access recovers it. Per-article attribution requires either restricting to single-use files
  or joining to the pageview stream by client session.

## Replica schema: the link tables have been normalised

- **`imagelinks.il_to` → `il_target_id`, and `categorylinks.cl_to` → `cl_target_id`**, both now joining
  through the `linktarget` table. Any snippet older than the migration fails with
  `Unknown column ... in 'WHERE'`. This one at least fails loudly — but assume *every* `*_to` column in
  a link table has moved, and read `SHOW COLUMNS FROM <table>` rather than recalling the schema.

- **Start a usage aggregate from the smaller side.** `GROUP BY il_target_id` over ~10⁸ `imagelinks`
  rows is fine; joining `page` per row to filter first is not.
