# Claude Code agent tooling lessons

How to write hook/guard scripts and Claude-driven CLI scripts so they don't trip
Claude Code's Bash permission validator with avoidable "manual approval required"
warnings. None of this is in the official hooks docs, and the failure modes are
not guessable — they only surface as recurring permission prompts.

---

## The core principle

The permission layer validates Claude's **tool-call string** (the shell command it
is about to run), *not* what a subprocess does once it is running. The static
validator must be able to resolve every path in the command. Anything that obscures
path resolution — a `cd` before a redirect, inline `python3 -c` code, a newline
followed by `#` inside a quoted argument — forces manual approval.
([permissions docs](https://code.claude.com/docs/en/permissions) — "Read and Edit
deny rules … do not apply to arbitrary subprocesses that read or write files
indirectly, like a Python or Node script that opens files itself.")

Crucially, several of these are **hardcoded heuristic guardrails that run *above*
the permission allowlist** — they fire before your `allow` rules are consulted, and
at least the newline-`#` check even bypasses sandbox auto-approve mode. So you
**cannot** allowlist (or sandbox-auto-approve) your way out of them; the only remedy
is to stop emitting the offending command shape — i.e. fix the script. (See
[anthropics/claude-code#48762](https://github.com/anthropics/claude-code/issues/48762)
for the cd-guardrail strings firing above the allowlist, and
[#45421](https://github.com/anthropics/claude-code/issues/45421) for the newline-`#`
check bypassing sandbox auto-approve.)

Two consequences shape everything below:

- **Move work *into* a single script invocation with flags.** One approved
  `Bash(python script.py *)` pattern then covers every operation.
- **Once `python script.py …` is approved, its internal file/HTTP I/O never
  re-prompts** — because that I/O is the subprocess's, not a Claude tool call.

General rule: **prefer one statically-analyzable command with absolute paths and
native flags over compound shell glue** (`cd` / `>` / inline `-c` / pipes into
interpreters).

## Bash patterns that trigger avoidable warnings

- **`cd X && cmd > file` → "Compound command contains cd with output redirection —
  manual approval required to prevent path resolution bypass".** The `cd` moves the
  path-resolution context, so the redirect target can't be verified to stay inside
  an allowed directory. **Fix:** drop the `cd` and use the tool's own
  location/output flag — `git -C <path>`, `make -C <dir>`, `tar -C <dir>`,
  `curl -o /abs/out`, `python script.py --out /abs/out` — or use an **absolute
  redirect target with no `cd`** (`python /abs/script.py > /abs/dir/out`).

- **`python3 -c "with open('…')` spanning lines → "Newline followed by # inside a
  quoted argument can hide arguments from path validation".** A multi-line `-c`
  string whose body contains a newline-then-`#` looks like it could smuggle an
  argument past validation. It is also often double-quoted, so it can never be
  allowlisted cleanly. **Fix:** don't hand-roll inline Python to read/write files;
  give the script a subcommand (`--show`, `--cat`) and call that, or use the Read
  tool / `jq`.

- **`gh api … | python3 -c "import json,sys; …"` stdin parsers.** Same anti-pattern,
  and the allow-rules for them accumulate endlessly (every literal differs).
  **Fix:** `gh … --jq '…'` or pipe to `jq`.

- **`curl https://…` per URL.** Each new URL needs its own approval. **Fix:** do
  HTTP in-process (`urllib`/`requests`) inside an approved script.

## Writing guard / hook scripts (PreToolUse / PostToolUse)

- **Read the hook JSON from stdin; on any parse error `sys.exit(0)`** (fail open).
  A guard that crashes or false-blocks is worse than one that misses an edge case.
  (Exception: a guard that is supposed to *fail closed* must guard its own parse
  step too — see the `block_ssh.py` note below.)
- **Match `tool_name` first and exit 0 immediately** if it isn't the tool you
  guard — cheap, and prevents false positives on unrelated calls.
- **Exit-code contract:** `0` = this hook raises no objection — the *normal*
  permission flow still applies (it is **not** an auto-approve) · `2` + stderr =
  block and show the message to Claude · any other nonzero = non-blocking error,
  tool proceeds, stderr logged to the transcript. Reserve `2` for genuine blocks;
  advisory warnings use `exit 0` + a stderr note. (There is also a newer JSON
  method — `exit 0` plus `{"hookSpecificOutput":{"permissionDecision":"allow"|
  "deny"|"ask"}}` on stdout — for explicit allow/deny decisions; see the
  [hooks reference](https://code.claude.com/docs/en/hooks).)
- **Human-facing text goes to stderr.** On a block (`exit 2`) only stderr is shown
  to Claude; stdout on `exit 0` is reserved for the optional JSON decision above.
  Make it actionable — say what to do instead and, for blocks, "do NOT retry".
- **Fail open for advisory guards; fail *closed* only for hard security boundaries**
  (e.g. blocking `ssh`/`scp`/`rsync -e ssh`). A true fail-closed guard must also
  `exit(2)` on a stdin/parse error — otherwise a crash exits nonzero-but-not-2,
  which is treated as a non-blocking error and the tool *proceeds*. (The bundled
  `block_ssh.py` exemplar wraps `json.load` in a try/except that `exit(2)`s on a
  parse error — so even malformed stdin fails *closed*. Without that guard a crash
  would exit nonzero-but-not-2 and let the command through.)
- **No shell-outs from the guard** — pure stdlib (`json`, `re`, `urllib`,
  `pathlib`). Keeps it fast, portable, and stops the guard itself from tripping
  other validators.
- **Resolve paths by walking up from `cwd`/`__file__` to a project marker;** never
  hardcode `/Users/...` or `expanduser`.
- **Use anchored, specific regex** to avoid false matches, and **dedup expensive
  work** (e.g. fetch each domain's `robots.txt` once).
- **One responsibility per guard;** compose several small guards rather than one
  mega-hook. Hooks merge across global/project settings and any `exit 2` blocks.

## Writing CLI scripts Claude will drive

- **Do file I/O in-process** (the script writes its own outputs via `pathlib`) —
  never rely on shell `>`. This alone eliminates the cd+redirect warning.
- **Provide read/inspect subcommands** (`--show`, `--cat`, `--list`) so Claude never
  hand-rolls `python3 -c "with open(...)"` to peek at outputs or caches.
- **Take input/output paths as arguments,** resolved internally — invocations then
  need no `cd` and no redirect.
- **Single entrypoint with flags** → one approved `Bash(python script.py *)` covers
  everything.
- **HTTP in-process,** not `curl` in Bash → no per-domain approval prompts.
- **Outputs cwd-local by default;** make a cross-project path an explicit opt-in
  flag (e.g. `--pending-file`) rather than reaching `../../` by default.

## Allowlist hygiene

- Permission `Write(...)`/`Bash(...)` allow-rules only matter for **Claude's** tool
  calls. A path a *script* writes in-process needs no `Write(...)` rule — adding one
  is dead config that implies coverage you don't have.
- Don't allowlist inline `python3 -c "..."` one-liners. The list grows without
  bound (every literal differs) and some forms can never match cleanly. **Fix the
  script** (add a subcommand) instead of chasing the warning with allow-rules.
  (And recall from the core principle: the cd+redirect and newline-`#` checks fire
  *above* the allowlist anyway, so allow-rules can't suppress them — fixing the
  script is the only lever.)
- **Exact-string accretion is the slow-motion version of the same failure.**
  Approving each prompt "with allowlist" as its literal command (a specific curl
  URL, a one-off `cp` with quoted filenames) builds a long list that covers
  *nothing* the next session — every new URL/filename prompts again. Field case
  (2026-07-19): a ~40-entry accreted list provided near-zero coverage of a
  day's analysis work; the day ran on manual approvals and the friction delayed
  an overnight run's prep past its launch window. At grant time, generalize to
  the narrowest **reusable** shape instead: a script's absolute path with `:*`
  for its flags, `WebFetch(domain:…)` rather than per-URL curl, `--out`-style
  subcommands rather than shell redirects. If no reusable shape exists, that's a
  script-design smell (see "Writing CLI scripts Claude will drive").
- **Route read-only exploration through dedicated tools, not Bash.** `Read`,
  `Grep`, and `Glob` don't touch the Bash permission layer; `cat`/`grep`/`ls`/
  `head` pipelines do, and each novel pipeline shape is a fresh prompt. In
  approval-per-call sessions, an agent that habitually explores via Bash
  generates dozens of avoidable prompts a day — the cumulative attention cost
  lands on the human, not the agent.
- **Second field case, worse (2026-09-22/23, wikipedia-drop-2026):** 365 allow
  entries, all one-off exact invocations (a named PDF `cp`, individual curl URLs,
  `git -C <path> add paper/ .gitignore`), `ask` and `deny` empty, no shared
  `.claude/settings.json` at all. Everyday read-only commands matched *nothing*,
  and one morning cost the human ~10 unblocks on a single session — while the
  prompt does not tell him **which** session is asking. 365 entries is the
  symptom, not the protection.
- **A prompt storm is usually a scope mismatch, not a rule shortage.** That
  project runs sessions in git worktrees while all gitignored data lives only in
  the main checkout, so normal work reads across two roots all day and the second
  one is outside the working directory. No number of command strings fixes that:
  declare the second root (`additionalDirectories`) and write rules that cover
  both. Ask "what shape of work is this scoped to?" before adding an entry.
- **`cd <dir> && git …` can never be silenced; `git -C <dir> …` can.** The harness treats the
  `cd` form as able to execute hooks from the target directory, so it offers no "always allow"
  at all — no allowlist entry will ever cover it. The `-C` form prompts only because of the
  path, and a prefix rule covers it for good. Same for `--prefix`/`--rootdir` style flags in
  other tools. Teach the flag form once and a whole class of prompts disappears
  (2026-09-23, dp PR gate) [confirmed].
- **A review gate needs a handful of read-only prefixes, not a rule per invocation:**
  `git -C <repo-root>/* :*`, `gh pr view|list|diff`, `gh issue view|list`,
  `gh api repos/<owner>/<repo>/*`. Grant those once at the project level.
- **Shaping a command to avoid a prompt is legitimate when — and only when — it
  keeps the work inside the design.** The goal is not to be unobserved; it is not
  to need a shortcut through someone else's area in the first place. Statically
  analysable shapes (a script path with `:*`, `Read`/`Grep`/`Glob` instead of
  shell pipelines, `--out` flags instead of redirects, `git -C` instead of
  `cd &&`) are both *less* prompting and *more* reviewable. Inline
  `python3 - <<'PY'` heredocs are the opposite: arbitrary code, never safely
  allowlistable, and they will — correctly — ask every time. If the honest shape
  of a task needs a boundary crossing, ask for it explicitly and say why; do not
  reach for a form that slips past the matcher.

## Verify against the artifact, not the code

A "verified" claim is only as good as the thing you looked at. A styling
bug shipped because the code *intended* distinct styles for series 7–12,
the change looked correct in the diff, and verification stopped there — the
rendered PNG actually showed two series pixel-identical (the style was
applied after axes creation, a silent no-op; see
[`matplotlib/lessons.md`](../matplotlib/lessons.md)). For anything with
rendered output (figures, PDFs, HTML), the verification step is: open the
exported artifact and look at it, or measure it (PDF MediaBox for sizes).
Reading the code back is not verification.

## Verifying the artifact is not enough — the assertion has to match the failure

The lesson above says look at the artifact. The failure mode *after* you do that
is asserting the wrong property of it. A LaTeX build script gated on undefined
references only; it reported "45 pages, 0 undefined references" across four
commits while the log carried nine `! ` errors. The artifact was rebuilt and
inspected every time. The habit was right and the check was narrow, which is
worse than no check, because it manufactures a confident "verified".

Two things generalise:

- **Where the tool keeps going after an error, "it produced output" is not a
  signal.** LaTeX writes a PDF through errors; BibTeX exits non-zero on
  warnings; a linter with no rules enabled passes everything. Ask what this tool
  does when it fails, and gate on *that*, not on the presence of output.
- **A gate written as prose gets skipped.** The check that would have caught
  this was already written down in
  [`agent-tooling/playbooks/arxiv-submission.md`](../agent-tooling/playbooks/arxiv-submission.md):
  "state page count, **error count**, bibitem count against distinct `\cite`
  keys". It was read past. The same sentence as an executable gate that exits
  non-zero cannot be read past. Prefer committing the check over documenting it.

Corollary: when a lesson repo exists for the stack you are working in, open it
*before* the task, not after the third failure. Three separate gate gaps in one
session — error count, duplicate labels, bibitem parity — were all named in a
playbook already sitting in the repo.

## Exercise the path you changed, end to end, before you fan out

**Run one full unit of work through the changed code before launching the batch.** Not the stage you
edited — the whole thing, to completion, on the smallest real input.

A portability patch touched two places in one script: path resolution at stage 1, and a lookup loop
at stage 4. The verification watched the resolved paths print, saw them correct, and stopped there.
The loop referenced a variable that was never initialised, and all fifteen projects died on it. The
test exercised the half that was already trusted.

The generalisable rule: **the region you edited defines what the test must reach.** If a change
touches two functions, the check must execute both. "It got past the part I was worried about" is the
shape of this failure, and it is cheap to avoid — one small project run to completion costs minutes
against a batch that costs hours.

**Order batches smallest-first** for the same reason: a systematic fault then surfaces in the first
minutes rather than partway through the largest input.

## Make the last artifact written the completion marker

**Write the manifest (or any summary file) *after* the data, and have the next stage refuse to
consume data whose manifest is missing.** This gives a pipeline atomic-ish semantics for free.

Without it, a run interrupted during its final write leaves a well-formed, readable, *short* file
under the production name — and every downstream check then measures itself against the truncated
input and reports ~100%. A structure pass killed by a dropped connection left a 161 MB output that
looked entirely normal; the only thing distinguishing it from a complete run was the manifest that
had not been written yet.

Related habits that make a long pipeline honest:

- **Have test modes write test paths.** A `--limit` flag that stops early *and* writes the production
  output path will silently replace a complete artifact with a partial one. A 400-article smoke test
  overwrote a finished 151,340-article file this way — and because the completeness floor was also
  skipped under `--limit`, the mode most likely to mislead was both unguarded and destructive.
- **Record the producing code, not just the inputs.** Hash the scripts and the git commit into the
  manifest. When a parser changes in a way that moves 11% of its output, two artifacts from either
  side of that change are otherwise indistinguishable — same name, same schema, same date.
- **Make drivers exit non-zero when any unit failed.** A shell driver that prints `INCOMPLETE` and
  exits 0 will be read as success by anything chaining on `&&`, and by a future cron.
- **`#!/usr/bin/env bash`, plus a version guard, if you use `declare -A` or `wait -n`.** macOS ships
  bash 3.2 at `/bin/bash`, which rejects both. A script can work for months purely because it happens
  to be invoked as `bash script.sh` with a newer bash on `PATH`.

## Check the instrument before you believe the finding

**When a measurement contradicts something you expect to be true, suspect the measurement first.**
Two numbers in a single session were artifacts of their own measuring stick, and both presented as
properties of the thing being measured:

- A validator reported **42.1% disagreement** between two implementations. Current MediaWiki wraps
  headings as `<div class="mw-heading mw-heading2"><h2 …>`, and the pattern matched both the div and
  the h2 — counting every heading twice. The tell was in the examples: 1-vs-2, 2-vs-4, 3-vs-6. **An
  exact ratio between "expected" and "observed" is nearly always an instrument fault**, not a finding.
- A statistic computed under `--limit 3000` was reported as a population value: **34.6%**, when the
  true figure was **11.3%**. `--limit` takes a *prefix* in dump order — the oldest and longest
  articles — not a sample. The rate decayed monotonically as the prefix grew.

So: **state the population a number describes, in the same sentence as the number.** The commit
message that said "4,337 of 12,527 positions from 3,000 articles" was honest; the runbook sentence
that later said "34.6% of positions move" was not, and nobody had to lie for that to happen.

**And check that a validation isn't circular.** An agreement of 202/202 between a wikitext parser and
an HTML parser was reported as validating a *model assumption* about which sections collapse. It
could not: the HTML oracle counted `<h2>` and the wikitext parser counted `==` — the same construct in
two syntaxes, so it agreed precisely where the parser was wrong. It was a real parser check and a
worthless assumption check. Ask what a passing test would still be consistent with.

## Guards can only see faults their own stage introduced

**Design at least one check that compares against something outside the pipeline.** Every threshold
inside a pipeline is an internal-consistency check: each stage measures itself against the input it
was handed, so it is structurally blind to a fault that corrupted that input upstream — the stage is
then perfectly consistent with the wrong thing.

Concretely, a partial parse of a usage table does not merely lose rows; it *manufactures* eligibility,
because items whose other usages were dropped now look unique. Downstream floors all read 100%,
because the survivors are internally coherent. The checks that catch this are of a different kind:

- **an external oracle** — ask the live API whether a sample of the population really has the property
  the pipeline claims;
- **cross-stage reconciliation** — have each stage assert its input row count against the upstream
  manifest, so a truncated or stale input fails at the boundary instead of scoring perfectly;
- **an invariant that does not depend on the data** — e.g. chunk-invariance, which holds for any
  correct implementation regardless of input.

## A bug recording is evidence you can't get any other way — make sure you can open it

Screen recordings (Jam, a `.mov` dropped in chat) carry things a bug report
never does: which of two dialogs appeared, whether a button existed at all,
what the timing was. In one case the entire diagnosis of a permission-prompt
storm came down to comparing two screenshots side by side — one prompt offered
"Always allow", the neighbouring one didn't, and that difference *was* the root
cause. No amount of reading the skill source would have found it.

Two practical points.

**Jam links arrive through an MCP server that needs a one-time OAuth grant.**
If it hasn't been done, the tool call fails and the useless response is "this
server needs authorization and I can't run the OAuth flow." The useful response
names the remedy:

```
claude mcp login Jam          # --no-browser for SSH/headless
claude mcp get Jam            # ✔ Connected, or ! Needs authentication
```

The grant is **user-scoped** — `claude mcp get` reports "available in all your
projects" — so one login covers every repo and there is nothing per-repo to
configure. A session already running won't see it until it restarts. Never run
the login flow on the user's behalf; hand them the command.
`hooks/mcp_auth_reminder.py` catches this automatically: when a prompt links to
a configured-but-unauthenticated server, it injects the command.

**A local video file is readable without any of that** — extract frames and look
at them:

```bash
ffmpeg -v error -i recording.mov -vf "fps=1/4,scale=1400:-1" -frames:v 8 /tmp/frame%02d.png
```

One frame every four seconds is usually enough to find the moment that matters;
scale up rather than down, because the detail you need is often small UI text.
Watch the filename: macOS screen recordings contain a **narrow no-break space**
(U+202F) before "AM"/"PM", so a path typed with an ordinary space silently fails
to match. Glob it (`ls ~/Downloads/Screen*Recording*.mov`) instead of retyping
it — a plain "no such file" on a file you can see is the tell.

## Persona reviews want rendered artifacts, not just source

When reviewing design-flavored work, spawning two parallel reviewer
subagents with distinct personas (a UI designer; a domain-methods expert)
and telling them to **Read the rendered PNGs**, not only the source, was
unusually productive: between them they found a shipped rendering defect,
an export-size contract violation, and a systematic coverage gap — none of
which a source-only review had surfaced. Give each persona the artifact
directory, force a severity-ranked list with concrete fixes, and merge.

## Model facts have three tiers of freshness — and the middle one looks authoritative

Asked which model to run a session on, an agent can answer from three places, and
they are **not** equally current:

1. **Training data** — always stale for model facts; a model released after the
   cutoff is invisible except as a name handed over in the system prompt.
2. **The `claude-api` skill's cached tables** — dated (`cached: <date>` in
   `SKILL.md`), and stale between refreshes. *This is the dangerous tier*: it is
   specific, tabular, and reads as authoritative, so it gets quoted verbatim.
3. **The live docs / Models API** — the only current source.

**Observed 2026-08-12.** The skill's cached table listed Claude Sonnet 5 at
`$3/$15 per MTok, with $2/$10 introductory pricing through 2026-08-31`. The live
pricing page said the opposite: *"The $2/$10 … announced at launch as
introductory pricing … is now the standard price. The previously scheduled
increase to $3/$15 … will not occur."* Quoting the cache produced a wrong price
**and** a phantom deadline three weeks out — the sort of thing that ends up in a
budget estimate.

The same fetch surfaced a fact the cache omitted entirely and that nobody would
guess: **the top-capability model can have an older knowledge cutoff than the
tier below it** (at the time: Opus 5 reliable-knowledge May 2026, Fable 5
Jan 2026). "Most capable" and "best informed" are separate axes.

**Rule:** for any model-selection, pricing, or capability answer, WebFetch the
live docs (or query the Models API) in the same turn you answer. The skill's own
trigger says "never answer from memory" — treat its cached tables as memory too.
Do **not** copy the resulting numbers into this repo: they are in the official
docs (CONTRIBUTING rule 1), and a second stale copy is the failure mode this
lesson is about. Record the *lookup route*, not the values.

Live sources: `https://platform.claude.com/docs/en/about-claude/models/overview.md`
and `.../about-claude/pricing` (note: **not** `/docs/en/pricing`, which 404s);
`client.models.retrieve(id)` for per-model capability flags.

## "Most capable tier" and "best at your task" are different axes

Model families are marketed as a ladder, and the ladder is real for *capability
in general* — but routing by tier alone picks the wrong model, in both
directions. Two failure modes, both observed 2026-08-12:

**Reaching too high.** The flagship tier is not automatically the coding
leader. At the time: the top tier led one repository-level benchmark by a point
(noise) while the tier below it led single-task coding *and* beat it decisively
on terminal-style agentic coding — at half the price, faster, and without the
flagship's operational costs (couldn't disable thinking, safety classifiers that
*refuse* requests, a 30-day data-retention floor that rules it out under ZDR).
The tier name is a capability claim, not a benchmark result.

**Reaching too low, which is the expensive one.** A mid-tier model scored
**85.2% on single-task SWE-bench Verified but 63.2% on repository-level
SWE-bench Pro.** *Single-task competence does not predict repository-scale
competence*, and the two benchmarks are reported in the same breath as if
interchangeable. A cross-file investigation routed to the mid tier because it
"looked like analysis" lands in that 22-point hole — and the failure is silent,
because the model answers confidently either way.

**Route by task SHAPE, not by importance:**

| shape | tier |
|---|---|
| Repository-scale reasoning — trace across many files, decide whether the check or the data is wrong, refactor broadly | top coding tier |
| Planning, judgement, reconciling contradictory docs | top coding tier |
| Scoped execution — run a prepared script, watch a log, single-file edits | mid tier |
| Bulk classification, routing, high-volume subagent fan-out | cheap tier — **but check its context window**, which is often a fraction of the others' and silently rules it out for wide scans |
| Multi-hour autonomous runs where one session is the unit of work | flagship tier, if anything |

**Check two benchmarks, not one.** Ask for a single-task score *and* a
repository-level score before routing anything cross-file. If only one is
published, assume the other is worse.

## One data root and one artifact root, declared up front

The recurring structural fault behind most permission friction here (three sessions, one day,
2026-09-22/23): sessions run in git worktrees while the gitignored data lives **only** in the
main checkout. Each layer then rediscovers the mismatch separately — the project's own scripts
resolve an absolute `data_root` and refuse to run from a worktree; a PreToolUse hook refuses
subagent writes into the main checkout, so a delegated brief fails on its *final* write unless
it carried a redirected output path; Write/Edit refuse paths under the base repo's shared
`.claude/`, so run directories end up duplicated in the worktree's own `.claude/` and drift;
headless `claude -p` refuses writes under any `.claude/` [confirmed].

**The sharpest form of it: when your edit root is not your execution root, your fix is not
live.** A one-line resume-bug fix made in a worktree, then a relaunch from the main checkout
(the only place the data lives), ran the OLD code and started redoing 72 finished stages
instead of skipping them; it took a commit–push–pull round trip to make the fix real. ~40
minutes lost, no data harmed [confirmed, 2026-09-23]. Every ordinary editing reflex — edit,
run, see the change — is silently wrong in that split, and with a long job the symptom arrives
minutes later as *unexpected work*, not as an error. Cheap mitigation that needs no harness
change: **a long-running runner records the sha of its own source at start, plus whether that
tree was dirty, and prints both in its report** — so "which version produced this?" is
answerable afterwards. Better: the launcher states up front "this runs from <main>, your edits
are in <worktree>, N files differ".

**Rule:** a session declares ONE data root and ONE artifact root at the start, and the harness
resolves both the same way for the session and every subagent. Keep run and output directories
out of `.claude/` so they are writable by design rather than by exception. Adding allowlist
entries treats the symptom; the roots are the disease.

## Review fan-outs must not pin the session's own checkout

Nine review agents pointed at one worktree pinned to a PR ref is correct for read-only review
and still wrong: the worktree becomes un-switchable for the whole run, because any branch change
for unrelated work would pull the tree out from under the readers mid-flight. Serialising
instead cost hours of wall-clock on work that had no dependency on the review [concluded,
2026-09-23 dp]. **Rule:** fan-out reads from a throwaway worktree, or at object level
(`git -C <repo> show <ref>:<path>`), never from the session's own checkout.

## A skill that writes into a repo must check the ignore status of the exact path

The pr-check skill documents its report directory as living under `.claude/`, "which is
gitignored — confirm the consuming repo ignores it". In dp, `.claude/` is only *partially*
ignored: `.claude/docs/` and `.claude/rules/` are deliberately tracked. So the verdict file of
a security review — file:line detail of weaknesses — would have been committed by the next
`git add -A` [confirmed, 2026-09-23]. **Rule:** verify the exact path with the repo's own
ignore check at run time and refuse to write when it is tracked. A convention about the parent
directory is not a guarantee about the path.

## `Write(path)` rules are ignored — file-writing tools are governed by `Edit(path)`

Building a narrow allowlist for an unattended headless wave: `Write(path)` allow/deny rules are
ignored with a warning, and only `Edit(path)` rules govern the file-writing tools. **A deny list
written with `Write(...)` alone silently denies nothing** [confirmed, 2026-09-22, C session].
Use `Edit(path)` for both allow and deny in every template, and lint for `Write(path)` rules.

## A headless template needs its shared resources declared, or they become guesses

An overnight worker needed the research vault (a sibling repo) and the memory inbox
(`~/agent/inbox/memory/`). Both lay outside its allowlist, so sources stayed `[guess]` and a
durable lesson went unwritten — the run completed and quietly produced weaker work [confirmed,
2026-09-22]. **Rule:** every headless template carries a read-only rule for the shared
reference material and an append-only rule for the memory inbox. An unattended agent cannot ask.

## Match `ssh` as the command, not as a substring

An ssh-blocking hook refused a heredoc that *edited a runbook containing ssh commands for the
human to run*; nothing executed ssh [confirmed, 2026-09-22]. The same false positive hit a
`grep` whose pattern contained the word. **Rule:** a command-blocking hook matches the first
token of each pipeline segment, not anywhere in the string. A hook that blocks writing *about*
a command teaches agents to route around the hook, which is the opposite of the intent.

## In a review panel, the panel sets the price — not the diff

Measured across 19 recorded `pr-check` runs on one Max plan (2026-09-12→22) [confirmed, from
the skill-run-cost log]: runs whose scope pulled in the UI reviewers (accessibility, usability,
frontend) cost ~890k subagent tokens each; runs scoped to Python alone cost ~320k — a 3x
difference from the scope globs, not from the change under review. Within a scope, diff size
barely moved the number: a 62-line and a 262-line diff both cost ~328k. Worst single run:
1.37M on a 424-line PR. A 61-line PR that convened no panel cost 0.

**Levers, in order of effect:** (1) make the scope globs narrow enough that UI reviewers convene
only on real UI diffs; (2) let small or non-matching diffs convene no panel at all; (3) only
then worry about the diff. ## Conversation length outranks model tier as a cost driver

Same measurement, corrected and looked at whole [confirmed, 2026-09-23]: **one** conversation —
8 days, 6,498 messages, spanning eight PRs — was 22.0M of 41.0M input+cache-write tokens, i.e.
54% of everything that user spent. Across all sessions, cache reads were **56x** fresh input:
a long conversation re-reads its own history on every turn, so its cost grows superlinearly
while the work per turn stays the same. Running a top-tier model through mechanical stretches
(doc edits, git hygiene, re-reading diffs) is real waste, but capping the tier would not have
changed the order of magnitude — **ending the conversation at a natural boundary would have**.

Levers, cheapest first: (1) end and hand off long sessions at a boundary (the rolling STATE.md
+ dated decision log exists precisely so this costs nothing); (2) scope review panels (~3x);
(3) route mechanical subagents to a cheaper model where a skill spawns them.

**Measurement trap on the way there:** the same conversation appeared in two worktree
directories and was first counted as two sessions, inflating the total by 36%. Deduplicate by
message content, not by transcript file, before quoting any number.

## Measure the account that does the work, not the one you can read

When work moved from the admin user to a dedicated agent user, cost visibility went with it:
the agent's transcripts are mode 700 (correctly), so the only measurable trace was its
skill-cost log [confirmed, 2026-09-23]. Do not solve this by reading another user's transcripts,
directly or via `sudo -u`. Have each session append ONE line — session id, project slug, model,
token counts, skills invoked, wall-clock — to a shared append-only file the operator can read.
Slugs only: no paths, prompts or file names in a file with wider read access than the
transcripts it summarises.

## A role's routine exception will grow to cover everything it touches

A director role's brief said it keeps "record commits" (STATE, DECISIONS, inboxes), and its
predecessors pushed those routinely. Over two days the same session also pushed analysis files,
a script and config rows — about fifteen pushes — although the project rule was "ask before
pushing analysis, data, scripts or config unless he said push this session", and he had not
[confirmed, 2026-09-23: the pushes are in origin/main]. Nothing blocked it: the rule lived in a
memory file that reads as being about paper writing, the brief never said where "records" end,
and no hook guarded `git push` for non-record paths.

**Rule:** a standing exception is defined by a **path list**, not by a noun. Write it in the
brief and the STATE file, not only in memory, and enforce it where the action happens — a
pre-push check that lists the non-record paths in the outgoing commits and requires a
per-session approval token. An exception that depends on each session inferring its own scope
is not a rule; it is a habit, and habits generalise.

## A repo-local skill under a gitignored `.claude/` cannot be fixed by pull request

The fix for a stale `local-e2e` skill could not travel: that repo ignores `.claude/*`, so the
skill file is invisible to git and every checkout carries its own private copy, drifting
separately [concluded, 2026-09-23]. Either un-ignore `.claude/skills/` so skills are reviewable
and shareable, or keep skills in the shared harness repo and install them. A skill that cannot
be reviewed is also a skill whose staleness nobody can see.

## The deployed copy of a guard is not the guard in the repo

The `block_ssh` hook running on the Mac emitted a message that does not exist in this repo's
version, and blocked cases the repo's policy allows — i.e. an older copy had been installed and
then diverged [confirmed, 2026-09-23: observed refusal text vs the repo source]. Guards are
installed artifacts; the repo is only the source. Version the installed copy (a `--version` or a
hash the installer records) and check it, or the lesson you write in the repo never reaches the
machine where the failure happens.

## Cross-session handoffs that cite a memory key must carry the content

A handoff referred a session to a stored memory for a procedure; that project's memory
directory was empty, so the procedure was unreachable and the session fell back to asking the
human [confirmed, 2026-09-23]. **Rule:** a pointer is only as good as the store behind it —
either verify the key exists when writing the handoff, or inline the procedure.

## References

- Permissions — subprocess internals are not re-validated; Bash rule syntax:
  <https://code.claude.com/docs/en/permissions>
- Hooks reference — exit-code contract and the JSON `permissionDecision` method:
  <https://code.claude.com/docs/en/hooks>
- `anthropics/claude-code#48762` — hardcoded compound-command guardrail strings
  ("…manual approval required to prevent path resolution bypass") fire above the
  permissions allowlist: <https://github.com/anthropics/claude-code/issues/48762>
- `anthropics/claude-code#45421` — the "Newline followed by # inside a quoted
  argument…" AST-parser warning bypasses sandbox auto-approve:
  <https://github.com/anthropics/claude-code/issues/45421>
- Official PreToolUse Bash command-validator hook example (same exit-code pattern):
  <https://github.com/anthropics/claude-code/blob/main/examples/hooks/bash_command_validator_example.py>

## Measure before you optimise a panel: the diff is not where the findings come from

The obvious cost fix for a review panel is to hand every reviewer a prepared evidence pack and
stop them exploring the repo. Measured on a real 449-line PR before adopting it [confirmed,
2026-09-23, wiki-polis #450, 4 reviewers + cross-review + synthesis = 9 agents, 1.05M subagent
tokens, 20m]: of **31 findings, 25 required reading outside the diff**, including **4 of the 7
must-fix** — an RTL precedent that existed only in one stylesheet rule, a whole-component read
showing an `aria-label` hiding its visible label, a tree-wide glyph grep, and a backend fallback
constant whose value made a newly added test vacuous.

So the pack is a **floor, not a ceiling**: it removes *duplicated* reads across reviewers and
gives them a shared cacheable prefix, but blindfolding the panel buys tokens and pays in
defects. Two of those four findings were cheap greps a reviewer might have requested; two
(a precedent hunt and a full component read) are not things you know to ask for unless you
already suspect them — which is the entire value of a reviewer.

The generalisable rule: **instrument the thing you are about to optimise.** One flag per
finding (`evidence=diff|repo`) turned an architectural argument into a number, and it cost one
line in the reviewer prompt.

## A scope flag that fires on prose costs a whole review pass

Same run: the `SENSITIVE` flag fired on the words "log in", "OAuth" and "session" appearing in
*translated message strings* and docs, not in code [confirmed]. That flag gates a security
review — the most expensive conditional step in the procedure. Apply sensitive-content patterns
to code paths only, exclude i18n catalogues, docs and changelogs, and make the verdict say when
a flag fired on text rather than code.
