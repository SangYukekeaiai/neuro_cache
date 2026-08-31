#!/usr/bin/env python3
"""Stage 3 of the 2026-08-23 stagewise verification: nocsim.

Arm M only (the 16-node arch). Replays each of the four layers' five
weight-trace samples through nocsim, charging every schedule step the
per-tile mac_cycles the trace recorded, and runs the compiled eventsim
backend over the resulting transaction list.

Everything read is listed in inputs/MANIFEST_stage3.json with its sha; every
number produced lands in outputs/stage3_results.json.

    conda run -n base python profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

import yaml

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[2]
IN, OUT = STAGE / "inputs", STAGE / "outputs"
STAGE2 = STAGE.parent / "stage2_weight_trace"

ARCH = "loas"
COMBO_TAG = "noc2MiB_node32kb"
# DRAM_LATENCY 0.25 = 64 GB/s at 500 MHz. Stage 1's copy is left at its
# recorded sha; this is the Stage 3 arch.
ARCH_YAML = IN / "arch" / "loas_inst16_node32kb_noc2MiB_pe16.yaml"
SCHEDULES = STAGE2 / "inputs" / "schedules" / ARCH
TRACES = STAGE2 / "outputs" / "weight_traces" / ARCH / COMBO_TAG

COMBOS = [
    ("V8", "vgg16_T4_n5", "layer_08_features_27"),
    ("R9", "resnet19_T4_n5", "layer_09_layer2_0_conv2"),
    ("V9", "vgg16_T4_n5", "layer_09_features_30"),
    ("R16", "resnet19_T4_n5", "layer_16_layer3_0_conv2"),
]
SAMPLES = range(5)
N_NODES = 16


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def layer_yaml(tag: str, sched: pathlib.Path) -> pathlib.Path:
    """The layer shape, taken from the schedule's own workload block so the
    two cannot drift apart."""
    d = json.loads(sched.read_text())
    p = IN / "layers" / f"{tag}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(d["workload"], sort_keys=False))
    return p


def run_one(tag, trace_dir, layer, sample, sched, lyaml, trace, csv_out, log_out):
    cmd = [sys.executable, "-m", "nocsim.sim",
           "--schedule", str(sched),
           "--layer", str(lyaml),
           "--arch", str(ARCH_YAML),
           "--weight-trace", str(trace),
           "--out", str(csv_out),
           "--simulate"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    dt = time.time() - t0
    log_out.write_text("$ " + " ".join(cmd) + "\n\n--- stdout ---\n" + r.stdout +
                       "\n--- stderr ---\n" + (r.stderr or ""))
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{sample} rc={r.returncode}\n{r.stderr[-2000:]}")

    got = {}
    for line in r.stdout.splitlines():
        for key in ("total_cycles", "unicast_cycles", "multicast_cycles",
                    "count_cycles", "dram_cycles"):
            if line.startswith(key):
                got[key] = int(line.split(":")[1].strip())
    missing = {"total_cycles", "count_cycles", "dram_cycles"} - set(got)
    if missing:
        raise RuntimeError(f"{tag} s{sample}: eventsim printed no {sorted(missing)}\n{r.stdout}")

    # count_cycles sums every node's COUNT, so the per-node compute time --
    # the quantity that actually competes with DRAM and NoC on the critical
    # path -- is that total divided by the node count.
    got["compute_per_node"] = got["count_cycles"] // N_NODES
    got["csv_bytes"] = csv_out.stat().st_size
    got["seconds"] = round(dt, 1)
    return got


def main() -> int:
    (OUT / "logs").mkdir(parents=True, exist_ok=True)
    (OUT / "tc").mkdir(parents=True, exist_ok=True)

    manifest = {
        "stage": "3_nocsim",
        "arm": "M (16 nodes)",
        "arch": {"path": str(ARCH_YAML.relative_to(STAGE)), "sha256_16": sha(ARCH_YAML),
                 "dram_latency": 0.25,
                 "note": "0.25 cycles of DRAM port occupancy per 256-bit packet "
                         "= 64 GB/s at 500 MHz"},
        "eventsim": {"binary": "src/nocsim/eventsim/eventsim",
                     "sha256_16": sha(ROOT / "src/nocsim/eventsim/eventsim")},
        "schedules": {}, "weight_traces": {},
    }

    rows = []
    print("=== Stage 3, arm M: 4 layers x 5 samples ===", flush=True)
    for tag, trace_dir, layer in COMBOS:
        sched = SCHEDULES / trace_dir / f"{layer}.json"
        lyaml = layer_yaml(tag, sched)
        d = json.loads(sched.read_text())
        manifest["schedules"][tag] = {
            "path": str(sched.relative_to(STAGE.parent)),
            "dram_num_steps": d["dram_num_steps"], "mode": d["mode"],
            "problem": d["workload"]["problem"], "sha256_16": sha(sched),
        }
        print(f"\n{tag}  {trace_dir}/{layer}  {d['dram_num_steps']} DRAM steps", flush=True)
        for s in SAMPLES:
            trace = TRACES / trace_dir / layer / f"sample_{s:05d}.json.gz"
            manifest["weight_traces"][f"{tag}/s{s}"] = {
                "path": str(trace.relative_to(STAGE.parent)), "sha256_16": sha(trace)}
            got = run_one(tag, trace_dir, layer, s, sched, lyaml, trace,
                          OUT / "tc" / f"{tag}_s{s:05d}.csv",
                          OUT / "logs" / f"{tag}_s{s:05d}.log")
            rows.append({"tag": tag, "trace_dir": trace_dir, "layer": layer,
                         "sample": s, **got})
            print(f"  s{s}  total={got['total_cycles']:>10,}  "
                  f"dram={got['dram_cycles']:>8,}  "
                  f"unicast={got['unicast_cycles']:>9,}  "
                  f"compute/node={got['compute_per_node']:>9,}  "
                  f"({got['seconds']}s)", flush=True)

    (IN / "MANIFEST_stage3.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (OUT / "stage3_results.json").write_text(json.dumps(rows, indent=1) + "\n")
    print(f"\nwrote {OUT / 'stage3_results.json'} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
