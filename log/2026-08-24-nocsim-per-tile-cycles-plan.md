# nocsim per-tile compute cycles: single-node and multi-node

Status: **DRAFT, awaiting approval.** Nothing below has been implemented.
Branch `wcache-rebuild-phase-a`, head `26ef6f0`.

Goal: charge every `(dram_i, noc_i)` step its own MAC cycle count, read from
the Stage 2 weight trace, on both the single-node and the multi-node arm,
through one mechanism.

Governing ruling: **U31** (`src/wcache/PROGRESS.md:835`, closed by an explicit
user answer, "Option 2"): nocsim reads the per-tile `mac_cycles` the weight
trace already stores; it is not driven with a live archmodel.


## 1. How nocsim simulates a layer

Two separate programs.

```
schedule JSON ─┐
               ├─> combine()  ──> tc.csv  ──> eventsim ──> total_cycles
weight trace ──┘   (Python)      (event      (C++)         + breakdown
                                  graph)
```

`combine()` builds the mesh once from the schedule's spatial factors
(`combine.py:168-172`: `X = T*WO*HO`, `Y = CIN*KW*KH*COUT`), then walks the
outer DRAM loop and inner NoC loop, emitting the same nine things at every
step:

| # | step | kind |
|---|---|---|
| 1 | weight load, GB to all nodes | send |
| 2 | psum load, GB to one PE per group | send |
| 3 | **MAC COUNT, all PEs in parallel** | **compute** |
| 4 | K-chain, partial sums forwarded | send |
| 5 | psum store, PE to GB | send |
| 6 | vmem load, GB to one PE per group | send |
| 7 | **LIF COUNT, all PEs in parallel** | **compute** |
| 8 | T-chain, timestep state forwarded | send |
| 9 | vmem store, PE to GB | send |

Three transaction kinds exist (`core/transaction.py:16-18`): `UNICAST=0`,
`MULTICAST=1`, `COUNT=2`. Each records its id, owning node, size in bits, and
the ids it waits on. `tc.csv` is that dependency graph flattened.

`eventsim` replays the graph as discrete events. A transaction starts when its
dependencies have finished **and** its node is idle **and** every link on its
route is free (`EventSim.h:14-18`). Sends hold their whole route for their
duration; DRAM-touching transactions cost `size * dram_latency` with no hop
term; COUNT occupies no links.

**Compute time enters only at steps 3 and 7.** Every other step sizes itself
from `schedule.data_size`, pure byte accounting off the loop structure. So the
entire arch-model question is one integer per step: `mac_cyc`.


## 2. The two arms are one mechanism

Single-node is the degenerate case of the same tiling, not a separate path.
Both rows below are the same layer, vgg16 `layer_08_features_27` (V8).

| | arm S, single-node | arm M, multi-node |
|---|---|---|
| arch config | `configs/arch/loas.yaml` | `loas_inst16_node32kb_noc2MiB_pe16.yaml` |
| `NodeLevel instances` | 1 | 16 |
| `noc_num_steps` | 1 | 64 |
| `dram_num_steps` | 2048 | 2 |
| `spatial_factors` | all 1 | COUT=16 |
| specs per `(dram_i, noc_i)` | **1** | **16** |
| `max()` over cores | over one element | over sixteen |
| total specs | 2048 | 2048 |

`iter_node_tiles`'s own docstring states this: it "degenerates exactly to the
original single-node-only behavior" when `noc_temporal_loops` is empty and
`spatial_factors` is trivial. The tiling is redistributed between arms, not
changed in kind.


## 3. State of each arm today

### Arm S: implemented, currently unrunnable

The single-node trace-driven path works. Measured 2026-08-24 by driving
`combine()` on V8 with the live model and a real capture:

```
arch.single_node: True
dram_num_steps=2048  noc_num_steps=1  spatial={all 1}
tiles: 2048   distinct (dram_i, noc_i): 2048   cores: 1
tc.csv written: 482,525 bytes
distinct mac COUNT steps: 2048   distinct durations: 16
  durations min/median/max: 751 / 1226 / 1875   sum = 2,597,632
```

Its only driver, `dump/scripts/sweep_archmodel_layers.py` (2026-07-20), is the
sole file that has ever passed `compute_model` to nocsim. Commit **2811a66**
(2026-08-02, "promote each arch's native C++ port to the sole implementation")
moved the five live Python models to `dump/python_reference/archmodels/`, so
that script's imports now fail. The models are intact, not destroyed.

That script also never hit **B179**, because it solved live and dumped the raw
solver result (top-level `has_solution`/`strategy`), which is the shape
`run_from_json` expects. B179 is a contract that diverged after the script was
archived, not a bug it ever had.

Consequence: `DenseStaticComputeModel` is the only `ArchComputeModel`
implementation left in `src/`, so `combine`'s `compute_model` parameter has no
possible trace-driven argument today.

### Arm M: never implemented

`combine.py:207` gates the per-tile compute call on `single_node`. Multi-node
takes the `else` branch, one static call for the whole layer.


## 4. What changes

Three modified files, one new runner, one new test file. Roughly 115 lines of
production change.

### 4a. `src/tracegen.py`, ~75 lines

`save_weight_trace` (line 330) has no reader counterpart. Add one beside it.

```python
@dataclass(frozen=True)
class StepCycles:
    """Per-(dram_i, noc_i) cycle counts read back from a saved weight trace,
    plus the identity fields needed to prove they belong to a schedule.

    by_step values are already the max over that tile's cores -- the
    reduction assemble_layer_traces applies at line 281 before writing, and
    the same one combine.py's "mac_count (all PEs, parallel)" calls for.
    Nothing recomputes it here; the per-core values are not in the file.
    """
    by_step: Dict[Tuple[int, int], ComputeCycles]
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    noc_num_steps: int

    def check_against(self, artifact: ScheduleArtifact, schedule) -> None:
        """Raise unless this trace was produced from this schedule."""
        # six comparisons: arch, layer_name, trace_dir,
        # workload_dims vs artifact.workload["problem"],
        # dram_num_steps, noc_num_steps


def load_step_cycles(path) -> StepCycles:
    """Read per-tile cycle counts out of one sample_NNNNN.json.gz, ignoring
    the bursts (ruling U31)."""
    # gzip.open, iterate doc["tiles"], reject duplicate keys,
    # require len(by_step) == dram_num_steps * noc_num_steps
```

One detail confirmed against the real corpus: the artifact nests the dims one
level deeper than the trace does.

```
artifact.workload  {'problem': {'KH': 3, ..., 'shape': 'snn-layer'}}
workload_dims                 {'KH': 3, ..., 'shape': 'snn-layer'}
```

So the comparison is against `artifact.workload["problem"]`. Comparing the
outer dicts returns `False` on a correctly matched pair, which would fire the
guard on every valid input.

### 4b. `src/nocsim/combine.py`, ~15 lines

Signature gains one keyword:

```python
cycles_by_step: Optional[Dict[Tuple[int, int], ComputeCycles]] = None,
```

At the cycle-source block (currently `combine.py:206-213`), the new case comes
first and never calls `iter_node_tiles`:

```python
model = compute_model or DenseStaticComputeModel(schedule, prob)
tiles_by_step = None
if cycles_by_step is not None:
    pass                       # cycles come from the table; no model, no tiles
elif single_node:
    tiles_by_step = {}
    for spec in iter_node_tiles(schedule, prob):
        tiles_by_step.setdefault((spec.dram_i, spec.noc_i), []).append(spec)
else:
    cycles = model.compute_cycles(model.format_input(trace, None), None)
    mac_cyc = cycles.mac_cycles
    lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0
```

In the NoC loop, in front of the existing `if tiles_by_step is not None:`
(line 315):

```python
if cycles_by_step is not None:
    c = cycles_by_step[(dram_i, noc_i)]      # KeyError is the right failure
    mac_cyc = c.mac_cycles
    lif_cyc = c.lif_cycles if c.lif_cycles is not None else 0
elif tiles_by_step is not None:
    ...unchanged...
```

The bare `KeyError` matches the comment already at line 313: `combine`'s loops
run the full cross product, so a missing key means the trace and the schedule
disagree, which is a defect to surface rather than a step to charge zero for.

### 4c. `src/nocsim/sim.py`, ~25 lines

The B179 reader fix at lines 139-142:

```diff
     with open(schedule_path) as fh:
-        result = json.load(fh)
+        data = json.load(fh)
 
-    if not result.get("has_solution"):
+    # A ScheduleArtifact nests the solver result under "result"; a raw
+    # `mip_solver solve` JSON is the result itself. Accept both rather
+    # than migrating either producer (PROGRESS.md B179).
+    result = data.get("result", data)
+    if not result.get("has_solution"):
```

This widens what loads and never narrows it. Verified: the raw solver document
(`cli.py:158-162` dumping `solve.py:200-208`) has top-level `status`,
`has_solution`, `objective`, `strategy`, `metrics`, `configs` and **no
`result` key**, so `.get("result", data)` returns the document itself and the
old behavior holds exactly.

Then `cycles_by_step` threads through `run()` and `run_from_json()` into
`combine()`, and the CLI gains `--weight-trace JSON_GZ`. One file is one
sample, so no `--sample` flag.

### 4d. `profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py`, ~170 lines

Follows the folder contract in that directory's `README.md:25-46`: a stage
reads only its own `inputs/`, and never writes into another stage's directory.

```
inputs/
  schedules/{single,multi}/loas/<trace_dir>/<layer>.json
  weight_traces/{single,multi}/.../sample_0000{0..4}.json.gz
  arch/{loas.yaml, loas_inst16_node32kb_noc2MiB_pe16.yaml}
  MANIFEST.json
outputs/
  tc/{single,multi}/<layer>/sample_NNNNN.csv
  stage3_report.json
  RESULTS.md
```

Per run, identical for both arms:

```python
artifact, prob, _ = tracegen.load_schedule(schedule_path)
schedule = schedule_from_strategy(artifact.result["strategy"], prob)
sc = tracegen.load_step_cycles(wt_path)
sc.check_against(artifact, schedule)

uni, multi, dram = run_from_json(schedule_path, prob, bitwidths, out_csv,
                                 arch=arch, cycles_by_step=sc.by_step)
ev = run_eventsim(out_csv, X=..., Y=..., dram_port=..., dram_latency=...)
```

`load_schedule` supplies `prob` from the artifact's own embedded workload, so
no layer YAML has to be located or regenerated.


## 5. Stage 1 and Stage 2 work per arm

| stage | arm M | arm S |
|---|---|---|
| Stage 1 | **done**: 4 layers at NoC 2 MiB / node 32 KiB, 16 nodes | **needed**: 4 solves against `configs/arch/loas.yaml` |
| Stage 2 | **done**: 20 traces, reconstruction verified exactly | **needed**: 20 traces against the arm S schedules |
| Stage 3 | this plan | this plan, same code |

Arm S Stage 1 is cheap: single-node solves are the fast case, and V8/V9 already
exist under `outputs/schedules/loas/vgg16_T4_n5/` while R9/R16 exist under
`outputs/schedules/loas/resnet19_T4_all/`. Re-solving all four into the Stage 1
outputs directory keeps the `trace_dir` naming consistent with what Stage 2
uses, which the identity guard checks.


## 6. What does not change

- The existing `single_node` per-tile branch, including the whole B178 repair:
  `(dram_i, noc_i)` keying, the fetch inside the NoC loop, `max()` over cores.
- All fifteen traffic-topology uses of `single_node` in `combine.py`
  (lines 253, 262, 273, 356, 382, 390, 431, 457, 465, 511, 530, 534, 545, 549).
- The nine-step structure, the mesh construction, the hop accounting.
- `eventsim`, in any respect.
- The archived Python models stay archived. The cross-check in section 7 uses a
  scratch copy under a different package name, because
  `dump/python_reference/archmodels` shadows `src/archmodels` on `sys.path`.

Behavior matrix:

| case | today | after |
|---|---|---|
| single-node, no trace | per-tile via the model | identical |
| multi-node, no trace | one static value per layer | identical |
| multi-node, with trace | not possible | per-tile from the trace |
| single-node, with trace | not possible | per-tile from the trace |
| loading a `ScheduleArtifact` | raises `ValueError` | loads |

One new interaction: passing `cycles_by_step` on a `single_node` arch makes the
table win over the model. That combination cannot occur today.


## 7. Verification

| # | check | arm |
|---|---|---|
| 1 | loader on real data: 128 keys, each value equals the file's own `tiles[i].mac_cycles` | M |
| 2 | loader on real data: 2048 keys | S |
| 3 | guard fires: R9's trace against V8's schedule raises, naming the mismatch | both |
| 4 | dense regression: `tc.csv` with `cycles_by_step=None` byte-identical before and after | both |
| 5 | single-node live-model path byte-identical before and after | S |
| 6 | **the number lands**: every step's COUNT duration in `tc.csv` equals the trace's `mac_cycles` for that `(dram_i, noc_i)` | both |
| 7 | cross-arm sanity: total MAC cycles for the same layer land in the same range across arms | both |

Check 6 is what separates real wiring from a plausible one that quietly still
charges dense cycles, which is the shape of both B173 and B179. Its chain is
`trace JSON -> cycles_by_step -> mac_count(pe_cycles) -> gen.count() ->
tc.csv size column`.

Check 7 has an anchor already measured. On V8's 2048 single-node tiles, the
live Python model and the C++ generator agree exactly:

```
tiles compared : 2048
identical      : 2048
mismatches     : 0
python  min/med/max: 751 / 1226 / 1875   sum=2,597,632
c++     min/med/max: 751 / 1226 / 1875   sum=2,597,632
```

So "read the number from the trace" and "recompute it live" are the same
answer, and U31 chose between two routes to an identical result on cost.


## 8. Why this matters numerically

Both measured rather than argued.

- The static dense formula and the real trace disagree by **30x to 58x** on
  per-tile cycles across the four layers (58.1x V8, 54.6x R9, 30.2x V9,
  38.3x R16), decomposing into 16x dataflow modelling (`COUT_node(4) x T(4)`
  serialized by `DenseStaticComputeModel`) and 1.9x to 3.6x sparsity.
- Even with the right model, charging one value per DRAM step instead of per
  NoC step undercounts by **3.4%** (U31: DRAM step 5 of loas vgg16 `layer_01`
  is 147/163/149/170, and the coarse path charges 147 four times).


## 9. Increments

One unit per increment, an erasable `EXPLAIN.md`, then stop and wait for "next".

1. `StepCycles`, `load_step_cycles`, `check_against`. Checks 1, 2, 3.
2. The `combine.py` parameter and two branches. Checks 4, 5.
3. `sim.py` B179 fix, threading, `--weight-trace`. Check 6 on arm M.
4. Arm S Stage 1 (4 solves) and Stage 2 (20 traces), size measured on one
   sample first.
5. `run_stage3.py` and the 40 runs (2 arms x 4 layers x 5 samples).
6. Check 7, cross-arm comparison, and `RESULTS.md`.

Increments 1 through 3 are code and tests only. Increment 4 produces data.


## 10. Risks and open items

| id | item |
|---|---|
| R1 | Arm S weight-trace size: 2048 tile entries per sample against arm M's 128. Measure one sample before generating twenty. |
| R2 | The identity guard must compare against the schedule copy Stage 2 actually used, whose `trace_dir` is the `_n5` name, not Stage 1's `_all`. |
| R3 | Reviving `dump/scripts/sweep_archmodel_layers.py` is out of scope. It also calls `tracegen.reconstruct_samples_for_schedule`, which no longer exists (now `reconstruct_samples`, line 296). |
| R4 | U29 (`burst_dim` other than COUT decoded silently wrong in `stream_format.h`) lives in the same format family and is untouched here. |
| R5 | Not chosen, and worth stating: restoring the five `model.py` trees from `dump/python_reference/` would make arm M work by opening the gate alone, with no loader and no new parameter. Rejected because it re-promotes implementations 2811a66 demoted, recomputes work Stage 2 has already saved, and contradicts U31. |
