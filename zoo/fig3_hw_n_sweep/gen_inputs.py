"""Generate single-node SpinalFlow hardware-size sweep architectures and mappings."""

import json
from pathlib import Path

from lays.parsers.layer import DIM_COUT, DIM_HO, DIM_WO
from lays.scheduler.artifact import check_schedule_matches_trace
from lays.weight_trace_gen.trace import build_workload_from_trace, exclusion_reason, valid_layer_names
from lays.weight_trace_gen.weight_trace import load_schedule, sample_indices

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
HARDWARE_SIZES = (32, 64, 128, 256, 512)
SAMPLE_COUNT = 100
SAMPLE_SEED = 0
SAMPLE_TOTAL = 500
SAMPLE_INDICES = tuple(sample_indices(n=SAMPLE_COUNT, seed=SAMPLE_SEED, n_total=SAMPLE_TOTAL))
SAMPLES = SAMPLE_INDICES
TRACE_ROOT = Path("/lustre/fs1/home/ya867177/data/input_trace_delta/B09")
NETWORKS = {"resnet19": TRACE_ROOT / "loas_resnet19_T4_n500"}


def workloads():
    result = {}
    for network, trace in NETWORKS.items():
        meta = json.loads((trace / "meta.json").read_text())
        result[network] = {layer: build_workload_from_trace(meta, layer)
                           for layer in valid_layer_names(meta)}
    return result


def arch_path(n):
    return ROOT / "inputs/arch" / f"spinalflow_1node_n{n}.yaml"


def schedule_cache(n):
    return ROOT / "inputs/schedules" / f"n{n}"


def schedule_path(network, layer, n):
    return schedule_cache(n) / "spinalflow" / NETWORKS[network].name / f"{layer}.json"


def main():
    feasibility_path = ROOT / "outputs/feasibility/report.json"
    feasibility = json.loads(feasibility_path.read_text())
    assert not feasibility["stride2_supported"], "Reassess the public loader before including stride-2 layers"
    manifest = {
        "hardware_sizes": HARDWARE_SIZES,
        "samples": SAMPLES,
        "sample_selection": {
            "n": SAMPLE_COUNT, "seed": SAMPLE_SEED, "n_total": SAMPLE_TOTAL,
            "indices": SAMPLE_INDICES,
        },
        "networks": {},
    }
    all_workloads = workloads()
    for network, trace in NETWORKS.items():
        meta = json.loads((trace / "meta.json").read_text())
        assert meta["n_samples"] == SAMPLE_TOTAL
        assert feasibility["trace"] == str(trace), (
            f"{feasibility_path} describes {feasibility.get('trace')!r}, expected {trace}"
        )
        assert feasibility["valid_layers"] == list(all_workloads[network])
        manifest["networks"][network] = {
            "arch": meta["arch"],
            "trace": str(trace),
            "included_layers": list(all_workloads[network]),
            "excluded_layers": {name: exclusion_reason(meta, name) for name in meta["layers"]
                                if name not in all_workloads[network]},
        }
    for n in HARDWARE_SIZES:
        path = arch_path(n)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'''arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM: 16
    BW_VMEM: 32
    DRAM_LATENCY: 0.25
  # One node, no physical GB. Capacities constrain the scheduler, not nocsim.
  single_node: true
  storage:
  - name: NodeLevel
    instances: 1
    pe:
      num_pes: {n}
    local_buffer:
      entries:
        weight: {3 * 3 * 512 * n}  # largest tile: 3*3*512*N bytes
        psum: {144 * n}  # 144*N bytes, proportional to hardware node size
        vmem: {144 * n}  # 144*N bytes, proportional to hardware node size
  - name: NoCLevel
    instances: 1  # entries omitted: no physical global buffer
  - name: OffChip
    instances: 1
''')
        for network, layers in all_workloads.items():
            for layer, workload in layers.items():
                problem = workload["problem"]
                active = min(n, problem["COUT"])
                assert problem["COUT"] % active == 0
                loops = [{"dim": dim, "size": problem[dim]} for dim in ("HO", "WO")]
                loops.append({"dim": "COUT", "size": problem["COUT"] // active})
                strategy = {
                    "NodeLevel": {
                        "temporal_tile": {"factors": [{"dim": dim, "size": problem[dim]}
                                                       for dim in ("KH", "KW", "CIN", "T")]},
                        "spatial_split": {"factors": [{"dim": "COUT", "size": active}]},
                    },
                    "NoCLevel": {"temporal_permutation": {"loops": []}, "spatial_splitting": {"loops": []}},
                    "DRAM": {"temporal_permutation": {
                        "order": " -> ".join(f"{loop['dim']}x{loop['size']}" for loop in loops),
                        "loops": loops,
                    }},
                }
                schedule = {
                    "arch": "spinalflow", "trace_dir": NETWORKS[network].name, "layer_name": layer,
                    "workload": workload,
                    "result": {"status": "MANUAL", "has_solution": True, "strategy": strategy},
                    "dram_num_steps": problem["HO"] * problem["WO"] * problem["COUT"] // active,
                    "mode": "base",
                }
                target = schedule_path(network, layer, n)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(schedule, indent=2) + "\n")
                check_schedule_matches_trace(target, NETWORKS[network], layer)
                artifact, _, tiles = load_schedule(target)
                assert len(tiles) == artifact.dram_num_steps
                assert all(tile.core_id == tile.noc_i == 0 and tile.node_bound[DIM_COUT] == active
                           and tile.node_bound[DIM_HO] == tile.node_bound[DIM_WO] == 1 for tile in tiles)
            print(f"N={n}, {network}: {len(layers)} schedules", flush=True)
    manifest_path = ROOT / "inputs/manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
