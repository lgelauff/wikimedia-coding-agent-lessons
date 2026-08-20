# Why we benchmark LLMs, and how

Framing and method for evaluating an LLM before putting it in a Wikimedia
research pipeline. Written so another agent can reproduce the reasoning, not
just the numbers.

Companion documents: [`liftwing-evaluation.md`](liftwing-evaluation.md) (results),
[`playbooks/liftwing-bench-suite.md`](playbooks/liftwing-bench-suite.md) and
[`playbooks/liftwing-bench-round2.md`](playbooks/liftwing-bench-round2.md) (designs).

---

## 1. Why we are testing

Not "is this model good." That question has no answer, and leaderboard scores do
not transfer to a specific pipeline.

The real question is a **deployment** question, forced by four constraints that
apply to this kind of work:

| constraint | consequence |
|---|---|
| **Volume** — thousands of policy statements, claims, papers | too many to process by hand, few enough that per-call price matters |
| **Provenance** — research output must be citable | an error that survives into a published claim is expensive and slow to detect |
| **Privacy** — the input is often wiki or community content | WMF-hosted inference is a real advantage, sometimes decisive |
| **Reproducibility** — analyses get re-run | a model that shifts under you invalidates the run, not just the item |

So the question is: **for which steps of this pipeline can a free, WMF-hosted
model replace a paid API or a human, and how would we know?**

---

## 2. What we are optimizing for

**Not accuracy.** The objective is the **total cost of a trustworthy result**:

```
cost = inference cost + verification cost + cost of undetected errors
```

Inference cost is the term everyone measures and the one that matters least
here — LiftWing is free. Verification dominates. **A free model requiring 100%
human review is more expensive than a paid model requiring 10%.**

That reframes the operational target:

> **Maximise the fraction of items that can be accepted without human review,
> subject to a hard bound on undetected errors.**

Four consequences that shaped every test we ran:

1. **Calibration outranks accuracy.** A model that is 70% accurate and *knows
   which 70%* is more useful than one that is 85% accurate uniformly, because
   the first can be routed and the second must be checked entirely.
2. **Silent failure is the worst property a model can have.** An error that
   announces itself costs a retry. An error that looks like an answer costs a
   retracted claim. This is the same conclusion the Wikipedia-AI-Skills A/B test
   reached from the opposite direction — its no-skills variant failed 6/12 tasks
   while producing plausible output with no error messages.
3. **Format compliance is nearly worthless on its own.** Our models returned
   100% schema-valid JSON across 676 calls while getting the values wrong more
   often than a majority-class guess. "It parsed" is not evidence.
4. **A trivial baseline is part of the measurement, not a nicety.** If a regex,
   a majority class, or BM25 already wins, the model's accuracy is irrelevant.

---

## 3. What we are testing for, concretely

Four questions, in order. Each is only worth asking if the previous one passed.

**Q1 — Can it do the task at all?**
Against a *trivial* baseline, not against zero. Majority class, a keyword regex,
BM25 top-1, or an existing purpose-built classifier.

**Q2 — Does it know when it cannot?**
Abstention rate on items where the right answer is "none of these", against
false-abstention on answerable items. The gap between those two is
discrimination; a shifted threshold is not calibration.

**Q3 — Does it fail loudly or silently?**
Measured with checks that need no gold: is the quoted text actually in the
source, does the returned row count match the input, is the output schema-valid
*and* the value right.

**Q4 — Is the failure ours or the model's?**
The one we learned last and should have asked first. Vary the prompt while
holding items, gold and model fixed. **In our case this overturned a published
verdict**: adding one line of definition per category moved macro-F1 +0.217 and
flipped a task from fail to pass.

---

## 4. The tests we ran

Nine probes across three rounds, ~7,900 calls. Four produced findings; three
were invalidated by our own construction errors; two are built but unrun. That
ratio is itself a result — **most of the difficulty was in building measurements
that could not lie.**

| # | test | question | verdict |
|---|---|---|---|
| 1 | Classification suite (4 tasks, 2 models) | Q1 | lost to trivial baselines on 3 of 4 — **later partly overturned by #9** |
| 2 | Batching probe (1/10/50/100 per call) | efficiency | **adopt**: 4.3× fewer tokens, zero row misalignment |
| 3 | Position/context probe | long input | **INVALID** — all items shared one label, scored 100% everywhere |
| 4 | Agreement-as-confidence (re-analysis) | Q2 | **refuted** — worse than the better model alone |
| 5 | Source extraction / rerank | Q1, Q3 | indistinguishable from BM25; **fabricated ~1 in 8 quotes** |
| 6 | Code-review agreement study | Q1 | **not measurable** — reference models agreed with each other at κ=0.138 |
| 7 | Null-control (invented-issue rate) | Q3 | **INVALID** — controls contained real defects; result inverted once fixed |
| 8 | Rate-limit boundary probe | operational | ~100 requests then 429 anonymous; Toolforge exempt |
| 9 | Prompt-specification sweep (9 arms) | Q4 | **definitions worth +0.217; few-shot HURT; one round-1 verdict overturned** |

---

## 5. The harness pattern (reusable)

Every benchmark used the same three-stage shape, and the separation is what made
mistakes cheap to fix:

```
prepare  →  items.jsonl     (task, gold, baseline precomputed, splits frozen)
rate     →  ratings.jsonl   (one record per call; append-only, resumable)
score    →  report          (never calls the model)
```

- **Scoring never re-calls the model.** Every metric bug we found — and there
  were several — was fixed and re-scored for free.
- **Resume on success only.** A failed call must not be recorded as done, or a
  transport outage becomes a permanent silent gap.
- **Prompts pre-rendered into the items.** The runner only POSTs them, so no
  prompt-construction logic can drift between a local run and a remote one.
- **One bundled file for remote runs.** A packer inlines runner *and* data into
  a single stdlib-only `.py`; it self-tests that it can read its own embedded
  data from a clean directory before it is written.
- **Provider-agnostic calls**, so the same harness benchmarks any backend by
  changing one environment variable.

---

## 6. The controls that make a result mean something

Each of these exists because its absence produced a wrong answer at least once.

| control | what it prevents | how it failed us |
|---|---|---|
| **Trivial baseline** | mistaking a bad score for a good one | 58.3% looked like a pass until always-guessing scored 70.7% |
| **Ceiling** (inter-rater agreement) | interpreting a low score with no reference | two strong models agreed at κ=0.138; our scorer still printed "150% of ceiling → SUBSTITUTABLE" by dividing by near-zero |
| **Null control** | a reviewer that invents problems | our "functionally identical" diffs contained real bugs; the model was right and the harness wrong |
| **Replication anchor** | drift between rounds | a byte-identical arm reproduced round 1, making the sweep's deltas trustworthy |
| **Leak check** | example/test contamination | a retrieval baseline scored 100% because the answer was inside the query |
| **Gold provenance check** | scoring against another model's opinions | all our classification "gold" was LLM-generated; we found out after 2,344 calls |
| **Gold-free metric** | every result resting on label quality | quote-in-source and row-count checks survived the gold problem intact |
| **Pre-registered threshold** | rationalising whatever number arrives | borrowed from an adversarial review of our own design |

**The single most transferable rule: a measurement that cannot fail is not
measuring.** A baseline at 100%, a probe at 100% in every condition, a "clean"
control nobody ever flags — each looked like success and was a bug.

---

## 7. What generalises beyond this model

- **Specify before you judge.** Category definitions were worth more than model
  choice, few-shot examples, output budget and input format combined.
- **Conventional wisdom is a hypothesis.** "Few-shot helps" was false here on
  both models at both example counts, and non-monotonically. A dose-response
  (0, 1, 3) made the direction visible where a single setting would not have.
- **Pick the metric before the format.** Structured input gave the best recall
  on dominant classes and a worse macro-F1, because macro-F1 weights a 9-item
  class like a 121-item one. Those are different deployments, not different
  qualities.
- **Check the independence assumption before importing an ensemble result.**
  Same-family models have correlated errors; their agreement is a shared prior.
- **Prefer a specialised model where one exists.** Wikimedia's own classifiers
  ship model cards with precision/recall/F1. The LLMs ship none — so with a
  classifier you can *know* how good it is, and with an LLM you must measure it
  yourself, which took us three days.
