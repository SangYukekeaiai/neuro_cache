# eval_scaling execution chain - AWAITING REVIEW, nothing implemented

The stage-by-stage chain for the design in `plan.md`. That file owns the
scope, the metric definitions, the schedule-identity argument and the open
questions; this one owns the order of operations, the per-stage inputs and
outputs, and the gates. Where the two could disagree, `plan.md` governs.

**S0 can start.** The four questions that gated it were closed by the user on
2026-11-16: the workload is the CIFAR-10 `B09/loas_vgg16_T4_n500` capture, the
grid is 1x/2x/4x, the figure carries three series including the multi-node
cache arm, and the previous campaign's Stokes array is cancelled. Of what is
still open, only **Q7** (the four non-LoAS mapspace pairs) is consumed by S0,
and it is a confirm-or-replace of a stated rule rather than a missing input.

**No stage inherits an artifact.** `zoo/eval_scaling/outputs/` and
`configs/` do not exist; every input below is produced by an earlier stage
or snapshotted from outside the figure. The cancelled array's rows are not
read by anything here.

## Sweep definition

| series | node mapspace | nodes | per-node L1/`lb` weight | shared L2/`GB` weight | total weight storage | simulator |
|---|---|---|---|---|---|---|
| single-node spad | KH/KW/CIN/T full, COUT spatial = full node | 1 | 1,048,576 B x m | - (`single_node: true`, direct DRAM->node) | 1,048,576 B x m | nocsim |
| multi-node spad | KH/KW/CIN/T full, COUT spatial = 1/16 | 16 | 32,768 B x m | 524,288 B x m | 1,048,576 B x m (16*lb + GB) | nocsim |
| multi-node cache | the multi-node schedule, unchanged | 16 | `l1_size_bytes` = 32,768 x m | `l2_size_bytes` = 524,288 x m | 1,048,576 B x m | cachesim |

`m` in **{1, 2, 4}**. `16 * 32768 * m + 524288 * m == 1048576 * m` at every
`m`, asserted in `make_configs.py:124-125` and to be asserted for the cache
configs too. All three series hold equal total weight bytes at every point,
which is what makes the comparison a comparison of *organization* rather than
of size. psum/vmem are held constant across the sweep so only weight capacity
moves; the caption must say so.

The COUT splits above are LoAS's. **The other four architectures' splits are
`plan.md` Q7 and must not be guessed.** The cache arm's per-core geometry
depends on the schedule's NoC-level spatial product and is **not known until
S1b prints it** (`plan.md` 7.7, Q12).

## Case arithmetic

With `A` = 5 architectures, 3 capacity points, `L` = 13 layers, `S` = 10
samples:

- **S1 solves** = `A x 2 x 3 x L` = **390**. The cache arm adds none: it
  reuses the multi-node schedules.
- **Scratchpad cases before dedup** = `390 x S` = **3,900**.
- **Scratchpad cases after dedup** = `(distinct schedules) x S`, which S1b
  measures. Bound from `plan.md` section 4: the single side collapses 39
  (layer, point) pairs per arch to 13 if the flatness finding holds, the multi
  side falls somewhere between 13 and 39, so 3,900 cases become between
  **1,300 and 2,600**.
- **Cache cases** = `A x 3 x L x S` = **1,950**, **none deduped** - cachesim
  reads the capacity out of its own config, so two points sharing a schedule
  share the trace and not the result (`plan.md` section 4).
- **Total simulation** = **3,250 to 4,550 cases.**

The 65 % dedup measured on the deleted LoAS campaign was over a *five*-point
grid and is not this figure's number.

**12 vs 13 layers**: 13 is the whole set, 12 is the convolutions alone
(`plan.md` Q2). `L` above assumes 13.

## Stages

### S0 - configs, from nothing (Delta, no compute)
- **Input:** `plan.md` sections 2, 6 and 7; the `B09/loas_vgg16_T4_n500`
  capture `meta.json` (layer dims and the valid-layer list); the five campaign
  mapspaces under `zoo/wt500_fig3cfg/mapspaces/`;
  `zoo/wt500_fig3cfg/arch.yaml` as the bitwidth and node-shape base;
  `examples/cache/base.json` as the cache base.
- **Component:** `zoo/eval_scaling/make_configs.py`, **extended** to emit per
  architecture rather than for LoAS alone, and to emit the three cachesim
  config JSONs.
- **Output:** `configs/arch_{arch}_{side}_x{m}.yaml` (30),
  `configs/mapspaces_{arch}_{side}/` (10), `configs/cache_x{m}.json` (3),
  `configs/sweep_config.json`, plus a snapshot of every external input with
  its SHA256.
- **Gate:** the equal-capacity assertion passes for every architecture **and
  for the three cache configs**, and every emitted mapspace is a one-field
  edit of its campaign original.

### S1 - schedules (Delta login; Gurobi lives here)
- **Input:** per case, arch yaml + mapspace + layer dims.
- **Component:** `lays.scheduler`, driven by `zoo/eval_scaling/gen_inputs.py`
  (a thin wrapper over the frozen `wt_gen_inputs_snapshot.py`, with the
  capture pinned at `gen_inputs.py:23`). `Threads=1`, single-threaded BLAS.
- **Output:** `outputs/s1/{arch}/{side}_x{m}/schedules/{arch}/{capture}/{layer}.json`
  and the matching `workloads/` layer yamls.
- **Gate:** every solve `OPTIMAL`. Any `INFEASIBLE` is recorded per
  `plan.md` Q6 - Prosperity's mapspace is known to reject layers on
  `cap_NodeLevel_psum` - and the answer is settled before S3.

### S1b - schedule identity, dedup, and the cache arm's geometry (Delta, seconds)
- **Input:** every S1 schedule.
- **Component:** **new** `zoo/eval_scaling/dedup.py`.
- **Method:** `plan.md` section 4. Canonical key is a SHA256 over
  `{result.strategy, dram_num_steps, mode}`, sorted keys, **with the arm in
  the key** so no cache point can be deduplicated. `arch_yaml_sha256` and
  `result.configs` are excluded deliberately: both vary at every capacity
  by construction, so a byte-level hash reports every schedule as different
  and is the wrong test.
- **Output:** `outputs/dedup_map.json` mapping every
  (arch, arm, side, layer, capacity) to its representative, and
  `outputs/cases.txt` holding scratchpad representatives plus **every** cache
  point.
- **Gates:** (a) the per-architecture saving reported before S3 is sized, with
  no number inherited from any earlier campaign; (b) the single-node flatness
  finding of `plan.md` section 3 confirmed or refuted per architecture;
  (c) the **NoC-level spatial product** of the first multi-node solve printed
  per architecture - if it is not the node count, **stop**: the cache series
  needs generator or simulator work this plan has not scoped
  (`plan.md` 7.7, Q12).

### S2 - pilot (two Stokes tasks)
- **Input:** one scratchpad representative case, and one cache case.
- **Component:** `run_case.py` end to end; and the
  `gen --stream | cachesim_run` pipe end to end.
- **Output:** wall time and peak RSS for one (point, layer) over `S` samples,
  **per arm** - the two arms run different simulators and neither is sized
  from the other - and **the second eventsim invocation timed separately**
  rather than assumed free (`docs/q11_row1.md`).
- **Gate:** reviewed before the array is sized. **No eval_scaling S4 run has
  ever completed and no cachesim run has ever been made on a stream from this
  capture, so both arms are unsized until this runs.**

### S3 + S4 - trace generation and scratchpad simulation (Stokes Slurm array)
- **Input:** S1 schedules shipped over the bridge; the capture's spike
  samples; the arch yaml.
- **Components:** `lays.weight_trace_gen` (`run_case.py:63-69`) then
  `lays.nocsim --simulate` (`run_case.py:82-88`), one array task per
  (point, layer) covering all `S` samples. **Twice per case**: once normally,
  once with eventsim's `--weight-only` flag over the same already-written
  `tc.csv`, which yields the weight-only makespan row 1 needs
  (`docs/q11_row1.md`, adopted; T72 adds the flag).
- **Output:** `outputs/s4/{arch}_{side}_x{m}_{layer}.csv`, one row per sample
  carrying `total_cycles`, `count_cycles`, `dram_cycles`,
  `dram_bytes_{weight,psum,vmem}` and `weight_makespan` from the ablation
  run.
- **Traces are not retained**: generated into `$TMPDIR`, `shutil.rmtree`d
  after S4 consumes them (`run_case.py:57-58, 116`). This figure needs no
  trace quota.
- **Gates:** `total_cycles >= count_cycles / nodes` per row, already asserted
  at `run_case.py:108`; and the dedup identity check of `plan.md` section 4
  step 5 - one skipped point per (arch, side) run for real and asserted to
  match its representative **exactly** on `total_cycles` and every
  `dram_bytes_*`. A mismatch is a stop, not a warning. **The step-5
  assertion covers both runs**, the full one and the ablation. Plus the two
  ablation gates of `docs/q11_row1.md`:
  `weight_makespan <= total_cycles` - which cannot fail on a correct
  implementation, so a pass is an implementation check and not evidence about
  the machine - and `weight_makespan >= count_cycles / nodes`.

### S3c + S4c - cache arm (Stokes Slurm array)
- **Input:** the **multi-node** S1 schedules; the capture's spike samples;
  `configs/cache_x{m}.json`.
- **Components:** `lays.weight_trace_gen gen --stream`
  (`src/lays/weight_trace_gen/cli.py:322-375`) piped into `cachesim_run` via
  `lays.cachesim run` (`src/lays/cachesim/cli.py:15-17, 22-24`). One stream is
  one sample (`cli.py:328-330`), so a task walks its `S` samples serially.
- **Output:** `outputs/s4c/{arch}_cache_x{m}_{layer}.csv`, one native-schema
  cachesim row per sample. `total_cycles` and `dram_bytes` are the two columns
  the figure reads; `tick_base_total`, `stretch_cycles`, the hit rates and the
  stall causes are kept as diagnostics.
- **Nothing is materialized**: the stream never becomes a file
  (`cli.py:298`).
- **Gates:** `total_cycles >= tick_base_total` for every row - a cache cannot
  make the weight path shorter than its no-stall baseline; and the binary's
  own stall-cause identity, which it throws on rather than reports
  (`src/lays/cachesim/native/src/instrument/stats.cpp:422-427`).

### S5 - aggregate (Delta)
- **Input:** S4 and S4c CSVs, `dedup_map.json`.
- **Component:** `zoo/eval_scaling/aggregate.py`, **rewritten** for the two
  metrics (row 1 is performance) and for the two arms' different column
  names.
- **Method:** re-expand deduped **scratchpad** rows from their
  representatives and **refuse to re-expand a cache row**, then per
  `plan.md` section 5 - sum over layers before forming any ratio, normalize
  to that panel's single-node 1x point, mean and 95 % CI over `S` samples.
  **Counted DRAM bytes, not the analytic CoSA product**: `aggregate.py:3-8`
  records that the analytic value "reconstructs total weight volume rather
  than measuring capacity-dependent refetch", which is exactly the failure
  mode a capacity sweep would walk into. **The traffic row is weight-only**
  (`plan.md` Q11, closed): `dram_bytes_weight` for the scratchpad arms
  against `dram_bytes` for the cache arm, so all three series are on one
  quantity.
- **Output:** `outputs/aggregate.csv` - (arch, series, multiplier) ->
  `perf_norm`, `perf_ci`, `traffic_norm`, `traffic_ci`, plus the unplotted
  diagnostics.

### S6 - plot (Delta)
- **Input:** `aggregate.csv`.
- **Component:** `zoo/eval_scaling/plot.py`, styled from `docs/scaling_mock.py`.
- **Output:** `outputs/eval_scaling.{pdf,png}` and `provenance.json`
  (input SHA256s, commit, dedup-map hash, case counts).
- **Gate:** user sign-off before anything is copied into the paper repo.

## Gates, in order

1. S0 equal-capacity assertion, scratchpad and cache - before S1.
2. S1 solve status and the Q6 feasibility list - before S1b.
3. S1b dedup report, flatness re-derivation, and the spatial-product check
   that the cache arm's geometry rests on - before S2.
4. S2 pilot measurement, **one per arm** - before either array.
5. S3/S4 dedup identity assertion, over both eventsim runs, plus the two
   ablation gates - before S5.
6. S4c `total_cycles >= tick_base_total` on every row - before S5.
7. Figure sign-off - before paper integration.

## Carried from `plan.md`, so this file is not read alone

- **The single-node series is expected exactly flat at 1.0** in both rows at
  this grid: the capacity constraint does not bind until about x0.28, below
  1x. That is the single-node half of the result, not a missing measurement,
  and `scaling_mock.py:26` currently draws it rising (`plan.md` Q10).
- **The cache series is a weight-path measurement from a different
  simulator** than the other two, so **row 1 compares weight-only makespans
  on all three series** (`plan.md` Q11, closed; `docs/q11_row1.md` is the
  finding and the spec). The scratchpad arms' weight-only makespan comes from
  a second eventsim run over the same `tc.csv` with psum and vmem durations
  zeroed, which is T72's work; until it lands, S5 cannot form row 1.
- **The 16-node cache geometry is undecided** until S1b prints the spatial
  product; if it is not the node count, the cache series needs work not
  scoped here (`plan.md` Q12).
- **The previous campaign's Stokes array is cancelled** by the user and is
  not a dependency, a cross-check or an input of any stage above.
