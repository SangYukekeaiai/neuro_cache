# Shared shell settings; set root to the repo root, then: . "$root/scripts/env.sh"
# Same default and layout as data_root() in src/util.py; override from the environment.
: "${NEURO_CACHE_DATA:=$root/data}"
: "${CONDA_ENV:=cosa_snn}"
export NEURO_CACHE_DATA CONDA_ENV
