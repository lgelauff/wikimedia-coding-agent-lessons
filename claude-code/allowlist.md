# Permission-allowlist methodology

Fewer permission prompts comes mostly from *coding hygiene*, not from a big allowlist. The reusable solution is a method + a few rules, not a copied list (most truly-safe read-only commands Claude Code already auto-allows, and a personal allowlist carries project-specific entries that shouldn't be shared).

## Method (per machine, ~5 min)

1. Let Claude scan your recent transcripts for the read-only commands that keep prompting (the `fewer-permission-prompts` skill does this), and add the high-frequency, safe ones to `~/.claude/settings.json` under `permissions.allow`.
2. Prefer **bundled script paths** over widening command access — see "Scripts over inline bash" in [`conventions.md`](conventions.md). One `Bash(<repo>/scripts/foo.sh*)` entry replaces a dozen ad-hoc-pipeline prompts.

## Rules (the part that's actually reusable)

**Never allowlist arbitrary code execution.** Each of these is equivalent to "allow anything":
`Bash(python:*)`, `Bash(python3:*)`, `Bash(node:*)`, `Bash(bash -c *)`, `Bash(sh -c *)`, `eval`, `Bash(uv run *)`, `Bash(npx *)`, `Bash(npm run *)`, `Bash(make *)`, `Bash(gh api:*)` (can POST/DELETE), `docker run`/`exec`, `ssh`, `sudo`. Allowlist the **exact** safe invocation (`Bash(bun run typecheck)`) or a **bundled script path** instead.

**Don't list what's already auto-allowed.** Claude Code auto-allows most read-only tools (`cat`, `ls`, `grep`, `rg`, `git status/log/diff/show/branch`, `gh pr view/list/diff`, `docker ps/logs/inspect`, etc.). Adding them is noise.

**Keep mutations explicit and personal.** `git push`, `git commit`, `gh pr create` etc. are reasonable *personal* allows if you've opted in, but they don't belong in a shared baseline — leave them in your own `settings.json`, not here.

## Safe-to-share baseline snippet

Conservative additions that are read-only and not auto-allowed. Merge into `permissions.allow` (de-dupe against what you have):

```json
{
  "permissions": {
    "allow": [
      "WebSearch",
      "Read(//tmp/**)"
    ]
  }
}
```

Everything beyond this is best generated per-machine from your own usage (step 1) rather than copied.
