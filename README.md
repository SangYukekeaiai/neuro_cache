# SNN CoSA

SNN CoSA is a small Gurobi-based scheduler for spiking neural network layer
mapping.  It parses a layer shape, hardware memory hierarchy, and optional
mapspace description, builds a mixed-integer model, solves for a schedule, and
writes the selected factor placement as JSON.

## Project Layout

```text
configs/
  arch/snn_arch.yaml              hardware memory hierarchy and bit widths
  mapspace/mapspace.yaml          dimensions eligible for spatial mapping
  workloads/sample_snn_layer.yaml sample SNN layer dimensions
src/snn_cosa/
  parsers/                        YAML parsers for layer, arch, bit widths, mapspace
  model/                          constants, variables, constraints, objectives
  solver.py                       model assembly, solve, schedule extraction
  cli.py                          command-line interface
COMMANDS.md                       copyable command reference
requirements.txt                  Python runtime dependencies
outputs/                          generated schedule JSON files
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

Mapspace YAML:

```yaml
mapspace:
  spatial_dims: [KH, KW, CIN, COUT, HO, WO, T]
```

## Environment

Use the `cosa_snn` conda environment:

```bash
cd /home/yy/projects/snn_cosa
conda activate cosa_snn
export PYTHONPATH=src
python -m pip install -r requirements.txt
```

The solver requires a working Gurobi license.  This project was checked with:

```text
gurobipy==13.0.2
numpy==2.4.6
PyYAML==6.0.3
```

## Run

Solve the sample layer:

```bash
python -m snn_cosa solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/snn_arch.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/sample_schedule.json
```

Optional solver controls:

```bash
python -m snn_cosa solve --time-limit 60 --mip-gap 0.01 --solver-log
```

## Output

The output JSON contains:

- `status`: Gurobi solve status.
- `objective`: final objective value if a solution exists.
- `strategy.NodeLevel.temporal_tile`: unordered temporal factors assigned to
  NodeLevel.  The model does not decide a NodeLevel loop permutation.
- `strategy.NoCLevel.temporal_permutation`: temporal loop factors at NoCLevel.
- `strategy.NoCLevel.spatial_splitting`: spatial split factors at NoCLevel.
- `strategy.DRAM.temporal_permutation`: temporal loop factors at DRAM.

NoCLevel and DRAM permutation blocks have an `order` string and a `loops` list.
NodeLevel has a `factors` list instead because no NodeLevel order is modeled.
Each entry contains only the dimension name and fused dimension size, for
example `{"dim": "HO", "size": 14}`.

For the included sample config, the verified solve status is `OPTIMAL` with
objective `64.399345`.

## Solver Flow

1. Parse layer, architecture, bit widths, and optional mapspace.
2. Create schedule variables `X[(i, j, n, k)]` and reuse variables `y[(v, i)]`.
3. Add assignment, spatial fanout, and capacity constraints.
4. Build data-size, temporal-traffic, and spatial-traffic expressions.
5. Minimize the combined objective.
6. Extract the chosen schedule into JSON-compatible dictionaries.
