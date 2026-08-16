# LiftWing benchmark round 2 — source work and discussion tone

Round 1 verdict: **operationally excellent, analytically weak** — lost to
majority-class or regex baselines on 3 of 4 tasks
([`../feedback/liftwing.md`](../feedback/liftwing.md), 2026-08-14).

Round 2 asks a different question: **were we testing the wrong task family?**
Every round-1 task was fine-grained taxonomic classification with fuzzy category
boundaries, forced-choice, on a homemade rubric. Published work says that is
close to the worst case for a mid-size open model.

## What the literature actually says

- **"LLM Is Not a Good Few-shot Information Extractor, but a Good Reranker for
  Hard Samples"** (arXiv 2303.08559). Fine-tuned small models beat LLMs at
  extraction; LLMs earn their place *reranking* a shortlist a cheap filter
  produced. **So stop asking the model to choose from a taxonomy; ask it to
  verify or rank a candidate.**
- **Agreement-based ensembles of sub-10B models can exceed single 70B+ models**
  on classification, when a decision is only taken if models agree. We have two
  models and 338 items already labelled by both — testable at zero cost.
- **Selective prediction**: the established framing is a coverage/accuracy
  trade-off (AUACC, C@Acc = max coverage at which accuracy ≥ Acc), not
  forced-choice accuracy. Round 1 gave the model no way to say "I don't know",
  so it dumped hard cases into vague classes (`principle` P=0.14 R=0.91).
- **Qwen3-14B's published strengths are MMLU-Redux 82.0, MATH-500 90.0,
  GPQA-Diamond 54.8** — factual recall, maths, reasoning. Nothing like what we
  tested.
- **Purpose-built rerankers are ~60× cheaper, 48× faster and up to 15% more
  accurate than LLM rerankers.** The same lesson as the LiftWing classifiers:
  if a specialised model exists, it wins.

## Round-2 principles

1. **Verify, don't classify.** Binary or graded judgements on a candidate, not
   n-way taxonomy selection.
2. **Allow abstention.** Every task offers "insufficient evidence". Report the
   coverage/accuracy curve, not one accuracy number.
3. **Use agreement as the confidence signal** — 14B and 27B must concur, else
   escalate.
4. **Prefer external benchmarks with published baselines.** Round 1 graded its
   own homework. Detox and FEVER come with strong prior art to lose to.
5. **Compute the trivial baseline first, always.** `segment_json` looked fine at
   58% until "always answer rule" scored 70.7%.

---

## Task A — Source extraction (the objectively scoreable one)

**Given a claim and a full paper text, return the passage that supports it.**

- **Gold:** `wikimedia-analysis/AI effects/v2/archive/claim_mapping_part*.json`
  — **281 claim→passage mappings, 46 papers, 26 distinct claims**, passages
  median 360 chars. Full source text in `research-vault/cache/<citekey>.txt`.
- **The metric is free and objective: is the returned span a verbatim substring
  of the source?** No judge, no embedding, no rubric. A model that invents a
  quote fails instantly.
- Metrics: **verbatim-hit rate** · **span overlap** (character IoU with the gold
  passage) · **hallucinated-quote rate** (returned text absent from source —
  the headline number) · abstention rate when the claim genuinely is not
  supported.
- **Baseline:** BM25 / TF-IDF best-matching paragraph. Cheap, strong, and the
  thing an LLM must beat to justify itself.
- **Why this matters most:** it is exactly the `collect-source` citation
  discipline — *"Only cite claims verified against the cached primary text."*
  If the model can reliably return a real quote, it automates the verification
  step. If it hallucinates quotes, that is disqualifying and worth knowing.

## Task B — Claim–source verification (FEVER-shaped, own data)

**Given a claim and a passage, does the passage support it?**

- **Positives:** the 281 gold mappings. **Negatives:** pair each claim with
  passages from *other* papers (hard negatives: same claim family, wrong paper).
- 3-way with abstention: supported / not supported / insufficient evidence.
- **Do not** use the raw `relation` field as the label — it is 241 supporting /
  38 qualifying / **2 contradicting**, so majority-class scores 85.8% and
  `contradicting` is unscoreable. Construct balanced pairs instead.
- **External anchor: FEVER** (185,445 claims over Wikipedia evidence,
  Supported / Refuted / NotEnoughInfo). Run a 500-claim sample to place
  LiftWing against a large published leaderboard. This is the calibration
  round 1 lacked entirely.

## Task C — Discussion tone (Wikipedia Detox)

**The Perspective API training data**, and the best-designed benchmark
available to us.

- **Source:** Wikipedia Detox / Wikipedia Talk Labels — **~100k talk-page
  comments, ~1M crowd annotations, 10 judgements per comment**, three
  dimensions: **personal attack, aggression, toxicity**. Public on Figshare;
  code at `github.com/ewulczyn/wiki-detox`; paper *Ex Machina: Personal Attacks
  Seen at Scale* (arXiv 1610.08914). Release notes:
  `meta.wikimedia.org/wiki/Research:Detox/Data_Release`.
- **Why it is the strongest option on the table:**
  - **Graded labels, not binary.** 10 annotators per comment gives a continuous
    score, so we can measure **correlation with human consensus** (Spearman)
    rather than pass/fail — a much more informative signal than accuracy.
  - **A published non-LLM baseline exists** (char n-gram + logistic regression,
    AUC ~0.96). We are not grading our own homework.
  - **Class balance is ours to choose** by sampling — no majority-class trap.
  - **Different task family**: affective/pragmatic judgement, not taxonomy
    lookup. This is the actual test of whether round 1's failure was the task
    type or the model.
  - It is Wikipedia governance data, so it transfers to the deliberation and
    moderation work directly.
- Metrics: Spearman ρ against mean human score · AUC on the binary threshold ·
  **accuracy at coverage** using inter-annotator agreement as the difficulty
  axis (do the models fail exactly where humans disagree?).
- **Fetch via the research-vault pipeline** (`collect-source`), not ad hoc.

## Task D — Free, zero new calls: agreement as confidence

Round 1 already has both models' predictions on the same 338 items in
`results.jsonl`. Compute:

- accuracy **on the subset where 14B and 27B agree**, and coverage of that subset
- the same for disagreement (expected: near chance)
- **AUACC / C@Acc** treating agreement as the confidence signal

If agreement-gated accuracy is high at usable coverage, the deployment pattern
is *ensemble-and-escalate*: take the agreed labels, route disagreements to a
stronger model. That would make round 1's "failure" a usable pipeline after all,
without a single extra call.

**Do this first — it is free and it may change the verdict.**

---

## Task E — Advisory / review, measured as AGREEMENT, not correctness

Reviewing a diff, a paper, or a draft has **no gold**. Our own bug-fix commits
are not gold either — they are one developer's judgement at one moment, and the
commit message frequently misdescribes what was actually wrong. Treating them as
truth would manufacture a ground truth that does not exist.

**So do not measure correctness. Measure substitutability:** does LiftWing reach
the same judgements as the models we currently pay for? That is the real
question — *can the free model stand in for the expensive one?*

### Design

- **Subjects:** `llm-qwen3-14b`, `llm-qwen36-27b`
- **Reference raters:** at least two from **different model families** — Claude
  (`AGENT_LLM_PROVIDER=claude-code`) and Mistral/OpenRouter. Different families
  matter: task D proved that same-family agreement is inflated by correlated
  error, so a qwen-vs-qwen number means little.
- **Items:** real diffs from our repos, paragraphs from drafts in progress,
  sections of papers in `research-vault/cache/`.
- **Output contract:** force structure so agreement is computable — e.g. per
  item `{issue_present: bool, category: <fixed list>, severity: 1-5}`. Free-form
  prose reviews cannot be scored for agreement without a judge, which just moves
  the problem.

### Metrics

- **Cohen's κ pairwise** (chance-corrected). Raw agreement % is meaningless
  under class imbalance — if 90% of paragraphs have no issue, "always say no"
  scores 90% agreement.
- **Krippendorff's α** across all raters for the graded `severity` field.
- Agreement with the **majority verdict of the reference raters**.

### The measurement that makes the rest interpretable

**Compute reference-vs-reference agreement first, as the ceiling.**

If Claude and Mistral only agree with each other at κ=0.40, then LiftWing at
κ=0.35 is *as good as any rater* and the task is simply subjective. Without that
ceiling, a low LiftWing κ is uninterpretable and will be misread as "the small
model is bad" when the honest reading is "nobody agrees about this."

This is the single most important design element in Task E, and it is the one
most agreement studies leave out.

### The null control — still required

Round 1 showed these models cannot say "no" (`principle` P=0.14 R=0.91).
Published work corroborates: a project-scale LLM vulnerability study found
**~97% false discovery rate**, and PeerReviewBench puts frontier models at only
41–51% F1 on paper review. So include **unmodified, known-clean items** and
measure the invented-issue rate. An advisor that flags everything costs more
time than it saves, and that failure will not show up in an agreement number
if every rater is equally trigger-happy.

### Interpretation guard

High agreement with Claude means LiftWing is a **substitute**, not that either
is **right**. Keep those two claims apart in anything written up.

---

## Tasks F–K — "are we asking the question wrong?"

Round 1 asked one question one way. These six vary *how we ask*, each isolating
a single variable, all on the same items so results are comparable. **G comes
first: until it runs, none of the others have a meaningful yardstick.**

---

## Task G — Is the gold actually gold? (DO THIS FIRST)

**All 340 classification labels were LLM-generated** (`runs/README.md`: "an LLM
agent per page"). Every round-1 accuracy figure is therefore *agreement with an
unnamed model*, against an unknown human ceiling.

- **Method:** stratified subsample of **50 statements** (all 7 deontic classes,
  over-sampling the sink classes `principle`/`procedure` and the starved
  `obligation`). Label them by hand against `RATING_RUBRIC.md`, blind to the
  existing labels. A second pass by another person on 20 of them gives a
  human–human figure.
- **Report:** human-vs-gold Cohen's κ = **the ceiling**; human–human κ = the
  ceiling *on the ceiling*.
- **Decision rule, fixed now:**
  - κ(human, gold) **> 0.7** → the gold is usable; round-1 numbers stand as
    agreement-with-a-good-labeler.
  - **0.4–0.7** → round-1 accuracies are *unqualified* and must be restated as
    inter-model agreement.
  - **< 0.4** → the gold does not encode a reproducible rubric. **Round-1
    classification results are withdrawn**, and the finding becomes "this
    taxonomy is not reliably applicable", which is a result about the *rubric*,
    not the model.
- 50 items of human labelling. The cheapest and highest-leverage thing on this
  entire list.

---

## Task H — Answer format: forced choice is an artifact

We forced an n-way pick with no escape hatch. A model that cannot say "unclear"
must put every hard case somewhere, and picks the vaguest bucket — so part of
the sink pattern is our answer format, not the model.

Same items, four formats:

1. **forced n-way** (round-1 replication)
2. **+ "unclear / none of these"** — measures how much of the sink was coercion
3. **binary cascade** — "is this an obligation? y/n", then prohibition, etc.
   Small models are typically better at binary decisions than n-way ones.
4. **reason-then-answer** — one sentence of justification before the label
   (costs tokens; the question is whether it buys accuracy)

**Metric:** macro-F1, plus sink-class precision, plus — for format 2 — the
**coverage/accuracy curve**, since abstention makes this a selective-prediction
problem rather than a classification one.

---

## Task I — Direction: verify instead of generate

Published work has LLMs weaker at generating a label than at checking one.
Round 1 only ever asked them to generate.

- **Generate:** "which class is this?"
- **Verify:** "this statement was labelled `obligation`. Correct? y/n"
- Verify each item against its gold label **and** against a deliberately wrong
  label, so accept-rate and reject-rate are separable.

**The failure mode to watch: a yes-machine.** If it accepts the wrong label as
readily as the right one, verification framing adds nothing — and that will look
like high accuracy if only correct labels are presented. **Both arms are
required for the result to mean anything.**

---

## Task J — Context: we stripped it, and never legitimately tested it

Round 1 showed isolated statements with no page, section, or title. A rule's
deontic type may be genuinely ambiguous without that. Probe A tried to test this
and was invalid (every item shared one label, so it scored 100% everywhere
including the isolated control).

- **Arms:** statement alone · + section heading · + surrounding paragraph ·
  + page title and type.
- **Rebuild the items class-balanced**, and **verify the isolated arm scores
  below 100% before trusting any delta.** That check is what Probe A lacked.
- This also finally measures long-context behaviour on real data.

---

## Task K — Self-consistency: the confidence signal we still lack

Cross-model agreement was refuted (correlated errors, same family). *Within*-model
sampling is a different mechanism and remains untested.

- Sample **k=5 at temperature 0.7**, take the majority label.
- **Metrics:** majority-vote macro-F1 vs single-sample greedy; and — the real
  prize — **does sample disagreement predict error?** If items where the 5
  samples split are the items it gets wrong, that is a usable confidence signal
  and enables the escalate-on-uncertainty pipeline that Task D failed to deliver.
- Cost: 5× calls. Free, and batching absorbs it.

---

## Task F — Specification ladder (was: few-shot)

Few-shot is one rung, not the whole question. **Each rung adds exactly one
thing**, on identical items, so the gain is attributable:

**Every result so far is zero-shot.** Before concluding anything about these
models, test the cheapest intervention that targets the *specific* failure we
measured.

| rung | adds | why |
|---|---|---|
| 1 | bare label list | reproduces round 1 |
| 2 | **category definitions** | the `governance_class` treatment — the only task that beat its baseline was the only one with definitions |
| 3 | + "unclear" option | removes the forced-choice artifact (shares an arm with Task H) |
| 4 | + k random examples per class | classic few-shot |
| 5 | + boundary-case examples | drawn from the actual confusion cells (obligation↔principle) |

**Rung 2 is the one to watch.** If definitions alone close most of the gap, the
round-1 verdict is largely a prompt artifact and the memo needs rewriting. If
rungs 2–5 barely move it, the verdict stands and is far better supported than it
is now.

### The falsifiable hypothesis

Round 1's dominant failure was not incapacity, it was **not knowing where the
category boundaries are**:

| class | 14B | 27B | pattern |
|---|---|---|---|
| `principle` | P=0.14 R=0.91 | P=0.22 R=0.74 | **sink** — everything lands here |
| `procedure` | P=0.24 R=1.00 | P=0.26 R=1.00 | **sink** |
| `obligation` (largest, n=127) | P=1.00 **R=0.13** | P=0.97 **R=0.45** | starved |

Precision 1.00 with recall 0.13 on the biggest class means: *when it says
obligation it is always right, but it usually says something vaguer.* The model
knows the concept and not the boundary. **Demonstrating boundaries is precisely
what few-shot examples do.**

**H1:** k-shot examples raise `obligation` recall and `principle` precision
substantially, with a smaller effect on overall macro-F1.
**H0:** few-shot moves macro-F1 by less than 1 SE and the sink pattern persists —
in which case the limitation is the model, not the prompt, and round 1's verdict
stands as written.

This is falsifiable in the right direction: **H1 predicts a specific per-class
movement, not just "the number goes up."**

### Design

Task: `deontic_type` (7 classes, n=318, worst sink behaviour, and a real regex
baseline at macro-F1 0.429 already established).

Two crossed variables:

| variable | levels |
|---|---|
| **k** (examples per class) | 0 (replicates round 1), 1, 3, 5 |
| **selection** | class-balanced random · **retrieved** (BM25-nearest to the item) · **boundary-pairs** (examples drawn from the confusion cells: obligation↔principle, condition↔procedure) |

Run `k=0` again rather than reusing round 1's number, so the comparison is
within one run and one prompt template.

### Leakage control — the thing that will silently break this

**Split first, once, and freeze it.** Examples come from a held-out pool that
never enters the scored set; with `retrieved` selection it is otherwise trivial
to hand the model the test item's near-duplicate. Hold out ~60 items (stratified
by class), score on the remaining ~258, and record the split in the items file so
every k and every selection strategy is scored on **identical** items.

Verify explicitly: assert no scored item id appears in any prompt.

### Metrics

- **Primary (the hypothesis):** `obligation` recall and `principle` precision.
- **Secondary:** macro-F1 vs the k=0 arm and vs the regex baseline (0.429).
- **Diagnostic:** labels-used count and the confusion matrix — did the sink
  drain, or did it just move to a different class?
- **Cost:** prompt tokens per item at each k. Few-shot is not free and the
  comparison must be cost-aware.

### Pre-registered pass mark

Few-shot is worth adopting if **`obligation` recall improves by ≥ 0.20
absolute** (from 0.13/0.45) **without `principle` precision falling**, at a token
cost the batching result absorbs.

### Why it is nearly free, and the one interaction to watch

**Combine with batching (Probe B).** In a batch of 100 items the few-shot block
is paid for **once**, not 100 times — so `k=5` batched costs a fraction of `k=5`
one-per-call. Probe B already showed 4.3× token savings with zero row
misalignment.

But the two interact and must not be conflated: **a batch is itself a form of
context**, and the 27B *improved* with batch size (0.622 → 0.756), which may
already be an in-context-learning effect from seeing many items at once. So run
few-shot at **fixed batch size** and vary only k, or the two effects are
inseparable.

### Cost

~258 scored items × 4 k-levels × 3 selection strategies × 2 models ≈ 6,200 calls
unbatched, ~1,500 batched. Free; roughly an hour on Toolforge.

---

## Suggested order

1. **D** — free, minutes, may reframe round 1. **DONE 2026-08-14: refuted**
   (agreement-gating scored worse than the 27B alone; see `../feedback/liftwing.md`).
2. **A** — objective metric, own gold. **DONE 2026-08-15: unusable**
   (indistinguishable from BM25; fabricates ~1 in 8 quotes).
3. **F** — **do this next.** Cheapest intervention, targets the measured failure,
   and until it runs, every round-1 conclusion carries an unstated "zero-shot"
   qualifier.
4. **C** — external, published baseline, best-designed data; most likely to
   yield a positive result.
5. **B** — needs negative construction; FEVER sample for calibration.
6. **E** — re-run only after the null control is rebuilt and validated; as posed
   the task was not measurable (ceiling κ=0.138).
