# LLM evaluation lessons

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


Gotchas from benchmarking two open-weight LLMs (Wikimedia LiftWing's
`llm-qwen3-14b` and `llm-qwen36-27b`) for a Wikipedia governance-research
pipeline — ~7,900 calls, eleven benchmarks run, **three of which were invalidated
by our own construction errors.** Those three are the useful part.

The question was never "is this model good." It was: **for which steps can a
free, WMF-hosted model replace a paid API or a human, and how would we know?**
That makes the objective *total cost of a trustworthy result* — inference plus
verification plus undetected errors — and verification dominates, because a free
model needing 100% human review costs more than a paid one needing 10%.

A reading list is at the bottom. The runnable harness lives in
[`agent-tooling/`](../agent-tooling/llm-evaluation-method.md).

## Measurements that cannot fail

- **A baseline at or near 100% is a bug, not a triumph.** Our first retrieval
  baseline scored **BM25 recall@1 = 100%** because the gold passage was inside
  the query — it was matching text against itself. The true figure was 21.6%.
  A benchmark whose baseline is already perfect cannot measure anything above it.
- **A probe that scores 100% in every condition, including its control, measured
  nothing.** Our long-context probe reported perfect accuracy at 43, 8,947 and
  16,400 tokens. The items had all been drawn from a single content policy, so
  they almost certainly shared one label and "always answer content" scored 100%.
  **Verify the control condition is below ceiling before trusting any delta** —
  if the easy case is already perfect, no degradation can appear.
- **Validate your null control; it is an experimental artefact like any other.**
  We built "functionally identical" diffs by renaming an identifier, but renamed
  only on `+`/`-` lines and left context lines alone — silently creating
  undefined-variable bugs. A model correctly reporting one was scored as
  *inventing* an issue. The stronger model caught it and our harness called it a
  hallucination; the result inverted once fixed. **"Identical by construction"
  was an assertion, not a check.**

## Baselines and ceilings

- **Compute the trivial baseline before reading any score, not after.** A task
  scoring 58.3% looked respectable until always-answering the majority class
  scored 70.7%. We reported it with no comparator first and read it as a pass.
  Majority class, a keyword regex, BM25 — one of these usually exists, and twice
  here it beat the model.
- **Without an inter-rater ceiling, an agreement number is uninterpretable.**
  Two capable models from different families agreed *with each other* at
  **κ=0.138** on code review. There was no stable signal to match — but our
  scorer still printed *"150% of ceiling → SUBSTITUTABLE"* by dividing a subject
  score by a near-zero denominator. **Refuse to issue a verdict when the ceiling
  is below ~0.20**, and compute the ceiling before any subject score.
- **Report base rates beside every κ.** Flag rates ran from 79% to 11% across our
  raters. Cohen's κ between raters with very different base rates sits near zero
  *regardless of judgement quality*, so a low κ may mean "one rater says yes to
  everything," not "they disagree case by case."

## Gold

- **Check what your gold actually is before designing a metric around it.** All
  340 of our classification labels turned out to be **LLM-generated with no human
  verification** — discovered after 2,344 calls. Every "accuracy" was really
  agreement with an unnamed model, and the human ceiling was unknown. *"Is the
  gold actually gold"* belongs in the same checklist slot as *"compute the
  trivial baseline."*
- **Gold may not be verbatim even when it looks like a quotation.** Our
  claim→passage mappings appeared to be extracted spans; only **3.9% were exact
  substrings** of the source, and 50.9% survived stripping to alphanumerics. A
  "did it return the gold span" metric was impossible. They had been paraphrased
  or stitched by whatever produced them.
- **Prefer metrics that need no gold at all.** After the gold problem surfaced,
  the three findings still standing were the three requiring no labels:
  *is the quoted text actually present in the source* (11.9% of quotes were not),
  *does the returned row count match the input*, and *what HTTP status came back*.
  Gold-free checks survive discoveries that invalidate everything else.

## Output format and metric choice

- **Schema-validity and value-accuracy are different metrics; never combine
  them.** We measured **100% schema-valid JSON across 676 calls with no JSON
  mode** — and value accuracy below the majority baseline. "It parsed" is not
  evidence of anything. This is the single highest-yield idea we borrowed
  (see [the Structured Output Benchmark](https://arxiv.org/pdf/2604.25359)).
- **Pick the metric before the format, because they disagree.** Structured JSON
  input gave the *best* recall on the dominant class (0.62 → 0.80) while
  *lowering* macro-F1 — macro-F1 weights a 9-item class equally with a 121-item
  one. Those are different deployments, not different qualities.
- **Report macro-F1 and accuracy together; the gap is the diagnostic.** One model
  scored 37.9% accuracy while never once emitting one of three available labels.
  Accuracy alone hid a total collapse onto a catch-all.

## Prompting, and blaming the model too early

- **Specify the task before concluding anything about the model.** We ran 2,344
  calls and published a verdict before checking whether the categories were
  defined. A later controlled sweep — same items, same gold, same model, only the
  prompt varying — found that **one line of definition per category was worth
  +0.217 macro-F1** on the smaller model and lifted recall on the largest class
  from 0.12 to 0.62. **It overturned one published verdict:** a model we recorded
  as failing scored a clear pass once the rubric was stated. Tellingly, the one
  task in that round whose prompt *did* define its categories was the one task
  that beat its baseline.
- **Deltas are valid even when the gold is not.** Vary the prompt while holding
  items, gold and model fixed and the differences between arms are trustworthy
  even if no arm's absolute level is. This works *before* any gold validation,
  which makes it the cheapest first move.
- **Few-shot is a hypothesis, not a rule.** Adding examples made results **worse**
  on both models at both counts, and non-monotonically (1-shot < 3-shot <
  0-shot). Our best guess is that examples drawn from inconsistent labels teach
  the inconsistency. A dose-response (0, 1, 3) made the direction visible; a
  single setting would have looked like noise.
- **A forced choice with no "unclear" option manufactures a failure mode.** Under
  forced choice the models routed hard cases into whichever label was vaguest —
  one category ran precision 0.14 at recall 0.91. Offering an escape hatch cost
  nothing measurable. It was also **never used once**, in any arm.
- **Check the independence assumption before importing an ensemble result.** We
  applied a published finding about ensembles of *different* small models to two
  models from the same family. Their errors correlate, so agreement is a shared
  prior rather than evidence — agreement-gating scored **worse than the better
  model alone** at full coverage.

## Harness shape

- **Split `prepare` → `rate` → `score`, and never let scoring call the model.**
  Every metric bug we found — and there were several — was then free to fix and
  re-score. With scoring fused to inference, each fix costs another full run.
- **Resume on success only.** A failed call recorded as "done" turns a transient
  outage into a permanent silent gap in your results. We hit this: a re-run
  skipped 152 failed calls because failures had been written to the output file.
- **Pre-render prompts into the items.** Then the runner only sends them, and no
  prompt-construction logic can drift between a local run and a remote one.
- **Carry per-arm settings inside the item** (system message, token budget, parse
  mode). We nearly shipped a "reasoning doesn't help" result produced by a system
  prompt that said *"answer with the requested token and nothing else"* — which
  gagged the very arm meant to test reasoning.
- **Pre-register the pass mark.** Otherwise you will get a number and
  rationalise it. This one came from an adversarial review of our own design, not
  from any paper.

## Operational notes (LiftWing specifically)

- **The LLM endpoints cap at ~100 requests for anonymous clients**, not the
  50,000/hour that the general `api.wikimedia.org` gateway allows. Confirmed by a
  **429 at exactly call 101**, 27 seconds into a 5 req/s run. It behaves as a
  quota, not a smooth rate — it is spendable in under half a minute. Running from
  Toolforge lifts it: 2,344 calls at 2 req/s with no 429 at all.
- **Latency is ~0.2–0.25s median.** A 39.9s median we recorded earlier was
  entirely our own client-side rate bucket, not the service.
- **Where a purpose-built classifier exists, prefer it.** Wikimedia's classifiers
  (`revertrisk`, `articlequality`, `readability`, `reference-need`, `langid`,
  `article-country`) ship model cards with precision/recall/F1. The LLMs ship
  none — so a classifier's quality is *knowable*, while an LLM's must be measured
  from scratch.

---

## Reading list

Ordered by what it prevents. **The first four would have caught three of our
eleven wasted benchmarks.**

**Before writing any code**

1. [**AI Evaluation Should Learn from How We Test Humans**](https://arxiv.org/pdf/2306.10512)
   — psychometrics for model evaluation: reliability, item difficulty,
   discrimination. Almost every failure above is a measurement-theory failure in
   ML clothing — an instrument with no reliability estimate, items that cannot
   discriminate, a ceiling never computed.
2. [**Questionable practices in machine learning**](https://arxiv.org/pdf/2407.12220)
   — names the ways evaluation misleads without anyone lying. Ours: no baseline
   until afterwards, a leaked signal, uncorrected multiple comparisons.
3. [**A Taxonomy for Data Contamination in LLMs**](https://arxiv.org/pdf/2407.08716)
   ([reading list](https://github.com/lyy1994/awesome-data-contamination)) —
   contamination includes *your own* leaks, not just pretraining overlap.
4. [**The Structured Output Benchmark**](https://arxiv.org/pdf/2604.25359) —
   schema compliance is not value correctness. Score them separately.

**By task shape**

- Extraction/retrieval: [LLMs are weak extractors but useful rerankers](https://arxiv.org/pdf/2303.08559)
  — reframe extraction as reranking a cheap retriever's shortlist. (Our models
  were *indistinguishable* from BM25, so treat the promise as a hypothesis.)
- Summarization: [HaRiM+](https://arxiv.org/pdf/2211.12118),
  [Hallucinations Leaderboard](https://arxiv.org/pdf/2404.05904). **Not ROUGE** —
  it collapses hallucination, omission and paraphrase-blindness into one number.
- Structured output: [Let Me Speak Freely?](https://arxiv.org/abs/2408.02442) —
  format restriction degrades reasoning. Our caveat: we found it
  *metric-dependent*, not universal.
- Review/critique: [SWR-Bench](https://arxiv.org/html/2509.01494v2). Frontier
  models reach only ~41–51% F1 on paper review; lead with a null control.
- Abstention: [Know Your Limits](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/Know-Your-Limits-A-Survey-of-Abstention-in-Large)
  plus selective-prediction metrics (AUACC, C@Acc). **In a
  verification-cost-dominated pipeline this can matter more than accuracy.**

**Wikimedia data with human labels**

- [**Wikipedia Detox**](https://arxiv.org/pdf/1610.08914) (Wulczyn, Thain &
  Dixon) — ~100k talk-page comments, **~10 annotators each**, graded scores, CC0
  on Figshare. The only Wikimedia-native set we found where the **human-agreement
  ceiling is computable from the data**, with a published non-LLM baseline
  (AUC ~0.96). If you need one honest benchmark, this is it.
- **FEVER** — 185k human-written claims over Wikipedia evidence.
- **Meta-Wiki model cards** — published metrics for the classifiers.

**Skip**

- Leaderboard scores for model selection. Qwen3-14B posts MMLU-Redux 82.0 and
  MATH-500 90.0; neither predicted anything we observed.
- Guides asserting few-shot always helps. See above.

---

**The one-line version, which came from our failures rather than any paper:**

> **A measurement that cannot fail is not measuring.** A baseline at 100%, a
> probe perfect in every condition, a control nobody ever flags — each looked
> like success and each was a bug.
