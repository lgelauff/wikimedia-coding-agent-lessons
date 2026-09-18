# `${AGENT_TOOLING_ROOT}` — how skills address the plugin

Companion to [`allowlist.md`](allowlist.md) (the mechanics of an allowlist entry) and
[`permission-framework.md`](permission-framework.md).

## The rule

**Every path a skill hands to a shell command or the agent is
`${AGENT_TOOLING_ROOT}/...`.** No relative paths, no host-specific variables.

```bash
python3 "${AGENT_TOOLING_ROOT}/scripts/scope.py" --config .claude/pr-check.json
```

Reason: a skill's commands are copied verbatim by whichever agent reads it, from whichever
directory, on whichever host. A relative path resolves against the **consuming** repo, where
those files do not exist; a `../../` path additionally resolves *lexically*, which breaks the
moment the skill directory is reached through a symlink (see below).

## Two variables, two mechanisms — do not conflate them

| | Set by | Available in | Use it in |
|---|---|---|---|
| `${CLAUDE_PLUGIN_ROOT}` | Claude Code | **hook commands only** | `hooks/hooks.json` |
| `${AGENT_TOOLING_ROOT}` | the deploying adapter | **the shell / tool environment** | `skills/*/SKILL.md` |

`hooks/hooks.json` correctly uses `${CLAUDE_PLUGIN_ROOT}`: hook commands run in a context
Claude Code populates, so the variable resolves. **Skill bodies do not run in that context** —
they are Bash tool calls made later, in a shell that never saw the plugin hook environment.
That is why `$SKILL_DIR` and `${CLAUDE_PLUGIN_ROOT}` in a `SKILL.md` both failed: neither is
defined where a skill's command actually executes.

## Wiring per host

**Claude Code** — the Claude adapter does not run skills, so the variable must exist in the
session environment. `install.py` writes it into the global settings, as an **absolute path**
resolved at install time:

```jsonc
// ~/.claude/settings.json
{ "env": { "AGENT_TOOLING_ROOT": "/home/ubuntu/GitHub/…/agent-tooling" } }
```

Absolute, *not* `${CLAUDE_PLUGIN_ROOT}`: that variable is undefined in the Bash environment, so
using it here would reproduce the exact bug this document exists to prevent.

**OpenCode** — set by the plugin's `shell.env` hook, which *"inject[s] environment variables
into all shell execution"*. Same value, same absolute path, from `machine.json`.

Both machines therefore get the same *variable* with different *values*, which is the point:
one form in the skill, resolved per machine.

## Enforced, not documented

`scripts/check_skill_vars.py` fails on any path-shaped or known-bad variable reference in a
`SKILL.md` — exit 0 clean, 1 violation, 2 could-not-scan (never treat 2 as clean). Its tests
include a regression case asserting the shipped tree passes.

## History

`$SKILL_DIR` was referenced by four skills (`browser-verify`, `latex-change-review`,
`pr-check`, `wikimedia-enterprise`) and assigned nowhere in this repo, so seven script
invocations expanded to `/../../scripts/…` and failed. `session-close/SKILL.md` also claimed
*"Every sibling skill uses this form"* — true of only 4 of 11. Both fixed 2026-09-17; the
guard exists so it cannot recur.
