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
  pattern.

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
