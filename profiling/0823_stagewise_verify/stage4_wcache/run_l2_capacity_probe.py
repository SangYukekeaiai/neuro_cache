#!/usr/bin/env python3
"""Why the L2 hit rate is 0, as a capacity sweep rather than an assertion.

The main sweep reports an L2 hit rate of 0.000 at almost every point, which on
its own is a statistic a reader cannot act on: it does not say whether the L2 is
too small, whether the L1 is absorbing everything, or whether the layer has no
reuse to find. This walks l2_size_bytes from the sweep's 512 KB to 16 MB at the
sweep's best point (64-byte lines, one bank, no prefetch) and lets the curve say
which it is.

l2_size_bytes does not feed the mapper, so all six points share one grid and one
pass of the stream.
"""
import concurrent.futures as cf
import csv, json, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BIN  = ROOT / "src/wcache/native/build/release/wcache_sweep"
STRM = HERE / "inputs/streams"
OUT  = HERE / "outputs"
CFG  = OUT / "_khkw_grid" / "l2_capacity.json"

TAGS    = ["V8", "V9", "R9", "R16"]
SAMPLES = range(5)
SIZES   = [512 * 1024, 1 << 20, 2 << 20, 4 << 20, 8 << 20, 16 << 20]

BASE = {
    "cin_block": 16, "cout_block": 4, "weight_bytes": 1, "layout": "khkw_split",
    "l1_size_bytes": 16384, "l1_assoc": 8, "l2_assoc": 16, "l2_mshrs": 32,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "l2_banks": 1, "prefetch_policy": "none", "prefetch_distance": 0,
}


def one(args):
    tag, s, commit = args
    r = subprocess.run(
        [str(BIN), "--config-grid", str(CFG), "--trace", str(STRM / f"{tag}_s{s:05d}.wcts"),
         "--arm", "cache", "--tier", "l2_capacity",
         "--run-id", f"l2cap-{tag}-s{s}", "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{s}\n{r.stderr}")
    got = list(csv.reader(r.stdout.splitlines()))
    out = []
    for line in got[1:]:
        d = dict(zip(got[0], line))
        d["_tag"], d["_sample"] = tag, str(s)
        out.append(d)
    return got[0], out


def main():
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps([dict(BASE, l2_size_bytes=n) for n in SIZES], indent=1))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()

    rows, header, t0 = [], None, time.time()
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        for hdr, got in pool.map(one, [(t, s, commit) for t in TAGS for s in SAMPLES]):
            header = hdr
            rows.extend(got)
    rows.sort(key=lambda d: (d["_tag"], int(d["_sample"]), int(d["l2_size_bytes"])))

    out = OUT / "khkw_l2_capacity.csv"
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
