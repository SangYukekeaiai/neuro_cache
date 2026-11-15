import csv
import json
import subprocess
import sys
from pathlib import Path
from zoo.fig12_edp.energy_driver import MODEL_ROOT, CACHE_CONFIGS

ROOT = MODEL_ROOT / "characterization"
sys.path.insert(0, str(ROOT))
import energy_harvest as harvest
ARCHX = MODEL_ROOT.parents[1]


def test_config_geometry_matches_energy_hardware(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path, "cache")
    configs = [json.loads((CACHE_CONFIGS / f"production_cache_{arm}.json").read_text()) for arm in ("a", "b")]
    for config in configs:
        for level in ("l1", "l2"):
            query = rows[f"cache.{level}.read"]["query"]
            assert query["class"] == "cache"
            assert query["size"] // 8 == config[level + "_size_bytes"]
            assert query["associativity"] == config[level + "_assoc"]
            assert rows[f"cache.mshr_cam_{level}.search"]["query"]["depth"] == config[level + "_mshrs"]
    assert configs[0]["l1_prefetch_distance"] == 4
    assert configs[0]["l2_prefetch_distance"] == 1
    assert configs[0]["l2_prefetch_min_touches"] == 9
    assert configs[1]["l2_prefetch_distance"] == 1
    for level in ("l1", "l2"):
        assert configs[1][level + "_prefetch_policy"] == "next_line"
        assert configs[1][level + "_prefetch_distance"] == 1
    assert configs[0]["l2_mshrs"] == configs[1]["l2_mshrs"] == 32


def test_both_configs_in_native_simulator(tmp_path):
    harvest.cap_threads()
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "src"))
    from lays.cachesim.stream import write_stream_header, write_tile_frame, write_stream_trailer
    trace = tmp_path / "sample.wcts"
    with trace.open("wb") as stream:
        write_stream_header(stream, n_tiles=1, n_cores=16, weight_bytes=1, burst_dim=3,
                            burst_stride=1, burst_span=4, spatial_factors={3: 16},
                            dims={0: 1, 1: 1, 2: 16, 3: 64, 4: 1, 5: 1, 6: 1},
                            arch="loas", workload="cache_validation", layer="small", sample_idx=0)
        total = write_tile_frame(stream, tile_index=0, mac_cycles=1,
                                 cores=[(0, [(0, (0, 0, 0, 0, 4))])], burst_dim=3)
        write_stream_trailer(stream, total)
    results = []
    for arm in ("a", "b"):
        output = tmp_path / (arm + ".csv")
        subprocess.run([str(repo / "src/lays/cachesim/native/build/release/cachesim_run"),
                        "--config", str(CACHE_CONFIGS / f"production_cache_{arm}.json"),
                        "--trace", str(trace), "--arm", "cache", "--header", "--out", str(output)], check=True)
        row, = list(csv.DictReader(output.open()))
        assert int(row["total_cycles"]) > 0
        assert int(row["dram_bytes"]) == int(row["dram_accesses"]) * 64
        assert int(row["l2_mshrs"]) == 32
        if arm == "b":
            assert row["prefetch_policy"] == "next_line"
            assert row["l2_prefetch_policy"] == "next_line"
        results.append(row)

    assert results[0]["dram_accesses"] != results[1]["dram_accesses"]




def test_production_configs_are_byte_pinned():
    import hashlib
    from zoo.fig12_edp.energy_driver import CACHE_CONFIG_SHA256, check_cache_configs
    paths = [CACHE_CONFIGS/f'production_cache_{arm}.json' for arm in ('a', 'b')]
    for arm, path in zip(('a', 'b'), paths):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == CACHE_CONFIG_SHA256[arm]
    check_cache_configs(*paths)


import pytest


@pytest.mark.parametrize('arm', ['a', 'b'])
def test_remote_runner_rejects_altered_config(tmp_path, arm):
    import importlib.util
    path = Path(__file__).resolve().parents[1]/'run_ec2/config.py'
    spec = importlib.util.spec_from_file_location('pin_test_remote_config', path)
    remote = importlib.util.module_from_spec(spec); spec.loader.exec_module(remote)
    cfg = remote.load(path.with_name('mini.json'))
    changed = tmp_path/(arm+'.json')
    changed.write_bytes(Path(cfg['cache_'+arm]).read_bytes()+b'\n')
    cfg['cache_'+arm] = str(changed)
    with pytest.raises(ValueError, match=f'cache {arm.upper()} differs from pinned SHA256'):
        remote.scientific_inputs(cfg)
