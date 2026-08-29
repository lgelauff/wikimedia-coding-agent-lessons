# TODO / Backlog

Tracked follow-ups for this repo. Newest intent at top.

## Assert-don't-substitute: a skill for keeping numbers in a paper honest

Surfaced 2026-08-29 preparing a paper whose prose carried **158** hand-typed
statistics, 20 of them repeated across more than one file, the worst appearing in
eight places at once. Details in the private study repo; nothing about the work
itself matters here, only the shape of the problem.

The established reproducible-paper practice is **substitution**: the analysis emits
`\newcommand{\CohortN}{119}`, the prose writes `\CohortN`, and a rebuild moves every
occurrence at once (worked example in the DataLad handbook; Brusey 2026 packages it
as an agent skill). It is correct and it is not what most authors will accept, for a
reason stronger than the obvious readability complaint.

**The documented cost is silent semantic drift.** Ordonez et al., *Experience with
Reproducibility and Consistency in Writing an Academic Paper* (ACM REP '25,
doi:10.1145/3736731.3746136): with generated macros, numbers "could change without the
author's knowledge, causing a disconnect between their reality and the prose." If a
macro quietly moves a sample size down, the number stays right and a sentence built on
it — "all but one case carries at least one" — goes quietly wrong. Harder to catch
than a stale number, because nothing looks wrong.

**The proposed middle path is to assert rather than substitute.** Keep the literal
number in the source, where a human reads and edits it; make the build check it:

    \prov{cohort.n}{119}

renders the literal `119`, and fails the build naming file, line, expected and actual
when the pipeline stops agreeing — sending the author back to re-read the sentence, which is
the right response to a base moving. Migration is incremental: accept one argument
(unchecked, today's behaviour) or two (checked), so existing calls keep working and
the marker count becomes a burndown rather than a permanent to-do list.

**Before this becomes a skill it needs one real trial**, per conventions §4. The trial
is live in a private study repo, where the design is written up at
`planning/provisional_numbers_proposal.md` and surfaced from a generated marker
report. Record afterwards: how many of the 158 actually got keys,
whether the formatting normalisation (`6{,}883{,}979` vs `6883979`) was as fiddly as
expected, and whether an assertion ever fired on a real change rather than only on a
deliberate test.

**Prior art is a linter, not a macro.** `sciwrite-lint`
(github.com/authentic-research-partners/sciwrite-lint, arXiv:2604.08501) ships
"numbers-vs-tables" and "arithmetic-consistency" checks over a finished manuscript.
Doing it inside the LaTeX build, so it blocks rather than reports, is the new part —
and is the claim to be sceptical of until the trial above says otherwise.

Natural home if it graduates: a sibling to `latex-change-review`, or a section of the
`arxiv-submission` playbook, which already carries the "check that can fail" discipline
this depends on.

## Promote `morning-integration` draft to a skill if trials hold

`agent-tooling/playbooks/morning-integration.md` (added 2026-07-20) is a DRAFT
playbook for the multi-session morning wrap-up (integrator = recipient + verifier,
two phases split by an explicit user go-signal). After 2–3 real mornings with
field-log entries, decide: fourth mode of `overnight-run`, or a sibling skill.

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
