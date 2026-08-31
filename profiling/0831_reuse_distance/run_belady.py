#!/usr/bin/env python3
"""Belady on the L2: five arms, the fixpoint iteration, and the checks.

Plan unit W4 of log/2026-08-31-belady-l2-plan.md.

THE FIXPOINT. Belady needs the L2 reference stream before it can run, and the
stream depends on when each core's misses arrive, which depends on the policy.
Each core's own L2 SEQUENCE is invariant (V4 plus non_inclusive; plan section 3),
so only the merge across the sixteen cores can shift. The driver therefore
iterates: build the oracle from run N's access log, run N+1 with it, and compare
the two logs. Identical logs mean the oracle was exact and the run is TRUE
Belady. That is check B3 and it is reported per layer, never assumed.
"""
import csv
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN  = ROOT / "src/wcache/native/build/release/wcache_run"
STRM = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/inputs/streams"
GRID = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/outputs/_khkw_grid/khkw_64b.json"
S3   = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/outputs/khkw_vs_stage3.csv"
OUT  = HERE / "outputs"

TAGS    = ["V8", "V9", "R9", "R16"]
SAMPLES = range(5)
MAX_ITERS = 4

BEST = {
    "cout_block": 4, "weight_bytes": 1, "layout": "khkw_split",
    "l1_size_bytes": 16384, "l1_assoc": 8,
    "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "cin_block": 16, "l2_banks": 1,
    "prefetch_policy": "none", "prefetch_distance": 0,
}

# Plan section 5. Arm E's assoc is filled in from l2_size_bytes at run time.
ARMS = [
    ("A_lru_16way",     {"l2_assoc": 16},                          "lru"),
    ("B_belady_16way",  {"l2_assoc": 16},                          "belady"),
    ("C_lru_64way",     {"l2_assoc": 64},                          "lru"),
    ("D_belady_64way",  {"l2_assoc": 64},                          "belady"),
    ("E_belady_fa",     {"l2_assoc": 524288 // 64},                "belady"),
    ("F_lru_fa",        {"l2_assoc": 524288 // 64},                "lru"),
]


def check_best():
    want = json.loads(GRID.read_text())[0]
    if want != BEST:
        raise SystemExit(f"BEST drifted from {GRID.name}[0]")


def engine(tag, sample, over, l2_policy, td, oracle=None, alog=None):
    cfg = dict(BEST, **over)
    cfg["l2_policy"] = l2_policy
    p = td / "cfg.json"
    p.write_text(json.dumps(cfg))
    cmd = [str(RUN), "--config", str(p),
           "--trace", str(STRM / f"{tag}_s{sample:05d}.wcts"),
           "--run-id", f"bel-{tag}-s{sample}", "--header"]
    if oracle: cmd += ["--l2-oracle", str(oracle)]
    if alog:   cmd += ["--access-log", str(alog)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag} s{sample} {l2_policy}: "
                           f"{r.stderr.strip().splitlines()[-1][:200]}")
    rows = list(csv.reader(r.stdout.splitlines()))
    return dict(zip(rows[0], rows[1]))


def l2_digest(path):
    """A digest of the L2 records only, which is what the oracle is built from."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.read(8)
        while True:
            b = f.read(1 << 16)
            if not b:
                break
            for i in range(0, len(b) - 7, 8):
                if b[i] == 1:                       # level == L2
                    h.update(b[i:i + 8])
    return h.hexdigest()[:16]


def one(tag, sample, name, over, policy):
    """One arm. LRU runs once; Belady iterates to a fixpoint."""
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        if policy == "lru":
            row = engine(tag, sample, over, "lru", td, alog=td / "a.log")
            return row, {"iters": 1, "converged": True, "digests": [l2_digest(td / "a.log")]}

        # Seed from an LRU run at the SAME geometry, then iterate.
        seed = td / "seed.log"
        engine(tag, sample, over, "lru", td, alog=seed)
        digests, oracle = [l2_digest(seed)], seed
        row = None
        for it in range(MAX_ITERS):
            out = td / f"i{it}.log"
            row = engine(tag, sample, over, "belady", td, oracle=oracle, alog=out)
            d = l2_digest(out)
            digests.append(d)
            if d == digests[-2]:
                # The stream this run produced equals the one its oracle was
                # built from, so the oracle was exact: this is true Belady.
                return row, {"iters": it + 1, "converged": True, "digests": digests}
            oracle = out
        return row, {"iters": MAX_ITERS, "converged": False, "digests": digests}


def stage3():
    out = {}
    for r in csv.DictReader(S3.open()):
        out[r["tag"]] = float(r["stage3_total_cycles"])
    return out


def preview():
    print("=" * 80)
    print("PREVIEW -- Belady on the L2, nothing has executed yet")
    print("=" * 80)
    print(f"  base config : khkw_split, 64 B lines, L1 16 KB 8-way, L2 512 KB, 1 bank")
    print(f"                latencies 0/2/24, prefetch none, verified against {GRID.name}[0]")
    print(f"  arms        :")
    for name, over, pol in ARMS:
        ways = over["l2_assoc"]
        print(f"                {name:<16} L2 512 KB {ways:>5}-way  policy {pol}")
    print(f"  layers      : {', '.join(TAGS)}   samples: {len(list(SAMPLES))} each")
    print(f"  runs        : {len(ARMS)}x{len(TAGS)}x{len(list(SAMPLES))} arms, "
          f"Belady arms iterate up to {MAX_ITERS}x plus one LRU seed")
    print(f"  produces    : outputs/belady_runs.csv, outputs/belady_summary.csv")
    print(f"  checks      : B1 belady >= lru at same geometry")
    print(f"                B2 belady fully-assoc == cold-forced ceiling")
    print(f"                B3 the oracle converges (L2 log identical across iterations)")
    print(f"  baseline    : nocsim stage3_total_cycles from {S3.name}")
    print("=" * 80)


def main():
    check_best()
    preview()
    OUT.mkdir(parents=True, exist_ok=True)
    s3 = stage3()
    rows, t0 = [], time.time()

    for tag in TAGS:
        for sample in SAMPLES:
            for name, over, policy in ARMS:
                row, info = one(tag, sample, name, over, policy)
                row.update({"_tag": tag, "_sample": str(sample), "_arm": name,
                            "_policy": policy, "_l2_assoc": str(over["l2_assoc"]),
                            "_iters": str(info["iters"]),
                            "_converged": str(info["converged"])})
                rows.append(row)
            print(f"  {tag} s{sample}  done  ({time.time()-t0:.0f}s)", flush=True)

    cols = ["_tag", "_sample", "_arm", "_policy", "_l2_assoc", "_iters", "_converged"] + \
           [c for c in rows[0] if not c.startswith("_")]
    with (OUT / "belady_runs.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in rows: w.writerow([r[c] for c in cols])

    # ---------------------------------------------------------------- checks --
    def mean(tag, arm, col):
        v = [float(r[col]) for r in rows if r["_tag"] == tag and r["_arm"] == arm]
        return sum(v) / len(v)

    print("\n" + "=" * 80)
    print("B3 -- did the oracle converge?")
    print("=" * 80)
    bad = [r for r in rows if r["_policy"] == "belady" and r["_converged"] != "True"]
    for tag in TAGS:
        its = {int(r["_iters"]) for r in rows if r["_tag"] == tag and r["_policy"] == "belady"}
        conv = all(r["_converged"] == "True" for r in rows
                   if r["_tag"] == tag and r["_policy"] == "belady")
        print(f"  {tag:>4}: {'CONVERGED' if conv else 'DID NOT CONVERGE'}"
              f"   iterations {sorted(its)}")
    print(f"  B3: {'PASS' if not bad else f'FAIL on {len(bad)} runs'}")

    print("\n" + "=" * 80)
    print("B1 -- Belady is never worse than LRU at the same geometry")
    print("=" * 80)
    b1 = True
    for tag in TAGS:
        for lru_arm, bel_arm, ways in (("A_lru_16way", "B_belady_16way", 16),
                                       ("C_lru_64way", "D_belady_64way", 64),
                                       ("F_lru_fa", "E_belady_fa", 8192)):
            l, b = mean(tag, lru_arm, "l2_hit_rate"), mean(tag, bel_arm, "l2_hit_rate")
            ok = b >= l - 1e-9
            b1 &= ok
            print(f"  {tag:>4} {ways:>5}-way: lru {100*l:6.2f}%  belady {100*b:6.2f}%  "
                  f"{'ok' if ok else 'VIOLATION'}")
    print(f"  B1: {'PASS' if b1 else 'FAIL'}")

    print("\n" + "=" * 80)
    print("B2 -- Belady fully-associative equals the cold-forced ceiling")
    print("=" * 80)
    b2 = True
    for tag in TAGS:
        acc = mean(tag, "E_belady_fa", "l2_accesses")
        dram = mean(tag, "F_lru_fa", "dram_accesses")   # distinct lines at fully-assoc
        ceiling = 0.0 if acc == 0 else 1 - dram / acc
        got = mean(tag, "E_belady_fa", "l2_hit_rate")
        ok = abs(got - ceiling) < 5e-4
        b2 &= ok
        print(f"  {tag:>4}: ceiling {100*ceiling:6.2f}%   belady FA {100*got:6.2f}%  "
              f"{'MATCH' if ok else 'MISMATCH'}")
    print(f"  B2: {'PASS' if b2 else 'FAIL'}")

    # --------------------------------------------------------------- summary --
    with (OUT / "belady_summary.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["layer", "arm", "l2_assoc", "policy", "l2_hit_rate", "total_cycles",
                    "stage3_cycles", "vs_stage3", "converged", "iters"])
        for tag in TAGS:
            for name, over, policy in ARMS:
                hr, cyc = mean(tag, name, "l2_hit_rate"), mean(tag, name, "total_cycles")
                conv = all(r["_converged"] == "True" for r in rows
                           if r["_tag"] == tag and r["_arm"] == name)
                its = max(int(r["_iters"]) for r in rows
                          if r["_tag"] == tag and r["_arm"] == name)
                w.writerow([tag, name, over["l2_assoc"], policy, round(hr, 6),
                            round(cyc, 1), round(s3[tag], 1), round(s3[tag] / cyc, 4),
                            conv, its])

    print("\n" + "=" * 80)
    print("LATENCY -- LRU, Belady, and nocsim")
    print("=" * 80)
    print(f"  {'layer':>5} {'LRU 16w':>11} {'Belady 16w':>12} {'LRU 64w':>11} "
          f"{'Belady 64w':>12} {'nocsim':>10}")
    for tag in TAGS:
        print(f"  {tag:>5} {mean(tag,'A_lru_16way','total_cycles'):>11,.0f} "
              f"{mean(tag,'B_belady_16way','total_cycles'):>12,.0f} "
              f"{mean(tag,'C_lru_64way','total_cycles'):>11,.0f} "
              f"{mean(tag,'D_belady_64way','total_cycles'):>12,.0f} "
              f"{s3[tag]:>10,.0f}")

    print(f"\n{len(rows)} runs -> {OUT}  ({time.time()-t0:.0f}s)")
    return 0 if (b1 and b2 and not bad) else 1


if __name__ == "__main__":
    sys.exit(main())
