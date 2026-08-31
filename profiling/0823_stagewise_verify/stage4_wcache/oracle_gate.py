#!/usr/bin/env python3
"""W0: prove the 20 Stage 4 streams carry the timeline Stage 3 measured.

The oracle arm simulates no cache. `total_cycles` is set equal to
`tick_base_total`, which is read straight off the stream's tick timeline, so
the row is a readout of the trace and not of a machine. That makes it the
right instrument for one question and one only:

    does the .wcts stream agree with Stage 3 about how long each node computes?

Stage 3 measured `compute_per_node` from the SAME input traces through a
different program (eventsim). If the two agree on all 20 points, the stream
Stage 4 is about to replay is the one Stage 3 already reported on. If they
disagree anywhere, every Stage 4 number would be measured against a trace
nobody has validated, and that is worth finding before a sweep rather than
after.

Two of the four checks are schema checks and say so below; they are cheap and
they catch a row that shifted a column, which is the failure that would make
the other two pass for the wrong reason.
"""
import csv, json, pathlib, subprocess, sys

HERE   = pathlib.Path(__file__).resolve().parent
ROOT   = HERE.parents[2]   # .../neuro_cache; HERE is profiling/<run>/stage4_wcache
BIN    = ROOT / "src/wcache/native/build/release/wcache_run"
CFG    = HERE / "inputs/configs/C2.json"
STREAM = HERE / "inputs/streams"
OUT    = HERE / "outputs"
STAGE3 = ROOT / "profiling/0823_stagewise_verify/stage3_nocsim/outputs/stage3_results.json"

TAGS = ["V8", "V9", "R9", "R16"]

def main() -> int:
    truth = {}
    for r in json.load(open(STAGE3)):
        truth[(r["tag"], r["sample"])] = r["compute_per_node"]

    OUT.mkdir(exist_ok=True)
    rows, header = [], None
    for tag in TAGS:
        for s in range(5):
            wcts = STREAM / f"{tag}_s0000{s}.wcts"
            if not wcts.exists():
                print(f"missing {wcts}", file=sys.stderr)
                return 1
            out = subprocess.run(
                [str(BIN), "--config", str(CFG), "--trace", str(wcts),
                 "--oracle-only", "--arm", "spad_oracle", "--tier", "baseline",
                 "--run-id", f"w0-{tag}-s{s}", "--header"],
                capture_output=True, text=True, check=True).stdout
            a, b = list(csv.reader(out.splitlines()))
            header = a
            rows.append(dict(zip(a, b)))

    csv_path = OUT / "w0_oracle.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r[c] for c in header])

    bad = []
    print(f"{'tag':5s} {'s':>2s} {'tick_base_total':>16s} {'stage3':>10s}  {'':4s}")
    for i, tag in enumerate(TAGS):
        for s in range(5):
            r = rows[i * 5 + s]
            tb = int(r["tick_base_total"])
            want = truth[(tag, s)]

            # 1. schema: the oracle arm's identity, which oracle_row sets by
            #    construction. It fails only if a column shifted.
            if r["total_cycles"] != r["tick_base_total"] or r["stretch_cycles"] != "0":
                bad.append(f"{tag} s{s}: total_cycles/stretch are not the oracle identity")
            # 2. schema: no cache ran, so every memory counter is blank, not 0.
            for c in ("l1_hits", "l1_accesses", "l2_hits", "dram_accesses", "dram_bytes"):
                if r[c] != "":
                    bad.append(f"{tag} s{s}: {c} = {r[c]!r}, expected blank")
            # 3. THE check: cross-stage agreement on the timeline.
            mark = "ok" if tb == want else "MISMATCH"
            if tb != want:
                bad.append(f"{tag} s{s}: tick_base_total {tb} != Stage 3 {want}")
            print(f"{tag:5s} {s:2d} {tb:16d} {want:10d}  {mark}")

    # 4. THE second check: the 5 samples must actually differ, or "5 samples"
    #    is one sample copied five times and every later average is a fiction.
    print()
    for i, tag in enumerate(TAGS):
        v = [int(rows[i * 5 + s]["tick_base_total"]) for s in range(5)]
        spread = max(v) - min(v)
        print(f"{tag:5s} spread across the 5 samples: {spread}")
        if spread == 0:
            bad.append(f"{tag}: the 5 samples have identical timelines")

    print()
    if bad:
        for b in bad:
            print("FAIL " + b)
        return 1
    print(f"w0_oracle: OK, 20 rows, cross-stage agreement on all of them")
    print(f"           {csv_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
