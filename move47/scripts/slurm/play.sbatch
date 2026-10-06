#!/bin/bash
# The tree harness plays arena games (one run = one model x harness configuration).
#SBATCH --job-name=gotree-play
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=7-00:00:00
#SBATCH --output=logs/play-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
export GOARENA_URL=${GOARENA_URL:?http://<arena-node>:8765}
export GOARENA_ADMIN_TOKEN=${GOARENA_ADMIN_TOKEN:?}
python -m harness.runner --harness tree --tree-worker "${WORKER:-claude:opus:high}" \
    --tree-opponent "${OPPONENT:-lv5}" --games "${GAMES:-50}" --name "${NAME:-tree/$WORKER}" -- \
    --budget "${BUDGET:-300}" --workers "${PAR:-32}" --memory "${MEMORY:-runs/shared-memory.db}"
