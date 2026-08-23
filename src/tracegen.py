"""Shared solve/reconstruct/persist core for weight-trace generation.

Extracts what scripts/sweep_archmodel_layers.py used to do entirely
inline (solve -> iterate tiles -> format_input -> compute_cycles /
weight_addresses) into reusable pieces, so that script and the
generate-once pipeline (scripts/solve_schedules.py,
scripts/generate_weight_traces.py) share one implementation instead of
two copies that could quietly drift apart.

Two independent artifacts, matching the two-stage design
(dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md):

  ScheduleArtifact  -- one solved MIP schedule, persisted once per
                       (arch, trace_dir, layer). Reused across every
                       sample's reconstruction, since batch never
                       participates in the workload/tiling dimensions
                       (archmodels/trace.py's build_workload_from_trace
                       never reads B at all).
  LayerWeightTrace  -- one sample's per-tile weight-address stream +
                       cycle counts, persisted once per
                       (arch, trace_dir, layer, sample).
"""

from __future__ import annotations

import gzip
import importlib
import json
import os
import pathlib
import random
import struct
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from archmodels import ARCH_NATIVE_BRIDGES, NodeTileSpec
from archmodels.trace import build_workload_from_trace
from nocsim.schedule.decode import schedule_from_strategy
from nocsim.schedule.tiles import iter_node_tiles
from parsers.layer import SNNProb

# mip_solver is imported lazily, inside solve_and_cache_schedule only:
# mip_solver.solve pulls in gurobipy at module load, and everything else
# in this module (loading/reconstructing an already-cached schedule) has
# no need for Gurobi at all -- see dump/python_reference/cachesim/sweep.py's
# own deferred-import comment for the same reasoning applied elsewhere.

@dataclass
class ScheduleArtifact:
    """A solved schedule, persisted once per (arch, trace_dir, layer)."""

    arch: str
    trace_dir: str
    layer_name: str
    workload: Dict[str, Any]
    result: Dict[str, Any]  # raw solve_schedule() output (has_solution, strategy, ...)
    dram_num_steps: int
    mode: str = "base"  # winning TrafficMode's .value; default keeps old caches loadable


def _dump_workload_path(workload: Dict[str, Any]) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(workload, f)
        return f.name


def _prob_from_workload(workload: Dict[str, Any]) -> SNNProb:
    return SNNProb(pathlib.Path(_dump_workload_path(workload)))


def solve_and_cache_schedule(
    arch_name: str,
    arch_yaml: str,
    dataflow_yaml: str,
    trace_dir_name: str,
    layer_name: str,
    meta: Dict[str, Any],
    next_cin: Optional[int],
    cache_dir: pathlib.Path,
) -> ScheduleArtifact:
    """Solve one (arch, layer)'s schedule across every TrafficMode, keep the
    winner by the same score sweep_weights.py/run_full_sweep.py use
    (w_u*util_sum + w_tr*tr_sum + w_dl*delay, lower is better), and persist
    it to cache_dir/<arch>/<trace_dir>/<layer_name>.json. Always re-solves --
    callers wanting skip-existing behavior should check for that file
    themselves first, matching every other skip-existing check in this
    pipeline (see generate_weight_traces.py).

    BASE is always feasible (unconstrained) but is not special-cased --
    across all 155 real (arch, layer) pairs in this project's own trace
    data, BASE never actually wins (verified 2026-07-19): every other
    TrafficMode either is infeasible for these single_node archs or beats
    BASE's score once feasible, since BASE's objective has no credit for
    the psum/vmem DRAM-traffic elimination the other modes' loop-order
    constraints unlock.

    Raises ValueError if EVERY mode is infeasible (callers sweeping many
    layers should catch this and record it, not let it abort the sweep).
    """
    from mip_solver.solve import solve_best_schedule  # lazy: see module-level comment

    workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
    layer_path = _dump_workload_path(workload)
    prob = SNNProb(pathlib.Path(layer_path))

    try:
        best_mode, best_result = solve_best_schedule(layer_path, arch_yaml, dataflow_yaml)
    except ValueError as exc:
        raise ValueError(
            f"solve_and_cache_schedule: infeasible for {arch_name}/{trace_dir_name}/{layer_name} "
            f"(every TrafficMode infeasible)"
        ) from exc
    schedule = schedule_from_strategy(best_result["strategy"], prob)

    artifact = ScheduleArtifact(
        arch=arch_name,
        trace_dir=trace_dir_name,
        layer_name=layer_name,
        workload=workload,
        result=best_result,
        dram_num_steps=schedule.dram_num_steps,
        mode=best_mode.value,
    )
    out_path = cache_dir / arch_name / trace_dir_name / f"{layer_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(asdict(artifact), fh, indent=1)
    return artifact


def load_schedule(path: pathlib.Path) -> Tuple[ScheduleArtifact, SNNProb, List[NodeTileSpec]]:
    """Load a persisted ScheduleArtifact and rederive the (prob, tiles) it
    implies. schedule/tiles aren't themselves JSON-serializable, so they're
    rebuilt deterministically from the cached workload+result rather than
    (de)serialized directly -- iter_node_tiles is a pure function of
    (schedule, prob), so this reproduces the exact same tile list every
    time without re-solving anything."""
    with open(path) as fh:
        data = json.load(fh)
    artifact = ScheduleArtifact(**data)
    prob = _prob_from_workload(artifact.workload)
    schedule = schedule_from_strategy(artifact.result["strategy"], prob)
    tiles = list(iter_node_tiles(schedule, prob))
    return artifact, prob, tiles


@dataclass
class CoreEntry:
    """One core's weight fetches at one tick, within one (dram_i, noc_i)
    tile. weight_addresses is that core's own raw bursted-event list for
    this tick only -- same [kh, kw, cin, cout_start, cout_end] shape as
    TileWeightTrace.weight_addresses, just scoped to one core/one tick.
    core_id decodes via nocsim.schedule.tiles.decode_core_id."""
    core_id: int
    weight_addresses: List[Any]


@dataclass
class TickEntry:
    """All cores' fetches at one tick, within one (dram_i, noc_i) tile. A
    core absent from `cores` had no fetch this tick (e.g. it finished its
    local work for the tile earlier) -- omitted, never padded with an
    empty CoreEntry."""
    tick: int
    cores: List[CoreEntry]


def merge_cores_by_tick(core_results: Dict[int, Dict[str, Any]]) -> List[TickEntry]:
    """Merge N cores' own per-tile results into one tile's tick-major
    ticks list -- the canonical on-disk order is dram_i -> noc_i -> tick ->
    core (core fastest-varying). See
    log/2026-08-02-multinode-core-driven-weight-trace-plan.md.

    core_results: {core_id: {"ticks": [{"tick": j, "weight_addresses": [...]}, ...]}},
    one entry per core that was active in this tile -- exactly what one
    per-core native-bridge call returns (already grouped by tick within
    that core's own data; see each arch's main.cpp). This function does
    only the cross-core merge, which is structurally Python's job: no
    single per-core native-bridge call has visibility into other cores'
    results, so nothing native could do this part.

    Raises nothing on an empty core_results -- returns [] (a tile with no
    active cores at all, e.g. num_cores=0, should never happen in practice
    but isn't this function's job to validate).
    """
    by_tick: Dict[int, List[CoreEntry]] = {}
    for core_id, result in core_results.items():
        for entry in result["ticks"]:
            by_tick.setdefault(entry["tick"], []).append(
                CoreEntry(core_id=core_id, weight_addresses=entry["weight_addresses"])
            )
    return [TickEntry(tick=t, cores=by_tick[t]) for t in sorted(by_tick)]


@dataclass
class TileWeightTrace:
    """One (dram_i, noc_i) tile's reconstructed weight fetches, tick-major
    (see log/2026-08-02-multinode-core-driven-weight-trace-plan.md).
    noc_i is always 0 and ticks always has exactly one core (core_id=0) for
    a single-node schedule -- the degenerate case of this same shape, not a
    separate format."""
    dram_i: int
    noc_i: int
    mac_cycles: int
    lif_cycles: Optional[int]
    ticks: List[TickEntry]


@dataclass
class LayerWeightTrace:
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    noc_num_steps: int
    tiles: List[TileWeightTrace]


def tick_entries_from_flat(weight_addresses: List[Any], tick_ids: List[int]) -> List[TickEntry]:
    """Transitional adapter (log/2026-08-02-multinode-core-driven-weight-trace-plan.md,
    Milestone 3): buckets the OLD flat parallel (weight_addresses, tick_ids)
    arrays -- what an arch's native binary returns before its own main.cpp
    is updated to emit tick-grouped output directly -- into the new
    TickEntry shape, single core (core_id=0). Used by every arch whose
    main.cpp hasn't been updated yet; removed for an arch once it has (loas
    no longer needs this -- its native output is already tick-grouped)."""
    by_tick: Dict[int, List[Any]] = {}
    for addr, tick in zip(weight_addresses, tick_ids):
        by_tick.setdefault(tick, []).append(addr)
    return [
        TickEntry(tick=t, cores=[CoreEntry(core_id=0, weight_addresses=addrs)])
        for t, addrs in sorted(by_tick.items())
    ]


def assemble_layer_traces(
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    unpacked: Iterable[Any],
    arch_name: str,
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
) -> List[LayerWeightTrace]:
    """Shared assembly step every arch's reconstruct_samples_native calls
    after its own native-binary invocation and per-arch unpacking. Groups
    per-(tile_idx, local_sample_idx) results by (dram_i, noc_i) across
    whichever core_ids `tiles` contains, merges cores via
    merge_cores_by_tick, and packages one LayerWeightTrace per sample.

    `unpacked` yields (tile_idx, local_sample_idx, mac_cycles, ticks) once
    per (tile, sample), sample-outer and tile-inner (the arch binaries'
    emission order; see the Phase D campaign plan, 10.4). This function
    keys everything off each record's own indices, so it is independent of
    that order -- `ticks` already in the
    [{"tick": j, "weight_addresses": [...]}] shape (loas's native output
    already is that shape; other archs get there via
    tick_entries_from_flat -- see that function's docstring). `tiles[tile_idx]`
    supplies that entry's (dram_i, noc_i, core_id).
    """
    noc_num_steps = max((t.noc_i for t in tiles), default=0) + 1
    num_samples = len(sample_indices)
    # per sample: {(dram_i, noc_i): {core_id: {"mac_cycles": int, "ticks": [...]}}}
    groups: List[Dict[tuple, Dict[int, Dict[str, Any]]]] = [dict() for _ in range(num_samples)]

    for tile_idx, local_idx, mac_cycles, ticks in unpacked:
        spec = tiles[tile_idx]
        key = (spec.dram_i, spec.noc_i)
        groups[local_idx].setdefault(key, {})[spec.core_id] = {"mac_cycles": mac_cycles, "ticks": ticks}

    out = []
    for i, sample_idx in enumerate(sample_indices):
        tiles_out = []
        for dram_i, noc_i in sorted(groups[i]):
            core_results = groups[i][(dram_i, noc_i)]
            mac_cycles = max(r["mac_cycles"] for r in core_results.values())
            tiles_out.append(TileWeightTrace(
                dram_i=dram_i, noc_i=noc_i, mac_cycles=mac_cycles, lif_cycles=None,
                ticks=merge_cores_by_tick(core_results),
            ))
        out.append(LayerWeightTrace(
            arch=arch_name, trace_dir=trace_dir_name, layer_name=layer_name,
            sample_idx=sample_idx, workload_dims=workload_dims,
            dram_num_steps=dram_num_steps, noc_num_steps=noc_num_steps,
            tiles=tiles_out,
        ))
    return out


def reconstruct_samples(
    arch_name: str,
    trace: Any,
    tiles: Sequence[NodeTileSpec],
    sample_indices: Sequence[int],
    trace_dir_name: str,
    layer_name: str,
    workload_dims: Dict[str, Any],
    dram_num_steps: int,
) -> List[LayerWeightTrace]:
    """One LayerWeightTrace per requested sample, dispatching to arch_name's
    native C++ bridge (archmodels.ARCH_NATIVE_BRIDGES). Single consolidated
    entry point for what used to be two copy-pasted dispatch blocks in
    scripts/generate_weight_traces.py and
    scripts/generate_weight_traces_canonical100.py -- callers own the
    trace/worker-pool setup around this, this function owns only the
    dispatch. `trace` should already be loaded (e.g. via
    archmodels.trace.load_layer_trace(..., mmap=True)); this function
    doesn't load it itself so a caller running many samples across
    multiple workers can load it once per worker instead of once per call.
    """
    module_name = ARCH_NATIVE_BRIDGES.get(arch_name)
    if module_name is None:
        raise KeyError(
            f"no native bridge registered for arch '{arch_name}'; "
            f"known archs: {sorted(ARCH_NATIVE_BRIDGES)}"
        )
    native_fn = importlib.import_module(module_name).reconstruct_samples_native
    return native_fn(
        trace, tiles, sample_indices, arch_name, trace_dir_name, layer_name,
        workload_dims, dram_num_steps,
    )


def save_weight_trace(trace: LayerWeightTrace, path: pathlib.Path) -> None:
    """Writes gzip-compressed JSON -- verified 19.5x smaller on real
    generated data (9.64MB -> 0.49MB), which is what makes the full sweep's
    storage footprint (otherwise ~510GB at 1000 samples/layer) fit in any
    reasonable quota. `path` should end in .json.gz; transparent to any
    caller reading it back with gzip.open -- only a direct `open()`/`cat`
    of the file needs to know it's gzipped. (The read-side counterpart,
    load_weight_trace, moved to dump/python_reference/tracegen_reconstruct.py
    since nothing in the live pipeline reads a trace back this way --
    src/cachesim/native_bridge.py reads the raw JSON directly instead.)

    Writes to a sibling temp file and os.replace()s it into place, so a
    process killed mid-write (OOM, SLURM time limit, etc.) can never leave
    a truncated file sitting at `path` -- skip-existing checks (this
    module's callers, generate_weight_traces.py) only ever see either the
    complete prior file or nothing, never a corrupted partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        with gzip.open(tmp_name, "wt") as fh:
            json.dump(asdict(trace), fh)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


# ----------------------------------------------------------------------
# WCTS (weight cache trace stream), version 1
#
# The in-flight sibling of save_weight_trace: the same data as a stream
# instead of a document, so a producer can feed the cache simulator down a
# pipe with nothing materialized in between (Phase D campaign plan, 10).
# The format is normative in log/2026-08-20-phaseD-implementation-plan.md,
# "The wire format, in full"; the C++ reader (wcache/stream_format.h)
# decodes exactly these bytes. `burst_span` sits beside burst_dim and
# burst_stride per coordinator ruling Q-D, which the normative table there
# predates -- that is the one field to check first if the two sides
# disagree.
#
# Fixed header, little-endian, no padding:
#    0  8  magic "WCTRACE1"        28  4  i32 burst_dim
#    8  4  u32 format_version      32  4  i32 burst_stride
#   12  4  u32 header_bytes        36  4  i32 burst_span
#   16  4  i32 n_tiles             40  4  i32 n_addr_fields
#   20  4  i32 n_cores             44  4  i32 n_spatial
#   24  4  i32 weight_bytes        48  4  i32 n_dims
#                                  52  4  i32 identity_bytes
# then n_addr_fields i32 field codes, n_spatial (dim_id, factor) pairs,
# n_dims (dim_id, extent) pairs, and the identity block.
# ----------------------------------------------------------------------

WCTS_MAGIC = b"WCTRACE1"
WCTS_VERSION = 1
WCTS_FIXED_HEADER_BYTES = 56
WCTS_END_MAGIC = -1

# Wire codes, deliberately independent of any enum elsewhere so a
# renumbering there cannot silently change the format.
WCTS_DIM_CODES = {"KH": 0, "KW": 1, "CIN": 2, "COUT": 3, "HO": 4, "WO": 5, "T": 6}
# 0=KH 1=KW 2=CIN 3=RUN_START 4=RUN_END, i.e. the [kh, kw, cin, cout_start,
# cout_end] address record every arch already emits.
WCTS_ADDR_FIELDS = (0, 1, 2, 3, 4)
_WCTS_BURST_BYTES = 8 + 4 * len(WCTS_ADDR_FIELDS)


def write_stream_header(fh, *, n_tiles, n_cores, weight_bytes, burst_dim,
                        burst_stride, burst_span, spatial_factors, dims,
                        arch, workload, layer, sample_idx) -> None:
    """Writes the WCTS stream header. `spatial_factors` and `dims` are
    {dim_id: value} mappings using the wire codes 0=KH 1=KW 2=CIN 3=COUT
    4=HO 5=WO 6=T. `burst_dim` is one of those codes. Raises ValueError when
    prod(spatial_factors.values()) != n_cores, which is U25's check on the
    producer side, and when `dims` is not exactly the seven codes."""
    product = 1
    for factor in spatial_factors.values():
        product *= factor
    if product != n_cores:
        raise ValueError(
            f"write_stream_header: prod(spatial_factors)={product} != n_cores={n_cores} "
            f"(spatial_factors={spatial_factors}); the reader rejects a stream where they disagree"
        )
    if sorted(dims) != sorted(WCTS_DIM_CODES.values()):
        raise ValueError(f"write_stream_header: dims must carry all 7 wire codes, got {sorted(dims)}")

    identity = b"".join(
        str(field).encode("utf-8") + b"\0" for field in (arch, workload, layer, sample_idx)
    )
    header_bytes = (WCTS_FIXED_HEADER_BYTES + 4 * len(WCTS_ADDR_FIELDS)
                    + 8 * len(spatial_factors) + 8 * len(dims) + len(identity))

    fh.write(WCTS_MAGIC)
    fh.write(struct.pack(
        "<IIiiiiiiiiii", WCTS_VERSION, header_bytes, n_tiles, n_cores, weight_bytes,
        burst_dim, burst_stride, burst_span, len(WCTS_ADDR_FIELDS),
        len(spatial_factors), len(dims), len(identity),
    ))
    fh.write(struct.pack(f"<{len(WCTS_ADDR_FIELDS)}i", *WCTS_ADDR_FIELDS))
    for dim_id in sorted(spatial_factors):
        fh.write(struct.pack("<ii", dim_id, spatial_factors[dim_id]))
    for dim_id in sorted(dims):
        fh.write(struct.pack("<ii", dim_id, dims[dim_id]))
    fh.write(identity)


def write_tile_frame(fh, *, tile_index, mac_cycles, cores) -> int:
    """Writes one tile frame and returns the number of burst records written.
    `cores` is [(core_id, [(local_tick, (kh, kw, cin, run_start, run_end)), ...]),
    ...], which MUST be sorted by core_id and, inside each core, by local_tick.
    A core with no bursts must be omitted, never passed as an empty list."""
    payload_bytes = sum(8 + _WCTS_BURST_BYTES * len(bursts) for _cid, bursts in cores)
    fh.write(struct.pack("<iiqQ", tile_index, len(cores), mac_cycles, payload_bytes))

    total = 0
    prev_core = -1
    for core_id, bursts in cores:
        if core_id <= prev_core:
            raise ValueError(f"write_tile_frame: core_id {core_id} not ascending in tile {tile_index}")
        if not bursts:
            raise ValueError(f"write_tile_frame: core {core_id} in tile {tile_index} has no bursts; omit it")
        prev_core = core_id
        fh.write(struct.pack("<ii", core_id, len(bursts)))
        prev_tick = -1
        for local_tick, addr in bursts:
            if local_tick <= prev_tick:
                raise ValueError(
                    f"write_tile_frame: local_tick {local_tick} not strictly ascending in "
                    f"core {core_id} of tile {tile_index} (previous {prev_tick})"
                )
            prev_tick = local_tick
            fh.write(struct.pack("<q5i", local_tick, *addr))
        total += len(bursts)
    return total


def write_stream_trailer(fh, total_bursts: int) -> None:
    """Writes the -1 end magic and the total burst count."""
    fh.write(struct.pack("<iQ", WCTS_END_MAGIC, total_bursts))


def _wcts_tile_frames(tiles, n_cores):
    """tick-major -> core-major, the one conversion where a mistake is
    invisible. Returns (frames, burst_span), burst_span being the MAXIMUM span
    over the layer's bursts and frames being
    [(mac_cycles, [(core_id, [(tick, addr), ...]), ...]), ...]. Ticks are
    neither renumbered nor re-sorted and an absent core is never padded:
    t.ticks is already ascending in tick, so appending in that order is
    already ascending inside each core -- write_tile_frame asserts it."""
    frames = []
    max_span = 0
    for tile in tiles:
        by_core: Dict[int, List[Tuple[int, tuple]]] = {}
        for entry in tile.ticks:
            for core in entry.cores:
                if not 0 <= core.core_id < n_cores:
                    raise ValueError(
                        f"stream_weight_trace: core_id {core.core_id} outside the machine "
                        f"(n_cores={n_cores})"
                    )
                for addr in core.weight_addresses:
                    kh, kw, cin, run_start, run_end = addr
                    if run_end <= run_start:
                        raise ValueError(
                            f"stream_weight_trace: empty run [{run_start}, {run_end}) "
                            f"on core {core.core_id}"
                        )
                    max_span = max(max_span, run_end - run_start)
                    by_core.setdefault(core.core_id, []).append(
                        (entry.tick, (kh, kw, cin, run_start, run_end))
                    )
        frames.append((tile.mac_cycles, [(cid, by_core[cid]) for cid in sorted(by_core)]))

    if max_span == 0:
        raise ValueError("stream_weight_trace: no bursts, so there is no burst_span to declare")
    return frames, max_span


def stream_weight_trace(trace: LayerWeightTrace, fh, *, n_cores, spatial_factors,
                        burst_dim=3, burst_stride=1, weight_bytes=1,
                        max_tiles=None) -> int:
    """Writes one whole LayerWeightTrace as a WCTS stream to the binary file
    object `fh`, header first, and returns the total burst count. The sibling to
    save_weight_trace: same data, a stream instead of a document, and no
    intermediate storage. `max_tiles` truncates the stream after that many tile
    frames, which is what --dump-trace-tiles uses to produce a valid short
    stream. Does not close `fh`.

    `burst_span` is measured from the addresses themselves rather than taken
    from a caller, because ruling R1 puts the burst axis and its geometry on
    this side of the pipe; the reader is not asked to supply any of it. It is
    the maximum burst span in this layer, used to size l1_demand_reserve; each
    burst's actual extent is derivable from its own run_start and run_end, so a
    ragged final run is emitted normally."""
    tiles = trace.tiles if max_tiles is None else trace.tiles[:max_tiles]
    # max_tiles is applied before the header, because n_tiles is a header field.
    frames, burst_span = _wcts_tile_frames(tiles, n_cores)

    write_stream_header(
        fh, n_tiles=len(frames), n_cores=n_cores, weight_bytes=weight_bytes,
        burst_dim=burst_dim, burst_stride=burst_stride, burst_span=burst_span,
        spatial_factors=spatial_factors,
        dims={WCTS_DIM_CODES[name]: int(extent)
              for name, extent in trace.workload_dims.items() if name in WCTS_DIM_CODES},
        arch=trace.arch, workload=trace.trace_dir, layer=trace.layer_name,
        sample_idx=trace.sample_idx,
    )
    total_bursts = 0
    for tile_index, (mac_cycles, cores) in enumerate(frames):
        total_bursts += write_tile_frame(fh, tile_index=tile_index,
                                         mac_cycles=mac_cycles, cores=cores)
    write_stream_trailer(fh, total_bursts)
    return total_bursts


_CANONICAL_N = 100
_CANONICAL_SEED = 0  # the seed configs/sampling/sample_indices.json was generated with


def sample_indices(n: int = 100, seed: int = 0, n_total: int = 10000) -> List[int]:
    """A fixed, reproducible n-sample subset of range(n_total), drawn live
    via random.Random -- no stored/hardcoded index list (replaces the now-
    deleted configs/sampling/sample_indices.json and the old
    canonical_sample_indices()/random_sample_indices() pair).

    `sample_indices()` (n=100, seed=0) is THE canonical 100-sample subset
    used everywhere a representative random sample (as opposed to the full
    10,000-sample sweep) is needed, so different callers never silently
    diverge onto their own random selections; verified to reproduce, byte
    for byte, the values previously hardcoded in that deleted JSON file.

    For n > 100, always a superset of that same canonical 100 (drawn at
    _CANONICAL_SEED regardless of `seed`) plus n-100 more drawn at `seed`
    from the remaining pool -- so growing n never discards
    already-generated work on the canonical 100 or on any smaller n at the
    same seed, matching every real n>100 call in this pipeline (e.g. the
    4000-sample sweep), which has always used seed=0 for both parts.

    Raises ValueError if n < 100."""
    base = sorted(random.Random(_CANONICAL_SEED).sample(range(n_total), _CANONICAL_N))
    if n < _CANONICAL_N:
        raise ValueError(f"sample_indices: n={n} smaller than the canonical {_CANONICAL_N}-sample base")
    if n == _CANONICAL_N:
        return base
    remaining_pool = [i for i in range(n_total) if i not in set(base)]
    extra = random.Random(seed).sample(remaining_pool, n - _CANONICAL_N)
    return sorted(base + extra)
