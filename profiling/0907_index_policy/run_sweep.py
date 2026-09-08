#!/usr/bin/env python3
"""Replacement policy at L1 and L2, all 31 layers, against the nocsim makespan.

One grid over `policy` alone. Everything except `policy` is the 0903_l1_8k
`off_16k` BASE, so the `lru` arm must reproduce that stage's row -- it is the
control, not a fifth result. `l2_policy` stays unset so both levels follow
`policy`. `belady` is the offline bound.

Usage: conda run -n base python run_sweep.py [workers]
"""
from __future__ import annotations

import csv, json, math, pathlib, statistics, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402

BIN     = ROOT / "src/wcache/native/build/release/wcache_sweep"
STREAMS = ROOT / "profiling/0831_all_layer_streams/streams"
NOCSIM  = ROOT / "profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv"
OUT     = STAGE / "outputs"
N_SAMPLES = 5

BASE = {"layout": "khkw_split", "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
        "l1_size_bytes": 16384, "l1_assoc": 8,
        "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32, "l2_banks": 1,
        "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
        "prefetch_policy": "none", "prefetch_distance": 0,
        "l2_prefetch_policy": "none"}

ARMS = ["lru", "rrip", "lfu", "belady"]
GRID = [dict(BASE, policy=p) for p in ARMS]

STALL_COLS = ["stall_total", "stall_l1_slot", "stall_l1_line", "stall_l1_port",
              "stall_l2_slot", "stall_l2_line", "stall_l2_port", "stall_channel"]
RATE_COLS  = ["l1_hit_rate", "l2_hit_rate", "l1_accesses", "l2_accesses",
              "dram_accesses", "dram_bytes", "l1_evictions"]


def tags():
    out = []
    for prefix, tdir in [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]:
        meta = json.loads((ROOT / "input_trace/loas" / tdir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            out.append((f"{prefix}{int(layer.split('_')[1])}", layer))
    return out


def one(args):
    tag, layer, s, grid_path, commit = args
    r = subprocess.run(
        [str(BIN), "--config-grid", str(grid_path),
         "--trace", str(STREAMS / f"{tag}_s{s:05d}.wcts"),
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
    base = {t: statistics.mean(float(r["total_cycles"]) for r in rs)
            for (t, a), rs in g.items() if a == "lru"}

    by_layer = []
    for tag, _ in tags():
        for arm in ARMS:
            rs = g.get((tag, arm))
            if not rs:
                continue
            m = lambda c: statistics.mean(float(r[c]) for r in rs)
            cyc = [float(r["total_cycles"]) for r in rs]
            mc  = statistics.mean(cyc)
            nr  = noc.get(tag)
            row = {"tag": tag, "layer": rs[0]["layer"], "workload": rs[0]["workload"],
                   "arm": arm, "policy": rs[0]["policy"], "samples": len(rs),
                   "cycles": round(mc, 1),
                   "cycles_spread": round((max(cyc) - min(cyc)) / mc, 4),
                   "speedup_vs_lru": round(base[tag] / mc, 4),
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

    jobs = [(t, l, s, grid_path, commit) for t, l in tags() for s in range(N_SAMPLES)]
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
