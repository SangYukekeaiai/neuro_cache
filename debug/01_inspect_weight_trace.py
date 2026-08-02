"""Stage 2 check: the generated tiny sample's weight_addresses.

Prints every tile's weight_addresses in full, checks each address stays
inside the tiny layer's declared bounds, and checks the whole sample
against the hand-derived table in log/2026-07-29-debug-pipeline-plan.md
(4 tiles in raster order (0,0),(0,1),(1,0),(1,1), 3 non-silent lines
each, those exact tuples in that order). Exits non-zero on any failure.
"""

import argparse
import gzip
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "debug" / "weight_traces" / "loas" / "tiny" / "layer_00" / "sample_00000.json.gz"

# Plan lines 216-221: one row per output-pixel tile, raster order, each
# entry (kh, kw, cin, cout_start, cout_end) in (kh asc, kw asc) order.
EXPECTED_TILES = (
    ((0, 0), ((1, 1, 0, 0, 4), (2, 1, 0, 0, 4), (2, 2, 0, 0, 4))),
    ((0, 1), ((1, 0, 0, 0, 4), (2, 0, 0, 0, 4), (2, 1, 0, 0, 4))),
    ((1, 0), ((0, 1, 0, 0, 4), (1, 1, 0, 0, 4), (1, 2, 0, 0, 4))),
    ((1, 1), ((0, 0, 0, 0, 4), (1, 0, 0, 0, 4), (1, 1, 0, 0, 4))),
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", default=str(SAMPLE))
    args = p.parse_args()

    with gzip.open(args.sample, "rt") as fh:
        data = json.load(fh)
    dims = data["workload_dims"]
    tiles = [[tuple(a) for a in t["weight_addresses"]] for t in data["tiles"]]

    failures = []

    def check(ok: bool, message: str) -> None:
        print(("  ok   " if ok else "  FAIL ") + message)
        if not ok:
            failures.append(message)

    print(f"{args.sample}")
    print(f"  arch={data['arch']} layer={data['layer_name']} sample={data['sample_idx']}")
    print(f"  workload_dims={dims}")
    print(f"  tiles: {len(tiles)}")
    for i, addrs in enumerate(tiles):
        print(f"  tile {i}: {len(addrs)} weight_addresses")
        for a in addrs:
            print(f"    (kh={a[0]}, kw={a[1]}, cin={a[2]}, cout_start={a[3]}, cout_end={a[4]})")

    print("bounds (kh<KH, kw<KW, cin<CIN, 0<=cout_start<cout_end<=COUT):")
    in_bounds = all(
        0 <= a[0] < dims["KH"] and 0 <= a[1] < dims["KW"] and 0 <= a[2] < dims["CIN"]
        and 0 <= a[3] < a[4] <= dims["COUT"]
        for addrs in tiles for a in addrs
    )
    check(in_bounds, f"every address inside KH={dims['KH']} KW={dims['KW']} "
                     f"CIN={dims['CIN']} COUT={dims['COUT']}")

    print("plan table (lines 216-221):")
    check(len(tiles) == len(EXPECTED_TILES), f"tile count == {len(EXPECTED_TILES)}, got {len(tiles)}")
    for i, (pixel, expected) in enumerate(EXPECTED_TILES):
        got = tuple(tiles[i]) if i < len(tiles) else ()
        check(got == expected, f"tile {i} (ho,wo)={pixel}: {list(expected)}"
                               + ("" if got == expected else f", got {list(got)}"))

    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        return 1
    print("PASSED: all bounds and plan-table checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
