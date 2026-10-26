#!/usr/bin/env python3
"""The locally runnable wcache case: the 0823 stage 4 khkw sweep (48 configs x
4 LoAS layers x 5 samples = 960 rows) from tracked inputs only, no Gurobi.

  run      regenerate the 20 WCTS streams with src/tracegen.py into
           $NEURO_CACHE_DATA/neuro_cache_outputs/wcache_baseline/streams and run
           the sweep on them -> .../wcache_baseline/khkw_sweep.csv
  compare  compare two sweep CSVs cell by cell, in row order, ignoring the
           columns that differ between identical runs; exit 1 on any mismatch

usage: python scripts/wcache_baseline.py run [--jobs N]
       python scripts/wcache_baseline.py compare REF NEW
"""
import argparse
import concurrent.futures as cf
import csv
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "profiling"),
                str(ROOT / "profiling/0823_stagewise_verify/stage4_wcache")]
import run_khkw_sweep as sweep  # noqa: E402
from common import tags  # noqa: E402
from util import data_root  # noqa: E402

SCHEDULES = ROOT / "profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules"
# Run metadata, not results: the commit hash and the wall-clock time of each run.
IGNORED_COLUMNS = ("git_commit", "sim_wall_seconds")


def out_dir():
    return data_root() / "neuro_cache_outputs/wcache_baseline"


def gen_stream(trace_dir, layer, sample, dst):
    """One sample's WCTS file, made the way stage4_wcache/inputs/gen_streams.sh makes it."""
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_weight_traces.py"),
         "--arch", "loas", "--trace-dir", trace_dir, "--layer", layer,
         "--schedule-cache", str(SCHEDULES), "--workers", "1", "--stream",
         "--sample-start", str(sample), "--sample-count", "1", "--dump-trace", str(dst)],
        stdout=subprocess.DEVNULL, check=True)


def run(jobs):
    out = out_dir()
    streams = out / "streams"
    streams.mkdir(parents=True, exist_ok=True)
    layers = {tag: (d, layer) for tag, d, layer in tags()}
    work = [(*layers[tag], s, streams / f"{tag}_s{s:05d}.wcts")
            for tag in sweep.TAGS for s in sweep.SAMPLES]
    print(f"generating {len(work)} streams -> {streams}", flush=True)
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(lambda w: gen_stream(*w), work))
    sweep.STRM, sweep.OUT, sweep.GRID = streams, out, out / "_khkw_grid"
    sys.argv = [sys.argv[0], str(jobs)]
    return sweep.main()


def compare(ref_path, new_path):
    """Number of differences between two sweep CSVs, printing each one."""
    ref = list(csv.reader(open(ref_path, newline="")))
    new = list(csv.reader(open(new_path, newline="")))
    if ref[0] != new[0]:
        print(f"header differs:\n  ref {ref[0]}\n  new {new[0]}")
        return 1
    if len(ref) != len(new):
        print(f"row count differs: ref {len(ref) - 1}, new {len(new) - 1}")
        return 1
    header = ref[0]
    keep = [i for i, c in enumerate(header) if c not in IGNORED_COLUMNS]
    dropped = [f"{i + 1}:{header[i]}" for i in range(len(header)) if i not in keep]
    bad = 0
    for r, (a, b) in enumerate(zip(ref[1:], new[1:]), start=1):
        for i in keep:
            if a[i] != b[i]:
                bad += 1
                print(f"  row {r} col {i + 1} {header[i]}: ref {a[i]!r} new {b[i]!r}")
    print(f"rows {len(ref) - 1}, columns compared {len(keep)} of {len(header)} "
          f"(dropped {', '.join(dropped)}), mismatches {bad}")
    return bad


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").add_argument("--jobs", type=int, default=16)
    c = sub.add_parser("compare")
    c.add_argument("ref")
    c.add_argument("new")
    a = p.parse_args()
    if a.cmd == "run":
        return run(a.jobs)
    return 1 if compare(a.ref, a.new) else 0


if __name__ == "__main__":
    sys.exit(main())
