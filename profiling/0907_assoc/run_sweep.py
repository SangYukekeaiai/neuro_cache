#!/usr/bin/env python3
"""L1 associativity: 32-way, 16-way and fully associative, under LRU and RRIP,
at both L1 sizes.

A grid over `l1_assoc` x `policy` x `l1_size_bytes`: {32, 16, fa} x {lru, rrip} x
{16 KB, 8 KB}, twelve points. Everything else is the 0903_l1_8k BASE, the same
one the 0907_index_policy stage uses, so the two stages are comparable row for
row.

WHAT THIS IS TESTING. Capacity is fixed, so halving the ways doubles the sets
and adds one index bit. Under `khkw_split` the index is the low bits of the line
id, which is `[cin_blk][pos_lo]` from the bottom, so the set count decides which
of those two digits the index can still see:

    16 KB, 32-way ->   8 sets, 3 index bits -> pos_lo alone
    16 KB, 16-way ->  16 sets, 4 index bits -> [cin_blk % 2][pos_lo]
     8 KB, 32-way ->   4 sets, 2 index bits -> pos_lo[1:0]
     8 KB, 16-way ->   8 sets, 3 index bits -> pos_lo alone

The prediction this stage exists to confirm or refute, taken from the traces
themselves (see EXPLAIN.md):

  * At 16 KB the two are the SAME machine on the large layers. Both reach 192 of
    the 256 lines a core can use in a tile and both leave 4.2% of sets over their
    ways, because the ways lost are exactly the sets gained.
  * At 8 KB, 32-way is BETTER. With 3 index bits the index is pos_lo alone, and a
    tile fires only 4 to 9 of the 9 kernel positions, so it reaches 6 of 8 sets
    and strands a quarter of the array. With 2 bits it reaches all 4 sets and the
    whole array is usable.
  * RRIP tracks LRU at every point, since 0907_index_policy measured them
    identical on all 31 layers at 8-way.

Usage: conda run -n ${CONDA_ENV:-cosa_snn} python run_sweep.py [workers]
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

BASE = base_config(drop=("l1_size_bytes", "l1_assoc"))

L1_SIZES = [16384, 8192]
POLICIES = ["lru", "rrip"]
LINE_B   = 64   # cin_block 16 x cout_block 4 x weight_bytes 1

# Fully associative is ONE set, so its way count is the whole line count and
# therefore depends on the size: 256 ways at 16 KB, 128 at 8 KB. That is why the
# associativity list is built per size rather than being a constant, and why the
# arm is labelled `fa` instead of by a number that would mean a different
# geometry in each half of the grid.
def assocs_for(sz):
    return [32, 16, sz // LINE_B]

def arm_tag(w, sz):
    return "fa" if w == sz // LINE_B else f"{w}w"

# ARMS labels the grid in the SAME order, because `one` matches a CSV row to its
# arm by index. Size outermost, then associativity, so the arms being compared
# stay adjacent in every output.
GRID = [dict(BASE, l1_size_bytes=sz, l1_assoc=w, policy=p)
        for sz in L1_SIZES for w in assocs_for(sz) for p in POLICIES]
ARMS = [f"{p}_{arm_tag(w, sz)}_{sz // 1024}k"
        for sz in L1_SIZES for w in assocs_for(sz) for p in POLICIES]

arm_size   = lambda a: a.rsplit("_", 1)[1]
arm_assoc  = lambda a: a.split("_")[1]
arm_policy = lambda a: a.split("_")[0]

STALL_COLS = ["stall_total", "stall_l1_slot", "stall_l1_line", "stall_l1_port",
              "stall_l2_slot", "stall_l2_line", "stall_l2_port", "stall_channel"]
RATE_COLS  = ["l1_hit_rate", "l2_hit_rate", "l1_accesses", "l2_accesses",
              "dram_accesses", "dram_bytes"]


def one(args):
    tag, layer, s, grid_path, commit = args
    stream = STREAMS / f"{tag}_s{s:05d}.wcts"
    r = subprocess.run(
        [str(BIN), "--config-grid", str(grid_path), "--trace", str(stream),
         "--arm", "cache", "--tier", "assoc",
         "--run-id", f"assoc-{tag}-s{s}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{s}: {r.stderr[-1500:]}")
    rows = list(csv.DictReader(r.stdout.splitlines()))
    if len(rows) != len(ARMS):
        raise RuntimeError(f"{tag} s{s}: got {len(rows)} rows, expected {len(ARMS)}")
    for i, d in enumerate(rows):
        d["_tag"], d["_sample"], d["_arm"], d["_layer"] = tag, str(s), ARMS[i], layer
    return rows


def aggregate(rows, avail):
    noc = {r["tag"]: r for r in csv.DictReader(open(NOCSIM))}
    g = {}
    for r in rows:
        g.setdefault((r["_tag"], r["_arm"]), []).append(r)
    # The control at each geometry is 16-way LRU, the configuration every earlier
    # stage ran, so `speedup_vs_16w` isolates the associativity change.
    base = {(t, arm_size(a)): statistics.mean(float(r["total_cycles"]) for r in rs)
            for (t, a), rs in g.items() if arm_assoc(a) == "16w" and arm_policy(a) == "lru"}

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
                   "l1_assoc": rs[0]["l1_assoc"], "l1_num_sets": rs[0]["l1_num_sets"],
                   "samples": len(rs), "cycles": round(mc, 1),
                   "cycles_spread": round((max(cyc) - min(cyc)) / mc, 4),
                   "speedup_vs_16w": round(base[(tag, arm_size(arm))] / mc, 4),
                   "nocsim_total_cycles": round(float(nr["nocsim_total_cycles"]), 1) if nr else ""}
            for c in STALL_COLS + RATE_COLS:
                if c in avail:
                    row[c] = round(m(c), 4 if "rate" in c else 2)
            by_layer.append(row)
    return by_layer


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

    jobs = [(t, l, s, grid_path, commit) for t, _, l in tags() for s in range(N_SAMPLES)]
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

    write_csv(OUT / "assoc_rows.csv", rows)
    by_layer = aggregate(rows, set(rows[0]))
    write_csv(OUT / "assoc_by_layer.csv", by_layer)

    # The one line a driver reads: accumulated cycles per arm, per workload.
    print()
    for arm in ARMS:
        rs = [r for r in by_layer if r["arm"] == arm]
        v = sum(r["cycles"] for r in rs if r["tag"][0] == "V")
        r_ = sum(r["cycles"] for r in rs if r["tag"][0] == "R")
        print(f"  {arm:16} sets={rs[0]['l1_num_sets']:>4}  vgg16 {v:>12,.0f}  "
              f"resnet19 {r_:>12,.0f}  total {v + r_:>12,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
