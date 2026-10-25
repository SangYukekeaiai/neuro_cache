"""Pieces shared by the profiling stage drivers: the base wcache config, the
`V<n>`/`R<n>` layer tags, and the next layer's CIN that serves as a layer's COUT.

Stages import it after `sys.path.insert(0, str(ROOT / "profiling"))`.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The khkw_split point every wcache stage from 0823 stage 4 on starts from:
# 64 B lines (cin_block 16 x cout_block 4 x 1 B), 16 KB 8-way L1, 512 KB 16-way L2.
BASE = {"layout": "khkw_split", "cin_block": 16, "cout_block": 4, "weight_bytes": 1,
        "l1_size_bytes": 16384, "l1_assoc": 8,
        "l2_size_bytes": 524288, "l2_assoc": 16, "l2_mshrs": 32, "l2_banks": 1,
        "l1_latency": 0, "l2_latency": 2, "l2_miss_latency": 24,
        "prefetch_policy": "none", "prefetch_distance": 0,
        "l2_prefetch_policy": "none"}

# BASE in the key order of run_khkw_sweep.py's grid points, which the stages
# that copy that sweep's best point (khkw_64b.json[0]) keep.
KHKW_KEYS = ("cout_block", "weight_bytes", "layout", "l1_size_bytes", "l1_assoc",
             "l2_size_bytes", "l2_assoc", "l2_mshrs", "l1_latency", "l2_latency",
             "l2_miss_latency", "cin_block", "l2_banks", "prefetch_policy",
             "prefetch_distance")


def base_config(keys=None, drop=(), **extra):
    """BASE's entries for `keys` (all of BASE when None), in that order, minus
    `drop`; a key in `extra` takes its value from there, and the rest of `extra`
    follows. The order is the key order of the grid files a stage writes;
    wcache itself reads the keys by name."""
    out = {k: extra[k] if k in extra else BASE[k]
           for k in (BASE if keys is None else keys) if k not in drop}
    out.update(extra)
    return out


WORKLOADS = [("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]


def tags():
    """(tag, trace_dir, layer) for every valid layer of both `_n5` workloads."""
    from archmodels.trace import valid_layer_names  # needs ROOT/src on sys.path
    out = []
    for prefix, trace_dir in WORKLOADS:
        meta = json.loads((ROOT / "input_trace/loas" / trace_dir / "meta.json").read_text())
        for layer in valid_layer_names(meta):
            out.append((f"{prefix}{int(layer.split('_')[1])}", trace_dir, layer))
    return out


def next_cin_for(meta, layer):
    """The next captured layer's CIN, which is this layer's COUT; None for the last layer."""
    names = list(meta["layers"])
    i = names.index(layer)
    return meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None
