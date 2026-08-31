#!/usr/bin/env python3
"""The khkw_split cache sweep: 48 configs x 4 layers x 5 samples = 960 runs.

The grid is line size [16, 32, 64] B x l2_banks [1, 2, 4, 8] x prefetch
distance [0, 1, 2, 4], all under the khkw_split layout, an L2 of 512 KB with 32
MSHRs, and everything else held at the C4 control's values.

Line size is not a sweep axis inside one wcache_sweep invocation. BroadcastSweep
gives one mapper to the whole grid and refuses points that disagree on
cin_block, so the 48 points are three grids of 16, each over its own pass of the
stream. That is 3 x 20 = 60 invocations rather than 960 process launches, and
each invocation parses the stream once for all 16 of its engines.

Prefetch distance 0 carries prefetch_policy "none": validate() refuses
next_burst at distance 0 rather than silently running as none, so the two keys
move together and the grid is written out as an explicit array instead of an
axes cross product.
"""
import concurrent.futures as cf
import csv, json, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BIN  = ROOT / "src/wcache/native/build/release/wcache_sweep"
STRM = HERE / "inputs/streams"
OUT  = HERE / "outputs"
GRID = OUT / "_khkw_grid"

TAGS       = ["V8", "V9", "R9", "R16"]
SAMPLES    = range(5)
LINE_BYTES = [16, 32, 64]
BANKS      = [1, 2, 4, 8]
DISTANCES  = [0, 1, 2, 4]

COUT_BLOCK = 4  # the innermost 4 COUT the sweep spec fixes

BASE = {
    "cout_block":      COUT_BLOCK,
    "weight_bytes":    1,
    "layout":          "khkw_split",
    "l1_size_bytes":   16384,
    "l1_assoc":        8,
    "l2_size_bytes":   524288,
    "l2_assoc":        16,
    "l2_mshrs":        32,
    "l1_latency":      0,
    "l2_latency":      2,
    "l2_miss_latency": 24,
}


def grid_for(line_bytes):
    """The 16 points that share one mapper: banks x prefetch at one line size."""
    cin_block = line_bytes // (COUT_BLOCK * BASE["weight_bytes"])
    points = []
    for banks in BANKS:
        for dist in DISTANCES:
            p = dict(BASE, cin_block=cin_block, l2_banks=banks)
            p["prefetch_policy"]   = "none" if dist == 0 else "next_burst"
            p["prefetch_distance"] = dist
            points.append(p)
    return points


def one(args):
    """One wcache_sweep invocation: 16 grid points over one pass of one stream."""
    tag, s, lb, grid_path, commit = args
    wcts = STRM / f"{tag}_s{s:05d}.wcts"
    r = subprocess.run(
        [str(BIN), "--config-grid", str(grid_path), "--trace", str(wcts),
         "--arm", "cache", "--tier", "khkw",
         "--run-id", f"khkw-{tag}-s{s}-{lb}b",
         "--git-commit", commit, "--header"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"sweep failed: {tag} s{s} {lb}B\n{r.stderr}")
    got = list(csv.reader(r.stdout.splitlines()))
    header, out = got[0], []
    for line in got[1:]:
        d = dict(zip(header, line))
        d["_tag"], d["_sample"] = tag, str(s)
        out.append(d)
    return tag, s, lb, header, out


def main():
    jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    GRID.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()

    paths = {}
    for lb in LINE_BYTES:
        p = GRID / f"khkw_{lb}b.json"
        p.write_text(json.dumps(grid_for(lb), indent=1))
        paths[lb] = p

    work = [(tag, s, lb, paths[lb], commit)
            for tag in TAGS for s in SAMPLES for lb in LINE_BYTES]

    # Threads and not processes: every one of them is blocked in wait() on a
    # child, so the GIL is never the thing holding a job up.
    rows, header = [], None
    n, t0 = 0, time.time()
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        for tag, s, lb, hdr, got in pool.map(one, work):
            header = hdr
            rows.extend(got)
            n += 1
            print(f"  {n}/{len(work)}  {tag} s{s} {lb}B  {time.time()-t0:.0f}s", flush=True)

    # pool.map preserves submission order, but the rows are sorted anyway so the
    # CSV is byte-identical whatever the job count was.
    rows.sort(key=lambda d: (d["_tag"], int(d["_sample"]), int(d["line_size_bytes"]),
                             int(d["l2_banks"]), int(d["prefetch_distance"])))

    cols = ["_tag", "_sample"] + header
    out = OUT / "khkw_sweep.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for d in rows:
            w.writerow([d[c] for c in cols])
    print(f"{len(rows)} rows -> {out}  ({time.time()-t0:.0f}s)")

    expect = len(TAGS) * len(SAMPLES) * len(LINE_BYTES) * len(BANKS) * len(DISTANCES)
    if len(rows) != expect:
        raise SystemExit(f"expected {expect} rows, got {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
