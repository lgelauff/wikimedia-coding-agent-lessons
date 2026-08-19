# Threat-surface review — charset-hygiene maintenance

Companion to the `charset-hygiene` skill. This is a **recurring maintenance ritual**, not part
of a charset check — kept out of the skill's hot path so a routine scan doesn't carry
instructions used maybe once a week.

## Roughly weekly

Check what is new in LLM watermarking and Unicode smuggling — Anthropic, OpenAI, Google, and
other agentic-model providers, plus the security literature. New encoding channels become new
*reasons a character is out of set*; they do not change the allowlist frame.

**Fetching follows the research-vault pipeline, not ad-hoc WebFetch**: look up
`research-vault/index.json` first, queue misses in `research-vault/inbox/pending.txt`, and
collect via `uv run ingest.py --collect` (rate-limited, robots-aware, archival). See the
`collect-source` skill.

Record what changed in `agent-tooling/feedback/` and, if a new family needs naming, add it to
`RISK_NOTES` in the script with a test.
