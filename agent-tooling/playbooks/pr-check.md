# Playbook: PR quality gate

An agent-neutral procedure for vetting a pull request and ending with one verdict. It is **adaptive**: cheap checks always run; expensive ones run only when the diff warrants them. This is the *method*; a per-agent adapter supplies the triggering, the concrete orchestration, and a per-project config with the repo-specific values.

## Inputs

- The diff under review (current branch vs the base, or a named PR).
- A **project config** (e.g. `.claude/pr-check.json`) supplying repo-specific values: the `base_ref`, scope globs, sensitive-content patterns, the `test_command`, the runtime-verification mechanism, and the human-staging mechanism. The procedure never hardcodes these — if the config is missing, say what's needed.

## Operating rules

- **Read-only.** Assess, don't fix or push.
- **Concurrency-safe.** Analyze committed refs; if you need a clean checkout, use a throwaway worktree, never the main one.
- **Reuse existing reviewers/runners** the host environment already provides rather than reimplementing them.
- **Deterministic before subjective.** Anything with a right answer runs as a check, not as a reviewer. The panel exists for questions that need a point of view — and for naming the checks we are still missing.
- **The panel sets the price, not the diff** [confirmed, 19 runs: UI-scoped ~890k subagent tokens vs ~320k for a single-language scope; a 62-line and a 262-line diff both ~328k]. Narrow scope globs are the cheapest lever; no panel at all on a diff that warrants none is cheaper still.

## Steps

**0. Scope.** Compute the changed files and scope flags (run the bundled `scope.py` with the project config). Flags typically include doc-only, templates/CSS, JS, DB/migrations, ops/deploy, backend logic, sensitive (auth/proxy/secret/SQL), and runtime (user-facing flows). Doc-only → skip to a light prose/accuracy pass and the verdict.

**1. Deterministic gate — no model in it.** Run everything that has a right answer: the project's `test_command`, linters, type checks, the repo's own guards, a secret scan, and any `sensitive_patterns` sweep over the diff. **A red gate caps the verdict at *needs-changes* and the panel does not convene** — the fix comes first, and a whole panel run is saved rather than made cheaper. Record what ran and what it said; that record is the panel's evidence in step 3.

**2. Evidence pack — a floor, not a ceiling.** Assemble once, for everyone: the diff, the files it touches, the gate's output, and the scope flags. It exists so that N reviewers do not each re-derive the same context; it does **not** replace exploration.

Measured on a real 449-line PR [confirmed, 2026-09-23, wiki-polis #450]: of 31 panel findings, **25 required reading outside the diff**, including 4 of the 7 must-fix findings — an RTL precedent found only by reading the stylesheet, a whole-component read that exposed an aria-label hiding its visible label, a tree-wide glyph grep, and a fallback constant in the backend that made a new test vacuous. A pack-only panel would have missed them. **Restricting reviewers to the pack buys tokens and pays in defects.**

So: give every reviewer cheap read access (file read, grep/glob over the tree, `git log`/`git show` on a pinned ref) and an explicit exploration budget in the prompt — e.g. "up to ~10 targeted reads/searches; say what you opened and why". Cost control comes from (a) the shared pack removing *duplicated* reads, (b) the cache hits a shared prefix produces, and (c) scope, not from blindfolding the panel. Record `evidence=diff|repo` per finding so this stays measured rather than assumed.

**3. Expert panel + cross-review — the subjective part only.** Convene reviewers matched to the scope flags (a generalist always; plus accessibility/usability for UI, frontend for JS, database for schema/migrations, ops for deploy). Scope picks **viewpoints**, not file types: the question is whose perspective this change needs.

A reviewer is there for what has no right answer — is this the right abstraction, will a user understand this wording, does this design survive the next change, what does this look like to someone who reviews for security. **Write reviewer prompts as viewpoints, never as checklists:** any checklist item a tool could answer belongs in step 1, and a reviewer running it is a linter with worse precision at a far higher price.

Run them in parallel, then a **cross-review** round where each confirms / disputes / supplements the others (this kills false positives and surfaces gaps), then synthesize. Scale to the change.

**3b. Gate proposals — the panel's second output.** Reviewers also name the *objective* questions the gate missed: "this should have been caught by a check". Each proposal names the check, what it would have caught here, and where it belongs (test, lint rule, guard, scope pattern). These are recorded in the verdict as a separate list and become gate work, so the same judgment is never bought twice. A finding a reviewer had to reason out once is a finding a check should own forever.

**4. Security review (conditional).** Only if the *sensitive* flag fired. A real security finding caps the verdict at *needs-changes*.

**5. Targeted local verification (conditional).** Run if the *runtime* flag fired, or if steps 1/3/4 produced a behavioral finding worth reproducing. This is **not** a canned full regression run — it's surgical:
   - **(a) Reproduce flagged bugs.** Reviewers found bugs by *reading*; here, drive the concrete trigger on a running stack and record reproduced / not-reproduced / n/a. Style/naming/pure-semantics findings can't be reproduced — they stand on the review alone. A reproduction can be cheap and decisive (e.g. a parse check proving an inline script is dead) — it need not be a full stack spin-up.
   - **(b) Exercise + time the touched pathways.** Confirm behavior and capture basic performance (response time, obvious N+1 / extra-round-trip / slow-fallback signs). Performance matters: regressions hide in fallback paths that all unit tests pass through.
   Reproduced → hard blocker. Asserted-but-not-reproducible → downgrade to "flagged, not reproduced." Slow-but-correct → call it out with timing.

**6. Human-staging recommendation.** Advise a person-driven staging pass when: the change hits live-backend behavior local verification can't reproduce; it's an accessibility/screen-reader change needing human judgment; the runtime flag fired but step 5 was skipped/failed; or it changes irreversible/identity-exposing flows. Otherwise state plainly that none is needed.

## Verdict

End with **GO / MERGE-WITH-FIXES / NEEDS-CHANGES** and one line of rationale, then: must-fix (deduped, cross-confirmed, by severity, with file:line + fix), should-fix/over-claims, security (if run), local-verification results (reproduced map + pathway timings), **gate proposals from step 3b** (check → what it would have caught → where it belongs), and the staging call.

**Persist it as a handoff.** Besides reporting in-conversation, write the verdict to a predetermined, git-ignored folder in the project (a `report_dir`), as a file keyed by PR id or branch. It must stand alone for a reader with zero session context (PR id + head SHA, scope, test result, must-fix with file:line + fix, reproduced-vs-flagged, staging call) — so the next agent or a human can act on it cold.

Rules of thumb: failing test, real security finding, or a **reproduced** bug → needs-changes; cross-confirmed correctness bugs not locally reproducible still lean needs-changes (say so honestly); flagged-but-not-reproduced → merge-with-fixes or noted non-issue; only minor/over-claim/perf-nits → merge-with-fixes; nothing of substance → go. Reproduction beats assertion — weight what the running system did over what a reviewer inferred.
