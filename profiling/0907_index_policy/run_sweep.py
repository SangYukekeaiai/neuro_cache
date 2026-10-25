#!/usr/bin/env python3
"""Replacement policy at L1 and L2, all 31 layers, against the nocsim makespan.

A grid over `policy` x `l1_size_bytes`: {lru, rrip, lfu} x {16 KB, 8 KB}, six
points. Everything else is the 0903_l1_8k BASE, which makes that stage the
control for both geometries: `lru_16k` must reproduce its `off_16k` row and
`lru_8k` its `off_8k` row. `l2_policy` stays unset so both levels follow
`policy`, and each policy is scored against lru AT ITS OWN SIZE so the number
measures the policy rather than the capacity.

ONE PASS PER STREAM. Every arm here is an ONLINE policy, so the sweep reads each
stream once and needs nothing from a prior run.

`belady` is deliberately NOT an arm, and its absence is what keeps that true. It
is built and correct at both levels, but it is offline: it needs a prior
wcache_run over each stream to write a 113 MB access log for the oracle to read,
which doubles the work of every job and puts a scratch file beside it. The bound
belongs in a stage of its own, run once the three online policies have been
compared and it is clear how much room is left to bound.

Usage: conda run -n base python run_sweep.py [workers]
"""
from __future__ import annotations

import csv, json, math, pathlib, statistics, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "profiling"))
from common import base_config, tags  # noqa: E402

BIN     = ROOT / "src/wcache/native/build/release/wcache_sweep"
STREAMS = ROOT / "profiling/0831_all_layer_streams/streams"
NOCSIM  = ROOT / "profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv"
OUT     = STAGE / "outputs"
N_SAMPLES = 5

BASE = base_config()

POLICIES = ["lru", "rrip", "lfu"]
L1_SIZES = [16384, 8192]

# The grid is the product, and ARMS is its labelling in the SAME order, because
# `one` matches a CSV row to its arm by index. Size is the outer loop so that
# the three policies of one geometry stay adjacent in every output.
GRID = [dict(BASE, policy=p, l1_size_bytes=sz) for sz in L1_SIZES for p in POLICIES]
ARMS = [f"{p}_{sz // 1024}k" for sz in L1_SIZES for p in POLICIES]

# The control for a given point is lru AT ITS OWN SIZE, so `speedup_vs_lru`
# measures the policy and not the geometry. Comparing an 8 KB arm against the
# 16 KB lru would fold the capacity loss the 0903_l1_8k stage already measured
# into every 8 KB number here.
def arm_size(arm):    return arm.rsplit("_", 1)[1]
def arm_policy(arm):  return arm.rsplit("_", 1)[0]

STALL_COLS = ["stall_total", "stall_l1_slot", "stall_l1_line", "stall_l1_port",
              "stall_l2_slot", "stall_l2_line", "stall_l2_port", "stall_channel"]
RATE_COLS  = ["l1_hit_rate", "l2_hit_rate", "l1_accesses", "l2_accesses",
              "dram_accesses", "dram_bytes", "l1_evictions"]


def one(args):
    tag, layer, s, grid_path, commit = args
    stream = STREAMS / f"{tag}_s{s:05d}.wcts"
    r = subprocess.run(
        [str(BIN), "--config-grid", str(grid_path), "--trace", str(stream),
         "--arm", "cache", "--tier", "policy",
         "--run-id", f"policy-{tag}-s{s}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{s}: {r.stderr[-1500:]}")
    rows = list(csv.DictReader(r.stdout.splitlines()))
    if len(rows) != len(ARMS):
        raise RuntimeError(f"{tag} s{s}: got {len(rows)} rows, expected {len(ARMS)}")
    for i, d in enumerate(rows):
        d["_tag"], d["_sample"], d["_arm"], d["_layer"] = tag, str(s), ARMS[i], layer
    return rows


def geomean(xs):
    xs = [x for x in xs if x > 0]
    return math.exp(sum(map(math.log, xs)) / len(xs)) if xs else float("nan")


def aggregate(rows, avail):
    noc = {r["tag"]: r for r in csv.DictReader(open(NOCSIM))}
    g = {}
    for r in rows:
        g.setdefault((r["_tag"], r["_arm"]), []).append(r)
    base = {(t, arm_size(a)): statistics.mean(float(r["total_cycles"]) for r in rs)
            for (t, a), rs in g.items() if arm_policy(a) == "lru"}

    by_layer = []
    for tag, _, _ in tags():
        for arm in ARMS:
            rs = g.get((tag, arm))
            if not rs:
                continue
            m = lambda c: statistics.mean(float(r[c]) for r in rs)
            cyc = [float(r["total_cycles"]) for r in rs]
            mc  = statistics.mean(cyc)
            nr  = noc.get(tag)
            row = {"tag": tag, "layer": rs[0]["layer"], "workload": rs[0]["workload"],
                   "arm": arm, "policy": rs[0]["policy"],
                   "l1_size_bytes": rs[0]["l1_size_bytes"],
                   "l1_num_sets": rs[0]["l1_num_sets"], "samples": len(rs),
                   "cycles": round(mc, 1),
                   "cycles_spread": round((max(cyc) - min(cyc)) / mc, 4),
                   "speedup_vs_lru": round(base[(tag, arm_size(arm))] / mc, 4),
                   "nocsim_total_cycles": round(float(nr["nocsim_total_cycles"]), 1) if nr else "",
                   "nocsim_compute_per_node": round(float(nr["nocsim_compute_per_node"]), 1) if nr else "",
                   "speedup_vs_nocsim_total":
                       round(float(nr["nocsim_total_cycles"]) / mc, 4) if nr else "",
                   "cycles_over_compute_floor":
                       round(mc / float(nr["nocsim_compute_per_node"]), 4) if nr else ""}
            for c in STALL_COLS + RATE_COLS:
                if c in avail:
                    row[c] = round(m(c), 4 if "rate" in c else 2)
            by_layer.append(row)

    agg = []
    for arm in ARMS:
        rs = [r for r in by_layer if r["arm"] == arm]
        a = {"arm": arm, "layers": len(rs),
             "total_makespan": round(sum(r["cycles"] for r in rs), 1),
             "total_nocsim": round(sum(float(r["nocsim_total_cycles"]) for r in rs), 1),
             "geomean_speedup_vs_lru": round(geomean([r["speedup_vs_lru"] for r in rs]), 4),
             "geomean_speedup_vs_nocsim_total":
                 round(geomean([r["speedup_vs_nocsim_total"] for r in rs]), 4),
             "geomean_cycles_over_compute_floor":
                 round(geomean([r["cycles_over_compute_floor"] for r in rs]), 4),
             "layers_beating_nocsim": sum(1 for r in rs if r["speedup_vs_nocsim_total"] > 1.0)}
        for c in STALL_COLS + ["l1_accesses", "l2_accesses", "dram_accesses", "l1_evictions"]:
            if c in avail:
                a[c] = round(sum(r[c] for r in rs), 1)
        for c in ["l1_hit_rate", "l2_hit_rate"]:
            if c in avail:
                a[c] = round(statistics.mean(r[c] for r in rs), 6)
        agg.append(a)
    return by_layer, agg


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} rows -> {path}")


def main() -> int:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    OUT.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    grid_path = OUT / "_grid.json"
    grid_path.write_text(json.dumps(GRID, indent=1) + "\n")

    jobs = [(t, l, s, grid_path, commit)
            for t, _, l in tags() for s in range(N_SAMPLES)]
    print(f"=== {len(jobs)} streams x {len(GRID)} configs, {workers} workers ===", flush=True)
    rows, fails, t0 = [], 0, time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            j = futs[f]
            try:
                rows.extend(f.result())
            except Exception as exc:
                fails += 1
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[2]}: FAILED ({exc!r})", flush=True)
                continue
            if i % 50 == 0 or i == len(jobs):
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[2]}", flush=True)
    print(f"{len(rows)} rows, {fails} failures, {time.time()-t0:.1f}s", flush=True)
    if fails:
        return 1

    avail = set(rows[0])
    missing = [c for c in STALL_COLS + RATE_COLS if c not in avail]
    if missing:
        print(f"note: schema has no {missing}, dropped from the output", flush=True)

    write_csv(OUT / "policy_rows.csv", rows)
    by_layer, agg = aggregate(rows, avail)
    write_csv(OUT / "policy_by_layer.csv", by_layer)
    write_csv(OUT / "policy_aggregate.csv", agg)

    cols = list(agg[0])
    print("\n" + " ".join(f"{c:>26}" for c in cols))
    for a in agg:
        print(" ".join(f"{a[c]:>26}" for c in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
