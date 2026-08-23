#!/usr/bin/env python3
"""Recompute Stage 2's weight-trace row counts from the raw spikes, in NumPy.

The 0823 run described this check in outputs/RESULTS.md but never committed the
code, so the strongest result in that stage could not be re-run. This is that
check, written to stand on its own: it reads only the input .npy and the Stage 1
schedule, reimplements the emission rule from
src/archmodels/loas/LoASGen.h:66-119, and compares against what the generator
wrote. Nothing here imports the generator or the native bridge.

The rule, restated: a tile is one (ho, wo) output pixel for one COUT block. Its
core walks (kh, kw, cin) and emits one AddressRow per position whose input site
(cin, hin, win) fires at least once across the tile's T range, where
hin = ho + kh - (KH-1)//2 and positions outside the input plane are padding and
emit nothing. COUT never enters the test, so every core at one pixel emits the
same row count.

    conda run -n base python profiling/0823_stagewise_verify/stage2_weight_trace/verify_reconstruction.py
"""
from __future__ import annotations

import gzip
import json
import pathlib
import sys

import numpy as np

STAGE = pathlib.Path(__file__).resolve().parent
IN, OUT = STAGE / "inputs", STAGE / "outputs"
ARCH = "loas"
COMBO_TAG = "noc2MiB_node32kb"

COMBOS = [
    ("vgg16_T4_n5", "layer_08_features_27"),
    ("resnet19_T4_n5", "layer_09_layer2_0_conv2"),
    ("vgg16_T4_n5", "layer_09_features_30"),
    ("resnet19_T4_n5", "layer_16_layer3_0_conv2"),
]
SAMPLES = range(5)


def pixel_row_counts(arr: np.ndarray, KH: int, KW: int, HO: int, WO: int) -> np.ndarray:
    """Rows one core emits at each (ho, wo), for one sample [T, Cin, Hin, Win]."""
    _T, _Cin, Hin, Win = arr.shape
    # A site is non-silent when it fires at any t. The tile's T range is the
    # whole capture here, since the node tile carries T in full.
    fires = arr.any(axis=0)                       # [Cin, Hin, Win], bool
    pad_h, pad_w = (KH - 1) // 2, (KW - 1) // 2
    counts = np.zeros((HO, WO), dtype=np.int64)
    for ho in range(HO):
        for wo in range(WO):
            n = 0
            for kh in range(KH):
                hin = ho + kh - pad_h
                if not (0 <= hin < Hin):
                    continue                      # padding contributes nothing
                for kw in range(KW):
                    win = wo + kw - pad_w
                    if not (0 <= win < Win):
                        continue
                    n += int(fires[:, hin, win].sum())
            counts[ho, wo] = n
    return counts


def generated(path: pathlib.Path) -> dict:
    """Row total, mac_cycles total, and the per-core COUT blocks, from one trace."""
    with gzip.open(path, "rt") as fh:
        doc = json.load(fh)
    total = 0
    macs = 0
    cout_blocks: dict[int, set] = {}
    for tile in doc["tiles"]:
        macs += tile.get("mac_cycles", 0)
        for tick in tile["ticks"]:
            for core in tick["cores"]:
                rows = core["weight_addresses"]
                total += len(rows)
                if rows:
                    # A row is [kh, kw, cin, cout_start, cout_end].
                    blk = cout_blocks.setdefault(core["core_id"], set())
                    for r in rows:
                        blk.add((r[3], r[4]))
    return {"total_rows": total, "mac_cycles": macs, "tiles": len(doc["tiles"]),
            "cout_blocks": cout_blocks}


def main() -> int:
    failures = 0
    for trace_dir, layer in COMBOS:
        sched = json.loads((IN / "schedules" / ARCH / trace_dir / f"{layer}.json").read_text())
        p = sched["workload"]["problem"]
        KH, KW, HO, WO, COUT = p["KH"], p["KW"], p["HO"], p["WO"], p["COUT"]

        # Tile instances per output pixel, from the schedule alone: every COUT
        # channel is covered, and one core-tick owns node_spatial COUT of them.
        node_spatial = {f["dim"]: f["size"]
                        for f in sched["result"]["strategy"]["NodeLevel"]["spatial_split"]["factors"]}
        per_pixel = COUT // node_spatial["COUT"]

        arr5 = np.load(IN / "input_trace" / trace_dir / f"{layer}.npy", mmap_mode="r")
        print(f"\n=== {trace_dir}/{layer}")
        print(f"  KH{KH} KW{KW} CIN{p['CIN']} COUT{COUT} HO{HO} WO{WO} T{p['T']}, "
              f"node spatial COUT x{node_spatial['COUT']}, {per_pixel} tile instances per pixel")

        for s in SAMPLES:
            counts = pixel_row_counts(np.asarray(arr5[:, s]), KH, KW, HO, WO)
            want_rows = int(counts.sum()) * per_pixel
            # mac_cycles is the per-core count, summed over tiles; every core at
            # one pixel emits the same rows, so the max over cores is that count.
            want_macs = int(counts.sum()) * (per_pixel // 16)

            got = generated(OUT / "weight_traces" / ARCH / COMBO_TAG / trace_dir / layer
                            / f"sample_{s:05d}.json.gz")
            ok_rows = want_rows == got["total_rows"]
            ok_macs = want_macs == got["mac_cycles"]

            # The COUT partition: 16 cores, disjoint blocks, union = 0..COUT-1.
            blocks = got["cout_blocks"]
            spans = sorted(b for blks in blocks.values() for b in blks)
            covered = np.zeros(COUT, dtype=np.int64)
            for a, b in spans:
                covered[a:b] += 1
            ok_part = (len(blocks) == 16 and covered.min() >= 1
                       and len(set().union(*blocks.values())) == len(spans))

            flag = "ok" if (ok_rows and ok_macs) else "MISMATCH"
            failures += 0 if (ok_rows and ok_macs) else 1
            print(f"  s{s}  rows want {want_rows:>10,} got {got['total_rows']:>10,}  "
                  f"macs want {want_macs:>8,} got {got['mac_cycles']:>8,}  "
                  f"cores {len(blocks)}  {flag}")
            if s == 0:
                cover = "disjoint, complete" if ok_part else "OVERLAPPING OR INCOMPLETE"
                print(f"      COUT partition: {len(spans)} distinct blocks over {len(blocks)} "
                      f"cores, each channel covered {covered.min()}-{covered.max()}x, {cover}")

    print(f"\n{'all row and mac_cycles counts reproduce exactly' if not failures else str(failures) + ' MISMATCHES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
