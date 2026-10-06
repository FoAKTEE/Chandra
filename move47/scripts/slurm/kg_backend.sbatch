#!/bin/bash
# kgservice backend: one KataGo analysis engine on one A100, shared over 127.0.0.1 with
# token auth (see README "KataGo service").  USR1 arrives 300 s before the 1 h limit and puts
# the backend into draining mode; kgservice keepalive submits the successor before that.
#SBATCH --job-name=kg-backend
#SBATCH --partition=preempt
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=2
#SBATCH --time=01:00:00
#SBATCH --signal=B:USR1@300
#SBATCH --output=logs/kg-backend-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
MODEL=${MODEL:-engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz}
CONFIG=${CONFIG:-engines/configs/analysis-gpu.cfg}
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
# exec: the backend becomes the batch shell, so it receives USR1 (B:) and SIGTERM directly.
exec python3 -m kgservice backend --model "$MODEL" --config "$CONFIG"
