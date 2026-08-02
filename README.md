# neuro_cache

Two-stage pipeline for spiking neural network (SNN) hardware scheduling and
simulation:

1. **`mip_solver`**: a Gurobi-based scheduler. Parses a layer shape,
   hardware memory hierarchy, and optional mapspace description, builds a
   mixed-integer model, solves for a schedule, and writes the selected
   factor placement as JSON to `outputs/schedules/`.
2. **`nocsim`**: consumes a solved schedule and generates the real NoC/DRAM
   transactions and compute-latency breakdown for it.

`archmodels` holds 5 single-node hardware configs (GustavSNN, LoAS,
Prosperity, PTB, SpinalFlow) used together with `tracegen.py` to reconstruct
per-tile weight-address traces from real captured spike data, feeding the
external `neuro_cache_trace` tool.

## Project layout

```text
configs/
  arch/                           hardware topology, capacities, and bit widths
  dataflow/                       NodeLevel dimension mapping constraints
  mapspace/mapspace.yaml          dimensions eligible for spatial mapping
  workloads/sample_snn_layer.yaml sample SNN layer dimensions
src/
  parsers/                        YAML parsers for layer, arch, dataflow, bit widths, mapspace
  mip_solver/                     constants, variables, constraints, objectives, cli
  mip_solver/solve.py             model assembly, solve, schedule extraction
  nocsim/                         NoC/DRAM transaction generation + compute latency
  archmodels/                     5 single-node hardware configs + shared trace loader
  tracegen.py                     solve + reconstruct + persist, for weight-trace generation
  util.py                         shared output-formatting utilities
outputs/                          generated schedules (schedules/) and weight traces (weight_traces/)
log/                              dated progress/design notes
dump/                             archived design docs and historical plans
requirements.txt                  Python runtime dependencies
```

## Environment

Use the `cosa_snn` conda environment:

```bash
conda activate cosa_snn
export PYTHONPATH=src
python -m pip install -r requirements.txt
```

The solver requires a working Gurobi license. This project was checked with:

```text
gurobipy==13.0.2
numpy==2.4.6
PyYAML==6.0.3
matplotlib
```

## Inputs

Layer YAML:

```yaml
problem:
  KH: 3
  KW: 3
  CIN: 64
  COUT: 128
  HO: 56
  WO: 56
  T: 16
```

Architecture YAML:

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM: 16
    BW_VMEM: 32
  storage:
    - name: NodeLevel
      instances: 1024
      pe:
        num_pes: 1024
        registers:
          entries:
            weight: 128
            psum: 128
            vmem: 256
          bitwidths:
            weight: 8
            psum: 16
            vmem: 32
      local_buffer:
        entries:
          weight: 1024
          psum: 1024
          vmem: 2048
    - name: NoCLevel
      entries:
        weight: 16384
        psum: 16384
        vmem: 32768
      instances: 1
    - name: OffChip
      instances: 1
```

Dataflow YAML:

```yaml
dataflow:
  node_dim_capacity:
    KH: 4
    KW: 4
    CIN: full
    COUT: {spatial: 128}
    T: full
```

Mapspace YAML:

```yaml
mapspace:
  spatial_dims: [KH, KW, CIN, COUT, HO, WO, T]
```

## Run

Solve the sample layer:

```bash
python -m mip_solver solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/spinalflow.yaml \
  --dataflow configs/dataflow/spinalflow.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/sample_schedule.json
```

Optional solver controls:

```bash
python -m mip_solver solve --time-limit 60 --mip-gap 0.01 --solver-log
```

Replay the solved schedule through the NoC simulator:

```bash
python -m nocsim.sim \
  --schedule outputs/sample_schedule.json \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/spinalflow.yaml \
  --out outputs/tc.csv
```

## Output

The solver's output JSON contains:

- `status`: Gurobi solve status.
- `objective`: final objective value if a solution exists.
- `strategy.NodeLevel.temporal_tile`: unordered temporal factors assigned to
  NodeLevel. The model does not decide a NodeLevel loop permutation.
- `strategy.NoCLevel.temporal_permutation`: temporal loop factors at NoCLevel.
- `strategy.NoCLevel.spatial_splitting`: spatial split factors at NoCLevel.
- `strategy.DRAM.temporal_permutation`: temporal loop factors at DRAM.

For the included sample config, the verified solve status is `OPTIMAL` with
objective `193.403908`.

`nocsim.sim` writes a `tc.csv` transaction list and prints unicast/multicast
hop counts and DRAM cost per variable (`weight`, `psum`, `vmem`).

## Solver flow

1. Parse layer, architecture, bit widths, and optional mapspace.
2. Create schedule variables `X[(i, j, n, k)]` and reuse variables `y[(v, i)]`.
3. Add assignment, spatial fanout, and capacity constraints.
4. Build data-size, temporal-traffic, and spatial-traffic expressions.
5. Minimize the combined objective.
6. Extract the chosen schedule into JSON-compatible dictionaries.
