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
- **Match `tool_name` first and exit 0 immediately** if it isn't the tool you
  guard — cheap, and prevents false positives on unrelated calls.
- **Exit-code contract:** `0` = allow · `2` + stderr = block and show the message to
  Claude · any other nonzero = allow but log. Reserve `2` for genuine blocks;
  advisory warnings use `exit 0` + a stderr note.
- **Human-facing text goes to stderr** (stdout is not surfaced the same way). Make
  it actionable — say what to do instead and, for blocks, "do NOT retry".
- **Fail open for advisory guards; fail *closed* only for hard security boundaries**
  (e.g. blocking `ssh`/`scp`/`rsync -e ssh`).
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
