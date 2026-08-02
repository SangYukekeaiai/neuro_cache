#!/usr/bin/env python3
"""One-off diagnostic: find the safe Gurobi WLS concurrent-solve ceiling
on a real Delta compute node, separate from any login-node contention.
Tests increasing worker counts; each level is wrapped in a hard per-task
timeout so a stalled level can't burn the whole interactive walltime.

Not part of the pipeline -- run manually, then delete."""

import json
import pathlib
import sys
import time
from multiprocessing import Pool

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

SCRATCH = pathlib.Path("/u/yyu9/projects/neuro_cache/scripts/tmp/_conc_probe_out")
TRACE_ROOT = pathlib.Path("/u/yyu9/neuro_cache_trace/input_trace/loas")
TRACE_NAME = "vgg16_T4_all"


def solve_one(args):
    arch, layer_name = args
    import tracegen
    with open(TRACE_ROOT / TRACE_NAME / "meta.json") as f:
        meta = json.load(f)
    names = list(meta["layers"])
    idx = names.index(layer_name)
    next_cin = meta["layers"][names[idx + 1]][2] if idx + 1 < len(names) else None
    cache_dir = SCRATCH / arch
    t0 = time.time()
    try:
        tracegen.solve_and_cache_schedule(
            arch, str(REPO / f"configs/arch/multinode_sweep/{arch}_inst16.yaml"),
            str(REPO / f"configs/dataflow/{arch}.yaml"), TRACE_NAME, layer_name,
            meta, next_cin, cache_dir,
        )
        return (arch, layer_name, "OK", time.time() - t0)
    except ValueError:
        return (arch, layer_name, "INFEASIBLE", time.time() - t0)
    except Exception as e:
        return (arch, layer_name, f"ERROR:{type(e).__name__}:{e}", time.time() - t0)


LAYERS = [
    "layer_01_features_3", "layer_02_features_7", "layer_03_features_10", "layer_04_features_14",
    "layer_05_features_17", "layer_06_features_20", "layer_07_features_24", "layer_08_features_27",
    "layer_09_features_30", "layer_10_features_34", "layer_11_features_37", "layer_12_features_40",
]
ARCHS = ["loas", "spinalflow", "ptb", "gustavsnn", "prosperity"]


def probe(n_workers: int, n_tasks: int, per_task_timeout: float = 20.0) -> None:
    tasks = [(ARCHS[i % len(ARCHS)], LAYERS[i % len(LAYERS)]) for i in range(n_tasks)]
    print(f"\n=== {n_workers} workers, {n_tasks} tasks ===", flush=True)
    t0 = time.time()
    with Pool(n_workers) as pool:
        async_result = pool.map_async(solve_one, tasks)
        try:
            results = async_result.get(timeout=per_task_timeout * n_tasks / max(1, n_workers) + 30)
        except Exception as e:
            wall = time.time() - t0
            print(f"TIMED OUT / FAILED after {wall:.1f}s: {e}", flush=True)
            pool.terminate()
            pool.join()
            return
    wall = time.time() - t0
    n_ok = sum(1 for r in results if r[2] == "OK")
    n_inf = sum(1 for r in results if r[2] == "INFEASIBLE")
    n_err = sum(1 for r in results if r[2].startswith("ERROR"))
    per_task_times = [r[3] for r in results]
    print(f"wall={wall:.2f}s  OK={n_ok} INFEASIBLE={n_inf} ERROR={n_err}  "
          f"per-task min/avg/max={min(per_task_times):.2f}/{sum(per_task_times)/len(per_task_times):.2f}/{max(per_task_times):.2f}s",
          flush=True)
    for r in results:
        if r[2].startswith("ERROR"):
            print("  ", r, flush=True)


if __name__ == "__main__":
    import multiprocessing
    print(f"CPU count visible: {multiprocessing.cpu_count()}", flush=True)
    for n in (8, 16, 24, 32, 48, 64):
        probe(n, n_tasks=n * 2)
