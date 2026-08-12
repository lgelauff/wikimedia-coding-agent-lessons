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
