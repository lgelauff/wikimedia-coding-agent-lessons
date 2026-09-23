# Working in this repo

This file is loaded automatically at the start of every OpenCode session in this directory.
It is the durable contract. For *what to work on next*, read
`.claude/next-session-2026-09-19.md` — that file is replaced each session; this one is not.

## First thing: read the current handoff

```
.claude/next-session-2026-09-19.md
```

It states the current state, the ordered next steps, known defects, open questions, and the
traps. Treat it as authoritative for the task at hand. The design-era predecessor
`.claude/harness-handoff-2026-09-12.md` explains *why* the design is what it is; the design
itself is `.claude/harness-design-2026-09-12.md`, where **Revisions 2–6 supersede the numbered
sections where they conflict**. The previous state is archived at `.claude/handoff-2026-09-17.md`.

**Do not paste the contents of these files into a chat or any external tool.** They describe a
threat model and name paths. Read them locally.

## The operating contract — non-negotiable

- **The boundary.** `~/dev/`, `~/agent/`, and `/usr/local/bin/` are the only writable locations
  (the latter two via `extra_allowed_paths`). `~/Data_pii/` (raw PII, root-owned, mode 700) and
  `~/.config/voice-samples/` are denied to every agent on every harness. If a rule blocks you
  from doing the work, say so and stop — that is a design conversation, not an obstacle.
- **Never allowlist arbitrary code execution.** Not `python:*`, not `npx *`, not `uv run`, not
  `make *`, not `docker run`, not `ssh`, not `sudo`. Exact invocations or bundled script paths
  only.
- **`git -C <path>`, never `cd <path> && git`.** The latter can never be allowed and prompts
  forever.
- **APIs over scraping.** Respect `robots.txt` and rate limits; back off on `Retry-After`. A
  robots.txt you cannot read is not permission.
- **Fetch only mandated sources; a blocked fetch goes through the Internet Archive.**
  Hosts in the Mandated Services Registry (`agent-tooling/settings/mandated-services.json`)
  are fetched directly under their connector's access policy. For a host that is **not**
  mandated — or when a mandated fetch is blocked or the host discourages AI ingestion —
  use the Internet Archive API: `archive.org/wayback/available` for coverage, then
  `web.archive.org/web/<ts>id_/<url>`. A direct fetch of a non-mandated target risks
  blacklisting the user's address. See the `source-connectors` skill.
- **No participant or research-subject data through third-party model hosts.** Participant data
  via `claude-code` is allowed (Stanford institutional agreement); via `openrouter`/`mistral` it
  is denied. Raw PII reaches no provider.
- **Truthfulness is a feature.** Prefer "I don't know" / "unverified" to a confident guess.
  Never state a number you have not computed.
- **Voice work is a bounded transform.** Organise and transcribe; never co-author; never
  substitute generic AI polish.
- **Cross-review is static by default.** A reviewer that believes a live or boundary-probing
  test is necessary must stop and request it (what / why / blast radius); the human decides on
  the spot. Subagents inherit the same permission boundary and cannot exceed it.
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
python3 agent-tooling/scripts/mandated_services.py  # webfetch registry vs connector library drift
python3 -m unittest agent-tooling.scripts.tests.test_audit_skills \
                    agent-tooling.scripts.tests.test_check_skill_vars \
                    agent-tooling.scripts.tests.test_install \
                    agent-tooling.scripts.tests.test_mandated_services \
                    agent-tooling.scripts.tests.test_backup_harness \
                    agent-tooling.scripts.tests.test_skill_trigger_eval \
                    agent-tooling.scripts.tests.test_script_approval \
                    agent-tooling.policies.tests.test_webfetch_mandated
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

## Deployment state

Deployed and verified on the Mac: `~/.config/opencode/opencode.json` is live; the plugin loads
and injects `AGENT_TOOLING_ROOT` / `WIKIMEDIA_UA`; and denies enforce (`external_directory`
blocks out-of-boundary file moves, `sudo` is refused). The `~/agent` hub exists and `deliver.py`
is installed root-owned at `/usr/local/bin/deliver.py`. The handoff records what is still open.
