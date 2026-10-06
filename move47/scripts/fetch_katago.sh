#!/usr/bin/env bash
# Download the prebuilt KataGo GPU engine and its networks into ./engines (gitignored).
#   - KataGo v1.18.2, CUDA 12.8 + cuDNN 9.8 Linux release (static-pie; dlopens CUDA libs at runtime)
#   - kata1-tf3-b11c768-s11003M-d5973M-7gres: strongest confidently-rated kata1 net on 2026-10-05
#     (offline judge / referee / strong opponent)
#   - g170e-b10c128 and g170-b6c96: the small nets go-bench's 9x9 tiers lv1..lv8 were calibrated with
# Every file is checked against a pinned SHA-256.  CUDA, cuBLAS and cuDNN come from the host;
# engines/katago is a launcher that adds the user's pip nvidia-* wheels to LD_LIBRARY_PATH.
# GPUs are visible only inside Slurm jobs: run the engine through scripts/slurm/*.sbatch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
E="$ROOT/engines"
REL=katago-v1.18.2-cuda12.8-cudnn9.8.0
mkdir -p "$E/dist" "$E/models"

fetch() {  # url dest sha256
  local url=$1 dest=$2 sum=$3
  if [ -f "$dest" ] && echo "$sum  $dest" | sha256sum -c --status; then return 0; fi
  curl -fsSL -A "Mozilla/5.0" -o "$dest.part" "$url"
  echo "$sum  $dest.part" | sha256sum -c --quiet
  mv "$dest.part" "$dest"
}

fetch "https://github.com/lightvector/KataGo/releases/download/v1.18.2/$REL-linux-x64.zip" \
  "$E/dist/$REL-linux-x64.zip" 2cb197fc9bc2050f29112abb5b83cdbad63936cb4605d6e199772aedc9806c02
fetch "https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz" \
  "$E/models/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz" 93bdb63a3bfae4a70db0cb5265287495ecfc10b1ba1cc6814feeba1cdf055871
fetch "https://github.com/lightvector/KataGo/raw/master/cpp/tests/models/g170e-b10c128-s1141046784-d204142634.bin.gz" \
  "$E/models/g170e-b10c128-s1141046784-d204142634.bin.gz" 1a8e05a4ea3fca20dab79410cbb566c760767fcdd2fa0b701cfe259a84cc8b04
fetch "https://github.com/lightvector/KataGo/raw/master/cpp/tests/models/g170-b6c96-s175395328-d26788732.bin.gz" \
  "$E/models/g170-b6c96-s175395328-d26788732.bin.gz" f5d32604e3675c480c7c8f6aa579a1ea857135628a0afccc8fa56330fbacd38d

[ -x "$E/dist/$REL/katago" ] || unzip -q -o "$E/dist/$REL-linux-x64.zip" -d "$E/dist/$REL"

cat > "$E/katago" <<'LAUNCHER'
#!/usr/bin/env bash
# Launcher for the prebuilt KataGo v1.18.2 CUDA 12.8 / cuDNN 9.8 release (written by fetch_katago.sh).
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
NV="${KATAGO_NVIDIA_LIBS:-$(python3 -c 'import nvidia.cudnn as c, os; print(os.path.dirname(list(c.__path__)[0]))' 2>/dev/null)}"
if [ -n "$NV" ]; then
  export LD_LIBRARY_PATH="$NV/cudnn/lib:$NV/cublas/lib:$NV/cuda_runtime/lib:$NV/cuda_nvrtc/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec "$HERE/dist/katago-v1.18.2-cuda12.8-cudnn9.8.0/katago" "$@"
LAUNCHER
chmod +x "$E/katago"
"$E/katago" version | head -1
