#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=$PWD
module load anaconda/anaconda-2024.10
export CONDA_PKGS_DIRS="$root/vendor/conda_pkgs"
conda install -y -p "$root/vendor/envs/tlv" --override-channels -c conda-forge 'yaml-cpp=0.6.3' 'libconfig=1.7.2'
bash src/install_stokes.sh
