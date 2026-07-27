# Proposal: the three-session model for agentic research work

*Status: **PROPOSAL — not adopted.** Written 2026-07-27 by the integrator session
(`claude/morning-wrap-up-repo-311cc6`, project `wikipedia-drop-2026`) at the user's request, for
review elsewhere. Evidence base: one week of live multi-session work (2026-07-20 → 27), not theory.
Companion: [`morning-integration.md`](morning-integration.md), whose integrator role this refines.*

---

## 1. The claim

Agentic research work should be split across **three concurrent sessions plus one class of cold
agent**, separated by **cadence** rather than by topic:

| | Session | Rhythm | Blocked by | Needs |
|---|---|---|---|---|
| **A** | **Infra / data** | slow; hours→days; bursty | user SSH, remote quota, dump availability | runbooks, credentials-adjacent context, verification rules |
| **B** | **Analysis / implementation** | fast; minutes→hours; parallel | data being present | one package's depth, then disposal |
| **C** | **Discussion / integration** | continuous | verified snippets arriving | snippets only |
| — | **Fact-check** | *cold agent, never a session* | — | the snippet + its cited sources + a durable written contract |

The interface between all four is the **evidence snippet**: claim → exact numbers → `Verified by:`
→ caveats → artefact paths. Self-contained by construction, so no role needs another's transcript.

## 2. Why separate at all — the evidence

In the trial week, **every significant correction came from someone other than the author**:

- A fact-check overturned the integrator's own explanation of a figure discrepancy (a claimed
  5-edition-vs-15-edition difference was actually a time-window difference).
- A back-fill agent found a **sign flip** in a headline sub-window claim that its original author had
  reported as robust.
- A rehearsal caught a **fatal flaw in hardening the integrator had just committed** (an assumed
  sorted-contiguous input was actually interleaved; checkpointing would have silently under-counted
  by ~99%).
- A dedicated caveat pass **demoted a headline paragraph** to not-printable, and found a previously
  undocumented instrument break sitting under its baseline.

This is already encoded for verification ("never fact-check your own work"). The proposal is that
**interpretation carries the same conflict of interest**: an agent that spent three hours building a
figure is invested in that figure being good.

## 3. Why *these* three — the cadence seam

Topic-based splits (one session per hypothesis) fail because hypotheses share data and share
framing. **Cadence-based splits hold** because the three rhythms genuinely block on different things:

- **Infra is slow and human-gated.** Remote jobs, quota checks, multi-CPU-day pipelines, `scp`
  retrievals. It waits on the user constantly. It does *not* need the paper's framing debate.
- **Analysis is fast and parallel.** Many bounded packages, each producing one snippet. It needs
  the data present; it does not need remote credentials.
- **Discussion is continuous and cross-cutting.** It needs neither of the above, only snippets.

Observed cost of *not* splitting: with a CPU-bound scoring job in the same session, fast figure work
had to be held back to avoid contention — the slow work stalled the fast work for no reason.

## 4. Why discussion must be the durable one (the asymmetry)

Implementation wants **depth on one thing, then disposal** — it is what burns context.
Discussion wants **continuity across packages**, because the highest-value insights are only visible
from there. From the trial, none of these could have come from inside a single package:

- Two collaborator-sourced figures failing to reconcile → likely *one* root cause, not two
  coincidences (needed both packages side by side; and the eventual resolution — a different
  aggregation scope — closed one of them outright).
- "Heterogeneity is the paper's frame, not its caveat" → emerged only after **five** independent
  results all pointed that way.
- A channel-divergence reframing → required three paragraphs' findings simultaneously.

So the disposable/durable assignment is the opposite of the intuitive one: **discard implementations,
keep the discussant.**

## 5. Why fact-check is a COLD AGENT, not a session

Independence is the entire value. A durable fact-check session accumulates the investment problem it
exists to prevent: having ruled on an artefact once, it becomes the author of that verdict and
defends rather than re-tests it. **Each check should arrive with no priors.**

The real cost of coldness — every checker re-learning project conventions (edition sets, pooled-cut
rules, locked folders) — is fixed by a **durable written contract**, not a durable agent. In the
trial this already exists as a reusable fact-check template kept verbatim in the work-packets file.
*Sharpen the contract; keep the agent cold.*

## 6. The discussion role's failure mode: CITE, DON'T COMPUTE

A snippet-only session drifts into plausible-sounding wrongness. **Observed, not hypothetical:** the
integrator computed a trend inline mid-discussion, never persisted it, and stated it to the user as
a finding. A later fact-check could neither corroborate the number (it existed in no artefact) nor
sustain the reading (it was seasonally confounded, and the underlying series was still declining).

**Rule:** if discussion needs a number that is not already in a snippet, that is a **new work
package**, not an aside. The discussion session cites; it does not compute.

## 7. Known costs and the discipline required

Three sessions means three places for state to diverge. Both of these were observed in the trial:

- **Shared-index collisions** — concurrent sessions swept each other's files into commits, and hit
  `index.lock` contention. *Mitigation (already in force): stage ONLY your own files by explicit
  full path, never `git add -A`/`.`; `git show --stat` before every push; `git reset HEAD -- <foreign>`
  if foreign files appear staged.*
- **Stale cross-session status** — one session's "at-risk work" warning about another was already
  false 90 seconds later; worktree directory names outlived their occupants. *Mitigation: identify
  sessions by BRANCH, never by worktree name; treat cross-session status as an advisory snapshot and
  re-verify before acting.*

Further costs to weigh in review:
- **Duplicated context acquisition** — each session re-reads project conventions. Partly mitigated by
  good durable docs; not free.
- **Handoff latency** — a snippet must land before discussion can use it.
- **Tacit knowledge loss** — the implementer knows things that never reached the snippet. In the
  trial, a rehearsal's most valuable finding survived *only because* it was written into its notes
  before the agent died. *Mitigation: snippets must record surprises and dead ends, not just results.*

## 8. Open questions for review

1. **Is infra genuinely a session, or a queue of user-gated tasks a discussant dispatches?** It
   spends most of its life blocked on a human.
2. **Who owns the running task list** when three sessions can all add to it?
3. **Does the discussant also own outward-facing drafts** (messages to collaborators), or is that a
   fourth role? Outward-facing work has its own approval gate.
4. **What is the minimum viable snippet** such that discussion never needs the transcript?
5. **When should an implementation be a session rather than a subagent?** Working answer: when it is
   long compute, multi-day, or needs its own worktree — otherwise a subagent.
6. **Does the model degrade gracefully to one session** on a small project, or does it impose
   overhead that only pays off above some scale?

## 9. Minimal adoption test

Run one week with the split, and measure:
- corrections caught by non-authors (expect: stays high),
- discussion-session context growth (expect: much slower than under the combined role),
- whether fast analysis work ever stalls behind slow infra work (expect: no),
- whether any number reaches the user without a snippet behind it (expect: zero — this is the
  cite-don't-compute rule made falsifiable).
