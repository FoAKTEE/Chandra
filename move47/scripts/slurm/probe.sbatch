#!/bin/bash
# Move-37 probe with many parallel worker sessions on one CPU node.
# Workers call closed LLMs over the network: the node needs outbound HTTPS to the model API
# (or a proxy) and the CLI tools logged in (claude / codex) or API keys in the environment.
#SBATCH --job-name=gotree-probe
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=2-00:00:00
#SBATCH --output=logs/probe-%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
WORKER=${WORKER:-claude:opus:high}          # or codex:gpt-6.1-sol:high, api:anthropic:claude-opus-5-5:high
BUDGET=${BUDGET:-2000}
PAR=${PAR:-32}
RUN=runs/probe-g2-37-${SLURM_JOB_ID}
# 0) cheap pre-check: is P10 ever proposed?  (10 fresh sessions)
python -m gotree prior --run "$RUN" --worker "$WORKER" --samples 10
# 1) the search itself; self-play rollouts by a second model family ("LLM vs LLM")
python -m gotree probe --run "$RUN" --worker "$WORKER" --worker-for rollout="${ROLLOUT_WORKER:-$WORKER}" \
    --budget "$BUDGET" --workers "$PAR" --memory "${MEMORY:-runs/shared-memory.db}" \
    ${SANDBOX:+--wrap "$SANDBOX"}
# 2) offline grading (needs KataGo; run on the GPU node or here with the CPU build)
python -m gotree judge --run "$RUN"
python -m gotree judge-values --run "$RUN" --n 200
