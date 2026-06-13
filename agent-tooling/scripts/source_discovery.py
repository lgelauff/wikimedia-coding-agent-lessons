#!/usr/bin/env python3
"""source_discovery.py — find scholarly sources for a research project.

The discovery stage of a literature-collection pipeline: turn search queries
into a deduplicated list of candidate papers (title, authors, year, DOI, an
open-access PDF URL when one exists, abstract, citation count). Write them as
JSONL for a downstream fetch + relevance-triage step to consume.

Generalized from wikimedia-analysis "AI effects" find_sources.py, but scholarly
instead of web: that tool LLM-generates queries then scrapes DuckDuckGo; this
one queries the scholarly graph (OpenAlex primary, Crossref optional), which
gives DOIs, OA PDF links, abstracts, and citation counts — the right backend
for an academic lit review. LLM query-generation and relevance scoring layer on
top (separate step); this core is deterministic and needs no API key.

Polite by construction: descriptive UA, a contact mailto for the API "polite
pool", and per-host rate limiting. Dependency-light (stdlib urllib only).

Usage:
    source_discovery.py --query "polis deliberation clustering" --out cand.jsonl
    source_discovery.py --queries-file queries.txt --per-query 25 --from-year 2015
    source_discovery.py --query "vTaiwan" --open-access-only --crossref
    echo "wiki survey opinion matrix" | source_discovery.py

Each output line is one candidate:
  {title, authors, year, doi, oa_pdf_url, source_api, query, abstract,
   cited_by_count, openalex_id}
"""
import argparse
import html
import ipaddress
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

OPENALEX = "https://api.openalex.org/works"
CROSSREF = "https://api.crossref.org/works"
MAILTO = os.environ.get("CROSSREF_MAILTO") or os.environ.get("DISCOVERY_MAILTO") or "lodewijk@stanford.edu"
UA = f"WikimediaAnalysis/1.0 (research; mailto:{MAILTO}; https://github.com/lgelauff/wikimedia-analysis)"
RATE_SECONDS = 1.0
TIMEOUT = 30

_last_per_host: dict[str, float] = {}


def _rate_limit(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc
    wait = _last_per_host.get(host, 0) + RATE_SECONDS - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_per_host[host] = time.time()


def _get_json(url: str) -> dict:
    _rate_limit(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, data: bytes | None = None) -> str:
    _rate_limit(url)
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex stores abstracts as an inverted index {word: [positions]}."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _authors_openalex(work: dict) -> list[str]:
    return [a.get("author", {}).get("display_name", "")
            for a in work.get("authorships", []) if a.get("author")]


def search_openalex(query: str, per_query: int = 25, from_year: int | None = None,
                    open_access_only: bool = False) -> list[dict]:
    """Search OpenAlex works; return normalized candidate dicts."""
    params = {"search": query, "per-page": min(per_query, 200), "mailto": MAILTO}
    filters = []
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    if open_access_only:
        filters.append("is_oa:true")
    if filters:
        params["filter"] = ",".join(filters)
    url = f"{OPENALEX}?{urllib.parse.urlencode(params)}"
    out = []
    for w in _get_json(url).get("results", []):
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        oa = (w.get("open_access") or {}).get("oa_url")
        out.append({
            "title": w.get("title") or w.get("display_name") or "",
            "authors": _authors_openalex(w),
            "year": w.get("publication_year"),
            "doi": doi,
            "oa_pdf_url": oa,
            "url": oa or (f"https://doi.org/{doi}" if doi else None),
            "source_api": "openalex",
            "query": query,
            "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
            "cited_by_count": w.get("cited_by_count", 0),
            "openalex_id": (w.get("id") or "").replace("https://openalex.org/", "") or None,
        })
    return out


def search_crossref(query: str, per_query: int = 25, from_year: int | None = None) -> list[dict]:
    """Search Crossref works; return normalized candidate dicts (no abstracts/OA)."""
    params = {"query": query, "rows": min(per_query, 100), "mailto": MAILTO}
    if from_year:
        params["filter"] = f"from-pub-date:{from_year}-01-01"
    url = f"{CROSSREF}?{urllib.parse.urlencode(params)}"
    out = []
    for w in _get_json(url).get("message", {}).get("items", []):
        authors = [f"{a.get('given','')} {a.get('family','')}".strip()
                   for a in w.get("author", [])] if w.get("author") else []
        year = None
        dp = (w.get("issued") or {}).get("date-parts") or [[None]]
        if dp and dp[0]:
            year = dp[0][0]
        title = (w.get("title") or [""])[0]
        doi = w.get("DOI")
        out.append({
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "oa_pdf_url": None,
            "url": f"https://doi.org/{doi}" if doi else w.get("URL"),
            "source_api": "crossref",
            "query": query,
            "abstract": w.get("abstract", ""),
            "cited_by_count": w.get("is-referenced-by-count", 0),
            "openalex_id": None,
        })
    return out


_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")


_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")


def _host_is_blocked(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # ordinary hostname; DNS-rebind SSRF is the fetcher's job
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def _safe_public_url(url: str) -> bool:
    """http/https to a non-private, non-metadata host. First-line SSRF guard
    before a scraped URL is emitted toward the fetcher."""
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and not _host_is_blocked(p.hostname or "")


def _clean(text: str) -> str:
    """Collapse newlines/control chars so a scraped value can't inject a new
    field into a downstream line-oriented format (e.g. pending.txt `url:`)."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", text or "").strip()


def _ddg_unwrap(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        q = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href).query
        uddg = urllib.parse.parse_qs(q).get("uddg")
        if uddg:
            return urllib.parse.unquote(uddg[0])
    return href if href.startswith("http") else "https:" + href


def search_web(query: str, per_query: int = 25) -> list[dict]:
    """Grey-lit / non-academic discovery via DuckDuckGo HTML (no API key).

    Catches reports, press, NGO/gov docs, blogs — sources the scholarly graph
    misses. Returns the same candidate schema (no DOI/year/abstract); the
    `url` is the fetch target the downstream bridge uses.
    """
    body = urllib.parse.urlencode({"q": query}).encode()
    page = _get_text("https://html.duckduckgo.com/html/", data=body)
    out, matched = [], 0
    for href, title_html in _DDG_RESULT.findall(page):
        matched += 1
        link = _ddg_unwrap(href)
        if not _safe_public_url(link):       # SSRF guard: scheme + private/metadata hosts
            continue
        title = _clean(html.unescape(_TAGS.sub("", title_html)))
        out.append({
            "title": title, "authors": [], "year": None, "doi": None,
            "oa_pdf_url": None, "url": link, "source_api": "web",
            "query": query, "abstract": "", "cited_by_count": 0, "openalex_id": None,
        })
        if len(out) >= per_query:
            break
    if page.strip() and matched == 0:        # markup drift / 429 / block page
        print(f"WARN web backend: non-empty page but 0 results parsed for {query!r} "
              "(DuckDuckGo markup change or rate-limit?)", file=sys.stderr)
    return out


def _dedup_key(c: dict) -> str:
    if c.get("doi"):
        return "doi:" + c["doi"].lower()
    if c.get("openalex_id"):
        return "oa:" + c["openalex_id"]
    if c.get("url"):
        return "url:" + c["url"].rstrip("/").lower()
    return "title:" + (c.get("title") or "").strip().lower()


def _call_backend(name: str, q: str, per_query: int, from_year: int | None,
                  open_access_only: bool) -> list[dict]:
    if name == "openalex":
        return search_openalex(q, per_query, from_year, open_access_only)
    if name == "crossref":
        return search_crossref(q, per_query, from_year)
    if name == "web":
        return search_web(q, per_query)
    raise ValueError(f"unknown backend: {name!r} (openalex|crossref|web)")


def run(queries: list[str], per_query: int = 25, from_year: int | None = None,
        open_access_only: bool = False, use_crossref: bool = False,
        max_total: int | None = None, backends: list[str] | None = None) -> list[dict]:
    """Run all queries through the named backends; dedup; return candidates.

    backends: subset of ["openalex","crossref","web"] (default ["openalex"]).
    use_crossref is kept for back-compat — it appends "crossref" if not listed.
    """
    names = list(backends) if backends else ["openalex"]
    if use_crossref and "crossref" not in names:
        names.append("crossref")
    seen: set[str] = set()
    results: list[dict] = []
    for q in queries:
        for name in names:
            try:
                hits = _call_backend(name, q, per_query, from_year, open_access_only)
            except Exception as e:  # one bad query/backend shouldn't sink the run
                print(f"WARN backend {name} failed for {q!r}: {e}", file=sys.stderr)
                continue
            for c in hits:
                k = _dedup_key(c)
                if k in seen:
                    continue
                seen.add(k)
                results.append(c)
                if max_total and len(results) >= max_total:
                    return results
    return results


def _read_queries(args) -> list[str]:
    qs = list(args.query or [])
    if args.queries_file:
        with open(args.queries_file, encoding="utf-8") as f:
            qs += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not qs and not sys.stdin.isatty():
        qs += [ln.strip() for ln in sys.stdin if ln.strip()]
    return qs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", action="append", help="a search query (repeatable)")
    ap.add_argument("--queries-file", help="file with one query per line (# comments ok)")
    ap.add_argument("--out", help="write JSONL here (default: stdout)")
    ap.add_argument("--per-query", type=int, default=25,
                    help="max results per query per backend (single page; capped by the "
                         "API at 200 OpenAlex / 100 Crossref — no cursor paging)")
    ap.add_argument("--from-year", type=int, help="only works published on/after this year")
    ap.add_argument("--open-access-only", action="store_true", help="OpenAlex: OA works only")
    ap.add_argument("--backends", default="openalex",
                    help="comma list of openalex,crossref,web (default: openalex). "
                         "Add 'web' for grey-lit/press/reports the scholarly graph misses.")
    ap.add_argument("--crossref", action="store_true", help="(compat) also query Crossref")
    ap.add_argument("--max-total", type=int, help="stop after this many deduped candidates")
    a = ap.parse_args()

    queries = _read_queries(a)
    if not queries:
        ap.error("no queries (use --query / --queries-file / stdin)")

    names = [b.strip() for b in a.backends.split(",") if b.strip()]
    cands = run(queries, a.per_query, a.from_year, a.open_access_only,
                a.crossref, a.max_total, backends=names)
    lines = [json.dumps(c, ensure_ascii=False) for c in cands]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        print(f"{len(cands)} candidates -> {a.out}", file=sys.stderr)
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
