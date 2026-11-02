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

## Public text: what must not appear

This repo is public, and so is every commit message. None of these may appear in a lesson, a skill,
a script or a commit message:

- host names or SSH aliases of private machines;
- absolute home paths (write `/Users/<you>/…` or a relative path) and paths into a private notes hub;
- e-mail addresses, other than documentation domains such as `example.org`, no-reply addresses and
  an organisation's own published role addresses;
- tokens, keys or passwords, even expired ones;
- internal log ids, session ids, or the names of participants, customers or private projects;
- details of how a private machine or harness is defended (its threat model).

Hedge what you have not verified: label it [concluded] or [guess], not [confirmed].

`agent-tooling/scripts/check_public_text.py` checks the mechanical part of this list on every push
(through `agent-tooling/git-hooks/pre-push`): added lines and commit messages. Private host names
and project names go in a **local** denylist, `.git/info/public-text-denylist`, one term per line.
That file is never committed, because a committed denylist would publish the names it protects.
The guard cannot judge prose about threat models; a reader still has to.
