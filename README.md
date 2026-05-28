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
  model/                          constants, variables, constraints, traffic, objective
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
      entries: 512
      instances: 1024
    - name: NoCLevel
      entries: 65536
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
- `model_size`: number of variables and constraints.
- `problem`: parsed layer dimensions.
- `layout`: loop-level boundaries for NodeLevel, NoCLevel, and OffChip.
- `schedule.levels`: selected factor placement by loop level.
- `schedule.readable`: adjacent same-dimension factors fused into temporal and
  spatial orders per memory region.
- `schedule.reuse_indicators`: active reuse variables `y[(v, i)]`.
- `schedule.summary`: spatial and temporal tile products per region.
- `costs`: per-variable footprint and traffic terms.

For the included sample config, the verified solve status is `OPTIMAL` with
objective `64.399345`.

## Solver Flow

1. Parse layer, architecture, bit widths, and optional mapspace.
2. Create schedule variables `X[(i, j, n, k)]` and reuse variables `y[(v, i)]`.
3. Add assignment, spatial fanout, and capacity constraints.
4. Build data-size, temporal-traffic, and spatial-traffic expressions.
5. Minimize the combined objective.
6. Extract the chosen schedule into JSON-compatible dictionaries.
