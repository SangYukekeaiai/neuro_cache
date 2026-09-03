#!/usr/bin/env python3
"""L1 eviction count vs the unique lines each core actually visits.

The 0831 `off` arm config verbatim (profiling/0831_l2_prefetch/outputs/_grid.json
row 0), prefetcher off at both levels, over all 31 layers of both workloads.

There is no eviction counter in the results row, so this reads `--line-trace`
instead: one row per RESIDENCY EPISODE, `ended_by` in {evict, invalidate,
end_of_run}. Evictions are the rows that say `evict`; unique lines are the
distinct (core, line) pairs the episodes name. Their ratio is the refetch
factor: 1.0 means every line was fetched once and never came back.

REUSE TIMES is the `hits` column of the same table: how many times a line was
used while it stayed resident. The unit is one RESIDENCY EPISODE and not one
line, because the question a cache asks is what a single fill buys, and a line
refetched twice buys its reuse twice over. Prefetch is off in this config, so
`hits == demand_hits`, which is asserted per row rather than assumed.

One sample per layer (s0), not five. Episodes are a property of the access
ORDER, and the five samples differ only in input data, not in the weight
schedule, so the extra four would restate the same number four times.
"""
from __future__ import annotations

import csv, json, os, pathlib, subprocess, sys, tempfile, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402

BIN     = ROOT / "src/wcache/native/build/release/wcache_run"
STREAMS = ROOT / "profiling/0831_all_layer_streams/streams"
OUT     = STAGE / "outputs"
SAMPLE  = 0

# The 0831 baseline arm, unchanged. Both prefetchers off.
CONFIG = {"layout": "khkw_split", "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
          "l1_size_bytes": 16384, "l1_assoc": 8,
          "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32, "l2_banks": 1,
          "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
          "prefetch_policy": "none", "prefetch_distance": 0,
          "l2_prefetch_policy": "none"}


def tags():
    out = []
    for prefix, tdir in [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]:
        meta = json.loads((ROOT / "input_trace/loas" / tdir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            out.append((f"{prefix}{int(layer.split('_')[1])}", layer, tdir))
    return out


def _cv(xs):
    """Coefficient of variation. 0 means a perfectly balanced array."""
    n = len(xs)
    if n == 0:
        return 0.0
    m = sum(xs) / n
    if m == 0:
        return 0.0
    return (sum((x - m) ** 2 for x in xs) / n) ** 0.5 / m


def summarise(path):
    """Stream the episode table; never hold it in memory."""
    ended = defaultdict(int)          # ended_by -> episodes
    per_core_ep = defaultdict(int)    # core -> episodes
    seen = set()                      # (core, line)
    lines_global = set()
    hits_total = zero_hit = 0
    hist = defaultdict(int)           # hits-in-one-episode -> episodes

    # Per SET INDEX, pooled over the 16 private L1s. Pooled and not per
    # (core, set): the sets are an artefact of the address map, which every
    # core shares, so a hot set is hot in the same place in all sixteen arrays.
    # `set_hist` is what makes a per-set percentile possible at all; a mean
    # alone cannot tell a set that is hot because it is asked for often from
    # one that is hot because its lines never leave.
    set_ep   = defaultdict(int)
    set_ev   = defaultdict(int)
    set_hits = defaultdict(int)
    set_lines = defaultdict(set)
    set_hist = defaultdict(lambda: defaultdict(int))

    with open(path, newline="") as fh:
        rows = csv.DictReader(r for r in fh if not r.startswith("#"))
        for r in rows:
            if r["level"] != "l1":
                continue
            core, line, st = int(r["core"]), int(r["line"]), int(r["set"])
            ended[r["ended_by"]] += 1
            per_core_ep[core] += 1
            seen.add((core, line))
            lines_global.add(line)
            h = int(r["hits"])
            hits_total += h
            zero_hit += (h == 0)
            hist[h] += 1
            assert int(r["demand_hits"]) == h, "prefetch off: every hit is a demand"
            set_ep[st] += 1
            set_ev[st] += (r["ended_by"] == "evict")
            set_hits[st] += h
            set_lines[st].add((core, line))
            set_hist[st][h] += 1
    episodes = sum(ended.values())

    # Percentiles off the histogram, not off a materialised list: the episode
    # count reaches 77,824 per layer and the histogram is the deliverable
    # anyway, so sorting the values themselves would be the same work twice.
    def pct(q):
        want, run = q * episodes, 0
        for h in sorted(hist):
            run += hist[h]
            if run >= want:
                return h
        return 0

    def pct_of(c, q):
        n = sum(c.values())
        want, run = q * n, 0
        for h in sorted(c):
            run += c[h]
            if run >= want:
                return h
        return 0

    sets = []
    for st in sorted(set_ep):
        n = set_ep[st]
        sets.append({
            "set": st, "episodes": n, "evictions": set_ev[st],
            "unique_lines": len(set_lines[st]), "hits": set_hits[st],
            "reuse_mean": round(set_hits[st] / n, 3),
            "reuse_p10": pct_of(set_hist[st], 0.10),
            "reuse_p50": pct_of(set_hist[st], 0.50),
            "reuse_p90": pct_of(set_hist[st], 0.90),
            "reuse_max": max(set_hist[st]),
        })

    return hist, sets, {
        "l1_episodes":      episodes,
        "l1_evictions":     ended["evict"],
        "l1_invalidations": ended["invalidate"],
        "l1_resident_eor":  ended["end_of_run"],
        "unique_core_line": len(seen),
        "unique_lines":     len(lines_global),
        "refetch_factor":   round(episodes / len(seen), 4) if seen else 0.0,
        "evict_per_unique": round(ended["evict"] / len(seen), 4) if seen else 0.0,
        "episode_hits":     hits_total,
        "dead_episodes":    zero_hit,
        "dead_fraction":    round(zero_hit / episodes, 4) if episodes else 0.0,
        "cores_seen":       len(per_core_ep),
        "reuse_mean":       round(hits_total / episodes, 3) if episodes else 0.0,
        "reuse_p10":        pct(0.10),
        "reuse_p50":        pct(0.50),
        "reuse_p90":        pct(0.90),
        "reuse_p99":        pct(0.99),
        "reuse_min":        min(hist) if hist else 0,
        "reuse_max":        max(hist) if hist else 0,
        "reuse_distinct":   len(hist),

        # Set imbalance, as three numbers that fail differently. The ratio is
        # what a hot set looks like to a designer, the CV is what it looks like
        # over the whole array, and the reuse ratio says whether the hot set is
        # hot because it is ASKED for more or because its lines live longer.
        "n_sets_seen":      len(sets),
        "set_ep_max":       max(s["episodes"] for s in sets),
        "set_ep_min":       min(s["episodes"] for s in sets),
        "set_ep_ratio":     round(max(s["episodes"] for s in sets)
                                  / max(1, min(s["episodes"] for s in sets)), 4),
        "set_ep_cv":        round(_cv([s["episodes"] for s in sets]), 4),
        "set_reuse_ratio":  round(max(s["reuse_mean"] for s in sets)
                                  / max(1e-9, min(s["reuse_mean"] for s in sets)), 4),
        "hot_set":          max(sets, key=lambda s: s["episodes"])["set"],
        "cold_set":         min(sets, key=lambda s: s["episodes"])["set"],
    }


def one(args):
    tag, layer, workload, cfg_path = args
    fd, tmp = tempfile.mkstemp(prefix=f"lt_{tag}_", suffix=".csv")
    os.close(fd)
    try:
        r = subprocess.run(
            [str(BIN), "--config", str(cfg_path),
             "--trace", str(STREAMS / f"{tag}_s{SAMPLE:05d}.wcts"),
             "--out", "-", "--header",
             "--line-trace", tmp, "--line-trace-level", "l1"],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{tag}: {r.stderr[-1500:]}")
        res = next(csv.DictReader(r.stdout.splitlines()))
        row = {"tag": tag, "workload": workload, "layer": layer,
               "l1_accesses": res["l1_accesses"], "l1_hits": res["l1_hits"],
               "l1_hit_rate": res["l1_hit_rate"],
               "l1_num_lines": res["l1_num_lines"], "n_cores": res["n_cores"]}
        hist, sets, agg = summarise(tmp)
        row.update(agg)
        return row, hist, sets
    finally:
        os.unlink(tmp)


def main() -> int:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_path = OUT / "_config.json"
    cfg_path.write_text(json.dumps(CONFIG, indent=1) + "\n")
    jobs = [(t, l, w, cfg_path) for t, l, w in tags()]
    print(f"=== {len(jobs)} layers, sample {SAMPLE}, {workers} workers ===", flush=True)
    rows, hists, setrows, t0 = [], {}, [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                row, hist, sets = f.result()
                rows.append(row)
                hists[row["tag"]] = (row["workload"], row["layer"], hist)
                for s in sets:
                    setrows.append(dict(tag=row["tag"], workload=row["workload"],
                                        layer=row["layer"], **s))
            except Exception as exc:
                print(f"  [{i}/{len(jobs)}] {futs[f][0]}: FAILED ({exc!r})", flush=True)
                continue
            print(f"  [{i}/{len(jobs)}] {futs[f][0]}", flush=True)
    if not rows:
        print("no rows"); return 1
    rows.sort(key=lambda d: (d["workload"], int(d["tag"][1:])))
    dst = OUT / "l1_evict.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    hdst = OUT / "l1_reuse_hist.csv"
    with open(hdst, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "workload", "layer", "hits", "episodes"])
        for tag in sorted(hists, key=lambda t: (t[0], int(t[1:]))):
            wl, layer, hist = hists[tag]
            for h in sorted(hist):
                w.writerow([tag, wl, layer, h, hist[h]])
    sdst = OUT / "l1_by_set.csv"
    setrows.sort(key=lambda d: (d["workload"], int(d["tag"][1:]), d["set"]))
    with open(sdst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(setrows[0]))
        w.writeheader(); w.writerows(setrows)
    print(f"{len(rows)} rows in {time.time()-t0:.1f}s -> {dst}")
    print(f"reuse-times histogram -> {hdst}")
    print(f"per-set table ({len(setrows)} rows) -> {sdst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
