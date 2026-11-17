#!/usr/bin/env python3
"""S1 driver for the scheduler-only scaling experiment (T76).

Same shape as ../gen_inputs.py: thin wrapper over wt_gen_inputs_snapshot,
one output dir per point under outputs/s1/. Only the Gurobi solve matters
here; the downstream trace stages are never run.
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import wt_gen_inputs_snapshot as wt  # noqa: E402  (frozen copy in ../)

wt.CAPTURE_RELATIVE_DIRS = ("B09/loas_vgg16_T4_n500",)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--point", action="append",
                    help="restrict to {arch}_{side}_x{m} names")
    ap.add_argument("--allow-bridge-violations", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--conda-env", default="base")
    ap.add_argument("--conda-exe", default="conda")
    ap.add_argument("--trace-root", default=None,
                    help="override capture root (e.g. on a non-Delta host)")
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
            "--arch-yaml", str((HERE / pt["arch_yaml"]).resolve()),
            "--mapspace-dir", str((HERE / pt["mapspace_dir"]).resolve()),
            "--output-dir", str(out),
        ]
        if args.smoke:
            argv.append("--smoke")
        if args.dry_run:
            argv.append("--dry-run")
        argv.extend(("--conda-env", args.conda_env))
        argv.extend(("--conda-exe", args.conda_exe))
        if args.trace_root:
            argv.extend(("--trace-root", args.trace_root))
        if args.allow_bridge_violations:
            argv.append("--allow-bridge-violations")
        print(f"=== T76 S1 {name} ===", flush=True)
        rc = wt.main(argv)
        if rc != 0:
            failures.append(name)
            print(f"!!! {name} failed rc={rc}", flush=True)
    if failures:
        print("FAILED points:", ", ".join(failures))
        return 1
    print("T76 S1 complete for all requested points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
