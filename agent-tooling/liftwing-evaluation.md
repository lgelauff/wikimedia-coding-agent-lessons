# LiftWing LLMs: a first evaluation

> ## ⚠️ Read this first — this is NOT a thorough evaluation
>
> **One person, one afternoon, ~2,900 calls, on one project's data.** Treat every
> number below as a first sighting, not a measurement.
>
> - **Small n.** Most tasks have 30–340 items. Confidence intervals run roughly
>   ±5 points at the largest and **±18 points** at the smallest. Nothing here
>   separates two models that are a few points apart.
> - **The classification "gold" was itself LLM-generated.** Not one human-verified
>   label. So those accuracy figures are **agreement with an unnamed model**, not
>   accuracy, and the human ceiling is unknown. Validating it against hand
>   labels is the first thing we would now do — and we would not repeat this
>   order of operations.
> - **We gave the model no category definitions — except on the one task it
>   won.** Three of four tasks presented a bare list of rubric terms. The single
>   task that defined its categories in one line each is the single task that
>   cleanly beat its baseline. We probably built the failure we then measured.
> - **Forced choice, no abstention.** A model that cannot answer "unclear" must
>   place every hard case somewhere, and it picks the vaguest bucket. Part of the
>   reported pathology is an answer-format artifact.
> - **Everything here is ZERO-SHOT.** No few-shot examples on any task. The
>   dominant failure was a *boundary* problem, not a capability one — the largest
>   class was recognised at precision 1.00 but recall 0.13, i.e. the model knew
>   the concept and not where it ends. That is what definitions and examples
>   address, and neither was tested.
> - **Our own prompts, our own rubrics.** Several tasks are homemade taxonomies
>   with fuzzy category boundaries — close to the worst case for any model. A
>   different prompt might move these substantially; we did not test prompt
>   sensitivity, and where we changed prompts, results moved.
> - **Two of our probes were invalid** and are reported as methods lessons
>   rather than results. One of them **inverted** once fixed.
> - **Whole task families are untested**, including the one most likely to
>   produce a positive result (affective/tone judgement against human labels).
> - **Nothing here is a controlled comparison** against other providers on the
>   same tasks.
>
> **Do not cite these numbers as LiftWing's capability.** They are a record of
> what one pipeline saw, and mostly a record of *how to build the harness*. The
> methods section is the part we would defend; the results table is the part we
> would expect to move.

**Date:** 2026-08-15 · **Models:** `llm-qwen3-14b` (16K), `llm-qwen36-27b` (32K)
· **Run from:** Toolforge

---

## Recommendation

**No** for anything requiring judgement, quotation, or a label you will not
check by hand. **Conditional yes** for coarse pre-filtering where a cheap
baseline does not already win and a stronger model reviews the shortlist.

The models are **free in money and expensive in verification.** Zero errors,
zero rate limits, sub-second latency — and output that has to be checked, where
the checking can cost more than a paid API would have. That trade is worth
taking only where an error is cheap and something downstream sees the result.

**In our runs it fabricated roughly 1 in 8 quotes.** On that basis we are not
putting it in a citation-verification path.

---

## What it costs and what you get

| | |
|---|---|
| Money | **Free** |
| Throughput (Toolforge) | ~6,400 calls/hr sustained at 2 req/s, **no 429 observed** |
| Throughput (anonymous) | 100/hr — a hard floor; bulk work becomes an overnight job |
| Latency | median **0.20s**, p90 0.56s (from Toolforge) |
| Reliability | **0 errors, 0 parse failures in 2,344 calls** |
| Structured output | **100% schema-valid** across 676 JSON calls, with no JSON mode |
| `<think>` preambles | **0 / 2,344** — our stripper never fired |

Operationally this was the best-behaved provider in our stack. Every failure
below is analytical, not infrastructural. **The anonymous 100/h cap does not
apply from Toolforge** — that alone changes what is feasible.

---

## Results

| task | result | baseline | read |
|---|---|---|---|
| segment type (JSON) | 58.3% | majority class **70.7%** | below baseline |
| deontic type | macro-F1 **0.572** (27B) | modal-verb regex 0.429 | above baseline |
| governance class | macro-F1 **0.685**, acc 77.2% | majority acc 60.1% | above baseline, misses its recall gate |
| statement alignment | 31–34% | majority 51.7%, embedding 62.1% | below baseline (replicated) |
| source rerank | 30.1% / 28.0% | **BM25 31.2%** | indistinguishable |
| quote fidelity | **11.9% / 5.6% fabricated** | want 0% | unusable for citation |
| agreement-as-confidence | 63.8% @ 73.7% coverage | 27B alone **64.3%** | refuted |
| batching | 0 misalignments, **4.3× fewer tokens** | — | adopt |

**In our tasks it lost to a trivial baseline more often than it beat one.**
Always compute the dumb baseline first — majority class, a regex, BM25. Twice
here a score that looked respectable was below always-guessing.

> **How much of this is the model, and how much is us?** The four classification
> rows are scored against LLM-generated labels, from prompts that mostly gave no
> category definitions, with no option to answer "unclear". The rows that do
> *not* depend on any of that — quote fabrication (checked against the source
> text itself) and source rerank (against BM25, a real baseline) — are the ones
> we would defend. **Read the classification rows as provisional.**

**One pathology showed in both models:** loose categories act as sinks. A vague
class drew precision 0.14–0.22 at recall 0.91, while the largest class got
recall 0.13–0.45. They struggle to answer "none of these" and route hard cases
into whichever label is broadest. **Stress-test your catch-all class before
trusting any label set.**

---

## Where it looked usable

1. **Coarse categorisation as a pre-filter**, not a decision, with a stronger
   model or a human on the shortlist.
2. **High-volume mechanical passes** where an error is cheap and caught later.
3. **Batch your requests.** 100 items per call used 4.3× fewer input tokens
   than one-per-call with zero row misalignment in our runs. The 14B degraded
   past ~10 per batch; the 27B did not. Verify on your own task before relying
   on it.
4. **The 27B beat the 14B on classification** but not uniformly — no better on
   alignment, and it abstained more often.

---

## Methods lessons

This is the part we would defend. Three of our own constructions produced
confident numbers from nothing, and each would have shipped a wrong conclusion.

1. **A null control is an experimental artefact and needs its own validation.**
   Our "functionally identical" control diffs contained genuine defects, so a
   model correctly reporting one was scored as *inventing* an issue. **The
   model was right and the harness was wrong**, and the finding inverted once
   fixed — the model we had called worst was being penalised for being better.
2. **A baseline that looks perfect is a bug.** Our first retrieval baseline
   scored **100% recall@1** because the gold passage sat inside the query,
   matching the text against itself. True figure: 21.6%.
3. **Compute the trivial baseline before reading any score.** 58.3% looked like
   a pass until always-answering the majority class scored 70.7%.
4. **Report the ceiling, or the number is uninterpretable.** Two strong
   reference models agreed with *each other* at κ=0.138 on code review — there
   was no stable signal to match. Our scorer nonetheless printed
   *"150% of ceiling → SUBSTITUTABLE"* by dividing by near-zero.
5. **Check base rates beside every κ.** Flag rates ranged 79% to 11% across
   raters; agreement statistics between raters with different base rates sit
   near zero regardless of judgement quality.
6. **Check the independence assumption before importing an ensemble result.**
   Same-family models have correlated errors — when they agree they are often
   both wrong, so agreement is a shared prior, not evidence.
7. **A confounded probe reports success.** Our long-context probe scored 100%
   at every input length *including the isolated control* — every item happened
   to share one label. It measured nothing while looking like a clean pass.
8. **Pre-register the threshold.** Without a pass mark fixed in advance you
   will get a number and rationalise it.

---

## Not tested

Stated so this is not read as coverage:

- **Long-context degradation.** Our probe was invalid; we know nothing. This
  decides whether whole-document extraction is viable at all.
- **Discussion tone / incivility** against human-labelled data with a published
  non-LLM baseline. The strongest available design and the one most likely to
  produce a positive result — untested.
- **Claim verification** against an external benchmark.
- **Code review.** As posed, the task was not measurable.
- **Few-shot prompting — the most important gap.** Everything above is
  zero-shot. The measured failure was that the model knows a concept but not its
  boundary (precision 1.00, recall 0.13 on the largest class), which is what
  demonstrating examples fixes if anything does. A design with a falsifiable
  hypothesis — few-shot should move *per-class* recall on the starved class, not
  merely the headline average — is in `playbooks/liftwing-bench-round2.md`.
  **Until it runs, treat the results table as an upper bound on how badly these
  models do, not a measure of what they can do.**
- **Prompt sensitivity and fine-tuning.** Also untested; either could move these
  numbers.

---

## Harness

Not yet committed — the benchmark scripts still hardcode this project's data
layout, which `conventions.md` says belongs in a per-project config rather than
the script. They will land here once that is fixed.

The pattern worth stealing regardless:

- **One bundled file for Toolforge.** A packer inlines the runner *and* its
  gold data into a single stdlib-only `.py` (data as a zlib+base64 blob). One
  `scp`, one command, no checkout, no `pip install` — and it self-tests that it
  can read its own embedded data from a clean directory before it is written.
- **Provider-agnostic calls**, so the same harness benchmarks any backend by
  changing one environment variable, and results stay comparable.
- **Resume on success only.** Failed calls must not be recorded as done, or a
  transport outage silently becomes a permanent gap in the results.
- **Separate `prepare` / `rate` / `score` steps** over JSONL. Scoring never
  re-calls the model, so a metric can be fixed — or a bug in it found — without
  spending anything.
