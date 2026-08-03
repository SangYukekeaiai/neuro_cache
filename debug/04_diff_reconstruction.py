"""Stage 1 parity check: packed-Python vs native-C++ reconstruction.

Runs one tiny-trace sample through both
python_reference.tracegen_reconstruct.reconstruct_samples_for_schedule
(driving the packed pure-Python compute modules in dump/python_reference/) and
the arch's native_bridge.reconstruct_samples_native, then diffs every tile's
weight_addresses and tick_ids exactly. Exits non-zero on any difference.
"""

import argparse
import importlib
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACE_ROOT = REPO_ROOT / "debug" / "traces"
SCHEDULE_CACHE = REPO_ROOT / "debug" / "schedules"

sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

import tracegen  # noqa: E402
from archmodels import ARCH_NATIVE_BRIDGES  # noqa: E402
from archmodels.trace import load_layer_trace  # noqa: E402
from python_reference.tracegen_reconstruct import reconstruct_samples_for_schedule  # noqa: E402

PY_MODEL_CLASSES = {
    "loas": "LoASComputeModel",
    "spinalflow": "SpinalFlowComputeModel",
    "ptb": "PTBComputeModel",
    "gustavsnn": "GustavSNNComputeModel",
    "prosperity": "ProsperityComputeModel",
}


def python_model(arch: str):
    module = importlib.import_module(f"python_reference.archmodels.{arch}.model")
    return getattr(module, PY_MODEL_CLASSES[arch])()


def native_reconstruct_fn(arch: str):
    return importlib.import_module(ARCH_NATIVE_BRIDGES[arch]).reconstruct_samples_native


def _flatten_single_core(tile):
    """Flatten a single-node TileWeightTrace's ticks (always exactly one
    core, core_id=0 -- see log/2026-08-02-multinode-core-driven-weight-trace-plan.md)
    back into a (weight_addresses, tick_ids) pair, at the same granularity
    this script has always diffed at, pre-dating the tick-major nesting."""
    addresses, tick_ids = [], []
    for entry in tile.ticks:
        for core in entry.cores:
            for addr in core.weight_addresses:
                addresses.append(addr)
                tick_ids.append(entry.tick)
    return addresses, tick_ids


def diff_layer(py_layer, native_layer):
    """One human-readable line per mismatched field; empty list means the two
    reconstructions are identical."""
    diffs = []
    if len(py_layer.tiles) != len(native_layer.tiles):
        return [f"tile count: python={len(py_layer.tiles)} native={len(native_layer.tiles)}"]
    for i, (py_tile, nat_tile) in enumerate(zip(py_layer.tiles, native_layer.tiles)):
        py_raw_addr, py_ticks = _flatten_single_core(py_tile)
        nat_raw_addr, nat_ticks = _flatten_single_core(nat_tile)
        py_addr = [tuple(a) for a in py_raw_addr]
        nat_addr = [tuple(a) for a in nat_raw_addr]
        if py_addr != nat_addr:
            diffs.append(f"tile {i} weight_addresses: python={py_addr} native={nat_addr}")
        if py_ticks != nat_ticks:
            diffs.append(f"tile {i} tick_ids: python={py_ticks} native={nat_ticks}")
    return diffs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arch", required=True, choices=sorted(ARCH_NATIVE_BRIDGES))
    p.add_argument("--trace-dir", required=True)
    p.add_argument("--layer", required=True)
    p.add_argument("--sample", type=int, default=0)
    p.add_argument("--trace-root", default=str(TRACE_ROOT))
    p.add_argument("--schedule-cache", default=str(SCHEDULE_CACHE))
    args = p.parse_args()

    schedule_path = pathlib.Path(args.schedule_cache) / args.arch / args.trace_dir / f"{args.layer}.json"
    artifact, _prob, tiles = tracegen.load_schedule(schedule_path)
    trace = load_layer_trace(pathlib.Path(args.trace_root) / args.trace_dir, args.layer, mmap=True)
    sample_indices = [args.sample]
    common = (args.arch, args.trace_dir, args.layer, artifact.workload["problem"], artifact.dram_num_steps)

    py_layer = reconstruct_samples_for_schedule(
        python_model(args.arch), trace, tiles, sample_indices, *common
    )[0]
    native_layer = native_reconstruct_fn(args.arch)(
        trace, tiles, sample_indices, *common
    )[0]

    print(f"{args.arch}/{args.trace_dir}/{args.layer} sample {args.sample}: "
          f"{len(py_layer.tiles)} tiles (python), {len(native_layer.tiles)} tiles (native)")
    diffs = diff_layer(py_layer, native_layer)
    if diffs:
        print(f"DIFF: {len(diffs)} mismatch(es)")
        for line in diffs:
            print(f"  {line}")
        return 1
    print("DIFF EMPTY: weight_addresses and tick_ids identical in every tile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
