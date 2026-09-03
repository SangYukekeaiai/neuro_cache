#!/usr/bin/env python3
"""Stage 2 for the all-layer stream set: 31 layers x 5 samples of WCTS.

Extends the four layers `stage4_wcache/inputs/streams` holds (V8, V9, R9, R16)
to every valid layer of both workloads, against the Stage 1 schedules in
`schedules/` and the committed 5-sample subset in `input_trace/loas`.

Tags are `V<n>` and `R<n>` with the layer's own number, unpadded, so the four
layers already on disk keep the names Stage 4 and the 0831 plans call them by.

Two things this script will not do, both learned the hard way:

  * It calls the interpreter at PYTHON directly rather than through `conda run`.
    `conda run` decodes the child's stdout as text, so 0xe4 comes back as the
    three bytes of U+FFFD and the stream is silently corrupt.
  * It takes the stream from --dump-trace, which the generator writes from
    Python, rather than from a stdout redirect. Same reason.

--check is the gate: the four layers that already exist must come out
byte-identical to the files Stage 4 has been replaying. It runs on its own, and
also automatically after a full generation.

    conda run -n base python profiling/0831_all_layer_streams/gen_streams.py --check
    conda run -n base python profiling/0831_all_layer_streams/gen_streams.py --workers 16
"""
from __future__ import annotations

import argparse
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
TRACE_ROOT = ROOT / "input_trace/loas"
SCHEDULES = STAGE / "schedules"
STREAMS = STAGE / "streams"
N_SAMPLES = 5
# tag prefix per trace dir
WORKLOADS = [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]

# The four streams Stage 4 already replays, and where they live.
STAGE4 = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/inputs/streams"
CHECK_TAGS = ["V8", "V9", "R9", "R16"]


def tasks() -> list:
    """(tag, trace_dir, layer, sample) for every layer of both workloads.

    The tag number is the layer's own `layer_NN_` prefix rather than an
    enumeration counter, so it stays right if a layer is ever dropped.
    """
    out = []
    for prefix, trace_dir in WORKLOADS:
        meta = json.loads((TRACE_ROOT / trace_dir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            tag = f"{prefix}{int(layer.split('_')[1])}"
            out.extend((tag, trace_dir, layer, s) for s in range(N_SAMPLES))
    return out


def generate(task) -> tuple:
    tag, trace_dir, layer, sample = task
    dst = STREAMS / f"{tag}_s{sample:05d}.wcts"
    if dst.exists():
        return tag, sample, dst.stat().st_size, 0.0, True
    t0 = time.time()
    subprocess.run(
        [PYTHON, str(GENERATOR), "--arch", ARCH,
         "--trace-root", str(TRACE_ROOT), "--trace-dir", trace_dir, "--layer", layer,
         "--schedule-cache", str(SCHEDULES), "--workers", "1", "--stream",
         "--sample-start", str(sample), "--sample-count", "1",
         "--dump-trace", str(dst)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tag, sample, dst.stat().st_size, time.time() - t0, False


def run_check() -> int:
    failures = 0
    for tag in CHECK_TAGS:
        got, want = STREAMS / f"{tag}_s00000.wcts", STAGE4 / f"{tag}_s00000.wcts"
        if not got.exists():
            print(f"  {tag}: not generated yet")
            failures += 1
            continue
        ok = got.read_bytes() == want.read_bytes()
        print(f"  {tag}_s00000: {'byte-identical to Stage 4' if ok else 'DIFFERS from ' + str(want)}")
        failures += not ok
    print("check: OK, this set reproduces the streams Stage 4 replays" if not failures
          else f"check: FAILED on {failures} stream(s)")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--check", action="store_true", help="Only run the byte-identity gate.")
    args = p.parse_args()
    if args.check:
        return run_check()

    STREAMS.mkdir(parents=True, exist_ok=True)
    todo = tasks()
    print(f"=== {len(todo)} streams, {args.workers} workers -> {STREAMS} ===", flush=True)
    t_start, total_bytes, n_new = time.time(), 0, 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(generate, t): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            task = futures[future]
            try:
                tag, sample, size, dt, cached = future.result()
            except Exception as exc:  # one layer failing shouldn't sink the rest
                print(f"  [{i}/{len(todo)}] {task[0]}_s{task[3]:05d}: FAILED ({exc!r})", flush=True)
                continue
            total_bytes += size
            n_new += not cached
            print(f"  [{i}/{len(todo)}] {tag}_s{sample:05d}: {size / 2**20:.1f} MiB"
                  f"{' (had it)' if cached else f' in {dt:.1f}s'}", flush=True)
    print(f"\n{n_new} generated, {len(todo) - n_new} already present, "
          f"{total_bytes / 2**30:.1f} GiB total, {time.time() - t_start:.1f}s")
    print("--- gate ---")
    return run_check()


if __name__ == "__main__":
    raise SystemExit(main())
