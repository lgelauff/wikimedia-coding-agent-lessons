# Working in this repo

This file is loaded automatically at the start of every OpenCode session in this directory.
It is the durable contract. For *what to work on next*, read
`.claude/next-session-2026-09-17.md` — that file is replaced each session; this one is not.

## First thing: read the current handoff

```
.claude/next-session-2026-09-17.md
```

It states the current state, the ordered next steps, known defects, open questions, and the
traps. Treat it as authoritative for the task at hand. Its predecessor
`.claude/harness-handoff-2026-09-12.md` explains *why* the design is what it is; the design
itself is `.claude/harness-design-2026-09-12.md`, where **Revisions 2–6 supersede the numbered
sections where they conflict**.

**Do not paste the contents of these files into a chat or any external tool.** They describe a
threat model and name paths. Read them locally.

## The operating contract — non-negotiable

- **`~/dev/` is the only writable location.** `~/Data_pii/` (raw PII, mode 700) and
  `~/.config/voice-samples/` are denied to every agent on every harness. If a rule blocks you
  from doing the work, say so and stop — that is a design conversation, not an obstacle.
- **Never allowlist arbitrary code execution.** Not `python:*`, not `npx *`, not `uv run`, not
  `make *`, not `docker run`, not `ssh`, not `sudo`. Exact invocations or bundled script paths
  only.
- **`git -C <path>`, never `cd <path> && git`.** The latter can never be allowed and prompts
  forever.
- **APIs over scraping.** Respect `robots.txt` and rate limits; back off on `Retry-After`. A
  robots.txt you cannot read is not permission.
- **No participant or research-subject data through third-party model hosts.** Participant data
  via `claude-code` is allowed (Stanford institutional agreement); via `openrouter`/`mistral` it
  is denied. Raw PII reaches no provider.
- **Truthfulness is a feature.** Prefer "I don't know" / "unverified" to a confident guess.
  Never state a number you have not computed.
- **Voice work is a bounded transform.** Organise and transcribe; never co-author; never
  substitute generic AI polish.
- **Do not commit or push unless asked.**

## Reporting discipline

Label every non-trivial claim **[confirmed]** (you observed it — say where) / **[concluded]**
(inferred — state the inference) / **[guess]** (unverified). Any "fixed" or "reproduced" claim
carries a `Verified by:` line naming the command or observation. If it is not verified, write
"unverified" — do not soften or omit it. Report failures plainly; do not overclaim success.

## Scripts are the interface, not inline shell

Repeated shell logic belongs in `agent-tooling/scripts/`, and policies in
`agent-tooling/policies/` as executables that exit `0` (allow) / non-zero (block) with a
human-readable reason. An agent must never parse another agent's event format — that is what
the adapter layer is for.

## Guards — run these, they encode real failures

```bash
python3 agent-tooling/scripts/check_skill_vars.py   # undefined $VAR in any SKILL.md
python3 agent-tooling/scripts/audit_skills.py       # cross-skill contradictions
python3 -m unittest agent-tooling.scripts.tests.test_audit_skills \
                    agent-tooling.scripts.tests.test_check_skill_vars \
                    agent-tooling.scripts.tests.test_install
```

Every guard must be shown to *catch* its failure class. A check that only ever reports clean is
worse than none, because it is trusted.

## Layout

| Path | What |
|---|---|
| `agent-tooling/scripts/` `playbooks/` `policies/` `git-hooks/` | **agent-agnostic core** — no host coupling |
| `agent-tooling/skills/` `hooks/` `settings/` `.claude-plugin/` | Claude Code adapter |
| `agent-tooling/adapters/opencode/` | OpenCode adapter — agents, plugin, `install.py`, machine config |
| `.claude/` | gitignored working notes. **Nothing here is in git and nothing is recoverable** |

Authority for conventions: `agent-tooling/ARCHITECTURE.md` and `agent-tooling/conventions.md`.
Where this file and those disagree, they win — and this file should be corrected.

## What is not yet true

Nothing is deployed. The Mac has no `~/.config/opencode/opencode.json`, so OpenCode is running
at permissive defaults and **none of the boundary rules above are enforced yet** — they are
conventions until `install.py --apply` runs and denies are verified. The handoff's §3 explains
how to settle that, and why it invalidates everything else if it fails.
