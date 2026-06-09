---
name: pr-check
description: >-
  Full PR quality-gate: scope the diff, run the project's tests, convene a
  type-matched panel of expert review agents with a cross-review round,
  conditional security review and targeted local verification, then a final
  go / merge-with-fixes / needs-changes verdict plus a call on whether a human
  staging test is warranted. Use whenever the user asks to "check this PR",
  "quality-check before merge", "run the PR gate", "is this ready to merge",
  "vet this branch", "/pr-check", or wants a consolidated go/no-go on a branch
  or PR — even if they don't name a specific check. Prefer this over running a
  code review or the test suite alone when the ask is "is this good to merge?".
---

# pr-check — Claude Code adapter

This is the Claude Code adapter over the agent-neutral **PR quality-gate playbook**. The method lives in the playbook; this file supplies Claude-specific wiring (config discovery, the `scope.py` call, the Workflow-based panel, and which existing skills to reuse).

## 1. Read the method

Read the playbook: [`../../playbooks/pr-check.md`](../../playbooks/pr-check.md). It defines steps 0–6 and the verdict rules. Follow it; the notes below are only the Claude-specific *how*.

## 2. Load the project config

Read `.claude/pr-check.json` in the **consuming repo** (schema: [`pr-check.example.json`](pr-check.example.json)). It supplies `base_ref`, scope globs, sensitive patterns, `test_command`, reviewer map, `a11y_spec`, `e2e_skill`, `staging_skill`. **If it's missing, stop and offer to create one from the example** — do not hardcode another repo's values.

## 3. Scope (playbook step 0)

Run the bundled script once instead of ad-hoc pipelines — it lives two levels up from this skill, at the plugin's `scripts/scope.py`:
```bash
python3 "$SKILL_DIR/../../scripts/scope.py" --config .claude/pr-check.json [--pr N | --base <ref>]
```
(`$SKILL_DIR` = this skill's directory. Allowlist `Bash(python3 *agent-tooling/scripts/scope.py*)` to make it prompt-free.)
It returns `{files, flags}`. Branch on the flags for the rest.

## 4. Review, tests, panel (steps 1–3)

- **Step 1:** `/code-review high` (never `/code-review ultra` — billed/user-only; *suggest* it in the verdict for high-risk changes).
- **Step 2:** run the config's `test_command`. Red suite → caps at needs-changes.
- **Step 3:** the expert panel + cross-review via the **Workflow** tool. Adapt [`references/panel-workflow.js`](references/panel-workflow.js): set `ROLES` from the config's reviewer map for the flags that fired (a generalist always), point all agents at a **pinned ref or worktree** (not the live tree, which may have concurrent edits), and pass the changed files.

## 5. Conditional steps (4–6)

- **Security (step 4):** only if `SENSITIVE`. Run `/security-review`.
- **Local verification (step 5):** if `RUNTIME` or any reproducible finding. Use the config's `e2e_skill` for stack lifecycle, but feed it the **finding-driven plan** from step 5, not generic happy-path flows. Reproduction can be cheap (e.g. `node --check` on an extracted inline script) — don't spin up the full stack when a parse/unit check is decisive.
- **Staging (step 6):** recommend the config's `staging_skill` per the playbook's criteria.

## 6. Verdict

Emit the playbook's verdict format. Be decisive; weight reproduced behavior over inferred findings.
