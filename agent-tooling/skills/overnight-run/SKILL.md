---
name: overnight-run
description: >-
  Prepare, rehearse, launch, and report an unattended 8–10 hour overnight run
  (long Python data pipeline or agentic task list) so it survives the night
  with zero permission prompts, zero mid-run questions, and tested
  crash-recovery. Three modes: PREP (hours before bed — one batch of intake
  questions, harden the script, anticipate every permission, dress rehearsal +
  kill-and-resume drill, go/no-go runbook), LAUNCH (bedtime — five-minute gate
  check, detached start, watch the first minutes), MORNING (report). Use
  whenever the user says "prepare an overnight run", "run this overnight /
  tonight / while I sleep", "this will take N hours", "get this ready so I can
  start it before bed", or asks why last night's run died. Prefer this over
  just launching a long script in the background — an unrehearsed launch is
  how runs die 20 minutes in.
---

# overnight-run — Claude Code adapter

The method lives in the agent-neutral playbook:
[`../../playbooks/overnight-run.md`](../../playbooks/overnight-run.md). Read it
first and follow its phases; this file adds only the Claude Code wiring.

**The one law (from the playbook): the overnight run must never need a human.**
Every question is answered during PREP, every permission granted or designed
away during PREP, every failure response pre-decided. If at any point overnight
you are about to ask the user something — that is a prep bug; park it in
QUESTIONS.md and continue.

## Mode selection

- "prepare an overnight run for X", hours before bed → **PREP**
- "run it" / "start the overnight run" (runbook exists) → **LAUNCH**
- "how did it go" / new morning session after a run → **MORNING**
- No runbook exists and the user says "run it tonight" right before bed →
  say plainly that unrehearsed launches are how nights get lost, then do the
  fastest honest PREP the remaining time allows and report which gate lines
  are unverified. The user decides with eyes open.

## Run directory

Everything for one run lives in the consuming repo at
`.claude/overnight/<YYYY-MM-DD>-<slug>/`:

```
runbook.md      the contract (template: references/runbook-template.md)
run.log         pipeline log (script writes it)
status.md       agentic runs: task-list checkpoint, updated after every task
DECISIONS.md    choices made under standing orders, appended overnight
QUESTIONS.md    parked human-only questions, appended overnight
report.md       the morning report
```

## PREP wiring (playbook Phases 0–4)

- **Intake (Phase 0):** FIRST run the pre-mortem yourself ("it's 7am and the
  night was wasted — why?"): list the 3–6 most plausible failure/doubt
  scenarios for THIS run, decide which are prevented by hardening/rehearsal,
  and turn the rest into concrete scenario questions. THEN use
  `AskUserQuestion` — ONE batch covering goal/acceptance, scope edges, failure
  policy + the pre-mortem scenarios ("if X: push on, downscope, or stop?"),
  priority order, budget, and the doubt threshold (how they price tokens
  wasted on a rejected result vs a night lost — capture it in their own
  words). Offer concrete options; don't dribble follow-ups. Write the runbook
  from `references/runbook-template.md` immediately after, including §5b
  (doubt policy: pre-mortem table + threshold + the probe→downscope→threshold
  ladder for unforeseen doubts).
- **Harden (Phase 1):** apply the playbook checklist to the script. The repo's
  own prior art is the standard to meet (resume support, rate-limit sleeps,
  User-Agent headers are already idiomatic in these projects).
- **Permissions (Phase 2):** command shapes per `claude-code/lessons.md` in
  this repo (no `cd`+redirect, no inline `python3 -c`, no per-URL `curl`,
  absolute paths). Add L3 entries to the consuming repo's
  `.claude/settings.local.json` — exact invocations or script paths only,
  never `Bash(python:*)`-class arbitrary exec. **Show the proposed settings
  diff and get an explicit yes before writing it** (permission-framework
  rule). Then verify empirically: the rehearsal must produce zero prompts.
- **Rehearse (Phase 3):** run the real command with `--limit`; then
  `kill -9` the process mid-run and relaunch to prove resume. Verify outputs
  by opening them, not by `ls`. The rehearsal's measured rate feeds the
  **budget-estimate** skill (sibling in this plugin): produce the P50/P90
  time (and, for agentic runs, token) estimate per its playbook; the gate's
  "fits with ≥25% margin" line judges the P90, and MORNING closes the loop by
  logging estimate-vs-actual to the run-cost history.
- **Gate (Phase 4):** fill the runbook's go/no-go checklist with `Verified
  by:` lines. Report READY or NOT-READY honestly; an unchecked line is NO-GO.

## LAUNCH wiring (playbook Phase 5)

- Re-verify stale-able gate lines (credentials, disk, new commits).
- Launch the verbatim runbook command with the Bash tool,
  `run_in_background: true`, wrapped in sleep prevention:
  `caffeinate -i nohup <command> > <run-dir>/run.log 2>&1`
  — `caffeinate -i` blocks idle sleep; `nohup` + file logging make the run
  survive this session dying. Background-task notification fires on exit
  either way.
- **Watch the first ~10 minutes / first items** via the script's `--status`
  subcommand and the log; confirm the observed rate matches the rehearsal
  extrapolation and a checkpoint has been durably written.
- Then say goodnight in one message: what runs, log path, ETA, what the
  morning report will contain.
- If the session stays open overnight to babysit: rely on the background-task
  completion notification; add at most a sparse periodic check (the script's
  own resilience is the real safety net, not the babysitter). On a mid-night
  failure notification: apply the runbook's failure policy — restart/resume is
  fine if standing orders cover it; otherwise log to QUESTIONS.md and stop
  cleanly. Never wait on a user reply.

## Agentic-run wiring

When the overnight work is Claude working a task list rather than one script:

- The runbook's task list carries per-task acceptance criteria, time boxes,
  and priority order; work strictly in that order.
- After EVERY task, update `status.md` (done / result / next). A compacted or
  crashed session resumes from `status.md`, never from memory.
- Decisions: standing orders first. Reversible-and-cheap: choose, append to
  `DECISIONS.md`, continue. Irreversible or user-reserved judgment calls:
  append to `QUESTIONS.md`, skip that task, take the next. A work stream you
  genuinely doubt (rising odds the user rejects the result): the runbook §5b
  ladder — spend a small bounded probe to get evidence, prefer downscoping
  (sample / snapshot-and-branch / park and take next priority) over both
  full-burn and full-stop, and apply the user's pre-agreed rejection-odds
  threshold. Reversible is not free — tokens spent on a binned result are the
  other way to waste the night.
- **No outward-facing actions overnight** — nothing sent, posted, or pushed to
  shared branches. Produce drafts; morning approval sends them.
- Delegate heavy reading/searching to subagents to protect the long session's
  context; keep the orchestrating context small.
- Use the project's configured model tier for subagents (per-project rule; if
  none is defined, that's a PREP intake question, not a 2am decision).

## MORNING wiring (playbook Phase 6)

Write `report.md` in the run directory in the playbook's format — verdict
first, everything verified with `Verified by:` lines, failures categorized,
DECISIONS and QUESTIONS surfaced, retry command ready. Present the verdict and
the parked questions in chat; the file holds the detail.
