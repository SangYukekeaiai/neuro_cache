#!/usr/bin/env python3
"""L1 line size: 64 B against 32 B against 16 B, at a FIXED set count, on RRIP.

The line is `cin_block x cout_block x weight_bytes`, and `cout_block` is held at
4 throughout, so the line size is set by `cin_block` alone:

    cin_block 16 x cout_block 4 x 1 byte = 64 B
    cin_block  8 x cout_block 4 x 1 byte = 32 B
    cin_block  4 x cout_block 4 x 1 byte = 16 B

Six points: those three line sizes at both L1 sizes, all RRIP with a 5-bit RRPV.

WAYS SCALE WITH THE LINE so the SET COUNT is identical in every arm: 32 ways at
64 B, 64 at 32 B, 128 at 16 B, giving 8 sets at 16 KB and 4 sets at 8 KB
throughout. This is what isolates the line size. The first version of this stage
held the ways at 32 and let the sets grow with the line count, which changed two
things at once, since a larger set count also pulls more of `cin_blk` into the
index.

RRPV WIDTH IS 5, so the re-reference prediction runs 0..31 and a 32-way or wider
set can hold a full priority order over its occupants instead of four buckets.
`rrip_bits` defaults to 2, which is SRRIP as published and what every earlier
result used, so no committed number moves.

WHAT CHANGES WITH THE LINE, which is more than the block size. `cin_block` is a
digit of the `khkw_split` flatten, so shrinking it:

  * multiplies the LINE COUNT of the layer by the same factor, since the same
    weights are packed into smaller lines;
  * would multiply the L1 set count by that factor at a fixed associativity,
    which is exactly what the ways above are scaled to cancel;
  * changes what one miss brings back, so it changes the DRAM traffic per useful
    byte and the spatial reuse a single fetch can serve.

So this is not only a cache-geometry sweep. The layout's line composition moves
with it, and `dram_bytes` is expected to differ between arms rather than staying
pinned the way it does across a pure placement change.

Geometry at each point (capacity / line = lines, lines / ways = sets):

    16 KB, 64 B,  32-way ->  256 lines,  8 sets
    16 KB, 32 B,  64-way ->  512 lines,  8 sets
    16 KB, 16 B, 128-way -> 1024 lines,  8 sets
     8 KB, 64 B,  32-way ->  128 lines,  4 sets
     8 KB, 32 B,  64-way ->  256 lines,  4 sets
     8 KB, 16 B, 128-way ->  512 lines,  4 sets

Usage: conda run -n base python run_sweep.py [workers]
"""
from __future__ import annotations

import csv, json, pathlib, statistics, subprocess, sys, time
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

BASE = base_config(("layout", "cout_block", "weight_bytes", "policy", "rrip_bits",
                    "l2_size_bytes", "l2_assoc", "l2_mshrs", "l2_banks",
                    "l1_latency", "l2_latency", "l2_miss_latency",
                    "prefetch_policy", "prefetch_distance", "l2_prefetch_policy"),
                   policy="rrip", rrip_bits=5)

L1_SIZES  = [16384, 8192]
CIN_BLOCK = [16, 8, 4]          # -> 64 B, 32 B, 16 B lines

# Ways scale WITH the line count so the set count is the same in every arm:
# halving the line doubles the lines, so doubling the ways holds sets fixed.
#
#   16 KB: 256/32 = 8 sets   512/64 = 8 sets   1024/128 = 8 sets
#    8 KB: 128/32 = 4 sets   256/64 = 4 sets    512/128 = 4 sets
#
# Without this the earlier run confounded two changes at once: the smaller line
# also multiplied the set count, which moved more of `cin_blk` into the index.
# Holding the sets fixed leaves the line size as the only thing that varies.
ASSOC = {16: 32, 8: 64, 4: 128}

# THREE SWEEPS PER STREAM, one per line size, and not one six-point grid.
# `cin_block` is a parameter of the address mapper, and one mapper serves a whole
# broadcast sweep, so wcache_sweep refuses a grid whose points disagree about it:
# "a layout sweep is one sweep per layout, each over its own pass of the stream".
# Each sweep still carries both L1 sizes, since those are pure cache geometry and
# share the mapper happily.
GRIDS = {cb: [dict(BASE, cin_block=cb, l1_assoc=ASSOC[cb], l1_size_bytes=sz)
              for sz in L1_SIZES]
         for cb in CIN_BLOCK}
ARMS = [f"{cb * 4}B_{sz // 1024}k" for cb in CIN_BLOCK for sz in L1_SIZES]

arm_size = lambda a: a.rsplit("_", 1)[1]
arm_line = lambda a: a.split("_")[0]

STALL_COLS = ["stall_total", "stall_l1_slot", "stall_l1_line", "stall_l1_port",
              "stall_l2_slot", "stall_l2_line", "stall_l2_port", "stall_channel"]
RATE_COLS  = ["l1_hit_rate", "l2_hit_rate", "l1_accesses", "l2_accesses",
              "dram_accesses", "dram_bytes", "padding_fraction"]


def one(args):
    tag, layer, s, grid_paths, commit = args
    stream = STREAMS / f"{tag}_s{s:05d}.wcts"
    out = []
    for cb in CIN_BLOCK:
        r = subprocess.run(
            [str(BIN), "--config-grid", str(grid_paths[cb]), "--trace", str(stream),
             "--arm", "cache", "--tier", "linesize",
             "--run-id", f"line-{tag}-s{s}-{cb}", "--git-commit", commit, "--header"],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{tag} s{s} cin_block {cb}: {r.stderr[-1500:]}")
        rows = list(csv.DictReader(r.stdout.splitlines()))
        if len(rows) != len(L1_SIZES):
            raise RuntimeError(f"{tag} s{s} cin_block {cb}: got {len(rows)} rows, "
                               f"expected {len(L1_SIZES)}")
        for sz, d in zip(L1_SIZES, rows):
            d["_tag"], d["_sample"], d["_layer"] = tag, str(s), layer
            d["_arm"] = f"{cb * 4}B_{sz // 1024}k"
            out.append(d)
    return out


def aggregate(rows, avail):
    noc = {r["tag"]: r for r in csv.DictReader(open(NOCSIM))}
    g = {}
    for r in rows:
        g.setdefault((r["_tag"], r["_arm"]), []).append(r)
    # 64 B at the same L1 size is the reference: it is the line every earlier
    # stage ran, so the ratio isolates the line-size change.
    base = {(t, arm_size(a)): statistics.mean(float(r["total_cycles"]) for r in rs)
            for (t, a), rs in g.items() if arm_line(a) == "64B"}

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
                   "arm": arm, "line_size_bytes": rs[0]["line_size_bytes"],
                   "cin_block": rs[0]["cin_block"],
                   "l1_size_bytes": rs[0]["l1_size_bytes"],
                   "l1_assoc": rs[0]["l1_assoc"], "l1_num_sets": rs[0]["l1_num_sets"],
                   "l1_num_lines": rs[0]["l1_num_lines"],
                   "samples": len(rs), "cycles": round(mc, 1),
                   "cycles_spread": round((max(cyc) - min(cyc)) / mc, 4),
                   "speedup_vs_64B": round(base[(tag, arm_size(arm))] / mc, 4),
                   "nocsim_total_cycles": round(float(nr["nocsim_total_cycles"]), 1) if nr else ""}
            for c in STALL_COLS + RATE_COLS:
                if c in avail:
                    row[c] = round(m(c), 6 if "rate" in c or "fraction" in c else 2)
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
    grid_paths = {}
    for cb, g in GRIDS.items():
        p = OUT / f"_grid_cin{cb}.json"
        p.write_text(json.dumps(g, indent=1) + "\n")
        grid_paths[cb] = p

    jobs = [(t, l, s, grid_paths, commit) for t, _, l in tags() for s in range(N_SAMPLES)]
    print(f"=== {len(jobs)} streams x {len(ARMS)} configs "
          f"({len(CIN_BLOCK)} passes each), {workers} workers ===", flush=True)
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

    write_csv(OUT / "line_rows.csv", rows)
    by_layer = aggregate(rows, set(rows[0]))
    write_csv(OUT / "line_by_layer.csv", by_layer)

    print()
    for arm in ARMS:
        rs = [r for r in by_layer if r["arm"] == arm]
        v = sum(r["cycles"] for r in rs if r["tag"][0] == "V")
        r_ = sum(r["cycles"] for r in rs if r["tag"][0] == "R")
        dram = sum(r["dram_bytes"] for r in rs)
        print(f"  {arm:10} lines={rs[0]['l1_num_lines']:>5} sets={rs[0]['l1_num_sets']:>4}  "
              f"vgg16 {v:>12,.0f}  resnet19 {r_:>12,.0f}  total {v + r_:>12,.0f}  "
              f"dram {dram / 1e6:>8,.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
