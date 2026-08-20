# wikimedia-coding-agent-lessons

Lessons **and solutions** for AI-assisted development on Wikimedia/Toolforge projects.

Each topic captures gotchas, doc links, and patterns that aren't obvious from official documentation — and, where it helps, the **runnable artifacts that resolve them** (reusable hooks, scripts, and skills). The prose is the *why*; the solutions are the *what you run*. Intended to be handed to an AI coding assistant at the start of a new project.

## Contents

- [`toolforge/lessons.md`](toolforge/lessons.md) — deployment, venv setup, uWSGI, ToolsDB, replica databases
- [`wikimedia/lessons.md`](wikimedia/lessons.md) — OAuth 2.0, MediaWiki API, Commons thumbnail API
- [`flask/lessons.md`](flask/lessons.md) — Flask-Session + SQLAlchemy 2.0, Alembic stamp-vs-upgrade, general Flask gotchas
- [`wikimedia-analytics/lessons.md`](wikimedia-analytics/lessons.md) — MediaWiki API parsing, mailing list archives, PAWS, User-Agent convention
- [`matplotlib/lessons.md`](matplotlib/lessons.md) — research figures: prop-cycle traps, exact-size export, 3D colorbars, font vendoring, CVD verification
- [`llm-evaluation/lessons.md`](llm-evaluation/lessons.md) — benchmarking an LLM before trusting it: baselines and ceilings, gold provenance, schema-validity vs value-accuracy, why three of our own probes were invalid, plus a reading list
- [`claude-code/lessons.md`](claude-code/lessons.md) — prose lessons for the agent itself: hook/guard & CLI-script patterns, allowlist hygiene, Bash quirks, artifact-based verification, persona reviews
- [`agent-tooling/`](agent-tooling/ARCHITECTURE.md) — **the runnable solutions**: reusable hooks, scripts, policies, playbooks, and skills, structured as an agent-agnostic core + thin per-agent adapters (Claude Code today). The *what you run* that pairs with the lessons above
- [`flushing-dataviz/`](flushing-dataviz/skills/flushing-dataviz/SKILL.md) — consistent, accessible styling for research charts and tables (matplotlib + LaTeX booktabs): a colorblind-safe and grayscale-print-safe palette, ICWSM/AAAI figure sizing, and paper/slides/poster styles. The runnable counterpart to `matplotlib/lessons.md`

## Two ways to read this repo

The folders above are organized by **tech stack** (toolforge / wikimedia / flask / …) plus one `agent-tooling/` home for runnable solutions. Cutting across that is a **purpose** axis — four lenses that explain *why* each piece exists. Most files sit in one lens; a few utilities serve two (noted below).

1. **Development** — building & shipping the software safely.
   Lessons: [toolforge](toolforge/lessons.md), [wikimedia](wikimedia/lessons.md), [flask](flask/lessons.md). Tooling: `pr-check`, `browser-verify`, `session-close` (end-of-session protocol: secure at-risk work — including the gitignored files `git status` is structurally blind to, via `git_hygiene --ignored` — then evaluate what the session established and route actions into the project's queues), the dev guards (`block_ssh`, `block_secret_read`, `github_write_permission`, `webfetch_content_check`, `dev_stack_reminder`, `git_hygiene_session`), policies (`is_ssh_command`, `classify_github_op`), scripts (`llm_review`, `scope`, `secrets`, `git_hygiene`, `check_inline_js`, `post_pr_screenshots`), and `git-hooks/pre-commit`.

2. **Data analytics** — querying & measuring Wikimedia data.
   Lessons: [wikimedia-analytics](wikimedia-analytics/lessons.md) (MediaWiki API parsing, PAWS / PAWS-SQL, dumps, replica schema, bot-inflation, Phabricator), [matplotlib](matplotlib/lessons.md) (publication figures). Tooling: `wikimedia-enterprise` (auth + usage for the credentialed Enterprise API — On-demand/Snapshot/Realtime/Metadata), `overnight-run` (prep → rehearse → launch → report protocol for unattended 8–10 h runs; playbook + skill), `liftwing-llm` (Wikimedia-hosted open-weight LLMs via the keyless OpenAI-compatible endpoint — the free, WMF-hosted option for bulk classification/extraction; 100 req/h anon ceiling + Toolforge escalation). Otherwise still lesson-heavy and tooling-light — a known gap.

3. **Research & writing prep** — sourcing and curation that precede a writing effort.
   Skills: `source-connectors` (model every source you collect from as a declared connector — endpoint, auth, access policy, licence, retrieval recipe; be a good neighbour rather than a scraper) and `latex-change-review` (show what a `.tex` edit actually changed — text diff for content, cropped before/after PNGs for styling). Playbook: `research-data-collection` ("curate, don't RAG-dump"). Pipeline: `source_discovery` → `score_candidates` → `candidates_to_pending`. Guard: `block_zotero`. Utility: `check_wayback_coverage` (citation robustness).

4. **Meta** — the agent and the tooling system reasoning about *itself*: architecture, governance, memory, and economics.
   Docs: [agent-tooling/ARCHITECTURE.md](agent-tooling/ARCHITECTURE.md), [conventions.md](agent-tooling/conventions.md), [settings/permission-framework.md](agent-tooling/settings/permission-framework.md) + [allowlist.md](agent-tooling/settings/allowlist.md), and [claude-code/lessons.md](claude-code/lessons.md) (lessons for the agent itself). Tooling: `charset-hygiene` (keep text and code inside a declared set of permitted characters — invisible Unicode, homoglyphs, watermark payloads; runs on one string or an unattended whole-tree pass), `memory_guard`, the observability trio `tool_token_log` / `record_run` / `cost_report`, and `budget-estimate` (time + token estimates for a proposed job — P50/P90 bands, evidence levels, rate-limit floors — built on that trio's history; feeds `overnight-run`'s go/no-go). Provider choice: `llm_provider` (one env var switches the whole machine's LLM backend: claude-code | liftwing | openrouter | mistral) with local, gitignored per-provider feedback logs in [agent-tooling/feedback/](agent-tooling/feedback/README.md) — the evidence behind "which provider for which task" — and `rate_budget` (flock-guarded token bucket + attribution ledger, so concurrent sessions cannot collectively blow a shared API quota; `--status` answers "who is using this API").

*Straddlers:* `capture` (screenshots) serves both Development and Research prep; `check_wayback_coverage` is a general utility leaning toward Research prep.

## How to use

At the start of a new project, paste the relevant files into the conversation or tell the assistant to fetch the URLs listed under "Docs to fetch at project start" in each file.

## How this repository is made

Most of the text here was written by AI coding agents. The direction is mine: what
gets built, when, where the focus goes, and what is kept. The agents supply the prose
and the code; the judgement about what was worth writing down, and what turned out to
be wrong, is the human contribution.

That matters for licensing. Agent-generated text is unlikely to carry copyright of its
own — there is no human author behind the individual sentences. What I hold is thinner
than in an ordinary codebase: the selection and arrangement, plus whatever I wrote or
reworked myself. Strong copyleft assumes an ownership this repository does not really
have, so it is licensed permissively instead.

## Licence

- **Code** — `scripts/`, `hooks/`, `policies/`, `git-hooks/`, and the code inside
  skills — is **MIT**. See [LICENSE](LICENSE).
- **Prose** — the `lessons.md` files, the playbooks, and this README — is
  **CC BY-SA 4.0**, to the extent it is mine to license.

In practice: take the code and use it, no strings. If you reuse the writing, credit it
and share alike.

**Individual folders may differ.** Where a folder is under a different licence —
vendored third-party assets, or material adapted from elsewhere — it says so in that
folder's own README. Check there before reusing anything from it.

## Code of Conduct

All contributions and discussions related to this repository are expected to follow the [Wikimedia Code of Conduct](https://www.mediawiki.org/wiki/Code_of_Conduct).
