#!/usr/bin/env python3
"""The L2 cin-neighbour prefetcher over all 31 layers, three arms.

One wcache_sweep invocation per stream carries all three configs, so the stream
is parsed once for three engines rather than three times. They share `cin_block`,
which BroadcastSweep requires of one grid.

  off    the 0831 baseline, l2_prefetch_policy none. Its rows must reproduce
         outputs/wcache_rows.csv from the no-prefetch run to the digit, which is
         the standing gate: a policy that changes a run it is switched off in is
         not a policy.
  up     cin_blk +1 only
  down   cin_blk -1 only. Its own arm rather than an inference from `both`
         minus `up`: the two halves interact through the cache they share, so
         subtracting one from the other would report a number no run produced.
  both   cin_blk +-1, the specification as written.
"""
from __future__ import annotations

import csv, json, pathlib, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from archmodels.trace import valid_layer_names  # noqa: E402

BIN     = ROOT / "src/wcache/native/build/release/wcache_sweep"
STREAMS = ROOT / "profiling/0831_all_layer_streams/streams"
OUT     = STAGE / "outputs"
N_SAMPLES = 5

BASE = {"layout": "khkw_split", "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
        "l1_size_bytes": 16384, "l1_assoc": 8,
        "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32, "l2_banks": 1,
        "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
        "prefetch_policy": "none", "prefetch_distance": 0}
PF = dict(l2_prefetch_policy="neighbour", l2_prefetch_axis="cin", l2_prefetch_distance=1)
GRID = [
    dict(BASE, l2_prefetch_policy="none"),
    dict(BASE, **PF, l2_prefetch_up=1, l2_prefetch_down=0),   # +1 only
    dict(BASE, **PF, l2_prefetch_up=0, l2_prefetch_down=1),   # -1 only
    dict(BASE, **PF, l2_prefetch_up=1, l2_prefetch_down=1),   # both
]
ARM = {0: "off", 1: "up", 2: "down", 3: "both"}


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
         "--arm", "cache", "--tier", "l2pf",
         "--run-id", f"l2pf-{tag}-s{s}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{s}: {r.stderr[-1500:]}")
    rows = list(csv.DictReader(r.stdout.splitlines()))
    if len(rows) != len(GRID):
        raise RuntimeError(f"{tag} s{s}: got {len(rows)} rows, expected {len(GRID)}")
    for i, d in enumerate(rows):
        d["_tag"], d["_sample"], d["_arm"], d["_layer"] = tag, str(s), ARM[i], layer
    return rows


def main() -> int:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    OUT.mkdir(parents=True, exist_ok=True)
    grid_path = OUT / "_grid.json"
    grid_path.write_text(json.dumps(GRID, indent=1) + "\n")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    jobs = [(t, l, s, grid_path, commit) for t, l in tags() for s in range(N_SAMPLES)]
    print(f"=== {len(jobs)} streams x {len(GRID)} configs, {workers} workers ===", flush=True)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(one, j): j for j in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            j = futs[f]
            try:
                rows.extend(f.result())
            except Exception as exc:
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[2]}: FAILED ({exc!r})", flush=True)
                continue
            if i % 25 == 0 or i == len(jobs):
                print(f"  [{i}/{len(jobs)}] {j[0]} s{j[2]}", flush=True)
    dst = OUT / "l2pf_rows.csv"
    with open(dst, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} rows in {time.time()-t0:.1f}s -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
