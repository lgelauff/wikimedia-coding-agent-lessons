---
name: session-close
description: Wrap up a working session on any repo — secure at-risk work that `git status` cannot see (gitignored files in worktrees, orphanable background jobs), evaluate what the session actually established, surface open ends by who is blocked, and route the resulting actions into the project's own queues (overnight runs, remote/Toolforge job packets, worklist). Use when the user says "let's wrap up", "close the session", "end of session", "what did we do today", "/session-close", or before stepping away from a long session. Do NOT use mid-task.
---

# Session close

A session ends in one of two states: the work is **secured and routed**, or it is **quietly lost**. Evaluating work that is about to be deleted is worthless, so securing comes first.

Run the phases in order. Do not skip Phase 1 because the tree "looks clean" — that is precisely the state in which the losses happen.

**This skill is repo-agnostic.** Where it says *the project's* worklist or job-packet file, use whatever that repo actually uses; discover it rather than assuming a filename. If a repo has no such queue, say so and propose one rather than inventing a path silently.

---

## Phase 1 — Secure (always first, never skipped)

```bash
python3 agent-tooling/scripts/git_hygiene.py --repo . --ignored
```

Exit 0 = clean. Exit 1 = decisions needed. **It only reports — it never commits, pushes, or deletes.**

`--ignored` is the flag that matters and it is **off by default**, because walking ignored trees can mean tens of GB and must never sit on the SessionStart critical path. At session close you want it on.

### Why the ignored scan exists

`git status` is **structurally blind to gitignored files**. A worktree can report perfectly clean while holding the only copy of something irreplaceable. Real incidents:

- A worktree collapse deleted **1,120 MB** of derived analysis fields. The worktree reported clean. It *was* clean — the data was ignored. Eight tracked scripts were left with no input.
- A bug-detector and its full scan output existed **only** inside a worktree's ignored scratch directory.
- Same day, a generalised regression guard sat untracked in a *second* worktree, absent from the commit that shipped its own audit.
- **And during the session that built this skill**, one of those worktrees was collapsed mid-session. The artifacts survived *only* because the check had run an hour earlier and copies had been made.

### Reading the output

- **Main-checkout ignored content is reported but never counted as at-risk.** It is the normal build/data store; a session ending cannot hurt it. Flagging it would drown the signal.
- **Worktree ignored content is at-risk**, because collapsing a worktree is routine cleanup that takes it along silently.

For each flagged path decide explicitly: **regenerable, or irreplaceable?** **Size is not the guide** — an 800 MB cache may be regenerable while a 12 KB scan output is not. Anything irreplaceable is copied into the main checkout or committed **before** you continue.

Then confirm no background job is still running that closing would orphan.

---

## Phase 2 — Evaluate what the session established

Not an activity log. The question is **what is known now that was not known at the start**, and at what grade.

Label every non-trivial claim **[confirmed]** (directly observed — say where), **[concluded]** (inferred — state the inference), or **[guess]** (unverified). An unlabelled conclusion is a violation.

State what **changed status**, in either direction:

- A finding that got **stronger** — and what verified it.
- A finding that got **weaker or died**. Say so as readily as a success. Nulls, withdrawn claims and refuted hypotheses are results. A static audit whose honest headline was "zero live bugs" is a finding; so is a dose-response that turned out to be a null.
- A number that **moved** — and whether anything downstream still quotes the old one.
- Anything now **stale**, usually because an upstream input was recomputed.

⚠ **Always check propagation.** When an input is found stale, enumerate everything that reads it before declaring the problem scoped. A single stale intermediate table once turned out to underlie *three* of four reported findings, not one. A staleness discovery is not complete until every consumer is listed.

⚠ **Distinguish candidates from confirmed.** Static-analysis and detector counts are candidates. One audit's raw output showed >1,000 hits that narrowed to **nine** real ones. Report both numbers, and never let the raw count travel alone.

---

## Phase 3 — Open ends, sorted by who is blocked

That sort order is what determines which items can move without the user.

| class | meaning |
|---|---|
| **Blocked on the user** | anything needing their terminal, credentials, an account, or a decision only they can make. Often the scarce resource — not CPU. |
| **Blocked on a decision** | needs a judgement call, not work. Give the options **and a recommendation**. |
| **Ready, no decisions** | could start immediately. |
| **Blocked externally** | third-party access, a collaborator's workstream. |

Anything raised and not resolved is either **filed** in the worklist or **explicitly dropped**. Silent disappearance is the failure mode. Queue doubts; don't block on them.

---

## Phase 4 — Route actions into the project's queues

**This is what makes a session close productive rather than administrative.** Actions do not go into prose nobody re-reads — they go into the queues the project runs from. Find the repo's actual queue files first.

### 4a. Remote / cluster job packets (Toolforge, HPC, CI-run batch work)

Everything needing a shell the agent cannot open goes here, written **batch-launchable**, because the scarce resource is the user's terminal time.

Every packet states:
- **Gates** — what must be true before launch, each independently checkable, load-bearing one first. A packet whose first gate fails should cost nothing.
- **Resource limits**, explicitly. On shared clusters, over-quota jobs may be **silently refused with empty logs** — so the packet must say how to confirm the job actually *started*, not just that a command returned.
- **The right submission mode** — batch/job submission rather than an interactive shell, where inline runs can hang unkillably.
- **Verification on content, not exit code.** Logs are often gone once a one-off completes, and file size proves nothing: a job dying two-thirds through leaves a plausibly-sized file.
- A **unique packet id**, checked against the shared index for collisions before use.

### 4b. Overnight / unattended runs

**Keep this queue stocked.** Bedtime should be a five-minute pick from a menu; a night is lost whenever the run has to be *prepared* at bedtime. Prep by day. (See the `overnight-run` skill for the full prep → rehearse → launch → report protocol.)

Any new package satisfies:
- A **`--test` mode exercising the full pipeline** on a small subset, for anything over ~5 minutes.
- **Checkpoints** — one low-verbosity line each — for anything over ~20 minutes. ⚠ Check this honestly: *file-level* idempotency alone will restart a 45-minute unit from zero after a crash.
- A frozen dated **script + hash + manifest** snapshot for any script whose output is kept.
- **Data persisted before any figure**; figures render from the persisted table, with a `--render-only` path.
- **Variant-suffixed outputs**, so a new parameterisation cannot clobber an already-cited one.

⚠ Before any bulk external-API or LLM run, confirm the **rate/throttle guard is actually working**, not merely present — an unverified guard has been the cause of silent quota burn.

### 4c. Everything else → the rolling worklist

Each entry self-contained enough to act on without this conversation: paths, ids, and why it matters.

---

## Phase 5 — Big picture

Three or four sentences, not a report. Where does **the actual deliverable** stand — the paper, the release, the tool — not the repo and not the pipeline.

Useful framings:
- **Output vs input.** Has evidence/code run ahead of the writing or shipping? Did this session narrow that gap or widen it?
- **What is shippable today** versus what is gated, and on what.
- **The critical path** — which single unblock moves the most.
- **Anything that could subtract** from the headline rather than add to it. Those rank above confirmations.

End with **one recommended next action** and why. A recommendation, not a menu. The user can overrule it.

---

## House rules throughout

- **Report failure as readily as success.** *"If things don't work, that is fine, as long as you know that it doesn't work."*
- **Verify by opening the output, not by exit code.** A run can "complete" while producing degraded results.
- **Correct the summary, not just the detail.** A correction appended below a wrong table leaves the table wrong — accurate in full, misleading at a glance.
- **A hash proves bytes match and nothing else** — not which copy is canonical, not which is cited.
- **Beware weak guards.** A check that passes on "not *all* values identical" will pass when 87% are identical. State what a guard actually discriminates, and whether its threshold has ever been exercised.
- **Never fabricate an identifier** (DOI, ISBN, ticket, arXiv id). Use a `VERIFY` placeholder unless the user supplied it.
- Put all questions for the user in **one numbered list**.
