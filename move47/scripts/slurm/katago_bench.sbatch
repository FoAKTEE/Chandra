#!/bin/bash
# KataGo GPU benchmark on one A100 (partition preempt: 1 h max, <=2 CPUs per GPU).
#SBATCH --job-name=katago-bench
#SBATCH --partition=preempt
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=2
#SBATCH --time=00:20:00
#SBATCH --output=logs/bench-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
MODEL=${MODEL:-engines/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz}
CFG=${CFG:-engines/dist/katago-v1.18.2-cuda12.8-cudnn9.8.0/default_gtp.cfg}
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
engines/katago version | head -1
engines/katago benchmark -model "$MODEL" -config "$CFG" -t "${THREADS:-8,16,32,64}" -v "${VISITS:-1600}"
