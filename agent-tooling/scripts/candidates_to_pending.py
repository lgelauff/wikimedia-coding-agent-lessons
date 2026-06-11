#!/usr/bin/env python3
"""candidates_to_pending.py — bridge discovered candidates into the vault intake.

The fetch + library-dedup stage is ALREADY built: research-vault `ingest.py
--collect` reads inbox/pending.txt blocks, dedups each against the vault index
by DOI/URL, and fetches the rest via the source-collection pipeline. So this
bridge does the one missing step: turn candidates.jsonl / scored.jsonl into
pending.txt blocks, then you run `ingest.py --collect`. No new fetcher.

Skips candidates already present in the target pending.txt (by DOI or URL) so
re-running is idempotent. With scored input, defaults to keep-only.

Usage:
    candidates_to_pending.py --in scored.jsonl --project 2026-polis-lit \
        --pending ~/Documents/GitHub/research-vault/inbox/pending.txt --added 2026-06-11
    candidates_to_pending.py --in candidates.jsonl --project X --all   # ignore verdict
Then:  cd research-vault && uv run ingest.py --collect
"""
import argparse
import json
import sys

BLOCK = ("---\n"
         "query:     {query}\n"
         "doi:     {doi}\n"
         "url:     {url}\n"
         "project:     {project}\n"
         "status:     pending\n"
         "added:     {added}\n")


def _query_line(c: dict) -> str:
    authors = ", ".join((c.get("authors") or [])[:3])
    return " ".join(str(x) for x in [c.get("title", ""), authors, c.get("year", "")] if x).strip()


def _existing_ids(pending_text: str) -> set[str]:
    ids = set()
    for line in pending_text.splitlines():
        s = line.strip()
        for k in ("doi:", "url:"):
            if s.startswith(k):
                v = s[len(k):].strip()
                if v:
                    ids.add(v.rstrip("/").lower())
    return ids


def to_blocks(candidates: list[dict], project: str, added: str,
              existing: set[str]) -> tuple[list[str], int]:
    blocks, skipped = [], 0
    for c in candidates:
        doi = (c.get("doi") or "").strip()
        url = (c.get("oa_pdf_url") or "").strip()
        if not doi and not url:
            skipped += 1
            continue
        if (doi and doi.rstrip("/").lower() in existing) or \
           (url and url.rstrip("/").lower() in existing):
            skipped += 1
            continue
        blocks.append(BLOCK.format(query=_query_line(c), doi=doi, url=url,
                                   project=project, added=added))
        if doi:
            existing.add(doi.rstrip("/").lower())
        if url:
            existing.add(url.rstrip("/").lower())
    return blocks, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="infile", required=True, help="candidates/scored JSONL")
    ap.add_argument("--project", required=True, help="project tag for the blocks")
    ap.add_argument("--added", required=True, help="date stamp (YYYY-MM-DD)")
    ap.add_argument("--pending", help="pending.txt to append to (default: stdout)")
    ap.add_argument("--all", action="store_true",
                    help="include all candidates (default: scored input -> keep only)")
    a = ap.parse_args()

    cands = [json.loads(ln) for ln in open(a.infile, encoding="utf-8") if ln.strip()]
    if not a.all and any("x_verdict" in c for c in cands):
        cands = [c for c in cands if c.get("x_verdict") == "keep"]

    existing = set()
    prior = ""
    if a.pending:
        try:
            prior = open(a.pending, encoding="utf-8").read()
            existing = _existing_ids(prior)
        except FileNotFoundError:
            pass

    blocks, skipped = to_blocks(cands, a.project, a.added, existing)
    text = "".join(blocks)
    if a.pending:
        with open(a.pending, "a", encoding="utf-8") as f:
            f.write(text)
        print(f"appended {len(blocks)} blocks ({skipped} skipped: dup/no-id) -> {a.pending}",
              file=sys.stderr)
        print("next: cd research-vault && uv run ingest.py --collect", file=sys.stderr)
    else:
        sys.stdout.write(text)
        print(f"# {len(blocks)} blocks ({skipped} skipped)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
