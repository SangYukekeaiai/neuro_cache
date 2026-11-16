#!/bin/bash
set -euo pipefail
ROOT=/work/hdd/bebv/yyu9/fig12_full500_deltaai
REPO=/u/yyu9/projects/neuro_cache_wcache
CONDA=/sw/user/python/miniforge3-pytorch-2.10.0/bin/conda
test "$(uname -m)" = aarch64
export CONDA_PKGS_DIRS="$ROOT/conda_pkgs"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
mkdir -p "$ROOT/logs"
if [ -n "${SLURM_JOB_ID:-}" ]; then
    "$CONDA" run --no-capture-output -p /sw/user/python/miniforge3-pytorch-2.10.0 \
        python -B "$REPO/zoo/fig12_edp/deltaai/budget.py"
fi
exec 9>"$ROOT/environment.lock"
flock 9
if [ -f "$ROOT/environment_ready.json" ]; then exit 0; fi
if [ ! -x "$ROOT/env/bin/python" ]; then
    "$CONDA" create --yes --override-channels -c conda-forge --prefix "$ROOT/env" python=3.12 pip rust
fi
"$CONDA" run --no-capture-output -p "$ROOT/env" python -m pip install \
    -r "$REPO/zoo/fig12_edp/deltaai/requirements.txt"
"$CONDA" run --no-capture-output -p "$ROOT/env" python -m pip freeze > "$ROOT/python_packages.txt"
"$CONDA" list -p "$ROOT/env" --explicit > "$ROOT/conda_explicit.txt"
"$CONDA" run --no-capture-output -p "$ROOT/env" python -B - <<'PY'
import hashlib,json,pathlib,platform,sys,time
root=pathlib.Path('/work/hdd/bebv/yyu9/fig12_full500_deltaai')
assert platform.machine()=='aarch64'
with pathlib.Path(sys.executable).open('rb') as f: header=f.read(20)
assert header[:4]==b'\x7fELF' and int.from_bytes(header[18:20],'little')==183
report={'machine':platform.machine(),'python':sys.version,'executable':sys.executable,'created_unix':time.time(),
        'packages_sha256':hashlib.sha256((root/'python_packages.txt').read_bytes()).hexdigest()}
(root/'environment_ready.json').write_text(json.dumps(report,indent=2)+'\n')
print(report,flush=True)
PY
