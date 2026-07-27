# Workflow understanding and optimization: today's plan

> Created: 2026-07-26. Rephrased workflow description, module map corrected
> against the actual repo, and a 4-step plan for today's workflow-review and
> optimization pass. Revised after a second round of comments covering
> NoCSim's inputs, a generalized CacheSim address layout, dropping
> `spatial_locality.py`, weight-trace tick recording, seed reproducibility,
> and parallelizing weight-trace generation.

## Context

The project's pipeline has grown module by module (mip_solver, archmodels,
nocsim) plus a set of informal profiling/analysis scripts (`profiling/`,
`scripts/locality_analysis/`, loose files at `src/` top level) that were
never consolidated into named modules. Today's goal is to pin down the
intended end-to-end workflow, compare it against the real code structure,
and use that comparison to drive a targeted optimization pass on the two
areas of active interest: weight-trace generation (ArchModel) and cache
config / CacheSim.

## Workflow, as understood and corrected today

1. **Inputs → MIP Solver**: arch config (`configs/arch/snn_arch.yaml`) and
   workload config (layer YAML) are the input interface, consumed by
   `src/mip_solver` (Gurobi model, `solve.py`), producing a solved
   **schedule** (JSON, `outputs/schedules/`) as an intermediate result.

2. **Schedule + general interface → ArchModel → weight trace + compute
   cycles**: `src/archmodels` (5 hardware configs) together with
   `src/tracegen.py` take the schedule and the "general interface", the
   real captured spike input data, held in the sibling repo
   `/u/yyu9/neuro_cache_trace/input_trace/loas/...`, and reconstruct a
   per-tile **weight-address trace** and **compute-cycle counts**
   (`mac_cycles`/`lif_cycles`) as intermediate results.

3. **Schedule + layer/arch config (+ optional compute cycles) → NoC Sim
   (incl. Performance Analyzer) → performance report**: `src/nocsim` is
   one module with two stages: a Python front end (`combine.py`) that
   turns schedule data into **transaction events**, and a C++ back end
   (`src/nocsim/eventsim`: `EventSim.h`, `NoC.h`, `Transaction.h`,
   `main.cpp`) that consumes those events and produces the performance
   report. "Performance Analyzer" is this C++ back end, not a separate
   module. Confirmed against code (see "Step 2 findings" for detail):
   the always-required inputs are the schedule JSON, the layer YAML, and
   the arch YAML. Real per-tile compute cycles are an *optional* input,
   supplied only by callers (e.g. `scripts/sweep_archmodel_layers.py`)
   that pass a live ArchModel `compute_model` plus the raw spike `trace`
   through to `combine()`; NoCSim recomputes cycles live from those two,
   it does not read the persisted weight-trace artifact from step 2. The
   plain CLI (`python -m nocsim.sim`) never supplies either, so its
   transaction sizes fall back to schedule-derived defaults.

4. **Weight trace + cache config + layout config → CacheSim → hit rate +
   visualization**: this module does not exist yet as real code, and is
   named **CacheSim**. Its intended scope, per today's review, covers two
   currently-separate plan documents plus a generalization of the address
   layout:
   - `log/2026-07-22-replacement-policy-cache-sim-plan.md`: LRU baseline,
     address mapping from a weight-trace event to a cache line, a defined
     cache-line format, and a sweep harness over cache size/associativity,
     producing hit-rate results across the swept config space.
   - `log/2026-07-23-input-driven-weight-locality-plan.md`: hot-zone
     locality diagnostics across `cin` (via a cache simulator over the
     expanded weight-address stream) and `hin`/`win`/`t` (via histograms
     directly on the raw spike trace). Folded into CacheSim's scope as a
     diagnostic sub-stage, since the `cin` half already builds and runs a
     cache simulator over the weight trace.
   - **Generalized layout, not a fixed tuple**: trace events are today
     stored as `(kh, kw, cin, cout_start, cout_end)` ranges. CacheSim
     needs to support any dimension ordering and any single dimension
     chosen as the ranged one, e.g. `(kh, kw, cout, cin_start, cin_end)`,
     `(cin, cout, kh, kw_start, kw_end)`, or a fully custom ordering. This
     layout is not to be hardcoded: it needs an explicit new field in
     `configs/arch/snn_arch.yaml` describing the chosen layout, which
     becomes an input to CacheSim alongside the weight trace and the
     cache config.

## Corrections and decisions from today's review

- **`neuro_cache_trace`** is the sibling capture repo
  (`/u/yyu9/neuro_cache_trace/`) holding raw captured spike `.npy` input
  data. It is the upstream "general interface" input consumed by
  ArchModel/`tracegen.py`, not a downstream layout converter.
- **`src/dram_permutation.py`** classifies the *MIP solver's* solved
  schedule output (`result.strategy.DRAM.temporal_permutation.loops`)
  into a canonical `M->K->N->T` super-dimension string, a Stage-1
  (mip_solver) schedule-analysis/visualization tool, unrelated to caching
  or weight traces. New work described in Phase 3 of
  `log/2026-07-20-full-weight-trace-sweep-plan.md`.
- **`src/spatial_locality.py`** (the D_C cross-address reuse-distance
  algorithm core) is no longer useful and is to be removed, along with
  the callers that exist only to drive it. See "Step 2 findings" below
  for the exact removal set.
- **`profiling/0723/*` and `scripts/locality_analysis/*`** (excluding the
  `spatial_locality.py`-only callers being removed) stay as exploratory
  scripts, not absorbed into CacheSim as a module dependency.
- **`src/dram_permutation.py` moves into `src/mip_solver/`**, revising
  the two earlier calls (grouping with `spatial_locality.py`, then
  staying at `src/` top level). It classifies the schedule that
  `mip_solver` itself produces, and is confirmed to be a single
  **arch-agnostic function**, not 5 arch-specific analyses:
  `src/mip_solver/**` never branches on architecture identity anywhere,
  and the 7 dimension names it reads (`KH`, `KW`, `CIN`, `COUT`, `HO`,
  `WO`, `T`) are defined once in `src/parsers/layer.py` and shared by
  every schedule regardless of which arch's YAML constrained the solve;
  the 5 archmodels only affect *which* schedule gets picked, never the
  schedule JSON's shape or dimension-naming. `src/mip_solver/cli.py`
  already has a near-identical helper, `_fmt_perm`, doing the same
  adjacent-dim fusion one level down (individual dims, not super-dims)
  over the exact same `s["DRAM"]["temporal_permutation"]["loops"]`
  structure, so `dram_permutation.py` belongs next to it as one
  arch-agnostic module inside `mip_solver`, not a separate top-level file.

## Weight-trace generation: additional requirements surfaced today

To review and implement alongside the existing ArchModel weight-trace
logic (`src/archmodels/*`, `src/tracegen.py`):

- **Tick recording for port-contention latency, all 5 archs**: a single
  tick can read multiple weight rows in parallel, and since a cache has
  at most 2 ports, compute latency depends on how many rows a tick
  actually reads at once. The weight trace needs a time-related field (a
  tick identifier per weight-row read) so this port contention can be
  modeled downstream, rather than treating all reads as latency-uniform.
  This applies to all 5 archmodels, not just GustavSNN, though each
  arch's per-tick row count comes from its own already-documented cycle
  model (see "Step 2 findings" for the per-arch breakdown), not a single
  shared formula.
- **Deterministic sampling**: weight-trace generation samples a subset of
  input traces (e.g. 100) using a random method. This needs a fixed,
  recorded seed so repeated runs produce identical weight traces.
- **Speed up generation**: weight-trace generation is currently slow;
  see "Step 2 findings" for the parallelization/speedup methodology
  breakdown (CPU multiprocessing, cluster-level Slurm parallelism, a
  possible C++ rewrite, and why GPU was already deliberately rejected for
  this workload) and the profiling step needed before committing to any
  of those.

## In-flight background jobs (2026-07-26)

After adding `tick_ids` to all 5 archs' `weight_ticks`, existing cached
weight traces under `outputs/weight_traces/` predate the field and need
backfilling. Two detached Slurm jobs handle this, both submitted via
`sbatch` so they run independently of any Claude Code session:

- **Job 20504645** (`scripts/slurm/run_patch_tick_ids.slurm`): patches
  `tick_ids` in place for LoAS/PTB/SpinalFlow/Prosperity (12,400 files),
  safe because their `event_to_ticks` is always `range(len(weight_addresses))`.
  Logs: `logs/patch_tick_ids_20504645.out`/`.err`.
- **Job 20504589** (`scripts/slurm/run_gustavsnn_regeneration.slurm`):
  full regeneration for GustavSNN (3,100 files, existing data deleted
  first), since its tick derivation needs the wave/submatrix structure
  that only exists during reconstruction, not recoverable from the
  persisted address list. Logs: `logs/gustavsnn_regen_20504589.out`/`.err`.

Check status with `squeue -u yyu9` or by reading the log files above,
from this session, a new one, or directly, no Claude session needs to
stay alive for these to keep running.

## SpinalFlow correctness gate, resolved (2026-07-26)

While restoring the Slurm array wrapper for the full sweep, found the
07-20 plan's flagged gate (155 schedules, 31 missing the `mode` field)
was entirely SpinalFlow: all 31 of its schedules were missing it.
Investigation found `configs/arch/spinalflow.yaml` didn't exist at all
(unlike LoAS/PTB/GustavSNN/Prosperity, each with their own tuned YAML;
`loas.yaml`'s own comments already referenced "mirrors
spinalflow.yaml's reasoning", confirming it was always supposed to
exist). A fresh solve against the generic `snn_arch.yaml` produced a
wildly different schedule (`dram_num_steps` 294,912 vs. the cached
1,024), suggesting real staleness, until the user supplied the correct
`configs/arch/spinalflow.yaml`. Spot-checking 3 combos against it matched
exactly (`mode='gb_oooo'`, same `dram_num_steps`, same DRAM permutation
in all 3), confirming the cached schedules and SpinalFlow's existing
weight-trace corpus (currently being patched by job 20504645) were valid
all along, only the config file and the `mode` field were missing. Ran
`scripts/solve_schedules.py --archs spinalflow --force` to re-solve all
31 for real; all 155 schedules now have `mode` populated, 0 missing.
No SpinalFlow regeneration needed.

## Storage shortfall and scoped-down sampling (2026-07-26)

Full 5-arch x 10,000-sample sweep estimated at ~2.15TB (from real
per-sample sizes measured today: 13GB/12,400 files for the 4
non-GustavSNN archs at 100 samples/layer, 8.4GB/3,100 for GustavSNN),
exceeding /work's ~1.6TB measured available (df; the authoritative `lfs
quota -g delta_bebv /work` shows no enforced group quota, so the
constraint is real physical free space on this mount, not policy).
Scoped down to **4000 samples/layer** (~856GB estimated). Added
`tracegen.random_sample_indices(n, seed=0)`: the canonical 100 plus
n-100 more, drawn without replacement with a fixed seed, always a
superset of the canonical 100 so already-generated/patched work is never
wasted as n grows. Added `--n-samples`/`--seed` to
`scripts/generate_weight_traces.py` and `generate_weight_traces_tile_parallel.py`
(third mode alongside `--canonical-samples` and
`--sample-start`/`--sample-count`). `scripts/slurm/run_full_sweep_array.slurm`
updated to use `--n-samples 4000` instead of the full 10,000.

## GustavSNN C++ rewrite (2026-07-26)

Per the profiling finding above (94% Python object/tuple construction,
not numpy gather), ported GustavSNN's `reconstruct_tile_sequence_batch` +
`event_to_address` + `event_to_ticks` to C++:
`src/archmodels/gustavsnn/native/` (`GustavGen.h`, `main.cpp`, `Makefile`,
mirrors `src/nocsim/eventsim`'s existing convention: standalone binary,
subprocess invocation, not Python bindings). One subprocess call per
(layer, sample-chunk) does the whole per-tile loop internally, avoiding
eventsim-style per-call overhead. `src/archmodels/gustavsnn/native_bridge.py`
bridges Python: packs tiles/trace to a compact binary format, invokes the
binary, unpacks results into the same `LayerWeightTrace` shape
`reconstruct_samples_for_schedule` produces.

**Verified against the Python implementation on real data**: 20 samples x
1024 tiles (20,480 tile-sample pairs) of `gustavsnn/resnet19_T4_all/layer_01_layer1_0_conv1`,
**0 mismatches** on addresses, tick_ids, and mac_cycles. **9.8x speedup**
(198.9s -> 20.3s) including subprocess overhead.

Wired into `scripts/generate_weight_traces_canonical100.py`: GustavSNN
now uses the native path automatically (`arch_name == "gustavsnn"`
branch in `regenerate_layer`), other 4 archs unaffected. GustavSNN
regeneration relaunched with it (replacing the Python-path job that had
made partial progress, that data is valid, just slower to produce, and
was left in place since skip-existing naturally reuses it).

[done] Wired into `scripts/generate_weight_traces.py`'s `_process_chunk`
too (same `arch_name == "gustavsnn"` branch). `run_full_sweep_array.slurm`
updated to route GustavSNN through the same sample-chunked script as
every other arch now, retiring the special-case
`generate_weight_traces_tile_parallel.py` routing for it (that script's
whole rationale, avoiding re-running an expensive Python per-tile loop
per worker, no longer applies once the loop is native C++).

**OOM on the first real run, found and fixed (2026-07-26)**: pass 2 (100
samples/layer) OOM-killed all 16 workers. Two independent causes, both
fixed:
1. `native_bridge.py` was writing the FULL trace (all ~10,000 samples,
   up to 2.6GB/layer) to a temp file on every call regardless of how
   many samples were actually requested. Fixed: slice `trace[:,
   sample_indices]` before handing off to the C++ binary; only the
   requested samples' worth of data gets written/read.
2. `generate_weight_traces_canonical100.py` loaded each layer's trace
   with `load_layer_trace(..., mmap=False)` (the default), so 16
   concurrent workers could each eagerly materialize a full multi-GB
   trace into RAM. Fixed: added `mmap=True`, matching
   `generate_weight_traces.py`'s own call, which never had this bug.

Verified the fix on real data at deliberately tight memory budgets: a
realistic 10-sample chunk (matching `SAMPLE_CHUNK_SIZE`) used ~2.25GB
and fit comfortably in a 4GB srun allocation. Relaunched the real
regeneration with `--cpus-per-task=8` (down from 16) for extra safety
margin against imperfect between-chunk memory release, still investigating
the full accounting for why 16 workers' estimated ~36GB aggregate
exceeded the 64GB allocation in the original failure.

## Full 4000-sample array sweep launched (2026-07-26)

Per user direction: launched the full sweep for all 5 archs in parallel
with the still-running GustavSNN canonical-100 job (`srun` job 20505629,
writing to `outputs/weight_traces/` in home), rather than waiting for it
and migrating first. Home data (all archs, including GustavSNN's
in-progress canonical-100) is left untouched, the array sweep writes to
`/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/` instead, a
different location, so no conflict, but also no reuse: the array sweep's
skip-existing won't see the canonical-100 work sitting in home and will
regenerate that portion fresh at `/work` too (accepted tradeoff for not
touching home right now).

`scripts/slurm/run_full_sweep_array.slurm` given an arch-conditional
`WORKERS`: 8 for GustavSNN (matching the just-validated safe setting),
64 for the other 4 (unchanged, Python path, much lower per-sample memory
footprint). Submitted as 5 independent `sbatch --array=0-30` jobs (one
per arch, so each can be monitored/cancelled/resubmitted independently):

| Arch | Job ID |
|---|---|
| loas | 20505940 |
| ptb | 20505941 |
| spinalflow | 20505942 |
| prosperity | 20505943 |
| gustavsnn | 20505944 (`--cpus-per-task=8 --mem=64G` override) |

All fully detached (`sbatch`), independent of any Claude Code session.
Monitor via `squeue -u yyu9` or `logs/weight_trace_<arch>_<jobid>_<taskid>.out`/`.err`.

**Superseded, see below**: all 5 jobs (20505940-20505944) were cancelled
per user direction, in favor of porting all 5 archs to C++ first (the
Python path was "too slow"), then regenerating everything at once with a
fixed seed once every arch has a verified-correct native path.

## All 5 archs ported to C++ (2026-07-26)

Extended GustavSNN's native pattern (`src/archmodels/<arch>/native/` +
`native_bridge.py`, standalone binary + subprocess, mirrors
`src/nocsim/eventsim`'s existing convention) to the remaining 4 archs.
Each verified byte-identical against
`tracegen.reconstruct_samples_for_schedule` on real data (20 samples x
the largest cached layer, `resnet19_T4_all/layer_01_layer1_0_conv1`,
`gpuA100x4-interactive` compute node) before being wired in:

| Arch | Mismatches | Speedup | Notable algorithm detail |
|---|---|---|---|
| GustavSNN | 0 / 20 samples x 1024 tiles | 9.8x | wave-derived ticks (see earlier section) |
| SpinalFlow | 0 / 20 samples x 1024 tiles | 1.7x | simplest algorithm, Python path already fast |
| LoAS | 0 / 20 samples x 8192 tiles | 7.4x | any-across-T non-silent test per (kh,kw,cin) |
| PTB | 0 / 20 samples x 8192 tiles | 9.5x | stSAP 2-pass + systolic `mac_cycles` formula ported verbatim |
| Prosperity | 0 / 20 samples x 1024 tiles | **91.0x** | O(M^2) ProSparsity prefix search, row bits packed as uint64_t bitmasks; the one arch whose Python path needed its own inner-loop vectorization (reconstruct.py's own docstring) to get any speedup at all -- C++ removes that bottleneck entirely |

Correctness-critical subtlety caught and replicated exactly: Prosperity's
`ProsperityReconstructed.rows` (and therefore `event_to_address`'s
emitted addresses) are in **processing order** (ascending popcount,
stable sort), not original row-major `(ho, wo)` order -- the C++ port
builds rows row-major for bit extraction, then iterates/emits in the
popcount-sorted order to match.

Both generation scripts (`generate_weight_traces.py`,
`generate_weight_traces_canonical100.py`) now have all 5 archs in their
`_NATIVE_BRIDGE_MODULES` registry -- every arch uses its native path
automatically, no Python Protocol dispatch left in the hot path for any
of them.

**Mid-work quota incident**: home hit 103G/103G again (GustavSNN's
canonical-100 job had grown it), blocking file creation entirely mid-port.
Fixed by migrating just `outputs/weight_traces/gustavsnn/` (4.9GB) to
`/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces_home_backup/gustavsnn/`
or (verified count match, then deleted the home copy), freeing ~5GB
without touching the other 4 archs' data in home per user instruction.
Home now at 98G/103G.

**GustavSNN's canonical-100 job (20505629) finished incomplete**:
1,573/3,100 files, `COMPLETED` state, exit 0, 33:48 elapsed (well under
the 58-minute limit, not a timeout), but all 12 vgg16 layers stuck at
exactly 10 files (pass-1-only, pass 2 never touched them) while most
resnet19 layers finished. stdout was completely empty (0 lines) despite
a 33-minute run, root cause not yet investigated. Needs a follow-up run.

## Full regeneration launched, all 5 archs native (2026-07-26)

Pre-launch memory check: all 4 remaining archs' native paths, 10-sample
chunk (realistic `SAMPLE_CHUNK_SIZE`) on their largest cached layer,
cumulative process RSS peaked at ~2.03GB, comfortably under GustavSNN's
already-validated ~2.25GB. At 64 workers that's ~128GB, well within the
array script's 240GB allocation. Judged safe to launch at full
concurrency without further per-arch isolation testing.

Relaunched the full 4000-sample array sweep (same `run_full_sweep_array.slurm`,
same arch-conditional `WORKERS`: 8 for GustavSNN, 64 for the rest), now
with every arch on its native C++ path, all writing to
`/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/`:

| Arch | Job ID |
|---|---|
| loas | 20506410 |
| ptb | 20506411 |
| spinalflow | 20506412 |
| prosperity | 20506413 |
| gustavsnn | 20506414 |

All detached (`sbatch --array=0-30`, 155 tasks total), independent of any
Claude Code session. Monitor via `squeue -u yyu9` or
`logs/weight_trace_<arch>_<jobid>_<taskid>.out`/`.err`.

**Still outstanding**: GustavSNN's incomplete canonical-100 run in home
(1,573/3,100, vgg16 layers stuck at pass-1-only) has not been re-run or
root-caused (empty stdout despite a 33-minute completed run) -- separate
from this /work sweep, not blocking it.

## Step 2 findings: mismatches between the workflow and the actual code

- **`spatial_locality.py` removal set** (confirmed by import graph, not
  just filename grep):
  - Real, direct importers, remove alongside it:
    `scripts/locality_analysis/compute_dc_histograms.py`,
    `scripts/locality_analysis/plot_dc_distributions.py`,
    `scripts/locality_analysis/plot_dc_stacked_bar.py`,
    `scripts/locality_analysis/channel_locality.py` (uses
    `adjacent_cin_neighbors`), `profiling/0723/access_pattern.py`.
  - Transitively broken:
    `scripts/locality_analysis/channel_locality_delta_sweep.py` imports
    `layer_channel_locality_multi` straight from `channel_locality.py`,
    so it goes with it.
  - Dead once `compute_dc_histograms.py` is gone:
    `scripts/locality_analysis/run_remaining_histograms.sh`,
    `run_remaining_histograms_parallel.sh`,
    `scripts/slurm/run_dc_histogram_array.slurm` (all three exist only to
    drive that script). `outputs/locality/histograms/*.json` becomes
    orphaned output data, left in place unless you want it cleaned up too.
  - Also to remove (per your call, not kept as a one-line fix):
    `scripts/locality_analysis/channel_locality_delta_sweep_exact.py`.
    It only borrowed the trivial `_layers_for` helper from
    `channel_locality.py`, no D_C/spatial_locality logic at all, so it
    could have been kept standalone with a one-line fix, but it's being
    removed alongside the rest of the D_C-era scripts instead.
  - Fully independent, unaffected, keep as exploratory:
    `scripts/locality_analysis/kernel_window_locality.py`,
    `kernel_window_locality_cross.py` (both only import `tracegen`, a
    different locality metric entirely).
  - Fully independent, unaffected, keep as the real Phase-3 deliverable:
    `scripts/visualize_dram_permutation.py` (only imports
    `dram_permutation`, not `spatial_locality`). The other three scripts
    that filename-grep for "dram_permutation" only reference it in a
    palette-convention comment, not an actual import, so removing
    `spatial_locality.py` doesn't entangle `dram_permutation.py` at all.

- **Tick/port gap, confirmed real and checked across all 5 archs**: none
  of the 5 `cycles.py` files persist a per-tick grouping into
  `TileWeightTrace` today, they only use it internally to produce an
  aggregate `cycle_count`. But the actual per-tick row count differs by
  architecture, so this is not one shared formula to copy everywhere:
  - **GustavSNN**: genuinely multiple *distinct* weight rows read in
    parallel per tick. `_wave_cycle_count` groups up to
    `PE_COUNT_MAX=8` non-zero rows per wave (one tick), multiple waves if
    a tile has more. This is the real multi-row-per-tick case that needs
    a tick field with >1 rows per tick.
  - **LoAS**: `access_cycle_count = compute_cycle_count =
    popcount(bitmask)`, one weight-fetch cycle per non-silent row,
    already one row per cycle. A tick field here is a trivial 1:1 with
    row index, no batching to record.
  - **Prosperity**: one residual-spike-bit row fetch per cycle
    (`cycle_count = sum over rows of sum(row.pattern)`), same
    one-row-per-cycle shape as LoAS.
  - **SpinalFlow**: one spike event per cycle (`len(events)`), same
    one-row-per-cycle shape again.
  - **PTB**: a systolic pipeline (`PE_ROWS_MAX` x `PE_COLS_MAX`), one new
    line issued per cycle but multiple rows in flight across pipeline
    stages at once (`i + r + c` timing), a different kind of overlap than
    GustavSNN's same-cycle parallel fetch, not a simple rows-per-tick
    count.
  Conclusion: add the tick field to `TileWeightTrace` for all 5 archs for
  a uniform CacheSim-facing format, but derive each arch's actual
  per-tick contents from its own cycle model above, GustavSNN is the only
  one where "multiple rows in one tick" is real batching; PTB needs its
  own pipeline-aware definition; LoAS/Prosperity/SpinalFlow are
  degenerate (tick == row index).

- **Sample-seed reproducibility, already solved but not canonical**:
  `tracegen.py`'s `reconstruct_samples_for_schedule` takes an explicit
  `sample_indices` argument and never randomizes internally. The main
  pipeline entry point (`scripts/generate_weight_traces.py`) uses
  `--sample-start`/`--sample-count`, a deterministic contiguous range,
  not randomness. The actual "pick 100 random samples with a fixed seed"
  logic lives only in `profiling/0723/regenerate_weight_traces.py` +
  `profiling/0723/sample_indices.json` (seed 0, already fixed and
  persisted, already reused by the cin-locality diagnostic scripts). The
  fix is to promote that seed-0 selection to the single canonical source
  used everywhere 100 random samples are needed, not add a new seed.

- **Parallelization / speedup methodology, three orthogonal axes**:
  1. **Numpy vectorization** (already used): `format_input_batch` gathers
     across all requested samples in one vectorized call per tile, not a
     per-sample Python loop.
  2. **Multiprocessing, intra-combo** (already used):
     `scripts/generate_weight_traces.py` /
     `generate_weight_traces_tile_parallel.py` fan out via
     `multiprocessing.Pool` (`--workers`) within one (arch, layer) combo.
  3. **Cluster-level, cross-combo** (missing, already scoped): a Slurm
     array over the 155 combos, the same gap Phase 0 of
     `log/2026-07-20-full-weight-trace-sweep-plan.md` already identified
     (restoring the wrapper deleted in commit `ee26d70`, recoverable via
     `git show ee26d70^:scripts/...`). This is orthogonal to the two
     questions below and can proceed regardless of how they're answered.

  On your two specific questions:
  - **C++ on CPU**: plausible, but the win is unproven without profiling
    first. The 2026-07-18 design doc
    (`dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md`)
    already characterizes this workload as "a gather + boolean-reduction
    workload, bandwidth-bound, no matmuls." For that shape, numpy's C
    internals already do the bulk arithmetic; a C++ rewrite would only
    win by removing Python-level overhead that numpy doesn't cover, most
    plausibly the per-tile construction of many small Python objects
    (`LoASLine`, `ProsperityRow`, etc., one per tile per sample) and any
    remaining per-tile Python loop (`reconstruct_tile_chunk`'s docstring
    calls out exactly this loop for GustavSNN's ~8000 tiles/sample). That
    object-construction/looping overhead is the concrete thing to profile
    before deciding whether a C++ port is worth building.
  - **GPU**: already explicitly and deliberately rejected in that same
    design doc's decision log, not merely deferred: bandwidth-bound
    gather with no matmuls is not a natural GPU win, the final per-tile
    Python object construction stays CPU-side regardless of where the
    gather ran, and the cluster's per-allocation cost is identical
    whether or not the GPU is used, so there's no opportunity-cost
    argument either. Revisiting this needs new profiling evidence that
    contradicts that reasoning; none has been gathered.
  - **Profiling done (2026-07-26), verdict: C++ is worth it**. Ran
    `cProfile` over a real 10-sample chunk of `layer_01_layer1_0_conv1`
    (the largest cached layer) via `reconstruct_samples_for_schedule`,
    for both GustavSNN and LoAS, on a compute node:

    | Arch | Total | `reconstruct_tile_sequence_batch` (dataclass construction) | `event_to_address` (tuple construction) | numpy ops (`nonzero`/`reduce`/`tolist`/etc.) |
    |---|---|---|---|---|
    | GustavSNN | 43.9s | 19.1s (43%) | 22.4s (51%) | <1s (~2%) |
    | LoAS | 25.0s | 15.5s (62%) | 5.1s (20%) | <1s (~4%) |

    Confirmed across two independent archs: numpy gather is not the
    bottleneck (well under 1s either way), 82-94% of total time is pure
    Python object/tuple construction, `reconstruct_tile_sequence_batch`'s
    per-tile `GustavLine`/`GustavSubmatrix`-style dataclass construction
    and `event_to_address`'s list-comprehension tuple building. This
    directly confirms the 2026-07-18 design doc's own hypothesis. A C++
    rewrite should target exactly these two hot paths (per arch), not the
    numpy broadcasting, which is already fast. New `event_to_ticks` code
    is negligible overhead (1.1s of GustavSNN's 43.9s).
  - **Not yet done**: the rewrite itself (build system, Python/C++
    interface, one implementation per arch) is a substantial undertaking
    on its own, deferred until explicitly scoped.

## Corrected module map

| Stage | Module | Status |
|---|---|---|
| Schedule solving | `src/mip_solver` | exists |
| Weight trace + compute cycles | `src/archmodels`, `src/tracegen.py` | exists; needs tick recording, canonical seed, cross-combo parallelism |
| NoC sim + Performance Analyzer | `src/nocsim` (Python front end + `eventsim` C++ back end) | exists |
| CacheSim (hit-rate sweep + locality diagnostics + generalized layout expansion) | none yet | to be built, scope = 07-22 + 07-23 plans + generalized layout config |
| Schedule analysis | `src/mip_solver/analysis/dram_permutation.py` | done: moved from `src/dram_permutation.py`, arch-agnostic |
| Reuse-distance analysis | ~~`src/spatial_locality.py`~~ | done: removed, see removal set above |

## Plan of execution for today

1. **Workflow understanding** (this document), done.
2. **Read the whole project and identify mismatches** (this document,
   "Step 2 findings" above), done.
3. **Manual review and optimization**, focused on:
   - Weight-trace generation logic in ArchModel (`src/archmodels/*`,
     `src/tracegen.py`):
     - Add a tick field to `TileWeightTrace` for all 5 archs, deriving
       each arch's actual per-tick row grouping from its own cycle model
       (GustavSNN's waves, PTB's pipeline timing, the degenerate
       one-row-per-tick case for LoAS/Prosperity/SpinalFlow), enabling
       2-port contention modeling downstream in CacheSim.
     - [done] Promoted the seed-0, 100-sample selection to
       `configs/sampling/sample_indices.json` +
       `tracegen.canonical_sample_indices()`; `scripts/generate_weight_traces.py`
       and `generate_weight_traces_tile_parallel.py` both gained a
       `--canonical-samples` flag (mutually exclusive with
       `--sample-start`/`--sample-count`) to use it; the former dedicated
       driver moved and was rewired too (see corrections above).
     - [done] Profiled the generation pipeline (see "Speedup methodology"
       above): numpy gather is fast (<1s), 82-94% of time is Python
       object/tuple construction. C++ would help but is a substantial
       undertaking, deferred; user chose to prioritize cluster-level
       parallelism first.
     - [done] The Slurm array wrapper was already restored/adapted in an
       earlier session (`scripts/slurm/run_full_sweep_array.slurm`,
       `scripts/plan_trace_shards.py`, `outputs/schedules/jobs.txt`, all
       present and verified consistent, 155 combos). Its own comments
       already document the GPU-partition-workaround constraint
       rediscovered this session. Not new work, just verified ready,
       modulo the SpinalFlow correctness gate below.
   - [done] Remove `src/spatial_locality.py` and the full removal set
     identified in Step 2 findings, including
     `channel_locality_delta_sweep_exact.py`.
   - [done] Move `src/dram_permutation.py` into
     `src/mip_solver/analysis/dram_permutation.py` (an `analysis`
     subpackage, since it's a post-hoc analyzer over solved schedules,
     not part of solving itself; one arch-agnostic module, no per-arch
     variants), update its one real caller
     (`scripts/visualize_dram_permutation.py`)'s import.
   - Cache config handling and CacheSim logic (currently
     `profiling/0723/lru_cache.py`, `cin_locality_sweep.py`, and the
     07-22/07-23 plan content), toward consolidating it into a real
     `CacheSim` module, including the new generalized layout config in
     `configs/arch/snn_arch.yaml`.
4. **Draw the workflow graph** reflecting the optimized structure, after
   step 3's manual review is complete.

## Open items to resolve during step 3

- Exact schema for the new layout field in `configs/arch/snn_arch.yaml`
  (how a dimension ordering plus one ranged dimension is expressed).
- Exact form of the tick field to add to `TileWeightTrace`, and each
  arch's per-tick derivation rule (GustavSNN's waves, PTB's pipeline
  timing, the degenerate case for LoAS/Prosperity/SpinalFlow).
- Target module path/name for the new `CacheSim` code (e.g.
  `src/cachesim/`).
