#!/usr/bin/env python3
"""Stage 1 for the all-layer stream set: one canonical schedule per layer.

Every valid layer of vgg16 and resnet19 solved at the SAME canonical config the
0823 verification pinned -- `pe16`, NoCLevel global buffer 2 MiB, node 32 KB --
so the 31-layer set is directly comparable to the four layers Stage 4 already
replays. That is one solve per layer, not 0823's 27, because the num_pes /
TrafficMode / NoC-size sweeps were answered there and are not re-asked here.

Shapes come from the `_all` meta.json on /work; no spike data is read. The
schedule is shape-derived, so each artifact is written twice: once under the
`_all` name it was solved from, and once with `trace_dir` rewritten to the
committed `_n5` subset, which is what Stage 2 reconstructs against. This is the
same rewrite `stage2_weight_trace/run_stage2.py:stage_inputs` performs.

Licensing: the personal WLS key in /u/yyu9/gurobi.lic is the default. It had
expired when this ran on 2026-08-31 and was extended mid-run, so the fallback
that unblocked it is recorded here rather than hardcoded -- NCSA runs a Gurobi
token server, and

    export GRB_LICENSE_FILE=/sw/external/containers_other/gurobi/gurobi.lic

is all it takes to use it. Both licenses were checked to give the same answer:
--check re-solves the four 0823 layers and diffs them against that run's
artifacts, and it passed on the token server before the 31-layer solve.

    conda run -n base python profiling/0831_all_layer_streams/solve_all_layers.py --check
    conda run -n base python profiling/0831_all_layer_streams/solve_all_layers.py
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[1]
STAGE1_0823 = ROOT / "profiling/0823_stagewise_verify/stage1_mip_solver"

sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402
import tracegen  # noqa: E402

ARCH = "loas"
ARCH_YAML = STAGE1_0823 / "inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml"
DATAFLOW_YAML = STAGE1_0823 / "inputs/dataflow/loas.yaml"
TRACE_ROOT = pathlib.Path("/work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas")
PAIRS = [("vgg16_T4_all", "vgg16_T4_n5"), ("resnet19_T4_all", "resnet19_T4_n5")]

OUT_ALL = STAGE / "schedules_all"          # solved artifacts, `_all` trace_dir
OUT_N5 = STAGE / "schedules"               # same artifacts, trace_dir -> `_n5`

# The four layers 0823 solved, for --check. Byte equality against that run is
# what says the token server and gurobipy 13.0.2 give the same answer the
# expired WLS key did.
CHECK_LAYERS = [
    ("vgg16_T4_all", "layer_08_features_27"),
    ("vgg16_T4_all", "layer_09_features_30"),
    ("resnet19_T4_all", "layer_09_layer2_0_conv2"),
    ("resnet19_T4_all", "layer_16_layer3_0_conv2"),
]


def load_meta(trace_dir: str) -> dict:
    return json.loads((TRACE_ROOT / trace_dir / "meta.json").read_text())


def next_cin_for(meta: dict, layer: str):
    names = list(meta["layers"])
    i = names.index(layer)
    return meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None


def solve_one(trace_dir: str, layer: str, meta: dict, out_root: pathlib.Path):
    return tracegen.solve_and_cache_schedule(
        ARCH, str(ARCH_YAML), str(DATAFLOW_YAML),
        trace_dir, layer, meta, next_cin_for(meta, layer), out_root)


def write_n5_copy(all_dir: str, n5_dir: str, layer: str) -> pathlib.Path:
    """Re-file one solved artifact under the 5-sample subset's directory name.

    Only `trace_dir` changes; the schedule itself is shape-derived and the two
    directories hold the same shapes, so nothing is re-solved.
    """
    src = OUT_ALL / ARCH / all_dir / f"{layer}.json"
    dst = OUT_N5 / ARCH / n5_dir / f"{layer}.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(src.read_text())
    doc["trace_dir"] = n5_dir
    dst.write_text(json.dumps(doc, indent=1) + "\n")
    return dst


def run_check() -> int:
    """Re-solve 0823's four layers into a scratch tree and diff against it."""
    scratch = STAGE / "_check"
    failures = 0
    for trace_dir, layer in CHECK_LAYERS:
        meta = load_meta(trace_dir)
        solve_one(trace_dir, layer, meta, scratch)
        got = (scratch / ARCH / trace_dir / f"{layer}.json").read_text()
        want_path = STAGE1_0823 / "outputs/schedules/pe16" / ARCH / trace_dir / f"{layer}.json"
        want = want_path.read_text()
        ok = json.loads(got) == json.loads(want)
        print(f"  {trace_dir}/{layer}: {'MATCH' if ok else 'DIFFERS from ' + str(want_path)}")
        failures += not ok
    print("check: OK, the token server reproduces 0823" if not failures
          else f"check: FAILED on {failures} layer(s)")
    return 1 if failures else 0


def run_all() -> int:
    t_start = time.time()
    for all_dir, n5_dir in PAIRS:
        meta = load_meta(all_dir)
        layers = valid_layer_names(meta)
        print(f"=== {all_dir}: {len(layers)} layers ===", flush=True)
        for layer in layers:
            t0 = time.time()
            art = solve_one(all_dir, layer, meta, OUT_ALL)
            write_n5_copy(all_dir, n5_dir, layer)
            print(f"  {layer:28s} {art.result['status']:8s} "
                  f"obj={art.result['objective']:.6f} steps={art.dram_num_steps} "
                  f"mode={art.mode} ({time.time() - t0:.1f}s)", flush=True)
    print(f"solved in {time.time() - t_start:.1f}s -> {OUT_N5}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true",
                   help="Re-solve 0823's four layers and diff, solving nothing else.")
    args = p.parse_args()
    raise SystemExit(run_check() if args.check else run_all())
