#!/bin/sh
# Run a PreToolUse safety gate and fail CLOSED if it crashes.
#
# Claude Code treats exit 2 as "block" and any other non-zero exit as a
# non-blocking error, so a gate that crashes (an ImportError, a TypeError on an
# older python3) silently lets the call through. Found 2026-11-02: three gates
# used `str | None` and could not even import on Python 3.9.
#
# The gates wrapped here only ever exit 0 (allow) or 2 (block). Any other code
# means the gate did not decide, so this wrapper blocks and says why.
# stdin (the tool call JSON) and stdout pass straight through.
#
# usage: fail_closed.sh <gate.py>
python3 "$@"
rc=$?
case $rc in
  0|2) exit $rc ;;
esac
echo "agent-tooling: safety hook $(basename "$1") crashed (exit $rc), so this call is blocked (fail closed). Fix the hook, or ask the user." >&2
exit 2
