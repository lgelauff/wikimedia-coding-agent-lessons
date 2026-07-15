# Playbook: preparing an unattended overnight run

Hand this to an LLM (or a careful human) and it should know how to take a task of
the form "run this for 8–10 hours tonight" and make it **actually survive the
night**: no permission prompts 20 minutes in, no unhandled error at hour one, no
"we didn't test it well enough" discovered at breakfast.

The method assumes the split the user actually works with:

- **Prep happens hours before bed** (afternoon/evening) — this is where ALL
  thinking, question-answering, hardening, and rehearsing happens.
- **Launch happens just before bed** — a five-minute go/no-go check and a start
  command, nothing more.
- **Overnight, nobody is watching.** Any question the run would need to ask is a
  prep failure, not a runtime event.

Two run shapes are covered; most real runs are the hybrid:

- **Pipeline run** — a long-running script (usually Python) does the work; the
  agent launches, monitors, and reports.
- **Agentic run** — the agent itself works through a task list for hours
  (analysis, writing, multi-step work).

---

## The one law

> **The overnight run must never need a human.**
> Every question answerable in advance gets answered in advance (Phase 0).
> Every permission gets granted or designed away in advance (Phase 2).
> Every failure mode gets a pre-decided response (Phase 0 + 1).
> Anything that still needs a human gets **parked for morning**, never asked at 3am.

Everything below is machinery for enforcing this law.

## Phase 0 — Intake: answer tomorrow's questions today

Interrogate the task **once**, in **one batch of questions** (never dribbled).
The output is the **runbook** (see the template in
`skills/overnight-run/references/runbook-template.md`) — the single document the
overnight session obeys. The batch must cover:

1. **Goal + acceptance** — what does a successful morning look like? What
   partial result is still worth having? (An 8-hour run that dies at hour 6
   with checkpoints is a 75% success, not a failure — if outputs are usable.)
2. **Scope edges** — what must NOT be touched: repos, files, APIs, spend caps,
   rate limits.
3. **Failure policy** — per-item errors: skip-and-log or abort? After how many
   consecutive failures is the run clearly broken and better stopped? (Default:
   skip-and-log items, abort after N consecutive failures — a dead API at 1am
   shouldn't burn 6 hours of retries.)
4. **Priority order** — if time runs out, what must be done first? Order the
   work so value is front-loaded.
5. **Standing orders / decision table** — every judgment call you can foresee,
   pre-decided: "if X happens, do Y." Plus the general rules for the
   unforeseen: *irreversible choices are parked in QUESTIONS for morning;
   reversible-and-cheap choices are made, logged in DECISIONS, and the run
   continues; reversible-but-expensive doubts go through the doubt policy
   (below) — never straight to a full-burn continuation.*
6. **Budget** — API quota, token budget, spend ceiling, disk space. Ground
   the numbers with the budget-estimate method
   ([`budget-estimate.md`](budget-estimate.md)): historical priors at intake
   time, upgraded to a measured level-1 estimate by the Phase 3 rehearsal.
7. **Continue-vs-stop economics** — the pre-agreed answer to "the run has
   developed doubts; is burning the remaining tokens worse than wasting the
   night?" See "The doubt policy" below; the intake batch must pin down the
   user's threshold, because the two failure costs (tokens spent on a rejected
   result vs a machine idle till morning) are theirs to weigh, not the run's.

**0b. Pre-mortem — make the predictable concerns boring.** Before asking the
intake batch, imagine it is 7am and the night was wasted, and list the 3–6 most
plausible reasons *for this specific run* (the API's schema changed; the data
is 90% empty; outputs look subtly wrong; auth dies at hour 2; the interesting
result turns out to hinge on a methodological choice the user cares about…).
For each, do one of:

- **Prevent** — hardening or a rehearsal check covers it (Phases 1–3);
- **Pre-decide** — fold it into the SAME intake batch as a concrete scenario
  question ("if X, should the run push on, downscope, or stop?") and record
  the answer as a standing order;
- **Accept** — explicitly note it as a risk the user is fine eating.

A concern that was foreseeable but never asked about is a prep bug — the whole
point is that 3am judgment calls are made at 3pm, by the user.

**Test for phase completion:** read the runbook as the overnight session would.
For every plausible event, the runbook yields an action without asking anyone.
If you can imagine a question the run would ask, the intake isn't done.

## The doubt policy — when a live concern isn't covered by standing orders

Sometimes the run develops a concern mid-night that no standing order covers:
the results look off, the approach feels increasingly likely to be rejected,
the work is technically succeeding but possibly at the wrong thing. "Reversible
→ continue" is the wrong rule here — grinding on is reversible *and* can waste
the entire token budget on output the human bins at breakfast. The trade-off is
between two wastes: **tokens spent on a rejected result** vs **a night of
machine time lost by stopping**. The user prices that trade-off in advance
(intake item 7); overnight, the run climbs this ladder:

1. **Probe before deciding.** Most concerns are cheaply checkable: spot-open
   five outputs, re-derive one item by hand, compare against a known-good
   sample. Spend a small bounded probe budget (default ≤2% of remaining
   budget) turning "this feels wrong" into evidence either way. Never make the
   continue/stop call on vibes when a probe was available.
2. **Prefer downscoping to stopping.** A reduced continuation usually
   dominates both extremes: keep going on a representative sample instead of
   the full set, snapshot current state and continue under the alternative
   interpretation, or park this stream and reallocate the night to the next
   runbook priority. Full stop is the answer only when *no* variant of the
   remaining work survives the concern.
3. **Apply the pre-agreed threshold.** The runbook states it in plain terms,
   e.g. *"keep going unless you'd bet the result gets rejected — stop/park at
   roughly >50% rejection odds"* (night-thrift) or *"my token budget is the
   scarce thing — park anything you doubt at >20% and spend the night on the
   safe streams"* (token-thrift). Estimate the rejection odds honestly, apply
   the threshold, done. No threshold in the runbook = intake bug; default to
   downscoping (step 2), never to a full-burn continuation.
4. **Log it either way.** The probe, the estimate, the choice → DECISIONS.md;
   if the concern deserves a human eye regardless of the choice made →
   QUESTIONS.md too. The morning report surfaces both.

## Phase 1 — Harden the runner (pipeline runs)

The script that runs overnight must satisfy ALL of these. They are not
nice-to-haves; each one maps to a documented way a night has been lost.

- **Single entrypoint with flags.** One `python script.py --flags` invocation
  covers every operation (run, resume, status, verify). No compound shell glue.
- **Checkpoint + resume by default.** Progress is durable (files written
  atomically, or an append-only log/JSONL, or a done-list); re-running skips
  completed items without flags or thought. Idempotent: running twice never
  corrupts or duplicates.
- **Per-item error isolation.** One bad item is caught, logged with its error,
  and skipped. The run only aborts on the systemic conditions from the failure
  policy (e.g. N consecutive failures, auth expiry, disk full).
- **Retry with exponential backoff** on transient network errors; a cap so a
  dead endpoint fails fast into the failure policy instead of retrying forever.
- **Rate limiting + proper User-Agent** per the project's API etiquette rules.
- **Logging to a file**, timestamped, with a progress line (`i/N done, ETA
  hh:mm`) at a sane interval and a per-item line on errors. stdout alone is not
  logging — the tmux/terminal may be gone by morning.
- **`--limit N` (and/or `--dry-run`)** so the exact production code path can be
  rehearsed on a small slice. The rehearsal must exercise the REAL path — a
  separate "test mode" that skips the real writes proves nothing.
- **A status/verify subcommand** (`--status`, `--verify`) so progress and output
  integrity can be checked without ad-hoc inline code (which triggers
  permission prompts — see Phase 2).
- **Zero-argument guard**: bare invocation prints usage and exits nonzero
  (see fuzheado/Wikipedia-AI-Skills `script-audit-guidelines.md`).
- **Wall-clock guard (optional but recommended):** `--stop-after HH:MM` or
  `--max-hours` so the run finishes flushing checkpoints before the human wakes
  up, instead of being killed mid-write.

## Phase 2 — Permission anticipation (never bypass)

Permissions are **designed away**, not bypassed. Method:

1. **Enumerate every command the overnight session will run** — launch, status
   checks, verification, report writing. Write them in the runbook verbatim.
2. **Shape each command to be statically analyzable** (this is what kills the
   3am prompt — see `claude-code/lessons.md` in this repo for the full list):
   - no `cd X && cmd > file` (use absolute paths / the script's `--out` flag);
   - no inline `python3 -c` (use the script's `--status`/`--verify`
     subcommands);
   - no `curl` per-URL (HTTP happens in-process inside the approved script);
   - file I/O in-process, never shell `>` redirects.
   Some validator guardrails fire ABOVE the allowlist and cannot be allowlisted
   away — the only fix is emitting clean command shapes.
3. **Add the narrow allowlist entries** the enumerated commands need to the
   consuming repo's `.claude/settings.local.json` (L3 in the permission
   framework): exact invocations or bundled script paths, **never**
   arbitrary-exec (`Bash(python:*)` is "allow anything"). Show the proposed
   config to the user and get an explicit yes — during prep, while they're
   awake.
4. **The rehearsal (Phase 3) doubles as the permission test.** Any permission
   prompt during the rehearsal is a Phase 2 failure: fix the command shape or
   the allowlist and rehearse again. Zero prompts in rehearsal is a go/no-go
   criterion.

**Machine-level checks (macOS):**
- The machine must not sleep mid-run: launch under `caffeinate -i`, or verify
  power settings. A laptop lid or an energy saver has ended more overnight runs
  than any exception.
- Power connected; disk space checked against expected output volume.
- The process must survive the terminal: background it properly (`nohup` /
  detached background task), log to files.

## Phase 3 — Dress rehearsal + failure drill

This is the "we didn't test it well enough" fix. Both parts are mandatory for a
green light; a smoke test (imports, one API call) is NOT sufficient.

**3a. Scaled dress rehearsal**
- Run the REAL pipeline, REAL data, REAL output paths, via the EXACT command
  from the runbook — limited to a small slice (e.g. `--limit 20`, or 15–30 min
  of wall clock).
- Verify the outputs: right schema, right location, spot-check actual content
  (not just "files exist" — open one and look).
- **Extrapolate runtime** from the measured per-item rate to the full workload
  — this is a level-1 budget estimate; follow
  [`budget-estimate.md`](budget-estimate.md) (P50/P90 band, rate-limit floors,
  retry overhead — and for agentic runs, the token estimate too). The P90 must
  fit the 8–10h window with ≥25% margin. If it doesn't fit: shrink scope, or
  apply the Phase 0 priority order and state plainly what won't get done.
- Zero permission prompts observed (Phase 2 criterion).

**3b. Failure drill (kill -9, not graceful)**
- Kill the rehearsal run mid-flight with SIGKILL — not Ctrl-C, not SIGTERM;
  overnight deaths are not graceful.
- Relaunch with the same runbook command. Verify: it resumes (doesn't restart
  from zero), completed items are not re-fetched/duplicated, and the item that
  was mid-write when killed is either cleanly redone or cleanly absent — never
  half-written in the output.
- If the run uses external state (API cursors, DB rows), verify the resume is
  consistent with that state too.

## Phase 4 — Go/no-go gate

The gate is a checklist in the runbook; every line carries a `Verified by:`
naming the command or observation. **An unchecked line is a NO-GO — say so
plainly.** "Probably fine" is the phrase that precedes every lost night.

Minimum gate (extend per run, never shrink):

- [ ] Runbook complete: standing orders answer every foreseeable question
- [ ] Pre-mortem done: each predictable failure prevented, pre-decided, or
      accepted; doubt threshold recorded in the user's own words
- [ ] Dress rehearsal passed on real data — Verified by: <cmd + observed output>
- [ ] Kill -9 + resume drill passed, no dupes/corruption — Verified by: <cmd>
- [ ] Runtime extrapolation fits window with ≥25% margin — Verified by: <math>
- [ ] Zero permission prompts during rehearsal — Verified by: <rehearsal run>
- [ ] Allowlist reviewed and explicitly approved by user
- [ ] Sleep prevention + power + disk verified — Verified by: <cmd>
- [ ] Launch command written verbatim in runbook
- [ ] Failure policy + abort conditions encoded in the script, not just prose
- [ ] Morning report path defined

## Phase 5 — Launch (just before bed)

By design this takes five minutes; all thinking already happened.

1. Re-run the gate — anything gone stale since prep (new commits? disk?
   credentials still valid?) re-verifies.
2. Launch the verbatim runbook command, detached from the terminal, under
   sleep prevention, logging to the runbook's log path.
3. **Watch the first minutes** (or first ~10 items): confirm items complete at
   the predicted rate and the first checkpoint is durably written. Most
   avoidable overnight failures are visible in the first ten minutes — the
   20-minutes-in death happens because nobody watched minute one.
4. Only then say goodnight, stating: what is running, where the log is, when
   it should finish, and what the morning report will contain.

**Agentic runs:** same protocol, but "the script" is the runbook's task list.
The agent works tasks in priority order, checkpointing progress to a status
file after each task (so a crashed/compacted session resumes from the file, not
from memory). Standing orders govern all decisions; the unforeseen gets the
reversible-choice rule and, when a work stream develops real doubt, the doubt
policy ladder (probe → downscope → threshold). **No outward-facing actions
overnight** —
no sending, posting, pushing to shared branches; produce drafts for morning
approval instead. Park human-only questions in QUESTIONS and continue with
other tasks.

## Phase 6 — Morning report

One document, written to the runbook directory, in this order:

1. **Verdict first**: `SUCCESS / PARTIAL (n/N) / FAILED` + one-sentence summary.
2. **What exists now**: outputs, paths, counts — each with `Verified by:`.
3. **Failures**: categorized (transient/skipped/systemic), with counts and one
   representative error each. Plain statement of anything NOT done.
3b. **Estimate vs actual** — one line (`estimated X / actual Y (±Z%)`), and
   the actuals appended to the run-cost history so the next estimate starts
   from a better prior (budget-estimate calibration duty).
4. **Decisions taken** overnight under standing orders (from DECISIONS log).
5. **Questions parked** for the human (from QUESTIONS).
6. **Proposed next steps** — including the retry command for failed items,
   ready to run.

No overclaiming: "the run completed" is only writable with the verification
subcommand's output attached.

---

## Anti-patterns (each has cost a night)

| Anti-pattern | Why it fails |
|---|---|
| Smoke test only ("imports work, one item works") | The failure modes are at item 500, not item 1 |
| Test mode that skips real writes | Proves the code path you're NOT running |
| Graceful-shutdown-only resume testing | Overnight deaths are SIGKILL-shaped |
| "I'll allowlist it when it prompts" | It prompts at 3am; nobody is there |
| Inline `python3 -c` to peek at outputs | Unallowlistable prompt magnet — use `--status` |
| Retry forever on network errors | A dead API burns the whole window |
| Asking the user a question mid-run | The one law; park it and continue |
| Grinding on all night with mounting doubt "because it's reversible" | Reversible ≠ free; a rejected result costs the whole token budget — climb the doubt ladder |
| Binary continue-or-stop when downscoping was available | A sampled/parked continuation preserves most value at a fraction of the risk |
| Deciding continue/stop on a hunch when a 5-item spot-check existed | Probes are cheap; wrong all-night bets are not |
| Launching and immediately saying goodnight | Minute one is when it dies; watch it |
| Progress only on stdout | Terminal is gone by morning; log to files |
| "Probably fine" on an unchecked gate line | It was not fine |
