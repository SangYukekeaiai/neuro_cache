# 2026-07-30 Trace-Generation Refactor and Multi-Node Arch Sweep Plan

Status: Parts A and B fully implemented, run, and analyzed (2026-07-30).

## Post-implementation update: sweep grid widened, run for real

After the initial B.1 implementation (single fixed point: NodeLevel 32
KiB, NoCLevel 1 MiB), the sweep was widened to a real grid per follow-up
direction: NodeLevel size swept over {2, 4, 8, 16, 32} KiB, NoCLevel size
over {512 KiB, 1, 2, 4} MiB, combined with the existing instances sweep
-> 5 archs x 4 instances x 5 node sizes x 4 noc sizes x 31 layers =
**12,400 combos**.

Feasibility of running this in 1 hour was checked empirically, not
assumed:
- Per-combo solve time measured at ~1.5-2.0s regardless of
  instances/entries values (expected: those only change constraint
  budgets, not the MIP's variable/constraint count).
- An initial 16-worker concurrency test on the shared NCSA Delta login
  node stalled almost completely (processes sat at 0.0-0.4% CPU for 10+
  minutes) -- this looked like a Gurobi WLS concurrency ceiling but
  turned out to be login-node contention: re-run on an actual
  `gpuA100x4-interactive` compute-node allocation (1 GPU + 64 CPUs, the
  account is GPU-type-only so a GPU is requested purely to satisfy
  Delta's job_submit policy, the solve itself never touches it) showed
  8/16/24/32/48/64-way concurrency all completing cleanly with zero
  errors and near-flat wall-clock time.
- Real run: **12,400 combos in 373s (6m 13s) at 64 workers on one
  interactive-node allocation** -- 560 solved, 11,840 infeasible, 0
  errored. Comfortably inside the 1-hour target and inside that
  partition's own 1-hour walltime cap.

Analysis (`scripts/tmp/analyze_multinode_arch_sweep.py`, classification
dropping every loop's tile size per the "ignore the permutation value"
request, keeping only which super-dimensions occupy each level and
DRAM's temporal order) found:
- Only `loas`, `ptb`, and one `gustavsnn` layer ever solve; `spinalflow`
  and `prosperity` are infeasible everywhere in the grid.
- Feasibility is governed entirely by (architecture, NodeLevel size):
  only the 16 KiB and 32 KiB points ever solve anything.
  **`NodeLevel.instances` and `NoCLevel` size have zero measured effect
  on feasibility** -- every one of the 4 instance values and 4 NoC sizes
  accounts for exactly 140 of the 560 solves.
- `loas` and `ptb` produce byte-identical structural-class distributions
  (4 classes, dominated by one class at 514/560).

Full results, the feasibility heatmap, and the classification table are
published as an Artifact: https://claude.ai/code/artifact/655b00b8-1e1a-4635-bd24-4bc5bace9d83

Raw data: `outputs/schedules/multinode_sweep/{summary.csv,
classification.csv}` (gitignored, not committed).

## Part A: Weight-trace generation pipeline refactor

### A.0 Motivation

- `generate_weight_traces.py` and `generate_weight_traces_canonical100.py`
  each carry their own copy of the native-bridge reconstruction dispatch
  (`_native_reconstruct_fn`/`_process_chunk`), verbatim-duplicated rather
  than shared.
- The canonical 100-sample subset (`configs/sampling/sample_indices.json`)
  is a hardcoded literal list with no reproducible generator in the repo,
  even though its own seed=0/n_total=10000 metadata implies one was meant
  to exist.
- `tracegen.py` imports `mip_solver.solve` (hence `gurobipy`) at module
  level purely for `TrafficMode`, so even read-only consumers of a cached
  schedule pull in Gurobi at import time.
- `tracegen.reconstruct_samples_for_schedule`/`reconstruct_tile_chunk`
  (pure-Python) and `load_weight_trace`/`iter_generated_traces` are dead
  in the live pipeline (all reconstruction now goes through each arch's
  native bridge instead), but still live in `src/tracegen.py` rather than
  being archived like the other pure-Python compute files already were.

### A.1 `mip_solver`: extract the solve-and-score core

Add `mip_solver.solve_best_schedule(layer_path, arch_yaml, dataflow_yaml) ->
(best_mode, best_result)`: the `for mode in TrafficMode: solve_schedule(...)`
enumeration loop and `_mode_score()`, moved out of
`tracegen.solve_and_cache_schedule`. This part has no trace/cache
bookkeeping and no dependency on `archmodels`/`parsers.layer`, pure
solver logic, sits next to the existing `solve_schedule()`.

`ScheduleArtifact`/`load_schedule()` stay in `tracegen.py` (paired with
the caching they do) rather than moving into `mip_solver` or `cachesim`:
cachesim's own contract, confirmed by both its native and pure-Python
implementations, is `(weight trace, cache config) -> hit rate`. It has
never consumed `ScheduleArtifact`, tiles, or workload data in any version.

### A.2 `tracegen.py` changes

- `solve_and_cache_schedule()`: calls `mip_solver.solve_best_schedule()`
  (imported lazily, inside this function only, not at module level),
  then builds `ScheduleArtifact` and persists it. Same external
  signature/behavior.
- `ScheduleArtifact.mode` default changes from `TrafficMode.BASE.value` to
  the literal `"BASE"`, removing the last reason to import `TrafficMode`
  at module scope.
- Net effect: `load_schedule()`/`ScheduleArtifact` become Gurobi-free at
  import time, not just at runtime.
- Collapse `canonical_sample_indices()` and `random_sample_indices()` into
  one function, e.g. `sample_indices(n=100, seed=0, n_total=10000)`,
  always computing `sorted(random.Random(seed).sample(range(n_total), n))`
  live. Verified this reproduces today's hardcoded 100-sample list
  byte-for-byte at `n=100, seed=0`, lossless, no existing generated
  trace becomes orphaned.
- Delete `configs/sampling/sample_indices.json`, nothing needs to read
  it once the function above is live.
- Add one consolidated reconstruction function to `tracegen.py`. Given
  arch name, an already-loaded trace object, tiles, sample indices,
  workload dims, and `dram_num_steps`, dispatches to that arch's native
  bridge and returns `LayerWeightTrace`(s). This replaces the two
  copy-pasted dispatch blocks in the scripts being deleted below. Takes
  an already-loaded trace (not a path) so the new thin wrapper script can
  still load the mmap'd trace once per worker process, matching the
  existing perf-motivated pattern in `generate_weight_traces.py`.
- Move `reconstruct_samples_for_schedule()`, `reconstruct_tile_chunk()`,
  `load_weight_trace()`, and `iter_generated_traces()` out of
  `src/tracegen.py` into a new `dump/python_reference/` module (exact
  filename TBD, e.g. `tracegen_reconstruct.py`), consistent with how the
  other superseded pure-Python compute files were already archived there.
  `save_weight_trace()` stays live (still the only writer both live
  scripts use).
- Update `debug/04_diff_reconstruction.py`'s import of
  `tracegen.reconstruct_samples_for_schedule` to point at the new
  archived location instead. This script still needs to run (it's the
  native-vs-Python parity check), so it just changes where it imports the
  reference implementation from, not what it does.

### A.3 `scripts/` changes

- Delete `generate_weight_traces.py` and
  `generate_weight_traces_canonical100.py`.
- Delete `slurm/run_full_sweep_array.slurm`.
- Move `plan_trace_shards.py` to `dump/`.
- Add one new thin wrapper script (single script, not two) that covers
  both "one explicit combo" and "every layer for one arch" modes via CLI
  flags. It owns: argument parsing, which combos/samples to iterate,
  the two-pass breadth-then-depth ordering when running all layers, and
  all multiprocessing/`Pool` setup (including loading the mmap'd trace
  once per worker). It contains no native-bridge dispatch logic of its
  own; every chunk it hands to a worker calls straight into the new
  `tracegen.py` reconstruction function from A.2.
- Update `scripts/README.md` to match once the above lands.

### A.4 Verification-stage constraint

Any diff/parity run comparing old vs. new behavior (the debug script from
A.2, or ad hoc checks on the new seeded sample-index function) writes its
output to a scratch path outside `outputs/schedules/` and
`outputs/weight_traces/`, and deletes it after. The real cached
artifacts are never touched by a verification run.

### A.5 Unaffected

`cachesim`; `solve_schedules.py` and `scripts/tmp/solve_multinode_schedules.py`
(both call `tracegen.solve_and_cache_schedule()`, whose external signature
doesn't change); `scripts/tmp/analyze_multinode_schedules.py`.

---

## Part B: Multi-node architecture sweep

### B.0 Already resolved, no fresh investigation needed here

`log/2026-07-29-arch-dataflow-multinode-plan.md` (status: implemented)
already did the check this plan originally asked for in its Step 0:

- `arch.yaml` owns hardware (topology, `single_node`, instance counts,
  `num_pes`, byte capacities); `dataflow.yaml` owns dimension-residency
  policy (`node_dim_capacity`). These are separate files per arch already.
- `NodeLevel.local_buffer.entries` and `NoCLevel.entries` are real MIP
  byte-capacity constraints when present, and unconstrained when absent.
  `NodeLevel.pe.registers.entries` is parsed but never constrains
  anything (metadata only).
- **`instances` and `num_pes` are independent axes.** `num_pes` bounds
  the product of spatial factors achievable at one node and validates the
  dataflow's `{spatial: N}` mapping; it does not set how many nodes
  exist. Node fanout is controlled purely by `storage[NodeLevel].instances`
  relative to `storage[NoCLevel].instances`. This was confirmed
  experimentally: re-solving one composition at `num_pes` in
  `{64, 128, 256}` rejected 64 (undersized for the required spatial
  mapping), solved at 128, and solved at 256 with the same mapping
  (excess PE capacity simply unused).
- All 5 archs already have a first-cut `configs/arch/<arch>_multinode.yaml`
  (128-node baseline, flat 1 MiB/tensor `NoCLevel.entries`, **no
  `NodeLevel.entries` at all**) with schedules solved and cached under
  `outputs/schedules/multinode/`, and a first classification pass via
  `analyze_multinode_schedules.py`.

**What's genuinely new in this plan, not covered by that prior work:**
adding a sized `NodeLevel.entries` (weight/psum/vmem, 30:1:1 ratio) is a
constraint the existing multinode fixtures don't exercise at all today.
The mechanism was verified to work in isolation, but never combined with
an `instances` sweep and a real `NodeLevel` byte cap at the same time,
across all 5 archs. Treat this as new territory to validate, not a
repeat of B.0's audit.

### B.1 Instances × entry-size sweep

- Sweep `NodeLevel.instances` over `{16, 64, 256, 1024}`, for all 5 archs.
- Size `NodeLevel.entries` (weight/psum/vmem) from the dnn-noc-buffer-sizes
  reference, holding the ratio at `30:1:1`.
- Size `NoCLevel.entries` from the same reference, same `30:1:1` ratio.
- **Open input needed before the generator script can be written:** the
  dnn-noc-buffer-sizes reference currently only exists as prose in
  `survey-output/cache-locality-profiling-dnn-accel/` (a literature
  survey), and there's no extracted numeric table in the repo yet. That
  needs to be pulled into a concrete lookup (e.g. bytes per node at some
  reference point) before the generator can size anything.
- New config-generator script → `scripts/tmp/` (per
  `2026-07-29-arch-dataflow-multinode-plan.md`'s own rule: multi-node
  runner/generator scripts live only in `/tmp/` or `scripts/tmp/`, never
  in the repo root, `src/`, `debug/`, `profiling/`, or `log/`).
- New sweep-driver script (arch × dataflow × workload) → `scripts/tmp/`,
  reusing the same `solve_and_cache_schedule`/`mip_solver.solve_best_schedule`
  path as the rest of the pipeline.
- Report the total combo count before running anything (5 archs × 4
  instance counts × 2 trace_dirs × ~31 layers, up to ~1240 combos,
  fewer if some layers are invalid per arch).
- Infeasible combos are an expected, recorded outcome, not a bug, e.g.
  SpinalFlow's dataflow requires full CIN resident at NodeLevel, which
  some `(instances, entries)` pairs may not have room for.

### B.2 Post-sweep analysis

- Compute statistics and a structural classification of the resulting
  schedules (loop-to-level assignment, spatial vs. temporal placement),
  explicitly ignoring the actual temporal/spatial permutation *order*.
  This extends the existing GB-split/DRAM-permutation classifier in
  `analyze_multinode_schedules.py` to also key on `instances` count.
- Publish the visualization as an Artifact.

---

## Open items: resolved

1. Archived pure-Python reconstruct/read functions
   (`reconstruct_samples_for_schedule`, `reconstruct_tile_chunk`,
   `load_weight_trace`, `iter_generated_traces`) moved to
   `dump/python_reference/tracegen_reconstruct.py`.
   `debug/04_diff_reconstruction.py` updated to import from there; its
   native-vs-Python parity check still passes (verified against the
   `loas`/`tiny` debug fixture).
2. Collapsed sample-index function is `tracegen.sample_indices(n=100,
   seed=0, n_total=10000)`. New wrapper script is
   `scripts/generate_weight_traces.py` (kept the original name; the old
   two scripts are deleted, not renamed).
3. dnn-noc-buffer-sizes sourcing: used
   `survey-output/dnn-noc-buffer-sizes/phase6_report/report.md`'s own
   canonical references rather than inventing numbers. NodeLevel total =
   32 KiB, rounded from Timeloop's Eyeriss-like per-PE scratchpad total
   (4KB weight + 8KB input + 2KB psum = 14KB), the report's own words:
   "the single most-used benchmark geometry in the hardware-mapping
   research community." NoCLevel total = 1 MiB, matching both this
   repo's existing 128-node baseline fixtures and MAESTRO's canonical L2
   shared-buffer reference from the same survey. Both split 30:1:1
   (weight/psum/vmem) as specified. **This is a judgment call, not a
   unique reading of the survey** (real per-design buffer sizes in that
   same report span roughly 2 KB to 4 MB per tensor) -- flagging for
   explicit sign-off before running the actual solve sweep.

## Extra fix made during implementation, not in the original plan text

While verifying `load_schedule()`/`ScheduleArtifact` were actually
Gurobi-free at import time (not just in `tracegen.py` itself), found a
second, deeper leak: `nocsim/schedule/decode.py` (a hard dependency of
`load_schedule`) imported `SNN_GB_START_LEVEL` from `mip_solver/schedule.py`,
which also defines the Gurobi-dependent `create_schedule_vars` in the same
module -- so importing that one integer constant pulled in `gurobipy`
regardless of the `tracegen.py`-level fix. Moved `SNN_GB_START_LEVEL` to
`mip_solver/constants.py` (already gurobipy-free) and updated the three
consumers (`mip_solver/schedule.py`, `nocsim/schedule/decode.py`; 
`mip_solver/solve.py`'s import path was unaffected). Verified
`import tracegen` no longer touches `gurobipy` at all.

## Verification performed (2026-07-30)

- `sample_indices(n, seed)` reproduces the deleted JSON's values exactly
  for n=100, and reproduces the old two-tier scheme exactly for n=150 and
  n=4000 at multiple seeds (stdlib-only check, not project code).
- `import tracegen` no longer touches `gurobipy` (checked via
  `sys.modules`); `mip_solver.solve` does, as expected.
- `tracegen.load_schedule()` loads the `loas`/`tiny` debug fixture
  correctly, Gurobi-free.
- `debug/04_diff_reconstruction.py` (native vs. archived pure-Python)
  passes against the `loas`/`tiny` fixture after the import fix.
- `scripts/generate_weight_traces.py`'s single-combo mode, run against
  the `loas`/`tiny` fixture with output in a scratch directory (deleted
  after), produces output byte-identical to the pre-existing known-good
  fixture at `debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz`.
- The `--all-layers` mode's per-task worker (`_regenerate_layer`), same
  fixture, same scratch-then-delete method, same byte-identical result.
- `tracegen.solve_and_cache_schedule()` (now routed through
  `mip_solver.solve_best_schedule`), run as a real Gurobi solve against
  `loas`/`tiny`/`layer_00` in a scratch cache dir (deleted after),
  produces the identical mode, `dram_num_steps`, and full strategy as the
  pre-existing cached schedule at `debug/schedules/loas/tiny/layer_00.json`.
- `scripts/tmp/generate_multinode_arch_sweep.py` run for real: wrote 20
  YAMLs to `configs/arch/multinode_sweep/` (5 archs x 4 instance counts),
  each `num_pes` correctly read from that arch's existing 128-node
  baseline rather than re-hardcoded.
- `scripts/tmp/sweep_multinode_arch_sweep.py --dry-run`: **620 real
  combos** (5 archs x 4 instance counts x 31 total valid layers across
  both networks) -- not yet run for real; needs review of the buffer-size
  judgment call above first.

## 2026-07-31 update: dataflow re-cap, real bugs found running the real sweep, final results

### Per-variable capacity analysis motivated a dataflow change

Computing NodeLevel weight/psum/vmem byte requirements directly from each
arch's real solved factors (VGG16 `layer_01_features_3`, unconstrained
NodeLevel) showed the fixed 30:1:1 ratio only fit `loas`/`ptb`/`spinalflow`
(all `CIN: full`, weight-bound). `gustavsnn` and `prosperity` are
vmem/psum-bound instead (they keep HO/WO resident, not CIN), needing
2 MB-scale totals under that ratio -- 64x the swept ceiling, which is why
they solved 0/2480 combos each in the first real run.

Fix applied directly to the dataflow configs (not just a one-off test):
narrower spatial/temporal caps that shrink every arch's real requirement
into the swept 2-32 KiB range: `loas`/`ptb` COUT spatial 16->4,
`spinalflow` COUT spatial 128->8, `gustavsnn` COUT/HO spatial 8->4 and WO
8->4, `prosperity` COUT spatial 128->8 and HO/WO 16->4.

### Bugs found and fixed while actually running the 12,400-combo sweep

1. **`mip_solver.solve.solve_schedule` never disposed its Gurobi `Model`.**
   Added `model.dispose()` in a `finally` block. Necessary but NOT
   sufficient on its own for the next bug.
2. **A single process solving many different arch configs in sequence
   started silently misreporting genuinely-feasible combos as
   infeasible.** Confirmed by direct A/B: a fresh single-purpose process
   was always correct; the same process, after several distinct configs,
   was wrong. Root cause eventually pinned to Gurobi WLS session
   accounting, not just process staleness (see next item) -- the fix that
   actually worked is spawning a genuinely fresh, never-reused process
   per combo (`multiprocessing.get_context("spawn")` +
   `maxtasksperchild=1`), verified against the same failing ladder until
   it reproduced the correct fresh-process answer at every point.
3. **This WLS license has a real concurrent-session ceiling.** Running
   the spawn-per-combo fix at 64 workers crashed outright:
   `GurobiError: Too many sessions, 5 active sessions for a baseline of
   2`. Measured the real safe ceiling directly: 2-8 concurrent workers
   clean at both small and larger batch sizes; 16 stalls badly (matches
   an earlier login-node observation previously misattributed to
   login-node contention); 64 crashes outright. **8 workers** is the
   verified-safe setting used for the real run.
4. **The skip-existing check's path never matched what got written.**
   `_solve_one` built its own `cache_dir` with an extra `/arch/` prefix
   that `solve_and_cache_schedule` also appends internally, so every
   "already exists" check looked in the wrong directory and never
   skipped anything. Fixed by removing the duplicate prefix.
5. **`summary.csv` was overwritten (`"w"` mode) at the end of each run,
   not appended.** A run killed by Slurm's walltime cap (this partition's
   own 1-hour cap; several runs needed 30-59 minutes) lost all
   bookkeeping for everything already solved. Fixed: open in `"a"` mode,
   write one row per combo as it completes, never truncate.
6. **Infeasible combos have no recoverable artifact.** Only a successful
   solve persists a schedule JSON; an infeasible result exists nowhere
   except its `summary.csv` row. Bug 5's fix (append, don't overwrite)
   is what actually makes infeasible combos skippable on resume --
   without a durable `summary.csv`, every resume re-derives every
   already-confirmed-infeasible combo from scratch, which is most of
   this grid.
7. **Even with bug 5 fixed, already-solved combos still paid a full
   process-spawn cost just to be skipped**, because the pre-dispatch
   filter only consulted `summary.csv`, not the schedule JSONs
   themselves -- and a spawn's cost turned out to be comparable to an
   actual solve's (~20 real minutes wasted across ~4,600 combos this way
   in one run). Fixed by also scanning `cache_dir` directly for existing
   schedule JSONs and reconciling them into `summary.csv` up front, with
   zero spawns -- `scan_solved_from_disk()` in the sweep driver.

None of this changes bug 2/3's root mechanism understanding beyond "spawn
+ maxtasksperchild=1 + <=8 workers is empirically correct and safe on
this license" -- the exact reason a long-lived process eventually
misreports feasibility was not fully isolated (ruled out: raw Gurobi
call count in one process, fork vs. spawn as such, and an
infeasible-then-feasible ordering effect all in isolation).

### Final results

The full 12,400-combo grid completed across several resumed runs (each
capped by the interactive partition's 1-hour walltime): **3,956 solved,
7,328 infeasible, 0 errored, 12,400/12,400 accounted for.**

- All 5 architectures now have a feasible region (was 3/5 before the
  dataflow re-cap).

### Correction found 2026-07-31 (post-analysis): SKIPPED rows were being
### dropped from every feasibility/classification stat

Both `scripts/tmp/sweep_multinode_arch_sweep.py`'s own final tally and
`scripts/tmp/analyze_multinode_arch_sweep.py` only counted
`status == "OK"` as solved. `SKIPPED` (a combo whose schedule JSON was
found already on disk, from an earlier run, via `scan_solved_from_disk`)
is equally a genuinely-solved combo, not an unattempted one -- excluding
it undercounted every feasibility number and dropped 1,116 real solved
schedules from classification entirely. Fixed by treating
`status in ("OK", "SKIPPED")` as solved throughout. Corrected numbers
below supersede the ones in the previous section.

- **5,072 solved** (40.9%), not 3,956 (31.9%) as first reported.
- `loas` and `ptb` are **fully feasible (496/496) at 32 KiB with zero
  exceptions** -- the earlier report showed them at ~61% due to the
  undercount, incorrectly implying real capacity failures at 32 KiB that
  do not exist. `prosperity` remains fully feasible (496/496) at both
  16 KiB and 32 KiB.
- Within any one (arch, NodeLevel size) cell, feasibility is a **clean
  per-layer binary split, verified with zero exceptions across all 25
  (arch, size) cells**: every layer's own 16 (instances x noc_size)
  combos are either all solved or all infeasible, never mixed. The
  fractional percentages in the heatmap come entirely from aggregating
  31 layers with different real CIN/COUT/HO/WO, not from noise -- e.g.
  for VGG16 `layer_01_features_3`, per-variable NodeLevel bytes recomputed
  under the current (re-capped) dataflow: `loas`/`ptb` need 2.30 KiB
  (weight-bound), `spinalflow` 4.59 KiB (weight-bound), `gustavsnn`
  2.62 KiB (vmem-bound), `prosperity` 0.82 KiB (vmem-bound) -- all well
  under 32 KiB for this particular layer, but other layers' larger CIN
  push some combos past whatever NodeLevel size is being tested.
- NoCLevel size and `NodeLevel.instances` **both** show zero measured
  effect on feasibility once corrected: exactly 1,268 solves at each of
  the 4 values of each. The previously-reported "small instances effect"
  (924 vs. ~1,000-1,016) was itself an artifact of the same undercount,
  not a real difference.
- Structural classification (`scripts/tmp/analyze_multinode_arch_sweep.py`,
  NoC-S / NoC-T order / DRAM-T order only, NodeLevel dropped per the
  narrowed visualization scope) found **82 distinct classes** overall
  (was reported as 79 pre-correction, 6 before the dataflow re-cap): 12
  each for `loas`/`spinalflow`/`ptb`, 19 for `gustavsnn`, 50 for
  `prosperity`.

Updated report (same URL, redeployed):
https://claude.ai/code/artifact/655b00b8-1e1a-4635-bd24-4bc5bace9d83
