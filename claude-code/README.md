# claude-code

Prose lessons for working with the Claude Code agent itself.

- **[`lessons.md`](lessons.md)** — allowlist hygiene, hook/guard-script patterns, Bash quirks that trip the permission validator, CLI-script patterns.

The **runnable** counterparts (reusable hooks, scripts, skills, allowlist baseline) now live in [`../agent-tooling/`](../agent-tooling/ARCHITECTURE.md), structured so the agent-agnostic core is separate from the thin Claude Code adapter. The Claude-specific pieces are under [`../agent-tooling/adapters/claude-code/`](../agent-tooling/adapters/claude-code/).
