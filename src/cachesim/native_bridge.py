"""Subprocess bridge to cache_replay -- the C++ port of
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
import tempfile
from typing import Sequence

from .config import CacheConfig
from .stats import HierarchyStats, HierarchySweepResult

_NATIVE_BIN = pathlib.Path(__file__).resolve().parent / "cache_replay"
_NATIVE_HIERARCHICAL_BIN = pathlib.Path(__file__).resolve().parent / "cache_replay_hierarchical"
_NATIVE_HIERARCHICAL_SWEEP_BIN = pathlib.Path(__file__).resolve().parent / "cache_sweep_hierarchical"


def load_sample(sample_path: pathlib.Path) -> dict:
    """One persisted sample's JSON, decompressed. Callers of the
    hierarchical path need the dict as well as the file, because the two
    cache configs are built from the sample's own workload_dims (the
    layer's true shape is not a cache-YAML key -- see
    config.load_cache_config)."""
    with gzip.open(sample_path, "rt") as fh:
        return json.load(fh)


def _write_events(path: pathlib.Path, sample_path: pathlib.Path) -> None:
    """The single-level binary's wire format, reading the OLD flat
    schema (tile["weight_addresses"]). The hierarchical path reads the
    Stage 1 nested schema instead; see _write_ticks."""
    data = load_sample(sample_path)
    events = [addr for tile in data["tiles"] for addr in tile["weight_addresses"]]
    with open(path, "wb") as out:
        out.write(struct.pack("<I", len(events)))
        for kh, kw, cin, cs, ce in events:
            out.write(struct.pack("<iiiii", kh, kw, cin, cs, ce))


def _run_replay(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> tuple[str, str, str]:
    """The binary's three whitespace-separated stdout fields, unparsed:
    hit count, access count, and hit rate as a "%.6f" string."""
    if not _NATIVE_BIN.exists():
        raise FileNotFoundError(f"cache_replay binary not found at {_NATIVE_BIN}; run `make` in src/cachesim/")

    args = [
        str(_NATIVE_BIN),
        str(config.cache_size_bytes),
        str(config.line_size_bytes),
        config.cache_type,
        str(config.associativity or 0),
        config.inner_dim,
        ",".join(order),
        config.layout,
        str(config.cin_block),
        str(config.cout_block),
        # 0 is the binary's "not set", which only layout='inner_dim' may
        # pass; CacheConfig has already refused a hybrid config without them.
        str(config.kh_bound or 0),
        str(config.kw_bound or 0),
        str(config.cin_bound or 0),
        str(config.cout_bound or 0),
    ]
    # Same private-temp-dir convention as src/archmodels/*/native_bridge.py:
    # a predictable name under the shared /tmp is a symlink target for any
    # other local user on a login node. Removed on both paths out.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp) / "events.bin"
        _write_events(tmp_path, trace_path)
        with open(tmp_path, "rb") as stdin_fh:
            proc = subprocess.run(args, stdin=stdin_fh, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cache_replay failed: {proc.stderr.strip()}")
    hits, total, hit_rate = proc.stdout.split()
    return hits, total, hit_rate


def native_sample_hit_rate(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> float:
    """Native equivalent of sweep.sample_hit_rate(trace_path, config,
    order) -- same inputs, same semantics, ~110x faster per call. Reads
    the sample's raw JSON directly (not tracegen.load_weight_trace), same
    as profiling/0726/cache_sweep.py, to avoid pulling in gurobipy just
    to flatten weight_addresses.

    The rate comes back through a "%.6f" text field, so 6 decimals is all
    the precision this wire carries; native_sample_hit_counts returns the
    two integers behind it when an exact number is needed."""
    return float(_run_replay(trace_path, config, order)[2])


def native_sample_hit_counts(trace_path: pathlib.Path, config: CacheConfig, order: Sequence[str]) -> tuple[int, int]:
    """(hits, accesses) for the same replay, exact instead of rounded."""
    hits, total, _rate = _run_replay(trace_path, config, order)
    return int(hits), int(total)


def _write_tick_data(path: pathlib.Path, data: dict) -> None:
    """cache_replay_hierarchical's wire format, reading the Stage 1
    nested schema (tiles -> ticks -> cores -> weight_addresses). This is
    what replaces _write_events on the hierarchical path; the
    single-level path keeps reading the flat schema.

    Tiles are flattened away: a tile boundary is also a tick boundary, so
    the tick stream alone carries everything the hierarchy needs. Cores
    are sorted ascending per tick, because that order is the order this
    tick's L2 fills get applied in and tracegen.merge_cores_by_tick does
    not guarantee it on disk. A core absent from a tick is absent here
    too -- never padded with an empty entry."""
    ticks = [tick for tile in data["tiles"] for tick in tile["ticks"]]
    with open(path, "wb") as out:
        out.write(struct.pack("<I", len(ticks)))
        for tick in ticks:
            cores = sorted(tick["cores"], key=lambda c: c["core_id"])
            out.write(struct.pack("<I", len(cores)))
            for core in cores:
                events = core["weight_addresses"]
                out.write(struct.pack("<iI", core["core_id"], len(events)))
                for kh, kw, cin, cs, ce in events:
                    out.write(struct.pack("<iiiii", kh, kw, cin, cs, ce))


def _write_ticks(path: pathlib.Path, sample_path: pathlib.Path) -> None:
    _write_tick_data(path, load_sample(sample_path))


def native_hierarchical_stats(
    trace_path: pathlib.Path,
    l1_config: CacheConfig,
    l2_config: CacheConfig,
    order: Sequence[str],
    *,
    l2_prefetch: bool,
    same_tick_pinning: bool,
) -> HierarchyStats:
    """Replay one Stage 1 nested sample through the native two-level
    engine (private L1 per core + shared L2). Native counterpart of
    dump/python_reference/cachesim/hierarchy.replay_sample, and returns
    the same HierarchyStats, which is what makes the two directly
    comparable.

    The layout arguments go over once, not per level: the plan gives L1
    and L2 one shared layout formula and one shared line size, so the
    binary takes them once and a mismatch cannot be expressed.

    l2_prefetch and same_tick_pinning are required here and required by
    the binary, so the engine's two policy switches have no default on
    either side of this bridge to drift apart."""
    if not _NATIVE_HIERARCHICAL_BIN.exists():
        raise FileNotFoundError(
            f"cache_replay_hierarchical binary not found at {_NATIVE_HIERARCHICAL_BIN}; run `make` in src/cachesim/"
        )

    args = [
        str(_NATIVE_HIERARCHICAL_BIN),
        str(l1_config.cache_size_bytes),
        l1_config.cache_type,
        str(l1_config.associativity or 0),
        str(l2_config.cache_size_bytes),
        l2_config.cache_type,
        str(l2_config.associativity or 0),
        str(l1_config.line_size_bytes),
        ",".join(order),
        l1_config.layout,
        str(l1_config.cin_block),
        str(l1_config.cout_block),
        str(l1_config.kh_bound or 0),
        str(l1_config.kw_bound or 0),
        str(l1_config.cin_bound or 0),
        str(l1_config.cout_bound or 0),
        "1" if l2_prefetch else "0",
        "1" if same_tick_pinning else "0",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp) / "ticks.bin"
        _write_ticks(tmp_path, trace_path)
        with open(tmp_path, "rb") as stdin_fh:
            proc = subprocess.run(args, stdin=stdin_fh, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cache_replay_hierarchical failed: {proc.stderr.strip()}")

    lines = proc.stdout.split("\n")
    n_cores = int(lines[0])
    per_core = tuple(tuple(int(f) for f in lines[1 + i].split()) for i in range(n_cores))
    l1_hits, l1_accesses, l2_hits, l2_accesses = (int(f) for f in lines[1 + n_cores].split())
    return HierarchyStats(
        per_core_l1=per_core,
        l1_hits=l1_hits,
        l1_accesses=l1_accesses,
        l2_hits=l2_hits,
        l2_accesses=l2_accesses,
    )


def native_hierarchical_sweep(
    trace_path: pathlib.Path,
    order: Sequence[str],
) -> tuple[HierarchySweepResult, ...]:
    """Replay one nested sample through the plan's fixed 24-point grid.

    The sample is decompressed and serialized once. The native process
    packs the tick stream once and runs all configurations over it, which
    avoids repeating the expensive JSON work for every point.
    """
    if not _NATIVE_HIERARCHICAL_SWEEP_BIN.exists():
        raise FileNotFoundError(
            f"cache_sweep_hierarchical binary not found at {_NATIVE_HIERARCHICAL_SWEEP_BIN}; "
            "run `make` in src/cachesim/"
        )

    data = load_sample(trace_path)
    dims = data["workload_dims"]
    args = [
        str(_NATIVE_HIERARCHICAL_SWEEP_BIN),
        ",".join(order),
        str(dims["KH"]),
        str(dims["KW"]),
        str(dims["CIN"]),
        str(dims["COUT"]),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        tick_path = pathlib.Path(tmp) / "ticks.bin"
        _write_tick_data(tick_path, data)
        del data
        with open(tick_path, "rb") as stdin_fh:
            proc = subprocess.run(args, stdin=stdin_fh, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cache_sweep_hierarchical failed: {proc.stderr.strip()}")

    lines = iter(proc.stdout.splitlines())
    n_configs = int(next(lines))
    results = []
    for _ in range(n_configs):
        fields = next(lines).split()
        if len(fields) != 9:
            raise RuntimeError(f"cache_sweep_hierarchical returned malformed config row: {' '.join(fields)}")
        cache_type = fields[0]
        associativity, l1_size, l2_size, n_cores, l1_hits, l1_accesses, l2_hits, l2_accesses = (
            int(value) for value in fields[1:]
        )
        per_core = tuple(tuple(int(value) for value in next(lines).split()) for _ in range(n_cores))
        results.append(HierarchySweepResult(
            cache_type=cache_type,
            associativity=associativity or None,
            l1_size_bytes=l1_size,
            l2_size_bytes=l2_size,
            stats=HierarchyStats(
                per_core_l1=per_core,
                l1_hits=l1_hits,
                l1_accesses=l1_accesses,
                l2_hits=l2_hits,
                l2_accesses=l2_accesses,
            ),
        ))
    try:
        extra = next(lines)
    except StopIteration:
        extra = None
    if extra is not None:
        raise RuntimeError(f"cache_sweep_hierarchical returned unexpected trailing output: {extra}")
    return tuple(results)
