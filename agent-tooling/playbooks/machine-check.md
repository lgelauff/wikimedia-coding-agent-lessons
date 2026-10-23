# Machine check — memory, disk and connection before big jobs

**Why.** The Mac has ~8 GB RAM and runs near 90% swap with many agent sessions; the Claude app froze
twice on 2026-10-20 from memory pressure. Lodewijk also sometimes works on a phone hotspot and does
not want agents moving large data over it without asking (2026-10-23). `machine_check.py` makes both
a one-line check with an exit code.

Script: `agent-tooling/scripts/machine_check.py` (stdlib only, macOS first; elsewhere unreadable items
say `unknown`). It reads only; it changes and signals nothing.

## When an agent runs it

```bash
python3 agent-tooling/scripts/machine_check.py --gate big-transfer   # >500 MB through the Mac
python3 agent-tooling/scripts/machine_check.py --gate heavy-local    # local job >2 GB RAM or long CPU
python3 agent-tooling/scripts/machine_check.py --gate light          # everything else; never stops
```

1. **Before** any big Mac-side transfer: downloads, uploads, scp/rsync to or from hague, HF pushes.
2. **Before** a heavy local run.
3. **Every ~30 minutes inside long-running loops** (re-run the same gate; a hotspot can start
   mid-run, swap creeps up).

Exit codes: **0** go ahead. **1** caution (swap above 85%): keep the job small, start nothing new
and heavy. **2** stop: **pause and ask Lodewijk in chat**, with the printed reason, before
continuing. A yes covers that job on that connection; ask again if the next check is still 2.
Add `--json` to parse it. Thresholds are flags: `--caution-swap-pct 85`, `--stop-swap-pct 90`,
`--min-free-disk-gib 15`.

| Gate | Exit 2 when | Exit 1 when |
|---|---|---|
| `big-transfer` | connection is `metered` **or `unknown`** | swap > 85% |
| `heavy-local` | swap > 90%, or free disk < 15 GiB | swap > 85% |
| `light` | never | swap > 85% |
| no gate | as `heavy-local` (connection not considered) | swap > 85% |

**Not gated:** downloads or jobs that run on hague or Toolforge themselves. They do not use Lodewijk's
connection or the Mac's memory. (Pulling their *results* to the Mac is a Mac-side transfer: gate it if
it is over 500 MB.)

## How the connection is classified

`metered` if any signal fires. `unmetered` needs positive evidence. Otherwise `unknown`, which stops
`big-transfer`: "I could not tell" is not permission to stream gigabytes over a phone.

| Signal | What it looks at | Confidence |
|---|---|---|
| (a) Hotspot subnet | default route's gateway is in 172.20.10.0/28 (`route -n get default`) | [confirmed] that this is the iPhone Personal Hotspot subnet default; [guess] that nothing else on Lodewijk's networks uses it |
| (b) Phone port | the primary interface's hardware port is "iPhone USB" or a Bluetooth PAN (`networksetup -listnetworkserviceorder`) | [concluded] from the port names macOS gives tethering; not seen on this Mac |
| (c) Listed SSID | the Wi-Fi SSID (`ipconfig getsummary`, fallback `networksetup -getairportnetwork`) is a line in `~/agent/state/metered-networks.txt` | [confirmed] as a lookup; only as good as the list. Lodewijk maintains it. Android hotspots and other metered Wi-Fi are caught **only** here |
| (d) Low Data Mode | `scutil --nwi` shows an Expensive/Constrained flag on the primary interface | [guess]: the output format is undocumented and the flag was not seen on this Mac; treat a hit as real, a miss as no information |

The metered file: one SSID per line, exact match (case-sensitive), blank lines and `#` comments ignored.
A missing file counts as an empty list. If macOS hides the SSID, a Wi-Fi connection is `unknown`, not
`unmetered`, because the list could not be consulted.

Output never contains MAC addresses, IP addresses or SSIDs, only which signal fired.

## Making the pause automatic

A job already running when the connection turns metered is not stopped by the check alone. Register
it with `focus_guard.py register <name> <pid> --kind big-transfer`; then `focus_guard.py metered on`
pauses exactly those jobs (SIGSTOP) and `metered off` resumes them. See `focus-guard.md`. Nothing
runs `metered on` by itself yet: an agent or Lodewijk does, when a check reports `metered`.

## Verified by

Unit tests with injected signals (`scripts/tests/test_machine_check.py`); one live run on the Mac
2026-10-23 (unmetered Wi-Fi, swap 85%, pressure warn). A real hotspot connection has **not** been tried
[unverified].
