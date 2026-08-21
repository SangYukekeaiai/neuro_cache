"""Solve exactly the (arch, layer) schedules the 16-core cache study needs.

`solve_schedules.py` solves every valid layer of every trace dir under a fixed
name -> YAML map, which is 93 solves here and uses the wrong arch files. This
solves the 12 the study actually uses, against configs/arch/<arch>_inst16.yaml.

Run from the repo root:
    conda run -n base python scripts/solve_inst16_subset.py \
        --trace-root /work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, "src")
import tracegen

ARCHS = ["loas", "ptb", "spinalflow"]

# The four layers of plan section 3.2, chosen by where their weight footprint
# sits against the shared L2 axis: 36 KB, 72 KB, 1125 KB, 2304 KB.
LAYERS = [
    ("vgg16_T4_all",    "layer_01_features_3"),
    ("vgg16_T4_all",    "layer_09_features_30"),
    ("resnet19_T4_all", "layer_01_layer1_0_conv1"),
    ("resnet19_T4_all", "layer_16_layer3_0_conv2"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-root", required=True, type=pathlib.Path)
    ap.add_argument("--cache-dir", default="outputs/schedules/inst16", type=pathlib.Path)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    metas = {}
    for trace_dir in {t for t, _ in LAYERS}:
        with open(args.trace_root / trace_dir / "meta.json") as fh:
            metas[trace_dir] = json.load(fh)

    ok = fail = skip = 0
    for arch in ARCHS:
        arch_yaml = f"configs/arch/{arch}_inst16.yaml"
        dataflow_yaml = f"configs/dataflow/{arch}.yaml"
        if not pathlib.Path(arch_yaml).exists():
            print(f"missing {arch_yaml}", file=sys.stderr)
            return 1
        for trace_dir, layer in LAYERS:
            out = args.cache_dir / arch / trace_dir / f"{layer}.json"
            if out.exists() and not args.force:
                print(f"  skip   {arch:11s} {trace_dir}/{layer}")
                skip += 1
                continue

            meta = metas[trace_dir]
            names = list(meta["layers"])
            i = names.index(layer)
            # COUT is the next layer's CIN; the last layer falls back to its own.
            next_cin = meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None

            t0 = time.time()
            try:
                art = tracegen.solve_and_cache_schedule(
                    arch, arch_yaml, dataflow_yaml, trace_dir, layer,
                    meta, next_cin, args.cache_dir,
                )
            except Exception as exc:
                print(f"  FAIL   {arch:11s} {trace_dir}/{layer}: {type(exc).__name__}: {exc}")
                fail += 1
                continue
            has = art.result.get("has_solution")
            dt = time.time() - t0
            print(f"  {'ok  ' if has else 'INFEASIBLE'} {arch:11s} {trace_dir}/{layer}  "
                  f"mode={art.mode} dram_steps={art.dram_num_steps} {dt:.1f}s")
            ok += 1 if has else 0
            fail += 0 if has else 1

    print(f"\nsolved {ok}, failed {fail}, skipped {skip}, of {len(ARCHS)*len(LAYERS)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
