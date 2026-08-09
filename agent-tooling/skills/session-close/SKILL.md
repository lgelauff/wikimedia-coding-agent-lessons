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

### The escape routes — work leaves by more than one door

The scanner covers the first two. **The rest it cannot see, and they are not optional to check** — they are where the expensive losses happen, because nothing warns you.

| # | Route | How to check | If you cannot verify |
|---|---|---|---|
| 1 | **Uncommitted / unpushed / stashed** | scanner | — |
| 2 | **Gitignored files, esp. in worktrees** | scanner `--ignored` | — |
| 3 | **Processes started from here** — a script left running in this session | `ps`, the repo's run/PID files | report it; **never kill it** |
| 4 | **Other terminals, other agents, other worktrees** | you cannot see them. **Ask.** | list what you know was started and ask the user to confirm each is finished |
| 5 | **Remote / detached compute** — cluster or Toolforge jobs, CI runs, cloud batch, anything dispatched elsewhere | usually needs credentials the agent does not have | **enumerate every job this session dispatched** and get each one's state |
| 6 | **Undocumented intentions** — a TODO, a defect or a follow-up that was only ever *said* | sweep the session for stated-but-unfiled items | file them in Phase 2, or name them as dropped |

**The rule for 3–6: anything that cannot be verified FINISHED is either explicitly handed off — to a person, a queue, or a scheduled job, named — or explicitly abandoned, out loud. Never left implicit.** A job still running when the session ends has no owner unless you give it one, and "it was probably done" is how a half-written output file becomes next week's mystery.

⚠ **Route 5 deserves its own paragraph** because it fails quietly and expensively. A dispatched job outlives the session that started it. If it is still running, say so, say where its output lands, and say who or what checks it. If it finished, say whether anything verified the *content* — an exit code and a plausible file size prove nothing, and logs are often gone once a one-off completes.

⚠ **Route 6 is the one that looks like nothing.** Things said in passing during a session — "that number looks wrong", "we should check X", "this needs a test" — are gone when the transcript is. If it was worth saying, it is worth filing or explicitly dropping. **Flag anything that may still need documenting rather than assuming someone wrote it down.**

⚠ Two blind spots no check covers: **unsaved editor buffers**, and **work written outside any repo** (scratch dirs, `/tmp`, deliberately out-of-tree output paths). Name them if either is plausible.

---

## Phase 2 — What still needs doing (the primary output)

**This is the part that earns the session close.** A close-out is read by whoever picks the work up — usually the user tomorrow, sometimes a cold agent with no memory of any of this. What they need is *what to do next and what is in the way*, not a narrative of what happened.

Sort by **who is blocked**, because that is what determines what can move without the user:

| class | meaning |
|---|---|
| **Blocked on the user** | needs their terminal, credentials, an account, or a decision only they can make. Frequently the real bottleneck. |
| **Blocked on a decision** | needs a judgement call, not work. Give the options **and a recommendation** — an unrecommended choice list just moves the work to them. |
| **Ready, no decisions** | could start immediately. Name the first command. |
| **Blocked externally** | third-party access, a collaborator's workstream, a pending request. |

Anything raised this session and not resolved is either **listed here** or **explicitly dropped, out loud**. Silent disappearance is the failure mode. Queue doubts rather than blocking on them.

**Where to look**, so this is discovery and not recall: uncommitted/unpushed work from Phase 1, `git log` for this session's commits, the repo's own worklist or issue tracker, and anything the transcript raised and left hanging. Prefer artifacts over memory — you will misremember.

---

## Phase 3 — What changed that alters what someone should do next

⚠ **Bounded on purpose.** A full retrospective is expensive and mostly redundant — `git log` already records what happened. Include a past-tense item **only if it changes a future decision**. If you cannot name what someone would do differently knowing it, leave it out.

That test admits four things, and they are the ones that actually bite:

- **A number moved** — and something downstream still quotes the old one. Name the consumers.
- **Something went stale**, usually because an upstream input was recomputed. ⚠ **Enumerate every consumer before declaring it scoped** — a single stale intermediate table once turned out to underlie *three* of four reported findings, not one.
- **A finding got weaker or died.** Say so as readily as a success; nulls and withdrawn claims are results, and someone will otherwise cite the dead version.
- **A candidate was mistaken for a confirmation.** Detector and static-analysis counts are candidates: one raw output showed >1,000 hits that narrowed to **nine**. Report both numbers; never let the raw count travel alone.

Label anything non-trivial **[confirmed]** (observed — say where), **[concluded]** (inferred — state the inference), or **[guess]**. An unlabelled conclusion is a violation.

Everything else that happened this session belongs in the commit log, not here.

## Phase 4 — Route the Phase 2 actions into the project's queues

⚠ **Session types differ, and this skill does not try to classify them.** A data-pipeline session, a writing session and a bug hunt close differently, but *guessing which one this was* is unreliable and the guess would drive everything downstream. Instead, **let the artifacts say what kind of session it was**: what did it produce — commits, a data artifact, prose, a failed run, an unanswered question? Route each by what it actually is. A repo with no queues at all still has Phase 2's table, which is the part that generalises.

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

---

## Output — persist it, or this skill contradicts itself

⚠ **Phases 2, 3 and 5 produce findings that exist only as chat text unless you write them down — which makes them exactly as loseable as the gitignored files Phase 1 exists to rescue.** Persist them.

🔒 **Advisory mode — draft it, do not write it.** Compose the dated close-out note and present it in chat, naming the path you would put it at, wherever the repo's own convention points (**discover it — do not invent a path**; if there is no convention, say so and propose one). It leads with **Phase 2's what-still-needs-doing table**, then what was routed where, then only the Phase 3 items that change a future decision, then the one recommended next action. **Self-contained enough for a cold agent with no memory of this session.** The user decides whether it is written. If they decline, the chat summary IS the deliverable — say so plainly rather than leaving them thinking a file exists.
