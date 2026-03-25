# Contributing

## What belongs here

A lesson belongs in this repo if **all three** of these are true:

1. **Not in the official docs** — or buried so deeply that you wouldn't find it without already knowing to look
2. **Not guessable** — a competent developer working from scratch would not reasonably anticipate this
3. **Reusable** — it applies across projects, not just to one specific data pipeline or analysis

## What does NOT belong here

- Things covered clearly in the official documentation (link to the doc instead)
- Project-specific implementation choices
- Things that are obvious from the error message or a quick search
- Workarounds for bugs that may already be fixed upstream

## Good examples

- "Flask-Session's `create_all` runs during `flask db upgrade`, causing Alembic to fail with 'table already exists'" — not in any doc, not guessable
- "`webservice restart` must be run from `~`, not from inside the repo" — not documented, not guessable

## Bad examples

- "Use `action=query` to fetch page content" — in the docs
- "Add error handling to API calls" — obvious
- "Cache past edition data as immutable" — project-specific
