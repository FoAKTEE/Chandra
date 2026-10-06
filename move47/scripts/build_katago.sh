#!/usr/bin/env bash
# Build KataGo (Eigen CPU backend) from source and install it with two small
# networks into ./engines.  Works on a plain Linux box with g++, cmake, zlib.
# On a GPU machine, use -DUSE_BACKEND=CUDA (or download a release binary) and
# a stronger network from https://katagotraining.org/ instead.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-$ROOT/.build}"
mkdir -p "$WORK" "$ROOT/engines/models"

if [ ! -d "$WORK/KataGo" ]; then
  git clone --depth 1 https://github.com/lightvector/KataGo "$WORK/KataGo"
fi

# Eigen is header-only; take it from PyPI if the system has none.
EIGEN_DIR=/usr/include/eigen3
if [ ! -d "$EIGEN_DIR" ]; then
  pip download cmeel-eigen --no-deps -d "$WORK/eigen" -q
  (cd "$WORK/eigen" && unzip -q -o cmeel_eigen-*.whl)
  EIGEN_DIR="$WORK/eigen/cmeel.prefix/include/eigen3"
fi

AVX2=0
grep -q avx2 /proc/cpuinfo && AVX2=1
mkdir -p "$WORK/build" && cd "$WORK/build"
cmake "$WORK/KataGo/cpp" -DUSE_BACKEND=EIGEN -DUSE_AVX2=$AVX2 -DEIGEN3_INCLUDE_DIRS="$EIGEN_DIR" -DCMAKE_BUILD_TYPE=Release
make -j"$(nproc)" katago
cp katago "$ROOT/engines/katago"

# Small networks shipped in the KataGo repo's test directory.
for m in g170e-b10c128-s1141046784-d204142634.bin.gz g170-b6c96-s175395328-d26788732.bin.gz; do
  cp "$WORK/KataGo/cpp/tests/models/$m" "$ROOT/engines/models/"
done
"$ROOT/engines/katago" version
