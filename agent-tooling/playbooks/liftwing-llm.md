# Playbook: LiftWing LLMs — the cheap external model for bulk work

Wikimedia LiftWing serves open-weight models (Qwen3-14B, Qwen3.6-27B) through a **keyless,
OpenAI-compatible** endpoint on `api.wikimedia.org`. It is the cheap external LLM for bulk
classification, extraction, scoring and validation — and the privacy-preferable option when
the input is wiki content.

Replaces the former `liftwing-llm` skill. The knowledge lives here and in
`scripts/llm_provider.py`; there is no skill wrapper, because "which cheap model do I delegate
to" is answered by configuration (`AGENT_LLM_PROVIDER`) rather than by a procedure.

## Never hand-roll the HTTP call

```bash
AGENT_LLM_PROVIDER=liftwing python3 "${AGENT_TOOLING_ROOT}/scripts/llm_provider.py" "your prompt"
```

`llm_provider.py` dispatches on `AGENT_LLM_PROVIDER` across `claude-code | liftwing |
openrouter | mistral`. It handles the endpoint, the default model (`llm-qwen3-14b`) and the
rate budget. Hand-rolling a `curl` re-implements all three, badly.

## Two surfaces, two different limits — do not confuse them

| Surface | Limit |
|---|---|
| LiftWing inference (`/service/lw/inference/…`) | **100 requests/hour anonymous** |
| The wider `api.wikimedia.org` gateway | different, higher — see the API Gateway docs |

Conflating them produces a job that plans against the wrong ceiling.

## The rate limit is the design constraint, not a detail

**100 requests/hour is a hard floor.** It is not a number to route around; it determines the
shape of the job:

- A pass needing more than 100 requests **is an overnight run**, not an afternoon one.
- **Batch items per request.** The cap is on *requests*, not tokens — putting 20 items in one
  prompt costs one request. This is the single largest lever on throughput.
- **Measure the error rate every pass.** A silently truncated batch looks like success.
- Escalation path when the ceiling binds: Toolforge hosting.

Check headroom before launching:

```bash
python3 "${AGENT_TOOLING_ROOT}/scripts/rate_budget.py" --status   # headroom + who used it
```

The budget is **enforced, not remembered** — the script tracks it, so do not rely on knowing
the current count.

## What it cannot do — design around it, don't discover it at 3am

- **No tool calling.**
- **No JSON mode.** Ask for JSON in the prompt and parse defensively; expect prose wrappers
  and occasional truncation.
- Reasoning-heavy work is a poor fit. Use it for mechanical passes.

## What to use it for

- Bulk classification, extraction, scoring, validation.
- Any large mechanical pass where a frontier model would be wasteful.
- **Privacy-preferable default for wiki content** — WMF-hosted, so wiki text stays within
  Wikimedia infrastructure rather than going to a third-party host.

Not for: judgment calls, anything needing tools, anything where a wrong answer is expensive
and hard to detect.

## Choosing it over the alternatives

| Situation | Choice |
|---|---|
| Bulk mechanical pass over wiki content | **LiftWing** |
| Bulk mechanical pass over non-wiki content | LiftWing is acceptable, not necessarily best |
| Needs tools, JSON mode, or real reasoning | A frontier model |
| Local-only, no data may leave the machine | Ollama (see `write-in-my-voice`'s design) |

## Log what you learn

Per-provider feedback goes in `agent-tooling/feedback/<provider>.md`. LiftWing's quirks are
worth recording — a batch that fails silently at item 17 is exactly the kind of thing that
costs an hour twice.

## Before a user study

Ask. Any LLM involved in a study is a methodology decision, not an implementation detail.
