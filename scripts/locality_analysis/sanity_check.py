#!/usr/bin/env python3
"""Milestone 1 - parser + sanity check (plan Sec 1.2, the de-risk step).

Loads one (arch, network, layer, sample) trace and verifies the assumptions the
rest of the harness relies on, then prints a pass/fail report:

  1. `dram_i` is contiguous 0 .. dram_num_steps-1.
  2. Tile concatenation (file) order matches ascending `dram_i` order.
  3. Every weight address stays in-bounds of `workload_dims` (KH, KW, CIN, COUT).
  4. Width-clamping rule holds: cout_end - cout_start == min(nominal, COUT), on a
     couple of small-COUT and large-COUT layers across all archs (plan Sec 1.1).

Usage (from project root):
    python scripts/locality_analysis/sanity_check.py
    python scripts/locality_analysis/sanity_check.py --arch loas --layer layer_12_features_40
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from locality_analysis.trace_io import (  # noqa: E402
    ARCHS, NOMINAL_WIDTH, list_layers, load_raw,
)

# Two layers exercising both the clamped (small COUT) and unclamped (large COUT)
# branches of the width rule, for the width-rule check (4).
WIDTH_CHECK_LAYERS = ["layer_01_features_3", "layer_12_features_40"]


def check_dram_contiguous(raw: dict) -> tuple[bool, str]:
    dram_is = [t["dram_i"] for t in raw["tiles"]]
    expected = list(range(raw["dram_num_steps"]))
    ok = sorted(dram_is) == expected
    detail = (
        f"{len(dram_is)} tiles, dram_num_steps={raw['dram_num_steps']}, "
        f"set == 0..N-1: {ok}"
    )
    return ok, detail


def check_concat_order(raw: dict) -> tuple[bool, str]:
    dram_is = [t["dram_i"] for t in raw["tiles"]]
    ok = dram_is == sorted(dram_is)
    detail = f"file order ascending in dram_i: {ok} (first: {dram_is[:5]})"
    return ok, detail


def check_in_bounds(raw: dict) -> tuple[bool, str]:
    d = raw["workload_dims"]
    KH, KW, CIN, COUT = d["KH"], d["KW"], d["CIN"], d["COUT"]
    n_addrs = 0
    violations = 0
    for tile in raw["tiles"]:
        for kh, kw, cin, cs, ce in tile["weight_addresses"]:
            n_addrs += 1
            if not (0 <= kh < KH and 0 <= kw < KW and 0 <= cin < CIN
                    and 0 <= cs < ce <= COUT):
                violations += 1
    ok = violations == 0
    detail = (
        f"{n_addrs} addresses checked against (KH={KH}, KW={KW}, "
        f"CIN={CIN}, COUT={COUT}); violations: {violations}"
    )
    return ok, detail


def check_width_rule(network: str) -> tuple[bool, list[str]]:
    ok = True
    lines = []
    for arch in ARCHS:
        available = set(list_layers(arch, network))
        for layer in WIDTH_CHECK_LAYERS:
            if layer not in available:
                lines.append(f"    {arch:11s} {layer:22s} SKIP (absent)")
                continue
            raw = load_raw(arch, network, layer, 0)
            COUT = raw["workload_dims"]["COUT"]
            widths = {ce - cs for t in raw["tiles"] for (_a, _b, _c, cs, ce)
                      in t["weight_addresses"]}
            expected = min(NOMINAL_WIDTH[arch], COUT)
            passed = widths == {expected}
            ok = ok and passed
            tag = "clamped" if NOMINAL_WIDTH[arch] > COUT else "unclamped"
            lines.append(
                f"    {arch:11s} {layer:22s} COUT={COUT:4d} "
                f"observed={sorted(widths)} expected={expected} "
                f"({tag}) {'PASS' if passed else 'FAIL'}"
            )
    return ok, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arch", default="gustavsnn")
    parser.add_argument("--network", default="vgg16_T4_all")
    parser.add_argument("--layer", default="layer_01_features_3")
    parser.add_argument("--sample", type=int, default=0)
    args = parser.parse_args()

    print(f"\n=== Milestone 1 sanity check ===")
    print(f"file: {args.arch}/{args.network}/{args.layer}/sample_{args.sample:05d}\n")
    raw = load_raw(args.arch, args.network, args.layer, args.sample)

    results = []
    for name, (ok, detail) in [
        ("[1] dram_i contiguous 0..N-1", check_dram_contiguous(raw)),
        ("[2] tile order == dram_i order", check_concat_order(raw)),
        ("[3] addresses in-bounds", check_in_bounds(raw)),
    ]:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        print(f"        {detail}")
        results.append(ok)

    print(f"\n[4] width-clamping rule (all archs x {len(WIDTH_CHECK_LAYERS)} layers):")
    ok4, lines = check_width_rule(args.network)
    for line in lines:
        print(line)
    print(f"{'PASS' if ok4 else 'FAIL'}  [4] width == min(nominal, COUT) everywhere")
    results.append(ok4)

    all_ok = all(results)
    print(f"\n=== {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'} ===\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
