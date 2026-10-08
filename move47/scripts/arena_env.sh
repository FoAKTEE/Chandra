# Settings shared by arena_up.sh, arena_down.sh and arena_status.sh (sourced, never run).
#
# Profiles (--profile NAME or $ARENA_PROFILE):
#   kata1   (default) the "real KataGo" ladder: strong net kata1-tf3-b11c768, config/tiers-9x9-kata1.json,
#           port 8765, arena dir runs/move47/arena
#   ladder  the calibrated ladder (lv1-lv8 rated): net g170e-b10c128, config/tiers-9x9.json, port 8766,
#           arena dir runs/move47/arena-ladder
# Each setting can still be overridden by its environment variable, which wins over the profile:
#   ARENA_DIR MODEL CONFIG TIERS HOST PORT REFEREE_VISITS REVIEW_VISITS ADJUDICATE MOVE_TIMEOUT
# ADJUDICATE holds the goarena adjudication options; ADJUDICATE="" turns adjudication off.
# MOVE_TIMEOUT (default 3600 s): agent inactivity that forfeits a game; longer than any wait of the
# agent for its model (mcts play --wait-for-model, hours).
# Both arenas can run at once: each has its own port, arena dir (pid files, tokens, db, logs) and
# keepalive, and each keepalive keeps one backend of its own model (Slurm: 2 GPUs, so one per model).

RUNS_ROOT=${RUNS_ROOT:-/data/haiyangw/claude/Move47/runs/move47}
DRY_RUN=0

# arena_args "$@": --profile NAME | --profile=NAME | --dry-run | -h
arena_args() {
  ARENA_PROFILE=${ARENA_PROFILE:-kata1}
  while (($#)); do
    case $1 in
      --profile) [[ $# -ge 2 ]] || { echo "$(basename "$0"): --profile needs a name" >&2; exit 2; }
                 ARENA_PROFILE=$2; shift 2 ;;
      --profile=*) ARENA_PROFILE=${1#*=}; shift ;;
      --dry-run) DRY_RUN=1; shift ;;
      -h|--help) sed -n '2,/^set -/p' "$0" | sed -n 's/^# \{0,1\}//p'; exit 0 ;;
      *) echo "$(basename "$0"): unknown argument $1 (use --profile kata1|ladder, --dry-run)" >&2; exit 2 ;;
    esac
  done
  case $ARENA_PROFILE in
    kata1|default)
      ARENA_PROFILE=kata1
      P_MODEL=engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz
      P_TIERS=config/tiers-9x9-kata1.json
      P_PORT=8765
      P_DIR=$RUNS_ROOT/arena ;;
    ladder)
      P_MODEL=engines/models/g170e-b10c128-s1141046784-d204142634.bin.gz
      P_TIERS=config/tiers-9x9.json
      P_PORT=8766
      P_DIR=$RUNS_ROOT/arena-ladder ;;
    *) echo "$(basename "$0"): unknown profile '$ARENA_PROFILE' (kata1, ladder)" >&2; exit 2 ;;
  esac
  ARENA_DIR=${ARENA_DIR:-$P_DIR}
  MODEL=${MODEL:-$P_MODEL}
  CONFIG=${CONFIG:-engines/configs/analysis-gpu.cfg}
  TIERS=${TIERS:-$P_TIERS}
  HOST=${HOST:-127.0.0.1}
  PORT=${PORT:-$P_PORT}
  REFEREE_VISITS=${REFEREE_VISITS:-1600}
  REVIEW_VISITS=${REVIEW_VISITS:-1600}
  MOVE_TIMEOUT=${MOVE_TIMEOUT:-3600}
  local adj="--adjudicate-winrate 0.01 --adjudicate-lead 20 --adjudicate-moves 4 --adjudicate-after 30"
  ADJUDICATE=${ADJUDICATE-$adj}
  read -r -a ADJ_ARGS <<<"$ADJUDICATE"
}

arena_show() {
  echo "profile $ARENA_PROFILE: arena dir $ARENA_DIR; model $MODEL; tiers $TIERS; config $CONFIG;" \
       "http://$HOST:$PORT; referee $REFEREE_VISITS / review $REVIEW_VISITS visits; move timeout ${MOVE_TIMEOUT}s;" \
       "adjudication ${ADJUDICATE:-off}"
}

# alive PIDFILE PATTERN: the recorded pid runs and its command line matches PATTERN
alive() {
  local pid
  pid=$(cat "$1" 2>/dev/null) || return 1
  [[ $pid =~ ^[0-9]+$ ]] && tr '\0' ' ' 2>/dev/null <"/proc/$pid/cmdline" | grep -q -- "$2"
}
