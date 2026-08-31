#!/usr/bin/env python3
"""The layout control: khkw_split against the two layouts already in the tree.

One point of the sweep, its best (64-byte lines, one L2 bank, no prefetch), run
under all three layouts on all 4 layers and all 5 samples. Without it the sweep
reports a speedup against stage 3 and leaves a reader unable to say whether it
came from the layout or from having a cache at all.

60 runs, one process each. wcache_sweep cannot serve this grid: BroadcastSweep
gives one mapper to the whole grid and refuses points that disagree on `layout`.
"""
import concurrent.futures as cf
import csv, json, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BIN  = ROOT / "src/wcache/native/build/release/wcache_run"
STRM = HERE / "inputs/streams"
OUT  = HERE / "outputs"
CFG  = OUT / "_khkw_grid"

TAGS    = ["V8", "V9", "R9", "R16"]
SAMPLES = range(5)
LAYOUTS = ["block_pack", "split_cin", "khkw_split"]

BASE = {
    "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
    "l1_size_bytes": 16384, "l1_assoc": 8,
    "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "l2_banks": 1, "prefetch_policy": "none", "prefetch_distance": 0,
}


def one(args):
    tag, s, layout, path, commit = args
    r = subprocess.run(
        [str(BIN), "--config", str(path),
         "--trace", str(STRM / f"{tag}_s{s:05d}.wcts"),
         "--arm", "cache", "--tier", "layout_control",
         "--run-id", f"ctl-{tag}-s{s}-{layout}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{s} {layout}\n{r.stderr}")
    a, b = list(csv.reader(r.stdout.splitlines()))
    d = dict(zip(a, b))
    d["_tag"], d["_sample"] = tag, str(s)
    return a, d


def main():
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    CFG.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()

    paths = {}
    for layout in LAYOUTS:
        p = CFG / f"control_{layout}.json"
        p.write_text(json.dumps(dict(BASE, layout=layout), indent=1))
        paths[layout] = p

    work = [(tag, s, l, paths[l], commit)
            for tag in TAGS for s in SAMPLES for l in LAYOUTS]
    rows, header, t0 = [], None, time.time()
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        for hdr, d in pool.map(one, work):
            header = hdr
            rows.append(d)
    rows.sort(key=lambda d: (d["_tag"], int(d["_sample"]), d["layout"]))

    out = OUT / "khkw_layout_control.csv"
    cols = ["_tag", "_sample"] + header
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in rows:
            w.writerow([d[c] for c in cols])
    print(f"{len(rows)} rows -> {out}  ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
