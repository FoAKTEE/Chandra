#!/bin/bash
# Stop what scripts/arena_up.sh started: the arena (with its kg-client), the keepalive, and every
# kgservice Slurm job for the model.  Then show that no such job or process is left.
set -uo pipefail
M47=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
ARENA_DIR=${ARENA_DIR:-/data/haiyangw/claude/Move47/runs/move47/arena}
MODEL=${MODEL:-engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz}
cd "$M47"

alive() {
  local pid
  pid=$(cat "$1" 2>/dev/null) || return 1
  [[ $pid =~ ^[0-9]+$ ]] && tr '\0' ' ' 2>/dev/null <"/proc/$pid/cmdline" | grep -q -- "$2"
}

# stop NAME PATTERN: SIGTERM the process group (arena_up made each process a session/group leader),
# SIGKILL after 20 s
stop() {
  local name=$1 pat=$2 pidf=$ARENA_DIR/$1.pid pid
  if ! alive "$pidf" "$pat"; then
    echo "$name: not running"
    rm -f "$pidf"
    return 0
  fi
  pid=$(cat "$pidf")
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 40); do alive "$pidf" "$pat" || break; sleep 0.5; done
  if alive "$pidf" "$pat"; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    echo "$name: killed (pid $pid)"
  else
    echo "$name: stopped (pid $pid)"
  fi
  rm -f "$pidf"
}

stop arena "goarena serve"            # first: no new engine queries
stop keepalive "kgservice keepalive"  # then: no successor jobs
python3 -m kgservice stop --model "$MODEL"
name="kgb-$(basename "$MODEL" .bin.gz)"
for _ in $(seq 60); do
  [[ -z $(squeue -h -u "$USER" -n "$name" -o %i 2>/dev/null) ]] && break
  sleep 1
done
echo "--- squeue -u $USER"
squeue -u "$USER"
echo "--- processes matching goarena|kgservice (none expected)"
pat='goarena|kgservice'
pgrep -fa "$pat" | grep -v -e "pgrep -fa" -e "arena_down.sh" || echo "none"
