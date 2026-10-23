# Focus guard — pause agent background jobs on the Mac during calls

**Why.** The Mac has ~8 GB RAM and runs near 90% swap with many agent sessions; the Claude app froze
twice on 2026-10-20 from memory pressure. While any macOS Focus is on (calls, but any Focus is the
safer trigger), registered agent background jobs are paused with SIGSTOP; when the Focus ends they
continue with SIGCONT. Paused jobs keep their memory but stop using CPU and stop starting new work.

Script: `agent-tooling/scripts/focus_guard.py` (stdlib only). State in `state/` and the log in
`logs/focus-guard.log` under the agent hub. It signals only jobs that were `register`ed, only when the pid is alive
and still shows the recorded command, never anything with "claude" in its command, and never kills.

## For Lodewijk: set up the two Shortcuts automations (once)

Nothing here is installed by an agent. Replace `<abs path>` with the absolute path of this repo's
`agent-tooling/scripts/` in the checkout you want to use (the main checkout, not a worktree, so the path
survives worktree clean-up).

1. Open **Shortcuts** → **Automation** tab → **+** (New Automation) → **Focus**.
2. Choose **Focus: Do Not Disturb** (or "Any Focus" if it is offered) and **When: Turning On**; next.
3. Add action **Run Shell Script**. Shell `/bin/zsh` (or `/bin/bash`), input none, and the script:
   `/usr/bin/python3 <abs path>/focus_guard.py on`
4. Set **Run immediately** (not "Ask before running") and **Notify when run: off**. Done.
5. Repeat 1–4 with **Turning Off** and the script `/usr/bin/python3 <abs path>/focus_guard.py off`.
6. If macOS only lets you pick specific Focus modes, create the on/off pair for **each** mode you use:
   Do Not Disturb, Sleep, Work, Personal, Driving, Reading, Fitness, Mindfulness, Gaming, plus any custom
   Focus (a call Focus, if you made one). A mode left out never pauses anything.
7. Test: `python3 <abs path>/focus_guard.py status`, switch a Focus on, run `status` again (should
   say `focus: ON since …`), switch it off.

Overlapping Focus modes: `on` and `off` are idempotent, but one "off" ends the pause even if a second
Focus is still on. If you stack Focus modes, say so; the script has no counter.

Version support:
- Your Mac reports Darwin 25.6.0, i.e. macOS 26 (Tahoe). [concluded — Darwin 25 ↔ macOS 26; not read from About This Mac]
- Shortcuts has a **Focus** automation trigger on macOS 13 Ventura and later. [guess — recalled, not checked against Apple's documentation]
- Personal automations on the Mac and the **Run Shell Script** action exist on recent macOS. [guess]
- Whether "Run immediately" and "Notify when run" appear for shell-script automations on macOS 26: [guess]; if the toggle is missing, the automation will ask before running and the guard will not fire unattended. Tell the coordinator if you see that.
- Not yet shown by test: that the automation fires on a real Focus change. Only the script is tested.

## For agents

When you launch a long background job **on the Mac** (local runs, overnight pipelines, browser
tests, large downloads), register it right after starting it and unregister when it ends:

```bash
python3 agent-tooling/scripts/focus_guard.py register <job-name> <pid> --owner <your-session>
python3 agent-tooling/scripts/focus_guard.py unregister <job-name>
```

Before **starting** new heavy Mac work, check the flag: if `focus_guard.py status` says `focus: ON`
(the flag file is `state/focus-on` in the agent hub), wait or defer it; a job started during a Focus is not paused
until the next `on`. A paused job looks hung (state `T`): do not kill or restart it; it resumes when
the Focus ends. Jobs on hague and Toolforge are not affected, and do not need registering. Never
register the Claude app or any `claude` process (the script refuses).

## Metered connection (phone hotspot)

Same mechanism, second trigger. Register a big download or upload with `--kind big-transfer`:

```bash
python3 agent-tooling/scripts/focus_guard.py register <job-name> <pid> --owner <your-session> --kind big-transfer
```

`focus_guard.py metered on` then pauses only the jobs registered that way (a Focus pauses every
registered job); `metered off` resumes them. Flags and stopped-lists are separate (`metered-on`,
`metered-stopped.json`), and a job held by both is resumed only when both have ended. It was added to
this script rather than made a second tool because the safety rules (registered pids only, command
re-check, never `claude`, SIGSTOP/SIGCONT only) are the ones to keep identical. Detecting the
connection is `machine_check.py`'s job (see `machine-check.md`); `metered on|off` is run by an agent or
Lodewijk after it reports `metered`. Not wired to any automatic trigger.
