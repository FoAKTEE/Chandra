#!/bin/bash
# Show the state of the GPU arena started by scripts/arena_up.sh (never prints the tokens).
set -uo pipefail
M47=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
ARENA_DIR=${ARENA_DIR:-/data/haiyangw/claude/Move47/runs/move47/arena}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-8765}
cd "$M47"
for p in "keepalive:kgservice keepalive" "arena:goarena serve"; do
  name=${p%%:*} pat=${p#*:}
  pid=$(cat "$ARENA_DIR/$name.pid" 2>/dev/null)
  if [[ $pid =~ ^[0-9]+$ ]] && tr '\0' ' ' 2>/dev/null <"/proc/$pid/cmdline" | grep -q -- "$pat"; then
    echo "$name: running (pid $pid)"
  else
    echo "$name: not running"
  fi
done
echo "healthz: $(curl -s -m 5 "http://$HOST:$PORT/healthz" || echo unreachable)"
if [[ -s $ARENA_DIR/viewer.token ]]; then
  curl -s -m 10 -H @<(printf 'Authorization: Bearer %s\n' "$(cat "$ARENA_DIR/viewer.token")") \
    "http://$HOST:$PORT/api/leaderboard" | python3 -c "$(cat <<'EOF'
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit("leaderboard: no answer")
for r in d.get("runs", []):
    live = r.get("live") or {}
    line = "run %s: %s/%s games, %s" % (r["id"], r["games_played"], r["target_games"], r["status"])
    if live:
        line += ", live game #%s vs %s at move %s" % (live["game_no"], live["opponent"], live["moves"])
    print(line)
print("%d runs; tiers: %s" % (len(d.get("runs", [])), ", ".join(t["name"] for t in d.get("tiers", []))))
EOF
)"
fi
python3 -m kgservice status
