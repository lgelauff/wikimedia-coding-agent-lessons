# Runbook — <run name>  (<YYYY-MM-DD>)

> The contract for tonight's unattended run. The overnight session obeys THIS
> DOCUMENT, not memory. If an event isn't covered here and isn't reversible,
> it goes to QUESTIONS.md — never to the user at 3am.

## 1. Goal & acceptance

- **Goal:** <one sentence>
- **Full success:** <what exists by morning, measurably>
- **Acceptable partial success:** <e.g. "≥60% of items fetched with valid
  checkpoints — remainder retryable">
- **Priority order if time runs short:** <1. …, 2. …, 3. …>

## 2. Scope edges (must NOT touch)

- <repos / paths / APIs / branches that are off limits>
- **Spend/quota ceiling:** <API calls, tokens, $>
- **Rate limits:** <req/s + backoff policy> — User-Agent: <value>

## 3. The run

- **Shape:** pipeline / agentic / hybrid
- **Launch command (verbatim — this exact string, no variations):**
  ```
  caffeinate -i nohup <absolute command with flags> > <run-dir>/run.log 2>&1
  ```
- **Status check command:** `<script> --status`
- **Verify command:** `<script> --verify`
- **Expected runtime:** P50 <X h> / P90 <X h> (measured <rate> in rehearsal ×
  <N> items, per budget-estimate; window is <Y> h → P90 margin <Z>%)
- **Expected tokens (agentic/hybrid):** P50 <X> / P90 <X> (evidence level:
  measured sample / history / arithmetic)
- **Log:** `<run-dir>/run.log` · **Outputs:** <paths>

### Agentic runs only — task list

| # | Task | Acceptance criterion | Time box | Priority |
|---|------|----------------------|----------|----------|
| 1 | <task> | <how the session knows it's done> | <max h> | <1..n> |

Checkpoint after every task → `status.md`.

## 4. Failure policy

- **Per-item error:** skip, log item + error, continue.
- **Abort conditions:** <N> consecutive failures / auth expiry / disk < <X> GB
  / <other systemic signals>. On abort: flush checkpoints, write partial
  report, stop cleanly.
- **Transient network errors:** retry ≤<k> times, exponential backoff from
  <s>s; then treat as per-item error.
- **On restart after crash:** relaunch the verbatim command; resume is
  automatic (proven in the failure drill below).

## 5. Standing orders (pre-decided judgment calls)

| If… | Then… |
|-----|-------|
| <foreseen event> | <decided response> |
| Anything not listed, reversible & cheap | Choose, append to DECISIONS.md, continue |
| Anything not listed, reversible but expensive / doubtful | §5b doubt policy — never a full-burn continuation |
| Anything not listed, irreversible | Append to QUESTIONS.md, skip, continue with next work |
| Any outward-facing action (send/post/push shared) | Never overnight — draft it for morning |

## 5b. Doubt policy (continue-vs-stop economics)

**Pre-mortem scenarios** (predicted during prep, adjudicated by the user):

| Scenario | Early signal to watch for | Pre-decided response |
|----------|---------------------------|----------------------|
| <e.g. output quality looks subtly wrong> | <e.g. spot-check disagreement> | <push on / downscope to sample / park stream / stop> |
| <e.g. data far sparser than expected> | <e.g. >X% empty at item 100> | <…> |

**User's trade-off, in their own words:** <e.g. "keep going unless you'd bet
against it — park at roughly >50% rejection odds" / "tokens are the scarce
thing; park anything you doubt at >20%">

**For unforeseen doubts, climb the ladder:**
1. Probe first (≤<2>% of remaining budget): spot-check, re-derive one item,
   compare to known-good — turn the hunch into evidence.
2. Prefer downscoping: representative sample, snapshot-and-branch, or park
   this stream and move to the next §1 priority.
3. Apply the threshold above to the honest rejection-odds estimate.
4. Log probe + estimate + choice → DECISIONS.md (and QUESTIONS.md if it needs
   a human eye regardless).

## 6. Permissions (anticipated, not bypassed)

- **Every command the overnight session will run:** <enumerate verbatim>
- **Allowlist entries added to `.claude/settings.local.json`:** <list> —
  approved by user on <date/time>: yes/no
- **Rehearsal prompt count:** <must be 0> — Verified by: <rehearsal run>

## 7. Go/no-go gate  — ALL boxes checked or it's a NO-GO

- [ ] Standing orders answer every foreseeable question (read-through done)
- [ ] Pre-mortem scenarios adjudicated; doubt threshold recorded in §5b in the
      user's own words
- [ ] Dress rehearsal on real data passed — Verified by: `<cmd>` → <observed>
- [ ] kill -9 + resume drill passed, no dupes/corruption — Verified by: `<cmd>`
- [ ] Runtime P90 fits window with ≥25% margin — Verified by: <calculation
      per budget-estimate playbook, evidence level stated>
- [ ] Zero permission prompts in rehearsal — Verified by: <rehearsal>
- [ ] Allowlist explicitly approved by user
- [ ] Sleep prevention planned (`caffeinate -i` in launch cmd) + power + disk —
      Verified by: `<cmd>`
- [ ] Launch command above is verbatim-tested (rehearsal used the same string
      with `--limit`)
- [ ] Abort conditions implemented in the script, not just in this document
- [ ] Morning report path: `<run-dir>/report.md`

**Gate verdict:** READY / NOT READY (<which lines are red, plainly>)

## 8. Launch log (filled at bedtime)

- Launched: <timestamp> · PID/task: <id>
- First-minutes watch: <n> items in <m> min (rehearsal predicted <r>) —
  first checkpoint written: yes/no
- Goodnight given: <timestamp> · ETA: <time>
