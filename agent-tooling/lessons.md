# Benchmark-design lessons

Hard-won from building and running LLM benchmarks in `scripts/` and
`playbooks/`. Every one of these was paid for with a wrong number that looked
right. Results live in [`feedback/liftwing.md`](feedback/liftwing.md).

---

## 1. Compute the trivial baseline BEFORE you read any result

The single most expensive omission. A `segment_type` classification scored
**58.3% value-accuracy with 100% schema compliance** and read as a pass. Then
the majority-class baseline turned out to be **70.7%** — "always answer `rule`"
beat the model outright.

The report had no baseline column, so the number looked like a grade. It was a
loss.

**Rule:** a metric without its baseline printed beside it is not a result, it is
a number. Compute majority-class, regex/heuristic, and (where relevant) an
*oracle-tuned* baseline — thresholds fitted on the test set itself. A generous
baseline is the honest one: if the model cannot beat a baseline that cheated,
it cannot beat it.

## 2. Accuracy hides label collapse; report macro-F1 alongside it

A model scored 37.9% accuracy on a 3-way task **while never once emitting one of
the three labels**. Accuracy cannot see that. Macro-F1 penalises it directly,
because a never-predicted class contributes an F1 of 0.

**Rule:** report macro-F1 (primary) *and* accuracy, per-class recall, and a
`labels used N/M` line. The **gap** between accuracy and macro-F1 is the
frequency-bias diagnostic.

## 3. Stress-test the catch-all class before you run

Defining a middle class as "related or overlapping" made it the safe answer and
the model chose it 21/29 times. The same pathology recurred at scale: loose
classes act as sinks (`principle` P=0.14 R=0.91, `procedure` P=0.26 R=1.00)
while the largest class starves (`obligation` R=0.13).

**Rule:** for every label set, ask *"is there a class a lazy model can always
pick?"* If yes, either tighten its definition or expect it to absorb everything.

## 4. Schema-validity and value-accuracy are different metrics

676 JSON calls returned **100% schema-valid** output whose **values lost to
always-answering-the-majority-class**. Perfect form, useless content. A pipeline
gating on "did it parse?" would have shipped garbage at scale and never known.

**Rule:** never let structural validity stand in for correctness. Score them
separately, always, and say so in the report.

## 5. Your null control can contain the very bug you are testing for

The worst one. A code-review benchmark built "functionally identical by
construction" null diffs by renaming an identifier — but renamed only on `+`/`-`
lines, leaving context lines untouched. A parameter declared on a context line
kept its old name while the body referenced the new one: **an undefined
variable, a genuine severe defect, inside the control that was supposed to
contain none.**

A model correctly reported it. The benchmark would have scored that as an
*invented issue* — **penalising the model for being right**, and systematically
favouring whichever model noticed least.

Caught only because a verdict was read by hand instead of trusted as a number.

**Rule:** a control is a claim about ground truth and needs verifying like any
other. Assert the invariant mechanically (here: no orphaned original identifier
survives anywhere in the diff) and spot-read raw outputs before trusting a
score. And prefer transformations that are *provably* safe — this rename is only
safe when every occurrence in the whole file at that revision is inside the
hunk being rewritten.

## 6. Check the independence assumption before importing an ensemble result

Published work says agreement-based ensembles of small models can beat a single
large one. Applied to `qwen3-14b` + `qwen36-27b` it **failed**: agreement-gated
accuracy 63.8% at 73.7% coverage, against **64.3% from the 27B alone at full
coverage**. Discard a quarter of the data, get worse answers.

Cause: same family, same training data, same failure modes. When they agree they
are frequently **both wrong**. Agreement was a shared prior, not independent
evidence. The published result concerned ensembles of *different* models.

**Rule:** an ensemble finding carries an independence precondition. Check it.
And when measuring agreement between raters, use raters from different families
or the number means nothing.

## 7. Agreement needs a ceiling or it is uninterpretable

For tasks with no ground truth (review, critique, judgement), agreement with a
stronger model is the honest measure — but a bare kappa cannot be read. If two
reference models agree with *each other* at kappa 0.40, a subject at 0.35 is as
good as any rater and the task is simply subjective.

**Rule:** always compute reference-vs-reference agreement first and report every
subject score as a fraction of it. Most agreement studies omit this, which is
how "the small model is bad" gets published when the truth is "nobody agrees."

**And keep the claims apart:** high agreement means **substitutable**, never
**correct**. Two models can be confidently wrong together — see lesson 6.

## 8. Pre-register the threshold, or the eval is decoration

Straight from an adversarial LLM review of our own design
(`wikipedia-policy-change/.claude/policy_network_review2_llm.md` §1.2):

> *"Without a pre-registered threshold the eval is decoration — you will run it,
> get some number, and rationalize whichever number you get."*

Fix the pass mark, the baseline, the asymmetric error, and `n` (with its CI)
*before* the first call. Template:
[`feedback/liftwing-bench-npov-prereg.md`](feedback/liftwing-bench-npov-prereg.md).

## 9. Name the asymmetric error and give it its own metric

Aggregate accuracy hides the error that actually costs you. A false merge hides
a policy reform; a false negative in triage silently drops a candidate; a
hallucinated quote enters the corpus as a rule nobody wrote.

**Rule:** each task names its dangerous direction and scores it separately with
its own pass mark. `governance_class` beat every baseline and still **failed**
on `user-admin` recall 0.672 vs a 0.70 gate — the right outcome.

## 10. Do the zero-call analysis first

The ensemble result in lesson 6 was killed by re-analysing output already on
disk — no new calls, a few minutes, before any engineering was spent building
the pipeline it would have justified.

**Rule:** before running anything new, ask what the data you already have can
refute.

## 11. A regression canary confirms the verdict, not the failure mode

A known-failing task was kept in the suite so that a sudden pass would signal a
harness bug. It worked — both models failed it again, independently, which is
what validated the harness.

But the *mechanism* did not reproduce: the earlier run showed zero predictions
of one label, the later run used all three labels with terrible recall on one.
Same conclusion, different pathology, driven by a prompt change.

**Rule:** canary on the verdict. Do not assume the failure mode is stable — it
is prompt-sensitive even when the conclusion is not.
