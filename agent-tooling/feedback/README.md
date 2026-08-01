# Provider feedback logs (local, gitignored)

One file per LLM provider, recording **what actually happened** when we used it
for real work. The per-provider files are **gitignored on purpose**: they carry
candid quality judgements and project-specific detail, and they are personal
observations rather than repo doctrine. What gets promoted here (committed) is
the *conclusion*, once it's stable — a line in a skill or a playbook.

```
feedback/
  README.md          <- committed: this file + the template
  liftwing.md        <- gitignored
  claude-code.md     <- gitignored
  openrouter.md      <- gitignored
  mistral.md         <- gitignored
```

Providers correspond to `AGENT_LLM_PROVIDER` values in
[`../scripts/llm_provider.py`](../scripts/llm_provider.py).

## Why bother

Two of this repo's mechanisms consume these logs:

- **`budget-estimate`** — level-2 (historical prior) evidence for "how long
  will this take / what will it cost" on a given task shape.
- **provider choice** — the standing rule is "delegate bulk mechanical work to
  the cheapest model that can do it reliably." *Reliably* is an empirical
  claim; this is where the evidence for it lives.

## Entry template

Append (newest first). Keep entries short — one screen each.

```markdown
## <YYYY-MM-DD> — <task shape in 5 words> (<project>)

- **Model / settings:** <model id, temperature/etc if non-default>
- **Task:** <what it was asked to do, and what "correct" meant>
- **Volume:** <N calls · input size · run wall-clock>
- **Throughput:** <calls/hour observed> (limit in force: <e.g. 100/h anon>)
- **Quality:** <verdict + how it was checked — spot-check n=?, gold set?>
- **Parse-failure rate:** <x/N> (for structured-output tasks)
- **Failures / surprises:** <errors, refusals, truncation, drift>
- **Verdict:** use again for this shape? <yes / no / with caveat>
- **Cost:** <$ or "free" or "subscription tokens ~X">
```

## Rules

- **Labels apply** (`[confirmed]` / `[concluded]` / `[guess]`) — an unmeasured
  impression is a guess, and should say so.
- **A "quality" verdict needs a check named.** "Seemed fine" is not a verdict;
  "spot-checked 10, 9 correct, 1 hallucinated a date" is.
- **No participant names, no private data, no secrets** — these files are
  local, but the rule doesn't bend for local files.
- Log the **negative** results too. A provider that failed a task shape is the
  most valuable entry in the file.
