# Playbook: PR quality gate

An agent-neutral procedure for vetting a pull request and ending with one verdict. It is **adaptive**: cheap checks always run; expensive ones run only when the diff warrants them. This is the *method*; a per-agent adapter supplies the triggering, the concrete orchestration, and a per-project config with the repo-specific values.

## Inputs

- The diff under review (current branch vs the base, or a named PR).
- A **project config** (e.g. `.claude/pr-check.json`) supplying repo-specific values: the `base_ref`, scope globs, sensitive-content patterns, the `test_command`, the runtime-verification mechanism, and the human-staging mechanism. The procedure never hardcodes these — if the config is missing, say what's needed.

## Operating rules

- **Read-only.** Assess, don't fix or push.
- **Concurrency-safe.** Analyze committed refs; if you need a clean checkout, use a throwaway worktree, never the main one.
- **Reuse existing reviewers/runners** the host environment already provides rather than reimplementing them.

## Steps

**0. Scope.** Compute the changed files and scope flags (run the bundled `scope.py` with the project config). Flags typically include doc-only, templates/CSS, JS, DB/migrations, ops/deploy, backend logic, sensitive (auth/proxy/secret/SQL), and runtime (user-facing flows). Doc-only → skip to a light prose/accuracy pass and the verdict.

**1. Mechanical review.** Run the environment's diff reviewer (or an inline correctness + reuse/efficiency pass). Capture findings with file:line + severity.

**2. Tests.** Run the project's `test_command`. A red suite caps the verdict at *needs-changes*; record which tests failed.

**3. Expert panel + cross-review.** Convene reviewers matched to the scope flags (a generalist always; plus accessibility/usability for UI, frontend for JS, database for schema/migrations, ops for deploy). Run them in parallel, then a **cross-review** round where each confirms / disputes / supplements the others (this kills false positives and surfaces gaps), then synthesize. Scale to the change.

**4. Security review (conditional).** Only if the *sensitive* flag fired. A real security finding caps the verdict at *needs-changes*.

**5. Targeted local verification (conditional).** Run if the *runtime* flag fired, or if steps 1/3/4 produced a behavioral finding worth reproducing. This is **not** a canned full regression run — it's surgical:
   - **(a) Reproduce flagged bugs.** Reviewers found bugs by *reading*; here, drive the concrete trigger on a running stack and record reproduced / not-reproduced / n/a. Style/naming/pure-semantics findings can't be reproduced — they stand on the review alone. A reproduction can be cheap and decisive (e.g. a parse check proving an inline script is dead) — it need not be a full stack spin-up.
   - **(b) Exercise + time the touched pathways.** Confirm behavior and capture basic performance (response time, obvious N+1 / extra-round-trip / slow-fallback signs). Performance matters: regressions hide in fallback paths that all unit tests pass through.
   Reproduced → hard blocker. Asserted-but-not-reproducible → downgrade to "flagged, not reproduced." Slow-but-correct → call it out with timing.

**6. Human-staging recommendation.** Advise a person-driven staging pass when: the change hits live-backend behavior local verification can't reproduce; it's an accessibility/screen-reader change needing human judgment; the runtime flag fired but step 5 was skipped/failed; or it changes irreversible/identity-exposing flows. Otherwise state plainly that none is needed.

## Verdict

End with **GO / MERGE-WITH-FIXES / NEEDS-CHANGES** and one line of rationale, then: must-fix (deduped, cross-confirmed, by severity, with file:line + fix), should-fix/over-claims, security (if run), local-verification results (reproduced map + pathway timings), and the staging call.

Rules of thumb: failing test, real security finding, or a **reproduced** bug → needs-changes; cross-confirmed correctness bugs not locally reproducible still lean needs-changes (say so honestly); flagged-but-not-reproduced → merge-with-fixes or noted non-issue; only minor/over-claim/perf-nits → merge-with-fixes; nothing of substance → go. Reproduction beats assertion — weight what the running system did over what a reviewer inferred.
