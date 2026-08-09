---
name: session-close
description: Wrap up a working session on any repo — secure at-risk work that `git status` cannot see (gitignored files in worktrees, orphanable background jobs), evaluate what the session actually established, surface open ends by who is blocked, and route the resulting actions into the project's own queues (overnight runs, remote/Toolforge job packets, worklist). Use when the user signals they are ending the session — "let's wrap up", "close the session", "end of session", "/session-close", "that's it for today", "picking this up tomorrow". A bare "what did we do today" is usually a recap request, not a session end: just answer it. Do NOT use mid-task, and do NOT use for "wrap up this PR/feature" — finishing one piece of work inside an ongoing session is a commit and a short summary, not a session close.
---

# Session close

> ## 🔒 ADVISORY MODE — PROBATIONARY, IN FORCE
>
> **This skill REPORTS and RECOMMENDS. It does not change anything.** Until it has run flawlessly
> enough times to earn it, it makes **no edits, no commits, no pushes, no file writes, no moves, no
> deletions** — in the repo or anywhere else.
>
> Everything below that reads like an instruction to act is an instruction to **propose the action
> and stop**. Present it, say exactly what you would run or write, and wait for the user to say yes.
> The user performs the change, or explicitly tells you to.
>
> **Why:** a session close runs precisely when unsaved work is at its most exposed and least
> recoverable. A tool that is wrong here is worse than no tool. It earns write access by first
> demonstrating it reads correctly — not the other way round.
>
> The scanner enforces its half in code: `git_hygiene.py` accepts only an allowlist of read-only
> git subcommands and raises `UnsafeGitCommand` on anything else, so it *cannot* mutate a repo even
> if edited carelessly. This block is the other half — the part that governs **you**.
>
> **To lift:** the user says so explicitly. Do not infer it from a single approval, from "go ahead"
> on one item, or from the skill having worked last time.

A session ends in one of two states: the work is **identified and routed**, or it is **quietly
lost**. Evaluating work that is about to be deleted is worthless, so the securing scan comes first.

Run the phases in order. Do not skip Phase 1 because the tree "looks clean" — that is precisely the state in which the losses happen.

**This skill is repo-agnostic.** Where it says *the project's* worklist or job-packet file, use whatever that repo actually uses; discover it rather than assuming a filename. If a repo has no such queue, say so and propose one rather than inventing a path silently.

---

## Phase 1 — Secure (always first, never skipped)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/git_hygiene.py" --repo . --ignored
```

`${CLAUDE_PLUGIN_ROOT}` is required — a bare `agent-tooling/...` path resolves against the *consuming* repo, where that directory does not exist. Every sibling skill uses this form.

**Exit codes: 0 = clean and the scan completed · 1 = at-risk work found · 2 = THE SCAN COULD NOT COMPLETE.** Treat 2 as worse than 1: a repo whose scan failed is *unverified*, not clean, and you cannot act on what you could not see. Never report "nothing at risk" on a 2.

**It only reports — it never commits, pushes, or deletes.**

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

For each flagged path decide explicitly: **regenerable, or irreplaceable?** **Size is not the guide** — an 800 MB cache may be regenerable while a 12 KB scan output is not.

🔒 **Advisory mode:** for anything you judge irreplaceable, **do not copy, move or commit it.** Say which path, why you believe it is irreplaceable, and give the exact command that would secure it — then stop and let the user run it. A wrong `cp` at session close overwrites the thing you were trying to save.

Then check for background jobs that closing would orphan. ⚠ **The scanner does not do this** — it is git-only. Check by hand (`ps`, the job scheduler, any run/PID files the repo uses) and **report** what is running; do not kill anything.

⚠ Two further blind spots the scanner cannot see, worth a sentence each rather than silence: **unsaved editor buffers**, and **work written outside any repo** (scratch dirs, `/tmp`, output paths the project deliberately keeps out of tree).

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

🔒 **Advisory mode:** identify the queue file and **draft the exact entry**, then show it and wait. Do not append to, reorder, or edit any queue file yourself.

⚠ **4a and 4b are CONDITIONAL.** Many repos have no remote compute and no unattended runs. Check whether this one does; if not, skip them, say so in one line, and go to 4c. Do not manufacture work to fill them.

### 4a. Remote / cluster job packets — ONLY if this repo uses them

Everything needing a shell the agent cannot open goes here, written **batch-launchable**, because the scarce resource is the user's terminal time.

Every packet states:
- **Gates** — what must be true before launch, each independently checkable, load-bearing one first. A packet whose first gate fails should cost nothing.
- **Resource limits**, explicitly, in whatever form the scheduler enforces. ⚠ Find out how *this* scheduler fails when you exceed them — on some (Toolforge's job framework, for one) an over-quota job is **silently refused with empty logs**, so the packet must say how to confirm the job actually *started*, not merely that a command returned 0.
- **The right submission mode** — batch/job submission rather than an interactive shell, where inline runs can hang unkillably.
- **Verification on content, not exit code.** Logs are often gone once a one-off completes, and file size proves nothing: a job dying two-thirds through leaves a plausibly-sized file.
- **If the repo numbers its job packets**, a unique id checked against that index for collisions before use. (Skip if it has no such scheme — do not invent one at session close.)

### 4b. Overnight / unattended runs — ONLY if this repo has them

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

## Output — persist it, or this skill contradicts itself

⚠ **Phases 2, 3 and 5 produce findings that exist only as chat text unless you write them down — which makes them exactly as loseable as the gitignored files Phase 1 exists to rescue.** Persist them.

🔒 **Advisory mode — draft it, do not write it.** Compose the dated close-out note and present it in chat, naming the path you would put it at, wherever the repo's own convention points (**discover it — do not invent a path**; if there is no convention, say so and propose one). It carries: the labelled findings from Phase 2, the open-ends table from Phase 3, what was routed where in Phase 4, and Phase 5's verdict plus the one recommended next action. **Self-contained enough for a cold agent with no memory of this session.** The user decides whether it is written. If they decline, the chat summary IS the deliverable — say so plainly rather than leaving them thinking a file exists.

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
