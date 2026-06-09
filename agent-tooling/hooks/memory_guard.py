#!/usr/bin/env python3
"""
PreToolUse hook: block launching a Workflow (or a backgrounded Agent) only when
the OS reports CRITICAL memory pressure.

Subagents inside a workflow are concurrent async calls in ONE process, so you
can't count them — but a fan-out under real pressure is what causes the OOM.
This gates the spawn point on the OS's own pressure verdict.

Why not "free %": on macOS free memory is chronically low (the OS fills RAM with
reclaimable cache), so a free-% threshold either nags forever or never fires.
The trustworthy signal is `kern.memorystatus_vm_pressure_level`:
    1 = normal, 2 = warning, 4 = critical.
Day-to-day this machine sits at 2 (warning); the OOM happens at 4 (critical).
So we block on level >= 4 by default — not on warning, not on a percentage.

  macOS  : block when memorystatus_vm_pressure_level >= WORKFLOW_BLOCK_PRESSURE_LEVEL (default 4)
  Linux  : no such level; fall back to MemAvailable% < WORKFLOW_MIN_FREE_PCT (default 8)

Gated tools: `Workflow`, and `Agent`/`Task` when run_in_background is set.
Fails OPEN: if no signal can be read, allow (don't block real work on a glitch).
"""
import json
import os
import subprocess
import sys

GATED = {"Workflow", "Agent", "Task"}


def pressure_level():
    """macOS pressure level (1 normal / 2 warning / 4 critical), or None."""
    try:
        out = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def linux_free_pct():
    """Linux MemAvailable% (real headroom number), or None."""
    try:
        info = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":")
            info[k.strip()] = float(v.strip().split()[0])
        if info.get("MemTotal"):
            return 100.0 * info.get("MemAvailable", 0) / info["MemTotal"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def is_gated(tool_name, tool_input):
    if tool_name not in GATED:
        return False
    if tool_name in ("Agent", "Task") and not tool_input.get("run_in_background"):
        return False
    return True


def is_critical(level, free, block_level, min_pct):
    """Pure decision: True only when a usable signal says we're in trouble."""
    if level is not None:
        return level >= block_level
    if free is not None:
        return free < min_pct
    return False  # no signal -> fail open


def main():
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        sys.exit(0)

    tool_name = d.get("tool_name", "")
    tool_input = d.get("tool_input", {}) or {}
    if not is_gated(tool_name, tool_input):
        sys.exit(0)

    block_level = int(os.environ.get("WORKFLOW_BLOCK_PRESSURE_LEVEL", "4"))
    min_pct = float(os.environ.get("WORKFLOW_MIN_FREE_PCT", "8"))
    level, free = pressure_level(), linux_free_pct()

    if is_critical(level, free, block_level, min_pct):
        where = (f"OS memory pressure = CRITICAL (level {level})" if level is not None
                 else f"free memory {free:.0f}% < {min_pct:.0f}%")
        sys.stderr.write(
            "\n🧠 BLOCKED: critical memory pressure — not launching a fan-out\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{where}.\n"
            f"A {tool_name} fan-out now risks the OOM crash you hit before.\n\n"
            "Do this first, then retry:\n"
            "  • /compact  (drop accumulated context — the usual culprit)\n"
            "  • let any running workflow finish; don't stack them\n"
            "  • close memory-heavy apps, or restart the session (claude --continue)\n"
            "  • override for this session: WORKFLOW_BLOCK_PRESSURE_LEVEL=5 (never blocks)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
