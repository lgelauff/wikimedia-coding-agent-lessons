# Session close — remote job packets and overnight runs

Loaded from `../SKILL.md` Phase 4 only when the repo uses remote compute or unattended runs.
The skill is in advisory mode: draft, never create or file.

### 4a. Remote / cluster job packets — ONLY if this repo uses them

🔒 **Describe what a compliant packet would contain and where it would go. Do not create it.**

Everything needing a shell the agent cannot open goes here, written **batch-launchable**, because the scarce resource is the user's terminal time.

Every packet states:
- **Gates** — what must be true before launch, each independently checkable, load-bearing one first. A packet whose first gate fails should cost nothing.
- **Resource limits**, explicitly, in whatever form the scheduler enforces. ⚠ Find out how *this* scheduler fails when you exceed them — on some (Toolforge's job framework, for one) an over-quota job is **silently refused with empty logs**, so the packet must say how to confirm the job actually *started*, not merely that a command returned 0.
- **The right submission mode** — batch/job submission rather than an interactive shell, where inline runs can hang unkillably.
- **Verification on content, not exit code.** Logs are often gone once a one-off completes, and file size proves nothing: a job dying two-thirds through leaves a plausibly-sized file.
- **If the repo numbers its job packets**, a unique id checked against that index for collisions before use. (Skip if it has no such scheme — do not invent one at session close.)

### 4b. Overnight / unattended runs — ONLY if this repo has them

🔒 **Same: draft the package spec, do not build or file it.** The requirements below are the bar a package must meet — they are what you check a *proposal* against, not a licence to write one.

**A stocked queue is the goal — recommend what would stock it.** Bedtime should be a five-minute pick from a menu; a night is lost whenever the run has to be *prepared* at bedtime. Prep by day. (See the `overnight-run` skill for the full prep → rehearse → launch → report protocol.)

Any new package satisfies:
- A **`--test` mode exercising the full pipeline** on a small subset, for anything over ~5 minutes.
- **Checkpoints** — one low-verbosity line each — for anything over ~20 minutes. ⚠ Check this honestly: *file-level* idempotency alone will restart a 45-minute unit from zero after a crash.
- A frozen dated **script + hash + manifest** snapshot for any script whose output is kept.
- **Data persisted before any figure**; figures render from the persisted table, with a `--render-only` path.
- **Variant-suffixed outputs**, so a new parameterisation cannot clobber an already-cited one.

⚠ Before any bulk external-API or LLM run, confirm the **rate/throttle guard is actually working**, not merely present — an unverified guard has been the cause of silent quota burn.

