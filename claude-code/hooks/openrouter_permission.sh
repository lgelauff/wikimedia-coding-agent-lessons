#!/usr/bin/env bash
# PreToolUse hook: ask permission for the first OpenRouter API call per model per session.
# Session = the Claude Code process subtree (identified by ancestor PID).

set -euo pipefail

INPUT=$(cat)

# Only care about commands that hit the OpenRouter API
COMMAND=$(printf '%s' "$INPUT" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null) || COMMAND=""

if ! printf '%s' "$COMMAND" | grep -q "openrouter.ai"; then
    exit 0
fi

# Extract model name from the JSON payload inside the command
MODEL=$(printf '%s' "$COMMAND" | \
    python3 -c "
import sys, re
cmd = sys.stdin.read()
m = re.search(r'\"model\"\s*:\s*\"([^\"]+)\"', cmd)
print(m.group(1) if m else 'unknown')
" 2>/dev/null) || MODEL="unknown"

# Stable session ID: walk up the process tree to find the root claude/node process
SESSION_PID=$(python3 -c "
import subprocess, os
pid = os.getppid()
for _ in range(10):
    try:
        out = subprocess.check_output(['ps', '-p', str(pid), '-o', 'ppid=,comm='],
                                       text=True).strip().split()
        ppid, comm = out[0], out[1] if len(out) > 1 else ''
        if int(ppid) <= 1:
            break
        if any(x in comm.lower() for x in ('claude', 'node', 'electron')):
            break
        pid = int(ppid)
    except Exception:
        break
print(pid)
" 2>/dev/null) || SESSION_PID="$$"

MODEL_SLUG=$(printf '%s' "$MODEL" | tr '/: ' '___')
PERM_FILE="/tmp/.or_allowed_${SESSION_PID}_${MODEL_SLUG}"

if [ -f "$PERM_FILE" ]; then
    exit 0  # Already approved this session
fi

cat <<EOF
╔══════════════════════════════════════════════════════╗
║        OpenRouter API — Permission Required          ║
╠══════════════════════════════════════════════════════╣
║  Model   : $MODEL
║  Session : $SESSION_PID
╠══════════════════════════════════════════════════════╣
║  First call to this model this session.              ║
║                                                      ║
║  To approve for this session, tell me:               ║
║    "ja, goedgekeurd" / "yes, approved"               ║
║                                                      ║
║  Or run this in your terminal:                       ║
║    touch "$PERM_FILE"
╚══════════════════════════════════════════════════════╝
EOF
exit 2
