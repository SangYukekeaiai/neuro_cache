"""FLITS_PER_PACKET: Python and the compiled eventsim must use one value.

The value is defined once in src/nocsim/eventsim/constants.h; EventSim.h
includes it and nocsim.core.transaction parses it. This test drives the
built binary, so it also catches a binary that is stale against the header.

A unicast that does not touch the DRAM port costs `hops + size *
FLITS_PER_PACKET` cycles (EventSim.h), so two sends that differ only in
`size` differ by exactly `delta_size * FLITS_PER_PACKET` cycles.

Row format (see Transaction.h): tc_id,actor,op,size,srcs,dests,deps
op 0 is UNICAST.
"""
import json
import pathlib
import subprocess

import pytest

from nocsim.core.transaction import FLITS_PER_PACKET

REPO = pathlib.Path(__file__).resolve().parents[1]
BINARY = REPO / "src/nocsim/eventsim/eventsim"


def _unicast_cycles(size, tmp_path):
    csv = tmp_path / f"unicast_{size}.csv"
    csv.write_text(f"0,0,0,{size},0,1,\n")
    r = subprocess.run(
        [str(BINARY), str(csv), "--X", "4", "--Y", "4",
         "--dram-port", "33", "--dram-latency", "1"],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)["total_cycles"]


def test_eventsim_uses_python_flits_per_packet(tmp_path):
    if not BINARY.exists():
        pytest.skip(f"no eventsim binary at {BINARY} (make -C src/nocsim/eventsim)")
    per_packet = (_unicast_cycles(20, tmp_path) - _unicast_cycles(10, tmp_path)) // 10
    assert per_packet == FLITS_PER_PACKET
