# scripts/

Vetted helpers that skills call instead of inline bash. Each gets a test in `tests/`.

- `llm_review.py` — OpenRouter/Mistral code-review path (model auto-selected by token count; reads `MISTRAL_API_KEY` from env).
- `wikimedia_enterprise_auth.py` — gets/caches a Wikimedia Enterprise API access token (login + silent refresh, ~90 days between password prompts). Prompts interactively (`getpass`, no echo) by default — the password is never written to disk; accepts `WIKIMEDIA_ENTERPRISE_USERNAME`/`WIKIMEDIA_ENTERPRISE_PASSWORD` from env (or the central secrets store) as an opt-in for non-interactive use.
