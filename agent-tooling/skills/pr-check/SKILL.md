---
name: pr-check
description: >-
  Decide whether a branch or PR is actually ready to merge. Use whenever someone
  asks to check, vet, or quality-check a PR or branch, asks "is this ready",
  "should I merge this", "/pr-check", or wants a go/no-go — and equally when they
  describe the work instead of naming a check, as in "run the tests and look at
  the diff, tell me if it's good" or "vet PR 412 before I merge it". Use it
  INSTEAD of doing that by hand: running the suite and reading the diff yourself
  is the obvious move and it is the one that misses things, because a green suite
  says nothing about the changes it does not cover. This scopes the diff, runs the
  project's tests, convenes a type-matched panel of expert reviewers with a
  cross-review round, adds a security pass and targeted local verification when
  the diff warrants them, and returns a go / merge-with-fixes / needs-changes
  verdict plus a call on whether a human should test on staging.
---

# pr-check — Claude Code adapter

This is the Claude Code adapter over the agent-neutral **PR quality-gate playbook**. The method lives in the playbook; this file supplies Claude-specific wiring (config discovery, the `scope.py` call, the Workflow-based panel, and which existing skills to reuse).

## Command form — read this before running anything

A PR gate runs a lot of shell, and every *novel* pipeline costs the user an approval. Two rules are the difference between a handful of prompts and thirty.

**Never `cd <path> && git …`.** Claude Code flags that shape as able to execute untrusted hooks from the target directory, so it offers **no "Always allow"** — only Deny or Allow once. It will prompt every time, in every session, forever; no allowlist entry can ever silence it. Use the tool's own directory flag instead, which is allowlistable:

| Instead of | Use |
|---|---|
| `cd repo && git grep …` | `git -C repo grep …` |
| `cd repo && git show …` | `git -C repo show …` |
| `cd app && npx vitest …` | `npm --prefix app exec vitest …` |
| `cd d && pytest` | `pytest --rootdir d d` |
| `cd d && make x` | `make -C d x` |

**Prefer one script call to a pipeline.** `scope.py` (§3) already collapses the scoping step into a single allowlistable call. It does **not** cover the investigative half — extracting a failure, checking when a line changed, reading a changelog — and that is where prompts actually accumulate, because each improvised `… | grep -A18 … | head -30` is a distinct string no allowlist matches. If you catch yourself running the same *shape* a second time, that is the signal to put it in `scripts/` rather than run it again.

This is `conventions.md` §2 applied to the half of the job the scripts don't yet cover: *"one vetted script = one narrow allowlist entry instead of N ad-hoc-pipeline prompts."*

## 1. Read the method

Read the playbook: [`../../playbooks/pr-check.md`](../../playbooks/pr-check.md). It defines steps 0–6 and the verdict rules. Follow it; the notes below are only the Claude-specific *how*.

## 2. Load the project config

Read `.claude/pr-check.json` in the **consuming repo** (schema: [`pr-check.example.json`](pr-check.example.json)). It supplies `base_ref`, scope globs, sensitive patterns, `test_command`, reviewer map, `a11y_spec`, `e2e_skill`, `staging_skill`, `report_dir`. **If it's missing, stop and offer to create one from the example** — do not hardcode another repo's values.

## 3. Scope (playbook step 0)

Run the bundled script once instead of ad-hoc pipelines (the plugin exposes its root as `${CLAUDE_PLUGIN_ROOT}`):
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scope.py" --config .claude/pr-check.json [--pr N | --base <ref>]
```
(Allowlist `Bash(python3 *agent-tooling/scripts/scope.py*)` to make it prompt-free.)
It returns `{files, flags}`. Branch on the flags for the rest.

## 4. Review, tests, panel (steps 1–3)

- **Step 1:** `/code-review high` (never `/code-review ultra` — billed/user-only; *suggest* it in the verdict for high-risk changes).
- **Step 2:** run the config's `test_command`. Red suite → caps at needs-changes.
- **Step 3:** the expert panel + cross-review via the **Workflow** tool. Adapt [`references/panel-workflow.js`](references/panel-workflow.js): set `ROLES` from the config's reviewer map for the flags that fired (a generalist always), point all agents at a **pinned ref or worktree** (not the live tree, which may have concurrent edits), and pass the changed files.

## 5. Conditional steps (4–6)

- **Security (step 4):** only if `SENSITIVE`. Run `/security-review`.
- **Local verification (step 5):** if `RUNTIME` or any reproducible finding. Use the config's `e2e_skill` for stack lifecycle, but feed it the **finding-driven plan** from step 5, not generic happy-path flows. Reproduction can be cheap (e.g. `node --check` on an extracted inline script) — don't spin up the full stack when a parse/unit check is decisive. For visual/UI flows, run **`browser-verify`** (headless screenshots of the relevant screens). If the user wants those screenshots **on the PR**, browser-verify's step 5 posts them as a comment — opt-in and confirmed, never automatic.
- **Staging (step 6):** recommend the config's `staging_skill` per the playbook's criteria.

## 6. Verdict + handoff file

Emit the playbook's verdict format in chat. Be decisive; weight reproduced behavior over inferred findings.

Then **persist it as a handoff** so it survives the session and another agent can pick it up:
- Write the full verdict (the playbook's verdict structure — must-fix, security, local-verification, staging call, checklist) to `<report_dir>/pr-<N>.md` (or `<report_dir>/<branch>.md` when run on a branch), where `report_dir` comes from the config (default `.claude/pr-check`).
- Create the dir if needed (`mkdir -p`). It lives under `.claude/`, which is gitignored — confirm the consuming repo ignores it (don't commit handoffs).
- Make the file **stand alone for a cold reader**: PR id + head SHA, the scope flags, test result, must-fix with file:line + fix, what was reproduced vs only-flagged, and the staging recommendation — like a fresh agent would need with zero session context.
- Tell the user the path you wrote.

## 7. Record the run cost

If a panel workflow ran, log its cost tagged by PR type so "what does pr-check cost on this kind of PR" accrues empirically. Use the **real `subagent_tokens`** the Workflow result reported (not a guess), the scope flags from step 0, and the diff size:
```bash
python3 "$SKILL_DIR/../../scripts/record_run.py" --skill pr-check --pr <N> \
  --flags <comma-separated flags that fired> --diff-lines <changed lines> \
  --subagent-tokens <subagent_tokens from the workflow result> --duration-ms <duration_ms>
```
Skip `--subagent-tokens` (defaults 0) for a docs-only run with no panel. See accrued cost-by-PR-type with `scripts/cost_report.py [--rate <$/Mtok>]`, or a pre-run estimate with `cost_report.py --predict --flags … --diff-lines …`.
