#!/usr/bin/env python3
"""The khkw_split sweep against stage 3, per layer and per config.

Two baselines, because stage 3 reports two numbers and they answer different
questions. `total_cycles` is what the NoC simulator took to deliver the layer,
so the ratio against it says whether a cache in front of the cores beats the
network as it stands. `compute_per_node` is the work a core would do with every
weight already in hand, so the ratio against it says how far a config is from
the floor no memory system can go under.

One row per (layer, line_bytes, l2_banks, prefetch_distance), each the mean over
the 5 samples. The samples are 5 draws of the same layer under the same
schedule, so their spread is a property of the input trace and not of the cache;
the spread is carried as a column rather than averaged away.
"""
import csv, json, pathlib, statistics, sys

HERE  = pathlib.Path(__file__).resolve().parent
SWEEP = HERE / "outputs/khkw_sweep.csv"
S3    = HERE.parent / "stage3_nocsim/outputs/stage3_results.json"
OUT   = HERE / "outputs/khkw_vs_stage3.csv"

KEY = ("_tag", "line_size_bytes", "l2_banks", "prefetch_distance")


def main():
    stage3 = json.load(open(S3))
    layer_of = {r["tag"]: r["layer"] for r in stage3}
    base_total = {}
    base_compute = {}
    for tag in {r["tag"] for r in stage3}:
        rs = [r for r in stage3 if r["tag"] == tag]
        base_total[tag]   = statistics.mean(r["total_cycles"] for r in rs)
        base_compute[tag] = statistics.mean(r["compute_per_node"] for r in rs)

    groups = {}
    for r in csv.DictReader(open(SWEEP)):
        groups.setdefault(tuple(r[k] for k in KEY), []).append(r)

    rows = []
    for k, rs in groups.items():
        tag = k[0]
        n = lambda c: [float(r[c]) for r in rs]
        cyc = n("total_cycles")
        mean_cyc = statistics.mean(cyc)
        rows.append({
            "tag": tag,
            "layer": layer_of[tag],
            "line_size_bytes": int(k[1]),
            "l2_banks": int(k[2]),
            "prefetch_distance": int(k[3]),
            "samples": len(rs),
            "wcache_cycles": round(mean_cyc, 1),
            "wcache_cycles_spread": round((max(cyc) - min(cyc)) / mean_cyc, 4),
            "stage3_total_cycles": round(base_total[tag], 1),
            "stage3_compute_per_node": round(base_compute[tag], 1),
            "speedup_vs_stage3_total": round(base_total[tag] / mean_cyc, 4),
            "cycles_over_compute_floor": round(mean_cyc / base_compute[tag], 4),
            "l1_hit_rate": round(statistics.mean(n("l1_hit_rate")), 6),
            "l2_hit_rate": round(statistics.mean(n("l2_hit_rate")), 6),
            "l1_accesses": round(statistics.mean(n("l1_accesses")), 1),
            "l2_accesses": round(statistics.mean(n("l2_accesses")), 1),
            "dram_accesses": round(statistics.mean(n("dram_accesses")), 1),
            "dram_bytes": round(statistics.mean(n("dram_bytes")), 1),
            "stall_total": round(statistics.mean(n("stall_total")), 1),
            "hidden_fraction": round(statistics.mean(n("hidden_fraction")), 4),
            "pf_coverage": round(statistics.mean(n("pf_coverage")) if rs[0]["pf_coverage"] else 0.0, 4),
            "padding_fraction": round(statistics.mean(n("padding_fraction")), 4),
        })

    rows.sort(key=lambda d: (d["tag"], d["line_size_bytes"], d["l2_banks"],
                             d["prefetch_distance"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {OUT}")

    # --- what the summary at the top of the artifact is built from -------------
    best = {}
    for r in rows:
        b = best.get(r["tag"])
        if b is None or r["wcache_cycles"] < b["wcache_cycles"]:
            best[r["tag"]] = r
    print("\nbest config per layer, by mean total_cycles")
    for tag in ["V8", "V9", "R9", "R16"]:
        r = best[tag]
        print(f"  {tag:4} {r['line_size_bytes']:3}B banks {r['l2_banks']} pf {r['prefetch_distance']}"
              f"  {r['wcache_cycles']:>10.0f} vs stage3 {r['stage3_total_cycles']:>10.0f}"
              f"  x{r['speedup_vs_stage3_total']:.2f}"
              f"  L1 {r['l1_hit_rate']:.3f} L2 {r['l2_hit_rate']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
