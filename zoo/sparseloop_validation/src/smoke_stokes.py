"""Run one unmodified shipped sparse example; record the installed environment."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    output=ROOT/'outputs/smoke';output.mkdir(parents=True,exist_ok=True)
    backend=ROOT/'vendor/paper_backend/timeloop'
    binary=backend/'build/timeloop-model'
    specs=ROOT/'vendor/smoke_example'
    # Avoid Accelergy's default creation of a home-directory configuration.
    (output/'accelergy_config.yaml').write_text('version: 0.3\nestimator_plug_ins: []\nprimitive_components: []\ncompound_components: []\n')
    pins=json.loads((ROOT/'vendor/paper_backend_files.json').read_text())
    for name,expected in pins.items():
        assert digest(ROOT/'vendor/paper_backend'/name)==expected, name
    command=[str(binary),*(str(specs/p) for p in ('aggregated_input.yaml','ERT.yaml','ART.yaml'))]
    with (output/'timeloop.log').open('w') as stream:
        result=subprocess.run(command,cwd=output,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
    if result.returncode:raise RuntimeError(f'shipped example exited {result.returncode}')
    stats=output/'timeloop-model.stats.txt';assert stats.exists() and stats.stat().st_size
    with (output/'accelergy_help.txt').open('w') as f:
        subprocess.run([str(Path(sys.executable).with_name('accelergy')),'--help'],cwd=output,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=30)
    freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True)
    (output/'pip_freeze.txt').write_text(freeze)
    report=json.loads((ROOT/'outputs/env_manifest.json').read_text())
    report.update(status='smoke_passed',smoke_passed=True,completed_utc=datetime.now(timezone.utc).isoformat(),
                  hostname=platform.node(),python=sys.version,python_executable=sys.executable,
                  pinned_backend_files_verified=len(pins),compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
                  command=command,binary_sha256=digest(binary),
                  smoke_inputs={p.name:digest(p) for p in specs.glob('*.yaml')},
                  outputs={str(p.relative_to(ROOT)):digest(p) for p in output.iterdir() if p.is_file()},
                  caveat='Shipped DSTC example only; no LoAS Tier B/C runs')
    (ROOT/'outputs/env_manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'smoke_passed':True,'stats':str(stats),'binary_sha256':digest(binary)}))

if __name__=='__main__':main()
