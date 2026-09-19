# Per-repo write grants — the checklist

How an agent gets **persistent write access to a repository**, and how that grant is
reviewed before it lands. A *write grant* is a permission entry that lets a harness
create or modify files in a repo instead of asking on every operation.

Two facts up front, because they decide the whole procedure:

- **Persistent grants are config, not a database.** In OpenCode 1.18.30 the durable
  mechanism is the generated `permission` block in `~/.config/opencode/opencode.json`
  (owned by `adapters/opencode/install.py`), plus a project-local `opencode.json` /
  `.opencode/agents/*.md`; in Claude Code it is the repo's `.claude/settings.local.json`
  (L3 in [`permission-framework.md`](permission-framework.md)). The core v2
  `PermissionSaved` table is the intended persistent path but is **not wired** in
  1.18.30 — do not design against it.
- **The confirmation gate is on the config, not on reads.** Reads are permissive by
  design; the thing a human must approve is a change to a repo's permission config.
  Show the proposed change and get an explicit yes before it lands
  (`permission-framework.md`).

A write grant is filesystem access. It is **not** a network grant — the `webfetch` door is
governed separately by the [Mandated Services Registry](mandated-services.json) and its
plugin guard. Direct network access from scripts is **not** covered by that registry
(stated in its `$comment`); keep the two concerns apart.

## Placement: highest safe, universal layer

A permission lives at the **highest layer where it is still both safe and universal**
(`permission-framework.md`). If a grant is only true of one repo, it is L3; if it is
universal and low-risk, promote it to L1/L2.

| Layer | File | Holds | Does **not** hold |
|---|---|---|---|
| L1 global | `~/.config/opencode/opencode.json` (`permission`), `~/.claude/settings.json` | universal low-risk allows | repo specifics; risky/destructive ops |
| L2 plugin | `agent-tooling/policies/` + the OpenCode plugin | deny-only decisions (OpenCode cannot `ask`) | static repo allows |
| L3 project | `<repo>/opencode.json`, `<repo>/.opencode/agents/*.md`, `<repo>/.claude/settings.local.json` | only genuinely repo-specific allows: this repo's test/venv/db/dev-stack entries | anything universal; one-shot residue |

## The checklist

1. **State the need concretely.** Name the exact command(s) or path(s) the harness must
   run without prompting, and why the default (ask) is wrong for them. "It keeps
   asking" is not a need.
2. **Classify it.** Universal and low-risk → L1. Repo-specific → L3. Destructive or
   one-shot → **nowhere** (never persist; see *What is not a grant*).
3. **Check for arbitrary execution.** The grant must be an exact invocation or a
   bundled script path — never `python:*`, `npx *`, `uv run`, `make *`, `docker run`,
   `ssh`, `sudo`, or a bare interpreter. A grant that allows arbitrary execution is a
   boundary hole wearing an allow-list's clothes.
4. **Prefer the narrowest rule.** A specific `bash` pattern beats a broad glob; an
   exact file path beats a directory. Remember OpenCode evaluates **last-match-wins**,
   so a broad allow placed after a specific deny will override it.
5. **Show the proposed diff** — the exact JSON that would be added, at which layer, for
   which harnesses. Include what it does *not* grant.
6. **Get an explicit yes.** No write until the human approves the shown config. This is
   the confirmation gate; do not treat a prior "go ahead" on the work as approval of
   the grant.
7. **Write it** at the chosen layer, backing up first (`install.py` backs up the global
   config; do the same for an L3 file).
8. **Verify it** (see below) and report the exact observation, not the intent.
9. **Record the reason** next to the grant (the manifest's `reason`, or a comment) so a
   future audit can tell a live grant from residue.

## Template: committed per-repo manifest (proposed, not yet wired)

A repo can carry a small committed manifest so its grants are reviewable in the repo
rather than only in a machine-local config. `install.py` **does not read this yet** —
propose the format and wire it deliberately before relying on it.

```json
{
  "repo": "lgelauff/example",
  "path": "~/dev/example",
  "harnesses": ["code", "analysis"],
  "write": {
    "edit": "allow",
    "bash": {
      "python3 -m pytest *": "allow",
      "uv run ruff *": "allow"
    }
  },
  "not_granted": ["git push", "network"],
  "verified": "2026-09-19",
  "reason": "test runner only; see PR #12"
}
```

The `not_granted` field is documentation, not enforcement — it records the boundary the
grant was reviewed against.

## Verify a grant

- **Global config:** `python3 agent-tooling/adapters/opencode/install.py --check` →
  `in sync` (exit 0). A hand-edit shows as drift, which is the point.
- **L3 config:** re-read the repo's `opencode.json` / `.claude/settings.local.json` and
  confirm the entry is present and correctly ordered (specific rules after the catch-all).
- **Behaviour:** perform the exact operation the grant covers and confirm it does not
  prompt. Report the command and the result; "should work now" is not verification.

## What is not a grant

- **One-shot residue** — dead PIDs, a one-time `mv`/`rm`, line-range readers, anything
  tied to a single past edit. Delete on sight (`permission-framework.md`).
- **Arbitrary execution** — step 3 above.
- **Read scopes** — reads are permissive; granting one is not a write grant.
- **A path outside the boundary** — `~/Data_pii/` and `~/.config/voice-samples/` are
  denied to every agent on every harness. That is not negotiable by a grant; if a rule
  blocks the work, stop and say so.
