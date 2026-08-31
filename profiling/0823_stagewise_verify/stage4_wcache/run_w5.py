#!/usr/bin/env python3
"""W5: both layouts x 5 cache configs x 4 layers x 5 samples = 200 runs.

The question this answers is NOT "does split_cin fix the L1", which W4 and the
C3 control already settle. It is whether the L1 win pays for what the layout
does to the L2, since a line-id relabelling is global and the L2 reads the same
ids.

C3 is the running assertion. It is fully associative, so `n_cin_lo` resolves to
1 and the flatten becomes a pure permutation: the two layouts MUST produce
identical counters. Any C3 pair that differs fails the whole run, because it
would mean the difference seen at C2, C4, C5 and C6 is partly implementation
noise rather than placement.

One row per run, with tag/sample/config prepended to the 93-column schema so a
row identifies itself without a join.
"""
import csv, itertools, json, pathlib, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BIN  = ROOT / "src/wcache/native/build/release/wcache_run"
CFGS = HERE / "inputs/configs"
STRM = HERE / "inputs/streams"
OUT  = HERE / "outputs"
SCRATCH = OUT / "_cfg"

TAGS    = ["V8", "V9", "R9", "R16"]
SAMPLES = range(5)
CONFIGS = ["C2", "C3", "C4", "C5", "C6"]
LAYOUTS = ["block_pack", "split_cin"]

# Columns that are expected to differ between two runs of the same point, so
# the C3 assertion must ignore them: two are identity, one is wall clock, and
# cin_lo_blocks is the config cell whose whole job is to differ.
IGNORE = {"run_id", "git_commit", "sim_wall_seconds", "cin_lo_blocks", "layout"}

def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)

    rows, header = [], None
    t0 = time.time()
    n = 0
    total = len(TAGS) * len(SAMPLES) * len(CONFIGS) * len(LAYOUTS)
    for tag, s, cfg, layout in itertools.product(TAGS, SAMPLES, CONFIGS, LAYOUTS):
        d = json.load(open(CFGS / f"{cfg}.json"))
        d["layout"] = layout
        p = SCRATCH / f"{cfg}_{layout}.json"
        json.dump(d, open(p, "w"))

        wcts = STRM / f"{tag}_s0000{s}.wcts"
        out = subprocess.run(
            [str(BIN), "--config", str(p), "--trace", str(wcts),
             "--arm", "cache", "--tier", "baseline",
             "--run-id", f"w5-{tag}-s{s}-{cfg}-{layout}", "--header"],
            capture_output=True, text=True, check=True).stdout
        a, b = list(csv.reader(out.splitlines()))
        header = a
        r = dict(zip(a, b))
        r["_tag"], r["_sample"], r["_config"] = tag, str(s), cfg
        rows.append(r)
        n += 1
        if n % 20 == 0:
            print(f"  {n}/{total}  {time.time()-t0:.0f}s", flush=True)

    cols = ["_tag", "_sample", "_config"] + header
    with open(OUT / "w5_grid.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])

    # --- the C3 control, checked on every (layer, sample) pair -----------------
    idx = {(r["_tag"], r["_sample"], r["_config"], r["layout"]): r for r in rows}
    bad = []
    for tag in TAGS:
        for s in SAMPLES:
            a = idx[(tag, str(s), "C3", "block_pack")]
            b = idx[(tag, str(s), "C3", "split_cin")]
            diff = [c for c in header if c not in IGNORE and a[c] != b[c]]
            if diff:
                bad.append(f"C3 {tag} s{s} differs on {diff}")
    print(f"\nC3 control: {len(TAGS)*len(SAMPLES)} pairs, "
          f"{'ALL IDENTICAL' if not bad else str(len(bad)) + ' FAILED'}")
    for x in bad:
        print("  FAIL " + x)

    # --- the headline, averaged over the 5 samples ----------------------------
    def mean(tag, cfg, layout, col, cast=float):
        v = [cast(idx[(tag, str(s), cfg, layout)][col]) for s in SAMPLES]
        return sum(v) / len(v)

    print(f"\n{'cfg':4s} {'layer':5s} {'l1_hit_rate':>22s}   {'dram_bytes':>25s}   {'total_cycles':>27s}")
    print(f"{'':4s} {'':5s} {'block_pack':>10s} {'split_cin':>11s}   "
          f"{'block_pack':>12s} {'split_cin':>12s}   {'block_pack':>12s} {'split_cin':>12s} {'delta':>7s}")
    for cfg in CONFIGS:
        for tag in TAGS:
            h0, h1 = mean(tag, cfg, "block_pack", "l1_hit_rate"), mean(tag, cfg, "split_cin", "l1_hit_rate")
            d0, d1 = mean(tag, cfg, "block_pack", "dram_bytes", int), mean(tag, cfg, "split_cin", "dram_bytes", int)
            c0, c1 = mean(tag, cfg, "block_pack", "total_cycles", int), mean(tag, cfg, "split_cin", "total_cycles", int)
            print(f"{cfg:4s} {tag:5s} {h0:10.6f} {h1:11.6f}   "
                  f"{d0:12,.0f} {d1:12,.0f}   {c0:12,.0f} {c1:12,.0f} {100*(c1-c0)/c0:+6.1f}%")
        print()

    print(f"{n} runs in {time.time()-t0:.0f}s -> {OUT/'w5_grid.csv'}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
