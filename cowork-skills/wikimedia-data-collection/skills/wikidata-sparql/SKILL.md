---
name: wikidata-sparql
description: >-
  Collect structured facts from Wikidata via the Wikidata Query Service (WDQS)
  SPARQL endpoint — entities matching criteria, properties, relationships,
  cross-wiki identifiers, counts. Use whenever you need STRUCTURED/queryable data
  ("all X that are Y", "the population/coordinates/identifiers of …") rather than
  prose from an article. The structured-data counterpart to the Action API.
---

# Wikidata SPARQL (WDQS) — collect structured facts

Query the knowledge graph directly instead of scraping infoboxes. Returns exactly
the rows you asked for.

**Prerequisites (Cowork):** network access enabled; `/outputs/` mounted.

## Endpoint & shape
`https://query.wikidata.org/sparql`, GET or POST, param `query=<SPARQL>`, header
`Accept: application/sparql-results+json`. Send a descriptive **User-Agent**
(required; WDQS blocks generic agents). Results: `results.bindings[]`, each a map
of `var → {type, value}`.

## Limits that matter
- **60-second query timeout** — keep queries selective; filter early, `LIMIT` your
  result set, avoid unbounded `?s ?p ?o`.
- **Rate-limited per-agent** — one query at a time, small delays; on HTTP 429 back
  off and retry.
- Prefer the **`wdt:`/`wd:` truthy** predicates for simple facts; use labels via
  the label service.

## Pattern
```python
import urllib.parse, urllib.request, json
EP = "https://query.wikidata.org/sparql"
UA = "WikimediaResearch/1.0 (you@example.org; collecting structured facts)"
SPARQL = """
SELECT ?city ?cityLabel ?population WHERE {
  ?city wdt:P31 wd:Q515 ;          # instance of: city
        wdt:P1082 ?population ;     # population
        wdt:P17 wd:Q55 .           # country: Netherlands
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} ORDER BY DESC(?population) LIMIT 100
"""
req = urllib.request.Request(EP + "?" + urllib.parse.urlencode({"query": SPARQL}),
        headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
rows = json.load(urllib.request.urlopen(req, timeout=70))["results"]["bindings"]
data = [{k: v["value"] for k, v in r.items()} for r in rows]
json.dump({"endpoint": EP, "query": SPARQL, "rows": data},
          open("/outputs/nl_cities.json", "w"), indent=2)
```

## Tips
- Build/debug queries interactively at `query.wikidata.org`, then paste the final
  SPARQL into the skill.
- For big result sets, page with `LIMIT`/`OFFSET` and ORDER BY a stable key, or
  narrow the constraints — don't try to pull the whole graph.
- Resolve a name → QID first via the Action API (`list=search`) or
  `wbsearchentities` if you only have a label.

## Don'ts
- Don't scrape Wikidata entity HTML pages — query the endpoint.
- Don't run unbounded queries (they'll time out at 60s). Don't omit the UA.

Reference: [WDQS](https://query.wikidata.org/) ·
[SPARQL examples](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/queries/examples) ·
[WDQS user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual).
