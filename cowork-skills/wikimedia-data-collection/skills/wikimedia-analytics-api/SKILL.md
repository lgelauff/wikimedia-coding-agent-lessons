---
name: wikimedia-analytics-api
description: >-
  Collect Wikimedia traffic and contribution metrics via the public REST
  Analytics (AQS) API — per-article and aggregate pageviews, unique devices,
  edits, editors, and registered-user counts, by project / time range /
  granularity / access method. Use whenever you need quantitative time-series
  about wiki readership or editing, instead of any dashboard scraping.
---

# Wikimedia Analytics (AQS) REST API — collect metrics

Public, key-free time-series metrics. No scraping of Stats/Grafana — hit the REST
endpoint and get clean JSON.

**Prerequisites (Cowork):** network access enabled; `/outputs/` mounted.

## Endpoint & shape
Base: `https://wikimedia.org/api/rest_v1/metrics/...`, GET, JSON.
Send a descriptive **User-Agent** (required). Path params are slash-delimited;
**URL-encode article titles** (spaces → `_` then percent-encode `/`).

## The common series
- **Per-article pageviews:**
  `/pageviews/per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}`
  e.g. `en.wikipedia/all-access/user/Albert_Einstein/daily/20240101/20241231`
- **Aggregate pageviews:** `/pageviews/aggregate/{project}/{access}/{agent}/{granularity}/{start}/{end}`
- **Top articles:** `/pageviews/top/{project}/{access}/{year}/{month}/{day}`
- **Unique devices:** `/unique-devices/{project}/{access-site}/{granularity}/{start}/{end}`
- **Edits / editors / registered users:** `/edits/aggregate/…`, `/editors/aggregate/…`,
  `/registered-users/new/…` under `…/metrics/`.

Params: `access` ∈ `all-access|desktop|mobile-web|mobile-app`; `agent` ∈
`user|spider|automated|all-agents` (use **`user`** to exclude bots);
`granularity` ∈ `daily|monthly`; dates `YYYYMMDD` (or `YYYYMMDDHH`).

## Pattern
```python
import urllib.parse, urllib.request, json, csv
UA = "WikimediaResearch/1.0 (you@example.org; collecting pageview metrics)"
def pageviews(project, article, start, end, access="all-access", agent="user"):
    art = urllib.parse.quote(article.replace(" ", "_"), safe="")
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"{project}/{access}/{agent}/{art}/daily/{start}/{end}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=30))["items"]
items = pageviews("en.wikipedia", "Albert Einstein", "20240101", "20241231")
with open("/outputs/einstein_pageviews.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["date", "views"])
    for it in items: w.writerow([it["timestamp"][:8], it["views"]])
```

## Tips
- **404 = no data** for that article/range (e.g. before 2015-07 for pageviews, or
  a title that redirects) — handle it, don't treat as failure.
- Pageview data starts **2015-07-01**; older "legacy" counts use a different
  endpoint and aren't comparable.
- One request already returns the whole time range — no pagination; just loop over
  multiple articles with a small delay.

## Don'ts
- Don't scrape stats.wikimedia.org / pageviews.wmcloud.org — they're front-ends to
  this same API. Don't omit the User-Agent. Don't mix `agent=all-agents` with
  `user` across a dataset (bots inflate counts).

Reference: [REST API](https://wikimedia.org/api/rest_v1/) ·
[AQS pageviews](https://www.mediawiki.org/wiki/Wikimedia_REST_API#Pageviews_data) ·
[Analytics metrics docs](https://doc.wikimedia.org/analytics-api/).
