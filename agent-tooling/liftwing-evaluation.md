# LiftWing LLMs: a first evaluation

> ### ⚠️ Provenance: written by an LLM. Verify before relying on it.
>
> This document was **researched, run and written by Claude (Opus 5)** working
> with a human collaborator, and it is **not peer-reviewed**. What that means
> concretely:
>
> - **The measurements are real** — every number comes from an actual run whose
>   raw output is on disk — **but the analysis, framing and generalisations are
>   LLM-produced** and carry the failure modes this document itself describes.
> - **Statistical rigour is limited.** Effect sizes are reported without
>   confidence intervals, nine prompt variants were compared against one anchor
>   with no multiple-comparison correction, and every prompt was run **once at
>   temperature 0** — so the "deltas" have no measured variance.
> - **Scope is narrow**: two models, one project's data, mostly one task family,
>   items numbering 29–340. Nothing here is a controlled comparison against other
>   providers, and nothing has been replicated by anyone else.
> - **Three of eleven benchmarks were invalidated by our own construction
>   errors.** We caught those three. We have no way to know what we did not catch.
> - **Several conclusions already changed once.** A published verdict in this
>   series was overturned by a later run — treat the current text as the latest
>   revision, not a settled result.
>
> **Use it as a checklist of things to verify, not as a source of facts.** The
> methodological cautions are the durable part; the numbers are one team's
> snapshot and should be re-measured before any decision rests on them.
>
> *A structured critique by domain reviewers (statistics, IR, annotation
> methodology, NLP evaluation) is in progress; findings are not yet incorporated.*


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
> - **We gave the model no category definitions — and that, not the model, caused
>   much of the reported failure.** Measured directly on 2026-08-18 (see
>   "Specification" below): adding one line of definition per class moved
>   macro-F1 **+0.217** on the 14B and **+0.145** on the 27B, and lifted recall on
>   the largest class from 0.12 to 0.62. **One task's round-1 verdict is
>   overturned by this.** Three of four tasks presented a bare list of rubric
>   terms; the one that defined its categories is the one that beat its baseline.
> - **Forced choice, no abstention.** Offering an "unclear" option turns out to
>   be free — and the model never once used it, in any arm.
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

**Date:** 2026-08-15, **substantially revised 2026-08-18** · **Models:**
`llm-qwen3-14b` (16K), `llm-qwen36-27b` (32K) · **Run from:** Toolforge
· ~7,900 calls total

---

## Recommendation

**Specify the task properly before you judge the model.** That is the first
recommendation, because it changed our own conclusions: defining the categories
moved macro-F1 by up to +0.217 and flipped one task from fail to pass. Most of
what we first recorded as model weakness was our prompt.

After that: **no** for anything requiring quotation or a label you will not
check by hand. **Conditional yes** for classification with a defined rubric, and
for coarse pre-filtering where a cheap baseline does not already win.

The models are **free in money and expensive in verification.** Zero errors,
zero rate limits, sub-second latency — and output that has to be checked, where
the checking can cost more than a paid API would have. That trade is worth
taking only where an error is cheap and something downstream sees the result.

**In our runs it fabricated roughly 1 in 8 quotes.** On that basis we are not
putting it in a citation-verification path. That finding is checked against the
source text rather than against labels, so unlike the classification results it
does not move when the prompt does.

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

Two rows carry a **2026-08-18 correction**: they were run with a bare list of
category names, and re-running them with one-line definitions changed the
verdict. Rows without a correction did not depend on a taxonomy prompt.

| task | result | baseline | read |
|---|---|---|---|
| segment type (JSON) | 58.3% | majority class **70.7%** | below baseline — **but never re-run with definitions; treat as unresolved** |
| deontic type — bare list | 0.435 / 0.556 | modal-verb regex 0.429 | 14B **below** the pass mark |
| **deontic type — with definitions** | **0.652 / 0.701** | same | **both clearly above; the 14B's failure was our prompt** |
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

## Specification: the biggest single lever

Measured 2026-08-18 — 9 prompt variants x 276 items x 2 models, 4,968 calls,
same items and same gold throughout, so only the prompt varies. The anchor arm
reproduced the round-1 numbers, so the differences are trustworthy even though
the absolute levels rest on LLM-generated labels.

| prompt | 14B | 27B | obligation recall (14B) |
|---|---|---|---|
| bare list of 7 category names | 0.435 | 0.556 | 0.12 |
| **+ one line defining each category** | **0.652** | **0.701** | **0.62** |
| + 1 example per category | 0.550 | 0.600 | 0.39 |
| + 3 examples per category | 0.560 | 0.629 | 0.55 |
| + "unclear" option | 0.625 | 0.676 | 0.64 |
| + room to reason (250 tok, not 12) | 0.625 | 0.559 | 0.64 |
| JSON input | 0.570 | 0.638 | **0.80** |
| JSON in and out | 0.578 | 0.665 | 0.69 |

**Definitions are worth more than everything else combined.** The failure they
fix is specific: the largest class was recognised at *precision 1.00, recall
0.12* — the model knew the concept and not where it ended, so hard cases went to
whichever label was vaguest. One sentence per class multiplied that recall
five-fold.

**Few-shot examples made it worse — on both models, at both counts.** Every
example-bearing variant scored below definitions alone, and non-monotonically
(1 example worse than 3, both worse than none). Our best guess is that the
examples are drawn from the same LLM-generated labels, so inconsistent
annotation is taught directly; a validated codebook might behave differently.
**Do not assume few-shot helps.** Here it cost 0.07–0.10 macro-F1.

**Structured input helps the classes that matter, and macro-F1 hides it.** JSON
input gave the best recall on the dominant class (0.80 on the 14B, 0.91 for
JSON-in-and-out on the 27B) while scoring lower on macro-F1 — because macro-F1
weights a 9-item class equally with a 121-item one. Pick the metric that matches
the deployment before picking the format.

**Room to reason helps a weak model and not a strong one.** Raising the output
budget from 12 tokens to 250 gained +0.190 on the 14B and +0.003 on the 27B —
and was the only variant that ever failed to parse (4%).

**What definitions did not fix:** one category stayed a sink in all 18
model-variant cells (recall 0.78–1.00 at precision 0.18–0.44). Specification
explains much of the pathology, not all of it. The rest is a codebook problem,
and no prompt fixes an underspecified category.

---

## Where it looked usable

0. **Define your categories first.** One line each. It is the cheapest
   intervention available and it outperformed every other change we tried.
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
9. **Test the prompt before blaming the model.** We ran 2,344 calls and wrote a
   verdict before checking whether the task was specified. One controlled sweep
   afterwards overturned part of it. Vary the prompt while holding items, gold
   and model fixed — the deltas are valid even when the labels are not, so this
   works before any gold validation.
10. **A conventional wisdom is a hypothesis.** "Few-shot helps" is near-universal
   advice; it was false here, on both models, at both example counts. Testing a
   dose-response (0, 1, 3) rather than a single setting is what made the
   direction visible.

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
