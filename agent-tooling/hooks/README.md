# Hooks

Claude Code hooks — the product-specific layer (PreToolUse/PostToolUse event in, decision out). Each pairs with a lesson in [`../../claude-code/lessons.md`](../../claude-code/lessons.md): the lesson is the *why*, the hook is the *what you run*. All read their secrets from the **environment** — none contain hardcoded keys. Where a hook's decision logic is reusable beyond Claude Code, extract it to `../policies/` with this hook becoming a thin adapter (see [`../ARCHITECTURE.md`](../ARCHITECTURE.md)). Done for `block_ssh` (→ `policies/is_ssh_command.py`) and `github_write_permission` (→ `policies/classify_github_op.py`): the hook parses the Claude event, the policy makes the call. (`webfetch_content_check` stays self-contained — its short-content check is a heuristic, not a reusable policy.)

| Hook | Event | What it does |
|---|---|---|
| `block_ssh.py` | PreToolUse | Blocks `ssh`/`scp`/`sftp`/rsync-over-ssh to remote hosts (present commands for the human to run instead). Adapter over `policies/is_ssh_command.py`; fails closed. |
| `memory_guard.py` | PreToolUse | Blocks launching a `Workflow` (or backgrounded `Agent`) under **critical** OS memory pressure, to prevent OOM crashes from fan-outs. Uses macOS `kern.memorystatus_vm_pressure_level` (≥4) / Linux `MemAvailable%`; **not** a free-% threshold (chronically low on macOS). Tunable: `WORKFLOW_BLOCK_PRESSURE_LEVEL` (default 4; set 5 to disable), `WORKFLOW_MIN_FREE_PCT` (Linux, default 8). Fails open. |
| `block_zotero.py` | PreToolUse | Blocks writes to a protected Zotero path. |
| `github_write_permission.py` | PreToolUse | Gates GitHub ops: **ask** on any write (push, pr/issue create/comment/review/edit/close/reopen/merge, release, workflow run, `gh api` write), **deny** on catastrophic (repo delete/archive, release delete). Reads pass. Adapter over `policies/classify_github_op.py`; emits the modern `permissionDecision` schema. (Replaced the old `.sh`, which read the wrong JSON path and never fired.) |
| `git_hygiene_session.py` | SessionStart | On entering a repo, warns about unsaved/at-risk work — uncommitted, untracked, stashes, unpushed commits, and dirty linked worktrees — via `additionalContext` so the assistant surfaces it first. Silent when clean. Adapter over `scripts/git_hygiene.py` (also runnable standalone: `--repo` / `--root` for a daily launchd scan of many repos). Fails open. |
| `dev_stack_reminder.py` | UserPromptSubmit | On a farewell prompt (bye/goodnight/ttyl…), if a configured dev-stack container is still running, reminds you how to stop it. Config-driven via `./.claude/dev-stack.json` (see `dev-stack.example.json`); no config = silent no-op. Fails open. |
| `openrouter_permission.sh` | PreToolUse | Asks permission for the first OpenRouter API call per model per session. |
| `webfetch_content_check.py` | PostToolUse | Warns when fetched content is suspiciously short (likely a redirect/login/error page, not the resource) — treat as UNVERIFIED. Self-contained heuristic; advisory, fails open. |
| `tool_token_log.py` | PostToolUse | Appends an **estimated** token-cost line per tool/skill call (input+output bytes ÷4) to a JSONL log. Never blocks. A hook can't see real API token accounting, so this is a proxy for "which tools/skills are context-heavy"; for exact numbers parse the transcript `usage` fields. Log path: `$TOOL_TOKEN_LOG`, else `~/.claude/tool-token-logs/<repo>.jsonl` — **one file per repo, deliberately**: a single machine-global log pools skill-name and call-pattern metadata from private and third-party repos alongside public ones. Logs live under `~/.claude`, never inside a repo, so they cannot be committed by accident. Summarize: `jq -s 'group_by(.tool)[]\|{tool:.[0].tool,calls:length,est_tokens:(map(.est_tokens)\|add)}' ~/.claude/tool-token-log.jsonl`. |
| `pre-commit` | git hook | Runs `detect-secrets-hook` on staged files; blocks commits with likely secrets. |

## Wiring

**Installed as part of the plugin, these wire automatically** via [`hooks.json`](hooks.json) (paths use `${CLAUDE_PLUGIN_ROOT}`). Wired by default: `block_ssh`, `memory_guard`, `github_write_permission`, `openrouter_permission` (PreToolUse), `git_hygiene_session` (SessionStart), `dev_stack_reminder` (UserPromptSubmit), and `webfetch_content_check` + `tool_token_log` (PostToolUse). `block_zotero.py` ships as a file but is **not** wired (personal path block — wire it yourself if you want it).

> ⚠️ **Dedup if you already wired these manually.** If your `~/.claude/settings.json` already references copies of these hooks (e.g. from before this plugin existed), remove those manual entries after installing the plugin — otherwise each hook fires twice. The plugin's `hooks.json` is now the single source.

For **non-plugin** use (copying hooks into `~/.claude/hooks/` and wiring by hand), the same structure applies with literal paths instead of `${CLAUDE_PLUGIN_ROOT}`.

`pre-commit` is a **git** hook, not a Claude hook — it lives in `../git-hooks/`, goes in your repo's `.git/hooks/` (or a global `core.hooksPath`), and needs `detect-secrets` (`pipx install detect-secrets`).

Secrets the hooks use (e.g. `MISTRAL_API_KEY` for the review path) come from your environment — set them in your shell profile, never in these files.
