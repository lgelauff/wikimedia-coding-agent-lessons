---
name: budget-estimate
description: >-
  Estimate wall-clock time AND token spend for a proposed job — a data
  pipeline, an agentic work session, or a hybrid — with P50/P90 bands, stated
  evidence level (measured sample > historical priors > arithmetic), hard
  rate-limit floors, and a fits/doesn't-fit verdict against the available
  window or budget. Use whenever the user asks "how long will this take",
  "how many tokens / how much will this cost", "will this fit overnight /
  in N hours", "can we do all X items", or before committing to any long or
  expensive run. Prefer this over answering with a gut figure — an unbanded
  vibes estimate is how nights and budgets get lost.
---

# budget-estimate — Claude Code adapter

The method lives in the agent-neutral playbook:
[`../../playbooks/budget-estimate.md`](../../playbooks/budget-estimate.md).
Follow its evidence hierarchy, formulas, and output format; this file adds the
Claude Code wiring.

## Evidence sources, in order

1. **Measure a sample.** If the job's script exists, run it with `--limit`
   (10–20 items) via the Bash tool and time it; the shaped-command and
   allowlist rules of the consuming repo apply as usual. For agentic work, run
   ONE representative task (or one subagent fan-out if the job fans out) and
   read its cost.
2. **Historical priors.** Query the run-cost history:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cost_report.py"` (add
   `--predict --flags … --diff-lines …` for pr-check-shaped jobs); check
   `~/.claude/skill-run-cost.jsonl` and `~/.claude/tool-token-log.jsonl`
   directly for other shapes; grep old run logs in the consuming repo
   (`.claude/overnight/*/run.log` timestamps are per-item rate data).
3. **Arithmetic** from documented rate limits / payload sizes — always
   labeled as assumed, per the playbook.

Never present a level-3 number as if it were measured. If the user wants a
fast answer and only level 3 is available, give the number WITH its label and
offer the 10-minute sample run as the upgrade.

## Output

Use the playbook's fixed shape: verdict-first against the window/budget, P50 +
P90 for both time and tokens, evidence level per number, hard floors, breaking
assumptions, and downscope/concurrency/model-tier levers if it doesn't fit.
Small jobs get the same shape in three lines, not a report.

## Calibration duty

If the estimated job then actually runs in this or a later session: compare
actual vs estimate in one line, and append the actuals to the history —
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/record_run.py" --skill <job-slug>
--subagent-tokens <n> --duration-ms <n>` (flags optional for non-PR jobs).
An estimate that never meets its actuals is the top anti-pattern in the
playbook.

## Used by

- **overnight-run** calls this skill during PREP: intake item 6 (budget) and
  the Phase 3 runtime extrapolation are budget-estimate invocations — the
  dress rehearsal IS the level-1 sample; its measured rate feeds the go/no-go
  "fits window with ≥25% margin" line, and the morning report closes the
  calibration loop.
