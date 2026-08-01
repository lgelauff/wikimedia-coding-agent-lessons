---
name: liftwing-llm
description: >-
  Call Wikimedia LiftWing's open-weight LLMs (Qwen3-14B / Qwen3.6-27B) through
  the keyless OpenAI-compatible endpoint on api.wikimedia.org — as the cheap
  external LLM for bulk classification, extraction, scoring, or validation, and
  as the privacy-preferable option when the input is wiki content. Use when the
  user mentions LiftWing, asks which LLM to delegate bulk work to, wants a free
  or WMF-hosted model, or is about to spend Claude tokens on a large mechanical
  LLM pass. Covers the 100 req/hour anonymous ceiling (a hard floor that makes
  bulk jobs overnight runs), the Toolforge escalation path, missing tool-calling
  and JSON mode, and the per-provider feedback log.
---

# liftwing-llm — Claude Code adapter

Wikimedia LiftWing hosts open-weight chat models for use in Wikimedia projects
and tools. Source: [Wikitech — LiftWing LLMs, Wikimania 2026](https://wikitech.wikimedia.org/wiki/Machine_Learning/LiftWing/Large_Language_Models/Wikimania_2026)
(that page is a **draft**; re-read it before trusting an endpoint that fails).
**Last verified against the live endpoint: 2026-08-01** — one real call to
`llm-qwen3-14b` returned a correct answer through `llm_provider.py`.

## Never hand-roll the HTTP call

Go through the repo's provider abstraction, which already implements the
keyless request, the `User-Agent`, the `<think>…</think>` stripping and the
bounded retry:

```bash
AGENT_LLM_PROVIDER=liftwing python3 "${CLAUDE_PLUGIN_ROOT}/scripts/llm_provider.py" "your prompt"
```

From Python: `from llm_provider import query_llm` with `AGENT_LLM_PROVIDER=liftwing`
in the environment. `AGENT_LLM_MODEL` overrides the model.

| Model | Context | Use |
|---|---|---|
| `llm-qwen3-14b` (default) | 16K | general chat; the default |
| `llm-qwen36-27b` | 32K | largest available; longer inputs |

## Two LiftWing surfaces — don't confuse their limits

LiftWing serves **two unrelated things** through the same host:

| Surface | Endpoint | Anon rate limit |
|---|---|---|
| **LLM chat** (this skill) | `…/models/llm-<model>/openai/v1/chat/completions` | **100 req/hour** |
| **Classic ML predictions** (revertrisk, articlequality, readability, topic, langid…) | `…/models/<model>:predict` | ~50,000 req/hour |

The 500× difference is GPU inference vs cheap predictive models — so a batch
size that is trivial for `revertrisk-language-agnostic` is a multi-day job on
the chat models. For the `:predict` surface, prefer the prior art in
[fuzheado/Wikipedia-AI-Skills](https://github.com/fuzheado/Wikipedia-AI-Skills)
(`wikimedia-ml-services`), which documents the model list, schemas, and batch
scripts; it does **not** cover the LLM endpoint (checked 2026-08-01).

**Unverified [guess]:** the Wikimania page says only "no API key required" and
points to Toolforge for more headroom, while the general API gateway raises
limits for OAuth-authenticated and known clients. Whether an OAuth bearer token
also lifts the LLM's 100/h cap is **untested** — measure before relying on it,
and log the answer in the feedback file.

## The rate budget is enforced, not remembered

Concurrent sessions are separate OS processes that cannot see each other's API
usage, so the 100/h ceiling is **enforced at the chokepoint**: every LiftWing
call through `llm_provider` first takes a token from a file-backed bucket
(`scripts/rate_budget.py`), guarded by an `flock` so two sessions can never
take the same token.

| Knob | Default | Why |
|---|---|---|
| refill | 1 token / 40 s (= 90/h) | headroom under the documented 100/h |
| burst | 8 tokens | small bursts when quota is idle; no session can hoard the hour |
| hourly backstop | 95 calls/60 min | matches the documented number; catches clock jumps or bucket-math bugs |

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rate_budget.py" --status   # headroom + who used it
```

- **Fail-fast by default** — an exhausted budget raises with the seconds until
  the next token, rather than sleeping (a silently sleeping agent looks hung).
- **`AGENT_RATE_WAIT=1` paces instead** — for scripted and overnight callers,
  which should be throttled, not aborted.
- **`AGENT_RATE_DISABLE=1`** turns the budget off — for running *from
  Toolforge*, where the cap doesn't apply. Never set it to "get more calls".
- **429 is expected, not exceptional:** `Retry-After` is honoured, the event is
  recorded in the ledger, and the generic retry does not hammer the wall.
- **Attribution:** `~/.claude/liftwing-usage.jsonl` holds one line per call
  (session, project, pid, model, outcome) — that ledger is the answer to
  "which sessions are using this API", and the evidence for tuning the knobs.
- **Budget before you batch.** `--status` is the pre-flight check for any
  multi-call pass; a study that needs 40 triage calls should see that number
  against the hour's headroom *before* starting, not at call 9.

## The rate limit is the design constraint

**100 requests/hour anonymously — a hard floor, not a soft limit.** Before
proposing LiftWing for a batch, do the arithmetic first (per
[`budget-estimate`](../budget-estimate/SKILL.md)): `N / 100` hours, minimum, no
concurrency escape. 500 items = 5 h; 1,000 = 10 h. That means:

- **Small/interactive work** (tens of calls): use it directly, now.
- **Bulk work**: it is an overnight job by arithmetic — hand it to
  [`overnight-run`](../overnight-run/SKILL.md) as a detached, checkpointing,
  resumable stage, or
- **escalate to Toolforge**, where the cap lifts to effectively unlimited. That
  is a **user-action request, not an agent action**: SSH is human-only in this
  repo (`block_ssh` hook). Prepare the tool-account job (Jobs framework — the
  bastion is for quick interactive calls only, never sustained work), then hand
  the user the exact commands, per the morning-integration external-compute
  pattern. Set `AGENT_RATE_DISABLE=1` there — the local bucket exists to
  protect a cap that no longer applies.

  ⚠️ **Toolforge is for PUBLIC wiki data only.** Research corpora with human
  participants — deliberation transcripts, survey responses, conversation
  comments — do not go to a shared WMF tool account to dodge a rate limit.
  Those stay local under the 100/h budget (batched per request, run overnight),
  which is a constraint on throughput, not a reason to relocate the data.

## What to use it for

**The decision rule:** if a wrong answer is caught cheaply by the next step,
LiftWing; if a wrong answer silently propagates into a conclusion, Claude.
LiftWing produces **inputs** to your reasoning, never the reasoning itself.

Because it cannot browse or retrieve, it knows nothing you don't paste — your
pipeline retrieves, the model only judges what it's handed. That is the
cite-don't-compute rule with a different hat on.

**Good fits** — mechanical judgments over text you already hold, with a small
output space (a label, a score, a yes/no, a code, a short list):

| Task | Why it fits |
|---|---|
| Relevance triage of search hits ("bears on question N? y/n + one line") | tiny output space, wrong answers caught on review |
| Term-scanning long texts, chunked ("does this passage discuss X?") | the input is past 32K anyway and must be chunked |
| Vocabulary / synonym / spelling-variant generation | verified by whether the searches then work |
| Language ID, gist translation of a passage | genuinely multilingual training |
| Field extraction into CSL-JSON | cheap to validate mechanically |
| Candidate dedup ("same work?") | binary, checkable |
| Fixed-form chunk summaries | output is an input to a later human read |

**Poor fits:** anything needing current facts (no browsing → confident
confabulation); multi-step work (no tool calling); scanned PDFs (no multimodal
— OCR'd *text* is fine, page images are not); and final synthesis, framing, or
quality verdicts — both the weak spot of a 14B/27B open model and the work you
shouldn't be outsourcing.

**Don't use an LLM where a purpose-built classifier exists.** For revert risk,
article quality, readability, or topic classification, LiftWing's `:predict`
models are better *and* ~500× less rate-limited. The LLM is for judgments no
existing model covers.

### Batch items per request — the cap is on REQUESTS, not tokens

This is the single biggest lever and it inverts the naive design. With 16–32K
of context and only ~90 requests/hour, **never send one item per call**:

- Send 10–20 numbered items in one prompt; ask for one labelled line each.
  A 300-item triage goes from ~3 hours to ~20 calls — inside a single hour.
- **Number the items and require the number back**, so a misaligned or short
  answer is detectable rather than silently shifting every label by one.
- Keep batches modest: a failed batch loses all its items at once, and long
  outputs risk truncation.
- Budget the validation retries too — a re-ask costs a request from the same
  bucket as the original.

### Measure the error rate, every pass

A bulk pass that reports no error rate has traded token cost for unmeasured
quality risk. Spot-check a sample (n≈10–20), record correct/incorrect and the
parse-failure count, and put both in the feedback log. That number is what
tells you whether the next pass of this shape can skip review.

## What it cannot do (design around, don't discover at 3am)

- **No tool/function calling and no JSON mode.** Structured output must be
  prompted for AND validated by the caller — parse defensively, count
  failures, and treat a parse-failure rate as a first-class metric.
- **No web search, no RAG, no image input.** Retrieval is your pipeline's job.
- **Reasoning preamble:** responses may open with `<think>…</think>`;
  `llm_provider` strips a leading block, but if you stream or call the endpoint
  from other code, reuse `llm_provider.strip_reasoning`.
- **Shared service** — latency varies with load; first token can be slow. Set
  generous timeouts, never a tight one that turns load into a fake error.

## Choosing it over the alternatives

Prefer LiftWing when the work is **bulk and mechanical** (classification,
extraction, scoring, first-pass validation) — the global rule already says
delegate those off Claude — and especially when the input is **wiki content**,
since it keeps that content on Wikimedia infrastructure instead of a
third-party commercial API. Keep Claude (`claude-code`) for judgment-shaped
work: synthesis, code, review, anything where the output is the deliverable
rather than an input to one.

Not a confidentiality boundary: it is a shared, draft service with no stated
guarantee. The standing rule holds — **no participant names, no private data,
no secrets** in any prompt, regardless of provider.

## Log what you learn — per-provider feedback

Every non-trivial use gets one entry in the provider's feedback log
(`agent-tooling/feedback/<provider>.md`, gitignored, template in that
directory's `README.md`): the task shape, model, N calls, observed
throughput/latency, output-quality verdict, parse-failure rate, and whether
you'd use it again for that shape. These logs are how "which provider for
which task" becomes evidence instead of vibes, and they feed
`budget-estimate`'s level-2 priors.

## Ask before a user study

At the **start of each user study** in a research playground, ask the user
which provider that study should run on (LiftWing / Claude / other) rather than
assuming a default — the choice affects reproducibility, cost, and what may be
reported about the study's tooling. Record the answer in the study's own notes
and, at the end, in the provider feedback log.
