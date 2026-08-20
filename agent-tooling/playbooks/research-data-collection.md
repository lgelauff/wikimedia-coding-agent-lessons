# Playbook: organizing a research data collection

Hand this document to an LLM and it should know how to **build and maintain** a
research project's data collection — heterogeneous data (text, PDFs, quantitative
datasets, scraped pages, scripts) organized so that both a human and an LLM can
navigate it, extend it, and trust it. It is a *shape and a set of operations*,
not a fixed folder list; you and the LLM fill in the specifics per project.

It is the research-data analog of the "wiki, not RAG" pattern: don't dump every
file into one folder (or a vector store) and hope to retrieve. **Curate** a
navigable, provenance-stamped structure where a small committed catalog is the
source of truth and everything else is reproducible from it.

## Core idea

A research collection has two populations of bytes that must never be confused:

- **Reproducible bytes** — anything you could re-fetch or re-derive: raw
  downloads, extracted text, cleaned tables. Large, disposable, *gitignored*.
- **Source-of-truth bytes** — the curated metadata that says what exists, where
  it came from, and what it means: the catalog, the schema, the provenance log.
  Small, hand/LLM-curated, *committed*, **never silently overwritten**.

Get that split right and the collection is trustworthy and an LLM can safely
operate on it. Get it wrong and you have a folder of mystery files.

## Architecture — four layers

```
raw/         immutable captures + a .meta.json sidecar each      [gitignored]
processed/   derived from raw via scripts; regenerable           [gitignored]
catalog/     COMMITTED source of truth — what exists & what it means
synthesis/   the human+LLM outputs: notes, review, findings      [committed]
```

1. **raw/** — every capture stored verbatim with a provenance sidecar
   (`source`, `fetched_at`, `sha256`, `content_type`). Append-only; you never
   edit a raw artifact, you re-capture it.
2. **processed/** — cleaned/extracted/normalized data, produced *only* by
   scripts from `raw/`. Deletable at any time because it rebuilds.
3. **catalog/** — the committed spine:
   - `sources.json` — one record per source (stable id/citekey, citation,
     DOI/URL, type, which raw artifact backs it, relevance/notes). CSL-JSON if
     bibliographic.
   - `schema/` — a data dictionary per quantitative dataset (columns, units,
     types, codebook, known caveats). *This is the part generic note-wikis lack
     and research requires.*
   - `claims.md` (or similar) — claims ↔ evidence inventory for the argument the
     data supports.
4. **synthesis/** — the "wiki pages": literature review, per-source notes, the
   document being produced. Prose, citing catalog ids.

## Operations — the verbs you run on the layers

**Ingest** — grow the collection. discover → dedup against the catalog → fetch
into `raw/` (with sidecar) → register in `catalog/`. Never fetch what the
catalog already has. Stamp provenance on the way in. (Reference implementation:
the `source_discovery` → `score_candidates` → `candidates_to_pending` pipeline
feeding `research-vault/ingest.py`.)

**Rescue an unreachable source** — the standard move when ingest fails: the
host isn't sanctioned, returns 4xx/5xx, rate-limits, geo-blocks, or the fetch
just died. **Always propose this before parking a source as "unreachable"** —
in practice it converts most dead ends into citable sources.

1. **Check existing coverage first** (read-only Wayback availability API —
   `check_wayback_coverage.py`). A good snapshot means no capture is needed.
2. **Ask the Internet Archive to capture it** — Save Page Now 2, authenticated
   with archive.org S3 keys (`spn2_save.py`). IA's *own* crawler fetches the
   page from IA's infrastructure, so nothing is scraped from your machine; that
   is precisely why it also succeeds on hosts that blocked or rate-limited you.
   `--capture-all` archives error responses when the failure is the evidence.
3. **Read and cite the snapshot.** `web.archive.org` is a stable, citable host,
   and snapshot citation is standard practice. Catalog BOTH URLs (original +
   snapshot) with an access-method field, and log the capture like any fetch.

This is a legitimate pattern, not a way around source governance: a public
archive is archiving a public page, and the citation is more durable than the
original. Two hard limits: it **cannot** defeat a paywall or login that IA also
lacks (that stays a shopping-list item for a human with access), and you must
**never submit URLs carrying personal data, credentials, session tokens, or
internal addresses** — an SPN2 capture is a permanent, public, outward-facing
write. Public pages only, and name the URL before capturing it.

**Query** — use the collection without growing it. "Do we already hold X?"
(check the catalog first, always), "what do our sources say about Y?" An LLM
reads `catalog/` + `synthesis/`, not the raw pile.

**Lint / Validate** — keep it honest. Run these checks and report violations:
- every `catalog/` entry points to a real `raw/` artifact with provenance;
- no orphan files in `raw/`/`processed/` that no catalog entry references;
- every quantitative dataset validates against its `schema/` dictionary;
- **reproducibility**: `processed/` regenerates from `raw/` + `scripts/` with no
  manual steps (the defensibility check — research data must be re-derivable).

## Meta-files (the load-bearing few)

- **AGENTS.md** — how an agent should ingest/query/lint *this* collection: the
  concrete commands, the source-of-truth rules, what's committed vs gitignored,
  and "when the catalog and a new capture conflict, ASK — never overwrite."
- **INDEX.md** — human-readable catalog/table of contents: what's collected, by
  id, with status.
- **LOG.md** — running provenance + decisions: what was searched, what was
  added/rejected and why (a search log, generalized). The collection's history.

## The one invariant

> `raw/` is reproducible and disposable. `processed/` must regenerate from
> `raw/` + `scripts/` with no manual steps. `catalog/` is the source of truth,
> committed, and is never auto-overwritten — on a conflict, surface it and ask.

If a project honors only one rule from this document, it is that one. Everything
else (exact folder names, file formats, which APIs) is intentionally abstract —
you and the LLM co-create the specifics, project by project. An adapter (a
Claude skill) can supply the triggering and the concrete commands; this playbook
is the method.
