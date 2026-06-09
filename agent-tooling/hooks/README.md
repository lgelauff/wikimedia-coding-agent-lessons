# Hooks

Claude Code hooks — the product-specific layer (PreToolUse/PostToolUse event in, decision out). Each pairs with a lesson in [`../../claude-code/lessons.md`](../../claude-code/lessons.md): the lesson is the *why*, the hook is the *what you run*. All read their secrets from the **environment** — none contain hardcoded keys. Where a hook's decision logic is reusable beyond Claude Code, extract it to `../policies/` (planned) with this hook becoming a thin wrapper (see [`../ARCHITECTURE.md`](../ARCHITECTURE.md)).

| Hook | Event | What it does |
|---|---|---|
| `block_ssh.py` | PreToolUse | Blocks `ssh` to remote hosts (present commands for the human to run instead). |
| `block_zotero.py` | PreToolUse | Blocks writes to a protected Zotero path. |
| `github_write_permission.sh` | PreToolUse | Gates GitHub *write* operations (push/PR/merge) behind an explicit prompt. |
| `openrouter_permission.sh` | PreToolUse | Asks permission for the first OpenRouter API call per model per session. |
| `webfetch_content_check.py` | PostToolUse | Inspects fetched content (injection / unexpected-instruction check). |
| `pre-commit` | git hook | Runs `detect-secrets-hook` on staged files; blocks commits with likely secrets. |

## Wiring

**Installed as part of the plugin, these wire automatically** via [`hooks.json`](hooks.json) (paths use `${CLAUDE_PLUGIN_ROOT}`). Wired by default: `block_ssh`, `github_write_permission`, `openrouter_permission` (PreToolUse) and `webfetch_content_check` (PostToolUse). `block_zotero.py` ships as a file but is **not** wired (personal path block — wire it yourself if you want it).

> ⚠️ **Dedup if you already wired these manually.** If your `~/.claude/settings.json` already references copies of these hooks (e.g. from before this plugin existed), remove those manual entries after installing the plugin — otherwise each hook fires twice. The plugin's `hooks.json` is now the single source.

For **non-plugin** use (copying hooks into `~/.claude/hooks/` and wiring by hand), the same structure applies with literal paths instead of `${CLAUDE_PLUGIN_ROOT}`.

`pre-commit` is a **git** hook, not a Claude hook — it lives in `../git-hooks/`, goes in your repo's `.git/hooks/` (or a global `core.hooksPath`), and needs `detect-secrets` (`pipx install detect-secrets`).

Secrets the hooks use (e.g. `MISTRAL_API_KEY` for the review path) come from your environment — set them in your shell profile, never in these files.
