# Hooks

Claude Code **adapter** hooks — the thin, product-specific layer (PreToolUse/PostToolUse event in, decision out). Each pairs with a lesson in [`../../../../claude-code/lessons.md`](../../../../claude-code/lessons.md): the lesson is the *why*, the hook is the *what you run*. All read their secrets from the **environment** — none contain hardcoded keys. Where a hook's decision logic is reusable beyond Claude Code, it should move to [`../../../policies/`](../../../) with this hook becoming a thin wrapper (see [`../../../ARCHITECTURE.md`](../../../ARCHITECTURE.md)).

| Hook | Event | What it does |
|---|---|---|
| `block_ssh.py` | PreToolUse | Blocks `ssh` to remote hosts (present commands for the human to run instead). |
| `block_zotero.py` | PreToolUse | Blocks writes to a protected Zotero path. |
| `github_write_permission.sh` | PreToolUse | Gates GitHub *write* operations (push/PR/merge) behind an explicit prompt. |
| `openrouter_permission.sh` | PreToolUse | Asks permission for the first OpenRouter API call per model per session. |
| `webfetch_content_check.py` | PostToolUse | Inspects fetched content (injection / unexpected-instruction check). |
| `pre-commit` | git hook | Runs `detect-secrets-hook` on staged files; blocks commits with likely secrets. |

## Wiring

These are **git/Claude hooks**, not skills — the harness runs them, so they go in config, not in a skill body. Copy the ones you want into `~/.claude/hooks/` (or reference them in place) and wire in `~/.claude/settings.json`:

```jsonc
{
  "hooks": {
    "PreToolUse": [
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/block_ssh.py" }] },
      { "hooks": [{ "type": "command", "command": "~/.claude/hooks/github_write_permission.sh" }] }
    ],
    "PostToolUse": [
      { "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/webfetch_content_check.py" }] }
    ]
  }
}
```

`pre-commit` goes in your repo's `.git/hooks/` (or a global `core.hooksPath`); it needs `detect-secrets` installed (`pipx install detect-secrets`).

Secrets the hooks use (e.g. `MISTRAL_API_KEY` for the review path) come from your environment — set them in your shell profile, never in these files.
