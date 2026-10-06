#!/bin/bash
# Start the GPU arena on the login host, detached so it survives the calling shell:
#   (a) python3 -m kgservice keepalive   keeps one strong-net KataGo backend alive in Slurm `preempt`
#   (b) python3 -m goarena serve         KATAGO_BIN=bin/kg-client, the kata1 ladder, adjudication on
# Everything lives in $ARENA_DIR (outside the Chandra tree): arena.db, admin.token and viewer.token
# (mode 600, created once, never tracked or printed), <name>.pid and <name>.log for both processes,
# kg-client.log (the arena's KataGo client: backend choice, failover, resends).
# Stop: scripts/arena_down.sh   Inspect: scripts/arena_status.sh
#
# Engine budget on one A100 with kata1-tf3-b11c768 (measured: 1600 visits ~1 s):
#   referee 1600 visits  one ownership search per finished game (~1 s) decides dead stones at full strength
#   review  1600 visits  per position, priority -10 (opponent moves at 0 go first; an opponent query
#                        waits at most for one review position, ~1-2 s); ~30 s per 38-ply game
set -euo pipefail
M47=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
CHANDRA=$(dirname "$M47")
ARENA_DIR=${ARENA_DIR:-/data/haiyangw/claude/Move47/runs/move47/arena}
MODEL=${MODEL:-engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz}
CONFIG=${CONFIG:-engines/configs/analysis-gpu.cfg}
TIERS=${TIERS:-config/tiers-9x9-kata1.json}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8765}
REFEREE_VISITS=${REFEREE_VISITS:-1600}
REVIEW_VISITS=${REVIEW_VISITS:-1600}
ADJUDICATE=(--adjudicate-winrate 0.01 --adjudicate-lead 20 --adjudicate-moves 4 --adjudicate-after 30)

cd "$M47"
mkdir -p "$ARENA_DIR"
ARENA_DIR=$(cd "$ARENA_DIR" && pwd -P)
case "$ARENA_DIR/" in
  "$(cd "$CHANDRA" && pwd -P)"/*) echo "arena_up: ARENA_DIR must be outside the Chandra tree" >&2; exit 2 ;;
esac
chmod 700 "$ARENA_DIR"
for f in "$MODEL" "$CONFIG" "$TIERS" bin/kg-client; do
  [[ -e $f ]] || { echo "arena_up: missing $M47/$f" >&2; exit 2; }
done

# alive PIDFILE PATTERN: the recorded pid runs and its command line matches PATTERN
alive() {
  local pid
  pid=$(cat "$1" 2>/dev/null) || return 1
  [[ $pid =~ ^[0-9]+$ ]] && tr '\0' ' ' 2>/dev/null <"/proc/$pid/cmdline" | grep -q -- "$2"
}

# launch NAME CMD...: new session (setsid; its own process group), pid file written by the process itself
launch() {
  local name=$1
  shift
  rm -f "$ARENA_DIR/$name.pid"
  echo "=== $(date '+%F %T') start: $*" >>"$ARENA_DIR/$name.log"
  setsid nohup bash -c 'echo $$ >"$0"; exec "$@"' "$ARENA_DIR/$name.pid" "$@" \
    >>"$ARENA_DIR/$name.log" 2>&1 </dev/null &
  for _ in $(seq 50); do [[ -s $ARENA_DIR/$name.pid ]] && break; sleep 0.1; done
}

umask 077
for t in admin viewer; do
  f=$ARENA_DIR/$t.token
  [[ -s $f ]] || python3 -c 'import secrets, sys; print(sys.argv[1] + secrets.token_urlsafe(24))' "${t:0:3}_" >"$f"
  chmod 600 "$f"
done

# (a) keepalive
if alive "$ARENA_DIR/keepalive.pid" "kgservice keepalive"; then
  echo "keepalive: already running (pid $(cat "$ARENA_DIR/keepalive.pid"))"
elif other=$(pgrep -f "kgservice keepalive.*$(basename "$MODEL")"); then
  echo "keepalive: another keepalive for $(basename "$MODEL") runs (pid $other); not starting a second one"
else
  launch keepalive env PYTHONUNBUFFERED=1 python3 -m kgservice keepalive --model "$MODEL" --config "$CONFIG"
  sleep 1
  alive "$ARENA_DIR/keepalive.pid" "kgservice keepalive" || { echo "keepalive failed; see $ARENA_DIR/keepalive.log" >&2; exit 1; }
  echo "keepalive: started (pid $(cat "$ARENA_DIR/keepalive.pid"))"
fi

# (b) arena; the tokens reach it through the environment only (never argv, so never in ps/pgrep output)
if alive "$ARENA_DIR/arena.pid" "goarena serve"; then
  echo "arena: already running (pid $(cat "$ARENA_DIR/arena.pid"))"
else
  (
    export GOARENA_ADMIN_TOKEN GOARENA_VIEWER_TOKEN PYTHONUNBUFFERED=1 KATAGO_BIN="$M47/bin/kg-client" \
      KGSERVICE_LOG="$ARENA_DIR/kg-client.log"     # the client's backend choice / failover lines
    GOARENA_ADMIN_TOKEN=$(cat "$ARENA_DIR/admin.token")
    GOARENA_VIEWER_TOKEN=$(cat "$ARENA_DIR/viewer.token")
    launch arena python3 -m goarena serve --db "$ARENA_DIR/arena.db" --host "$HOST" --port "$PORT" \
      --katago-bin "$M47/bin/kg-client" --katago-model "$M47/$MODEL" --katago-config "$M47/$CONFIG" \
      --tiers "$M47/$TIERS" --move-timeout 3600 --referee-visits "$REFEREE_VISITS" \
      --review-visits "$REVIEW_VISITS" "${ADJUDICATE[@]}"
  )
  for _ in $(seq 60); do
    curl -sf -m 2 "http://$HOST:$PORT/healthz" >/dev/null 2>&1 && break
    alive "$ARENA_DIR/arena.pid" "goarena serve" || break
    sleep 1
  done
  curl -sf -m 2 "http://$HOST:$PORT/healthz" >/dev/null 2>&1 || {
    echo "arena failed to come up; see $ARENA_DIR/arena.log" >&2; tail -5 "$ARENA_DIR/arena.log" >&2; exit 1; }
  echo "arena: listening on http://$HOST:$PORT (pid $(cat "$ARENA_DIR/arena.pid"))"
fi
echo "website: http://$HOST:$PORT/?key=<contents of $ARENA_DIR/viewer.token>"
echo "admin token file: $ARENA_DIR/admin.token  (e.g. GOARENA_ADMIN_TOKEN=\$(cat ...) python3 -m harness.runner ...)"
python3 -m kgservice status
