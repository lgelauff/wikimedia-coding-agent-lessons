# Confidentiality redesign note (block_secret_read + block_ssh)

Written 2026 after a security+AI panel reviewed the `block_secret_read` guard.
**Decision to make:** whether to go beyond the tripwire fix already applied.

## What was already fixed (shipped)
The two guards were **narrowed** to stop the constant false positives:
- `block_secret_read`: matches only **path-anchored** secret shapes on `basename`
  (`.env*`, `id_rsa`/`ed25519`, `.pem/.p12/.pfx`, the central-store path, and
  `secret`/`credential` only in a **data** filename like `my-secrets.txt`). No more
  bare-word "secret" — so `grep secret`, editing the guard's own source, and the
  mandated pre-push secret-scan all work again. Env matching is an explicit
  allowlist (no bare `*_KEY`/`*_TOKEN`, so `PRIMARY_KEY`/`CSRF_TOKEN` pass). Verdict
  is now **`ask`** (human decides), not hard-`deny` (which trained route-arounds).
- `block_ssh`: strips quoted spans before matching, so `ssh` mentioned in an echo
  or commit message no longer trips it — while `sudo ssh` and `rsync -e "ssh"` are
  still caught.

## The honest limit (why this is only a tripwire)
A **PreToolUse hook sees only tool INPUT**, so it can never be a confidentiality
*boundary*. It is bypassable in one line and by design cannot stop a secret VALUE
that a blessed script prints. Confirmed leak paths it does NOT cover:
`python3 -c "open('.env').read()"`, `base64`/`dd`/`git show HEAD:.env`, `< .env`
redirection, bare `printenv`, globs, the **Grep tool**, MCP filesystem tools,
`WebFetch(file://)`. On a single-user Mac the agent runs **as you**, so it can
already read `~/.config/agent-secrets/.env` regardless. Treat the hook as
best-effort friction against an *accidental* `cat`, never as protection against an
evading or injected agent.

## The real design (decide separately — NOT yet done)
1. **Containment** (the actual control): keep real secrets out of the agent's
   reach — not in its env, readable only by helper scripts (ideally a separate uid,
   or at least loaded on-demand and never exported into the agent's shell). If no
   secret value is present, no command can leak it. *(Heavy on a personal Mac; the
   separate-uid version may be more than it's worth — evaluate.)*
2. **PostToolUse output redaction** (tractable defense-in-depth): a hook that masks
   known secret **values** in tool stdout/tracebacks — this is the only thing that
   catches the residual "a script printed its own secret" case that no input filter
   can. Recommended if we do anything more.
3. **Demote the narrowed hook** to a documented tripwire; don't count it as the
   security property.

**Recommendation:** the tripwire fix is enough for day-to-day. Do (2) if/when secret
handling gets heavier; (1) only if the threat model actually warrants it. Don't
reflexively build containment — decide it deliberately.
