# Playbook: estimating a job's time and token budget

Hand this to an LLM and it should produce a **defensible estimate of wall-clock
time and token spend** for a proposed job — a data pipeline, an agentic work
session, or a hybrid — with uncertainty stated, assumptions listed, and a
plain verdict on whether the job fits the available window/budget. The method
exists because "this should take about an hour" said from vibes is how nights
and budgets get lost.

## The hierarchy of evidence

Use the strongest method available; only fall down the ladder when the level
above is genuinely unavailable. **State which level the estimate came from.**

1. **Measure a sample** (strongest). Run the real job on a small slice
   (`--limit 20`, or one representative task for agentic work) and extrapolate
   from the measured rate. This is the only level that captures the real API
   latency, the real payload sizes, the real context growth.
2. **Historical priors.** Prior runs of the same or a similar job: the
   `record_run.py` log (`~/.claude/skill-run-cost.jsonl`, queried via
   `cost_report.py [--predict]`), old run logs with timestamps, the
   `tool_token_log.py` proxy log. Same-shape history beats fresh guesses.
3. **First-principles arithmetic** (weakest acceptable). items × per-item cost
   from documented figures (API latency, rate limits, payload sizes,
   tokens-per-file-read ≈ bytes/4). Never present this level without saying
   the per-item figure is assumed, not measured.

"I ran nothing and checked no history" is not an estimate; it's a guess, and
must be labeled as one.

## Time estimate (wall-clock)

```
T = startup + (N_items × t_item / concurrency) × retry_overhead
```

- **t_item** from the evidence ladder above.
- **Hard floors dominate:** if a rate limit applies, `N / rate_limit` is a
  lower bound no optimization can beat — compute it first and say so. (1M
  items at 1 req/s is 11.6 days; no estimate discussion needed.)
- **retry_overhead:** multiply by ~1.1–1.3 for network-bound work unless the
  sample already included failures.
- **Startup costs** (auth, cache warm, model load) matter for short jobs,
  vanish for long ones — include them only when T < ~1h.
- Sanity-check against the calendar: rate limits per hour/day, API quota
  resets, the machine's own window (an "8-hour" overnight window is 8 hours,
  not "roughly a night").

## Token estimate (agentic / LLM work)

```
Tok = N_tasks × tok_task × fanout_factor
```

- **tok_task** from a measured sample task or the `record_run` history for the
  matching skill/flags. A task's cost is dominated by context reads + tool
  results, not output — which is why byte-counting inputs (level 3) is a weak
  but usable proxy (bytes/4).
- **fanout_factor:** subagent-heavy work costs mostly *subagent* tokens, which
  only show up when measured from a real run (this is exactly what
  `record_run.py` exists to capture). If the job fans out and there is no
  history, run one fan-out as the sample — level 3 badly underestimates here.
- **Context growth:** long single-context sessions get more expensive per task
  as they age; assume the last task costs ~1.5–2× the first unless work is
  delegated to fresh subagents.
- Convert to money only when asked, and name the rate used.

## Output format (always the same shape)

1. **Verdict first:** fits / doesn't fit / fits-only-if, against the stated
   window and budget, with margin. ("~6.5h P50, ~9h P90 against a 9h window —
   fits at P50, no margin at P90.")
2. **The numbers:** P50 and P90 for time and tokens. P90 ≈ P50 × 1.5 is an
   honest default when the sample is small; tighten only with real variance
   data.
3. **Evidence level** (1/2/3) per number, and the measured/assumed per-item
   figures.
4. **Hard floors** (rate limits, quotas) stated separately — these are facts,
   not estimates.
5. **Assumptions** that would change the answer if wrong (payload size, item
   count, failure rate).
6. **Levers** if it doesn't fit: downscope options (sample, priority subset),
   concurrency, a cheaper model tier for subagents, splitting across nights.

## Calibrate afterwards — the estimate isn't done until the run is

After the job runs, compare actual vs estimate and append the real numbers to
the history (`record_run.py --skill <job> --subagent-tokens … --duration-ms …`
or the project's own log). One line in the run report: `estimated X / actual Y
(±Z%)`. Off by >2×? Write down which assumption broke — that's the next
estimate's level-2 prior. Uncalibrated estimation stays vibes with extra steps.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| Point estimate, no band ("about 3 hours") | Hides that P90 blows the window |
| Extrapolating from item 1 | First items hit warm caches and no failures |
| Ignoring the rate-limit floor | Optimism cannot beat arithmetic |
| Estimating fan-out token cost from the orchestrator's view | Subagent tokens are the cost, and they're invisible until measured |
| Estimate delivered, never compared to actuals | The error repeats forever |
