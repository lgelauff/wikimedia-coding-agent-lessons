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

## 6. Visual evidence (screenshots)

**Habit: any UI-observable change carries a screenshot — in the PR and in the issue/bug report, not just chat.** The tooling makes this cheap and headless (no computer takeover):

- `scripts/capture.py` — render a route/state → PNG + sidecar `.json` (console errors, final URL, sha256). The shot helper other skills call; it does not manage the stack, assert, or post.
- Chain: `local-e2e` (serve) → `capture.py` (shoot) → `post_pr_screenshots.py` (publish to PR).
- Posting to GitHub stays opt-in + confirmed (`post_pr_screenshots.py` dry-runs by default). Never auto-post.

## 7. Versioning and registration

Two failure modes this repo has actually hit, both silent:

**A stale version withholds work from every consumer.** The plugin cache is keyed by
version, and `plugin.json`'s value silently overrides the marketplace entry's. Between
2026-08-01 and 2026-08-19 the version sat at 0.9.1 while three new skills landed, so no
session ever saw them. **Bump `plugin.json` on every release**, never set `version` in
both places, and let `scripts/check_version_bump.py` enforce it from `pre-push`.

**Docs and tree drift apart in both directions.** A README once advertised a skill
called deep-research that did not exist, while `source-connectors` and
`latex-change-review` existed and were named nowhere. `scripts/check_registration.py`
checks both directions plus relative links. Run it from `pre-push`.

## Open items

*(The foundation-phase items — marketplace manifest, install model, migrating `pr-check`
as the reference skill — all shipped in June 2026 and were removed from this list on
2026-08-20. The marketplace now carries six plugins.)*

- **No skill has an eval.** §4 above requires `skill-creator` evals for skills with
  verifiable output, and a documented dry-run for subjective ones. Neither exists for any
  skill in this repo — a rule with a 100% violation rate. Nothing measures whether a
  skill fires when it should, or whether overlapping skills crowd each other.
