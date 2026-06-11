# agent-tooling — architecture

Reusable automation for AI coding agents, structured so the **general core is agent-agnostic** and the **agent-specific parts are thin adapters**. Most of what's useful here — deterministic scripts, policy logic, and the *procedures* skills encode — has nothing to do with any particular agent. Only the glue that lets a given agent (Claude Code today) trigger and wire it is product-specific.

## Principle

> Write the logic once, as something any agent — or a CI job, or a human at a terminal — can run. Add a thin per-agent adapter only for the parts that are genuinely product-specific: how that agent triggers a procedure, and how it hands a hook its event and reads back a decision.

This keeps the valuable, hard-won part (the *what* and the *why*) reusable, and quarantines the disposable part (one product's wiring format) to the edge.

## Layers, by coupling

| Layer | Agent coupling | Lives in | Examples |
|---|---|---|---|
| **Scripts** | none — plain programs (stdin/args → stdout + exit code) | `scripts/` | `llm_review.py` (LLM diff review via OpenRouter), `scope.sh` (classify a diff) |
| **Policies** | none — decision logic as standalone executables that know nothing of any agent's event format | `policies/` | "is this command an SSH to a remote host?", "does this fetched content contain injection?" |
| **Playbooks** | none — procedures as prose (a method, not an implementation) | `playbooks/` | the PR quality-gate method; the local-e2e verification method |
| **Git hooks** | none — standard git, works for any developer/agent | `git-hooks/` | `pre-commit` (detect-secrets scan) |
| **Adapters** | **product-specific** — the only Claude-coupled layer | the plugin's `skills/` + `hooks/` + `settings/` | Claude Code: `SKILL.md` files, PreToolUse/PostToolUse hooks, `settings.json` snippets |

## What is actually Claude-Code-specific

Only the adapter layer:
- **Hook I/O contract** — the PreToolUse/PostToolUse event JSON in, the permission-decision JSON out, and `settings.json` wiring.
- **Skill format** — `SKILL.md` frontmatter + description-triggering.
- **Orchestration calls** — the Workflow / Agent tools a skill invokes.

Everything else (the policy a hook enforces, the script it runs, the procedure a skill follows) is general.

## Directory layout

`agent-tooling/` **is a Claude Code plugin** (the repo root is its marketplace). A Claude Code plugin is, by definition, the Claude adapter — so rather than a redundant `adapters/claude-code/` layer, the agnostic-vs-Claude split is expressed as labeled sibling subdirs inside the plugin. Plugin discovery requires `skills/`+`hooks/` at the plugin root, and a skill's referenced files must live inside the plugin root — both satisfied here.

```
wikimedia-coding-agent-lessons/
├── .claude-plugin/marketplace.json   repo = marketplace; lists the agent-tooling plugin
└── agent-tooling/                    the plugin (= the Claude Code adapter)
    ├── .claude-plugin/plugin.json
    ├── ARCHITECTURE.md  conventions.md
    ├── skills/          Claude-specific — SKILL.md referencing ../../playbooks/X + Claude orchestration
    ├── hooks/           Claude-specific — PreToolUse/PostToolUse (+ settings/ allowlist)
    ├── settings/        Claude-specific — allowlist method + hook-wiring snippets
    ├── scripts/         AGENT-AGNOSTIC — deterministic helpers; tests in scripts/tests/
    ├── playbooks/       AGENT-AGNOSTIC — procedures (markdown)
    ├── policies/        AGENT-AGNOSTIC — decision executables (is_ssh_command; tests in policies/tests/)
    └── git-hooks/       standard git hooks (no agent coupling)
```

The agnostic subdirs (`scripts/`, `playbooks/`, `policies/`, `git-hooks/`) carry no Claude coupling — a different agent's package would reference the same files. Only `skills/`+`hooks/`+`settings/` are Claude-specific. A second agent is **not** scaffolded until needed (YAGNI); the contracts below keep adding one cheap (it would be a sibling package that imports these same agnostic dirs).

## Adapter contracts

So a future sibling agent package can be added without touching the agnostic core:

**Policy adapter (hook).** A policy is an executable that, given the relevant fact on stdin/args, exits `0` (allow) / non-zero (block) and prints a human-readable reason. The adapter's only job: translate the host agent's event into that input, and translate the exit/reason into the host's decision format. Policies must never parse a specific agent's event JSON themselves.

**Playbook adapter (skill).** A playbook is the procedure in prose, written agent-neutrally ("scope the diff; review; run tests; convene reviewers; verify; emit a verdict"). The adapter (a Claude `SKILL.md`) supplies the triggering, the concrete tool calls (Workflow/Agent), and a pointer to the playbook. Two agents share one playbook; each has its own adapter.

## Conventions (all layers)

- **Scripts/policies:** read-only unless mutation is the whole point (then say so loudly); secrets from the **environment**, never hardcoded; dependency-light; non-zero exit + clear message on failure; a test under `*/tests/`.
- **Playbooks:** describe the method and its decision points, not one repo's commands. Repo-specific values (globs, test commands, stack layout) belong in a per-project config the adapter reads, not in the playbook.
- **Adapters:** keep them thin. If an adapter grows real logic, that logic probably belongs in a script/policy/playbook.
- **Permissions:** never allowlist arbitrary code execution; prefer exact invocations or bundled script paths. (See `agent-tooling/settings/` and the allowlist method.)
- **Pair with a lesson:** when a solution exists because of a non-obvious gotcha, capture the gotcha in the matching `*/lessons.md` and cross-link.

## Migration map (current → target)

The first fold landed everything under `claude-code/`. It relocates as:

| Now | Target | Why |
|---|---|---|
| `claude-code/scripts/llm_review.py` | `agent-tooling/scripts/` | not Claude-specific at all |
| `claude-code/hooks/pre-commit` | `agent-tooling/git-hooks/` | standard git hook |
| `claude-code/hooks/block_ssh.py` | policy → `agent-tooling/policies/`; Claude wrapper → `agent-tooling/hooks/` | general policy + thin adapter — **done**: `policies/is_ssh_command.py`, hook now a thin adapter |
| `claude-code/hooks/webfetch_content_check.py` | `agent-tooling/hooks/` | kept self-contained — its short-content check is a small heuristic, not a reusable policy |
| `claude-code/hooks/github_write_permission.sh`, `openrouter_permission.sh` | `agent-tooling/hooks/` (logic extractable to `policies/` if reused) | gating tied to the agent's permission model |
| `claude-code/allowlist.md`, `conventions.md` | `agent-tooling/` (conventions) + `agent-tooling/settings/` (allowlist) | split general rules from Claude wiring |
| `wiki-polis/.claude/skills/{pr-check,local-e2e,staging-chrome-test}` | playbook → `agent-tooling/playbooks/`; `SKILL.md` → `agent-tooling/skills/` | general procedure + Claude adapter |
| `claude-code/lessons.md` | stays (prose lessons topic), cross-linked from adapters | it's adapter-knowledge for Claude Code specifically |

## Status

Architecture defined. Restructure executes next, per the migration map. Only the Claude Code adapter ships now; the contracts above keep the door open for others at no current cost.
