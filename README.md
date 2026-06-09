# wikimedia-coding-agent-lessons

Lessons **and solutions** for AI-assisted development on Wikimedia/Toolforge projects.

Each topic captures gotchas, doc links, and patterns that aren't obvious from official documentation — and, where it helps, the **runnable artifacts that resolve them** (reusable hooks, scripts, and skills). The prose is the *why*; the solutions are the *what you run*. Intended to be handed to an AI coding assistant at the start of a new project.

## Contents

- [`toolforge/lessons.md`](toolforge/lessons.md) — deployment, venv setup, uWSGI, ToolsDB, replica databases
- [`wikimedia/lessons.md`](wikimedia/lessons.md) — OAuth 2.0, MediaWiki API, Commons thumbnail API
- [`flask/lessons.md`](flask/lessons.md) — Flask-Session + SQLAlchemy 2.0, Alembic stamp-vs-upgrade, general Flask gotchas
- [`wikimedia-analytics/lessons.md`](wikimedia-analytics/lessons.md) — MediaWiki API parsing, mailing list archives, PAWS, User-Agent convention
- [`claude-code/lessons.md`](claude-code/lessons.md) — prose lessons for the agent itself: hook/guard & CLI-script patterns, allowlist hygiene, Bash quirks
- [`agent-tooling/`](agent-tooling/ARCHITECTURE.md) — **the runnable solutions**: reusable hooks, scripts, policies, playbooks, and skills, structured as an agent-agnostic core + thin per-agent adapters (Claude Code today). The *what you run* that pairs with the lessons above

## How to use

At the start of a new project, paste the relevant files into the conversation or tell the assistant to fetch the URLs listed under "Docs to fetch at project start" in each file.

## Code of Conduct

All contributions and discussions related to this repository are expected to follow the [Wikimedia Code of Conduct](https://www.mediawiki.org/wiki/Code_of_Conduct).
