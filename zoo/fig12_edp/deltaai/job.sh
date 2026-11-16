#!/bin/bash
set -euo pipefail
ROOT=/work/hdd/bebv/yyu9/fig12_full500_deltaai
REPO=/u/yyu9/projects/neuro_cache_wcache
test "$(uname -m)" = aarch64
cd "$REPO"
if [ "${SLURM_JOB_PARTITION:-}" = ghx4-interactive ]; then
    mkdir -p "$ROOT/interactive_outcomes"
    exec 8>"$ROOT/interactive_lane.lock"
    if ! flock -n 8; then
        python -B -c 'import json,os,pathlib; p=pathlib.Path("/work/hdd/bebv/yyu9/fig12_full500_deltaai/interactive_outcomes")/(os.environ["SLURM_JOB_ID"]+".json"); p.write_text(json.dumps({"status":"lost_race"})+"\n")'
        exit 0
    fi
    if python -B - "$1" <<'PY'
import json,pathlib,sys
p=pathlib.Path('/work/hdd/bebv/yyu9/fig12_full500_deltaai/interactive_status.json')
s=json.loads(p.read_text()) if p.exists() else {}
sys.exit(0 if int(sys.argv[1]) in s.get('handed_to_batch',[]) else 1)
PY
    then
        python -B -c 'import json,os,pathlib; p=pathlib.Path("/work/hdd/bebv/yyu9/fig12_full500_deltaai/interactive_outcomes")/(os.environ["SLURM_JOB_ID"]+".json"); p.write_text(json.dumps({"status":"already_handed_to_batch"})+"\n")'
        exit 0
    fi
    python -B -c 'import json,os,pathlib; p=pathlib.Path("/work/hdd/bebv/yyu9/fig12_full500_deltaai/interactive_outcomes")/(os.environ["SLURM_JOB_ID"]+".json"); p.write_text(json.dumps({"status":"owns_lane"})+"\n")'
fi
export LD_LIBRARY_PATH="$ROOT/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CARGO_BUILD_JOBS=1 CARGO_HOME="$ROOT/cargo_home" CARGO_TARGET_DIR="$ROOT/build/rust_aarch64"
(
    flock 9
    if [ ! -f "$ROOT/archx_ready.json" ]; then
        python -m pip install --no-build-isolation --no-deps -e ./zoo/archx
        python -B - <<'PY'
import hashlib,json,pathlib,platform,time,archx._core
root=pathlib.Path('/work/hdd/bebv/yyu9/fig12_full500_deltaai')
repo=pathlib.Path('/u/yyu9/projects/neuro_cache_wcache')
core=pathlib.Path(archx._core.__file__).resolve()
assert platform.machine()=='aarch64' and core.is_relative_to(repo/'zoo/archx/src')
with core.open('rb') as f: header=f.read(20)
assert header[:4]==b'\x7fELF' and int.from_bytes(header[18:20],'little')==183
report={'machine':platform.machine(),'archx_core':str(core),'sha256':hashlib.sha256(core.read_bytes()).hexdigest(),'built_unix':time.time()}
(root/'archx_ready.json').write_text(json.dumps(report,indent=2)+'\n')
print(report,flush=True)
PY
    fi
) 9>"$ROOT/archx_build.lock"
python -B - <<'PY'
import hashlib,json,pathlib,platform,archx._core
r=json.loads(pathlib.Path('/work/hdd/bebv/yyu9/fig12_full500_deltaai/archx_ready.json').read_text())
p=pathlib.Path(archx._core.__file__).resolve()
assert platform.machine()==r['machine']=='aarch64'
assert str(p)==r['archx_core'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
print('ARM_ARCHX_CORE '+str(p),flush=True)
PY
sample=$1
shift
if [ "${SLURM_JOB_PARTITION:-}" = ghx4-interactive ] && [ "${SLURM_GPUS_ON_NODE:-}" = 1 ]; then
    set -- "$@" --memory-gib 100 --cores 72 --defer-oversize
fi
exec bash zoo/fig12_edp/delta/node.sh "$ROOT" "$sample" --memory-gib 420 --cores 288 "$@"
