"""Cut an N-sample subset out of a captured LoAS input trace.

The full captures are 10,000 CIFAR-10 samples per layer and 25.8 GB across
both workloads, which is why they lived outside the repo in the sibling
capture repo `/u/yyu9/neuro_cache_trace/`. That folder was deleted between
the 2026-08-11 and 2026-08-12 home snapshots; the data is recoverable from
`/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/`
until that snapshot rolls off, roughly 30 days after it was taken.

This script is the fold: it takes N samples chosen by a seeded RNG and writes
them into the repo, where 5 samples is 13.6 MB rather than 25.8 GB.

Two things it must get right, both of which are silent if missed:

  1. `meta.json`'s per-layer shape is VALIDATED by
     `archmodels.trace.load_layer_trace`, which throws when the array's shape
     and the declared shape disagree. So the declared `B` is rewritten to N.
  2. The SAME sample indices are used for every layer of every workload. A
     per-layer draw would mean layer 2 held different CIFAR-10 images than
     layer 1, and the reconstruction walks the layers of one network as one
     forward pass, so the subset has to be a subset of IMAGES, not of arrays.

The output directory is named for what it holds (`vgg16_T4_n5`), never
`vgg16_T4_all`: a directory named "all" holding 5 of 10,000 samples is the
kind of trap that reads as a result later. The seed and the chosen indices go
into `meta.json` so the subset can be reproduced or extended.

Usage:
    conda run -n base python scripts/subset_input_traces.py \
        --src  /u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/input_trace/loas \
        --dest input_trace/loas --n 5 --seed 0
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np

DEFAULT_SRC = pathlib.Path(
    "/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC"
    "/neuro_cache_trace/input_trace/loas"
)
DEFAULT_DEST = pathlib.Path("input_trace/loas")
DEFAULT_CAPTURES = ["vgg16_T4_all", "resnet19_T4_all"]


def subset_one(src_dir: pathlib.Path, dest_dir: pathlib.Path, n: int, seed: int) -> dict:
    with open(src_dir / "meta.json") as fh:
        meta = json.load(fh)

    n_samples = meta["n_samples"]
    if n > n_samples:
        raise ValueError(f"{src_dir}: asked for {n} of only {n_samples} samples")

    # Sorted so the subset preserves the capture's own sample order, which keeps
    # index i of the subset traceable back to `indices[i]` of the capture.
    rng = np.random.default_rng(seed)
    indices = sorted(int(i) for i in rng.choice(n_samples, size=n, replace=False))

    dest_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for layer, shape in meta["layers"].items():
        src = src_dir / f"{layer}.npy"
        # mmap, so a 2.6 GB layer is never resident: the sample axis is axis 1
        # of a C-contiguous array, so one sample is a handful of contiguous
        # blocks and only those pages are ever touched.
        arr = np.load(src, mmap_mode="r")
        if list(arr.shape) != list(shape):
            raise ValueError(f"{src}: shape {arr.shape} disagrees with meta.json {shape}")
        out = np.ascontiguousarray(arr[:, indices])
        np.save(dest_dir / f"{layer}.npy", out)
        meta["layers"][layer] = list(out.shape)
        written += out.nbytes
        print(f"  {layer:32s} {str(tuple(shape)):26s} -> {str(out.shape):22s} "
              f"{out.nbytes/1e6:7.2f} MB")

    meta["n_samples"] = n
    # Provenance, so the subset is never mistaken for the capture and can be
    # reproduced or widened without guessing how it was made.
    meta["subset"] = {
        "of": src_dir.name,
        "n": n,
        "seed": seed,
        "sample_indices": indices,
        "selected_by": "numpy.random.default_rng(seed).choice(n_samples, n, replace=False), sorted",
        "made_by": "scripts/subset_input_traces.py",
    }
    with open(dest_dir / "meta.json", "w") as fh:
        json.dump(meta, fh, indent=1)
        fh.write("\n")
    return {"dir": dest_dir.name, "bytes": written, "indices": indices}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=pathlib.Path, default=DEFAULT_SRC,
                    help="directory holding the full captures (default: the 2026-08-11 snapshot)")
    ap.add_argument("--dest", type=pathlib.Path, default=DEFAULT_DEST,
                    help="where the subsets are written (default: input_trace/loas)")
    ap.add_argument("--captures", nargs="+", default=DEFAULT_CAPTURES,
                    help="capture directory names under --src")
    ap.add_argument("--n", type=int, default=5, help="samples to keep (default: 5)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed (default: 0)")
    args = ap.parse_args()

    if not args.src.is_dir():
        print(f"source not found: {args.src}", file=sys.stderr)
        print("If the snapshot has rolled off, list what is left with: "
              "ls /u/yyu9/.snapshot/", file=sys.stderr)
        return 1

    total = 0
    for name in args.captures:
        # `_all` means all 10,000 samples, so the subset must not inherit the name.
        dest_name = name.replace("_all", "") + f"_n{args.n}"
        print(f"=== {name} -> {dest_name}")
        r = subset_one(args.src / name, args.dest / dest_name, args.n, args.seed)
        total += r["bytes"]
        print(f"  samples {r['indices']}  ({r['bytes']/1e6:.1f} MB)")
    print(f"\ntotal {total/1e6:.1f} MB in {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
