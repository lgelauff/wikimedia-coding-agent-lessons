# Benchmark cards

One card per benchmark attempted, 2026-08-13 → 18, evaluating LiftWing's
`llm-qwen3-14b` and `llm-qwen36-27b` for a Wikimedia research pipeline.
Method and rationale: [`llm-evaluation-method.md`](llm-evaluation-method.md).
Results narrative: [`liftwing-evaluation.md`](liftwing-evaluation.md).

**The field that matters most is "Discriminating?"** — did the benchmark
separate model quality from noise, from a baseline, or from our own harness?
A benchmark that runs cleanly and cannot distinguish anything is a cost, not a
measurement.

Scoring of that field:
- **YES** — cleanly separated the model from a baseline or from another model
- **PARTLY** — produced a usable signal on one axis, not the headline one
- **NO** — ran fine, distinguished nothing
- **INVALID** — a construction error made the output meaningless or inverted

Summary: **4 YES · 2 PARTLY · 2 NO · 3 INVALID · 4 never run**

---

## 1. Deontic type classification

| | |
|---|---|
| **Question** | Can it assign a 7-way normative category to a policy statement? |
| **Items** | 318 statements from 6 nl/de/en policy pages |
| **Gold** | **LLM-generated, unvalidated** — discovered only after the run |
| **Baseline** | majority class 39.9%; modal-verb regex macro-F1 0.429 |
| **Ceiling** | unknown — no human labels exist |
| **Metric** | macro-F1 (primary), per-class recall, confusion matrix |
| **Result** | 14B 0.449 · 27B 0.572 (bare prompt) |
| **Discriminating?** | **PARTLY** — separated the two models, but the verdict was wrong |
| **Cost** | 636 calls |

The verdict ("27B passes, 14B fails") **was overturned by card 11**: with
category definitions the 14B scores 0.652, a clear pass. The benchmark
distinguished the models but measured our prompt as much as the model.
Diagnostic value was high — `obligation` at precision 1.00 / recall 0.13 is
what pointed at a boundary problem rather than a capability one.

---

## 2. Governance class classification

| | |
|---|---|
| **Question** | Who does this rule govern — content, user-user, or user-admin? |
| **Items** | 338 statements |
| **Gold** | LLM-generated, unvalidated |
| **Baseline** | majority class 60.1% accuracy |
| **Ceiling** | unknown |
| **Metric** | macro-F1; `user-admin` recall as the pre-registered asymmetric-error gate |
| **Result** | 14B 0.652 · 27B 0.685; accuracy 73.1% / 77.2%. **Both fail the gate** (recall 0.672 < 0.70) |
| **Discriminating?** | **YES** — clearly beat its baseline, and the gate failed independently of the headline |
| **Cost** | 676 calls |

**The only round-1 task whose prompt defined its categories, and the only one
that cleanly beat its baseline.** That looked like coincidence at the time; card
11 established it was causal. The asymmetric gate earned its place: the task
passes on macro-F1 and fails on the metric that decides deployment.

---

## 3. Segment type + prominence (JSON output)

| | |
|---|---|
| **Question** | Two labels per statement, emitted as JSON, with no JSON mode |
| **Items** | 338 |
| **Gold** | LLM-generated, unvalidated |
| **Baseline** | **not computed at run time — the error that made the result misread** |
| **Metric** | schema-validity and value-accuracy, deliberately separate |
| **Result** | schema-validity **100%** (338/338, both models); value-accuracy 43.2% / 58.3% |
| **Discriminating?** | **PARTLY** — decisive on format, misleading on content |
| **Cost** | 676 calls |

The most instructive card. **100% schema compliance alongside value accuracy
below the majority baseline of 70.7%** — computed afterwards, which is why the
report first showed 58.3% with no comparator and looked like a pass. Separating
the two metrics is what exposed it; had we reported a single "JSON task score"
we would have shipped the wrong conclusion.

**Also carries a harness bug**: `prominence` gold contained a value (`normal`,
9.8% of items) that the prompt never offered, so those items were unanswerable
by construction. That row is void.

**Status: unresolved, not failed** — never re-run with definitions.

---

## 4. Cross-wiki statement alignment (de↔en NPOV)

| | |
|---|---|
| **Question** | Do two statements from different language editions express the same rule? |
| **Items** | 29 labelled (of 65); labels y=4, p=10, n=15 |
| **Gold** | partial human/LLM review file — the closest thing to human gold we had |
| **Baseline** | majority class 51.7%; **oracle-tuned embedding threshold 62.1%** |
| **Ceiling** | unknown |
| **Metric** | 3-way accuracy; merge-precision as the asymmetric error (a false merge hides a policy reform) |
| **Result** | 31–34% accuracy, below both baselines. Replicated twice, on two prompts |
| **Discriminating?** | **YES** — unambiguous fail, and it replicated |
| **Cost** | 58 + 58 calls |

Retained afterwards as a **regression canary**: any harness change that makes
this suddenly pass is a bug until proven otherwise. It has since re-failed on
schedule twice, which is exactly its job.

One design lesson: defining the middle class as "related or overlapping" made it
a safe catch-all and the model chose it 21/29 times. **Stress-test the catch-all
before running.**

---

## 5. Probe A — context rot / position

| | |
|---|---|
| **Question** | Does accuracy fall when the target sits inside a long document? |
| **Items** | 12, at 43 / 8,947 / 16,400 tokens |
| **Gold** | governance_class labels (LLM-generated) |
| **Result** | **100% accuracy in every condition, including the isolated control** |
| **Discriminating?** | **INVALID** |
| **Cost** | 72 calls |

The items were drawn from a single content policy, so they almost certainly all
shared one label — a model answering "content" always scores 100%. It measured
nothing while looking like a clean pass.

**The tell was the control**: 100% in the *isolated* condition means the task was
trivial, so no drop could ever appear. **Verify the control is below ceiling
before trusting any delta.** Long-context behaviour remains completely untested.

---

## 6. Probe B — batching efficiency

| | |
|---|---|
| **Question** | Same 100 items, packed 1 / 10 / 50 / 100 per request — what does batching cost? |
| **Gold** | governance_class labels |
| **Baseline** | batch=1 (one item per call) |
| **Metric** | macro-F1 per batch size, input tokens, **row-misalignment count (disqualifying at any quality)** |
| **Result** | **zero misalignments at every size, both models**; batch-100 used 2,161 vs 9,393 input tokens (**4.3×**). 14B degraded 0.786→0.595; 27B *improved* 0.622→0.756 |
| **Discriminating?** | **YES** — and the only card that produced an immediately actionable change |
| **Cost** | 226 calls |

The one unambiguous win. The disqualifying criterion mattered: a silently
misaligned batch corrupts every label with no error signal, so it had to gate
adoption independently of accuracy.

The 27B *improving* with batch size is counter-intuitive and rests on n=100 over
3 classes — **replicate before relying on it.** It may be in-context learning
from seeing many items at once, which would confound card 11's shot track.

---

## 7. Agreement-as-confidence (re-analysis, zero new calls)

| | |
|---|---|
| **Question** | Is cross-model agreement a usable confidence signal? |
| **Items** | 1,023 item-pairs already collected |
| **Baseline** | the better single model at full coverage (64.3%) |
| **Result** | agreement-gated **63.8% at 73.7% coverage** — worse than the 27B alone |
| **Discriminating?** | **YES** — cleanly refuted the hypothesis |
| **Cost** | **zero calls** |

The cheapest card here and it killed a proposed pipeline before any engineering.
**Cause: correlated error.** Two models from the same family share failure modes,
so agreement is a shared prior, not independent evidence — the published result
we were importing concerned ensembles of *different* small models.

A real signal did fall out: on disagreements, at least one model is right 84% of
the time. Complementary knowledge exists; agreement just cannot locate it.

**Do the zero-call re-analysis first.**

---

## 8. Source extraction (retrieve-then-rerank)

| | |
|---|---|
| **Question** | Given a claim and 8 retrieved passages, pick the supporting one and quote it |
| **Items** | 134 positive + 29 hard negatives, from 46 cached papers |
| **Gold** | claim→passage mappings — **LLM-produced and not verbatim** (3.9% exact substrings) |
| **Baseline** | **BM25 recall@1 = 21.6%** (a real, non-LLM baseline) |
| **Ceiling** | BM25 recall@8 = 69.4% — the gold is absent from the shortlist 31% of the time |
| **Metric** | rerank accuracy; abstention; **quote-hallucination rate (needs no gold)** |
| **Result** | rerank 30.1% / 28.0% vs BM25 31.2% — **indistinguishable**. Quote fabrication **11.9% / 5.6%** |
| **Discriminating?** | **YES** on the gold-free metric, **NO** on rerank |
| **Cost** | 344 calls |

The most important card for deployment. The rerank result cannot separate the
model from BM25 — but **the quote check needed no gold at all**, so it survived
the discovery that the gold was unusable. ~1 in 8 quotes from the 14B is not in
the passage it claims to quote.

Two design saves worth copying: the task was **reshaped** when the gold proved
non-verbatim (a "did it return the gold span" metric was impossible), and a
**leak was caught mid-build** — the first BM25 test scored 100% recall@1 because
the gold passage was inside the query.

---

## 9. Code-review agreement study

| | |
|---|---|
| **Question** | Can a cheap model substitute for an expensive one as a reviewer? |
| **Items** | 56 real diffs + 20 null controls, 7 repos |
| **Gold** | **none — deliberately.** Review has no ground truth; our own bug-fix commits are not gold |
| **Ceiling** | **reference-vs-reference κ = 0.138** (GPT-4o-mini vs Gemini 2.5 Flash) |
| **Metric** | Cohen's κ vs each reference; invented-issue rate on nulls |
| **Result** | **Task not measurable.** Flag rates ranged 79% to 11% across raters |
| **Discriminating?** | **NO** (agreement) / **INVALID** (null control, first pass) |
| **Cost** | ~450 calls across 6 raters |

The ceiling is the finding: two capable models from different families barely
agreed with each other, so there was no stable signal to substitute *for*. Our
scorer nonetheless printed *"150% of ceiling → SUBSTITUTABLE"* by dividing by
near-zero — now blocked below κ=0.20.

**The null control inverted.** Rename-based "functionally identical" diffs
contained genuine undefined-variable defects, so a model correctly reporting one
was scored as *inventing* an issue. **qwen36-27b caught it; the harness was
wrong.** Result withdrawn; generator now verifies every occurrence lies inside
the diff before renaming.

Also confounded by base rate: κ between a 79%-flagger and an 11%-flagger is near
zero regardless of judgement quality.

---

## 10. Rate-limit boundary probe

| | |
|---|---|
| **Question** | Is the anonymous LLM cap 100/hour (our figure) or 50,000/hour (a community skill's)? |
| **Method** | 120 calls at 5 req/s from a laptop, no OAuth, local bucket disabled |
| **Result** | **429 at exactly call 101**, after 27 seconds |
| **Discriminating?** | **YES** — settled a 17-day-old question in 27 seconds |
| **Cost** | 101 calls |

Both figures were right for different things: the community table describes the
general API gateway, the LLM service carries its own tighter quota. It is a
**quota of ~100, not a smooth rate** — spendable in under half a minute.
Toolforge is exempt (2,344 calls at 2 req/s, no 429).

Confirmed a third time that our 39.9s median latency on 2026-08-01 was entirely
our own rate bucket; unthrottled it is 0.25s.

**When an external source contradicts your figure by orders of magnitude, probe
the boundary rather than picking a side.**

---

## 11. Prompt-specification sweep (9 arms)

| | |
|---|---|
| **Question** | Was the round-1 failure the model, or how we asked? |
| **Items** | 276 scored per arm (42 held out for examples), 9 arms, 2 models |
| **Gold** | LLM-generated — **but every arm shares it, so the deltas are valid regardless** |
| **Baseline** | `bare` arm, **byte-identical to round 1 on all 276 items (verified)** |
| **Metric** | Δ macro-F1 vs bare; `obligation` recall; `principle` precision; sink check |
| **Result** | definitions **+0.217 (14B) / +0.145 (27B)**; obligation recall 0.12→0.62 and 0.44→0.87 |
| **Discriminating?** | **YES** — the most informative card of the set |
| **Cost** | 4,968 calls, ~40 min |

**Overturned card 1's verdict.** Three findings that run against common practice:

- **Few-shot HURT** on both models at both counts, non-monotonically (1-shot <
  3-shot < 0-shot). Likely because the examples carry the same inconsistent
  LLM labelling.
- **JSON input gave the best per-class recall** (0.80 on the 14B, 0.91 on the
  27B) while scoring *lower* on macro-F1 — macro-F1 weights a 9-item class like
  a 121-item one. Choose the metric before the format.
- **Room to reason helped the weak model** (+0.190) and **not the strong one**
  (+0.003), and was the only arm that ever failed to parse (4%).

The escape hatch was **never used once** in any arm. Offering it is free; the
model will not take it.

**Not fixed:** one category stayed a sink in all 18 cells. Specification
explains much of the pathology, not all.

---

## 12. Rejected before running — the nl-wiki policy quiz

| | |
|---|---|
| **Why considered** | 25 multiple-choice questions with an answer key and per-question source citations |
| **Why rejected** | **18 of 25 answers were "b"** — always-answer-b scores 72%. And the source file for 5 questions has all 23 year headings but **only one non-empty content line**, so those answers came from the live page, not the snapshot |
| **Discriminating?** | would have been **NO** |

Cost: zero. **Checking the answer-key distribution and the source file took
minutes and avoided a benchmark that would have measured position bias.**

---

## 13–16. Designed, not run

| card | gold | why it is worth running |
|---|---|---|
| **Wikipedia Detox (tone)** | **~10 human annotators per comment**, graded scores, CC0 | the only design where accuracy would mean accuracy; ceiling computable *from the data*; published non-LLM baseline (AUC ~0.96) |
| **FEVER-anchored claim verification** | 185k human-written claims | external calibration against a public leaderboard |
| **Corrected context-rot probe** | needs class-balanced items | decides whether whole-document work is viable at all — currently unknown |
| **Codebook validation (Task G)** | **BLOCKED** — no codebook exists and the label set has drifted across four variants | no prompt fixes an underspecified category |

---

## What the cards say collectively

**Gold provenance was the systemic weakness.** Eight of eleven executed cards
scored against LLM-generated or partial labels. The three metrics that survived
scrutiny — quote-in-source, row misalignment, and the 429 boundary — are the
three that **needed no gold at all**.

**Baselines decided more verdicts than models did.** Majority class, a
modal-verb regex, BM25 and an oracle-tuned embedding threshold each changed a
reading. Two cards were misread until a baseline was computed afterwards.

**Three of eleven were invalidated by our own construction.** In every case the
tell was the same: *a number that could not fail.* 100% recall@1, 100% accuracy
in every condition, a control nobody flagged.

**The cheapest cards were among the most informative.** The zero-call
re-analysis refuted a pipeline; a 101-call probe settled a 17-day question; a
minutes-long check on an answer key avoided a worthless benchmark.
