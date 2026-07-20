# Weight-trace generation: "generate once, analyze many times" -- Design

## Context

Today, the only consumer of `reconstruct_tile_sequence` / `weight_addresses`
/ `compute_cycles` is `scripts/sweep_archmodel_layers.py`, which re-solves
the MIP schedule and re-reconstructs from the raw captured `.npy` trace on
every run, for every (arch, layer) combination -- nothing is persisted
beyond the final TC-CSV and a summary row (`total_weight_addresses` as a
*count*, not the addresses themselves). A dedicated persistence module
(`weight_trace.py`) was drafted once and explicitly dropped ("nothing
consumes it yet" -- `2026-07-12-archmodel-spinalflow-design.md`); the
locality analyzer that would have been the first real consumer was later
built and then removed ("Plan 2, stopped per direction").

We want a real generate-once workflow: run the expensive solve+reconstruct
pipeline exactly once per (arch, trace_dir, layer, sample), persist the
resulting weight-address stream + per-tile cycle counts to disk, and have
all future analysis just load those files.

The critical complication: `reconstruct_tile_sequence` hardcoded
`batch = 0` in all 5 arch plugins, and batch was never part of the
schedule/tiling dimensions at all (`build_workload_from_trace` never reads
it). "Generate once" is supposed to cover **every captured sample** (up to
~10,000 in the `_all` trace variants), not just sample 0 -- so batch had to
become a real, vectorized parameter before generation could mean anything
beyond what today's code already does.

## Non-goals (explicitly deferred)

- Persisting the full reconstructed per-tile representation (`LoASReconstructed`,
  `PTBReconstructed`, etc.) -- only the derived weight-address stream and
  per-tile cycle counts are persisted. Nothing currently planned consumes
  the raw reconstruction beyond what produces those two things.
- Changing `combine.py` / `run_from_json`'s live TC-CSV generation path --
  `sweep_archmodel_layers.py` keeps producing TC CSVs exactly as today;
  this work only adds persistence of the weight-address stream alongside it.
- GPU acceleration of reconstruction (see Decision log below -- deliberately
  rejected, not merely deferred).
- Rebuilding the locality analyzer itself (`src/snn_cosa/locality/`) -- this
  spec only builds the persisted artifact it would consume; the analyzer's
  own reuse-distance/classification logic is separate future work.

## Decision log (resolved during design)

- **Trace root**: `--trace-root` CLI flag, default
  `/u/yyu9/neuro_cache_trace/input_trace/loas` (the sibling capture repo),
  not copied into `projects/neuro_cache/input_trace/`.
- **Trace scope**: default trace dirs are `vgg16_T4_all` and
  `resnet19_T4_all` (the ~10,000-sample variants), not the tiny `_B1`
  ones -- this is *why* batch-vectorization was in scope at all.
- **Persisted artifact**: weight-address stream + per-tile
  `mac_cycles`/`lif_cycles` + metadata. Not the raw reconstruction.
- **Code reuse**: the solve+iterate+reconstruct+address/cycle loop is
  extracted into a shared module (`src/snn_cosa/tracegen.py`) that both
  the new generate script and `sweep_archmodel_layers.py` call, instead of
  duplicating it.
- **Skip-existing**: on by default, checked **per sample file** (not a
  shared manifest), specifically so parallel slurm-array tasks never
  contend on writing the same index file. A separate `--summarize` mode
  (not run during generation) scans the output tree and writes
  `manifest.csv` afterward.
- **CPU vs GPU**: CPU-numpy only. This is a gather + boolean-reduction
  workload (bandwidth-bound, no matmuls), not a natural GPU win, and the
  final step (constructing `LoASLine`/`ProsperityRow`/etc. Python objects)
  is CPU-side regardless of where the gather ran. The cluster's only
  partitions are GPU-equipped (see HPC section), but since the allocation
  cost is identical whether or not the GPU is used, there's no
  opportunity-cost argument for using it either. Revisit only if real
  profiling after the below still shows this as the bottleneck.

## Already completed (prerequisite work)

1. **`src/snn_cosa/{model,solver.py}` to `mip_solver/`** -- disambiguates
   the MIP formulation from `ArchComputeModel` and the sibling repo's NN
   models. Mechanical rename, 21 import sites updated, verified
   byte-identical `solve_schedule()` output before/after. Committed.

2. **Batch-vectorization of all 5 archs' `reconstruct_tile_sequence`** --
   each arch gained a `reconstruct_tile_sequence_batch(trace, tile,
   batch_indices)` that reconstructs every requested sample in one
   vectorized numpy pass (instead of `len(batch_indices)` separate
   Python-level nested loops); the original scalar function is now a
   one-line wrapper (`reconstruct_tile_sequence_batch(trace, tile, [0])[0]`),
   so there is exactly one implementation per arch, not two that could
   silently drift. Not yet committed.

   Each was verified against a reference copy of the pre-vectorization
   algorithm (0 mismatches in every case) and measured for speedup at
   varying trace sparsity (real captured spike data is expected to be
   sparse -- that's the entire premise of these compressed architectures):

   | Arch | Verification | Speedup (dense to sparse) |
   |---|---|---|
   | LoAS | 49,152 (tile,batch) combos, 0 mismatches | 1.7x - 9.6x |
   | SpinalFlow | 12,288 combos, 0 mismatches | 2.1x - 13.0x |
   | PTB | 49,152 combos, 0 mismatches | 2.2x - 12.8x |
   | GustavSNN | 6,144 combos, 0 mismatches | 2.1x - 14.4x |
   | Prosperity | 48 combos (real tiles) + 144 synthetic bit-pattern configs, 0 mismatches | 9.3x - 11.0x |

   Prosperity needed a second change beyond the gather: its
   `_prosparsity_process` compression (the paper's O(M^2) all-pairs
   subset/overlap search, M=256 per the paper's own tile config) dominates
   per-sample cost regardless of sparsity, so gather-vectorization alone
   measured 1.0x. The O(M^2) function's *sequential outer order* (row i's
   prefix choice depends on every prior row) was left untouched; its
   *inner* per-step candidate search was vectorized (one numpy comparison
   against a growing array of already-processed rows, instead of a Python
   scan + `max()` with a lambda), independently verified against the
   original on 144 configurations including hand-built edge cases, giving
   11.6x-16.4x on the inner loop alone and 9.3x-11.0x end-to-end.

3. Found the missing `configs/arch/{spinalflow,ptb,gustavsnn,prosperity}.yaml`
   gap (none had ever existed in git history -- only `loas.yaml` did,
   meaning 4 of `sweep_archmodel_layers.py`'s 5 `ARCHS` entries could not
   actually run in this checkout); user has since added all 4.

4. Located and verified the cluster's Gurobi WLS license
   (`/sw/user/containers/gurobi/gurobi.lic`, group-readable via `grp_202`;
   user also placed a personal copy at `~/gurobi.lic`), confirmed working
   (v13.0.2) via a real MIP solve.

## Design

### Two-stage pipeline: solve once, reconstruct many times

Splitting these matters for two independent reasons: (a) `solve_schedule`
is the only Gurobi consumer in this whole pipeline, and Gurobi license
seats are a shared, limited resource -- solving redundantly inside a
massively parallel sample-sweep would contend for seats unnecessarily; and
(b) the schedule/tile geometry is identical across every sample of a given
(arch, layer) (batch isn't a workload dimension), so re-solving per sample
would be pure waste regardless of licensing.

```
Stage 1 (scripts/solve_schedules.py)          Stage 2 (scripts/generate_weight_traces.py)
----------------------------------------      --------------------------------------------
~140 calls total (5 archs x ~28 layers)       ~1.4M (arch, layer, sample) reconstructions
Needs Gurobi license                          No Gurobi at all -- pure numpy
Low concurrency                               Fully parallel (slurm array, see below)
  |
  v
outputs/schedules/<arch>/<trace_dir>/<layer_name>.json
  (solved MIP result + derived tile list)
                                                |
                                                v
                                    outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/
                                        sample_00000.json ... sample_09999.json
```

### Shared core module: `src/snn_cosa/tracegen.py`

Extracts `sweep_archmodel_layers.py`'s inline `solve_schedule` to
`iter_node_tiles` to `format_input`/`compute_cycles`/`weight_addresses` loop
(today's lines 64-98) into reusable functions:

```python
def solve_and_cache_schedule(arch_name, arch_yaml, trace_dir, layer_name, meta, next_cin, cache_dir) -> ScheduleArtifact: ...
def load_schedule(path) -> Tuple[Schedule, SNNProb, List[NodeTileSpec]]: ...

@dataclass
class TileWeightTrace:
    dram_i: int
    mac_cycles: int
    lif_cycles: Optional[int]
    weight_addresses: List[Any]

@dataclass
class LayerWeightTrace:
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: dict
    dram_num_steps: int
    tiles: List[TileWeightTrace]

def reconstruct_samples_for_schedule(model, trace, tiles, sample_indices) -> List[LayerWeightTrace]: ...
def save_weight_trace(trace: LayerWeightTrace, path: Path) -> None: ...
def load_weight_trace(path: Path) -> LayerWeightTrace: ...
def iter_generated_traces(root: Path) -> Iterator[LayerWeightTrace]: ...
```

`sweep_archmodel_layers.py` is refactored to call
`reconstruct_samples_for_schedule` (sample `[0]`) instead of its own inline
loop for its stats (`total_mac_cycles`, `cycles_vary`,
`total_weight_addresses`), zero behavior change, just de-duplicated code,
and still calls `run_from_json`/`combine.py` exactly as today for TC-CSV
generation (unaffected by any of this).

### Output layout

```
outputs/schedules/<arch>/<trace_dir>/<layer_name>.json
outputs/weight_traces/<arch>/<trace_dir>/<layer_name>/sample_<00000-09999>.json
outputs/weight_traces/manifest.csv   # written only by --summarize, not during generation
```

### Skip-existing / resumability

`generate_weight_traces.py` checks per-sample-file existence before
recomputing (skip if `sample_<i>.json` exists with `status: "OK"`; always
retry prior `ERROR`); `--force` overrides. No shared index file is written
during generation, specifically to avoid concurrent-write races when many
slurm array tasks run against the same output tree simultaneously.
`--summarize` is a separate, explicit mode that scans the tree once and
(re)writes `manifest.csv`, run after generation finishes, or periodically
to check progress, never concurrently with active generation.

### HPC execution

This allocation (NCSA DeltaAI, confirmed via `sacctmgr`/`sinfo`) has **no
CPU-only partition** -- every partition (`ghx4`, `full`, `test`,
`ghx4-interactive`) is a GH200 node, and `bebv-dtai-gh` is the only usable
account. `ghx4` has the longest non-interactive time limit (2 days) and is
what the existing capture job already uses.

Job-list + array-index pattern (avoids fragile arithmetic in the sbatch
script itself): `scripts/plan_trace_shards.py` writes
`outputs/weight_traces/jobs.txt`, one line per
`(arch, trace_dir, layer_name, sample_start, sample_count)`; the array
script indexes into it via `sed -n "$((SLURM_ARRAY_TASK_ID+1))p"`.

**Open item, needs verification on the actual cluster (not something I can
check from here):** whether this partition's scheduler requires an
explicit `--gres=gpu:N` even for a job that never touches the GPU. If so,
Stage 2 jobs will need to request (and then simply not use) at least one
GPU purely to be schedulable, a real constraint on how many Stage-2 array
tasks can run concurrently (bounded by GPU count, not CPU core count),
separate from the CPU-vs-GPU *compute* decision above.

### Testing / verification approach

Already demonstrated throughout this work (per-arch reference-algorithm
comparison, a fully hand-traceable tiny example, sparsity-swept timing).
For the new pipeline components specifically:

- Cross-check: `total_weight_addresses` summed from a generated
  `LayerWeightTrace` must exactly equal what
  `sweep_archmodel_layers.py`'s own summary CSV already reports for the
  same (arch, layer), both derive from the same `weight_addresses()`
  calls, so any discrepancy is a real bug.
- Run `generate_weight_traces.py` on the smallest layer / fewest samples
  first, inspect the JSON by hand.
- Re-run without `--force`, confirm skipped entries are reported as
  skipped, not recomputed.
- Full sweep, then `--summarize`, review `manifest.csv`.