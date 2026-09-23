# scripts/

Vetted helpers that skills call instead of inline bash. Each gets a test in `tests/`.

- `llm_review.py` — OpenRouter/Mistral code-review path (model auto-selected by token count; reads `MISTRAL_API_KEY` from env).
- `wikimedia_enterprise_auth.py` — gets/caches a Wikimedia Enterprise API access token (login + silent refresh, ~90 days between password prompts). Prompts interactively (`getpass`, no echo) by default — the password is never written to disk; accepts `WIKIMEDIA_ENTERPRISE_USERNAME`/`WIKIMEDIA_ENTERPRISE_PASSWORD` from env (or the central secrets store) as an opt-in for non-interactive use.
- `script_approval.py` — approve a script by its **content** (SHA-256), then run only the exact approved bytes. `approve` is deliberately left off the allowlist, so the human's permission prompt *is* the approval; `run` is allowlisted and refuses an unapproved, edited, symlink-swapped or out-of-project script. The ledger lives in the **main** checkout's `.claude/script-approvals.json` even from a worktree. For scripts under active iteration; once stable, a script graduates to a root-owned read-only folder and leaves the ledger.
