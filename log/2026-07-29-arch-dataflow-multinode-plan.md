# 2026-07-29 Architecture/Dataflow Separation and Multi-Node Scheduling Plan

Status: implemented. The split, five multi-node configs, 155 stored
schedules, and value-free GB/DRAM analysis were verified on 2026-07-29.

## Rephrased goal

The work has two parts:

1. Separate physical hardware properties from dataflow constraints. In
   particular, move `node_dim_capacity` out of each architecture YAML and
   into a dedicated dataflow YAML. Keep topology, PE counts, bit widths, and
   storage capacities in the architecture YAML.
2. Confirm exactly which NodeLevel `entries` fields constrain the MIP, then
   construct a multi-node architecture whose NodeLevel is the current
   SpinalFlow single-node design. Run the scheduler with that composition and
   inspect the resulting NodeLevel, NoCLevel, and DRAM mapping.

The current SpinalFlow config is the concrete reference. Its
`node_dim_capacity` has the requested semantics, shown here with the revised
`full` spelling:

```yaml
node_dim_capacity:
  KH:   4
  KW:   4
  T:    full
  COUT: {spatial: 128}
  CIN:  full
```

## Configuration ownership

| File | Owns | Does not own |
|---|---|---|
| `arch.yaml` | topology, `single_node`, bit widths, memory levels, instance counts, PE counts, register sizes, local-buffer sizes, NoC/global-buffer sizes | dimension residency or spatial/temporal mapping policy |
| `dataflow.yaml` | NodeLevel dimension residency, temporal caps, fully resident dimensions, barred dimensions, and PE-spatial dimension caps | byte capacities or hardware instance counts |
| `mapspace.yaml` | dimensions the solver may spatially partition at NoCLevel | fixed NodeLevel dataflow and hardware capacities |

This keeps one canonical source for each fact: byte counts are hardware;
dimension placement rules are dataflow.

## Task 1: Split `arch.yaml` from `dataflow.yaml`

### 1.1 Proposed single-node SpinalFlow files

The current `configs/arch/spinalflow.yaml` would be split as follows.

`configs/arch/spinalflow.yaml`:

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM:   16
    BW_VMEM:   32
    DRAM_LATENCY: 17

  single_node: true
  storage:
    - name: NodeLevel
      instances: 1
      pe:
        num_pes: 128
    - name: NoCLevel
      instances: 1
    - name: OffChip
      instances: 1
```

`configs/dataflow/spinalflow.yaml`:

```yaml
dataflow:
  node_dim_capacity:
    KH:   4
    KW:   4
    T:    full
    COUT: {spatial: 128}
    CIN:  full
```

The meaning stays unchanged:

- `KH: 4` and `KW: 4` cap the resident NodeLevel factors at the largest
  achievable factor product no greater than four.
- `T: full` and `CIN: full` force the complete dimensions to reside at
  NodeLevel.
- `COUT: {spatial: 128}` maps up to 128 output channels across the node's
  PEs.
- Missing `HO` and `WO` bar those dimensions from NodeLevel.

The files are paired explicitly at the command line, rather than making one
config silently select the other:

```bash
python -m mip_solver solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/spinalflow.yaml \
  --dataflow configs/dataflow/spinalflow.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/schedules/spinalflow_single_node.json
```

### 1.2 Parser and solver changes

1. Add `src/parsers/dataflow.py` with an `SNNDataflow` parser that validates
   `dataflow.node_dim_capacity` using the rules currently implemented in
   `src/parsers/arch.py`. The accepted values are a positive integer,
   the literal string `full`, or `{spatial: N}`. `null` is no longer the
   spelling for full residency.
2. Keep `SNNArch` responsible only for hardware. Remove
   `node_dim_capacity` and its derived spatial split from `SNNArch`.
3. Derive `node_pe_spatial_split` from `SNNDataflow`, but validate its product
   against `SNNArch.node_pe_num_pes` when the two parsed objects are composed.
4. Add `dataflow_path` to `solve_schedule`, the enumerator, trace generation,
   and schedule-generation scripts. Add `--dataflow` to the `solve` and
   `enumerate` CLI commands.
5. Pass `SNNDataflow` directly to the NodeLevel dimension-capacity and
   PE-spatial constraints. Hardware-capacity constraints continue to receive
   `SNNArch`.
6. Migrate each existing named design (`spinalflow`, `ptb`, `loas`,
   `gustavsnn`, and `prosperity`) to a matching file under
   `configs/dataflow/`, converting every full-residency `null` to `full`.
   Update README examples and script defaults.

### 1.3 Task 1 verification

- Parser checks reject unknown dimensions, non-positive caps, malformed
  `{spatial: N}` values, `null`, unknown strings, and a spatial product
  larger than the selected architecture's `num_pes`.
- Solve the same SpinalFlow layer before and after the split. The status,
  objective, and full `strategy` must match; only configuration provenance
  should change.
- Run one solve for every migrated architecture/dataflow pair to catch broken
  script or parser call sites.
- Record both architecture and dataflow paths in the schedule artifact so a
  result can be reproduced.

## Task 2: Audit NodeLevel entries and build the multi-node composition

### 2.1 Check which `entries` fields are constraints

The code currently has two different meanings for NodeLevel entries, so the
audit must test them separately:

| Field | Current behavior to verify |
|---|---|
| `NodeLevel.pe.registers.entries` | Parsed and stored as metadata; no constraint, objective, or NoC simulation path reads it. |
| `NodeLevel.local_buffer.entries` | Used to construct per-variable NodeLevel byte-utilization expressions and enforced by `cap_NodeLevel_<variable>` MIP constraints. If omitted, no NodeLevel byte-capacity constraint is created. |
| `NoCLevel.entries` | Enforced as per-variable global-buffer byte-capacity constraints. If omitted, no NoCLevel byte-capacity constraint is created. |
| `OffChip.entries` | Not present; OffChip is treated as unbounded. |

The audit will trace these fields through `src/parsers/arch.py`,
`src/mip_solver/objectives/utilization.py`, and
`src/mip_solver/solve.py`, then confirm the behavior with small solves:

1. Inspect the generated model for named NodeLevel and NoCLevel capacity
   constraints.
2. Reduce one capacity below the required tile footprint and confirm that it
   changes feasibility or forces a different mapping.
3. Increase it and confirm that the corresponding restriction relaxes.
4. Change `pe.registers.entries` alone and confirm that the schedule is
   unchanged.

If register entries are intended to constrain scheduling, that is a separate
modeling decision after the audit; this plan will not silently reinterpret
metadata as a new capacity constraint.

### 2.2 Build a multi-node architecture around the current single node

Create `configs/arch/spinalflow_multinode.yaml` by composing:

- the SpinalFlow compute node from `configs/arch/spinalflow.yaml`
  (`num_pes: 128`);
- a 128-node topology with a 1 MiB shared-GB scheduling baseline per tensor;
  and
- the separated SpinalFlow NodeLevel rules from
  `configs/dataflow/spinalflow.yaml`.

The first scheduling fixture would be:

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM:   16
    BW_VMEM:   32
    DRAM_LATENCY: 17

  single_node: false
  storage:
    - name: NodeLevel
      instances: 128
      pe:
        num_pes: 128
    - name: NoCLevel
      entries:
        weight: 1048576
        psum:   1048576
        vmem:   1048576
      instances: 1
    - name: OffChip
      instances: 1
```

The original `snn_arch.yaml` fixture values made the forced SpinalFlow node
tile infeasible (`weight: 1024` locally and `weight: 64` at the GB). The
implemented configs therefore omit unknown NodeLevel byte capacities instead
of inventing them and use the repository survey's 1 MiB shared-GB reference
per tensor. These remain scheduling baselines, not claims about a real
128-node version of any of the five accelerators.

`pe.num_pes` has a direct but specific effect on the MIP:

- It is the upper bound on the product of all spatial factors assigned at
  NodeLevel.
- It validates the product of the dataflow's explicit `{spatial: N}` entries.
- With the current SpinalFlow dataflow, `COUT: {spatial: 128}` means
  `num_pes: 128` is the minimum valid value. A smaller value must fail
  validation. A larger value leaves unused PE capacity and should not change
  this fixed COUT mapping.
- It does not set the number of accelerator nodes. Multi-node fanout is
  controlled by `storage[NodeLevel].instances` relative to
  `storage[NoCLevel].instances`.

Run the composed schedule with:

```bash
python -m mip_solver solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/spinalflow_multinode.yaml \
  --dataflow configs/dataflow/spinalflow.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/schedules/spinalflow_multinode.json
```

### 2.3 Scheduling checks

The first multi-node result is accepted when:

1. `single_node: false` leaves the NoCLevel scheduling region enabled.
2. `strategy.NodeLevel` still obeys the SpinalFlow node rules: resident
   `KH <= 4`, `KW <= 4`, full `T` and `CIN`, spatial `COUT <= 128`, and no
   `HO` or `WO`.
3. `strategy.NoCLevel` and `strategy.DRAM` contain the solver-selected
   placement and permutation of factors left outside the node.
4. The NodeLevel local-buffer and NoCLevel global-buffer footprints do not
   exceed their configured `entries`.
5. Every prime factor is assigned exactly once across NodeLevel, NoCLevel,
   and DRAM.
6. A side-by-side single-node versus multi-node report records the schedule,
   objective, buffer utilization, and traffic metrics for the same layer.
7. A focused `num_pes` check runs the same composition with 64, 128, and 256
   PEs per node: 64 must be rejected because the requested spatial factor is
   128; 128 must solve; and 256 must retain the same NodeLevel COUT mapping as
   128.

If the NoCLevel strategy is empty, do not force a factor into it merely to
make the output look multi-node. First determine whether the empty mapping is
the legitimate optimum, is caused by the very small existing NoC capacities,
or exposes a missing multi-node constraint/objective.

### 2.4 Location of multi-node runner scripts

Any script created specifically to launch, inspect, or compare multi-node
runs must be stored in one of these two locations:

- `/tmp/` for disposable one-off probes; or
- `scripts/tmp/` for repository-local scripts that should remain available
  during this work.

Do not add multi-node runner scripts under the repository root, `src/`,
`debug/`, `profiling/`, or `log/`. Architecture and dataflow configs remain
under `configs/`, and schedule results remain under `outputs/`; this rule
applies to executable runner and analysis scripts.

## Deliverables after plan approval

- Separated hardware and dataflow YAMLs for all current designs.
- A dedicated dataflow parser and updated solver/CLI/script interfaces.
- A written NodeLevel/NoCLevel entries audit with model-level evidence.
- `spinalflow_multinode.yaml`, built from the current single-node compute
  node and the explicitly identified multi-node fixture capacities.
- Multi-node runner and comparison scripts located only in `/tmp/` or
  `scripts/tmp/`.
- Reproducible single-node and multi-node schedule JSON files plus a concise
  comparison.

## Resolved implementation decisions

1. The infeasible `snn_arch.yaml` byte capacities were replaced by the
   explicitly labeled 1 MiB shared-GB scheduling baseline; unknown NodeLevel
   capacities remain omitted.
2. Backward compatibility was not retained. `node_dim_capacity` in an
   architecture YAML and `null` in a dataflow YAML are both rejected.
