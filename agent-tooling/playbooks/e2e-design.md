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
  (A new suite has none of these; see "Two modes" below.)
- How the app starts, and what it talks to that you do not own.
- A per-project config naming the e2e command, the spec directory, where notes go, and the CI
  provider. The procedure never hardcodes these.

## Two modes

- **NEW** — no suite yet, or one new journey to cover. Run parts 1 and 2. There is nothing to
  measure, so **skip** the suite-shape, flake-history and cost-before measurements, and **omit**
  the flake-ledger and deletions sections of the output; say in the output that they were
  skipped because the suite did not exist.
- **RE-THINK** — a suite exists and has drifted. Run part 3 first, then parts 1 and 2 for what
  it exposes.

## Part 1 — choose the routes

1. **List journeys, not pages.** A journey is one user intent, start to finish: "a participant
   joins a room from an invite link and submits a statement". Pages and components are where
   cheaper tiers live.
2. **Rank by blast radius x traffic.** Cover the paths whose breakage is unrecoverable
   (payment, identity, consent, data submission) and the paths almost everyone walks. A rarely
   used, easily retried flow does not earn an end-to-end test.
3. **Cap the set deliberately.** E2E is the most expensive tier per assertion; a good suite is
   a handful of journeys that are *always* green, not fifty that are usually green. Write the
   cap down, so adding a journey is a decision rather than a reflex. **Default when the project
   has none: 5–10 journeys, or a per-PR runtime budget of 5 minutes, whichever binds first**
   [a starting default, not a measured optimum — replace it with the project's own numbers].
4. **Push everything else down a tier.** If an assertion can be made by a unit or integration
   test, that is where it belongs: same coverage, a fraction of the runtime, and a far better
   failure message. Duplicate assertions across tiers are pure cost.
5. **Name the journeys nobody covers.** The output of this step is both the list to build and
   the list you consciously decline.

## Part 2 — build each one so it stays honest

- **Assert what the user perceives**, through accessible roles and names — the button *named*
  "Join", the status region that announces the result. Selectors tied to CSS classes or DOM
  structure test the implementation and break on every refactor. Using accessible names also
  turns each test into a small accessibility check for free.
  - **But an accessible name is content.** Copy edits, translations, right-to-left locales and
    two controls with the same name all break it. Keep role + name as the default; **fall back to
    a stable test id** when the name is expected to change for reasons unrelated to the journey
    (marketing copy, per-locale runs), when the same name legitimately appears more than once, or
    when the element has no user-facing name. Resolve ambiguity by scoping to a region (the
    dialog, the row) before reaching for a test id.
  - **Locators must match exactly one element.** Frameworks with a strict mode fail a locator
    that resolves to several; do not silence that with "first match" — it means the test cannot
    say which control the user would have pressed.
- **One intent per spec, with its own seeded data.** Explicit fixed ids per spec, created fresh,
  so specs cannot leak state into each other and can run in any order.
  - **Fixed ids are only safe with per-worker isolation.** Once specs run in parallel workers or
    CI shards, two workers seeding "room 42" collide. Give each worker its own database or schema,
    or namespace every seeded id by the worker/shard index. Without one of those, fixed ids turn
    parallelism into flakiness.
- **Set up state through the fastest honest door.** Seed the database or call the API to reach
  the precondition; drive the UI only for the part under test. Logging in through the UI in
  every spec buys nothing after the first spec that tests logging in.
  - **Keep that first spec.** At least one spec must **authenticate through the real UI**, and at
    least one must **exercise the real validation path** (submit bad input through the form and
    see the user-facing error). Seeding via API or database otherwise retires the login and
    validation paths silently: every spec is green and nothing proves a user can sign in.
- **No fixed waits as synchronisation.** Wait on a condition the app actually reaches (an
  element, a response, a state change). Ban fixed-duration sleeps as a way to *wait for*
  something: they are simultaneously the slowest and the flakiest way to synchronise. The one
  legitimate time-based assertion is a **negative** one ("no second request is sent", "the toast
  does not appear"); state its budget explicitly and keep it bounded — "within 500 ms, because the
  debounce is 300 ms" — rather than an unexplained pause.
- **Shorten real waits through configuration, not fakery.** Where the product has deliberate
  delays (debounces, polls, nudges), give the test environment a config block that reduces them
  to milliseconds, so the real timers still drive the real code. One project cut its suite from
  ~9.5 minutes to under one this way [confirmed, 2026-09-23, reported from that repo's workflows
  and config; `agent-tooling/lessons.md` → "The cheapest readiness gate is not having one"].
- **Decide the hermetic boundary explicitly.** Stub third-party services at the network edge
  unless the integration *is* the thing under test. A suite that calls live services inherits
  their latency and their outages, and then needs credentials, low concurrency and long
  timeouts to survive — the same project pays that price today: 2 workers, a 180 s per-test
  timeout and a credential to run at all [confirmed, 2026-09-23, same lessons entry].
  - **Pair every stub with a contract check.** A stub freezes the provider as it was the day
    you recorded it. Add a **non-blocking nightly job** that runs the same calls against the live
    provider (or refreshes the recorded cassettes and diffs them) and alerts on drift, so the
    per-PR suite stays hermetic without going blind to a changed API.
- **Start the app the cheapest deterministic way.** A single-process app can be started
  in-process on an ephemeral port, which removes health checks and polling entirely: the setup
  either resolves or throws. A container stack cannot, so it needs compose, pinned images and a
  readiness endpoint — take the principle (deterministic startup), not the shortcut.
  - **"Listening" is not "ready".** Caches, compiled templates, connection pools and background
    workers may still be warming after `listen()` resolves; the first spec then pays for it, or
    times out. Warm up explicitly (one request to a representative route) before the suite starts.
  - **A random-port localhost origin breaks origin-sensitive features.** Cookies with `Domain`,
    `Secure` or `SameSite` attributes, OAuth redirect URIs registered for a fixed origin, CSP and
    CORS allow-lists, service-worker scope, and websocket origin checks can all behave differently
    on `http://127.0.0.1:<random>`. Either configure the test environment for that origin
    explicitly, or cover those features in a spec that runs against a fixed, production-shaped
    origin.
- **Make failures diagnosable without a re-run:** trace on first retry, screenshot on failure,
  video retained on failure, and the build identifier of what was tested in the run summary.
- **A pass after a retry is a flake, not a pass.** Record every test that needed a retry to go
  green, with its name and the run, in the run summary or a results file. That record is where
  part 3's flake ledger gets its data; a retry policy that reports only the final green erases it.

### Also decide, and write down

Each of these is a choice the suite makes whether or not anyone makes it on purpose:

- **Data cleanup** — teardown per spec, per worker, or a disposable database per run.
- **Auth-state fixtures and the role matrix** — which roles (anonymous, member, moderator,
  admin) each journey runs as, and how their session state is prepared and reused.
- **Quarantine policy** — a quarantined test gets an expiry date and a named owner; at expiry
  it is fixed or deleted, never renewed silently.
- **Clock, timezone and randomness** — a fixed clock and timezone and seeded randomness for any
  date-driven flow (deadlines, "3 days ago", end-of-month), so the suite does not fail on
  particular days.
- **Locale coverage** — which locales run, including at least one right-to-left locale if the
  product ships one.
- **Viewport and browser matrix** — which viewports and engines are per-PR and which nightly.
- **Visual regression** — included (with its baseline-update rule) or explicitly declined.
- **Merge blocking** — whether a red per-PR suite blocks merge, and who may override it.

## Part 3 — the periodic re-think

Run this when the suite's runtime, flake rate, or the product's shape has drifted — quarterly is
a reasonable default; after any incident the suite did not catch is a better trigger.

1. **Journey coverage, not line coverage.** Put the current journey list beside the current
   specs. Which journeys have no test? Which specs correspond to no journey anyone walks?
2. **Would each test fail if the feature broke?** Break the implementation (delete or mutate
   it) for a sample and check the test goes red **with the failure message it claims to guard**
   — an unrelated red (a crash in setup, a missing fixture) proves nothing. A green test over
   broken code is worse than no test, because it is trusted. Nothing in CI does this for you.
   - **Default sample:** the top 3 journeys by blast radius plus 2 other specs chosen at random
     (all specs if there are 5 or fewer) [a starting default, not a measured optimum].
   - **Consent and isolation.** Deliberately breaking code needs the user's explicit yes first,
     and runs only in a **throwaway worktree**, never the user's checkout; remove the worktree
     afterwards.
   - **Its blind spot:** this cannot detect an over-mocked spec. If the spec stubs the very
     component you broke, it stays green for the wrong reason and looks like a failure of the
     technique rather than of the spec. Check what each sampled spec mocks before trusting a
     green-over-broken result either way.
3. **Flake ledger.** Every test that retried or failed spuriously in the last 30 days, with a
   count (from the pass-after-retry records above). Fix, quarantine or delete — a flaky test
   trains the team to ignore red.
4. **Cost per merge.** Runtime x runs per day. Decide again what runs per PR, what runs nightly
   or weekly, and what is opt-in. A per-PR suite that people skip is not a gate.
5. **Ask what changed in the product.** New flows, removed features, changed defaults. Specs
   outlive the features they were written for.
6. **End with deletions.** The pass must name specs to delete, merge or move down a tier, as
   well as journeys to add. A re-think that only adds has not thought.

## Output

A short document in the project's notes area: the journey list (covered / declined, with
reasons), the cap, the hermetic boundary and its contract checks, the tier split (per-PR /
nightly / opt-in), the "also decide" choices, and — in RE-THINK mode only — the flake ledger,
the delete-the-feature results, the deletions made, and what the suite cost before and after.
Date it, so the next pass starts from evidence rather than from opinion. The notes area must not
be tracked by git; if it is, stop and ask where to write.
