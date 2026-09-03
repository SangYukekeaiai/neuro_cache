#!/usr/bin/env python3
"""Join the three arms per layer, and gate the off arm against the run it must
reproduce. One row per (layer, arm), each the mean over its 5 samples."""
from __future__ import annotations
import csv, json, pathlib, statistics, sys

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
OUT   = STAGE / "outputs"
PREV  = ROOT / "profiling/0831_all_layer_streams/outputs"

def mean(rs, c): return statistics.mean(float(r[c]) for r in rs)

def main() -> int:
    rows = list(csv.DictReader(open(OUT / "l2pf_rows.csv")))
    nocsim = json.loads((PREV / "nocsim_rows.json").read_text())
    base_total   = {t: statistics.mean(r["total_cycles"] for r in nocsim if r["tag"] == t)
                    for t in {r["tag"] for r in nocsim}}
    base_compute = {t: statistics.mean(r["compute_per_node"] for r in nocsim if r["tag"] == t)
                    for t in {r["tag"] for r in nocsim}}

    # --- the gate: the off arm must reproduce the no-prefetch run -------------
    prev = {}
    for r in csv.DictReader(open(PREV / "wcache_rows.csv")):
        prev[(r["_tag"], r["_sample"])] = r
    bad = []
    for r in rows:
        if r["_arm"] != "off":
            continue
        p = prev.get((r["_tag"], r["_sample"]))
        if p is None:
            continue
        for col in ("total_cycles", "l1_hits", "l1_accesses", "l2_hits", "l2_accesses",
                    "dram_accesses", "dram_bytes", "stall_total"):
            if p[col] != r[col]:
                bad.append((r["_tag"], r["_sample"], col, p[col], r[col]))
    print(f"V1 gate: {len(prev)} baseline rows compared on 8 columns -> "
          f"{'OK, the off arm reproduces the no-prefetch run exactly' if not bad else str(len(bad)) + ' MISMATCHES'}")
    for b in bad[:8]:
        print("   ", b)

    groups = {}
    for r in rows:
        groups.setdefault((r["_tag"], r["_arm"]), []).append(r)
    order = []
    for (tag, arm) in groups:
        if tag not in order:
            order.append(tag)

    out = []
    for tag in order:
        for arm in ("off", "up", "down", "both"):
            rs = groups.get((tag, arm))
            if not rs:
                continue
            cyc = mean(rs, "total_cycles")
            off = mean(groups[(tag, "off")], "total_cycles")
            out.append({
                "tag": tag, "layer": rs[0]["_layer"], "arm": arm, "samples": len(rs),
                "cycles": round(cyc, 1),
                "speedup_vs_off": round(off / cyc, 4),
                "nocsim_total_cycles": round(base_total[tag], 1),
                "speedup_vs_nocsim": round(base_total[tag] / cyc, 4),
                "cycles_over_compute_floor": round(cyc / base_compute[tag], 4),
                "l1_hit_rate": round(mean(rs, "l1_hit_rate"), 6),
                "l2_hit_rate": round(mean(rs, "l2_hit_rate"), 6),
                "l2_accesses": round(mean(rs, "l2_accesses"), 1),
                "dram_accesses": round(mean(rs, "dram_accesses"), 1),
                "dram_bytes": round(mean(rs, "dram_bytes"), 1),
                "stall_total": round(mean(rs, "stall_total"), 1),
                "stall_l2_port": round(mean(rs, "stall_l2_port"), 1),
                "stall_channel": round(mean(rs, "stall_channel"), 1),
                "l2_pf_issued": round(mean(rs, "l2_pf_issued"), 1),
                "l2_pf_issued_up": round(mean(rs, "l2_pf_issued_up"), 1),
                "l2_pf_issued_down": round(mean(rs, "l2_pf_issued_down"), 1),
                "l2_pf_timely": round(mean(rs, "l2_pf_timely"), 1),
                "l2_pf_late": round(mean(rs, "l2_pf_late"), 1),
                "l2_pf_wasted": round(mean(rs, "l2_pf_wasted"), 1),
                "l2_pf_dropped_array_hit": round(mean(rs, "l2_pf_dropped_array_hit"), 1),
                "l2_pf_coverage": round(mean(rs, "l2_pf_coverage"), 6),
            })
    dst = OUT / "l2pf_by_layer.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)

    by = {(r["tag"], r["arm"]): r for r in out}
    import math
    ARMS = ("off", "up", "down", "both")

    # --- against stage 3 (nocsim), which is the comparison this table is for ---
    print(f"\n{'tag':>4}" + "".join(f"{a + ' vs s3':>12}" for a in ARMS) + f"{'stage3':>12}")
    for tag in order:
        print(f"{tag:>4}" + "".join(f"{by[(tag,a)]['speedup_vs_nocsim']:>12.4f}" for a in ARMS)
              + f"{by[(tag,'off')]['nocsim_total_cycles']:>12,.0f}")
    print()
    print(f"{'arm':>6}{'geomean vs s3':>16}{'ahead of s3':>14}{'geomean vs off':>17}"
          f"{'faster than off':>18}{'best':>9}{'worst':>9}")
    for arm in ARMS:
        v = [by[(t, arm)]["speedup_vs_nocsim"] for t in order]
        g = [by[(t, arm)]["speedup_vs_off"] for t in order]
        print(f"{arm:>6}{math.exp(statistics.mean(math.log(x) for x in v)):>16.4f}"
              f"{sum(1 for x in v if x > 1):>10}/{len(v):<3}"
              f"{math.exp(statistics.mean(math.log(x) for x in g)):>17.4f}"
              f"{sum(1 for x in g if x > 1):>14}/{len(g):<3}"
              f"{max(g):>9.3f}{min(g):>9.3f}")
    print(f"\n-> {dst}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
