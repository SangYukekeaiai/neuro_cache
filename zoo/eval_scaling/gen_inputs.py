#!/usr/bin/env python3
"""S1 driver for eval_scaling: solve schedules for every sweep point.

Thin wrapper over zoo/wt500_fig3cfg/gen_inputs.py restricted to the
loas_vgg16 capture, looping over the 10 (side, multiplier) points from
configs/sweep_config.json. Each point gets its own output dir under
outputs/s1/, fully separated from the wt500 campaign outputs.

Usage:
  conda run -n gurobi python zoo/eval_scaling/gen_inputs.py [--smoke] [--point single_x1 ...]
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wt_gen_inputs_snapshot as wt  # frozen copy, decoupled from wt500

# Restrict the campaign machinery to the one eval_scaling capture.
wt.CAPTURE_RELATIVE_DIRS = ("B09/loas_vgg16_T4_n500",)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="first layer only, per point")
    ap.add_argument("--point", action="append", help="restrict to side_xM points")
    ap.add_argument("--allow-bridge-violations", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--conda-env", default="gurobi")
    args = ap.parse_args()

    manifest = json.loads((HERE / "configs" / "sweep_config.json").read_text())
    failures = []
    for pt in manifest["points"]:
        name = f"{pt['arch']}_{pt['side']}_x{pt['multiplier']}"
        if args.point and name not in args.point:
            continue
        out = HERE / "outputs" / "s1" / pt["arch"] / f"{pt['side']}_x{pt['multiplier']}"
        argv = [
            "--arch", pt["arch"],
            "--arch-yaml", str(HERE / pt["arch_yaml"]),
            "--mapspace-dir", str(HERE / pt["mapspace_dir"]),
            "--output-dir", str(out),
        ]
        if args.smoke:
            argv.append("--smoke")
        if args.dry_run:
            argv.append("--dry-run")
        argv.extend(("--conda-env", args.conda_env))
        if args.allow_bridge_violations:
            argv.append("--allow-bridge-violations")
        print(f"=== S1 {name} ===", flush=True)
        rc = wt.main(argv)
        if rc != 0:
            failures.append(name)
            print(f"!!! {name} failed rc={rc}", flush=True)
    if failures:
        print("FAILED points:", ", ".join(failures))
        return 1
    print("S1 complete for all requested points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
