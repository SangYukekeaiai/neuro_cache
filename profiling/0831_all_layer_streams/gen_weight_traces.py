#!/usr/bin/env python3
"""The second artifact form: one sample_NNNNN.json.gz per (layer, sample).

nocsim reads a saved weight-trace sample, not a WCTS stream (`nocsim/sim.py`'s
--weight-trace: "path to ONE saved weight-trace sample"), so comparing wcache
against nocsim over all 31 layers needs this form as well as `streams/`. Same
Stage 1 schedules, same five committed samples, same generator; only the output
form differs.

The combo tag matches the 0823 run's, `noc2MiB_node32kb`, so the layout under
weight_traces/ is identical to `stage2_weight_trace/outputs/weight_traces/` and
the gate below can diff against it.

One sample per subprocess, as in gen_streams.py: the native call holds a
sample's whole per-tile weight-address list in memory at once, and asking for
five at a time multiplies that by five for no gain.

    conda run -n base python profiling/0831_all_layer_streams/gen_weight_traces.py --workers 16
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402

PYTHON = "/u/yyu9/miniconda3/bin/python"
GENERATOR = ROOT / "scripts/generate_weight_traces.py"
ARCH = "loas"
COMBO_TAG = "noc2MiB_node32kb"
TRACE_ROOT = ROOT / "input_trace/loas"
SCHEDULES = STAGE / "schedules"
OUT_DIR = STAGE / "weight_traces"
N_SAMPLES = 5
WORKLOADS = [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]

# The 20 the 0823 run produced, for the gate.
STAGE2 = ROOT / "profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces" / ARCH / COMBO_TAG
CHECK = [("vgg16_T4_n5", "layer_08_features_27"), ("vgg16_T4_n5", "layer_09_features_30"),
         ("resnet19_T4_n5", "layer_09_layer2_0_conv2"), ("resnet19_T4_n5", "layer_16_layer3_0_conv2")]


def sample_path(trace_dir: str, layer: str, sample: int) -> pathlib.Path:
    return OUT_DIR / ARCH / COMBO_TAG / trace_dir / layer / f"sample_{sample:05d}.json.gz"


def tasks() -> list:
    out = []
    for _, trace_dir in WORKLOADS:
        meta = json.loads((TRACE_ROOT / trace_dir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            out.extend((trace_dir, layer, s) for s in range(N_SAMPLES))
    return out


def generate(task) -> tuple:
    trace_dir, layer, sample = task
    dst = sample_path(trace_dir, layer, sample)
    if dst.exists():
        return layer, sample, dst.stat().st_size, 0.0, True
    t0 = time.time()
    subprocess.run(
        [PYTHON, str(GENERATOR), "--arch", ARCH,
         "--trace-root", str(TRACE_ROOT), "--trace-dir", trace_dir, "--layer", layer,
         "--schedule-cache", str(SCHEDULES), "--out-dir", str(OUT_DIR),
         "--combo-tag", COMBO_TAG, "--workers", "1",
         "--sample-start", str(sample), "--sample-count", "1"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return layer, sample, dst.stat().st_size, time.time() - t0, False


def run_check() -> int:
    """The four 0823 layers must decode to the same trace the 0823 run saved.

    Compared as decoded JSON rather than as gzip bytes: gzip embeds an mtime,
    so two identical traces written at different times differ as files while
    being the same trace.
    """
    failures = 0
    for trace_dir, layer in CHECK:
        for s in range(N_SAMPLES):
            got_p, want_p = sample_path(trace_dir, layer, s), STAGE2 / trace_dir / layer / f"sample_{s:05d}.json.gz"
            if not want_p.exists():
                continue
            ok = json.loads(gzip.decompress(got_p.read_bytes())) == json.loads(gzip.decompress(want_p.read_bytes()))
            failures += not ok
            if not ok:
                print(f"  {layer} s{s}: DIFFERS from {want_p}")
    print("check: OK, all 20 overlapping traces match the 0823 run" if not failures
          else f"check: FAILED on {failures} trace(s)")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    if args.check:
        return run_check()

    todo = tasks()
    print(f"=== {len(todo)} weight traces, {args.workers} workers -> {OUT_DIR} ===", flush=True)
    t_start, total, n_new = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(generate, t): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            task = futures[future]
            try:
                layer, sample, size, dt, cached = future.result()
            except Exception as exc:
                print(f"  [{i}/{len(todo)}] {task[1]} s{task[2]}: FAILED ({exc!r})", flush=True)
                continue
            total += size
            n_new += not cached
            print(f"  [{i}/{len(todo)}] {layer} s{sample}: {size / 2**20:.1f} MiB"
                  f"{' (had it)' if cached else f' in {dt:.1f}s'}", flush=True)
    print(f"\n{n_new} generated, {len(todo) - n_new} already present, "
          f"{total / 2**30:.2f} GiB, {time.time() - t_start:.1f}s")
    print("--- gate ---")
    return run_check()


if __name__ == "__main__":
    raise SystemExit(main())
