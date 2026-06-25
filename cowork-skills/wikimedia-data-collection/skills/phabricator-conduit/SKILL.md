---
name: phabricator-conduit
description: >-
  Collect tasks, comments, and project data from Wikimedia Phabricator via the
  Conduit API (maniphest.search, transaction.search, project.search, user.search)
  — filter tasks by project/status/assignee/date, page through results, and pull
  history. Use whenever you need data from phabricator.wikimedia.org instead of
  scraping the task web UI.
---

# Phabricator Conduit API — collect tasks & history

Query Phabricator's API, not its HTML. Prefer the modern **`*.search`** methods
(paginated, constraint-based) over legacy `maniphest.query`.

**Prerequisites (Cowork):** network access enabled; `/outputs/` mounted; a Conduit
**API token** available to the task as an env var (do NOT hardcode it). Token
comes from Phabricator → Settings → *Conduit API Tokens*.

## Endpoint & shape
`https://phabricator.wikimedia.org/api/<method>`, POST form-encoded, JSON back.
Auth: pass `api.token`. Response: `{result:{data:[{id,phid,fields:{…}}],
cursor:{after}}}`.

## Key methods
- **`maniphest.search`** — tasks. Constraints: `projects[]`, `statuses[]`,
  `assigned[]`, `authorPHIDs[]`, `priorities[]`, `query` (fulltext),
  `modifiedStart`/`createdStart` (unix ts). `order=newest`. `attachments[projects]=1`
  to get tags inline.
- **`transaction.search`** — a task's comments/history (`objectIdentifier=Txxxx`).
- **`project.search`** / **`user.search`** — resolve a project/user *name* → PHID
  (you filter by PHID, not name, so resolve first).
- **`phid.lookup`** — map `Txxxx`/names → PHIDs.

## Pagination
`limit` max 100; loop passing `result.cursor.after` until it's `null`.

## Pattern
```python
import os, json, urllib.parse, urllib.request, time
BASE = "https://phabricator.wikimedia.org/api"
TOK  = os.environ["PHABRICATOR_TOKEN"]          # provided to the task; never hardcode
UA   = "WikimediaResearch/1.0 (you@example.org; collecting task data)"
def conduit(method, **params):
    params["api.token"] = TOK
    rows, after = [], None
    while True:
        p = dict(params)
        if after: p["after"] = after
        body = urllib.parse.urlencode(p, doseq=True).encode()
        req = urllib.request.Request(f"{BASE}/{method}", data=body,
                                     headers={"User-Agent": UA})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        if d.get("error_code"):
            raise RuntimeError(f"{d['error_code']}: {d['error_info']}")
        res = d["result"]; rows += res["data"]
        after = res.get("cursor", {}).get("after")
        if not after: break
        time.sleep(0.3)
    return rows
# open tasks in a project (resolve the project PHID first via project.search)
tasks = conduit("maniphest.search",
                **{"constraints[projects][]": "PHID-PROJ-xxxxxxxx",
                   "constraints[statuses][]": "open", "order": "newest", "limit": 100})
json.dump([{ "id": t["id"], **t["fields"] } for t in tasks],
          open("/outputs/open_tasks.json", "w"), indent=2, default=str)
```

## Secret handling (important)
- Read the token from an **env var the task is given**; never write it into the
  skill or a deliverable.
- A bare `-d api.token=…` exposes the token in the process list — prefer feeding it
  from an env var as above (or `arc call-conduit`, which reads `~/.arcrc`).

## Don'ts
- Don't scrape `phabricator.wikimedia.org/Txxxxx` HTML — use `maniphest.search`.
- Don't use legacy `*.query` methods. Don't print/commit the token. Don't ignore
  the cursor (you'll miss most results).

Reference: [Conduit](https://phabricator.wikimedia.org/conduit/) ·
[maniphest.search](https://phabricator.wikimedia.org/conduit/method/maniphest.search/).
