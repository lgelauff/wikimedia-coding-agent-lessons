# TODO / Backlog

Tracked follow-ups for this repo. Newest intent at top.

## Validate `overnight-run` and `budget-estimate` on a real run

The new `agent-tooling/skills/overnight-run/` skill (+ `playbooks/overnight-run.md`)
is untested prose (per conventions §4, a documented dry-run on a real case is the
validation bar for subjective-output skills). On the next real overnight run:
use the skill end-to-end (PREP → LAUNCH → MORNING), then record here what the
runbook failed to anticipate — especially any permission prompt or mid-run
question that still occurred — and fold fixes back into the playbook's
anti-pattern table. Same for `budget-estimate`: record estimate-vs-actual on
that run and note which assumption (if any) broke by >2×.

## Collect tools developed across the various repos

Sweep the other GitHub projects (under `/Users/lodewijk/Documents/GitHub/`) for
reusable scripts, hooks, policies, and skills that were built ad hoc and never
folded back here. Pull the genuinely reusable ones into `agent-tooling/` (or
note them as lessons), classified by the four-lens model in the README
(Development / Data analytics / Research & writing prep / Meta).

- Goal: one canonical home for the tooling instead of copies scattered per repo.
- Watch for the same logic reimplemented divergently across repos (the
  permission-framework already flagged "3 divergent GitHub guards") — consolidate
  to one agnostic core + thin adapter rather than copying.
- Keep agnostic core vs. Claude adapter split per `agent-tooling/ARCHITECTURE.md`.

## Add a "friendly references" / see-also file

A curated list of related repos and external resources we recommend a reader
(human or agent) also look at — the "friends" of this repo. Candidate names:
`SEE_ALSO.md`, `RELATED.md`, or a "Related work" section in the README.

- One entry per pointer: name, link, and a one-line *why look here*.
- Group by the four-lens model (Development / Data analytics / Research &
  writing prep / Meta) so a reader jumps to the relevant neighbours.
- Likely seeds: `wikimedia-analysis` (already referenced in script UAs/citekeys),
  the `research-vault` project the ingest pipeline feeds, and upstream docs the
  lessons files already cite ("Docs to fetch at project start").
- Needs user input on which repos/resources to vouch for before writing.

## Smaller follow-ups (surfaced 2026-06-21)

- **Data-analytics tooling gap** — that lens is lesson-heavy, tooling-light. If
  analytics is ongoing, add reusable scripts there (it has none today).
- **`block_zotero` only guards `Bash`** (`agent-tooling/hooks/block_zotero.py`)
  — its docstring says Zotero must never be "read, written, edited, or modified,"
  but the code returns early unless `tool_name == "Bash"`, so a `Read`/`Edit`/
  `Write` on `~/Zotero/zotero.sqlite` is not blocked. Extend to file-path tools.
