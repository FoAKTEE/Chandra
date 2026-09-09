#!/usr/bin/env bash
# run_codex_max.sh — start one Codex GPT-6 (reasoning effort max) worker task
# non-interactively, in the background, with a full transcript log.
#
# Usage: run_codex_max.sh <task-name> <prompt-file> [sandbox] [cwd]
#   sandbox: danger-full-access (default on this host — bubblewrap fails) | workspace-write | read-only
#   cwd:     directory the worker runs in (default: the git toplevel of $PWD, else $PWD)
# Output (under ${CHANDRA_RUNTIME:-/tmp/chandra}/codex/):
#   <task-name>.log       full transcript; ends with "# done <utc>" (or "# codex exec exited N")
#   <task-name>.final.md  the worker's final message
# Model / effort: CODEX_MODEL (default gpt-6-astra), CODEX_EFFORT (default max).
# The prompt is passed on STDIN from the file — codex exec blocks forever on an
# open non-tty stdin, so never launch it without the `- < file` redirection.
set -euo pipefail
name=${1:?task-name}; prompt=${2:?prompt-file}
sandbox=${3:-danger-full-access}
cwd=${4:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}
model=${CODEX_MODEL:-gpt-6-astra}; effort=${CODEX_EFFORT:-max}
out=${CHANDRA_RUNTIME:-/tmp/chandra}/codex
mkdir -p "$out"
[ -f "$prompt" ] || { echo "prompt file not found: $prompt" >&2; exit 2; }
(
  cd "$cwd"
  codex exec -m "$model" -c model_reasoning_effort="\"$effort\"" -s "$sandbox" --skip-git-repo-check \
    -o "$out/$name.final.md" - < "$prompt" > "$out/$name.log" 2>&1 \
    || echo "# codex exec exited $? (model $model, effort $effort)" >> "$out/$name.log"
  echo "# done $(date -u +%FT%TZ)" >> "$out/$name.log"
) > /dev/null 2>&1 < /dev/null &
echo "codex task '$name' started (pid $!): model $model, effort $effort, sandbox $sandbox, cwd $cwd"
echo "log: $out/$name.log   final: $out/$name.final.md"
