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

## Two ways to read this repo

The folders above are organized by **tech stack** (toolforge / wikimedia / flask / …) plus one `agent-tooling/` home for runnable solutions. Cutting across that is a **purpose** axis — four lenses that explain *why* each piece exists. Most files sit in one lens; a few utilities serve two (noted below).

1. **Development** — building & shipping the software safely.
   Lessons: [toolforge](toolforge/lessons.md), [wikimedia](wikimedia/lessons.md), [flask](flask/lessons.md). Tooling: `pr-check`, `browser-verify`, the dev guards (`block_ssh`, `block_secret_read`, `github_write_permission`, `webfetch_content_check`, `dev_stack_reminder`, `git_hygiene_session`), policies (`is_ssh_command`, `classify_github_op`), scripts (`llm_review`, `scope`, `secrets`, `git_hygiene`, `check_inline_js`, `post_pr_screenshots`), and `git-hooks/pre-commit`.

2. **Data analytics** — querying & measuring Wikimedia data.
   Lessons: [wikimedia-analytics](wikimedia-analytics/lessons.md) (MediaWiki API parsing, PAWS / PAWS-SQL, dumps, replica schema, bot-inflation, Phabricator). Tooling: `wikimedia-enterprise` (auth + usage for the credentialed Enterprise API — On-demand/Snapshot/Realtime/Metadata), `overnight-run` (prep → rehearse → launch → report protocol for unattended 8–10 h runs; playbook + skill). Otherwise still lesson-heavy and tooling-light — a known gap.

3. **Research & writing prep** — sourcing and curation that precede a writing effort.
   Skill: `deep-research`. Playbook: `research-data-collection` ("curate, don't RAG-dump"). Pipeline: `source_discovery` → `score_candidates` → `candidates_to_pending`. Guard: `block_zotero`. Utility: `check_wayback_coverage` (citation robustness).

4. **Meta** — the agent and the tooling system reasoning about *itself*: architecture, governance, memory, and economics.
   Docs: [agent-tooling/ARCHITECTURE.md](agent-tooling/ARCHITECTURE.md), [conventions.md](agent-tooling/conventions.md), [settings/permission-framework.md](agent-tooling/settings/permission-framework.md) + [allowlist.md](agent-tooling/settings/allowlist.md), and [claude-code/lessons.md](claude-code/lessons.md) (lessons for the agent itself). Tooling: `memory_guard`, the observability trio `tool_token_log` / `record_run` / `cost_report`, and `budget-estimate` (time + token estimates for a proposed job — P50/P90 bands, evidence levels, rate-limit floors — built on that trio's history; feeds `overnight-run`'s go/no-go).

*Straddlers:* `capture` (screenshots) serves both Development and Research prep; `check_wayback_coverage` is a general utility leaning toward Research prep.

## How to use

At the start of a new project, paste the relevant files into the conversation or tell the assistant to fetch the URLs listed under "Docs to fetch at project start" in each file.

## Code of Conduct

All contributions and discussions related to this repository are expected to follow the [Wikimedia Code of Conduct](https://www.mediawiki.org/wiki/Code_of_Conduct).
