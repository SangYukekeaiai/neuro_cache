# Plan: 5-arch x 8-benchmark x 500-sample weight-trace campaign (Figure 3 scratchpad config)

**Status: approved 2026-11-10 ("go ahead to implement"). Decisions: Q2 = both
outputs; Q3 = fix gustavsnn streaming first; Q4 = estimate in section 10;
configs in `zoo/wt500_fig3cfg/` stand as generated (PTB T=64 unless the user
objects). Q5 (Stokes alias / node helper name) still open.**

Written 2026-11-10 against `~/projects/neuro_cache`, branch
`wcache-rebuild-phase-a` at `1932ba7` (clean tree). Session: `weight-trace-gen`.
This replaces the earlier draft that was mistakenly written against the stale
`~/neuro_cache_wcache` checkout (same repo, two commits behind, since removed).
Items I could not verify from DeltaAI are marked **[verify on stokes]**.

Naming note: commit `dd37b46` renamed the old hardware-N sweep to
`zoo/fig2_hw_n_sweep`. "Figure 3" now means `zoo/fig3_design_space`, the
multi-node scheduling design-space campaign, and that is the configuration this
plan uses.

## 1. Objective

Generate weight traces for **all 5 architectures** (loas, ptb, spinalflow,
prosperity, gustavsnn) against **all 8 captured benchmarks** (every valid
layer, **all 500 samples** each), using:

- the **campaign hardware config** `zoo/wt500_fig3cfg/arch.yaml`: the fig3
  multi-node LAYS hardware with user corrections (num_pes **exactly 4** per
  node, L1 weight **32 KB**, L2 weight **2 MB**; section 2.1), and
- the **campaign node-mapspace of each architecture**:
  `zoo/wt500_fig3cfg/mapspaces/*.yaml` (fig3 variants with loas/ptb T
  reverted to temporal; section 2.2).

Execution runs on the **Stokes cluster** (`/lustre/fs1/home/ya867177`), driven
from a compute node allocated via the cluster's node helper ("ncode/cnode",
exact name confirmed in stage S0) inside a **peon-code tmux session**, so work
survives a dropped SSH connection. Final traces are delivered back to
**DeltaAI** (`/work/nvme/bebv/yyu9/`) for storage.

**GustavSNN runs last**, per instruction (and because it is the only arch with
a known streaming bug, section 7).

## 2. Input configuration (complete)

### 2.1 Campaign scratchpad / hardware configuration (fig3-derived, corrected weight capacities)

**The campaign configs are written out for review at `zoo/wt500_fig3cfg/`**
(`arch.yaml` + `mapspaces/*.yaml` + README with full diffs); the fig3 files
themselves are not edited. Base: `zoo/fig3_design_space/arch.yaml`, one fixed
LAYS configuration, multi-node (`single_node: false`), with three
**user-directed changes**: `num_pes` per node is **exactly 4** (fig3 used 32),
L1 (per-node) weight is **32 KB = 32,768 B** (fig3 used 30,720), and L2
(global buffer) weight is **2 MB = 2,097,152 B** (fig3 used 1,966,080, 15/16
of 2 MB).

| Level | Instances | Contents |
|---|---|---|
| NodeLevel (L1) | **16 nodes** | `num_pes: 4`; local buffer **32,768 B weight** / 1,024 B psum / 1,024 B vmem |
| NoCLevel (L2, global buffer) | 1 | **2,097,152 B weight** / 65,536 B psum / 65,536 B vmem; inter-node fanout at most 16 |
| OffChip | 1 | DRAM, 0.25 cycles per 32-byte packet (64 GB/s at 500 MHz, read by nocsim only) |

Bitwidths: weight/psum/vmem = 8/16/32. Total PEs: 16 x 4 = 64. The buffer
capacities constrain the scheduler; the trace generator consumes whatever
schedule the solver returns. The PE change shrinks per-node fanout relative to
fig3, so nothing from `outputs/baselines.json` is reused: S2 re-solves
everything at the campaign sizes.

The `problem:` block in that file (KH=3, KW=3, CIN=512, COUT=512, HO=4, WO=4,
T=4, the ResNet-19 layer3_0_conv2 showcase layer) is **figure-3-specific and is
not reused**: this campaign replaces it with each benchmark layer's own
workload dims from its capture `meta.json`.

### 2.2 Node-mapspaces of the 5 architectures (`zoo/wt500_fig3cfg/mapspaces/`)

Derived from the fig3 variants with user-directed changes (2026-11-10): loas
and ptb drop their fig3 `T: {spatial: 4}` fanout (the 4 T-lanes no longer
exist at `num_pes: 4`); the other three keep their fig3 content.

```yaml
# loas.yaml: T spatial 4 -> full (now identical to the published examples/node_mapspace/loas.yaml)
node_dim_capacity: {KH: full, KW: full, CIN: full, T: full, COUT: {spatial: 4}}

# ptb.yaml: T spatial 4 -> T: 64, the published window. REVIEW FLAG: user
# recalled 32, but the previous config and PTBGen.h (TW_SIZE 8 x 8 columns)
# both say 64. All current captures have T <= 32, so either value admits
# every benchmark.
node_dim_capacity: {KH: 4, KW: 4, CIN: full, COUT: {spatial: 4}, T: 64}

# spinalflow.yaml: fig3 variant kept as-is
node_dim_capacity: {KH: 4, KW: 4, CIN: full, COUT: {spatial: 4}, T: full}

# prosperity.yaml: fig3 variant kept as-is (CIN resident at 16 instead of barred)
node_dim_capacity: {CIN: 16, COUT: {spatial: 4}, HO: 4, WO: 4, T: full}

# gustavsnn.yaml: fig3 variant kept as-is; T barred
node_dim_capacity: {KH: full, KW: full, CIN: full, COUT: {spatial: 2}, HO: {spatial: 2}, WO: 4}
```

Spatial-budget check against `num_pes: 4`: every mapspace's node spatial
product is exactly 4 (COUT 4 everywhere; gustavsnn COUT 2 x HO 2), so no idle
or over-subscribed lanes. Feasibility across all benchmark layers is
established in stage S2 (the fig3 `baselines.json` solves used the old
32-PE/T-lane hardware and are not reused).

### 2.3 Benchmarks (workloads): all mirrored on DeltaAI, n=500 each

| # | Bench | Trace directory | Layers in meta | Notes |
|---|---|---|---:|---|
| 1 | A02 | `A02/spikformer_4_384_cifar100_T4_n500` | 12 | CIFAR-100, T=4 |
| 2 | A04 | `A04/sdt_2_512_cifar100_T4_n500` | 16 | CIFAR-100, T=4 |
| 3 | A07 | `A07/spikinglm_t4_T4_n500` | 72 | spiking LM, ~20 GB capture |
| 4 | A08 | `A08/vgg16_cifar10_loas_T32_n500` | 13 | **T=32** |
| 5 | B09 | `B09/loas_vgg16_T4_n500` | 13 | T=4 |
| 6 | B09 | `B09/loas_resnet19_T4_n500` | 19 | 13 of 19 replayable (stride-2 excluded) |
| 7 | C01 | `C01/sma_azo_vgg_cifar10_dvs_T10_n500` | 6 | **T=10**, DVS |
| 8 | C01 | `C01/sma_azo_vgg_dvs128_gesture_T16_n500` | 6 | **T=16**, DVS |

DeltaAI root: `/work/nvme/bebv/yyu9/input_trace_delta/` (verified present, all
8 with `meta.json`, `n_samples: 500`).
Stokes root: `/lustre/fs1/home/ya867177/data/input_trace_delta/`; only
`B09/loas_resnet19_T4_n500` is confirmed there (used by fig2). **[verify on
stokes]** the other 7; missing ones are transferred in stage S1.

Per-benchmark valid-layer sets come from
`lays.weight_trace_gen.trace.valid_layer_names` (1x1/3x3 stride-1 convs plus
dense layers via `dense.py`); the exact lists are frozen into the campaign
manifest in stage S2. Sample set: **indices 0..499 (all 500)**, not the
100-of-500 subset fig2 used.

### 2.4 Tooling

- **Stage-1 schedules:** `python -m lays.scheduler solve` (Gurobi, conda env
  `gurobi`, exactly as `zoo/fig3_design_space/run_baselines.py` invokes it),
  once per `(arch mapspace, benchmark, valid layer)` with the fig3 arch YAML,
  writing a schedule cache. Gurobi license confirmed on DeltaAI
  (`~/gurobi.lic`); a Stokes license is unconfirmed, so **all schedules are
  solved on DeltaAI** (outputs are small JSON) and the cache is rsynced to
  Stokes.
- **Stage-2 generation:** `python -m lays.weight_trace_gen gen` per
  `(arch, trace_dir, layer)` with `--sample-start 0 --sample-count 500`,
  writing `sample_NNNNN.json.gz` step-cycles, plus `--stream` for the WCTS
  address stream. Measured cost on real data: 2-5 s per (arch, layer, sample).
- **Binaries:** `make -C src/lays/weight_trace_gen/<arch>` for each of the 5
  (only LoAS is in `make build`). cachesim/nocsim are not run by this campaign.
- **Slurm harness:** reuse the `zoo/fig2_hw_n_sweep/slurm/` array-harness
  pattern (`shard_cases.py` -> `run_array.sbatch` -> `rerun_missing.py` ->
  merge/coverage check), adapted to emit weight traces rather than nocsim
  cycles.

## 3. Deliverable format

**Open question Q2.** Two candidate outputs per `(arch, bench, layer, sample)`:

1. **Step-cycles** `sample_NNNNN.json.gz` (what nocsim consumes; small), and
2. **WCTS v2 address stream** (what cachesim consumes; the weight trace of
   actual addresses).

Recommendation: produce **both**; WCTS is the weight trace proper and the
step-cycles come nearly free from the same run. The old July-era
`~/sample_weight_trace_*.json` full-JSON format is superseded and not planned
unless you want it.

## 4. Sweep matrix and ordering

`arch x benchmark` = 5 x 8 = 40 combos; each combo runs its valid layers x 500
samples. Execution order:

1. **Wave 1:** loas, ptb, spinalflow.
2. **Wave 2:** prosperity.
3. **Wave 3 (last):** gustavsnn, per instruction, and because its `--stream`
   is broken today (section 7); by then the fix or the cycles-only fallback
   (Q3) is settled.

Rough scale: ~150 valid layers total x 500 samples x 5 archs ≈ 375k
layer-sample runs x 2-5 s ≈ **210-520 CPU-hours**; a few hours wall-clock as
Slurm arrays. The S3 pilot measures real per-bench cost and WCTS bytes before
the full launch; A07 (72 layers) and A08 (T=32) are expected to dominate.

## 4b. GustavSNN: architecture detail and the stream fix

This section records the corrected hardware model (user, 2026-11-10: "HO,
COUT parallel are inside one core, not deploy one HO to one core") and what
it means for trace generation. Source: `docs/weight_trace_gen_archs.md`
sections 2, 4 and 6, plus `gustavsnn/GustavGen.h`.

### What one GustavSNN tile is

GustavSNN is the only arch of the five whose tile holds **all resident input
channels at one timestep**: a tile spans full CIN, one T, a COUT block, and a
block of output pixels (HO rows x up to 4 WO positions). T is barred from the
node, so timesteps are DRAM-temporal; the campaign mapspace splits COUT
(spatial 2) and HO (spatial 2) across the node's 4 PEs and keeps KH/KW/CIN
fully resident.

### How a tile executes (the wave model)

1. **Line lists per HO row.** For each HO row of the tile, the generator
   builds the list of weight lines `(kh, kw, cin)` that any WO position in
   the row needs (a line is kept if any of the up-to-4 WO positions sees a
   spike there; WO is OR'd away, which is where GustavSNN saves fetches).
   Lines are ordered by kh, then kw, then cin.
2. **Waves of HO rows.** HO rows are grouped into waves. All rows of a wave
   advance in lockstep: on each tick, every still-active row fetches its next
   line; a short row simply stops early. A wave lasts as long as its longest
   row, and `mac_cycles = sum of wave lengths`.
   **Wave width (user requirement, 2026-11-10):** the maximum parallel rows
   per wave, i.e. the maximum bursts per tick, was hardcoded as
   `constexpr PE_COUNT_MAX = 8` (`GustavGen.h:35`, mirrored in the bridge).
   It must instead be a parameter derived from the schedule's NodeLevel
   spatial fanout (product of `spatial_split` factors; equals the arch's
   `num_pes`), with **campaign value 4** (COUT 2 x HO 2). The doc's section-4
   examples below were produced at width 8 and remain ground truth at that
   width; at width 4, example 2's nine rows regroup into waves
   {0-3}, {4-7}, {8}. Tracked in row T6.
3. **Consequence:** several fetches legitimately share one tick (one per
   active HO row), and nothing deduplicates across rows, so the cache sees
   repeated addresses at the same tick when two rows need the same line.

### The corrected core model

The parallel HO-row lanes and the COUT fanout are **internal to one core**:
one GustavSNN core contains all of a node's PEs (campaign shape: 2 COUT x
2 HO = 4), fed by one weight-fetch path that issues multiple line fetches in
the same cycle. A WCTS "core" therefore maps to the schedule's core, not to
an HO-row lane, and same-tick bursts from that core are the true hardware
behavior, not an artifact.

This invalidates the first fix attempted (T1, built and verified, then
withdrawn): promoting each HO-row lane to its own WCTS core id made the
stream *parse* under the v2 strictly-ascending-tick rule, but modeled the
node as N independent single-fetch cores, which misstates fetch concurrency
to the cache simulator (N fake ports instead of one port issuing N bursts
per cycle).

### The previous issue, with the failing example

Cycle-count generation always worked; the address stream never did. WCTS v2
requires ticks to be **strictly ascending within each core** of a tile
(enforced in `src/lays/cachesim/stream.py`, checked again by the C++ reader).
GustavSNN's wave execution issues one fetch per active HO row per tick, so
several bursts legitimately share a tick, and the stream merge flattened all
of them onto one core:

```
$ python -m lays.weight_trace_gen gen --arch gustavsnn ... --stream
ValueError: write_tile_frame: local_tick 0 not strictly ascending in core 0
            of tile 0 (previous 0)
exit code 1, 293 bytes already written to stdout
```

Concretely, on worked example 1 below (row ho=0 with 7 lines, row ho=1 with
10, one wave): both rows fetch at tick 0, `(1,0,1,0,8)` and `(0,0,1,0,8)`.
Flattened onto core 0 the stream's tick sequence is

```
core 0: tick 0, tick 0, tick 1, tick 1, tick 2, tick 2, ...
                ^^^^^^ second burst at tick 0 on the same core -> ValueError
```

so the writer dies on the very first tick pair, before tick 1 is written.
Every real layer trips this (layer_07 averages 3.3 bursts per cycle); it
failed on all single-node layers tried and on multinode layer_07, while the
other four archs stream fine because they never exceed one burst per tick
per core.

Fix history: first attempt (T1) promoted each HO-row lane to its own WCTS
core, which parses but misstates the hardware (see "The corrected core
model" above) and was withdrawn; the adopted fix follows.

### The adopted fix (T6)

Teach the format the truth instead of reshaping the truth to fit the format:

- **WCTS v3**: within a core, ticks become **non-decreasing** instead of
  strictly ascending; equal ticks mean concurrent bursts from that core's
  internal PEs. Version-gated: the relaxed rule applies to v3 streams only,
  and existing v2 streams remain valid.
- Symmetric change in the Python writer validation
  (`src/lays/cachesim/stream.py`) and the C++ reader
  (`cachesim/trace/stream_format.h`, the ascending-tick check).
- The gustavsnn bridge reverts to one WCTS core per schedule core; the
  per-lane core expansion is removed.
- The doc's section-4 worked examples stay the regression ground truth,
  re-asserted in v3 shape: example 1 streams as **one core** whose tick 0
  carries 2 bursts (both HO rows fetch), ticks 7-9 carry 1 (short row
  finished), `mac_cycles = 10`, all 17 addresses intact.

The other four archs are untouched: LoAS, PTB, SpinalFlow and Prosperity
fetch at most one burst per tick per core, so their v2-style streams are
already v3-conforming.

### Concrete generation-order examples

Verified outputs of the real `gustavgen` binary (from
`docs/weight_trace_gen_archs.md` section 4, re-verified during T1 review).
Addresses are `(kh, kw, cin, cout_start, cout_end)`: a burst covering that
kernel position and input channel for the whole COUT block. HO and WO never
appear in an address.

**Ordering rules, outermost to innermost:**

1. Across a layer: tiles execute in `dram_i` order per the schedule's DRAM
   loops, outer to inner. GustavSNN schedules iterate COUT blocks outer and
   T inner, so a 256-tile layer runs (cout-block 0, t0..t3),
   (cout-block 1, t0..t3), and so on.
2. Within a tile: HO rows are taken in order and grouped into waves of up to
   8; waves run back-to-back, each starting at the tick where the previous
   wave ended.
3. Within a wave: at tick `wave_start + j`, every row that still has a j-th
   line fetches it; rows are listed in row order within the tick.
4. Within a row: lines are fetched in (kh, kw, cin) lexicographic order.
5. No deduplication anywhere: two rows needing the same weight at the same
   tick emit the same address twice, and the cache sees both.

**Example 1: two HO rows, two input channels, one wave.**
Tile `HO=2, WO=2, CIN=2, COUT=[0,8)`, one timestep. Spikes, cin=0 (4x4 input,
3x3 kernel, pad 1; cin=1 spikes at (hin 0, win 0) and (hin 1, win 1)):

```
        win 0 1 2 3
  hin 0     0 0 1 0
  hin 1     0 1 1 0
  hin 2     1 1 0 0
  hin 3     0 0 0 0
```

A line `(kh, kw, cin)` is kept for row `ho` if any `wo` in {0,1} sees a spike
at `hin = ho+kh-1`, `win = wo+kw-1` (WO OR'd away). For row ho=0, line
`(1,0,1)`: kh=1 gives hin=0; wo=1 gives win=0; cin1 spikes at (0,0), so kept.

- Row ho=0: 7 lines: `(1,0,1) (1,1,1) (1,2,0) (2,1,0) (2,1,1) (2,2,0) (2,2,1)`
  (kh=0 skipped: hin=-1)
- Row ho=1: 10 lines: `(0,0,1) (0,1,1) (0,2,0) (1,1,0) (1,1,1) (1,2,0)
  (1,2,1) (2,0,0) (2,1,0) (2,2,0)`

Two rows form one wave, `wave_len = max(7,10) = 10`. Actual output,
17 fetches in 10 cycles:

```
tick 0: (1,0,1,0,8) (0,0,1,0,8)     tick 5: (2,2,0,0,8) (1,2,0,0,8)
tick 1: (1,1,1,0,8) (0,1,1,0,8)     tick 6: (2,2,1,0,8) (1,2,1,0,8)
tick 2: (1,2,0,0,8) (0,2,0,0,8)     tick 7: (2,0,0,0,8)   row 0 done,
tick 3: (2,1,0,0,8) (1,1,0,0,8)     tick 8: (2,1,0,0,8)   row 1 alone
tick 4: (2,1,1,0,8) (1,1,1,0,8)     tick 9: (2,2,0,0,8)
```

In WCTS v3 terms this is one core with tick sequence 0,0,1,1,...,6,6,7,8,9:
non-decreasing, equal ticks = the two HO lanes fetching concurrently.
`mac_cycles = 10` while fetches = 17; the two differ, unlike every other arch.

**Example 2: nine HO rows, two waves, a same-tick duplicate.**
Rows 0-8 where row 0 has 2 lines, row 3 has 1, row 8 has 3, the rest none
(1x3 kernel tile). Waves: rows 0-7 (`wave_len 2`, ticks 0-1), then row 8
(`wave_len 3`, ticks 2-4). Output, 5 cycles, 6 fetches:

```
tick 0: (0,0,0,0,8) (0,0,0,0,8)   rows 0 and 3 fetch the SAME weight; both emitted
tick 1: (0,1,0,0,8)               row 0's second line
tick 2: (0,0,0,0,8)               wave 2 begins: row 8
tick 3: (0,1,0,0,8)
tick 4: (0,2,0,0,8)
```

This pins the two subtleties the regression tests guard: the duplicate
address inside tick 0, and wave 2 starting at tick 2, not 0.

**Real-layer flavor.** `layer_07_features_24` tile 0 opens exactly like a
scaled-up example 1, duplicates included:

```
tick 0: (1,0,0,0,8) (0,0,0,0,8) (0,0,1,0,8) (0,0,3,0,8)
tick 2: (1,0,7,0,8) (0,0,7,0,8) (0,0,6,0,8) (0,0,6,0,8)
```

Whole-layer scale: 256 tiles, 672,768 bursts in 204,992 mac cycles, about
3.3 bursts per cycle on average: precisely the property that breaks WCTS
v2's one-fetch-per-tick-per-core rule and motivates v3. Under the campaign
mapspace each core has 2 HO lanes (x2 COUT internal), so a core issues at
most 2 bursts per tick instead of the up-to-8 in these examples; the
mechanism is identical.

## 5. Workflow (stages, each a reviewable unit)

- **S0: Stokes preflight.** SSH to Stokes; locate the node-allocation helper
  the user remembers as "ncode/cnode" (`which ncode cnode`, `ls ~/local/bin`,
  cluster docs); allocate a compute node; start a **peon-code tmux session on
  that node** so the campaign survives disconnects. Note from the fig2
  campaign: Stokes has no usable systemd user bus, so long jobs use `setsid`
  alone. Pull `neuro_cache` to `1932ba7`+ on Stokes; build the 5 generator
  binaries; record the venv (`~/.venvs/neuro_cache_wcache/bin/python` per
  fig2 provenance, name to re-confirm).
- **S1: Input placement.** Check all 8 trace dirs on Stokes; rsync missing
  ones from DeltaAI (`/work/nvme/bebv/yyu9/input_trace_delta/`). A07 alone is
  ~20 GB; sizes and lustre quota are checked before transfer.
- **S2: Schedules (on DeltaAI, Gurobi).** New campaign dir `zoo/wt500_fig3cfg/`
  with a `gen_inputs.py` that: builds each benchmark layer's workload from its
  `meta.json`, runs `lays.scheduler solve` with the campaign arch YAML
  (`zoo/wt500_fig3cfg/arch.yaml`) + the arch's campaign mapspace
  (`zoo/wt500_fig3cfg/mapspaces/`), and freezes the campaign manifest (valid-layer
  lists, infeasible/excluded pairs recorded explicitly, sample set 0..499,
  schedule hashes). Then a **bridge-compatibility gate** (see risk 1) before
  rsyncing the cache to Stokes.
- **S3: Pilot on Stokes.** 1 sample x 1 layer x all 40 combos through both
  outputs (gustavsnn cycles-only unless Q3 says fix first). Confirms
  schedule-to-bridge compatibility per arch, exercises `dense.py` on the
  transformer benches (A02/A04/A07), and measures runtime and bytes to size
  the arrays and the S6 transfer.
- **S4: Full generation, waves 1-2.** Slurm arrays (manifest -> shards ->
  `rerun_missing.py` until complete -> coverage check that every
  (combo, layer, sample) exists exactly once).
- **S5: Wave 3, gustavsnn.** Same harness, last; stream behavior per Q3.
- **S6: Delivery to DeltaAI.** rsync from Stokes to
  `/work/nvme/bebv/yyu9/weight_traces/wt500_fig3cfg/<arch>/<trace_dir>/<layer>/`
  (**Q4**: confirm destination), with a sha256 manifest generated on Stokes
  and re-verified on DeltaAI, plus a final coverage report.

## 6. Where things run

| What | Where | Why |
|---|---|---|
| Schedule solve (S2) | DeltaAI, conda env `gurobi` | Gurobi license confirmed here; outputs are small |
| Trace generation (S3-S5) | Stokes compute nodes, Slurm arrays, launched from a peon-code tmux session on an allocated node | per instruction; arrays + `rerun_missing` make it restartable even if the session dies |
| Storage of final traces (S6) | DeltaAI `/work/nvme/bebv/yyu9/` | per instruction |

## 7. Known risks

1. **Campaign mapspaces vs. trace-generator bridge assumptions.** The native
   bridges hard-code tile shapes (`docs/weight_trace_gen_archs.md` sections 5
   and 8). With the 2026-11-10 mapspace corrections, loas and ptb are back to
   all-T-temporal and match their bridges; the remaining mismatch is
   **prosperity**: its bridge reads **one CIN per tile**, while the campaign
   mapspace keeps fig3's CIN residency of up to 16. GustavSNN (T barred, full
   CIN) matches its bridge.
   Schedules that violate a bridge's assumptions are **silently misread**, so
   S2 ends with an explicit gate that checks every solved schedule against the
   bridge contracts; violations mean either a mapspace-conformant re-solve or
   a bridge extension task before generation starts. This is the largest
   unknown in the plan and is resolved before any 500-sample run.
2. **GustavSNN `--stream` crashes** (`write_tile_frame: local_tick not
   strictly ascending`): its parallel intra-core fetches collide with the v2
   strictly-ascending-tick rule. Decision history: Q3 = fix first; a
   per-HO-row-core fix was built and verified, then withdrawn on the user's
   architecture correction (HO/COUT parallelism is intra-core); the adopted
   fix is WCTS v3 same-tick bursts, detailed in section 4b (row T6). Running
   gustavsnn last keeps this off the critical path.
3. **Multi-node schedules** (16 nodes, NoC fanout up to 16) produce many more
   tiles per layer than the single-node fig2 runs the 2-5 s/sample timing came
   from; the S3 pilot re-measures cost before committing the arrays.
4. **Dense/transformer layers** (A02/A04/A07) are the least-exercised
   generator path; the S3 pilot gates the full run.
5. **Solver infeasibility** for some (arch, layer) pairs at the fig3 buffer
   sizes is possible; S2 records exclusions explicitly rather than silently
   skipping.
6. **Stokes disk**: input mirrors (tens of GB) plus WCTS outputs (unknown
   until S3) must fit the `/lustre/fs1` quota; checked in S1/S3.

## 8. Open questions (answer these on review)

- **Q1** Review the generated configs in `zoo/wt500_fig3cfg/` (hardware:
  16 nodes x 4 PEs, L1 weight 32 KB, L2 weight 2 MB, psum/vmem unchanged; the
  five mapspaces), including the **PTB T=64-vs-32 flag** in
  `mapspaces/ptb.yaml`.
- **Q2** Deliverables: step-cycles `.json.gz` + WCTS streams (recommended), or
  only one of the two?
- **Q3** GustavSNN streaming: fix the core-id bug first, or cycles-only now?
- **Q4** DeltaAI destination `/work/nvme/bebv/yyu9/weight_traces/` OK?
- **Q5** Stokes access: your SSH alias/hostname for Stokes, and the real name
  of the node helper ("ncode"/"cnode"?). S0 will discover it, but a name saves
  time.

## 10. Capacity estimate (Q4)

WCTS v2 cost: 28 B per fetch burst (`<q5i`: i64 tick + 5 x i32 address), plus
~24 B per tile frame and 8 B per core frame. Calibrating with the measured
single-node vgg16 burst counts (`docs/weight_trace_gen_archs.md` sections 5
and 8: LoAS ~280k bursts/layer, PTB same, SpinalFlow ~80k, Prosperity ~40k,
GustavSNN ~600k), a vgg16-class benchmark at 500 samples costs roughly
200-250 GB uncompressed across all 5 archs, GustavSNN dominating (~120 GB of
it). Scaling over the 8 benchmarks (A07: 72 layers, A08: T=32 inflating
SpinalFlow ~8x, C01: only 6 layers): **~1-3 TB uncompressed WCTS**, i.e.
**~300-800 GB gzipped** (addresses compress well; 3-5x assumed). Step-cycles
`.json.gz` add ~10-40 GB over ~375k files.

Destination capacity: DeltaAI `/work` has 1.4 TB free of 2.0 TB (shared;
user currently at 174 GB with no hard quota, no inode limit). Decision:
**store WCTS gzipped**; the S3 pilot re-measures real bytes per sample under
the campaign schedules (the calibration numbers came from different, 128-PE
single-node schedules) before S4 commits, and if the measured total threatens
the shared headroom, we raise it with the user before generating.

First measured data point (T3 review, 2026-11-10): one real gustavsnn layer
sample = **18.8 MB** on disk, consistent with the ~120 GB-per-CNN-benchmark
estimate for gustavsnn above. Same review flagged that the harness's printed
`--time=90:00` assumes ~2.7 s/sample for a 2000-case shard (a gustavsnn shard
writes ~37 GB in that window); the S3 pilot must confirm the real rate before
the full array submits, or shards time out together.

Memory note (T4 decision, 2026-11-10): prosperity's CIN>1 support enumerates
one native one-CIN invocation per resident channel (byte-identical output,
verified). At A07 scale (1.18M-tile layers, 72 of them) this extrapolates to
~12.4 GB transient RSS and a ~0.9 GB task.bin per bridge call. Accepted as-is
because prosperity runs in wave 2; if the S3 pilot shows A07 x prosperity
breaking node memory or time budgets, the C++ record widening
(cin_off/cin_n) becomes a targeted follow-up before wave 2.

## 9b. Task split (board preview; superseded by the live board at dispatch)

| id | owner | task |
|---|---|---|
| T1 | impl | S2 scaffolding: `zoo/wt500_fig3cfg/gen_inputs.py`, workload build from meta.json, solve loop (DeltaAI) |
| T2 | impl | Schedule solve runs + bridge-compatibility gate + rsync cache to Stokes |
| T3 | impl | Bridge extension if the gate demands it (prosperity CIN>1), with regression vs the hand-traced examples |
| T4 | impl | Slurm harness adaptation (shard/array/rerun/coverage for weight-trace outputs) |
| T5 | boss-coordinated on Stokes | S0/S1 preflight, node + peon-code session, input rsync |
| T6 | impl | S3 pilot, 40 combos, size/time report |
| T7 | impl | S4 waves 1-2 full run |
| T8 | impl | (if Q3=fix) gustavsnn WCTS core-id fix + regression |
| T9 | impl | S5 gustavsnn full run |
| T10 | impl | S6 delivery + checksum verification to DeltaAI |
| T11 | archie | Review gates after T2, T6, and before T10 sign-off |
| T12 | scribe | Campaign README + provenance (fig3-style) after traces pass review |
