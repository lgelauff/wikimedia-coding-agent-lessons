---
name: mediawiki-action-api
description: >-
  Collect content and metadata from any Wikimedia wiki (Wikipedia, Commons,
  Wiktionary, Meta…) via the MediaWiki Action API — article wikitext, revisions
  and revision history, page metadata, categories, links, backlinks, and search
  results. Use whenever you need data FROM a wiki page or set of pages and would
  otherwise be tempted to open/scrape the article HTML. API-first, never scrape.
---

# MediaWiki Action API — collect wiki content & metadata

Get structured data from a wiki's `api.php` instead of parsing rendered HTML
(which truncates and changes). Read-only collection; no login needed for public
data.

**Prerequisites (Cowork):** network access enabled; an `/outputs/` folder mounted
for the deliverable.

## Endpoint & shape
`https://<wiki>/w/api.php` (e.g. `https://en.wikipedia.org/w/api.php`), GET,
`format=json&formatversion=2`. Everything is `action=query` + a module.

**Always send these params:** `format=json`, `formatversion=2`, `maxlag=5`
(auto-backoff when the cluster is lagged — retry after the returned wait), and a
descriptive `User-Agent` header (required — see README).

## The common collections
- **Wikitext of a page:** `action=query&prop=revisions&rvprop=content&rvslots=main&titles=<Title>`
- **Revision history:** `prop=revisions&rvprop=ids|timestamp|user|comment&rvlimit=max` (paginate via `continue`)
- **Page metadata / pageprops:** `prop=info|pageprops&inprop=url`
- **Categories of a page:** `prop=categories&cllimit=max`
- **Links out / backlinks:** `prop=links&pllimit=max` · backlinks: `list=backlinks&bltitle=<Title>`
- **Members of a category:** `list=categorymembers&cmtitle=Category:<X>&cmlimit=max`
- **Full-text search:** `list=search&srsearch=<query>&srlimit=max`
- **Resolve redirects:** add `redirects=1`.

## Pagination (do not skip)
Responses include a `continue` object when there's more. Loop: merge `continue`
params into the next request until `continue` is absent. Use `…limit=max` to
minimize round-trips. Add a small delay between pages.

## Minimal run (Python stdlib — no pip needed)
```python
import urllib.parse, urllib.request, json, time
API = "https://en.wikipedia.org/w/api.php"
UA  = "WikimediaResearch/1.0 (you@example.org; collecting article metadata)"
def query(**params):
    params.update(format="json", formatversion=2, maxlag=5)
    out, cont = [], {}
    while True:
        q = {**params, **cont}
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                     headers={"User-Agent": UA})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        out.append(d.get("query", {}))
        if "continue" not in d: break
        cont = d["continue"]; time.sleep(0.5)
    return out
# e.g. category members → write deliverable to /outputs/
pages = [p["title"] for r in query(list="categorymembers",
         cmtitle="Category:Physics", cmlimit="max") for p in r.get("categorymembers", [])]
json.dump({"endpoint": API, "params": "categorymembers Category:Physics",
           "pages": pages}, open("/outputs/physics_pages.json", "w"), indent=2)
```

## Don'ts
- Don't fetch the article URL and parse HTML — use `prop=revisions`/`extracts`.
- Don't ignore `maxlag` / `continue`. Don't hammer; add delays.
- Don't use a generic User-Agent (Wikimedia blocks them).

Reference: [API:Main page](https://www.mediawiki.org/wiki/API:Main_page) ·
[API:Query](https://www.mediawiki.org/wiki/API:Query) ·
[maxlag](https://www.mediawiki.org/wiki/Manual:Maxlag_parameter).
