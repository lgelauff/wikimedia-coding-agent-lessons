# Morning integration — multi-session wrap-up (DRAFT / experiment)

*Status: **experimental, one live trial in progress (2026-07-20)**. Per conventions §4 this is
untested prose until a documented real-case run validates it. If it works across a few mornings,
promote to a skill (likely a fourth mode of `overnight-run`, or a sibling skill — decide then).*

## The problem

Several agent sessions work overnight in parallel (worktrees/branches). In the morning the user
wants one view: what landed, what's at risk, what questions are open, what the next work packages
are — without the integrator session trampling sessions that are still wrapping up.

Prior art: `overnight-run` MORNING mode covers a *single* detached run's report. The worker-side
wrap-up (commit, push, handoff file) exists as a third-party skill pattern ("agent-handoff
session wrap-up", mcpmarket.com). The multi-session *integrator* role is the new piece.

## Separate DOING from DISCUSSING (refinement, 2026-07-27)

Three roles, deliberately on different substrates. The split emerged from a week's trial and every
significant correction in it came from someone other than the author.

| Role | Substrate | Lifetime | Reads | Produces |
|---|---|---|---|---|
| **Implement** | subagent for a bounded build; **session + worktree** only when it's long compute or multi-day | ephemeral — discard after | whatever it needs | one evidence snippet + artifacts |
| **Fact-check** | **subagent** (not a session — it's bounded: verify these numbers against these sources) | ephemeral | the snippet + its cited sources | verdict, in-place fixes, flags |
| **Discuss / integrate** | **durable session** | spans many packages | **snippets only** | framing, decisions, next packages |

**Why the asymmetry matters.** Implementation wants depth on one thing, then disposal — it's what
burns context. Discussion wants *continuity across packages*, because the real insights are only
visible from there. In the trial, none of these could have come from inside a single package:
two collaborator figures failing to reconcile (needed both), "heterogeneity is the paper's frame"
(needed five separate results), the channel-divergence reframing (needed three paragraphs at once).

**Never let the author verify their own work.** Already a rule for fact-checking; it applies just as
much to *interpretation* — an agent that spent three hours building a figure is invested in that
figure being good.

**The discussion role's failure mode: CITE, DON'T COMPUTE.** A snippet-only session drifts into
plausible-sounding wrongness. Trial case: the integrator computed a trend inline during discussion,
never persisted it, stated it to the user — and the fact-check could neither corroborate it nor
sustain the reading (it was seasonally confounded). If discussion needs a number that isn't already
in a snippet, that is a new work package, not an aside.

## Roles and contract

**Worker sessions** (each, at wrap-up — the "WIND-DOWN command", paste-ready):

> **WIND-DOWN.** Wrap up now. No new angles of inquiry. Do not kill or break ongoing long-running
> work: let short jobs finish; for anything still running, record what it is, where it logs, and
> the restart command in your handoff instead of waiting. Commit and push your branch; merge into
> main only if the merge is clean, otherwise leave the branch and say why. Write your handoff at
> `.claude/handoff-<YYYY-MM-DD>-<slug>.md`, identifying yourself by BRANCH: (1) delivered, with
> file entry points; (2) still running/unfinished + restart commands; (3) all open questions as a
> numbered list, deduplicated against the shared question file; (4) coordination notes. Write YOUR
> handoff only — the integrator session `<integrator-branch>` combines. Everything non-destructive:
> never delete data or outputs; archive with a breadcrumb instead. Then AUTO-ARCHIVE yourself:
> if and only if your branch is merged into main, pushed, and your worktree is clean, remove your
> worktree and archive this session — no need to ask. If any condition fails, leave everything in
> place and flag it in the handoff instead.

The auto-archive gate exists so the user never has to make the retire call per session; the
merged+pushed+clean conjunction is what makes it safe to automate.

**Integrator session** (one, the recipient) — two phases separated by an explicit user go-signal.
**Model tier: mid-tier (Sonnet-class) from turn one.** The role is execution-shaped — inventory,
verification, report assembly against this playbook — not open-ended reasoning; official Claude Code
guidance recommends Sonnet for coordination/verification. Escalate a single step (work-package
design / decision-list judgment) to a bigger model only if it proves thin. A mid-session model
switch costs one full uncached context pass, so pick the tier at session start (trial 1: the
integrator ran on the top tier and consumed most of a 5-hour usage window on relay work).

**Permission prep (once per project):** the morning session's operation set is predictable — git
read/merge/push, file listing/stat, integrity checks (`gzip -t`, `cmp`), the deposit script, and a
file-stability monitor — so it should run with **zero permission prompts**. Pre-allow those patterns
in the project/worktree settings (Claude Code: a `fewer-permission-prompts`-style allowlist), and if
the integrator runs in a worktree, add the MAIN checkout to `permissions.additionalDirectories` —
handoffs, data, and the brief all live there, and every cross-checkout touch otherwise prompts.

### Phase 0 — passive prep (session start; read-only toward others' work)

0. **Announce your identity first**: state your branch (and worktree) in your first message, e.g.
   "Morning session identifier: branch `<branch>`", and repeat it in status messages. The user uses
   it to route wind-down instructions and to distinguish you from workers. Until the go-signal the
   integrator makes NO commits/merges/pushes in the project repo — workers self-merge in this window,
   and an integrator that merges early races them.
1. `git fetch`; list branches by recency, worktrees + dirty state, `.claude/handoff-<today>-*.md`.
2. Report at-risk work (uncommitted / unpushed / unmerged) per session — but do NOT fix it;
   each worker resolves its own. (Trial 1: both at-risk items self-resolved within minutes;
   an eager integrator would have collided.)
3. Read handoffs + batched-question files as they land; keep a running dedup.
4. Check for commits by OTHER authors in the last 24–48 h (collaborators).
5. Prepare the verification checklist; wait.

### Phase 1 — verify + integrate (only after the user says "everything has wrapped up")

6. Per session, verify the contract: handoff exists; branch pushed; merged to main or reason
   flagged; worktree clean. Output a table with `Verified by:` lines (epistemic-labels rule).
7. Merge any remaining clean branches to main; push; conflicts → flag, don't force.
8. Write ONE combined overview at `.claude/morning-overview-<YYYY-MM-DD>.md`:
   - verdict table (per session: delivered / verified / at-risk)
   - what landed, by theme (link entry points, don't restate)
   - still-running jobs + how to check/restart them
   - ONE consolidated numbered decision list (dedup across all handoffs; batched-questions rule)
   - proposed work packages: self-contained prompts, salvage/unfinished items first
   - restructuring / staleness observations (highest level only)
9. **External-compute collects are user-action requests, not agent actions.** If overnight jobs ran
   on remote infrastructure (e.g. Toolforge), the integrator assembles the exact retrieval commands
   (scp targets, integrity checks, on-remote cleanup) from the relevant runbook and asks the user to
   run them — SSH/scp is human-only. Include the request in the overview's user-action section.
10. **Deposit new half-fabricates (intermediate artifacts) to the shared working-data repo** if the
    project has a sharing agreement / deposit registry. The registry (e.g. `registry.json`,
    source of truth) says what's pending: deposit `local`-status artifacts, append a new vintage for
    rebuilt ones (e.g. freshly collected external-compute outputs, after integrity checks). Deposits
    are append-only; never overwrite a recorded version.
11. Confirm clean tree + pushed state everywhere; retire merged worktrees only if authorized.
12. Append a dated entry to this file: what the protocol failed to anticipate.
13. **Apply pending agent-app updates at the seam** (optional, last): after everything is wrapped,
    verified, and merged — and before launching the day's new sessions — restart the agent app /
    run its update command. Rationale (Claude Code, verified 2026-07-20): updates take effect on
    restart; conversations survive a restart but background tasks and monitors are killed and NOT
    restored, so never restart mid-wrap-up while a watcher is armed. Re-arm any monitor you still
    need after the restart. A `stable` release channel suits overnight-dependent setups.

## Field log

### 2026-07-20 (wikipedia-drop-2026) — trial 1

- **Worker self-resolution works but is racy to observe:** the integrator's first status snapshot
  showed a dirty worktree that was clean 90 seconds later (the worker committed mid-check).
  Lesson: Phase-0 at-risk reports are advisory snapshots; never act on them, re-verify at Phase 1.
- **The go-signal must be explicit.** "Reports landing in the next half hour maybe" is not a
  trigger; polling wastes tokens and risks integrating a half-written handoff. The user saying
  "all wrapped up" is the only Phase-1 trigger.
- **Handoffs that point instead of restate are cheap to integrate.** The first handoff in
  (hypothesis-review) linked entry-point files and a shared question file rather than duplicating
  content — integration cost near zero. Encourage this in the worker prompt.
- **Designate exactly ONE integrator, by name, in every worker's wind-down prompt.** In trial 1 a
  worker session went beyond its own handoff and committed a *combined* morning brief to main while
  the designated integrator was in Phase 0 — two combiners, duplicated dedup work, and the risk of
  two conflicting decision lists. The worker contract should say: "write YOUR handoff only; the
  integrator session <name> combines."
- **Worktree/session naming confuses handoffs.** Worktree directories get reused by later sessions on
  new branches; two handoffs flagged "stoic-bhabha at risk" after that worktree's occupant had
  changed and the flag was stale. Identify sessions by BRANCH, not worktree directory name.
- **Deposit-time path/vintage discrepancies are the norm, not the exception.** Trial 1: the collect
  runbook's retrieval target and the deposit registry's `source_glob` were different directories; the
  landing set overlapped an older partial build. Byte-compare (`cmp`) settled it (same build, now
  complete) and the deposit proceeded from the registry path. Never guess a vintage identifier —
  derive it from the artifact's own README/log, and dry-run the deposit first. Watch for pre-existing
  HF vintage tags (409) when appending a completion to an existing vintage.
- **Repeat every document link in a footer with resolvable paths.** Mid-message links are often
  worktree/branch-relative and dead by click time (multi-checkout repos). End any link-bearing
  handoff message with a "Links:" bullet list, each path valid where the file currently lives
  (main-checkout absolute path once merged; name the branch for branch-only files).
- **Every Phase-1 checklist item needs exactly one owner — and a just-in-time re-check.** In trial 1
  the integrator and a lingering worker session both executed the brief's deposit step minutes apart:
  duplicate registry version entries, one with a conflicting vintage label. Before any
  state-mutating checklist item (deposit, merge, retire), re-read the shared state (registry,
  git log) in the same minute you act; and after the go-signal the integrator should confirm all
  worker sessions have actually STOPPED, not just handed off. The producing session's metadata
  label beats the integrator's inference — when both exist, keep the producer's.
- **Parallel agents sharing ONE checkout must stage by explicit path.** With several subagents
  writing to the same working copy, the git index is shared state: in trial 1 one agent's `git add`
  swept up a sibling agent's file that appeared between its add and commit (it caught this via
  `git show --stat`, did `reset --soft HEAD~1`, re-staged selectively — no loss, but only because it
  checked). Rule for every parallel-agent prompt: stage ONLY your own files by full path, never
  `git add -A/.`, and verify with `git show --stat` before pushing. Push races themselves are
  benign — `pull --rebase` once and retry.
- **An "orchestrator" subagent may not be able to spawn subagents.** Trial 1: an Opus agent spun
  up to *orchestrate* workers found no subagent-spawning tool in its context, so it silently became
  a solo worker — doing the analysis itself and, critically, being unable to run the mandatory
  independent fact-check (an agent must not verify its own work). Lesson: orchestration that needs
  fan-out belongs to a top-level session (which has the Agent tool), not a nested subagent. If you
  do delegate orchestration, tell the agent to REPORT BACK a dispatch plan rather than assume it can
  spawn — and always run the second-agent fact-check from a level that can spawn.
- **Some stalls are just flaky WiFi, not agent bugs (user, 2026-07-23).** When an agent dies on a
  connection/watchdog error, first check whether its deliverable already landed on disk — the work
  often finished and only the report was lost. Give network `curl`/fetch a hard `--max-time`, and
  prefer in-thread checks against local committed files when the option exists.
- **"Agent completed" ≠ task done — the background-compute stall.** A subagent that launches its
  own long-running job (a Monitor, a detached script) can hit its turn boundary while that job is
  still running and report as *completed* with the work unfinished. Trial 1: 2 of 5 parallel agents
  stalled this way, both mid-pipeline. Detection: the return text says "still running / I'll pick
  back up" instead of a deliverable. Fix: resume the agent by message (its context is intact) — do
  NOT respawn, which re-does the compute. Prevention: tell compute-launching agents to wait for
  their own job in-turn, and always read an agent's returned deliverable before marking a step done.
  Corollary: never report a step complete on the strength of a completion notification alone.
- **Keyword-based guard hooks can false-positive on prose.** A commit that merely *mentioned* a
  remote-copy command inside a heredoc tripped the SSH-blocking hook. Workaround: write file content
  with the editor tool, keep Bash for git only.
- **A shared batched-question file beats per-handoff question lists.** One worker maintained
  `private/reviews/cleanup-morning-questions.md` and other handoffs appended numbered items
  beyond it — dedup was trivial because numbering continued (items 10–12).
