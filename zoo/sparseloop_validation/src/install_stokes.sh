#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
module is-loaded anaconda/anaconda-2024.10 || module load anaconda/anaconda-2024.10
module is-loaded gcc/gcc-9.1.0 || module load gcc/gcc-9.1.0
export CONDA_ENVS_PATH="$root/vendor/envs" CONDA_PKGS_DIRS="$root/vendor/conda_pkgs"
export PIP_CACHE_DIR="$root/vendor/pip_cache" PYTHONDONTWRITEBYTECODE=1
export TMPDIR="$root/outputs/tmp" XDG_CACHE_HOME="$root/outputs/cache"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"
if [ ! -x "$root/vendor/envs/tlv/bin/python" ]; then conda create -y -p "$root/vendor/envs/tlv" --override-channels -c conda-forge python=3.10 'boost-cpp=1.74' 'yaml-cpp=0.6.3' 'libconfig=1.7.2' ncurses scons pip numpy pyyaml; fi
conda run --no-capture-output -p "$root/vendor/envs/tlv" python -m pip install "$root/vendor/paper_backend/accelergy"
# Install prerequisites via Conda instead of the artifact Dockerfile's root apt commands.
ln -sfn ../pat-public/src/pat "$root/vendor/paper_backend/timeloop/src/pat"
export BOOSTDIR="$root/vendor/envs/tlv" LIBCONFIGPATH="$root/vendor/envs/tlv"
export CPLUS_INCLUDE_PATH="$root/vendor/envs/tlv/include"
export LIBRARY_PATH="$root/vendor/envs/tlv/lib" LD_LIBRARY_PATH="$root/vendor/envs/tlv/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$root/vendor/paper_backend/timeloop"
conda run --no-capture-output -p "$root/vendor/envs/tlv" scons -j2 --accelergy build/timeloop-model
