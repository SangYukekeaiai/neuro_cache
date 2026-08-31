#!/usr/bin/env python3
"""Increment 4 of log/2026-08-24-nocsim-per-tile-cycles-plan.md.

Arm S (single-node loas) Stage 1 and Stage 2, so Stage 3 can be run on both
arms from the same four layers and the same five samples.

Arm M's copies already exist under stage1_mip_solver/ and stage2_weight_trace/.
This produces arm S's, and only arm S's:

  Stage 1  configs/arch/loas.yaml + configs/dataflow/loas.yaml, solved under
           the `_n5` trace_dir names so StepCycles.check_against passes
           against the trace generated from them.
  Stage 2  the same generator arm M used, pointed at those schedules.

    conda run -n base python profiling/0823_stagewise_verify/stage3_nocsim/run_armS_stage12.py [--stage1-only]
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[2]
IN, OUT = STAGE / "inputs", STAGE / "outputs"

sys.path.insert(0, str(ROOT / "src"))
import tracegen  # noqa: E402

ARCH = "loas"
ARCH_YAML = ROOT / "configs/arch/loas.yaml"
DATAFLOW_YAML = ROOT / "configs/dataflow/loas.yaml"
TRACE_ROOT = ROOT / "input_trace/loas"
GENERATOR = ROOT / "scripts/generate_weight_traces.py"
COMBO_TAG = "single_node"

# (trace_dir, layer). The same four layers Stage 1 and Stage 2 used for arm M.
COMBOS = [
    ("vgg16_T4_n5", "layer_08_features_27"),
    ("resnet19_T4_n5", "layer_09_layer2_0_conv2"),
    ("vgg16_T4_n5", "layer_09_features_30"),
    ("resnet19_T4_n5", "layer_16_layer3_0_conv2"),
]
SAMPLE_START, SAMPLE_COUNT = 0, 5

SCHED_DIR = IN / "schedules_single_node"
TRACE_OUT = OUT / "weight_traces_single_node"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def next_cin_for(meta, layer):
    names = list(meta["layers"])
    i = names.index(layer)
    return meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None


def stage1() -> dict:
    metas = {t: json.loads((TRACE_ROOT / t / "meta.json").read_text())
             for t in sorted({t for t, _ in COMBOS})}
    rows = {}
    print("=== arm S Stage 1: single-node solves ===", flush=True)
    print(f"  arch     {ARCH_YAML.relative_to(ROOT)}  (sha {sha(ARCH_YAML)})", flush=True)
    print(f"  dataflow {DATAFLOW_YAML.relative_to(ROOT)}  (sha {sha(DATAFLOW_YAML)})", flush=True)
    for trace_dir, layer in COMBOS:
        meta = metas[trace_dir]
        t0 = time.time()
        art = tracegen.solve_and_cache_schedule(
            ARCH, str(ARCH_YAML), str(DATAFLOW_YAML),
            trace_dir, layer, meta, next_cin_for(meta, layer), SCHED_DIR)
        p = SCHED_DIR / ARCH / trace_dir / f"{layer}.json"
        prob = art.workload["problem"]
        rows[f"{trace_dir}/{layer}"] = {
            "path": str(p.relative_to(STAGE)),
            "problem": prob,
            "dram_num_steps": art.dram_num_steps,
            "mode": art.mode,
            "objective": art.result["objective"],
            "solve_seconds": round(time.time() - t0, 2),
            "sha256_16": sha(p),
        }
        print(f"  {trace_dir:16s} {layer:26s} steps={art.dram_num_steps:>5} "
              f"mode={art.mode:9s} obj={art.result['objective']:.6f} "
              f"({time.time() - t0:.1f}s)", flush=True)
    return rows


def stage2(sched_rows: dict) -> dict:
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    rows = {}
    print("\n=== arm S Stage 2: weight traces ===", flush=True)
    for trace_dir, layer in COMBOS:
        cmd = [sys.executable, str(GENERATOR),
               "--arch", ARCH,
               "--trace-root", str(TRACE_ROOT),
               "--trace-dir", trace_dir,
               "--layer", layer,
               "--schedule-cache", str(SCHED_DIR),
               "--out-dir", str(TRACE_OUT),
               "--combo-tag", COMBO_TAG,
               "--sample-start", str(SAMPLE_START),
               "--sample-count", str(SAMPLE_COUNT),
               "--workers", "1"]
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        t0 = time.time()
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        dt = time.time() - t0
        (OUT / "logs" / f"armS_{trace_dir}_{layer}.log").write_text(
            "$ " + " ".join(cmd) + "\n\n--- stdout ---\n" + r.stdout +
            "\n--- stderr ---\n" + (r.stderr or ""))
        if r.returncode != 0:
            raise RuntimeError(f"{trace_dir}/{layer} rc={r.returncode}\n{r.stderr[-2000:]}")
        d = TRACE_OUT / ARCH / COMBO_TAG / trace_dir / layer
        files = sorted(d.glob("sample_*.json.gz"))
        total = sum(f.stat().st_size for f in files)
        rows[f"{trace_dir}/{layer}"] = {
            "dir": str(d.relative_to(STAGE)),
            "samples": len(files),
            "bytes_total": total,
            "seconds": round(dt, 1),
        }
        print(f"  {trace_dir:16s} {layer:26s} {len(files)} samples, "
              f"{total / 1e6:.1f} MB, {dt:.0f}s", flush=True)
    return rows


def main() -> int:
    IN.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    sched_rows = stage1()
    manifest = {
        "stage": "3_nocsim / arm S inputs",
        "arm": "S (single_node)",
        "arch_yaml": {"path": str(ARCH_YAML.relative_to(ROOT)), "sha256_16": sha(ARCH_YAML)},
        "dataflow_yaml": {"path": str(DATAFLOW_YAML.relative_to(ROOT)), "sha256_16": sha(DATAFLOW_YAML)},
        "input_trace_root": str(TRACE_ROOT),
        "samples": {"start": SAMPLE_START, "count": SAMPLE_COUNT},
        "schedules": sched_rows,
    }
    if "--stage1-only" not in sys.argv:
        manifest["weight_traces"] = stage2(sched_rows)
    (IN / "MANIFEST_armS.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print("\nwrote", IN / "MANIFEST_armS.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
