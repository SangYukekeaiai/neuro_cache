#!/usr/bin/env python3
"""Stage 1 of the 2026-08-23 stagewise verification: the MIP solver.

Solves the two LoAS deep layers on the 16-core arch and answers three
questions:

  A. does `num_pes` move the schedule?
  B. are all 13 TrafficModes actually enumerated, and which one wins?
  C. how small can the NoCLevel global buffer get, and where does shrinking
     it start changing the schedule?

Everything this stage reads is copied into inputs/ first, and everything it
produces lands in outputs/. Nothing else is written, and no later stage's
inputs are prepared here.

    conda run -n base python profiling/0823_stagewise_verify/stage1_mip_solver/run_stage1.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
import sys
import time

import yaml

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[2]
IN, OUT = STAGE / "inputs", STAGE / "outputs"

sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import build_workload_from_trace  # noqa: E402
from mip_solver.modes import TrafficMode  # noqa: E402
from mip_solver.solve import _mode_score, solve_schedule  # noqa: E402
import tracegen  # noqa: E402

# --- what this stage reads -------------------------------------------------
BASE_ARCH = ROOT / "configs/arch/multinode_sweep/loas_inst16_node32kb_noc4096kb.yaml"
BASE_DATAFLOW = ROOT / "configs/dataflow/loas.yaml"
TRACE_ROOT = pathlib.Path("/work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas")
# Four layers, two density regimes. The 0823 run used only the two dense ones;
# the 0823 survey (HANDOFF-ANSWER.md) placed them above the published band and
# added a representative layer per workload. Both regimes stay in the sweep so
# every whole-file output below remains a superset of the earlier record.
LAYERS = [
    # representative: densities 0.1995 and 0.184, inside the published band
    ("vgg16_T4_all", "layer_08_features_27"),
    ("resnet19_T4_all", "layer_09_layer2_0_conv2"),
    # stress case: 0.578, and 0.424 which is LoAS Table II's own R-L19 figure
    ("vgg16_T4_all", "layer_09_features_30"),
    ("resnet19_T4_all", "layer_16_layer3_0_conv2"),
]
PES = [4, 16, 64, 256]
CANONICAL_PES = 16
CANONICAL_NOC = 2 << 20

# NoCLevel global-buffer totals to sweep, in bytes, each split 30:1:1 the same
# way the arch files do.
NOC_TOTALS = [4 << 20, 2 << 20, 1 << 20, 512 << 10, 256 << 10, 128 << 10,
              64 << 10, 32 << 10, 16 << 10, 8 << 10]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def split_30_1_1(total: int) -> dict:
    """Split a byte total 30:1:1 across weight/psum/vmem, as the arch files do."""
    unit = total // 32
    return {"weight": 30 * unit, "psum": unit, "vmem": unit}


def write_arch(base: dict, out: pathlib.Path, *, num_pes=None, noc_total=None) -> pathlib.Path:
    doc = copy.deepcopy(base)
    if num_pes is not None:
        doc["arch"]["storage"][0]["pe"]["num_pes"] = num_pes
    if noc_total is not None:
        doc["arch"]["storage"][1]["entries"] = split_30_1_1(noc_total)
    out.write_text(yaml.safe_dump(doc, sort_keys=False))
    return out


def kb(n: int) -> str:
    return f"{n >> 20}MiB" if n >= (1 << 20) else f"{n >> 10}KiB"


def stage_inputs() -> dict:
    """Copy every input into inputs/ and return the manifest-backed handles."""
    shutil.copy2(BASE_DATAFLOW, IN / "dataflow" / BASE_DATAFLOW.name)
    base = yaml.safe_load(BASE_ARCH.read_text())

    arch_pes = {
        pes: write_arch(base, IN / "arch" / f"loas_inst16_node32kb_noc{kb(CANONICAL_NOC)}_pe{pes}.yaml",
                        num_pes=pes, noc_total=CANONICAL_NOC)
        for pes in PES
    }
    arch_noc = {
        tot: write_arch(base, IN / "arch" / f"loas_inst16_node32kb_noc{kb(tot)}_pe{CANONICAL_PES}.yaml",
                        num_pes=CANONICAL_PES, noc_total=tot)
        for tot in NOC_TOTALS
    }

    metas = {t: json.loads((TRACE_ROOT / t / "meta.json").read_text())
             for t in sorted({t for t, _ in LAYERS})}
    workloads = {}
    for trace_dir, layer in LAYERS:
        meta = metas[trace_dir]
        names = list(meta["layers"])
        i = names.index(layer)
        next_cin = meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None
        wl = build_workload_from_trace(meta, layer, next_cin=next_cin)
        p = IN / "workloads" / f"{trace_dir}__{layer}.yaml"
        p.write_text(yaml.safe_dump(wl, sort_keys=False))
        workloads[(trace_dir, layer)] = (p, next_cin)

    manifest = {
        "stage": "1_mip_solver",
        "solver": "gurobipy, via mip_solver.solve",
        "traffic_modes_enumerated": [m.value for m in TrafficMode],
        "base_arch": {"path": str(BASE_ARCH.relative_to(ROOT)), "sha256_16": sha(BASE_ARCH)},
        "dataflow": {"path": str(BASE_DATAFLOW.relative_to(ROOT)), "sha256_16": sha(BASE_DATAFLOW)},
        "shape_source": {
            "trace_root": str(TRACE_ROOT),
            "files": [str(TRACE_ROOT / t / "meta.json") for t in sorted(metas)],
            "note": "meta.json supplies CIN/HO/WO/T only; COUT is the next layer's CIN. "
                    "No spike data is read in this stage.",
        },
        "arch_variants_num_pes": {
            str(pes): {"path": f"inputs/arch/{p.name}", "num_pes": pes, "sha256_16": sha(p)}
            for pes, p in arch_pes.items()
        },
        "arch_variants_noc_size": {
            kb(tot): {"path": f"inputs/arch/{p.name}", "noc_total_bytes": tot,
                      "entries": split_30_1_1(tot), "sha256_16": sha(p)}
            for tot, p in arch_noc.items()
        },
        "workloads": {
            f"{t}/{l}": {"path": f"inputs/workloads/{p.name}",
                         "next_cin_used_as_cout": nc, "sha256_16": sha(p)}
            for (t, l), (p, nc) in workloads.items()
        },
        "canonical": {"num_pes": CANONICAL_PES, "noc_total_bytes": CANONICAL_NOC},
    }
    (IN / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return {"arch_pes": arch_pes, "arch_noc": arch_noc, "metas": metas,
            "workloads": workloads}


def next_cin_for(meta, layer):
    names = list(meta["layers"])
    i = names.index(layer)
    return meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None


def strategy_digest(result) -> dict:
    """The placement, flattened, for comparing two schedules by shape alone."""
    s = result["strategy"]
    return {
        "node_temporal": [(f["dim"], f["size"]) for f in s["NodeLevel"]["temporal_tile"]["factors"]],
        "node_spatial": [(f["dim"], f["size"]) for f in s["NodeLevel"]["spatial_split"]["factors"]],
        "noc_temporal": s["NoCLevel"]["temporal_permutation"]["order"],
        "noc_spatial": s["NoCLevel"]["spatial_splitting"]["order"],
        "dram_temporal": s["DRAM"]["temporal_permutation"]["order"],
    }


# --- A: num_pes ------------------------------------------------------------
def run_num_pes(staged) -> list:
    rows = []
    for pes in PES:
        for trace_dir, layer in LAYERS:
            meta = staged["metas"][trace_dir]
            t0 = time.time()
            try:
                art = tracegen.solve_and_cache_schedule(
                    "loas", str(staged["arch_pes"][pes]),
                    str(IN / "dataflow" / BASE_DATAFLOW.name),
                    trace_dir, layer, meta, next_cin_for(meta, layer),
                    OUT / "schedules" / f"pe{pes}")
            except Exception as exc:
                print(f"  pe={pes:<4d} {layer:26s}  REJECTED  {exc}", flush=True)
                rows.append({"num_pes": pes, "trace_dir": trace_dir, "layer": layer,
                             "status": "REJECTED", "error": str(exc)})
                continue
            r = art.result
            rows.append({"num_pes": pes, "trace_dir": trace_dir, "layer": layer,
                         "status": r["status"], "objective": r["objective"],
                         "delay": r["metrics"]["delay"],
                         "dram_num_steps": art.dram_num_steps, "mode": art.mode,
                         "solve_seconds": round(time.time() - t0, 2)})
            print(f"  pe={pes:<4d} {layer:26s}  {r['status']:8s} obj={r['objective']:.6f} "
                  f"steps={art.dram_num_steps} mode={art.mode}", flush=True)
    return rows


# --- B: every TrafficMode --------------------------------------------------
def run_all_modes(staged) -> list:
    """Solve each layer under all 13 TrafficModes and record every outcome,
    including the ones solve_best_schedule discards, so the enumeration is
    visible rather than asserted."""
    rows = []
    arch = str(staged["arch_pes"][CANONICAL_PES])
    dataflow = str(IN / "dataflow" / BASE_DATAFLOW.name)
    for trace_dir, layer in LAYERS:
        layer_yaml = str(staged["workloads"][(trace_dir, layer)][0])
        for mode in TrafficMode:
            t0 = time.time()
            res = solve_schedule(layer_yaml, arch, dataflow,
                                 traffic_mode=mode, return_metrics=True)
            feasible = bool(res.get("has_solution") and res.get("metrics"))
            row = {"trace_dir": trace_dir, "layer": layer, "mode": mode.value,
                   "status": res.get("status"), "feasible": feasible,
                   "solve_seconds": round(time.time() - t0, 2)}
            if feasible:
                row.update(objective=res["objective"],
                           delay=res["metrics"]["delay"],
                           mode_score=_mode_score(res["metrics"]),
                           strategy=strategy_digest(res))
            rows.append(row)
            print(f"  {layer:26s} {mode.value:16s} "
                  f"{'feasible' if feasible else res.get('status'):12s} "
                  f"score={row.get('mode_score', float('nan')):.6g}", flush=True)
        feas = [r for r in rows if r["layer"] == layer and r["feasible"]]
        win = min(feas, key=lambda r: r["mode_score"])
        win["winner"] = True
        print(f"  -> {layer}: {len(feas)}/{len(list(TrafficMode))} feasible, "
              f"winner {win['mode']}\n", flush=True)
    return rows


# --- C: NoCLevel global-buffer size ---------------------------------------
def run_noc_sizes(staged) -> list:
    rows = []
    for trace_dir, layer in LAYERS:
        ref = None
        for tot in sorted(NOC_TOTALS, key=lambda t: (t != CANONICAL_NOC, -t)):
            meta = staged["metas"][trace_dir]
            try:
                art = tracegen.solve_and_cache_schedule(
                    "loas", str(staged["arch_noc"][tot]),
                    str(IN / "dataflow" / BASE_DATAFLOW.name),
                    trace_dir, layer, meta, next_cin_for(meta, layer),
                    OUT / "schedules_noc" / kb(tot))
            except Exception as exc:
                print(f"  noc={kb(tot):>6s} {layer:26s}  INFEASIBLE", flush=True)
                rows.append({"trace_dir": trace_dir, "layer": layer,
                             "noc_total_bytes": tot, "noc_total": kb(tot),
                             "entries": split_30_1_1(tot), "feasible": False,
                             "error": str(exc)})
                continue
            r = art.result
            dig = strategy_digest(r)
            if ref is None:
                ref = dig
            rows.append({"trace_dir": trace_dir, "layer": layer,
                         "noc_total_bytes": tot, "noc_total": kb(tot),
                         "entries": split_30_1_1(tot), "feasible": True,
                         "status": r["status"], "objective": r["objective"],
                         "delay": r["metrics"]["delay"],
                         "dram_num_steps": art.dram_num_steps, "mode": art.mode,
                         "util": r["metrics"]["util"], "strategy": dig,
                         f"same_as_{kb(CANONICAL_NOC)}": dig == ref})
            print(f"  noc={kb(tot):>6s} {layer:26s}  obj={r['objective']:.6f} "
                  f"steps={art.dram_num_steps} mode={art.mode:9s} "
                  f"util_w={int(r['metrics']['util']['weight'])} "
                  f"{'same' if dig == ref else 'CHANGED'}", flush=True)
        print(flush=True)
    return rows


def main() -> int:
    staged = stage_inputs()

    print("=== A. num_pes sweep ===", flush=True)
    pes_rows = run_num_pes(staged)

    def load(pes, t, l):
        d = json.loads((OUT / "schedules" / f"pe{pes}" / "loas" / t / f"{l}.json").read_text())
        d["result"]["configs"]["arch"] = "<blanked>"
        return d

    diff = []
    for trace_dir, layer in LAYERS:
        ref = load(CANONICAL_PES, trace_dir, layer)
        for pes in PES:
            if pes == CANONICAL_PES or not (OUT / "schedules" / f"pe{pes}").exists():
                continue
            same = load(pes, trace_dir, layer) == ref
            diff.append({"layer": f"{trace_dir}/{layer}", "num_pes": pes,
                         "vs_num_pes": CANONICAL_PES,
                         "verdict": "IDENTICAL" if same else "DIFFERS"})
    print("\n  invariance vs pe%d:" % CANONICAL_PES)
    for d in diff:
        print(f"    pe={d['num_pes']:<4d} {d['layer']:42s} {d['verdict']}")

    print("\n=== B. all TrafficModes ===", flush=True)
    mode_rows = run_all_modes(staged)

    print("=== C. NoCLevel global-buffer size ===", flush=True)
    noc_rows = run_noc_sizes(staged)

    (OUT / "solve_rows.json").write_text(json.dumps(pes_rows, indent=1) + "\n")
    (OUT / "num_pes_invariance.json").write_text(json.dumps(diff, indent=1) + "\n")
    (OUT / "mode_sweep.json").write_text(json.dumps(mode_rows, indent=1) + "\n")
    (OUT / "noc_size_sweep.json").write_text(json.dumps(noc_rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
