---
name: browser-verify
description: >-
  Find out whether a page actually works, by driving a real headless browser. Use
  whenever someone reports UI behaviour and wants it confirmed or disproved — "the
  arguments tab is blank on staging", "is this fix live", "did that break
  anything", "test the UI locally", "confirm this bug still reproduces" — or hands
  you specific things to try in the running app. Use it INSTEAD of reading the
  code and reasoning about it: inspecting the source is the obvious move and it
  cannot tell you what the browser did, because the failures that reach a user are
  the ones the code looks fine for — a silent JS error, a route that renders
  unstyled, a cached bundle. This reproduces or verifies in headless Chromium and
  checks the adjacent paths a fix most plausibly broke. Lighter than a full PR
  gate; pairs with pr-check's local-verification step.
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

For a **pure screenshot** (a screen or a bug, no assertions), skip the probe and call the shared helper: `python3 "$SKILL_DIR/../../scripts/capture.py" --url <route> --out shot.png [--login dev-user-1] [--clip SELECTOR] [--viewport 390x844] [--dark]`. Same shot logic as this template, factored out so other skills share it; saves the PNG + a sidecar with console errors / final URL / sha256.

## 4. Verdict (playbook step 4)

Report each check as CONFIRMED / FIXED-AND-CLEAN / REGRESSION / COULD-NOT-RUN, with evidence (assertion text, console dump, `probe.png`). State explicitly whether the risky-path / user-supplied checks passed — that's the "no side damage" finding. One-line overall verdict. Trust the browser over the code.

## 5. Optionally post screenshots to the PR

The probe already screenshots each screen it drives. If the user wants those on the PR (only when asked — never automatically), label the **relevant** ones and use the bundled poster. It pushes images to a `pr-screenshots` assets branch (PR branch stays clean) and embeds their raw URLs in a comment; **public repos only**.

```bash
python3 "$SKILL_DIR/../../scripts/post_pr_screenshots.py" --pr <N> \
  --intro "browser-verify on <what>" \
  --image "Arguments tab=probe-args.png" --image "Vote flow=probe-vote.png"
```
It **dry-runs by default** (prints the comment, touches nothing). Show that to the user; add `--confirm` to actually push + comment **only after they approve** — this both pushes to the remote and posts a public comment.

Memory note: headless keeps this light, but it still launches Chromium — if OS memory pressure is critical, free memory or `/compact` first (the memory_guard hook only gates fan-outs, not this).
