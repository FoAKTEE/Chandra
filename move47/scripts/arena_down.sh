#!/bin/bash
# Stop what scripts/arena_up.sh started for one profile: the arena (with its kg-client), the keepalive,
# and every kgservice Slurm job for the profile's model.  Then show that no such job or process is left.
#
#   scripts/arena_down.sh [--profile kata1|ladder] [--dry-run]
# Same profiles and environment overrides as arena_up.sh (scripts/arena_env.sh).  The other profile's
# arena, keepalive and jobs are left alone and listed separately.
set -uo pipefail
M47=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
# shellcheck source=arena_env.sh
source "$M47/scripts/arena_env.sh"
arena_args "$@"
cd "$M47"
name="kgb-$(basename "$MODEL" .bin.gz)"
if ((DRY_RUN)); then
  arena_show
  echo "would stop: arena ($ARENA_DIR/arena.pid), keepalive ($ARENA_DIR/keepalive.pid);" \
       "scancel kgservice jobs named $name"
  exit 0
fi

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
for _ in $(seq 60); do
  [[ -z $(squeue -h -u "$USER" -n "$name" -o %i 2>/dev/null) ]] && break
  sleep 1
done
echo "--- squeue -u $USER"
squeue -u "$USER"
echo "--- processes of this profile (none expected): goarena on port $PORT, keepalive/client/backend for $(basename "$MODEL")"
mine="goarena serve.*--port $PORT( |\$)|kgservice (keepalive|client|backend).*$(basename "$MODEL")"
pgrep -fa -- "$mine" | grep -v -e "pgrep -fa" -e "arena_down.sh" -e "grep -" || echo "none"
others=$(pgrep -fa 'goarena|kgservice' | grep -v -e "pgrep -fa" -e "arena_down.sh" -e "grep -" | grep -Ev -- "$mine")
[[ -n $others ]] && { echo "--- other goarena/kgservice processes (other profiles, left running)"; echo "$others"; }
exit 0
