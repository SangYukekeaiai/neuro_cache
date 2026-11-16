"""Build native programs once per host workspace; refuse subsequent source drift."""
import argparse
import fcntl
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO/'zoo/fig12_edp/stokes'))
import stage1_worker as worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(); build = root/'build'; build.mkdir(parents=True, exist_ok=True)
    with (root/'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sources = {}
        for directory in ('cachesim/native', 'nocsim/eventsim', 'weight_trace_gen'):
            for p in (REPO/'src/lays'/directory).rglob('*'):
                if p.is_file() and 'build' not in p.parts and (p.suffix in ('.cpp', '.h', '.hpp') or p.name == 'Makefile'):
                    sources[str(p.relative_to(REPO))] = worker.digest(p)
        receipt = build/'native_ready.json'
        if receipt.exists():
            saved = worker.load(receipt)
            if saved['machine'] != platform.machine() or saved['sources'] != sources:
                raise ValueError('native source/ISA changed; use a fresh build workspace')
            for name, sha in saved['binaries'].items():
                if worker.digest(Path(name)) != sha:
                    raise ValueError('native binary changed: '+name)
            print('NATIVE_REUSED '+str(receipt), flush=True)
            return
        def run(argv):
            subprocess.run(argv, cwd=REPO, check=True)
        native = 'src/lays/cachesim/native'
        make = ['make', '-C', native, 'MODE=release', 'BUILDDIR='+str(build/'cachesim'), '-j2']
        run(make+['all'])
        test = build/'cachesim/prefetch/test_next_line'
        run(make+[str(test)])
        run([str(test), str(REPO/'zoo/fig12_edp/configs/production_cache_b.json')])
        run(['make', '-C', 'src/lays/nocsim/eventsim', 'BIN='+str(build/'eventsim'), '-B', '-j2'])
        binaries = [build/'cachesim/cachesim_run', build/'eventsim']
        for arch in ('spinalflow', 'ptb', 'loas', 'gustavsnn', 'prosperity'):
            directory = REPO/'src/lays/weight_trace_gen'/arch
            run(['make', '-C', str(directory), '-B', '-j2'])
            binaries.append(directory/('gustavgen' if arch == 'gustavsnn' else arch+'gen'))
        expected = {'x86_64': 62, 'aarch64': 183}[platform.machine()]
        for p in binaries:
            with p.open('rb') as stream: header = stream.read(20)
            if header[:4] != b'\x7fELF' or int.from_bytes(header[18:20], 'little') != expected:
                raise ValueError('wrong native ISA: '+str(p))
        worker.save(receipt, {'machine': platform.machine(), 'host': platform.node(),
            'job': os.environ.get('SLURM_JOB_ID'), 'sources': sources,
            'binaries': {str(p): worker.digest(p) for p in binaries},
            'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
            'finished_unix': time.time()})
        print('NATIVE_BUILT '+str(receipt), flush=True)


if __name__ == '__main__':
    main()
