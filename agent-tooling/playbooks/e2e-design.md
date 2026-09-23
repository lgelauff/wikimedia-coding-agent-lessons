# Playbook: designing end-to-end interaction tests

An agent-neutral method for deciding **which** end-to-end journeys a project should have, how
each one is built so it stays fast and honest, and how to re-audit the set when it drifts. It is
about the *design* of the suite. Running a browser to verify one change is `browser-verify`;
deciding whether a PR is mergeable is `pr-check`.

The failure this prevents is not a missing test. It is a suite that grows by accretion — one
spec per feature, each asserting the implementation that existed the day it was written — until
it is slow, flaky, and still silent on the three journeys that actually matter.

## Inputs

- The product's **real user journeys** (from analytics, server logs, support reports, or the
  team's own account of what people do). Not the sitemap, and not the feature list.
- The current suite: spec files, runtime, retry/flake history, what the last real incidents were.
- How the app starts, and what it talks to that you do not own.

## Part 1 — choose the routes

1. **List journeys, not pages.** A journey is one user intent, start to finish: "a participant
   joins a room from an invite link and submits a statement". Pages and components are where
   cheaper tiers live.
2. **Rank by blast radius x traffic.** Cover the paths whose breakage is unrecoverable
   (payment, identity, consent, data submission) and the paths almost everyone walks. A rarely
   used, easily retried flow does not earn an end-to-end test.
3. **Cap the set deliberately.** E2E is the most expensive tier per assertion; a good suite is
   a handful of journeys that are *always* green, not fifty that are usually green. Write the
   cap down, so adding a journey is a decision rather than a reflex.
4. **Push everything else down a tier.** If an assertion can be made by a unit or integration
   test, that is where it belongs: same coverage, a fraction of the runtime, and a far better
   failure message. Duplicate assertions across tiers are pure cost.
5. **Name the journeys nobody covers.** The output of this step is both the list to build and
   the list you consciously decline.

## Part 2 — build each one so it stays honest

- **Assert what the user perceives**, through accessible roles and labels — the button *named*
  "Join", the status region that announces the result. Selectors tied to CSS classes or DOM
  structure test the implementation and break on every refactor. Using accessible names also
  turns each test into a small accessibility check for free.
- **One intent per spec, with its own seeded data.** Explicit fixed ids per spec, created fresh,
  so specs cannot leak state into each other and can run in any order.
- **Set up state through the fastest honest door.** Seed the database or call the API to reach
  the precondition; drive the UI only for the part under test. Logging in through the UI in
  every spec buys nothing after the first spec that tests logging in.
- **No sleeps.** Wait on a condition the app actually reaches (an element, a response, a state
  change). Ban fixed-duration waits outright: they are simultaneously the slowest and the
  flakiest way to synchronise.
- **Shorten real waits through configuration, not fakery.** Where the product has deliberate
  delays (debounces, polls, nudges), give the test environment a config block that reduces them
  to milliseconds, so the real timers still drive the real code. One project cut ~9.5 minutes to
  under one this way.
- **Decide the hermetic boundary explicitly.** Stub third-party services at the network edge
  unless the integration *is* the thing under test. A suite that calls live services inherits
  their latency and their outages, and then needs credentials, low concurrency and long
  timeouts to survive — a real project pays exactly that price today.
- **Start the app the cheapest deterministic way.** A single-process app can be started
  in-process on an ephemeral port, which removes health checks and polling entirely: the setup
  either resolves or throws. A container stack cannot, so it needs compose, pinned images and a
  readiness endpoint — take the principle (deterministic startup), not the shortcut.
- **Make failures diagnosable without a re-run:** trace on first retry, screenshot on failure,
  video retained on failure, and the build identifier of what was tested in the run summary.

## Part 3 — the periodic re-think

Run this when the suite's runtime, flake rate, or the product's shape has drifted — quarterly is
a reasonable default; after any incident the suite did not catch is a better trigger.

1. **Journey coverage, not line coverage.** Put the current journey list beside the current
   specs. Which journeys have no test? Which specs correspond to no journey anyone walks?
2. **Would each test fail if the feature broke?** Delete the implementation (or mutate it) for
   a sample and check the test goes red. A green test over broken code is worse than no test,
   because it is trusted. Nothing in CI does this for you.
3. **Flake ledger.** Every test that retried or failed spuriously in the last 30 days, with a
   count. Fix, quarantine or delete — a flaky test trains the team to ignore red.
4. **Cost per merge.** Runtime x runs per day. Decide again what runs per PR, what runs nightly
   or weekly, and what is opt-in. A per-PR suite that people skip is not a gate.
5. **Ask what changed in the product.** New flows, removed features, changed defaults. Specs
   outlive the features they were written for.
6. **End with deletions.** The pass must name specs to delete, merge or move down a tier, as
   well as journeys to add. A re-think that only adds has not thought.

## Output

A short document in the repo: the journey list (covered / declined, with reasons), the cap, the
hermetic boundary, the tier split (per-PR / nightly / opt-in), the flake ledger, and the
deletions made. Date it, and record what the suite cost before and after — so the next pass
starts from evidence rather than from opinion.
