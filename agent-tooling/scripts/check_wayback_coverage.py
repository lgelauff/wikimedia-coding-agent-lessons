#!/usr/bin/env python3
"""Check Wayback-Machine coverage of a list of URLs (read-only availability API).

Project-agnostic: feed it URLs, it reports which are archived by archive.org and which
are not, so you can decide what to push to Save-Page-Now. Read-only — it never submits
captures (that's a separate, authenticated SPN2 step; do NOT use anonymous /save GETs).

Usage:
  python check_wayback_coverage.py urls.txt            # one URL per line
  some_command_that_emits_urls | python check_wayback_coverage.py -
  python check_wayback_coverage.py urls.txt --out coverage.csv --sleep 0.6

Out: a CSV (url, archived, closest_timestamp, snapshot_url, domain) + a stdout summary.

Lesson notes:
- Endpoint: http://archive.org/wayback/available?url=<urlencoded>. Returns
  archived_snapshots.closest.{available,timestamp,url}; empty = not archived.
- Send a descriptive User-Agent and rate-limit (one host = archive.org). ~0.6s between
  calls is polite for the availability API.
- Archiving the gaps is a DIFFERENT job: use the authenticated SPN2 API (free
  archive.org account -> S3 keys), which returns a job_id you poll for status. Anonymous
  `GET web.archive.org/save/<url>` is rate-limited, statusless, and unreliable — don't.
"""
import argparse, csv, json, re, sys, time, urllib.parse, urllib.request, collections

UA = "WikimediaAnalysis/1.0 (research; https://github.com/lgelauff/wikimedia-analysis)"


def available(u, ua):
    api = "http://archive.org/wayback/available?url=" + urllib.parse.quote(u, safe="")
    try:
        req = urllib.request.Request(api, headers={"User-Agent": ua})
        snap = (json.load(urllib.request.urlopen(req, timeout=30)).get("archived_snapshots") or {}).get("closest")
        if snap and snap.get("available"):
            return snap.get("timestamp", ""), snap.get("url", "")
    except Exception as e:
        return "ERROR", str(e)[:80]
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", help="file with one URL per line, or - for stdin")
    ap.add_argument("--out", default="wayback_coverage.csv")
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--ua", default=UA)
    a = ap.parse_args()
    fh = sys.stdin if a.urls == "-" else open(a.urls, encoding="utf-8")
    urls = sorted({l.strip() for l in fh if l.strip().startswith("http")
                   and "archive.org" not in l and "web.archive" not in l})
    print(f"checking {len(urls)} URLs", file=sys.stderr)
    rows, arch, err = [], 0, 0
    for i, u in enumerate(urls, 1):
        ts, snap = available(u, a.ua)
        ok = bool(ts) and ts != "ERROR"
        arch += ok; err += ts == "ERROR"
        dom = re.match(r"https?://([^/]+)", u)
        rows.append({"url": u, "archived": ok, "closest_timestamp": ts if ok else "",
                     "snapshot_url": snap if ok else "", "domain": dom.group(1).replace("www.", "") if dom else ""})
        if i % 25 == 0:
            print(f"  {i}/{len(urls)} — {arch} archived", file=sys.stderr)
        time.sleep(a.sleep)
    with open(a.out, "w", newline="", encoding="utf-8") as o:
        w = csv.DictWriter(o, fieldnames=["url", "archived", "closest_timestamp", "snapshot_url", "domain"])
        w.writeheader(); w.writerows(rows)
    miss = collections.Counter(r["domain"] for r in rows if not r["archived"] and r["closest_timestamp"] != "ERROR")
    print(f"\n{arch}/{len(urls)} archived ({arch/max(1,len(urls)):.0%}), {len(urls)-arch-err} not, {err} errors -> {a.out}")
    print("top not-archived domains:", dict(miss.most_common(10)))


if __name__ == "__main__":
    main()
