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
