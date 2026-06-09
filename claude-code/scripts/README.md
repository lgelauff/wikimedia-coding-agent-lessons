# scripts/

Vetted helpers that skills call instead of inline bash. Each gets a test in `tests/`.

- `llm_review.py` — OpenRouter/Mistral code-review path (model auto-selected by token count; reads `MISTRAL_API_KEY` from env).
