"""Task 7: the Python writer and the C++ reader must agree on the wire format.

Checks the byte layout the WCTS section of
log/2026-08-20-phaseD-implementation-plan.md defines, with `i32 burst_span`
added beside burst_dim and burst_stride (coordinator ruling Q-D), which puts
the fixed header at 56 bytes and n_addr_fields at offset 40.

Run: PYTHONPATH=src python tests/test_stream_writer.py
"""
import io
import json
import pathlib
import struct
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from tracegen import (CoreEntry, LayerWeightTrace, TickEntry,  # noqa: E402
                      TileWeightTrace, stream_weight_trace)

FIXED_HEADER_BYTES = 56
EXAMPLES = REPO / "src" / "wcache" / "examples"


def tiny_trace():
    t0 = TileWeightTrace(dram_i=0, noc_i=0, mac_cycles=10, lif_cycles=None, ticks=[
        TickEntry(tick=0, cores=[CoreEntry(core_id=0, weight_addresses=[[1, 1, 6, 0, 16]]),
                                 CoreEntry(core_id=2, weight_addresses=[[0, 0, 0, 16, 32]])]),
        TickEntry(tick=1, cores=[CoreEntry(core_id=0, weight_addresses=[[1, 1, 7, 0, 16]])]),
    ])
    t1 = TileWeightTrace(dram_i=0, noc_i=1, mac_cycles=8, lif_cycles=None, ticks=[
        TickEntry(tick=0, cores=[CoreEntry(core_id=1, weight_addresses=[[2, 2, 2, 0, 16]])]),
    ])
    return LayerWeightTrace(arch="loas", trace_dir="vgg16_T4_all",
                            layer_name="layer_01_features_3", sample_idx=0,
                            workload_dims={"KH": 3, "KW": 3, "CIN": 64, "COUT": 64,
                                           "HO": 32, "WO": 32, "T": 4},
                            dram_num_steps=1, noc_num_steps=2, tiles=[t0, t1])


def test_header_and_frames():
    buf = io.BytesIO()
    total = stream_weight_trace(tiny_trace(), buf, n_cores=4, spatial_factors={3: 4})
    assert total == 4, total
    data = buf.getvalue()
    assert data[:8] == b"WCTRACE1"
    version, header_bytes = struct.unpack_from("<II", data, 8)
    assert version == 1
    n_tiles, n_cores, weight_bytes, burst_dim, burst_stride, burst_span = struct.unpack_from(
        "<iiiiii", data, 16)
    assert (n_tiles, n_cores, weight_bytes) == (2, 4, 1)
    assert (burst_dim, burst_stride, burst_span) == (3, 1, 16)
    n_addr, n_spatial, n_dims, ident = struct.unpack_from("<iiii", data, 40)
    assert (n_addr, n_spatial, n_dims) == (5, 1, 7)
    assert header_bytes == FIXED_HEADER_BYTES + 4 * n_addr + 8 * n_spatial + 8 * n_dims + ident
    assert list(struct.unpack_from("<5i", data, FIXED_HEADER_BYTES)) == [0, 1, 2, 3, 4]
    # The identity block: four NUL-terminated UTF-8 fields.
    ident_off = header_bytes - ident
    assert data[ident_off:header_bytes] == b"loas\0vgg16_T4_all\0layer_01_features_3\0" b"0\0"
    # First tile frame, immediately after the header.
    tile_index, n_blocks, mac, payload = struct.unpack_from("<iiqQ", data, header_bytes)
    assert (tile_index, n_blocks, mac) == (0, 2, 10)
    # Two core blocks: core 0 with 2 bursts, core 2 with 1 burst.
    assert payload == (8 + 2 * 28) + (8 + 1 * 28), payload
    off = header_bytes + 24
    core_id, n_bursts = struct.unpack_from("<ii", data, off)
    assert (core_id, n_bursts) == (0, 2)
    tick0, kh, kw, cin, run_start, run_end = struct.unpack_from("<q5i", data, off + 8)
    assert (tick0, kh, kw, cin, run_start, run_end) == (0, 1, 1, 6, 0, 16)
    # Trailer.
    end_magic, total_bursts = struct.unpack_from("<iQ", data, len(data) - 12)
    assert end_magic == -1 and total_bursts == 4


def test_spatial_product_must_match_n_cores():
    buf = io.BytesIO()
    try:
        stream_weight_trace(tiny_trace(), buf, n_cores=8, spatial_factors={3: 4})
    except ValueError:
        return
    raise AssertionError("expected ValueError: prod(spatial_factors) != n_cores")


def test_core_id_beyond_the_machine_is_rejected():
    buf = io.BytesIO()
    try:
        stream_weight_trace(tiny_trace(), buf, n_cores=2, spatial_factors={3: 2})
    except ValueError:
        return
    raise AssertionError("expected ValueError: core_id 2 >= n_cores 2")


def test_max_tiles_truncates_to_a_valid_short_stream():
    buf = io.BytesIO()
    total = stream_weight_trace(tiny_trace(), buf, n_cores=4, spatial_factors={3: 4},
                                max_tiles=1)
    data = buf.getvalue()
    n_tiles = struct.unpack_from("<i", data, 16)[0]
    assert n_tiles == 1, "the header must declare the TRUNCATED tile count"
    end_magic, total_bursts = struct.unpack_from("<iQ", data, len(data) - 12)
    assert end_magic == -1 and total_bursts == total == 3


def test_a_truncated_stream_is_a_byte_prefix_of_the_full_one():
    """What --dump-trace-tiles relies on: the short stream's tile frames are the
    full stream's first frames, byte for byte."""
    full, short = io.BytesIO(), io.BytesIO()
    stream_weight_trace(tiny_trace(), full, n_cores=4, spatial_factors={3: 4})
    stream_weight_trace(tiny_trace(), short, n_cores=4, spatial_factors={3: 4}, max_tiles=1)
    fd, sd = full.getvalue(), short.getvalue()
    hb = struct.unpack_from("<I", fd, 12)[0]
    assert hb == struct.unpack_from("<I", sd, 12)[0], "headers must be the same length"
    body = sd[hb:len(sd) - 12]
    assert fd[hb:hb + len(body)] == body


def test_non_ascending_tick_inside_a_core_is_rejected():
    trace = tiny_trace()
    trace.tiles[0].ticks[1].tick = 0  # a second burst for core 0 at the same tick
    buf = io.BytesIO()
    try:
        stream_weight_trace(trace, buf, n_cores=4, spatial_factors={3: 4})
    except ValueError:
        return
    raise AssertionError("expected ValueError: local_tick not strictly ascending")


def test_empty_run_is_rejected():
    trace = tiny_trace()
    trace.tiles[1].ticks[0].cores[0].weight_addresses = [[2, 2, 2, 8, 8]]
    buf = io.BytesIO()
    try:
        stream_weight_trace(trace, buf, n_cores=4, spatial_factors={3: 4})
    except ValueError:
        return
    raise AssertionError("expected ValueError: run_end <= run_start")


def test_ragged_final_run_carries_the_maximum_span():
    """A layer whose last COUT run is short is emitted normally: the header
    declares the MAXIMUM span, and each burst's own run_start/run_end still
    give that burst's true extent."""
    trace = tiny_trace()
    trace.tiles[1].ticks[0].cores[0].weight_addresses = [[2, 2, 2, 0, 5]]
    buf = io.BytesIO()
    stream_weight_trace(trace, buf, n_cores=4, spatial_factors={3: 4})
    header, tiles, _total = decode_stream(buf.getvalue())
    assert header["burst_span"] == 16, header["burst_span"]
    extents = sorted(addr[4] - addr[3]
                     for _i, _m, cores in tiles for _cid, bursts in cores
                     for _tick, addr in bursts)
    assert extents == [5, 16, 16, 16], extents


def decode_stream(data):
    """The reader half, in Python: (header dict, [(tile_index, mac_cycles,
    [(core_id, [(tick, addr), ...]), ...]), ...], total_bursts)."""
    assert data[:8] == b"WCTRACE1"
    fields = struct.unpack_from("<IIiiiiiiiiii", data, 8)
    keys = ("format_version", "header_bytes", "n_tiles", "n_cores", "weight_bytes",
            "burst_dim", "burst_stride", "burst_span", "n_addr_fields", "n_spatial",
            "n_dims", "identity_bytes")
    h = dict(zip(keys, fields))
    off = FIXED_HEADER_BYTES
    h["addr_fields"] = list(struct.unpack_from(f"<{h['n_addr_fields']}i", data, off))
    off += 4 * h["n_addr_fields"]
    h["spatial_factors"] = dict(struct.unpack_from("<ii", data, off + 8 * i)
                                for i in range(h["n_spatial"]))
    off += 8 * h["n_spatial"]
    h["dims"] = dict(struct.unpack_from("<ii", data, off + 8 * i) for i in range(h["n_dims"]))
    off += 8 * h["n_dims"]
    h["identity"] = data[off:off + h["identity_bytes"]].decode().rstrip("\0").split("\0")
    off += h["identity_bytes"]
    assert off == h["header_bytes"], (off, h["header_bytes"])

    tiles = []
    for expected_index in range(h["n_tiles"]):
        tile_index, n_blocks, mac_cycles, payload = struct.unpack_from("<iiqQ", data, off)
        assert tile_index == expected_index
        off += 24
        frame_end = off + payload
        cores = []
        for _ in range(n_blocks):
            core_id, n_bursts = struct.unpack_from("<ii", data, off)
            off += 8
            bursts = []
            for _ in range(n_bursts):
                tick = struct.unpack_from("<q", data, off)[0]
                addr = struct.unpack_from("<5i", data, off + 8)
                off += 28
                bursts.append((tick, addr))
            cores.append((core_id, bursts))
        assert off == frame_end, "payload_bytes disagrees with the frame it describes"
        tiles.append((tile_index, mac_cycles, cores))
    end_magic, total_bursts = struct.unpack_from("<iQ", data, off)
    assert end_magic == -1
    assert off + 12 == len(data), "trailing bytes after the trailer"
    return h, tiles, total_bursts


def load_fixture(name):
    d = json.loads((EXAMPLES / name).read_text())
    tiles = [TileWeightTrace(
        dram_i=t["dram_i"], noc_i=t["noc_i"], mac_cycles=t["mac_cycles"],
        lif_cycles=t["lif_cycles"],
        ticks=[TickEntry(tick=e["tick"],
                         cores=[CoreEntry(core_id=c["core_id"],
                                          weight_addresses=c["weight_addresses"])
                                for c in e["cores"]])
               for e in t["ticks"]],
    ) for t in d["tiles"]]
    return LayerWeightTrace(
        arch=d["arch"], trace_dir=d["trace_dir"], layer_name=d["layer_name"],
        sample_idx=d["sample_idx"], workload_dims=d["workload_dims"],
        dram_num_steps=d["dram_num_steps"], noc_num_steps=d["noc_num_steps"], tiles=tiles)


def test_round_trip_a_real_fixture():
    """The checked-in v2 slices are real corpus data (8 cores, 2 tiles), which
    pins the emitter against something the hand-built trace cannot."""
    trace = load_fixture("loas_vgg16_layer01_v2.json")
    buf = io.BytesIO()
    total = stream_weight_trace(trace, buf, n_cores=8, spatial_factors={3: 8})
    header, tiles, total_bursts = decode_stream(buf.getvalue())
    assert total == total_bursts == 384, total
    assert header["n_tiles"] == len(trace.tiles) == 2
    assert header["identity"] == ["loas", "vgg16_T4_all", "layer_01_features_3", "0"]
    assert sorted(cid for cid, _ in tiles[0][2]) == list(range(8))
    # Every burst the fixture holds must come back, unchanged.
    flat_in = sorted((e.tick, c.core_id, tuple(a))
                     for t in trace.tiles for e in t.ticks for c in e.cores
                     for a in c.weight_addresses)
    flat_out = sorted((tick, cid, addr)
                      for _i, _m, cores in tiles for cid, bursts in cores
                      for tick, addr in bursts)
    assert flat_in == flat_out


if __name__ == "__main__":
    test_header_and_frames()
    test_spatial_product_must_match_n_cores()
    test_core_id_beyond_the_machine_is_rejected()
    test_max_tiles_truncates_to_a_valid_short_stream()
    test_a_truncated_stream_is_a_byte_prefix_of_the_full_one()
    test_non_ascending_tick_inside_a_core_is_rejected()
    test_empty_run_is_rejected()
    test_ragged_final_run_carries_the_maximum_span()
    test_round_trip_a_real_fixture()
    print("test_stream_writer: OK")
