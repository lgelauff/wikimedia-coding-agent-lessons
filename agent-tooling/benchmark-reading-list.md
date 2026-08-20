# Reading list: benchmarking an LLM for a Wikimedia research pipeline

For an agent about to evaluate whether some model can do real work in a research
pipeline. Ordered by what it prevents, not by importance in the abstract.

Each entry says **what it changes** and, where applicable, **which of our
mistakes it would have caught** — see [`benchmark-cards.md`](benchmark-cards.md)
for the incidents. Provenance of what we actually used:
[`benchmark-provenance.md`](benchmark-provenance.md).

**If you read nothing else, read §0. It is four items and it would have
prevented three of our eleven benchmarks from being wasted.**

---

## §0 — Before you write any code

### 0.1 Position: AI Evaluation Should Learn from How We Test Humans
[arXiv 2306.10512](https://arxiv.org/pdf/2306.10512)

**The one I most wish I had read first.** Argues for psychometrics — item
response theory, reliability, item difficulty and discrimination — instead of
"average score on a fixed set."

**What it changes:** you stop asking "what did it score" and start asking "does
this item discriminate, and what is this instrument's reliability?" Nearly every
failure we had was a measurement-theory failure wearing an ML costume: a probe
where every item was the same difficulty (all scored 100%), a ceiling we never
computed, an instrument with no reliability estimate.

### 0.2 Questionable practices in machine learning
[arXiv 2407.12220](https://arxiv.org/pdf/2407.12220)

A catalogue of ways ML evaluation misleads — usually without anyone lying.

**What it changes:** it names the failure modes so you recognise yours. Ours
were: no baseline computed until afterwards, a leaked test signal, multiple
comparisons without correction, and reporting a metric whose comparator did not
exist.

### 0.3 A Taxonomy for Data Contamination in LLMs
[arXiv 2407.08716](https://arxiv.org/pdf/2407.08716) ·
list: [awesome-data-contamination](https://github.com/lyy1994/awesome-data-contamination)

**What it changes:** contamination is not only "the model trained on the test
set." It includes *your own* leaks. Our first retrieval baseline scored **100%
recall@1** because the gold passage sat inside the query — a contamination bug
that looked like a triumphant baseline.

**Rule to take:** a baseline at or near 100% is a bug until proven otherwise.

### 0.4 The Structured Output Benchmark
[arXiv 2604.25359](https://arxiv.org/pdf/2604.25359) · siblings:
[LLMStructBench](https://arxiv.org/html/2602.14743v1),
[ExtractBench](https://arxiv.org/html/2602.12247v2)

Near-perfect schema compliance alongside ~83% value accuracy.

**What it changes:** score **schema-validity and value-accuracy separately,
always.** We measured 100% schema compliance with value accuracy *below the
majority baseline*. A combined "JSON score" would have read as a pass. This is
the highest-yield single idea we borrowed.

---

## §1 — Match to your task shape

Read the one that fits. Skip the rest until you need them.

**Classification / labelling**
Macro-F1 under imbalance — e.g. [arXiv 2404.09135](https://arxiv.org/pdf/2404.09135).
Report macro-F1 *and* accuracy; **the gap between them is the frequency-bias
diagnostic.** Ours caught a model scoring 37.9% while never emitting one of three
labels.

**Extraction / retrieval**
["LLM Is Not a Good Few-shot Information Extractor, but a Good Reranker for Hard
Samples!"](https://arxiv.org/pdf/2303.08559) — reframe extraction as reranking a
cheap retriever's shortlist. Pair with a real retrieval baseline (BM25). Note our
model was *indistinguishable* from BM25, so treat the paper's promise as a
hypothesis.

**Summarization / generation**
Faithfulness and hallucination measurement:
[HaRiM+](https://arxiv.org/pdf/2211.12118),
[Hallucinations Leaderboard](https://arxiv.org/pdf/2404.05904).
**Do not use ROUGE.** It collapses hallucination, omission and paraphrase-
blindness into one number.

**Long inputs**
"Lost in the middle" / context-rot work (∞Bench, RULER). U-shaped accuracy by
position; degradation with length even when evidence is well-placed.
**Design warning from us:** use class-balanced items and verify the *isolated*
control scores below ceiling first. Ours scored 100% everywhere and measured
nothing.

**Review / critique**
[SWR-Bench](https://arxiv.org/html/2509.01494v2) and the paper-review benchmarks.
Frontier models reach only ~41–51% F1 on review, and project-scale vulnerability
work reports ~97% false discovery. **Lead with a null control**, and validate
that control — ours contained real bugs and inverted the finding.

**Structured output / format**
["Let Me Speak Freely?"](https://arxiv.org/abs/2408.02442). Format restriction
degrades reasoning. **Our caveat:** we found it metric-dependent — JSON input
raised dominant-class recall while lowering macro-F1. Treat "restriction hurts"
as directional, not universal.

**Ensembles / self-consistency**
Whatever you read, **check the independence condition before importing it.** We
applied a result about ensembles of *different* small models to two models from
one family. Correlated errors; agreement-gating scored worse than the better
model alone.

**Abstention / calibration**
["Know Your Limits: A Survey of Abstention in LLMs"](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00754/131566/Know-Your-Limits-A-Survey-of-Abstention-in-Large)
plus selective-prediction metrics (AUACC, C@Acc, risk-coverage). **For a
verification-cost-dominated pipeline this may matter more than accuracy** — a
model that knows which items it can do lets you route them.

---

## §2 — Reliability and agreement, if any task lacks ground truth

Needed the moment you compare raters rather than score against truth.

- **Cohen's κ / Fleiss' κ** — chance-corrected agreement. Raw agreement % is
  meaningless under imbalance.
- **Landis & Koch (1977)** interpretation bands — widely used, widely criticised
  as arbitrary. Cite as convention, not as evidence.
- **Krippendorff's α** — handles ordinal data and missing ratings; better than
  Fleiss for graded scores.

**Two things we learned the hard way, which the textbooks underplay:**

1. **Always compute the ceiling** (reference-vs-reference agreement) *before*
   interpreting any subject score. Two strong models agreed with each other at
   **κ=0.138** on code review — there was no signal to match. Our scorer still
   printed "150% of ceiling → SUBSTITUTABLE" by dividing by near-zero.
2. **Report base rates beside every κ.** Between a 79%-flagger and an
   11%-flagger, κ is near zero regardless of judgement quality.

---

## §3 — Data, not papers

**Wikipedia Detox** — [Ex Machina](https://arxiv.org/pdf/1610.08914) (Wulczyn,
Thain & Dixon), data CC0 on Figshare, ~100k talk-page comments, **~10 annotators
each**, graded scores.
**Why it matters more than any paper here:** it is the only Wikimedia-native
dataset we found where the **human-agreement ceiling is computable from the
data**, with a published non-LLM baseline (AUC ~0.96). If you need one honest
benchmark, use this.

**FEVER** — 185k human-written claims over Wikipedia evidence, three-way
verdicts. External calibration against a public leaderboard.

**Wikimedia model cards on Meta-Wiki** — the *classifiers* (`revertrisk`,
`articlequality`, `readability`, `reference-need`, `langid`, `article-country`)
publish precision/recall/F1. **The LLMs publish none.** So a classifier's quality
is knowable; an LLM's must be measured, which cost us three days.

---

## §4 — Wikimedia-specific context

- **[fuzheado/Wikipedia-AI-Skills](https://github.com/fuzheado/Wikipedia-AI-Skills)**
  — service catalogue for LiftWing and ORES: endpoints, parameters, response
  shapes. Its `AB_TEST_META_REPORT.md` finds a 2.8× speedup and 12/12 vs 6/12
  correctness with skills loaded, and — converging with us from the opposite
  direction — that **failures are silent, producing plausible output with no
  error message.**
  **Caveat we verified:** its rate table (50,000/hr anonymous) describes the
  general API gateway. The **LLM endpoints cap at ~100 requests**, confirmed by a
  429 at exactly call 101.
- **Wikitech LiftWing LLM pages** — marked draft; verify anything load-bearing.

---

## §5 — What to skip

- **Leaderboard scores for model selection.** Qwen3-14B posts MMLU-Redux 82.0 and
  MATH-500 90.0; none of that predicted its behaviour on our tasks.
- **"Best model for X" listicles.** No baselines, no error bars.
- **Prompt-engineering guides asserting few-shot always helps.** It hurt here on
  both models at both example counts, non-monotonically. Test a dose-response
  (0, 1, 3) rather than trusting a single setting.

---

## The shortest possible version

If you read one thing: **§0.4** (separate schema-validity from value-accuracy).
If you read two: add **§0.1** (evaluation is measurement, so measure your
instrument).

And one rule that came from our failures rather than any paper:

> **A measurement that cannot fail is not measuring.** A baseline at 100%, a
> probe scoring 100% in every condition, a control nobody ever flags — each
> looked like success and each was a bug.
