#!/usr/bin/env bash
# wait_codex.sh — bounded wait for a run_codex_max.sh task; prints the final message.
# Usage: wait_codex.sh <task-name> [timeout-seconds (default 3600)] [poll-seconds (default 30)]
# Exit 0 when the log ends with "# done", 1 on timeout, 2 if codex exited non-zero.
set -uo pipefail
name=${1:?task-name}; limit=${2:-3600}; poll=${3:-30}
out=${CHANDRA_RUNTIME:-/tmp/chandra}/codex
log="$out/$name.log"; final="$out/$name.final.md"
waited=0
until grep -q '^# done' "$log" 2>/dev/null; do
  if [ "$waited" -ge "$limit" ]; then echo "timeout after ${limit}s waiting for $log" >&2; exit 1; fi
  sleep "$poll"; waited=$((waited + poll))
done
if grep -q '^# codex exec exited' "$log"; then
  echo "codex exited non-zero — see $log" >&2; tail -20 "$log" >&2; exit 2
fi
[ -f "$final" ] && cat "$final"
