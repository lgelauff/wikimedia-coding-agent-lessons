# Wikimedia data-collection skills (Claude Cowork)

A small set of **Cowork** skills for collecting Wikimedia data the *right* way —
via official APIs, never by scraping rendered HTML.

These are written for **Claude Cowork**, not Claude Code. Same `SKILL.md` format,
but the runtime differs (see [Cowork notes](#cowork-notes)). They're kept separate
from the repo's `agent-tooling/` plugin, which is Claude-Code-specific (hooks,
permission model) and doesn't apply in Cowork.

## Skills

| Skill | Collects | Endpoint |
|---|---|---|
| `mediawiki-action-api` | article wikitext, revisions, metadata, categories, links, search | `…/w/api.php` |
| `wikidata-sparql` | structured facts / entity queries | `query.wikidata.org/sparql` |
| `wikimedia-analytics-api` | pageviews, editor/edit metrics (REST + AQS) | `wikimedia.org/api/rest_v1/…` |
| `phabricator-conduit` | tasks, comments, projects (Wikimedia Phabricator) | `phabricator.wikimedia.org/api/…` |

## Shared principles (every skill follows these)

1. **API-first, never scrape.** If an API exposes the data, use it — don't parse
   article HTML (it's truncated/unstable and wastes the servers' rendering).
2. **Identify yourself.** Wikimedia's User-Agent policy *requires* a descriptive
   UA with contact + purpose; generic/empty UAs get blocked. Use:
   `WikimediaResearch/1.0 (your@email; what you're doing)`.
3. **Be polite.** Honor pagination (`continue` / SPARQL `LIMIT/OFFSET` / Conduit
   cursors), respect rate limits, and on the Action API send **`maxlag=5`** so you
   back off automatically when the cluster is lagged. Add small delays in loops.
4. **Respect robots.txt** and each endpoint's documented limits/timeouts.
5. **Stamp provenance.** Write what you collected to a file with the endpoint, the
   exact params, and a UTC timestamp — so the result is reproducible.
6. **Deliver to `/outputs/`.** Collected data is the deliverable: write CSV/JSON to
   the mounted outputs folder, not scattered temp paths.

## Cowork notes

- **Network must be enabled.** Cowork VMs default to internet isolation; these
  skills make outbound HTTPS calls to Wikimedia endpoints, so the user must allow
  network access for the task (or wire an MCP connector if one exists). If a skill
  can't reach the endpoint, say so — don't fall back to scraping a cached page.
- **Mounted paths only.** Read inputs from a mounted folder; write to `/outputs/`.
  Don't assume host filesystem (`~`, `/Applications`, etc.).
- **Pre-installed packages only.** Examples use Python **stdlib** (`urllib`) or
  `curl` so they run without `pip install`. `pandas` is typically available for
  shaping output.
- **Autonomous.** No interactive prompts; the skill runs end-to-end and leaves a
  deliverable.

Refs: [Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) ·
[MediaWiki API](https://www.mediawiki.org/wiki/API:Main_page) ·
[Wikimedia REST/AQS](https://wikimedia.org/api/rest_v1/) ·
[WDQS](https://query.wikidata.org/) ·
[Conduit](https://phabricator.wikimedia.org/conduit/) ·
[UA policy](https://meta.wikimedia.org/wiki/User-Agent_policy).
