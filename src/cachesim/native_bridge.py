"""Subprocess bridge to native/cache_replay -- the C++ port of
sweep.sample_hit_rate's logic (expand_events + tag_for_element + Cache
replay), for one CacheConfig against one persisted trace sample. Same
convention as src/archmodels/*/native_bridge.py: a standalone compiled
binary, invoked once per call, custom binary I/O instead of JSON.

Only exists because the pure-Python path is ~110x slower per (sample,
config) on real data -- see cache_replay.cpp's header. Falls back to
raising, not to the Python path, on any native-binary error: silently
computing a different (slow) answer than what was asked for is worse
than a loud failure.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import struct
import subprocess
from typing import Sequence

from .config import CacheConfig

_NATIVE_BIN = pathlib.Path(__file__).resolve().parent / "native" / "cache_replay"


def _write_events(path: pathlib.Path, sample_path: pathlib.Path) -> None:
    with gzip.open(sample_path, "rt") as fh:
        data = json.load(fh)
    events = [addr for tile in data["tiles"] for addr in tile["weight_addresses"]]
    with open(path, "wb") as out:
        out.write(struct.pack("<I", len(events)))
        for kh, kw, cin, cs, ce in events:
            out.write(struct.pack("<iiiii", kh, kw, cin, cs, ce))


def native_sample_hit_rate(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> float:
    """Native equivalent of sweep.sample_hit_rate(trace_path, config,
    order) -- same inputs, same semantics, ~110x faster per call. Reads
    the sample's raw JSON directly (not tracegen.load_weight_trace), same
    as profiling/0726/cache_sweep.py, to avoid pulling in gurobipy just
    to flatten weight_addresses."""
    if not _NATIVE_BIN.exists():
        raise FileNotFoundError(f"cache_replay binary not found at {_NATIVE_BIN}; run `make` in src/cachesim/native/")

    tmp_path = pathlib.Path(f"/tmp/cache_replay_{__import__('os').getpid()}_{id(trace_path)}.bin")
    try:
        _write_events(tmp_path, trace_path)
        args = [
            str(_NATIVE_BIN),
            str(config.cache_size_bytes),
            str(config.line_size_bytes),
            config.cache_type,
            str(config.associativity or 0),
            config.inner_dim,
            ",".join(order),
        ]
        with open(tmp_path, "rb") as stdin_fh:
            proc = subprocess.run(args, stdin=stdin_fh, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"cache_replay failed: {proc.stderr.strip()}")
        hits, total, hit_rate = proc.stdout.split()
        return float(hit_rate)
    finally:
        tmp_path.unlink(missing_ok=True)
