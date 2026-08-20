# LiftWing LLM benchmark suite — design (Toolforge)

A multi-task suite for the LiftWing **LLMs** (`llm-qwen3-14b` 16K, `llm-qwen36-27b`
32K), sized to run from **Toolforge**, where the 100 req/h anonymous cap lifts.

Status: **designed, not built.** Harness to extend:
[`../scripts/bench_statement_align.py`](../scripts/bench_statement_align.py).
Prior result and method precedent: [`../feedback/liftwing.md`](../feedback/liftwing.md),
[`../feedback/liftwing-bench-npov-prereg.md`](../feedback/liftwing-bench-npov-prereg.md).

---

## 1. What Toolforge changes — and what it does not

| constraint | anonymous | Toolforge |
|---|---|---|
| requests/hour | **100 (hard)** | lifted |
| context window | 16K / 32K | **unchanged** |
| wall-clock per call | ~1–5s server | **unchanged** |
| gold-set size | 340 statements | **unchanged** |

Only one of four constraints lifts. So the suite's job is **not** "run more
calls" — it is to answer the two questions that requests-per-hour was hiding:

1. **Where does quality break as input grows?** (context rot — §4)
2. **What request shape is most efficient per unit of work?** (batching — §5)

Gold-set size is now the binding limit on statistical power, not rate. Say so in
every result.

---

## 2. Method discipline — inherited, non-negotiable

From `wikipedia-policy-change/.claude/policy_network_review2_llm.md` §1.2:
*"Without a pre-registered threshold the eval is decoration — you will run it,
get some number, and rationalize whichever number you get."*

Every task below ships a pre-registration before its first call, containing:

1. **A non-LLM baseline to beat** — majority class, embedding score, regex, or
   the relevant LiftWing *classifier*. Tune it generously (oracle-tuned on the
   test set); a weak baseline flatters the model and teaches you nothing.
2. **A pass mark and a verdict rule**, fixed in advance.
3. **The asymmetric error named**, with its own metric.
4. **n and the resulting CI**, stated up front.

### Two hard lessons already paid for

- **Report macro-F1 *and* accuracy, always.** The alignment run scored 37.9%
  accuracy while **never once emitting one of its three labels**. Accuracy alone
  hid a model that had collapsed onto a catch-all. Macro-F1 penalises exactly
  that. The *gap* between the two is the frequency-bias diagnostic.
- **Stress-test the catch-all class before running.** Defining `p` as "related
  or overlapping" made it a safe default and the model chose it 21/29 times.
  For every label set, ask: is there a class a lazy model can always pick?

### Class imbalance in our gold

Rare classes cannot be scored. Report macro-F1 over classes with **n ≥ 10**, and
list excluded classes explicitly rather than silently folding them in.

| field | classes | distribution (n=340) |
|---|---|---|
| `deontic_type` | 9 | obligation 122, prohibition 51, permission 47, condition 25, principle 23, definition 17, procedure 10, *scope 4, eligibility 3* |
| `governance_class` | 3 | content 203, user-user 71, user-admin 28 |
| `segment_type` | 6 | rule 219, procedure 50, summary 13, *meta 7, principle 7, definition 6* |

---

## 3. The token-tier axis

Five tiers spanning three orders of magnitude of input. Each task below is
tagged with its tier. Both models run every tier that fits their window.

| tier | input | output | shape | fits |
|---|---|---|---|---|
| **T1 micro** | ~150–250 tok | 1–5 tok | one statement, one label | both |
| **T2 small** | ~400–1.5K | 50–250 tok | one statement → structured record | both |
| **T3 medium** | ~2–6K | 0.5–2K | one section → many statements | both |
| **T4 large** | ~8–15K | 1–3K | whole page → statements + exclusions | both (14B near limit) |
| **T5 xl** | ~18–30K | 1–3K | two pages (cross-wiki or cross-year) | **27B only** |

Real page sizes, measured: `de_dritte_meinung` 4.5K tok · `de_npov` 3.9K ·
`en_rfc` 7.5K · `en_npov` 8.9K. So T4 = one page, T5 = a page pair.

**T5 is the tier that matters most for the project** — cross-wiki comparison
(#7) and cross-year drift both need two documents in context at once, and that
is precisely where context rot is documented to bite.

---

## 4. Cross-cutting probe A — context rot and position

Published finding to replicate on our data: accuracy follows a **U-shape** by
position, dropping 20–30 points in the middle, and ten of twelve models fall
**below half their short-context score by 32K**.

**Design.** Take a statement with a known gold label. Ask the same question
three ways:

- **P0 isolated** (T1): the statement alone. This is the ceiling.
- **P1 embedded** (T4): the statement inside its full source page; ask for the
  label of the statement at a given position.
- **P2 padded** (T5): the same, with a second unrelated policy page concatenated
  before or after, placing the target at relative position **0.1 / 0.5 / 0.9**.

**Metric:** accuracy by (tier × position). **Report the drop from P0**, not the
absolute number — the absolute is confounded by task difficulty.

**Why it decides something:** if P1/P2 collapse, the pipeline must chunk to
statement level before the LLM ever sees text, and the "give it the whole page"
design in `atomic_statements_design.md` is not viable on these models.

---

## 5. Cross-cutting probe B — batching efficiency (the low/high-token question)

The same work, three request shapes. **Total items held constant at 100
statements**; only the packing changes.

| shape | requests | tokens/request | total input tokens |
|---|---|---|---|
| **B1 one-per-call** | 100 | ~200 | ~20K |
| **B2 batch-10** | 10 | ~600 | ~6K |
| **B3 batch-50** | 2 | ~2.2K | ~4.4K |
| **B4 batch-100** | 1 | ~4K | ~4K |

Batching amortises the instruction preamble, so **B4 uses ~5× fewer input
tokens than B1 for identical work**. The question is what it costs in quality.

**Measure per shape:** macro-F1 · wall-clock for all 100 · total tokens ·
**alignment failures** (output row count ≠ input row count, or rows returned
out of order — a failure mode that does not exist at batch size 1) · position
effect *within* the batch (are items late in the list labelled worse?).

**Verdict rule:** adopt the largest batch whose macro-F1 is within 1 SE of B1
**and** whose alignment-failure rate is 0. Alignment failures are
disqualifying at any quality level — a silently misaligned batch corrupts
labels without any error signal.

This is the single most decision-relevant experiment in the suite: it sets the
request shape for every bulk job that follows.

---

## 6. Task catalogue

### 6.1 Classification — `deontic_type` · T1 · n=316

Given one statement, assign obligation / prohibition / permission / condition /
principle / definition / procedure. (Excludes scope n=4, eligibility n=3.)

- **Gold:** `runs/*.statements.csv`, `nlwiki_*/04_statements.csv`
- **Primary:** macro-F1 over the 7 scorable classes · **Secondary:** accuracy,
  per-class recall, confusion matrix
- **Baselines:** majority (obligation ≈ 38%) · keyword regex on modals
  (must/should/may · muss/soll/darf · moet/mag) — a genuinely strong baseline
  for deontic typing and the one to beat
- **Catch-all risk:** `principle` and `definition` are semantically loose. Check
  the confusion matrix for collapse onto them.
- **Pass:** macro-F1 ≥ regex baseline + 0.10

### 6.2 Categorization — `governance_class` · T1 · n=302

content / user-user / user-admin: who the norm governs.

- **Primary:** macro-F1 (imbalance is 203/71/28 — accuracy is useless here)
- **Baseline:** majority (content ≈ 67%) — note a 67%-accuracy model can have
  macro-F1 ≈ 0.27. Exactly the trap §2 warns about.
- **Asymmetric error:** missing `user-admin` erases the admin-machinery
  distinction that the en-RfC vs de-Dritte-Meinung finding rests on. Report
  **user-admin recall** separately with its own pass mark (≥ 0.70).

### 6.3 Categorization — `segment_type` + `prominence` · T2/T3 · n=302

rule / procedure / summary / meta / principle / definition, plus
central·supporting·context.

- Two-label output → first **multi-field JSON** test. Score **schema-validity**
  and **value-accuracy separately** (per the Structured Output Benchmark, which
  found near-perfect compliance alongside only 83% value accuracy).
- **Run at T2 (statement alone) and T3 (statement in its section)** — the
  design's open question is whether prominence is a property of the segment or
  the statement. This measures whether context actually helps.

### 6.4 Text extraction — page → atomic statements · T3/T4 · n=6 pages

The #4 task, and the expensive one.

- **Gold:** 4 scripted pages (36/66/113/91) + 2 hand-authored nlwiki (12/26)
- **Metrics — three, kept separate:**
  - **Schema-validity**: fraction of outputs that parse and conform
  - **Recall vs gold**: gold statements recovered (semantic match, τ pre-registered)
  - **Precision**: emitted statements that are real norms, not restatement or
    invention — **hallucinated-norm rate is the headline number**
- **Baseline:** sentence-splitter + modal-verb filter. If the LLM does not beat
  a sentence splitter on recall, the extraction tier is not earning its place.
- **Asymmetric error:** a hallucinated norm enters the corpus as a rule nobody
  wrote. Precision gates adoption; recall does not.
- **Also score completeness routing** (`04_exclusions.csv`): did it log what it
  declined to extract? The design's completeness invariant is *nothing dropped
  un-logged*.

### 6.5 Summarization — statement rendering · T2 · n=340

`source_quote` → canonical one-sentence `statement_en` (median 107 chars).

**Do not use ROUGE.** It collapses hallucination, omission, and paraphrase-
blindness into one number, and our gold renderings are deliberate paraphrases —
a faithful output can share almost no n-grams with the gold.

- **Faithfulness**: does the rendering assert anything not in `source_quote`?
- **Coverage**: does it drop a condition, threshold, or scope qualifier present
  in the gold? (Losing "at least two weeks" or "non-vandalism" changes the rule.)
- Score both as binary per item → report two rates, never averaged together.
- **Baseline:** the `source_quote` verbatim. It is perfectly faithful and scores
  0 on normalisation — the model must beat it on *canonicalisation* while not
  losing on faithfulness.

### 6.6 Translation / cross-lingual rendering · T2 · n=140

`statement_orig` (de/nl) → `statement_en`, against gold pairs.

- Same faithfulness + coverage metrics as 6.5, plus **terminology consistency**:
  is the same source term rendered the same way across items? (Inconsistent
  rendering breaks downstream exact-match attribution.)
- **This is the honest test of LiftWing open question #4** — the alignment run
  was *not*, because its source statements were already pre-translated.

### 6.7 Triage / relevance screening · T1/T2

Binary or 3-way inclusion screening.

- **Gold:** `wikimedia-analysis/AI effects/v2/archive/triage_*.json`
- **Primary:** macro-F1 · **Asymmetric error:** a false negative silently drops
  a real candidate and is unrecoverable downstream — report **recall on the
  include class** with its own pass mark.
- Best-fit task for a cheap model: high volume, tolerant of false positives if a
  stronger model reviews the shortlist. If LiftWing passes nowhere else, it may
  still pass here — and that is a genuinely useful result.

### 6.8 Negative control — statement alignment · T1 · n=29

**Already run, already failed** (macro-F1 collapse, zero `n` predictions,
merge-precision 48.3%). Keep it in the suite unchanged as a **regression
canary**: any harness change or model update that suddenly "passes" this task
is a bug in the harness until proven otherwise.

---

## 7. What the suite costs

| tier | tasks | calls (B1 shape) | est. tokens in |
|---|---|---|---|
| T1 | 6.1, 6.2, 6.7, 6.8 | ~950 | ~200K |
| T2 | 6.3, 6.5, 6.6 | ~780 | ~600K |
| T3/T4 | 6.4, 6.3-context | ~40 | ~350K |
| T5 | probe A padded | ~60 | ~1.4M |
| probe B | batching sweep | ~113 | ~35K |

≈ **1,950 calls, ~2.6M input tokens**, both models. Free.

**[confirmed 2026-08-14, 20-call live smoke test] Server latency is ~0.34s
median, 0.79s max — not the 2–4s assumed above.** The 39.9s median recorded in
the earlier alignment run was *entirely* the local rate bucket, not the model.

So **the rate limiter is the binding constraint, not the server**:

| rate | wall-clock for ~1,950 calls |
|---|---|
| 1 req/s | ~33 min |
| 2 req/s | ~16 min |
| server-bound (no limiter) | ~11 min |

This is **not an overnight run** — it is a coffee break. The `overnight-run`
pairing is unnecessary. Ramping 1→2 req/s costs ~17 minutes against going
straight to 2, which is a cheap price for probing the 429 boundary politely.

---

## 8. Toolforge runbook — one upload, one command

The suite is built and live-tested. `scripts/bundle_liftwing_suite.py` packs
`scripts/liftwing_suite.py` plus all gold data into **one 125 KB stdlib-only
file**. No repo checkout, no pip install, no second upload. The bundler
self-tests the result with `HOME` unset before writing, so a bundle that builds
is provably standalone.

```bash
# 1. build locally (already done; rebuild after any edit to liftwing_suite.py)
python3 ~/Documents/GitHub/wikimedia-coding-agent-lessons/agent-tooling/scripts/bundle_liftwing_suite.py

# 2. upload once. Absolute path — runnable from any directory, and NOT relative
#    to whichever repo you happen to be standing in. No <user>@ placeholder:
#    Toolforge login resolves through your ~/.ssh/config alias.
scp ~/Documents/GitHub/wikimedia-coding-agent-lessons/agent-tooling/scripts/liftwing_suite_standalone.py login.toolforge.org:~/

#    then, once logged in, confirm the upload is intact:
#      sha256sum liftwing_suite_standalone.py | cut -c1-16    -> 6c0e5dca63bae777

# 3. on Toolforge — verify before committing to the full run (~20 calls, ~30s)
python3 liftwing_suite_standalone.py --smoke --skip-probes \
        --out smoke.jsonl --report smoke.txt

# 4. full suite: starts at 1 req/s, ramps to 2/s after 60 clean calls
python3 liftwing_suite_standalone.py --out results.jsonl --report report.txt

# interrupted? nothing is lost
python3 liftwing_suite_standalone.py --resume --out results.jsonl
# re-score without re-calling
python3 liftwing_suite_standalone.py --score-only --out results.jsonl
```

Run it under the Jobs framework (`toolforge jobs run`) rather than a login
shell if you want it to survive disconnect — though at ~16–33 minutes a
`tmux`/`screen` session is enough.

Rate flags: `--rate 1.0 --rate-target 2.0 --ramp-after 60`. The ramp doubles
only after 60 consecutive successes and **halves on any 429, logging the body**
— which is how open question #1 finally gets an answer.

### Notes

- SSH is **human-only** here — running on Toolforge is a **user action**. The
  deliverable is a self-contained runner plus a runbook, never an agent-launched
  job.
- `wikipedia-policy-change/docs/TOOLFORGE_SETUP.md` has the account/Jobs setup.
- Set `AGENT_RATE_DISABLE=1` on Toolforge (the local bucket is the anonymous-cap
  guard and would otherwise pace calls to 40s apart — it was the entire reason
  the last run's median latency read 39.9s).
- **Capture the 429 boundary.** LiftWing open question #1 is still open because
  the local bucket always bound first. On Toolforge, log status codes and bodies
  so the real limit and its error shape finally get recorded.
- Log per call: latency, prompt/completion tokens, `<think>` presence (open
  question #3 — the stripper has **never** met a real reasoning preamble in 29
  calls), and any non-200.

---

## 9. Read this before interpreting any result

- **Gold-set size, not rate, is now the limit.** n=302 gives roughly ±5–6 points
  on a macro-F1; n=29 gave ±18. Do not compare two models on a task with n<100.
- **A task the LiftWing *classifiers* already solve does not belong here.**
  `LW-64` topic vectors matched a 512-dim Jina embedding with no gain from
  combining them (`wikipedia-drop-2026/analysis/labeler-selection/decision.md`,
  M7 ≈ 0.565). If a purpose-built classifier exists, use it and skip the LLM.
- **One real quality datapoint exists so far and it is negative.** Design each
  task expecting failure and make sure the result will be *informative* when it
  fails — that is what the per-class recalls and asymmetric-error metrics are
  for.
