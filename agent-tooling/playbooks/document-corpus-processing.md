# Playbook — processing a document corpus with a rate-limited LLM

*Written 2026-08-02 from the wikipedia-drop-2026 curriculum corpus: **117 documents, 12.5M
characters** — 71 TIMSS country chapters, 35 national/provincial curricula, 10 Japanese MEXT
sections, 1 UK specification. Status: **DRAFT — pattern validated in parts, not yet
end-to-end.***

*Numbers are labelled: **[corpus]** = measured on that corpus (evidence in its
`private/curriculum-work-register.md`); **[platform]** = from provider documentation, not
measured here. Reviewed cold 2026-08-02; the review caught two figures stated as measured that
had no artifact behind them — both are now recorded upstream and cited.*

## The shape of the problem

You have a pile of PDFs (government documents, reports, primary sources) and you want
structured data out of them. Three costs, and they belong on **different machines**:

| stage | bound by | where it belongs |
|---|---|---|
| text extraction / OCR | CPU | **local**, overnight, checkpointed |
| LLM extraction | **request rate**, not tokens | **batched on infrastructure without the cap** |
| judgment, synthesis, review | quality | your main agent — not delegated |

The mistake is treating this as one job. Extraction is cheap and parallel; LLM calls are the
scarce resource; judgment shouldn't be outsourced at all.

## Rule 1 — ship derived text, never the source corpus

The LLM only ever sees extracted text. Extract locally, upload `.txt`.

- 12.5 MB of text vs ~150 MB of PDFs (measured, this corpus)
- nothing to purge afterwards but a scratch directory
- and it sidesteps the question of whether the source documents belong on shared
  infrastructure at all

**Ask that question anyway.** WMF Toolforge's norm is *public wiki data*. Public government
documents are not participant data — but they are not wiki data either. Using a shared tool
account to dodge a rate limit is a relationship decision, not a technical one. Human's call.

## Rule 2 — the cap is on REQUESTS, so batch items per request

**Check which resource your provider meters — this rule inverts if you get it wrong.**

- **Request-metered** (e.g. WMF LiftWing chat: ~90 req/h anonymous **[platform]**, while the
  same host serves classic ML `:predict` models at ~50,000/h — a 500× gap that is easy to
  conflate). Here, batching 10–20 numbered items per prompt turns a 3-hour job into 20 minutes.
  Number the items and require the number back, so a short or misaligned answer is detectable
  rather than silently shifting every label by one.
- **Token-metered** (most commercial APIs). Batching buys you nothing on cost and can *hurt* —
  oversized prompts blow context and a failed batch loses every item in it. Optimise for
  smaller, retryable units instead.

> **WMF-specific aside, ignore without Toolforge:** running from a Toolforge tool account lifts
> the LiftWing cap (`AGENT_RATE_DISABLE=1`) — the documented escalation path, and the reason a
> remote batch tier is worth building at all. There is no general equivalent; on a commercial
> API, relocating compute does not change your bill.

## Rule 3 — target sections before you process everything

On this corpus, **four documents held 1.48M of the 2.34M *non-TIMSS* tokens** **[corpus]** —
a subset of the 3.1M-token whole, not the same scope as the 12.5M-character figure above — and
were mostly irrelevant: a
580-page framework spanning ages 3–18, a 626-page all-subject curriculum. Extracting only the
relevant sections cuts the job 5–10× **and improves quality**, because the model isn't wading
through mathematics to find literary works.

Corollary: check whether the source already solved this for you. One province published
**per-subject files**, so the targeting problem disappeared — `Literatura.pdf` was right there.

## Rule 4 — structure assumptions break across sources

The single most expensive error in this corpus. A 71-chapter set from one publisher looked
uniform; it had **at least three dialects** of the same section boundary (heading, exhibit
table, absent entirely). A regex tuned on one country silently produced **zero output for four
of six countries** while the run exited 0 and reported "0 parse failures".

- Split on the **coarsest** boundary that all sources share; let the model tag the finer
  structure per row (and allow `unspecified` as a real value).
- Verify a parser against **several** sources before a bulk run, not one.
- A stage that produces nothing must be **loud**, not a clean exit.

## Rule 5 — quality gates that catch *confidently wrong* output

Confidence scores don't catch the failure modes that matter. Two cheap gates that do:

- **Wrong language pack**: OCR with `eng` on Spanish text yields readable prose with *every*
  diacritic corrupted (`Desempeños`→`Desempefios`, `búsqueda`→`bUsqueda`). Tesseract reports
  high confidence throughout. Gate: **diacritic density** below a plausible threshold ⇒ refuse.
- **Merged columns**: OCR of a two-column table welds the columns together, destroying the
  row association you actually wanted. Symptom: the vertical rule read as literal `|`
  characters. Gate: `|` frequency above a threshold ⇒ warn.

Generalise: for each known failure mode, find a **statistic of the output** that is cheap and
fails loudly. A pass that reports no error rate has traded cost for unmeasured risk.

## Rule 6 — LLMs normalise your delimiters

Asking for tab-separated output produced space-separated output — **every row unparseable,
21 of 21 on the first live call** **[corpus]**. **Pipes survive; tabs do not.** Parse
defensively anyway (fallback splitters, a regex anchored on an enum field), and count parse
failures as a first-class metric — the re-run gave 26 terms and 0 failures, so the metric is
what told us the fix worked.

## Rule 7 — hash everything, trust no filename

- A "copy" suffix is not evidence of duplication and neither is a matching name: **verify by
  hash**. One drop of 24 files hashed to 23 distinct **[corpus]**; of four files named some
  variant of `Literatura`, three were *distinct documents* (4º, 5º, 6º año, confirmed from
  first-page text) and only one was a true duplicate.
- Before concluding a document must be OCR'd, check whether the publisher offers a text-layer
  edition — but verify: the "official" alternative here proved **byte-identical** to the copy
  we already had (same md5), settling the question for the cost of one download.
- Idempotence key = **content hash**, not path. A re-uploaded identical file is a no-op; a
  changed file reprocesses.

## Rule 8 — an inbox that never empties is not an inbox

Landing zone → index → **move** into the library, in that order, enforced by tooling.

- `shutil.move`, never copy. A copy created a **70 MB byte-identical duplicate** here.
- Move only what is already indexed, so an unregistered drop stays visible instead of buried.
- Keep the arrival manifest (source URLs) where it is — for externally-fetched documents the
  URL is the only thing you cannot recompute, and government sites rot (two documents in this
  corpus already required the Wayback Machine).

## Rule 9 — idempotence must key on the prompt too, not just the content

Content-hash `.done` files make re-uploads free — and silently skip every document when you
*improve the prompt*, which is the one time you most want reprocessing. Key on
`hash(content) + hash(prompt_version)`.

## Rule 10 — "has a text layer" is a binary; quality is not

A cheap extractability check (here: >50 characters across sampled pages) answers *is there
text*, not *is the text good*. Bad font encodings and broken CID maps produce plenty of
characters that are pure garbage. Budget a separate quality gate (Rule 5) rather than treating
the binary as a pass.

## Rule 11 — validate a sample before trusting a full pass

Have a **second, cold** process re-extract ~10% of items from the same sources and report an
agreement rate. Without it, a bulk pass has traded cost for unmeasured quality — and the agent
that did the extraction is the worst possible judge of it.

## Rule 12 — check usage terms before extracting, and record vintage

Corpora carry conditions: the TIMSS volume here requires a specific attribution, naming its
chapter authors as responsible for content. Check redistribution terms *before* building
derived datasets, and pin each document's retrieval date and edition — one document in this
corpus is a consolidated text silently different from the original it is named after.

## Still unproven (do not present this as validated)

- The Toolforge batch tier is **designed but not built or run**; the local tier is measured.
- No end-to-end run has been done on the full corpus.
- Layout-aware OCR (PaddleOCR PP-StructureV3, Surya) is the recommended fix for Rule 5's column
  problem but has **not been benchmarked here** — architectural reasoning only.
