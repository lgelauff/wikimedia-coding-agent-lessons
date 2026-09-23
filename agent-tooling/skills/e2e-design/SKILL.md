---
name: e2e-design
description: >-
  Design an end-to-end test suite, or re-think one that has drifted. Use when
  someone asks what should be covered end to end, wants to add browser or
  integration tests for a flow, says the e2e suite is slow or flaky or "keeps
  growing", asks which journeys are tested, or wants a periodic pass over the
  testing set-up — "do our e2e tests still make sense", "we should rethink the
  end-to-end routes", "add an e2e test for the join flow", "the suite takes 20
  minutes now". Use it INSTEAD of writing another spec next to the existing ones:
  adding one more test is the obvious move and it is how suites become slow,
  flaky and still silent on the journeys that matter, because coverage grows per
  feature while journeys go uncovered. This picks the journeys worth testing from
  what users actually do, builds each so it asserts what a user perceives rather
  than the implementation, sets the hermetic boundary and the tier split, and
  ends a re-think with deletions as well as additions. For running a browser to
  check one change use browser-verify; for a merge decision use pr-check.
---

# e2e-design — Claude Code adapter

Claude Code adapter over the agent-neutral **end-to-end design playbook**. The method lives in
the playbook; this file is the Claude-specific wiring.

Read the playbook first: `${AGENT_TOOLING_ROOT}/playbooks/e2e-design.md`. It defines the three
parts (choose the routes, build each one, the periodic re-think) and the output document.

## Which mode

Ask, or infer from the request:

- **NEW** — a project has no suite, or a new journey needs covering → playbook parts 1 and 2.
- **RE-THINK** — a suite exists and has drifted (slow, flaky, grew by accretion, missed an
  incident) → part 3 first, then 1 and 2 for whatever it exposes.

## 1. Gather the inputs — measure, do not assume

Do these before proposing anything; each is one command, and the numbers decide the design:

- **Suite shape:** count spec files and tests; total wall-clock for the last few CI runs
  (`gh run list`/`gh run view` if the repo is on GitHub); the slowest specs.
- **Flake history:** which tests retried or failed spuriously in the last 30 days.
- **Startup path:** how the app comes up in tests (in-process? compose? a live dependency?),
  and what it talks to that the project does not own.
- **Journeys:** ask the user for the real ones. Analytics or server logs beat anyone's memory,
  including theirs; if neither exists, say the list is `[guess]` and get it confirmed.

## 2. Propose, in the playbook's order

Journeys ranked by blast radius x traffic → the cap → the tier split (per-PR / nightly /
opt-in) → the hermetic boundary → the startup mechanism. Show the user the journey list,
including the journeys you are **declining** to cover and why, before writing any test.

## 3. Write or fix specs to the playbook's rules

Accessible roles and labels over CSS selectors; one intent per spec with its own seeded ids;
preconditions set through the API or the database, not by driving the UI; no fixed-duration
waits; product delays shortened by test config rather than a faked clock; trace/screenshot/video
on failure; the tested build identifier in the run summary.

## 4. The re-think's hard step

For a sample of specs, **break the feature and confirm the test goes red** — in a throwaway
worktree, never the user's checkout, and revert immediately. A green test over broken code is
the finding that matters most, and nothing in CI produces it. Report which specs passed this and
which did not.

## 5. Output

Write the playbook's output document to the repo's notes area (`.claude/` unless the project
says otherwise) — journey list covered/declined, cap, boundary, tier split, flake ledger,
deletions, and the suite's cost before and after. **Check the exact path is ignored at run time**
(`git check-ignore -q <path>`); some repos track parts of `.claude/`. Tell the user the path.

Deletions are part of the deliverable: a re-think that only adds tests has not thought. Propose
them; never delete a test without the user's explicit yes.

## Related

- `browser-verify` — drive a browser to check one change or bug (verification, not design).
- `pr-check` — the merge decision; its local-verification step reuses the suite this skill shapes.
