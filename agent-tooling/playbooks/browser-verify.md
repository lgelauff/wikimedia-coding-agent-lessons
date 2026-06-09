# Playbook: browser-verify

Agent-neutral procedure for verifying a change in a **real headless browser** — confirm a bug exists, or verify it's gone *and* nothing on the risky adjacent paths broke. Drives headless Chromium via Playwright. An adapter (e.g. a Claude skill) supplies the host-specific wiring.

The point: unit tests and code review reason *about* the code; this runs it. The decisive signal is what the browser actually does — including **console errors / page exceptions**, which reveal JS that silently never executed (a dead `<script>` looks identical to a working one in a diff).

## Step 1 — Build the test plan (merge auto + user input)

The plan is a list of concrete CHECKS, from three sources:
1. **User-supplied items** (always included, first-class) — whatever the operator explicitly wants verified ("confirm voting still submits", "circle nav reachable by keyboard", "no console errors on the arguments tab"). If none were given, offer the chance to add some before proceeding.
2. **The claim under test** — derived from the change/bug: the one behavior to confirm or refute. State it as a falsifiable check.
3. **Risky adjacent paths** — what this change could break as collateral (the "side damage" check). Use the project's scope/runtime mapping + the diff to pick 1–3 neighbors that share code or state with the change.

Output the plan explicitly before touching the browser, so the operator can adjust.

## Step 2 — Bring the app up

Use the project's own way to serve the stack (config `browser.serve` / the e2e mechanism) — don't reinvent it. Record the base URL. If the stack can't come up, stop and say so; don't pretend a browser check happened.

## Step 3 — Probe (headless)

Write a focused probe (one per flow, or one with many checks) from the Playwright template. Rules that matter:
- **Headless Chromium** — light, no GUI, no desktop-browser memory cost.
- **Always attach console / pageerror / requestfailed listeners** — console errors are failures, not noise. This is the highest-value signal.
- **Wait on locators or `domcontentloaded`, never `networkidle`** — some pages hold a connection open and never idle.
- Each check records pass/fail + evidence (assertion message, console dump, screenshot).
- Drive the real affordances a user would (click the visible control), not internal hooks.

## Step 4 — Verdict (per item)

For each check report one of:
- **CONFIRMED** — the bug reproduces in the browser (hard blocker).
- **FIXED-AND-CLEAN** — the previously-broken behavior now works, no console/page errors.
- **REGRESSION** — a risky-path or user-supplied check failed, or new console errors appeared (the fix caused side damage).
- **COULD-NOT-RUN** — stack/Playwright unavailable; say so, don't infer.

Weight what the browser did over what the code seemed to say. End with a one-line overall verdict and the evidence (screenshot path, console errors). If side-damage checks all passed, state that explicitly — "no regressions on the risky paths checked: X, Y."
