"""Regression tests for output-tile offsets omitted by 1x1 schedules."""

import importlib
import struct

import pytest

from lays.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO
from lays.weight_trace_gen import NodeTileSpec


BRIDGES = (
    "lays.weight_trace_gen.loas.native_bridge",
    "lays.weight_trace_gen.ptb.native_bridge",
    "lays.weight_trace_gen.spinalflow.native_bridge",
)


def _tile(tile_offset):
    return NodeTileSpec(
        dram_i=2,
        node_bound={
            DIM_HO: 1,
            DIM_WO: 1,
            DIM_KH: 1,
            DIM_KW: 1,
            DIM_CIN: 3,
            DIM_COUT: 4,
            DIM_T: 2,
        },
        tile_offset=tile_offset,
        is_last_K=True,
    )


@pytest.mark.parametrize("bridge_name", BRIDGES)
def test_pack_task_defaults_absent_1x1_output_offsets_to_zero(bridge_name):
    """A 1x1 tile has no HO/WO entries in iter_node_tiles."""
    bridge = importlib.import_module(bridge_name)
    tile = _tile({DIM_CIN: 5, DIM_T: 1, DIM_COUT: 7})

    payload = bridge._pack_task((2, 1, 3, 1, 1), [tile], [0])

    fields = struct.unpack_from("<11i", payload, offset=28)
    assert fields[:3] == (2, 0, 0)
    assert fields[3:] == (1, 1, 5, 3, 1, 2, 7, 4)


@pytest.mark.parametrize("bridge_name", BRIDGES)
def test_pack_task_keeps_explicit_3x3_output_offsets(bridge_name):
    bridge = importlib.import_module(bridge_name)
    tile = _tile({DIM_HO: 4, DIM_WO: 6, DIM_CIN: 5, DIM_T: 1, DIM_COUT: 7})

    payload = bridge._pack_task((2, 1, 3, 8, 9), [tile], [0])

    fields = struct.unpack_from("<11i", payload, offset=28)
    assert fields == (2, 4, 6, 1, 1, 5, 3, 1, 2, 7, 4)
