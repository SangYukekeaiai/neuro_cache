"""Writes one checked-in example fixture out as a WCTS stream on stdout.

    python3 to_stream.py <fixture.json> [max_tiles] > slice.wcts

The fixtures are v2 documents (tick and core_id present); the v1 legacy file
has neither and cannot drive the engine. `n_cores` is 8 and `spatial_factors`
is {3: 8} for every example: the burst axis is dim 3 and the corpus was
generated with 8 cores, so a fixture whose own core list is shorter (prosperity
uses 6) still streams with the two extra cores contributing no bursts.

`max_tiles` truncates the stream after that many tile frames, which is what the
per-tile prefix cases want.
"""
import json
import pathlib
import sys
import types

# src/, three levels up from src/wcache/examples/, is where tracegen lives.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

try:
    import archmodels.trace  # noqa: F401
except ImportError:
    # tracegen's WCTS writers need only `struct`, but the module's top-level
    # `from archmodels.trace import ...` pulls in numpy, which the wire format
    # has no part in. Where that import cannot be satisfied, a stub stands in
    # so this helper depends on the writer and nothing else.
    _stub = types.ModuleType("archmodels.trace")
    _stub.build_workload_from_trace = None
    sys.modules["archmodels.trace"] = _stub

from tracegen import (CoreEntry, LayerWeightTrace, TickEntry,  # noqa: E402
                      TileWeightTrace, stream_weight_trace)

N_CORES = 8


def load(path):
    doc = json.load(open(path))
    tiles = [TileWeightTrace(
        dram_i=t["dram_i"], noc_i=t["noc_i"], mac_cycles=t["mac_cycles"],
        lif_cycles=t.get("lif_cycles"),
        ticks=[TickEntry(tick=k["tick"],
                         cores=[CoreEntry(core_id=c["core_id"],
                                          weight_addresses=c["weight_addresses"])
                                for c in k["cores"]])
               for k in t["ticks"]])
        for t in doc["tiles"]]
    return LayerWeightTrace(arch=doc["arch"], trace_dir=doc["trace_dir"],
                            layer_name=doc["layer_name"],
                            sample_idx=doc["sample_idx"],
                            workload_dims=doc["workload_dims"],
                            dram_num_steps=doc["dram_num_steps"],
                            noc_num_steps=doc["noc_num_steps"], tiles=tiles)


def main(argv):
    if not 2 <= len(argv) <= 3:
        sys.exit(__doc__)
    max_tiles = int(argv[2]) if len(argv) == 3 else None
    n = stream_weight_trace(load(argv[1]), sys.stdout.buffer, n_cores=N_CORES,
                            spatial_factors={3: N_CORES}, max_tiles=max_tiles)
    print(f"to_stream: wrote {n} bursts", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
