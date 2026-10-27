"""The WCTS (weight cache trace stream) writer.

Written by the weight-trace generator (stream_weight_trace); read only by
the cache simulator's C++ reader (native/include/cachesim/stream_format.h).
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from weight_trace_gen.weight_trace import LayerWeightTrace


# ----------------------------------------------------------------------
# WCTS (weight cache trace stream), version 2
#
# The in-flight sibling of save_step_cycles: it carries the weight
# addresses that file leaves out, as a stream, so a producer can feed the cache simulator down a
# pipe with nothing materialized in between (Phase D campaign plan, 10).
# docs/atlas/cachesim_native.md section 1.7 describes the format; the C++
# reader (src/cachesim/native/include/cachesim/stream_format.h) decodes exactly
# these bytes. `burst_span` sits beside burst_dim and burst_stride per
# coordinator ruling Q-D, a later addition to the format -- that is the one
# field to check first if the two sides disagree.
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
# n_dims (dim_id, extent) pairs, and the identity block. Each burst record is
# <q5i: local_tick, then the run's full anchor kh, kw, cin, cout, then run_end.
# The run walks burst_dim from the anchor's coordinate on that axis to run_end.
# ----------------------------------------------------------------------

WCTS_MAGIC = b"WCTRACE1"
WCTS_VERSION = 2
WCTS_FIXED_HEADER_BYTES = 56
WCTS_END_MAGIC = -1

# Wire codes, deliberately independent of any enum elsewhere so a
# renumbering there cannot silently change the format.
WCTS_DIM_CODES = {"KH": 0, "KW": 1, "CIN": 2, "COUT": 3, "HO": 4, "WO": 5, "T": 6}
# 0=KH 1=KW 2=CIN 3=COUT 4=RUN_END. For a COUT burst this is the
# [kh, kw, cin, cout_start, cout_end] address record every arch already emits.
WCTS_ADDR_FIELDS = (0, 1, 2, 3, 4)
_WCTS_BURST_BYTES = 8 + 4 * len(WCTS_ADDR_FIELDS)


def write_stream_header(fh, *, n_tiles, n_cores, weight_bytes, burst_dim,
                        burst_stride, burst_span, spatial_factors, dims,
                        arch, workload, layer, sample_idx) -> None:
    """Writes the WCTS stream header. `spatial_factors` and `dims` are
    {dim_id: value} mappings using the wire codes 0=KH 1=KW 2=CIN 3=COUT
    4=HO 5=WO 6=T. `burst_dim` is one of those codes. Raises ValueError when
    prod(spatial_factors.values()) != n_cores, which is U25's check on the
    producer side, when `dims` is not exactly the seven codes, and when
    `burst_dim` is not one of KH, KW, CIN, COUT (0..3)."""
    if burst_dim not in (0, 1, 2, 3):
        raise ValueError(f"write_stream_header: burst_dim {burst_dim} is not one of 0=KH 1=KW 2=CIN 3=COUT")
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


def write_tile_frame(fh, *, tile_index, mac_cycles, cores, burst_dim) -> int:
    """Writes one tile frame and returns the number of burst records written.
    `cores` is [(core_id, [(local_tick, (kh, kw, cin, cout, run_end)), ...]),
    ...], which MUST be sorted by core_id and, inside each core, by local_tick.
    A core with no bursts must be omitted, never passed as an empty list.
    Raises ValueError when a run is empty along `burst_dim`, i.e. run_end is
    not past the anchor's coordinate on that axis."""
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
            if addr[4] <= addr[burst_dim]:
                raise ValueError(
                    f"write_tile_frame: empty run [{addr[burst_dim]}, {addr[4]}) along "
                    f"burst_dim {burst_dim} in core {core_id} of tile {tile_index}"
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
                    kh, kw, cin, cout_start, cout_end = addr
                    if cout_end <= cout_start:
                        raise ValueError(
                            f"stream_weight_trace: empty run [{cout_start}, {cout_end}) "
                            f"on core {core.core_id}"
                        )
                    max_span = max(max_span, cout_end - cout_start)
                    by_core.setdefault(core.core_id, []).append(
                        (entry.tick, (kh, kw, cin, cout_start, cout_end))
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
    save_step_cycles: it carries the weight addresses that file leaves out,
    with no intermediate storage. `max_tiles` truncates the stream after that many tile
    frames, which is what --dump-trace-tiles uses to produce a valid short
    stream. Does not close `fh`.

    `burst_span` is measured from the addresses themselves rather than taken
    from a caller, because ruling R1 puts the burst axis and its geometry on
    this side of the pipe; the reader is not asked to supply any of it. It is
    the maximum burst span in this layer, used to size l1_demand_reserve; each
    burst's actual extent is derivable from its own cout_start and cout_end, so
    a ragged final run is emitted normally. The addresses are COUT runs, which
    are exactly v2 records [kh, kw, cin, cout, run_end] with burst_dim 3, so any
    other `burst_dim` is refused rather than mislabelled."""
    if burst_dim != 3:
        raise ValueError(
            "stream_weight_trace: LayerWeightTrace addresses are [kh, kw, cin, cout_start, "
            "cout_end] COUT runs, so burst_dim must be 3; write a non-COUT stream with "
            "write_stream_header and write_tile_frame"
        )
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
                                         mac_cycles=mac_cycles, cores=cores, burst_dim=3)
    write_stream_trailer(fh, total_bursts)
    return total_bursts
