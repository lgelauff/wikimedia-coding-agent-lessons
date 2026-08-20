# Where the benchmark designs came from

Provenance for [`benchmark-cards.md`](benchmark-cards.md) and
[`llm-evaluation-method.md`](llm-evaluation-method.md). Written because "is this
grounded in literature or did you make it up?" is a fair question with a mixed
answer, and for research use the distinction matters.

Three tiers, honestly separated:

- **Tier A** — a paper read during this work that changed a design
- **Tier B** — standard practice applied from background knowledge, not read here
- **Tier C** — our own invention, with no literature behind it

---

## Tier A — papers that actually changed a design

### 1. LLMs are weak extractors but useful rerankers
**"Large Language Model Is Not a Good Few-shot Information Extractor, but a Good
Reranker for Hard Samples!"** — [arXiv 2303.08559](https://arxiv.org/pdf/2303.08559)

**Changed:** benchmark card 8. The original design asked the model to extract a
supporting passage from a whole paper. This paper's filter-then-rerank framing
is why it became "rerank a BM25 shortlist" instead — which also happened to
solve a context-window problem.

**Held up?** Partly. The model was *indistinguishable* from BM25 rather than an
improvement on it, so the reranking value the paper reports did not appear here.

### 2. Schema compliance ≠ value correctness
**The Structured Output Benchmark** — [arXiv 2604.25359](https://arxiv.org/pdf/2604.25359);
also **LLMStructBench** ([2602.14743](https://arxiv.org/html/2602.14743v1)) and
**ExtractBench** ([2602.12247](https://arxiv.org/html/2602.12247v2)).

Reported near-perfect schema compliance alongside best-case value accuracy of
83.0% on text.

**Changed:** card 3, and it is the single most consequential borrowing here.
Because of this we scored **schema-validity and value-accuracy as separate
metrics**. We then measured 100% schema-validity with value accuracy *below the
majority baseline*. A single combined "JSON task score" would have shipped the
wrong conclusion.

**Held up?** Exactly — the pattern reproduced.

### 3. Format restriction degrades reasoning
**"Let Me Speak Freely? A Study on the Impact of Format Restrictions on
Performance of LLMs"** — [arXiv 2408.02442](https://arxiv.org/abs/2408.02442)

**Changed:** the `defined_reason` and JSON arms in card 11. Round 1 capped every
classification call at 4–12 output tokens, making deliberation structurally
impossible; this paper is why we treated that as a variable rather than a
constant.

**Held up? Only partly, and the divergence is interesting.** The paper predicts
format restriction hurts. We found it is **metric-dependent**: JSON input
*improved* recall on dominant classes (0.62 → 0.80 on the 14B) while *lowering*
macro-F1. And extra reasoning room helped the weaker model (+0.190) but not the
stronger (+0.003). "Restriction hurts" was too coarse for what we saw.

### 4. Macro-F1 under class imbalance
Found via survey material rather than one canonical paper — e.g.
[arXiv 2404.09135](https://arxiv.org/pdf/2404.09135) on LLM evaluation metrics.

**Changed:** made macro-F1 primary everywhere and accuracy secondary, and made
**the gap between them** the frequency-bias diagnostic.

**Held up?** Yes, and it caught the failure it was chosen for: 37.9% accuracy
while the model never once emitted one of three labels.

### 5. ROUGE conflates independent failure modes
Faithfulness/hallucination literature — **HaRiM+**
([arXiv 2211.12118](https://arxiv.org/pdf/2211.12118)), the **Hallucinations
Leaderboard** ([2404.05904](https://arxiv.org/pdf/2404.05904)).

**Changed:** the (unrun) summarization design scores **faithfulness and coverage
separately and never uses ROUGE**. Untested — we never ran that card.

### 6. "Lost in the middle" / context rot
∞Bench and RULER-adjacent work; U-shaped accuracy by position, 20–30 point mid-
context drop, and degradation with input length even when evidence is well-placed.

**Changed:** motivated Probe A (card 5). **The probe was invalid for unrelated
reasons** — our items all shared one label — so we tested none of this.

### 7. False-positive rates dominate review tasks
Project-scale LLM vulnerability work reporting ~97% false discovery;
**PeerReviewBench** putting frontier models at 41–51% F1 on paper review;
**SWR-Bench** ([arXiv 2509.01494](https://arxiv.org/html/2509.01494v2)).

**Changed:** card 9 leads with the **null control** — clean inputs, count what
gets invented — rather than with agreement. Good instinct; our null control then
turned out to be broken, which is a Tier C failure, not a literature one.

### 8. Wikipedia Detox
**"Ex Machina: Personal Attacks Seen at Scale"**, Wulczyn, Thain & Dixon —
[arXiv 1610.08914](https://arxiv.org/pdf/1610.08914); data CC0 on Figshare
(doi 10.6084/m9.figshare.4054689), ~100k comments, ~10 annotators each.

**Changed:** the highest-priority unrun card. It is the only design where a
**human-agreement ceiling is computable from the data** and a published non-LLM
baseline (AUC ~0.96) exists.

### 9. FEVER
185,445 human-written claims over Wikipedia evidence, Supported / Refuted /
NotEnoughInfo. **Changed:** the (unrun) claim-verification design, as an external
calibration anchor.

### 10. Agreement-based ensembles of small models — **imported and REFUTED**
Survey material claiming sub-10B models in an agreement framework can exceed a
single 70B+ model.

**Changed:** motivated card 7. **We were wrong to import it.** The published
condition concerns ensembles of *different* small models; qwen3-14b and
qwen36-27b are the same family with correlated errors, so agreement is a shared
prior rather than independent evidence. Agreement-gating scored *worse* than the
better model alone.

**Lesson: check the independence assumption before importing an ensemble
result.** The paper was not wrong; our application of it was.

---

## Tier B — standard practice, applied from background knowledge

Not read during this work. Flagged because they are load-bearing and were used
without re-derivation:

| what | where used | note |
|---|---|---|
| **Cohen's κ, Fleiss' κ** | card 9 | implemented from the standard formulas |
| **Landis & Koch (1977) interpretation bands** | card 9 `interpret()` | "substantial / moderate / fair / slight" — a 1977 convention, widely used and widely criticised as arbitrary |
| **BM25** (Robertson & Spärck Jones) | card 8 baseline | standard parameters k1=1.5, b=0.75, not tuned |
| **Precision / recall / confusion matrices** | throughout | — |
| **Binomial standard error** for "is this difference real" | cards 8, 11 | crude; no multiple-comparison correction across 9 arms |

**A caveat on the last row:** card 11 compares nine arms against one anchor with
no correction for multiple comparisons. The headline effect (+0.217) is far too
large for that to matter; the smaller inter-arm differences (e.g. 1-shot vs
3-shot) are not safe to read individually.

---

## Tier C — our own, with no literature behind it

Invented for this work. Some earned their place; one actively caused a wrong
result.

- **The `prepare → rate → score` harness split**, with scoring never re-calling
  the model. Practical, not principled — but it made every metric bug free to fix.
- **The gold-free metric principle** — prefer checks needing no labels
  (quote-in-source, row-count alignment, HTTP status). This *emerged from our own
  failure*: after discovering the gold was LLM-generated, the gold-free metrics
  were the only ones still standing.
- **"A measurement that cannot fail is not measuring"** — our formulation, from
  three separate incidents (100% recall@1, 100% at every context length, a null
  control nobody flagged).
- **The replication-anchor arm** (byte-identical to the previous round) — this is
  ordinary experimental hygiene, but we did not take it from anywhere.
- **The rename-based null control — our invention, and it was wrong.** It created
  genuine undefined-variable defects, so a model correctly reporting one scored
  as *inventing* an issue. qwen36-27b caught it. **No literature to blame.**
- **The ceiling floor (refuse a verdict below κ=0.20)** — our patch after the
  scorer printed "150% of ceiling → SUBSTITUTABLE" by dividing by near-zero.

### One important non-literature source

**Pre-registering the threshold** — arguably the most valuable discipline in the
whole programme — came from `policy_network_review2_llm.md`, an **adversarial LLM
review of the user's own project design**, not from a paper. Its line was:
*"Without a pre-registered threshold the eval is decoration — you will run it,
get some number, and rationalize whichever number you get."*

Worth recording that a critique generated inside the project shaped the method
more than most of the papers did.

---

## Honest summary

**Grounded:** the metric choices (macro-F1 under imbalance, schema-vs-value
separation, faithfulness-vs-ROUGE), the reranking reframe, the format-restriction
variable, and both external datasets.

**Not grounded, and it shows:** benchmark *construction* — null controls, leak
checks, replication anchors, ceiling handling. That is where all three invalid
cards came from. There is a substantial literature on experimental design for ML
evaluation that we did not consult, and three broken probes is roughly the cost
of not consulting it.

**Actively mis-imported:** one ensemble result, applied without checking its
independence condition.

**Nothing here was peer-reviewed, replicated by anyone else, or run on more than
one project's data.**
