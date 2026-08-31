#!/usr/bin/env python3
"""The reuse-distance runs: 4 layers x 5 samples at the khkw_split best config.

Plan unit U4 of log/2026-08-31-reuse-distance-plan.md.

One unit of work is one stream: run the engine with --access-log, hand the log
to reuse_tool, delete the log. Peak disk is therefore one log per worker, about
40 MB each, rather than the 450 MB the whole corpus would occupy at once.

The best config is copied from Friday's grid,
profiling/0823_stagewise_verify/stage4_wcache/outputs/_khkw_grid/khkw_64b.json[0],
and is asserted against it at startup so the two cannot drift apart.

V1 and the re-triage precondition are checked per run, here, because this is the
one place that holds both the histogram and the results row.
"""
import concurrent.futures as cf
import csv
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN  = ROOT / "src/wcache/native/build/release/wcache_run"
TOOL = HERE / "reuse_tool"
STRM = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/inputs/streams"
GRID = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/outputs/_khkw_grid/khkw_64b.json"
OUT  = HERE / "outputs"

TAGS    = ["V8", "V9", "R9", "R16"]
SAMPLES = range(5)

LAYER_NAME = {
    "V8":  "vgg16 layer_08_features_3",
    "V9":  "vgg16 layer_09_features_30",
    "R9":  "resnet19 layer_09_layer2_0_conv2",
    "R16": "resnet19 layer_16_layer3_0_conv2",
}

# Friday's best point, verbatim.
BEST = {
    "cout_block": 4, "weight_bytes": 1, "layout": "khkw_split",
    "l1_size_bytes": 16384, "l1_assoc": 8,
    "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "cin_block": 16, "l2_banks": 1,
    "prefetch_policy": "none", "prefetch_distance": 0,
}


def check_best_matches_friday():
    """The config here must BE the artifact's best point, not resemble it."""
    grid = json.loads(GRID.read_text())
    want = grid[0]
    if want != BEST:
        diff = {k: (want.get(k), BEST.get(k)) for k in set(want) | set(BEST)
                if want.get(k) != BEST.get(k)}
        raise SystemExit(f"BEST has drifted from {GRID.name}[0]: {diff}")


def preview():
    print("=" * 78)
    print("PREVIEW -- reuse-distance runs, nothing has executed yet")
    print("=" * 78)
    print(f"  config   : khkw_split, 64 B lines (cin_block 16 x cout_block 4 x 1 B)")
    print(f"             L1 {BEST['l1_size_bytes']//1024} KB {BEST['l1_assoc']}-way"
          f"   L2 {BEST['l2_size_bytes']//1024} KB {BEST['l2_assoc']}-way"
          f"   l2_banks {BEST['l2_banks']}")
    print(f"             latencies l1 {BEST['l1_latency']} / l2 {BEST['l2_latency']}"
          f" / dram {BEST['l2_miss_latency']}"
          f"   prefetch {BEST['prefetch_policy']} d={BEST['prefetch_distance']}")
    print(f"             verified identical to {GRID.parent.name}/{GRID.name}[0]")
    print(f"  layers   : " + ", ".join(f"{t} ({LAYER_NAME[t]})" for t in TAGS[:2]))
    print(f"             " + ", ".join(f"{t} ({LAYER_NAME[t]})" for t in TAGS[2:]))
    print(f"  samples  : {len(list(SAMPLES))} per layer, {len(TAGS)*len(list(SAMPLES))} runs total")
    print(f"  cores    : 16 private L1 stacks + 1 shared L2 stack per run")
    print(f"  produces : outputs/reuse_hist.csv   level,core,distance,count per (layer,sample)")
    print(f"             outputs/reuse_runs.csv   the 93-column results row per run")
    print(f"             outputs/v4_independence.csv  the L1-histogram config check")
    print(f"  checks   : V1 histogram total == l1_accesses / l2_accesses, exactly")
    print(f"             max_wait_depth == 0, so no request re-probes")
    print(f"  disk     : one ~40 MB access log per worker, deleted after use")
    print("=" * 78)


def one(args):
    tag, s, overrides, label = args
    cfg = dict(BEST, **overrides)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        (td / "cfg.json").write_text(json.dumps(cfg))
        log, hist = td / "a.log", td / "h.csv"
        r = subprocess.run(
            [str(RUN), "--config", str(td / "cfg.json"),
             "--trace", str(STRM / f"{tag}_s{s:05d}.wcts"),
             "--run-id", f"reuse-{label}-{tag}-s{s}", "--header",
             "--access-log", str(log)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"wcache_run failed for {tag} s{s}:\n{r.stderr}")
        rows = list(csv.reader(r.stdout.splitlines()))
        row = dict(zip(rows[0], rows[1]))

        t = subprocess.run([str(TOOL), str(log), str(hist)], capture_output=True, text=True)
        if t.returncode != 0:
            raise RuntimeError(f"reuse_tool failed for {tag} s{s}:\n{t.stderr}")
        hrows = list(csv.DictReader(hist.open()))
        # The log is deleted with the temp dir, which is what keeps peak disk at
        # one log per worker rather than the whole corpus.

    # --- the two per-run checks, made where both numbers are in hand ---------
    tot = {"l1": 0, "l2": 0}
    for h in hrows:
        tot[h["level"]] += int(h["count"])
    for lvl, col in (("l1", "l1_accesses"), ("l2", "l2_accesses")):
        if tot[lvl] != int(row[col]):
            raise RuntimeError(f"V1 FAILED {tag} s{s} {lvl}: histogram {tot[lvl]:,} "
                               f"vs {col} {int(row[col]):,}")
    if int(row["max_wait_depth"]) != 0:
        raise RuntimeError(
            f"{tag} s{s}: max_wait_depth = {row['max_wait_depth']}, so requests re-probe and "
            f"l1_accesses counts probes rather than references. The distances would be "
            f"contaminated with re-triage repeats; see access_log.h.")

    for h in hrows:
        h["_tag"], h["_sample"], h["_label"] = tag, str(s), label
    row["_tag"], row["_sample"], row["_label"] = tag, str(s), label
    return tag, s, label, hrows, row


def main():
    check_best_matches_friday()
    preview()
    if not RUN.exists(): raise SystemExit(f"missing {RUN}; run `make MODE=release apps`")
    if not TOOL.exists(): raise SystemExit(f"missing {TOOL}; build reuse_tool first")
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 4

    work = [(tag, s, {}, "best") for tag in TAGS for s in SAMPLES]
    # V4: the same layer at a 16x larger L1. Section 2 of the plan claims the L1
    # access sequence cannot depend on the cache, so these histograms must match.
    work += [(tag, 0, {"l1_size_bytes": 262144}, "l1_256k") for tag in TAGS]

    hist_rows, run_rows = [], []
    t0, n = time.time(), 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        for tag, s, label, hrows, row in pool.map(one, work):
            hist_rows.extend(hrows); run_rows.append(row); n += 1
            print(f"  {n}/{len(work)}  {tag} s{s} [{label}]  "
                  f"l1={int(row['l1_accesses']):>9,} l2={int(row['l2_accesses']):>7,}  "
                  f"{time.time()-t0:.0f}s", flush=True)

    best_h = [h for h in hist_rows if h["_label"] == "best"]
    hcols = ["_tag", "_sample", "level", "core", "distance", "count"]
    with (OUT / "reuse_hist.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(hcols)
        for h in sorted(best_h, key=lambda d: (d["_tag"], int(d["_sample"]), d["level"],
                                               int(d["core"]), int(d["distance"]))):
            w.writerow([h[c] for c in hcols])

    rcols = ["_tag", "_sample", "_label"] + [c for c in run_rows[0] if not c.startswith("_")]
    with (OUT / "reuse_runs.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(rcols)
        for r in sorted(run_rows, key=lambda d: (d["_label"], d["_tag"], int(d["_sample"]))):
            w.writerow([r[c] for c in rcols])

    # --- V4 ------------------------------------------------------------------
    def l1_sig(label, tag):
        return sorted((h["core"], h["distance"], h["count"]) for h in hist_rows
                      if h["_label"] == label and h["_tag"] == tag
                      and h["_sample"] == "0" and h["level"] == "l1")
    print("\nV4: the L1 histogram must not depend on the L1 size")
    v4 = []
    for tag in TAGS:
        a, b = l1_sig("best", tag), l1_sig("l1_256k", tag)
        ok = a == b
        v4.append({"layer": tag, "l1_16KB_rows": len(a), "l1_256KB_rows": len(b),
                   "identical": ok})
        print(f"  {tag:>4}: 16 KB vs 256 KB  ->  {'IDENTICAL' if ok else 'DIFFERS'}"
              f"   ({len(a)} buckets)")
    with (OUT / "v4_independence.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(v4[0])); w.writeheader(); w.writerows(v4)
    if not all(r["identical"] for r in v4):
        raise SystemExit("V4 FAILED: the L1 sequence is not config-independent after all")

    print(f"\n{len(best_h)} histogram rows, {len(run_rows)} runs -> {OUT}  "
          f"({time.time()-t0:.0f}s)")
    print("V1 passed on every run (histogram total == l1_accesses and l2_accesses)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
