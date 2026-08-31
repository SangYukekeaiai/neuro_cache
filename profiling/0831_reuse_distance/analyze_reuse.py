#!/usr/bin/env python3
"""Reuse-distance analysis: the CDF, the hit-rate curve, V2, V3, and the finding.

Plan unit U5 of log/2026-08-31-reuse-distance-plan.md.

The curve is read straight off the histogram: a reference hits in a
fully-associative LRU cache of N lines exactly when its distance is < N, and a
cold reference never hits, so

    hit_rate(N) = (references with distance < N) / (all references)

Cold stays in the denominator, so this is comparable to a measured hit rate
rather than to a warm-cache idealisation.

WHAT THE PREDICTION IS A PREDICTION OF. Stack distance predicts a
FULLY-ASSOCIATIVE LRU cache and nothing else. V2 and V3 therefore validate it
against fully-associative RUNS of the engine, which is the only comparison that
can confirm or refute the arithmetic. Comparing it to the swept 8-way L1 and
16-way L2 is a second and separate question, and answering it is what turned up
the finding in section 4.

The L1 is PRIVATE, so its curve is the reference-weighted mean over the sixteen
per-core curves rather than one curve over a pooled stack. The L2 is shared and
has one curve.
"""
import collections
import csv
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT  = HERE / "outputs"
RUN  = ROOT / "src/wcache/native/build/release/wcache_run"
STRM = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/inputs/streams"
LINE_BYTES = 64
TAGS = ["V8", "V9", "R9", "R16"]

BEST = {
    "cout_block": 4, "weight_bytes": 1, "layout": "khkw_split",
    "l1_size_bytes": 16384, "l1_assoc": 8,
    "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32,
    "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
    "cin_block": 16, "l2_banks": 1,
    "prefetch_policy": "none", "prefetch_distance": 0,
}


def engine(tag, sample=0, **over):
    cfg = dict(BEST, **over)
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "c.json"
        p.write_text(json.dumps(cfg))
        r = subprocess.run([str(RUN), "--config", str(p),
                            "--trace", str(STRM / f"{tag}_s{sample:05d}.wcts"),
                            "--run-id", "an", "--header"],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{tag}: {r.stderr.strip().splitlines()[-1]}")
    rows = list(csv.reader(r.stdout.splitlines()))
    return dict(zip(rows[0], rows[1]))


def load():
    h = collections.defaultdict(dict)
    for r in csv.DictReader((OUT / "reuse_hist.csv").open()):
        h[(r["_tag"], int(r["_sample"]), r["level"], int(r["core"]))][int(r["distance"])] = int(r["count"])
    return h


def merged(hist, tag, sample, level):
    out = collections.Counter()
    for (t, s, lv, _c), b in hist.items():
        if (t, s, lv) == (tag, sample, level):
            out.update(b)
    return dict(out)


def curve(buckets, n_lines):
    total = sum(buckets.values())
    if total == 0:
        return 0.0
    return sum(c for d, c in buckets.items() if 0 <= d < n_lines) / total


def pct(x):
    return f"{100*x:6.2f}%"


def main():
    hist = load()
    report = {}

    # ------------------------------------------------------------ 1. shape --
    print("=" * 86)
    print("1. THE DISTRIBUTIONS -- where the mass actually sits (sample 0)")
    print("=" * 86)
    shapes = []
    for tag in TAGS:
        for level in ("l1", "l2"):
            b = merged(hist, tag, 0, level)
            total, cold = sum(b.values()), b.get(-1, 0)
            finite = {d: c for d, c in b.items() if d >= 0}
            mx = max(finite) if finite else None
            print(f"  {tag:>4} {level}: {total:>9,} refs, cold {cold:>7,} ({pct(cold/total)}), "
                  f"{len(finite):>3} distinct distances, max distance "
                  f"{mx if mx is not None else 'n/a'}")
            top = sorted(finite.items(), key=lambda kv: -kv[1])[:4]
            if top:
                print("        " + "  ".join(f"d={d}: {pct(c/total)}" for d, c in top))
            shapes.append({"layer": tag, "level": level, "refs": total, "cold": cold,
                           "n_distances": len(finite), "max_distance": mx})
    report["shape"] = shapes

    # ------------------------------------- 2. V2: the L1, against fully-assoc --
    print()
    print("=" * 86)
    print("2. V2 -- L1 prediction against a MEASURED fully-associative L1 (16 KB, 256 ways)")
    print("=" * 86)
    print(f"  {'layer':>5} {'predicted':>11} {'measured FA':>13} {'delta':>9}")
    v2, v2_ok = [], True
    for tag in TAGS:
        p = curve(merged(hist, tag, 0, "l1"), 256)
        m = float(engine(tag, l1_assoc=256)["l1_hit_rate"])
        ok = abs(p - m) < 5e-4
        v2_ok &= ok
        print(f"  {tag:>5} {pct(p):>11} {pct(m):>13} {pct(p-m):>9}  "
              f"{'MATCH' if ok else 'MISMATCH'}")
        v2.append({"layer": tag, "predicted": round(p, 6), "measured_fa": round(m, 6),
                   "match": ok})
    report["v2"] = {"rows": v2, "pass": v2_ok}

    # ------------------------------------- 3. V3: the L2, against fully-assoc --
    print()
    print("=" * 86)
    print("3. V3 -- L2 prediction against a MEASURED fully-associative L2, by capacity")
    print("=" * 86)
    sizes = [2**18, 2**19, 2**20, 2**22]
    print(f"  {'layer':>5} {'':>10} " + " ".join(f"{s//1024:>6} KB" for s in sizes))
    v3, v3_ok = [], True
    for tag in TAGS:
        pred = [curve(merged(hist, tag, 0, "l2"), s // LINE_BYTES) for s in sizes]
        meas = [float(engine(tag, l2_size_bytes=s, l2_assoc=s // LINE_BYTES)["l2_hit_rate"])
                for s in sizes]
        ok = all(abs(p - m) < 5e-4 for p, m in zip(pred, meas))
        v3_ok &= ok
        print(f"  {tag:>5} {'predicted':>10} " + " ".join(f"{pct(p):>9}" for p in pred))
        print(f"  {'':>5} {'measured':>10} " + " ".join(f"{pct(m):>9}" for m in meas)
              + f"   {'MATCH' if ok else 'MISMATCH'}")
        v3.append({"layer": tag, "sizes": sizes,
                   "predicted": [round(p, 6) for p in pred],
                   "measured_fa": [round(m, 6) for m in meas], "match": ok})
    report["v3"] = {"rows": v3, "pass": v3_ok}

    # --------------------------------------------------------- 4. the finding --
    print()
    print("=" * 86)
    print("4. THE FINDING -- the swept caches are losing to CONFLICT, not capacity")
    print("=" * 86)
    print("   The 2026-08-28 artifact read the L2's flat 0.00% as a capacity cliff and")
    print("   concluded 4 MB was needed. The distances say the largest L2 reuse is only")
    print("   ~3,071 lines, so 256 KB should suffice. Associativity at FIXED size decides it.")
    print()
    print(f"  {'layer':>5} {'L2 512 KB 16-way':>17} {'L2 512 KB 64-way':>17} "
          f"{'L2 4 MB 16-way':>16} {'cycles 16w':>11} {'cycles 64w':>11} {'gain':>7}")
    finding = []
    for tag in TAGS:
        a = engine(tag)                                     # the swept point
        b = engine(tag, l2_assoc=64)                        # same size, more ways
        c = engine(tag, l2_size_bytes=2**22)                # the artifact's prescription
        ca, cb, cc = (int(x["total_cycles"]) for x in (a, b, c))
        gain = 1 - cb / ca
        print(f"  {tag:>5} {pct(float(a['l2_hit_rate'])):>17} "
              f"{pct(float(b['l2_hit_rate'])):>17} {pct(float(c['l2_hit_rate'])):>16} "
              f"{ca:>11,} {cb:>11,} {gain:>6.1%}")
        finding.append({"layer": tag,
                        "l2_512k_16way": {"hit": round(float(a["l2_hit_rate"]), 6), "cycles": ca},
                        "l2_512k_64way": {"hit": round(float(b["l2_hit_rate"]), 6), "cycles": cb},
                        "l2_4m_16way":   {"hit": round(float(c["l2_hit_rate"]), 6), "cycles": cc},
                        "cycle_gain_from_ways": round(gain, 6)})
    report["finding_l2_conflict"] = finding

    print()
    print("   And the L1 runs the other way: the 8-way L1 BEATS fully-associative LRU,")
    print("   which is the khkw_split set index doing exactly what it was built for.")
    print()
    print(f"  {'layer':>5} {'8-way (swept)':>14} {'fully-assoc':>13} {'set-assoc wins by':>18}")
    l1f = []
    for tag in TAGS:
        a = float(engine(tag)["l1_hit_rate"])
        f = float(engine(tag, l1_assoc=256)["l1_hit_rate"])
        print(f"  {tag:>5} {pct(a):>14} {pct(f):>13} {pct(a-f):>18}")
        l1f.append({"layer": tag, "eight_way": round(a, 6), "fully_assoc": round(f, 6),
                    "set_assoc_advantage": round(a - f, 6)})
    report["finding_l1_set_index"] = l1f

    # ------------------------------------------------- 5. the curve and knees --
    samples = sorted({s for (_t, s, _l, _c) in hist})
    with (OUT / "hit_rate_curve.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["layer", "level", "cache_bytes", "cache_lines", "predicted_hit_rate"])
        for tag in TAGS:
            for level in ("l1", "l2"):
                for e in range(0, 25):
                    n = 2 ** e
                    r = sum(curve(merged(hist, tag, s, level), n) for s in samples) / len(samples)
                    w.writerow([tag, level, n * LINE_BYTES, n, round(r, 6)])

    print()
    print("=" * 86)
    print("5. THE KNEE -- smallest fully-associative cache reaching 99% of its ceiling")
    print("=" * 86)
    knees = []
    for tag in TAGS:
        for level in ("l1", "l2"):
            b = merged(hist, tag, 0, level)
            ceiling = 1 - b.get(-1, 0) / sum(b.values())
            knee = next((2**e for e in range(25)
                         if ceiling > 0 and curve(b, 2**e) >= 0.99 * ceiling), None)
            where = f"{knee*LINE_BYTES//1024} KB ({knee} lines)" if knee else "no reuse to capture"
            print(f"  {tag:>4} {level}: ceiling {pct(ceiling)}, knee at {where}")
            knees.append({"layer": tag, "level": level, "ceiling": round(ceiling, 6),
                          "knee_lines": knee,
                          "knee_bytes": knee * LINE_BYTES if knee else None})
    report["knees"] = knees

    (OUT / "analysis.json").write_text(json.dumps(report, indent=1))
    print(f"\nwrote {OUT/'hit_rate_curve.csv'} and {OUT/'analysis.json'}")
    print(f"V2: {'PASS' if v2_ok else 'FAIL'}    V3: {'PASS' if v3_ok else 'FAIL'}")
    return 0 if (v2_ok and v3_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
