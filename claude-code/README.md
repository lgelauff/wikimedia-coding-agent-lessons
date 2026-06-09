# claude-code — lessons **and** solutions

This topic isn't only prose. It pairs the gotchas with the runnable artifacts that resolve them.

- **[`lessons.md`](lessons.md)** — the *why*: allowlist hygiene, hook/guard-script patterns, Bash quirks that trip the permission validator.
- **[`hooks/`](hooks/)** — the *what you run*: reusable PreToolUse/PostToolUse + pre-commit hooks (SSH guard, GitHub-write gate, OpenRouter gate, secret-scan, fetched-content check).
- **[`scripts/`](scripts/)** — vetted helpers skills call instead of inline bash (e.g. `llm_review.py`, the OpenRouter/Mistral review path). Tests in `scripts/tests/`.
- **[`skills/`](skills/)** — reusable skills (portable core + per-project config). *Migrating in.*
- **[`allowlist.md`](allowlist.md)** — method + rules for cutting permission prompts.
- **[`conventions.md`](conventions.md)** — how to author the above so it stays portable and reviewable.

Everything here reads secrets from the environment and avoids single-repo assumptions, so it's safe to publish and reuse across projects. To consume it as an installable plugin (rather than copy-paste), see the open items in `conventions.md`.
