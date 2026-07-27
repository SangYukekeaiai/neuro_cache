#!/usr/bin/env python3
"""Backfill TileWeightTrace.tick_ids into already-generated weight-trace
files for LoAS, PTB, SpinalFlow, and Prosperity, without regenerating
them.

Safe to do by direct JSON patch ONLY for these four archs: each one's
event_to_ticks (src/archmodels/<arch>/address.py) is exactly
list(range(len(weight_addresses))), a pure function of the address count
already present in every file -- no trace/schedule/reconstruction needed.

GustavSNN is deliberately excluded: its ticks depend on the wave/submatrix
structure (piece_idx, per-submatrix line position) that only exists
inside GustavReconstructed during reconstruction and is not recoverable
from the flattened, already-persisted address list. GustavSNN's cached
samples need full regeneration, not patching.

Idempotent: a tile that already has tick_ids is left untouched, so a
partial or repeated run is safe. CPU-bound (gzip decompress + json parse
+ json dump + gzip compress per file), so --workers fans out across
local CPU cores via multiprocessing -- run this on a compute node
(srun/sbatch), not the login node.
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import os
import random
import pathlib
import sys
import tempfile
from typing import List

PATCHABLE_ARCHS = ["loas", "ptb", "spinalflow", "prosperity"]


def patch_file(path: pathlib.Path) -> bool:
    """Returns True if the file was rewritten (had >=1 tile missing tick_ids)."""
    with gzip.open(path, "rt") as fh:
        data = json.load(fh)

    changed = False
    for tile in data["tiles"]:
        if "tick_ids" not in tile:
            tile["tick_ids"] = list(range(len(tile["weight_addresses"])))
            changed = True

    if not changed:
        return False

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        with gzip.open(tmp_name, "wt") as fh:
            json.dump(data, fh)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
    return True


def _patch_one(path_str: str):
    path = pathlib.Path(path_str)
    try:
        return (path_str, patch_file(path), None)
    except Exception as exc:  # noqa: BLE001 - one bad file shouldn't sink the whole batch
        return (path_str, False, repr(exc))


def _collect_files(root: pathlib.Path) -> List[pathlib.Path]:
    files: List[pathlib.Path] = []
    for arch_name in PATCHABLE_ARCHS:
        arch_dir = root / arch_name
        if arch_dir.is_dir():
            files.extend(sorted(arch_dir.glob("*/*/sample_*.json.gz")))
    return files


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default="outputs/weight_traces")
    p.add_argument("--workers", type=int, default=1)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = pathlib.Path(args.root)
    files = _collect_files(root)
    n_total = len(files)
    print(f"{n_total} files to check across {PATCHABLE_ARCHS}, {args.workers} worker(s)", flush=True)

    # File size is wildly skewed (median ~400KB, some dense layers >15MB
    # compressed) and _collect_files' sorted glob groups a layer's samples
    # consecutively -- imap_unordered's chunking would otherwise hand entire
    # chunks of a worker's queue from the SAME giant layer, stalling every
    # worker at once instead of interleaving big and small files. A fixed
    # seed keeps this reproducible run to run.
    random.Random(0).shuffle(files)

    n_patched = 0
    n_already_done = 0
    n_errors = 0

    if args.workers <= 1:
        results = (_patch_one(str(f)) for f in files)
    else:
        pool = multiprocessing.Pool(processes=args.workers)
        results = pool.imap_unordered(_patch_one, (str(f) for f in files), chunksize=8)

    for i, (path_str, changed, err) in enumerate(results):
        if err is not None:
            n_errors += 1
            print(f"ERROR on {path_str}: {err}", file=sys.stderr)
        elif changed:
            n_patched += 1
        else:
            n_already_done += 1
        if (i + 1) % 2000 == 0:
            print(f"  ...{i + 1}/{n_total}", flush=True)

    if args.workers > 1:
        pool.close()
        pool.join()

    print(f"done: {n_patched} patched, {n_already_done} already had tick_ids, {n_errors} errors")
    return 1 if n_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
