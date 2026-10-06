#!/bin/bash
# Offline-judge check of the two target moves on one A100 (partition preempt, <=2 CPUs per GPU).
#SBATCH --job-name=move47-engine-check
#SBATCH --partition=preempt
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=2
#SBATCH --time=00:30:00
#SBATCH --output=logs/engine-check-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
mkdir -p judge
python3 scripts/engine_check.py --visits ${VISITS:-2000 20000} > "judge/engine-check-${SLURM_JOB_ID}.json"
echo "wrote judge/engine-check-${SLURM_JOB_ID}.json"
