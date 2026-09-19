# Permission exceptions — the UX

What happens when a harness hits a permission it does not have, mid-session, and how an
exception is granted. Companion to [`permission-framework.md`](permission-framework.md)
(the layers) and [`per-repo-write-grants.md`](per-repo-write-grants.md) (the durable
per-repo grant checklist).

## The v1 reality [confirmed]

OpenCode 1.18.30 answers a permission request with `reply("always")` by adding the
request's `always` patterns to an **in-memory `approved` ruleset scoped to the project
directory**. It survives later sessions **in the same directory**, and is lost on
restart. It is not a durable grant and not truly "per session" — the directory is the
scope. Do not build anything on it that must persist.

Plugins **cannot `ask`** (trap #7): a plugin can only deny by throwing. So any decision
that needs the human's judgement has to live either in a static permission pattern or in
a written request the human acts on. That constraint decides this UX.

## The decision

Exceptions are **explicit and human-granted, never silent**. Three routes, in order of
scope:

| Route | Lifetime | Use for |
|---|---|---|
| Answer the prompt **once** | one tool call | a genuine one-off |
| Answer **`always`** | the project directory, in memory, until restart | a repeated op within this session |
| A **written request + a narrow grant** | durable (config) | anything that must survive a restart |

The durable path today is the `permission` block (global or the repo's L3
`.claude/settings.local.json` / `opencode.json`); the core v2 `PermissionSaved` table is
the intended persistent path but is **not wired** in 1.18.30. Plan-scoped grants were
researched and the user said **wait** (`.claude/permission-plan-scoped-2026-09-19.md`).

## The written-request format

When a harness is blocked and believes the work is legitimate, it does not retry and
does not route around the block. It writes one message to the human:

1. **What was tried first** — the sanctioned route, and why it did not serve.
2. **Why** the work needs this specific permission (exact command or path).
3. **Blast radius** — what it would touch, and what data leaves.

The `webfetch` guard's deny message is the reference wording; any future guard should
reuse this shape rather than inventing a one-click pop-up.

## What is never granted

- **Arbitrary execution** — no `python:*`, `npx *`, `uv run`, `make *`, `docker run`,
  `ssh`, `sudo`, or bare-interpreter patterns. Exact invocations or bundled script paths
  only.
- **The crown jewels** — `~/Data_pii/` and `~/.config/voice-samples/` are denied to every
  agent on every harness. That is not negotiable by an exception; if a rule blocks the
  work, stop and say so.
- **One-shot residue** — a pattern tied to a single past command belongs in neither the
  `always` set nor a config; answer once.

## Granting and revoking

- **Grant:** follow [`per-repo-write-grants.md`](per-repo-write-grants.md) — show the
  proposed config, get an explicit yes, write it at the highest safe layer, verify.
- **Revoke:** remove the pattern from the layer it was added to, then
  `install.py --check` (global) or re-read the L3 file. An `always` grant needs nothing —
  it dies with the session.
