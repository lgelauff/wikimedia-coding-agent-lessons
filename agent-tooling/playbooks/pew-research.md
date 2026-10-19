# Playbook: Pew Research Center, machine-readable pages only

Route `pew-research-machine-readable` in `settings/mandated-services.json` (list A, Lodewijk,
2026-10-19). Pew publishes agent-facing versions of its pages and says so in its robots file.
This playbook is how an agent finds one, fetches it, cites it, and what it must not do. Read
it before the first Pew fetch of a session. Sources and dates are at the end; re-check them
when this file is older than six months.

## The budget comes first

- **At most 1 page per 10 s and 25 pages per day**, counting every request to
  `www.pewresearch.org`, including 404s and `llms.txt`. A blind probe that misses still spends
  budget, so never guess URLs in a loop.
- One request at a time. On a 429 or 5xx, stop for 10 minutes; on a repeat, stop for the day.
- Cache every response with its URL, fetch time and sha256. Never fetch the same URL twice in a day.
- Project User-Agent. No cookies, no login, no `Accept: text/markdown` negotiation (Pew has it
  switched off; the explicit URLs below are the supported door).

## What exists, and what the registry lets you fetch

Pew's platform code is public (`github.com/pewresearch`, plugins `prc-markdown-for-agents`
and `prc-pdf-extraction`). The URL shapes below come from that code and the live robots file.

| URL shape | What it is | Registry |
|---|---|---|
| `/llms.txt` | the agent index: About, Methods, topics, featured posts, datasets, staff, RLS links | allowed |
| `/religious-landscape-study/markdown` | the RLS directory: every RLS page with its markdown link | **denied** (the allow pattern needs a segment before `/markdown`); see *Open questions* |
| `/religious-landscape-study/<kind>/<slug>/markdown` | one RLS page as markdown, e.g. `state/alabama/markdown`, `religious-tradition/…/markdown` | allowed |
| `/<post-path>/topline` | Markdown, with YAML frontmatter, of an AI-OCR extraction of the post's **topline PDF** (question wording and marginals) | allowed |
| `/<post-path>/text` | the same extraction as plain text | allowed |
| `/<post-path>.md`, `/<post-path>/markdown` | the **article or report body** as markdown with frontmatter (title, date, authors, datasets, the topline extraction URL) | **denied**; see *Open questions* |
| ordinary HTML pages, topic pages, search, sitemaps, `/wp-admin/` | the human site | denied |

So under the current registry, **`/topline` and `/text` are survey toplines, not report
text.** They exist only for posts whose report materials include a topline PDF that Pew has
extracted. Otherwise `/text` answers `404` with the body `No extraction found for this post`,
and `/topline` answers the site's HTML 404 page. Observed 2026-10-19 on a 2026 short read
and a 2025 RLS report: both 404 on `/text`, and the short read 404 on `/topline` too.

## Recipe

1. **Fetch `/llms.txt` once per day at most** and keep it. Use it to find report and dataset
   URLs (featured posts are listed as `<post-path>.md`, so strip `.md` to get the post path).
2. **Otherwise, get the post path from your task**: a URL the human gave, a citation, or an
   OpenAlex or Crossref record. Do not browse topic pages or search to find one; both are denied.
3. **Survey numbers (marginals, exact question wording):** fetch `<post-path>/topline`. A 404
   means there is no extraction: stop. Do not try `/text` as well, it is the same extraction.
   The PDF itself is under `/wp-content/uploads/…` and is not covered: a human downloads it.
4. **Religious Landscape Study:** fetch the page you need as
   `/religious-landscape-study/<kind>/<slug>/markdown`. `<kind>` is one of `region`, `state`,
   `metro-area`, `religious-tradition`, `religious-family`, `religious-denomination`, or a
   demographic or belief dimension. Take the slug from the directory listing, which a human can
   open, or from a previous fetch. Do not guess slugs.
5. **Report prose:** not fetchable today. Ask the human for the text, or for the `.md` route
   (see *Open questions*).
6. **Datasets:** never fetched by an agent. They need a free Pew account, which a human uses to
   download the file. Then the dataset terms below apply to the local file.

## Read the extraction critically

The topline extraction is AI OCR of a PDF. The frontmatter carries the OCR provider, a
confidence score and the source PDF URL. Before a number goes into a paper, compare it with
the PDF, which a human downloads. Quote the question wording exactly as extracted, and note
that it is an extraction.

## Citing

Pew's terms (section 2) give the format:

> "Report Title." Pew Research Center, Washington, D.C. (Publication date) URL.

Cite the parent report's URL, not the `/topline` or `.md` URL; give the access date. When you
use dataset numbers, Pew's dataset terms also require this disclaimer, verbatim:

> "Pew Research Center bears no responsibility for the analyses or interpretations of the data
> presented here. The opinions expressed herein, including any implications for policy, are
> those of the author and not of Pew Research Center."

A translation must carry: "Pew Research Center has published the original content in English
but has not reviewed or approved this translation."

## Must not

- **Reproduce in principal part.** No mirroring, cataloguing or republishing of a report in
  full or "in principal part" without Pew's written permission (terms, section 1). Excerpts,
  quotes and numbers with a citation are fine.
- **Republish dataset files.** Data may be reproduced as excerpts only, never "in full or
  substantially in full" (section 13). American Trends Panel datasets have their own terms;
  read them before use.
- **Re-identify respondents.** No attempt to identify or derive information about individual
  respondents, and no linking of records with other datasets to do so. If a dataset contains
  identifying information, stop using it and tell the human, who notifies Pew.
- **Imply endorsement** of a cause, policy or position by Pew, or use Pew's marks.
- **Reuse third-party material as a stand-alone file.** Content attributed to another party
  (a partner's chart or photo) stays out.
- **Crawl.** No HTML pages, topic pages, search, sitemaps or wp-admin, and no URL guessing.

The robots file's `Content-Signal: ai-train=yes, search=yes, ai-input=yes` is Pew's consent
to AI use of the machine-readable pages. It does not lift the terms above.

## Open questions (Lodewijk)

1. **Allow the report body (`<post-path>.md` and `<post-path>/markdown`)?** It is the door Pew
   built for agents: llms.txt links reports that way, and Pew's code calls it a clean
   alternative to scraping HTML. Without it, agents cannot read report text at all. The patterns
   would be `/*.md` and `/*/markdown`, within the same 25 pages a day.
2. **Allow the RLS directory itself** (`/religious-landscape-study/markdown`)? The current
   pattern `/religious-landscape-study/*/markdown*` misses it, so agents cannot list RLS pages.
3. **Tighten `/*/text*`.** Patterns are prefix matches, so this one also admits an ordinary
   page whose slug starts with "text" (`/short-reads/2026/01/01/texting-while-driving/` is
   allowed by `webfetch_mandated.py`, checked 2026-10-19). `/*/text/` and an exact
   `/*/text` would be tighter, but the matcher has no end anchor; see `policies/webfetch_mandated.py`.

## Sources (all read 2026-10-19)

- `www.pewresearch.org/robots.txt` and `/llms.txt` (live, HTTP 200).
- `/religious-landscape-study/markdown` (live, 200, `text/markdown`).
- Terms of Use, `/about/terms-and-conditions/` (live; effective date 05/25/2018): sections 1, 2,
  3 and 13.
- Platform code via the GitHub REST API: `pewresearch/prc-markdown-for-agents` README;
  `pewresearch/prc-pdf-extraction` README, `includes/class-rewrite-rules.php` and
  `includes/class-content-discovery.php`. The live robots file's `Allow: /*/topline` shows that
  Pew's extraction URL slug is `topline` (the code's default is `extraction`).
- Probes on the approved route, 2026-10-19: two `/text` 404s and one `/topline` 404, as above.
