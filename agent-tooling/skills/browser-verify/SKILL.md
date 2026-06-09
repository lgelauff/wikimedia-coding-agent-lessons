---
name: browser-verify
description: >-
  Verify a change in a real HEADLESS browser: figure out what to look for, drive
  headless Chromium with Playwright, and either confirm a bug still reproduces or
  verify it's fixed AND that nothing on the risky adjacent paths broke. Use
  whenever the user wants to "check this fix in the browser", "confirm/repro this
  bug headlessly", "test the UI locally", "did the fix work and break anything",
  "run a headless browser test", "verify the arguments tab / voting / a page
  works", or hands you specific things to test in the running app. Prefer this
  over a screenshot or a code-only review when the question is "does it actually
  behave correctly in a browser?". Lighter than a full PR gate; pairs with
  pr-check's local-verification step.
---

# browser-verify — headless browser verification

Claude Code adapter over the agent-neutral **browser-verify playbook**. The method lives in the playbook; this file is the Claude-specific wiring.

Read the playbook: [`../../playbooks/browser-verify.md`](../../playbooks/browser-verify.md). Follow its steps 1–4 and verdict labels.

## Inputs

Accept, in priority order:
- **User-supplied checks** (args or ask) — explicit things to verify. *Always offer this up front*: "Anything specific you want tested? (e.g. 'voting still submits', 'circle nav by keyboard')." Include every one as a first-class check.
- **A PR number / bug description / the current diff** — to auto-derive the claim under test and the risky adjacent paths.

## 1. Plan (playbook step 1)

Combine the user's items + the auto-derived claim + 1–3 risky neighbors into an explicit CHECK list. Use the project config (`.claude/pr-check.json`, same file pr-check uses) for the scope→risky-path mapping. Print the plan and let the user adjust before launching the browser.

## 2. Serve (playbook step 2)

Read the config's `browser` block: `{ base_url, serve, playwright }`. Bring the stack up via `serve` (for wiki-polis that's the `local-e2e` skill — reuse it for the stack lifecycle). Note the real base URL it reports.

## 3. Prereqs + probe (playbook step 3)

Ensure Playwright is present (once):
```bash
python3 -c "import playwright" 2>/dev/null || pip install playwright
python3 -c "import playwright" && playwright install chromium
```
Copy [`references/playwright-template.py`](references/playwright-template.py) to a scratch `probe.py`, set `BASE_URL`, and fill one `check(...)` per plan item (login/navigate in SETUP). Keep the console/pageerror/requestfailed listeners — console errors are failures. Wait on locators, never `networkidle`. Run headless:
```bash
python3 probe.py    # exit 0 = all checks pass + no console/page errors
```
Allowlist `Bash(python3 *probe.py*)` and `Bash(playwright install*)` to keep it prompt-free.

## 4. Verdict (playbook step 4)

Report each check as CONFIRMED / FIXED-AND-CLEAN / REGRESSION / COULD-NOT-RUN, with evidence (assertion text, console dump, `probe.png`). State explicitly whether the risky-path / user-supplied checks passed — that's the "no side damage" finding. One-line overall verdict. Trust the browser over the code.

Memory note: headless keeps this light, but it still launches Chromium — if OS memory pressure is critical, free memory or `/compact` first (the memory_guard hook only gates fan-outs, not this).
