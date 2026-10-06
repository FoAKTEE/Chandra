#!/bin/bash
# Arena + KataGo (opponents, referee, offline judge) on one GPU node.
#SBATCH --job-name=goarena
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/arena-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
# GPU build of KataGo + a strong network (download on a login node):
#   KATAGO_BIN=/path/katago-cuda  KATAGO_MODEL=/path/kata1-b28c512nbt-....bin.gz
export KATAGO_BIN=${KATAGO_BIN:-engines/katago}
export KATAGO_MODEL=${KATAGO_MODEL:-engines/models/g170e-b10c128-s1141046784-d204142634.bin.gz}
export GOARENA_ADMIN_TOKEN=${GOARENA_ADMIN_TOKEN:?set an admin token}
echo "arena on $(hostname):8765"
python -m goarena serve --host 0.0.0.0 --port 8765 --db runs/arena.db \
    --tiers ${TIERS:-config/tiers-9x9.json} --size ${SIZE:-9} --review-visits 200 --referee-visits 800 \
    --viewer-token "${GOARENA_VIEWER_TOKEN:-}"
