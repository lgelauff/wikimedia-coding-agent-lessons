#!/bin/bash
# seq_runner.sh: run a list of steps one after another inside ONE Toolforge job (or any shell).
#
# A failing step is logged and the runner MOVES ON to the next step, unless that step is marked `stop`.
# Rerunning the same sequence skips steps that already succeeded (their .ok marker), so a killed or
# partly failed sequence resumes where it left off.
#
# Usage:   bash seq_runner.sh SEQUENCE_FILE OUT_DIR
# Sequence file, one step per line, TAB-separated (blank lines and lines starting with # are ignored):
#   NAME <TAB> ON_FAIL <TAB> TIMEOUT <TAB> COMMAND
#     NAME     [A-Za-z0-9._-]+, unique; used for <OUT_DIR>/<NAME>.log and <OUT_DIR>/<NAME>.ok
#     ON_FAIL  continue | stop        (stop = end the sequence if this step fails)
#     TIMEOUT  a `timeout` duration, e.g. 30m, 6h, or 0 for none
#     COMMAND  run with `bash -c`; stdout+stderr go to <OUT_DIR>/<NAME>.log
# Output: <OUT_DIR>/sequence.log gets one line per event and a final
#   SEQ END ok=<n> failed=<n> skipped=<n> not_run=<n> [failed: a b] [not_run: c d]
# Exit code: 0 if every step succeeded or was already done, 1 otherwise.
# The toolforge CLI is not available inside jobs: steps must be plain commands, not `toolforge jobs run`.
set -u
SEQ=${1:?usage: seq_runner.sh SEQUENCE_FILE OUT_DIR}
OUT=${2:?usage: seq_runner.sh SEQUENCE_FILE OUT_DIR}
mkdir -p "$OUT" || exit 2
LOG="$OUT/sequence.log"
ts() { date -u +%FT%TZ; }
note() { echo "$1 $(ts)" | tee -a "$LOG"; }

# Validate the whole file first, so a typo in step 7 is caught before step 1 runs.
names=(); bad=0; n=0
while IFS= read -r line || [ -n "$line" ]; do
  n=$((n + 1))
  case "$line" in ''|'#'*) continue ;; esac
  nf=$(printf '%s' "$line" | awk -F'\t' '{print NF}')
  if [ "$nf" -lt 4 ]; then echo "line $n: needs 4 TAB-separated fields (NAME ON_FAIL TIMEOUT COMMAND), has $nf"; bad=1; continue; fi
  if printf '%s' "$line" | awk -F'\t' '{exit !($1==""||$2==""||$3==""||$4=="")}'; then echo "line $n: an empty field (use 0 for no TIMEOUT)"; bad=1; continue; fi
  IFS=$'\t' read -r name onfail tmo cmd <<< "$line"
  if ! [[ "$name" =~ ^[A-Za-z0-9._-]+$ ]]; then echo "line $n: bad NAME '$name'"; bad=1; continue; fi
  if [ "$onfail" != continue ] && [ "$onfail" != stop ]; then echo "line $n ($name): ON_FAIL must be continue|stop"; bad=1; fi
  if [ -z "${tmo:-}" ]; then echo "line $n ($name): TIMEOUT missing (use 0 for none)"; bad=1; fi
  if [ -z "${cmd:-}" ]; then echo "line $n ($name): COMMAND missing"; bad=1; fi
  for x in "${names[@]:-}"; do [ "$x" = "$name" ] && { echo "line $n: duplicate NAME '$name'"; bad=1; }; done
  names+=("$name")
done < "$SEQ"
[ "$bad" -eq 0 ] || { echo "SEQ REFUSED: fix the sequence file" | tee -a "$LOG"; exit 2; }

note "SEQ START file=$SEQ steps=${#names[@]} sha256=$(sha256sum "$SEQ" 2>/dev/null | cut -c1-16 || shasum -a 256 "$SEQ" | cut -c1-16)"
ok=0; failed=0; skipped=0; failed_list=""; stopped=""
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  IFS=$'\t' read -r name onfail tmo cmd <<< "$line"
  if [ -n "$stopped" ]; then not_run_list="${not_run_list:-} $name"; continue; fi
  if [ -e "$OUT/$name.ok" ]; then note "STEP $name SKIP already-ok"; skipped=$((skipped + 1)); continue; fi
  note "STEP $name START"
  t0=$(date +%s)
  if [ "$tmo" = 0 ]; then bash -c "$cmd" > "$OUT/$name.log" 2>&1; rc=$?
  else timeout -k 60 "$tmo" bash -c "$cmd" > "$OUT/$name.log" 2>&1; rc=$?; fi
  secs=$(( $(date +%s) - t0 ))
  if [ "$rc" -eq 0 ]; then
    echo "$(ts) rc=0 secs=$secs" > "$OUT/$name.ok"; ok=$((ok + 1)); note "STEP $name EXIT 0 secs=$secs"
  else
    failed=$((failed + 1)); failed_list="$failed_list $name"
    [ "$rc" -eq 124 ] && why=" (timeout $tmo)" || why=""
    note "STEP $name EXIT $rc$why secs=$secs; last log line: $(tail -n 1 "$OUT/$name.log" | cut -c1-200)"
    [ "$onfail" = stop ] && { stopped=$name; note "STEP $name was marked stop: ending the sequence"; }
  fi
done < "$SEQ"
nr=$(echo ${not_run_list:-} | wc -w | tr -d ' ')
note "SEQ END ok=$ok failed=$failed skipped=$skipped not_run=$nr${failed_list:+ [failed:$failed_list]}${not_run_list:+ [not_run:${not_run_list}]}"
[ "$failed" -eq 0 ] && [ "$nr" -eq 0 ]
