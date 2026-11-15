"""Load-bearing count, native-sample replay and resume checks."""

from dataclasses import asdict
import json
from pathlib import Path
import struct

import numpy as np
import pytest
import yaml

from lays.cachesim.stream import stream_weight_trace
from lays.nocsim.core.generator import TC_Generator
from lays.nocsim.core.noc import NoC
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.tiles import iter_node_tiles
from lays.nocsim.step_cycles import save_step_cycles
from lays.parsers.layer import SNNProb
from lays.scheduler.artifact import ScheduleArtifact
from lays.weight_trace_gen.spinalflow import native_bridge

from zoo.fig12_edp.nocsim import parse_tc_csv, run_case
from zoo.fig12_edp.nocsim import driver
from zoo.fig12_edp.nocsim.wcts import load_wcts_cycles

ROOT = Path(__file__).resolve().parents[3]


def test_multicast_edges_endpoints_bursts_and_chains(tmp_path):
    noc = NoC(4, 4)
    gen = TC_Generator(noc)
    gen.unicast("weight", 3 * 256, 8, noc.dram_port, noc.gb_port, [], "dram_0__load_weight")
    gen.unicast("weight", 256, 8, noc.dram_port, noc.gb_port, [], "dram_1__load_weight")
    gen.multicast("weight", 3 * 256, 8, noc.gb_port, [3, 7, 12], [], "weight_0_0__send_3-7-12")
    gen.unicast("weight", 2 * 256, 8, noc.gb_port, 1, [], "weight_0_0__send_1")
    gen.unicast("psum", 256, 16, 0, 4, [], "psum_0_0__kchain_0_4")
    gen.unicast("vmem", 2 * 256, 32, 4, 5, [], "vmem_0_0__tchain_4_5")
    gen.count(10, 0, [], "mac_0_0__count_0")
    path = tmp_path / "tc.csv"
    gen.to_file(path)
    got = parse_tc_csv(path, X=4, Y=4)
    assert got["weight_multicast_packet_hops"] == 24  # routes7,6,1: union8, farthest7, sum14; three packets
    assert got["weight_unicast_packet_hops"] == 10
    assert got["weight_packet_hops"] == 34
    assert (got["k_chain_packet_hops"], got["t_chain_packet_hops"], got["chain_packet_hops"]) == (1, 2, 3)
    assert (got["gb_reads"], got["gb_writes"], got["l1_delivery_bytes"]) == (5, 4, 352)
    assert (got["dram_accesses"], got["dram_bytes"], got["dram_payload_bytes"]) == (3, 192, 128)
    assert got["dram_transactions"] == 2


def test_boundary_traffic_rejected(tmp_path):
    gen = TC_Generator(NoC(2, 2))
    gen.unicast("psum", 256, 16, 4, 0, [], "psum_0_0__load_0")
    path = tmp_path / "tc.csv"
    gen.to_file(path)
    with pytest.raises(ValueError, match="boundary"):
        parse_tc_csv(path, X=2, Y=2)


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    """One tiny sample through the existing native generator, exactly once."""
    dims = dict(KH=1, KW=1, CIN=4, COUT=4, HO=2, WO=1, T=2, shape="snn-layer")
    workload = {"problem": dims}
    layer = tmp_path / "layer.yaml"
    layer.write_text(yaml.safe_dump(workload))
    prob = SNNProb(layer)
    strategy = {
        "NoCLevel": {
            "spatial_splitting": {"loops": [{"dim": "T", "size": 2}, {"dim": "CIN", "size": 2}]},
            "temporal_permutation": {"loops": [{"dim": "HO", "size": 2}]},
        },
        "DRAM": {"temporal_permutation": {"loops": []}},
    }
    schedule = schedule_from_strategy(strategy, prob)
    artifact = ScheduleArtifact(
        "spinalflow", "tiny_native", "layer_0", workload,
        {"has_solution": True, "strategy": strategy,
         "configs": {"arch": str(ROOT / "examples/arch/spinalflow_inst16.yaml")}}, 1)
    path = tmp_path / "schedule.json"
    path.write_text(json.dumps(asdict(artifact)))
    spikes = np.zeros((2, 1, 4, 2, 1), dtype=np.uint8)
    spikes[0, 0, :3, 0, 0] = 1
    spikes[1, 0, 1:, 0, 0] = 1
    spikes[:, 0, 0, 1, 0] = 1
    tiles = list(iter_node_tiles(schedule, prob))
    core_cycles = {}
    original = native_bridge._unpack_output

    def capture(*args):
        for record in original(*args):
            tile = tiles[record[0]]
            core_cycles.setdefault((tile.dram_i, tile.noc_i), []).append(record[2])
            yield record

    monkeypatch.setattr(native_bridge, "_unpack_output", capture)
    trace, = native_bridge.reconstruct_samples_native(
        spikes, tiles, [0], artifact.arch, artifact.trace_dir, artifact.layer_name, dims, 1)
    wcts, steps = tmp_path / "sample_00000.wcts", tmp_path / "sample_00000.json.gz"
    with wcts.open("wb") as stream:
        stream_weight_trace(trace, stream, n_cores=4, spatial_factors=schedule.spatial_factors)
    save_step_cycles(trace, steps)
    return path, wcts, steps, artifact, schedule, core_cycles


def test_native_sample_smoke_and_max_reduction(native_case, tmp_path):
    path, wcts, steps, artifact, schedule, core_cycles = native_case
    extracted = load_wcts_cycles(wcts, artifact, schedule)
    assert any(max(c) < sum(c) for c in core_cycles.values())
    for key, c in extracted.by_step.items():
        assert c.mac_cycles == max(core_cycles[key])
    result = run_case(path, "spinalflow", wcts, tmp_path / "wcts_run")
    from_steps = run_case(path, "spinalflow", output_dir=tmp_path / "steps_run", steps_path=steps)
    assert result["tc_sha256"] == from_steps["tc_sha256"]
    assert result["eventsim"] == from_steps["eventsim"]
    assert result["total_cycles"] > 0
    assert result["k_chain_packet_hops"] > 0 and result["t_chain_packet_hops"] > 0
    assert result["dram_bytes"] == result["dram_accesses"] * 64
    assert result["time_seconds"] == result["total_cycles"] / 500_000_000
    print("native sample smoke:", json.dumps({k: result[k] for k in (
        "weight_packet_hops", "chain_packet_hops", "gb_reads", "gb_writes",
        "l1_delivery_bytes", "dram_accesses", "dram_bytes", "total_cycles")}, sort_keys=True))
    print("native per-core cycles:", core_cycles)


def test_resume_checks_inputs_and_output(native_case, tmp_path, monkeypatch):
    path, wcts, *_ = native_case
    output = tmp_path / "resume"
    first = run_case(path, "spinalflow", wcts, output)
    before = (output / "tc.csv").stat().st_mtime_ns

    def forbidden(*args, **kwargs):
        raise AssertionError("resume regenerated transactions")

    monkeypatch.setattr(driver, "combine", forbidden)
    assert run_case(path, "spinalflow", wcts, output) == first
    assert (output / "tc.csv").stat().st_mtime_ns == before
    with pytest.raises(ValueError, match="input hashes"):
        run_case(path, "spinalflow", wcts, output, frequency_hz=250_000_000)
    saved = path.read_bytes()
    path.write_bytes(saved + b"\n")
    with pytest.raises(ValueError, match="input hashes"):
        run_case(path, "spinalflow", wcts, output)
    path.write_bytes(saved)
    sample_bytes = wcts.read_bytes()
    wcts.write_bytes(sample_bytes + b"x")
    with pytest.raises(ValueError, match="input hashes"):
        run_case(path, "spinalflow", wcts, output)
    wcts.write_bytes(sample_bytes)
    with (output / "tc.csv").open("a") as stream:
        stream.write("# corrupted output\n")
    with pytest.raises(ValueError, match="checksum"):
        run_case(path, "spinalflow", wcts, output)


def test_failed_simulation_leaves_no_committed_result(native_case, tmp_path, monkeypatch):
    path, wcts, *_ = native_case
    output = tmp_path / "failed"
    original = driver.run_eventsim

    def fail(*args, **kwargs):
        raise RuntimeError("simulation interrupted")

    monkeypatch.setattr(driver, "run_eventsim", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        run_case(path, "spinalflow", wcts, output)
    assert not (output / "result.json").exists() and not (output / "tc.csv").exists()
    monkeypatch.setattr(driver, "run_eventsim", original)
    assert run_case(path, "spinalflow", wcts, output)["total_cycles"] > 0


def test_wcts_v3_same_stored_cycles(native_case, tmp_path):
    _, wcts, _, artifact, schedule, _ = native_case
    data = bytearray(wcts.read_bytes())
    struct.pack_into("<I", data, 8, 3)
    version3 = tmp_path / "version3.wcts"
    version3.write_bytes(data)
    assert load_wcts_cycles(version3, artifact, schedule) == load_wcts_cycles(wcts, artifact, schedule)


@pytest.mark.parametrize("damage", ["truncated", "version", "payload", "trailer", "identity"])
def test_wcts_malformed_rejected(native_case, tmp_path, damage):
    _, wcts, _, artifact, schedule, _ = native_case
    data = bytearray(wcts.read_bytes())
    if damage == "truncated":
        data = data[:-14]
    elif damage == "version":
        struct.pack_into("<I", data, 8, 99)
    elif damage == "payload":
        header = struct.unpack_from("<I", data, 12)[0]
        struct.pack_into("<Q", data, header + 16, 2**63)
    elif damage == "trailer":
        struct.pack_into("<Q", data, len(data) - 8, 99)
    else:
        data = data.replace(b"tiny_native", b"wrong_layer")
    broken = tmp_path / "broken.wcts"
    broken.write_bytes(data)
    with pytest.raises(ValueError):
        load_wcts_cycles(broken, artifact, schedule)


def test_steps_mismatch_and_boundary_flags_rejected(native_case, tmp_path):
    path, _, steps, *_ = native_case
    doc = json.loads(path.read_text())
    doc["layer_name"] = "different_layer"
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="layer_name"):
        run_case(path, "spinalflow", steps, tmp_path / "wrong_layer")
    doc["result"]["strategy"]["NoCLevel"]["temporal_permutation"]["loops"] = [
        {"dim": "CIN", "size": 2}, {"dim": "HO", "size": 2}]
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="free psum/vmem"):
        run_case(path, "spinalflow", steps, tmp_path / "nonfree")
