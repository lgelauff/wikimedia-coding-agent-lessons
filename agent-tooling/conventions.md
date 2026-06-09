# Authoring conventions (skills / scripts / hooks)

How to add reusable Claude Code automation here so it stays portable, reviewable, and quiet. Read before adding.

## 1. Portable core, project bindings

A reusable skill must run in **any** repo. The skill holds the *logic*; everything repo-specific is read from a per-project config in the consuming repo.

- **In the skill:** workflow, decision rules, orchestration, output format.
- **In the project config** (`.claude/<skill>.json` in the consuming repo): file globs, test/build commands, stack layout, doc paths — anything with a repo-specific value.
- If the project config is missing, the skill should say what's needed and how to create it — never hardcode a fallback to one repo.

**Test:** drop the skill into an unrelated repo — does it still make sense? If not, a project value leaked into the core.

## 2. Scripts over inline bash

Repeated shell logic goes in `scripts/`, not inline in a SKILL.md:

1. **Fewer permission prompts** — one vetted script = one narrow allowlist entry instead of N ad-hoc-pipeline prompts.
2. **Determinism + testability** — a script has one behavior and a test in `scripts/tests/`.
3. **Reviewability** — scripts diff cleanly.

Scripts: read-only unless mutation is the whole point (then say so loudly); no secrets (read from env); dependency-light; non-zero exit + clear message on failure.

## 3. Permission hygiene

See [`settings/allowlist.md`](settings/allowlist.md). The one rule that always holds: **never allowlist arbitrary code execution**; prefer exact invocations or bundled script paths.

## 4. Quality bar

- Scripts: a test in `scripts/tests/` (smoke test of exit code + output shape is fine).
- Skills with verifiable output: `skill-creator` evals. Subjective output (review verdicts): a documented dry-run on a real case beats fake assertions.
- Hooks: read secrets from env; keep them generic (no single-repo paths).
- Pair it with a lesson: if the solution exists because of a non-obvious gotcha, capture the gotcha in `lessons.md` and link the two.

## 5. Add-a-skill checklist

- [ ] `skills/<name>/SKILL.md` with a specific, pushy `description`.
- [ ] Repo specifics in a documented `.claude/<name>.json`, not hardcoded.
- [ ] Repeated bash extracted to `scripts/` + tests.
- [ ] No arbitrary-exec allowlist entries introduced.
- [ ] Validation noted (eval or dry-run); no secrets; no single-repo assumptions.

## Open items (foundation phase)

- Plugin/marketplace manifest (`.claude-plugin/`) so projects can install this — confirm the current schema against an installed plugin before writing it; don't guess.
- Install model: marketplace install (versioned, per-project opt-in) vs a dev symlink for live editing.
- Migrate `pr-check` as the reference skill proving the portable/binding split.
