#!/usr/bin/env python3
"""wcache at the best config against nocsim, over all 31 layers x 5 samples.

Three phases, each resumable because each writes its own file and skips what is
already there:

  W  155 wcache_sweep runs, one config point (the khkw_64b grid's winner), one
     WCTS stream each             ->  outputs/wcache_rows.csv
  N  155 nocsim runs, one saved weight-trace sample each
                                  ->  outputs/nocsim_rows.json
  J  the join, one row per layer, each the mean over its 5 samples
                                  ->  outputs/all_layers_vs_nocsim.csv

The join's schema is the one `stage4_wcache/analyze_khkw_sweep.py` established,
so a row here reads the same way a row of `khkw_vs_stage3.csv` does. Its two
baselines are kept for the same reason that file gives: `total_cycles` says
whether a cache in front of the cores beats the network as it stands, and
`compute_per_node` says how far the config is from the floor no memory system
can go under.

Samples are 5 draws of one layer under one schedule, so their spread belongs to
the input trace rather than to the cache; it is carried as a column rather than
averaged away.

    conda run -n base python profiling/0831_all_layer_streams/run_compare.py --workers 16
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402

OUT = STAGE / "outputs"
WCACHE_BIN = ROOT / "src/wcache/native/build/release/wcache_sweep"
NOCSIM_ARCH = ROOT / "profiling/0823_stagewise_verify/stage3_nocsim/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml"
SCHEDULES = STAGE / "schedules"
STREAMS = STAGE / "streams"
TRACES = STAGE / "weight_traces/loas/noc2MiB_node32kb"
LAYER_YAMLS = STAGE / "layers"
TC_DIR = STAGE / "tc"                      # nocsim transaction lists
N_NODES = 16
N_SAMPLES = 5
WORKLOADS = [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]

# The khkw_64b grid's winning point, verbatim from
# stage4_wcache/outputs/_khkw_grid/khkw_64b.json[0]. Line size is derived:
# cin_block * cout_block * weight_bytes = 16 * 4 * 1 = 64 B.
BEST = {
    "layout": "khkw_split", "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
    "l1_size_bytes": 16384, "l1_assoc": 8,
    "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32, "l2_banks": 1,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "prefetch_policy": "none", "prefetch_distance": 0,
}


def combos() -> list:
    """(tag, trace_dir, layer) for every valid layer of both workloads."""
    out = []
    for prefix, trace_dir in WORKLOADS:
        meta = json.loads((ROOT / "input_trace/loas" / trace_dir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            out.append((f"{prefix}{int(layer.split('_')[1])}", trace_dir, layer))
    return out


def layer_yaml(tag: str, trace_dir: str, layer: str) -> pathlib.Path:
    """The layer shape, taken from the schedule's own workload block so the two
    cannot drift apart. Same construction run_stage3.py uses."""
    p = LAYER_YAMLS / f"{tag}.yaml"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        d = json.loads((SCHEDULES / "loas" / trace_dir / f"{layer}.json").read_text())
        p.write_text(yaml.safe_dump(d["workload"], sort_keys=False))
    return p


# --- phase W: wcache -------------------------------------------------------

def run_wcache_one(args) -> list:
    tag, trace_dir, layer, sample, grid_path, commit = args
    r = subprocess.run(
        [str(WCACHE_BIN), "--config-grid", str(grid_path),
         "--trace", str(STREAMS / f"{tag}_s{sample:05d}.wcts"),
         "--arm", "cache", "--tier", "khkw",
         "--run-id", f"alllayer-{tag}-s{sample}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"wcache failed: {tag} s{sample}\n{r.stderr[-2000:]}")
    rows = list(csv.DictReader(r.stdout.splitlines()))
    for d in rows:
        d["_tag"], d["_sample"] = tag, str(sample)
    return rows


def phase_wcache(workers: int) -> pathlib.Path:
    dst = OUT / "wcache_rows.csv"
    if dst.exists():
        print(f"W: have {dst}, skipping")
        return dst
    grid_path = OUT / "_best_config.json"
    grid_path.write_text(json.dumps([BEST], indent=1) + "\n")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    jobs = [(t, d, l, s, grid_path, commit) for t, d, l in combos() for s in range(N_SAMPLES)]
    print(f"=== W: {len(jobs)} wcache runs, {workers} workers ===", flush=True)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_wcache_one, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            j = futures[f]
            try:
                got = f.result()
            except Exception as exc:
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[3]}: FAILED ({exc!r})", flush=True)
                continue
            rows.extend(got)
            if i % 25 == 0 or i == len(jobs):
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[3]}", flush=True)
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"W: {len(rows)} rows in {time.time() - t0:.1f}s -> {dst}")
    return dst


# --- phase N: nocsim -------------------------------------------------------

def run_nocsim_one(args) -> dict:
    tag, trace_dir, layer, sample = args
    TC_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "nocsim.sim",
           "--schedule", str(SCHEDULES / "loas" / trace_dir / f"{layer}.json"),
           "--layer", str(layer_yaml(tag, trace_dir, layer)),
           "--arch", str(NOCSIM_ARCH),
           "--weight-trace", str(TRACES / trace_dir / layer / f"sample_{sample:05d}.json.gz"),
           "--out", str(TC_DIR / f"{tag}_s{sample:05d}.csv"),
           "--simulate"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"nocsim failed: {tag} s{sample} rc={r.returncode}\n{r.stderr[-2000:]}")
    got = {}
    for line in r.stdout.splitlines():
        for key in ("total_cycles", "unicast_cycles", "multicast_cycles",
                    "count_cycles", "dram_cycles"):
            if line.startswith(key):
                got[key] = int(line.split(":")[1].strip())
    missing = {"total_cycles", "count_cycles", "dram_cycles"} - set(got)
    if missing:
        raise RuntimeError(f"{tag} s{sample}: eventsim printed no {sorted(missing)}\n{r.stdout}")
    # count_cycles sums every node's COUNT, so per-node compute -- the quantity
    # that competes with DRAM and the NoC on the critical path -- is that / 16.
    got["compute_per_node"] = got["count_cycles"] // N_NODES
    got.update(tag=tag, trace_dir=trace_dir, layer=layer, sample=sample,
               seconds=round(time.time() - t0, 1))
    return got


def phase_nocsim(workers: int) -> pathlib.Path:
    dst = OUT / "nocsim_rows.json"
    if dst.exists():
        print(f"N: have {dst}, skipping")
        return dst
    jobs = [(t, d, l, s) for t, d, l in combos() for s in range(N_SAMPLES)]
    print(f"=== N: {len(jobs)} nocsim runs, {workers} workers ===", flush=True)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_nocsim_one, j): j for j in jobs}
        for i, f in enumerate(as_completed(futures), 1):
            j = futures[f]
            try:
                rows.append(f.result())
            except Exception as exc:
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[3]}: FAILED ({exc!r})", flush=True)
                continue
            if i % 25 == 0 or i == len(jobs):
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[3]}", flush=True)
    dst.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"N: {len(rows)} rows in {time.time() - t0:.1f}s -> {dst}")
    return dst


# --- phase J: the join -----------------------------------------------------

def phase_join() -> pathlib.Path:
    wrows = list(csv.DictReader(open(OUT / "wcache_rows.csv")))
    nrows = json.loads((OUT / "nocsim_rows.json").read_text())
    dst = OUT / "all_layers_vs_nocsim.csv"

    base_total, base_compute = {}, {}
    for tag in {r["tag"] for r in nrows}:
        rs = [r for r in nrows if r["tag"] == tag]
        base_total[tag] = statistics.mean(r["total_cycles"] for r in rs)
        base_compute[tag] = statistics.mean(r["compute_per_node"] for r in rs)

    groups = {}
    for r in wrows:
        groups.setdefault(r["_tag"], []).append(r)

    order = [t for t, _, _ in combos()]
    out = []
    for tag in order:
        rs = groups.get(tag)
        if not rs or tag not in base_total:
            print(f"  {tag}: missing one side, skipped")
            continue
        n = lambda c: [float(r[c]) for r in rs]
        cyc = n("total_cycles")
        mean_cyc = statistics.mean(cyc)
        out.append({
            "tag": tag,
            "layer": rs[0]["layer"],
            "workload": rs[0]["workload"],
            "line_size_bytes": int(rs[0]["line_size_bytes"]),
            "l2_banks": int(rs[0]["l2_banks"]),
            "prefetch_distance": int(rs[0]["prefetch_distance"]),
            "samples": len(rs),
            "wcache_cycles": round(mean_cyc, 1),
            "wcache_cycles_spread": round((max(cyc) - min(cyc)) / mean_cyc, 4),
            "nocsim_total_cycles": round(base_total[tag], 1),
            "nocsim_compute_per_node": round(base_compute[tag], 1),
            "speedup_vs_nocsim_total": round(base_total[tag] / mean_cyc, 4),
            "cycles_over_compute_floor": round(mean_cyc / base_compute[tag], 4),
            "l1_hit_rate": round(statistics.mean(n("l1_hit_rate")), 6),
            "l2_hit_rate": round(statistics.mean(n("l2_hit_rate")), 6),
            "l1_accesses": round(statistics.mean(n("l1_accesses")), 1),
            "l2_accesses": round(statistics.mean(n("l2_accesses")), 1),
            "dram_accesses": round(statistics.mean(n("dram_accesses")), 1),
            "dram_bytes": round(statistics.mean(n("dram_bytes")), 1),
            "stall_total": round(statistics.mean(n("stall_total")), 1),
            "hidden_fraction": round(statistics.mean(n("hidden_fraction")), 4),
            "padding_fraction": round(statistics.mean(n("padding_fraction")), 4),
        })

    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(f"\n{'tag':>4} {'wcache':>10} {'nocsim':>10} {'speedup':>8} "
          f"{'/floor':>7} {'L1 hit':>8} {'L2 hit':>8}")
    for r in out:
        print(f"{r['tag']:>4} {r['wcache_cycles']:>10.0f} {r['nocsim_total_cycles']:>10.0f} "
              f"{r['speedup_vs_nocsim_total']:>8.3f} {r['cycles_over_compute_floor']:>7.2f} "
              f"{r['l1_hit_rate']:>8.4f} {r['l2_hit_rate']:>8.4f}")
    print(f"\nJ: {len(out)} layers -> {dst}")
    return dst


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--phase", choices=["w", "n", "j", "all"], default="all")
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase in ("w", "all"):
        phase_wcache(args.workers)
    if args.phase in ("n", "all"):
        phase_nocsim(args.workers)
    if args.phase in ("j", "all"):
        phase_join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
