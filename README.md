# wikimedia-coding-agent-lessons

Lessons learned for AI-assisted development on Wikimedia/Toolforge projects.

Each file captures gotchas, doc links, and patterns that are not obvious from official documentation — intended to be provided to an AI coding assistant at the start of a new project.

## Contents

- [`toolforge/lessons.md`](toolforge/lessons.md) — deployment, venv setup, uWSGI, ToolsDB, replica databases
- [`wikimedia/lessons.md`](wikimedia/lessons.md) — OAuth 2.0, MediaWiki API, Commons thumbnail API
- [`flask/lessons.md`](flask/lessons.md) — Flask-Session + SQLAlchemy 2.0, Alembic stamp-vs-upgrade, general Flask gotchas

## How to use

At the start of a new project, paste the relevant files into the conversation or tell the assistant to fetch the URLs listed under "Docs to fetch at project start" in each file.
