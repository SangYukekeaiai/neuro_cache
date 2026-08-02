"""Synthesize the tiny two-layer trace used by the debug pipeline.

Writes a meta.json + one float32 .npy per layer, the format
src/archmodels/trace.py's load_layer_trace expects. layer_00 is the layer
every later debug stage exercises; layer_01 only supplies layer_00's COUT
via build_workload_from_trace's next_cin lookup, so its contents are never
read.
"""

import json
import pathlib

import numpy as np

OUT_ROOT = pathlib.Path(__file__).resolve().parent / "traces" / "tiny"

META = {
    "captured_at": "synthetic",
    "arch": "loas",
    "timestep": 2,
    "batch_size": 1,
    "dataset": "debug-tiny",
    "layers": {
        "layer_00": [2, 1, 1, 2, 2],
        "layer_01": [2, 1, 4, 2, 2],
    },
}


def make_layer_00() -> np.ndarray:
    trace = np.zeros(META["layers"]["layer_00"], dtype=np.float32)
    trace[0, 0, 0, 0, 0] = 1.0
    trace[0, 0, 0, 1, 1] = 1.0
    trace[1, 0, 0, 1, 0] = 1.0
    # (h=0, w=1) stays silent across all T: later stages rely on exactly one
    # silent input position to exercise LoAS's silent-neuron compression.
    silent = trace.sum(axis=0)[0, 0] == 0
    assert silent.tolist() == [[False, True], [False, False]], silent
    return trace


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with open(OUT_ROOT / "meta.json", "w") as fh:
        json.dump(META, fh, indent=2)
        fh.write("\n")
    np.save(OUT_ROOT / "layer_00.npy", make_layer_00())
    np.save(
        OUT_ROOT / "layer_01.npy",
        np.zeros(META["layers"]["layer_01"], dtype=np.float32),
    )
    print(f"wrote meta.json, layer_00.npy, layer_01.npy to {OUT_ROOT}")


if __name__ == "__main__":
    main()
