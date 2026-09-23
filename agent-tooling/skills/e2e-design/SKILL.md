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

## 0. Load the project config

Read `.claude/e2e-design.json` in the **consuming repo** (schema:
[`e2e-design.example.json`](e2e-design.example.json)): `e2e_command`, `spec_dir`, `notes_dir`,
`ci_provider`. **If it is missing, say so and offer to create one from the example**, filling in
what you can see in the repo and asking for the rest — do not assume GitHub, Playwright or a
`.claude/` notes folder.

## Which mode

Ask, or infer from the request:

- **NEW** — a project has no suite, or a new journey needs covering → playbook parts 1 and 2.
  **Skip** the suite-shape, flake-history and cost-before measurements below (there is nothing
  to measure), and **omit** the flake-ledger, delete-the-feature and deletions sections of the
  output. Say in the output that they were skipped and why.
- **RE-THINK** — a suite exists and has drifted (slow, flaky, grew by accretion, missed an
  incident) → part 3 first, then 1 and 2 for whatever it exposes.

## 1. Gather the inputs — measure, do not assume

Do these before proposing anything; each is one command, and the numbers decide the design.
In NEW mode only the last two apply.

- **Suite shape (RE-THINK):** count spec files and tests under `spec_dir`; total wall-clock for
  the last few CI runs, read through the configured `ci_provider` (for `github-actions`,
  `gh run list` / `gh run view`; for `none`, ask the user); the slowest specs.
- **Flake history (RE-THINK):** which tests retried or failed spuriously in the last 30 days.
- **Startup path:** how the app comes up in tests (in-process? compose? a live dependency?),
  and what it talks to that the project does not own.
- **Journeys:** ask the user for the real ones. Analytics or server logs beat anyone's memory,
  including theirs; if neither exists, say the list is `[guess]` and get it confirmed.

## 2. Propose, in the playbook's order

Journeys ranked by blast radius x traffic → the cap (the playbook's default of 5–10 journeys or
a 5-minute per-PR budget unless the project sets its own) → the tier split (per-PR / nightly /
opt-in) → the hermetic boundary and its nightly contract checks → the startup mechanism → the
playbook's "also decide" list. Show the user the journey list, including the journeys you are
**declining** to cover and why, before writing any test.

## 3. Write or fix specs to the playbook's rules

Accessible roles and names by default, a stable test id where the name is content that will
change or is ambiguous, and locators that match exactly one element; one intent per spec with
its own seeded ids, isolated per worker/shard; preconditions set through the API or the
database — except at least one spec that signs in through the real UI and one that exercises
real validation; no fixed waits as synchronisation, and an explicit bounded budget on any
negative assertion; product delays shortened by test config rather than a faked clock; an
explicit warm-up after the app starts; trace/screenshot/video on failure; retried passes
recorded as flakes; the tested build identifier in the run summary. Run specs with the config's
`e2e_command`.

## 4. The re-think's hard step (RE-THINK only)

For a sample of specs (default: the top 3 journeys plus 2 at random), **break the feature and
confirm the test goes red with the failure message it claims to guard** — any other red does
not count.

- **Ask first.** Deliberately breaking code needs the user's explicit yes in this conversation,
  naming which features you will break. No yes, no breakage.
- **Throwaway worktree only** (`git -C <repo> worktree add <tmp> <ref>`), never the user's
  checkout; remove it afterwards (`git -C <repo> worktree remove <tmp>`).
- Before trusting a result, check what the spec mocks: this cannot catch an over-mocked spec.

A green test over broken code is the finding that matters most, and nothing in CI produces it.
Report which specs passed this and which did not.

## 5. Output

Write the playbook's output document under the config's `notes_dir`. **Check the exact path is
ignored at run time** (`git check-ignore -q <path>`); some repos track parts of `.claude/`. **If
it is not ignored, stop and ask the user where to write** — do not write a tracked file and do
not pick another location yourself. Tell the user the path you wrote.

NEW mode omits the flake-ledger, delete-the-feature and deletions sections and says so.

Deletions are part of the deliverable: a re-think that only adds tests has not thought. Propose
them; never delete a test without the user's explicit yes.

## Related

- `browser-verify` — drive a browser to check one change or bug (verification, not design).
- `pr-check` — the merge decision; its local-verification step reuses the suite this skill shapes.
