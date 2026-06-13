# Permission framework

How Claude Code permissions are organized across this machine. Replaces the
ad-hoc per-repo allow-lists that had drifted (3 divergent GitHub guards, four
double-firing global hooks, ~300-entry allow-lists full of one-shot residue,
machine-wide `Read(//Users/**)`, and useful policies trapped in single repos).

Companion: [`allowlist.md`](allowlist.md) (the mechanics of writing an entry).

## Principles

1. **Three layers, each with one job** (below).
2. A permission lives at the **highest layer where it is still both safe and universal**. Everything else stays local.
3. **No arbitrary-exec allows** — exact patterns or bundled script paths only.
4. **Dynamic gating (ask/block) lives in plugin hooks, not static lists.**

## Decisions (2026-06-11)

- **Gating model: HYBRID.** Static allow-lists for safe routine ops; plugin hooks that *ask* on risky ops (writes/push/delete) and *block* the never-allowed (merge/close, ssh). dp's github-write hook is the reference for the `ask` pattern.
- **Read scope: PERMISSIVE (revised 2026-06-11).** Reads are low-risk — don't gate or ask on them; broad read allows are fine. The confirmation gate is NOT on reads but on **per-repo config setup** (writing/editing a repo's `.claude/settings.local.json`, `dev-stack.json`, `pr-check.json`): show the proposed config and get an explicit yes before it lands. (Supersedes the initial "tighten reads to GitHub/+/tmp" call.)
- **L1 baseline: LEAN.** Only universally-safe low-risk allows globally; everything else prompts or lives per-repo.

## The three layers

| Layer | Location | Holds | Does NOT hold |
|---|---|---|---|
| **L1 — Global baseline** | `~/.claude/settings.json` | universal low-risk allows (tightened read scopes, `gh run/workflow/job view`, `WebSearch`) + plugin enablement | any project specifics; any risky/destructive op |
| **L2 — Plugin policies** | `agent-tooling` (user-scope, applies everywhere) | the canonical gating hooks — ssh-block, github-write *ask*, merge/close *block*, memory_guard, dev-stack reminder, zotero | static repo allows |
| **L3 — Project `settings.local.json`** | each repo | only genuinely repo-specific allows: this repo's test/venv/db/dev-stack/network entries | anything universal (promote to L1/L2); one-shot residue |

L2 is installed once and is the single source for gating hooks — never re-wire those hooks in L1 (that was the double-fire bug). L1 keeps only `block_zotero` until it's folded into the plugin.

## Taxonomy — every permission sorts into one category, each with a home layer

| # | Category | Home | Mode |
|---|---|---|---|
| 1 | Reads (path scopes) | L1, broad | allow (low-risk; never gated) |
| 2 | VCS & GitHub ops | L2 | ask (any write) / deny (catastrophic: repo delete) |
| 3 | Package / build / test runners | L3 | allow |
| 4 | Dev-server / container lifecycle | L3 + L2 reminder | allow |
| 5 | Network / WebFetch domains | L1 (common) / L3 (repo) | allow |
| 6 | File mutation (write/mv/rm) | L3, narrow | allow |
| 7 | Destructive / one-shot | nowhere — never persist | — |

## Hygiene rule (what never goes in a persisted allow-list)

One-shot commands with no future reuse: dead PIDs (`kill 57646`), one-time
absolute-path `mv`/`rm`, line-range readers (`sed -n '135,145p'`, `awk 'NR>=…'`),
and anything tied to a single past edit. These are transcript residue; delete on
sight. Run `/fewer-permission-prompts` per repo to keep L3 lean.

## Categorization pass (how "which are repo-specific" gets answered)

Harvest every allow + hook across global + all repos into one matrix; tag each
**UNIVERSAL → L1/L2**, **REPO-SPECIFIC → keep in L3**, or **STALE → delete**;
regenerate clean lists. Examples seen in the first audit:
- UNIVERSAL: `Read(//tmp/**)`, `Bash(gh api:*)`, `WebSearch`
- REPO-SPECIFIC: `FLASK_DEBUG=… uv run flask …`, `PGPASSWORD=<local-dev> psql …`
- STALE: `kill 57646 *`, one-time `.claude/research/…` `mv`/`rm`, `sed -n '135,145p'`

## Build order

1. This doc (model + taxonomy + decisions). ← done
2. Harvest→tag matrix across global + all repos. ← done (2026-06-11): ~990 allow entries → univ≈456 / repo≈295 / stale≈114 / unclear≈523. Promotion set (≥3 repos): `WebSearch`, `WebFetch(github/raw.githubusercontent/wikitech/mediawiki/meta.wikimedia/arxiv/archive.org)`, `git add/commit/push/pull`, `gh api`, shell read-utils.
3. Unify the plugin policy set. ← done (2026-06-11): `policies/classify_github_op.py` + `hooks/github_write_permission.py` (ask on write / deny on catastrophic; replaced the broken `.sh` that read the wrong JSON path); `hooks/dev_stack_reminder.py` (config-driven via `.claude/dev-stack.json`). Both with tests.
4. Derive the lean L1 baseline (tightened reads, promotion set above); prune wiki-polis L3 as the pilot. ← needs the user (global edit is classifier-blocked; `/fewer-permission-prompts` is user-invoked).
5. Roll the L3 pruning to the other repos.

Migration notes: once the plugin's `github_write_permission.py` is live, the global `github_write_permission.sh` wiring and wiki-polis's inline `gh pr merge|close` block hook are redundant — remove them (L3 cleanup). wiki-polis adopts the reminder by adding `.claude/dev-stack.json` and dropping its inline farewell hook.
