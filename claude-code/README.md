# claude-code

Prose lessons for working with the Claude Code agent itself.

- **[`lessons.md`](lessons.md)** — allowlist hygiene, hook/guard-script patterns, Bash quirks that trip the permission validator, CLI-script patterns.

The **runnable** counterparts (reusable hooks, scripts, the PR-gate skill, allowlist method) now live in [`../agent-tooling/`](../agent-tooling/ARCHITECTURE.md) — a Claude Code plugin whose `skills/`+`hooks/`+`settings/` are the Claude-specific parts and whose `scripts/`+`playbooks/`+`policies/` are the agent-agnostic core.
