# 2026-08-02 Multi-Node, Core-Driven Weight-Trace Format Plan

> Status: DRAFT, approved for implementation 2026-08-02. This is **Stage 1**
> of the 2-level hierarchical cache design (weight-trace generation, based
> on schedule + arch model). **Stage 2** (L1/L2 cache replacement-policy
> design) is explicitly out of scope for this plan and will be planned
> separately once Stage 1 lands.

## Context

The existing weight-trace pipeline (`solve_schedules.py` -> `generate_weight_traces.py`,
refactored 2026-07-30) only ever reconstructs real weight-address traces for
`single_node` architectures. `nocsim/combine.py:181-188` confirms the real-trace
per-tile reconstruction path (`iter_node_tiles`, `ArchComputeModel.weight_addresses`/
`weight_ticks`) is gated on `arch.single_node`; for multi-node configs it falls
back to one static, schedule-derived cycle count for the whole run and never
touches the real trace. So multi-node weight-address generation does not exist
anywhere in the repo today -- this plan builds it.

A 2-level cache design (L1 private per core, L2 shared) only makes structural
sense on a multi-node/NoC architecture -- a `single_node` schedule has nowhere
for a second cache level to sit. This plan's scope is therefore centered on the
multi-node configs (`configs/arch/*_multinode.yaml`); single-node is the
degenerate case of the same format (one core, `noc_i` always 0), not a
separate code path.

## Scope (flagged for sign-off, matching this repo's own convention of
explicitly flagging judgment calls -- see 2026-07-30's buffer-size sizing)

- Architectures: all 5 multi-node fixtures (`loas`, `ptb`, `gustavsnn`,
  `prosperity`, `spinalflow`), reusing the existing `*_multinode.yaml` +
  `configs/dataflow/<arch>.yaml` pairs and, where already cached, the solved
  schedules under `outputs/schedules/multinode/`.
- Workloads: both `vgg16_T4_all` and `resnet19_T4_all`, all valid layers.
- Samples: the canonical 100-sample subset (`tracegen.sample_indices`,
  seed 0), matching every other generation run in this pipeline.
- **No migration of the existing 25 GB single-node corpus** (12,400 files,
  `outputs/weight_traces/`) -- explicit user decision, 2026-08-02. Every
  trace (single-node and multi-node) is regenerated fresh in the new format
  described below; the old flat-format corpus is not reshaped or reused.

## Format design

### Nesting and terminology

```
Tile id (dram_i, noc_i)
  Time step j                     -- per-tile-local tick, resets to 0 per tile
    core k                        -- a NodeLevel instance (private-L1 unit)
      weight event [kh, kw, cin, cout_start, cout_end]
```

- `dram_i` / `noc_i`: DRAM-level and NoC-level positions in the schedule's
  loop nest (`combine.py`'s existing two-axis loop). Together they identify
  one tile. For single-node, `noc_i` is always 0 (`NoCLevel` is empty).
- `j` ("time step"): the existing per-tile-local tick concept
  (`ArchComputeModel.weight_ticks()`'s docstring: "0-based, restarting at 0
  for every tile"), now promoted to an explicit nesting level instead of a
  parallel `tick_ids` array.
- `core`: one NodeLevel instance -- the private-L1 granularity. Not a PE
  (PE-level parallelism within a core stays absorbed inside that core's own
  burst/cycle accounting, exactly as it already is for single-node).
- Weight events keep today's raw bursted-event shape,
  `[kh, kw, cin, cout_start, cout_end]` -- not fully-expanded individual
  elements (`layout.h`'s existing streaming design exists specifically to
  avoid materializing ~15M elements/sample; this format must not reintroduce
  that).

### On-disk shape

```json
{
  "arch": "loas", "trace_dir": "resnet19_T4_all", "layer_name": "...",
  "sample_idx": 18, "workload_dims": {...},
  "dram_num_steps": 64, "noc_num_steps": 1,
  "tiles": [
    {"dram_i": 2, "noc_i": 0, "mac_cycles": 4, "lif_cycles": null,
     "ticks": [
       {"tick": 0, "cores": [{"core_id": 0, "weight_addresses": [[1,1,0,0,4]]},
                              {"core_id": 1, "weight_addresses": [[1,1,0,4,8]]}]},
       {"tick": 1, "cores": [{"core_id": 0, "weight_addresses": [[1,1,1,0,4],[1,1,1,4,8]]}]},
       {"tick": 2, "cores": [{"core_id": 1, "weight_addresses": [[1,1,2,4,8]]}]},
       {"tick": 3, "cores": [{"core_id": 0, "weight_addresses": [[1,1,2,0,4]]}]}
     ]}
  ]
}
```

Canonical on-disk order: `dram_i -> noc_i -> j -> core` (core fastest-varying).
A core absent from a given tick's `cores` list means it had no fetch that
cycle (e.g. it finished its local work for the tile earlier under the
lock-step assumption below) -- it is omitted, never padded with an empty entry.

### Named modeling assumptions

- **Lock-step concurrency**: every core in a tile is assumed to advance
  through the same `(dram_i, noc_i, j)` sequence in lock-step. This is an
  explicit simplification, matching how `combine.py` already treats NoC
  steps (one shared `noc_i` counter for every spatial partition). It does
  **not** capture `eventsim`'s contention-based timing skew -- that remains
  a separate, unmodeled refinement.
- `mac_cycles` (tile-level) = `max` over cores' own local cycle counts,
  consistent with lock-step (the tile can't finish before its slowest core).
- `lif_cycles` = `null` placeholder for multi-node tiles (unknown at this
  stage), reusing the existing `ComputeCycles(mac_cycles, lif_cycles=None)`
  convention already used for archs with no MAC/LIF split.
- Total trace volume is **not** N times single-node's: the workload's total
  weight-element touches are fixed; spatial splitting across cores
  repartitions that fixed total rather than multiplying it.

### Explicitly out of scope / unaffected

`nocsim`/`combine.py`'s existing latency machinery (weight broadcast,
psum-chain, vmem-chain, `schedule.data_size`-based transaction sizing,
`NoC` hop-counting, `eventsim`) is untouched. It is a separate system
modeling different variables (psum/vmem accumulator movement, not weight
cache traffic) and stays on schedule-derived sizing. Any question of how an
L1 miss should translate into NoC transaction cost is deferred to a later
stage, not addressed here.

## Cross-checks performed against real data (2026-08-02)

Inspected a real solved multi-node schedule,
`outputs/schedules/multinode/loas/resnet19_T4_all/layer_01_layer1_0_conv1.json`
(`has_solution: True`):

```
workload: COUT=128, HO=32, WO=32, KH=KW=3, CIN=64, T=4
NoCLevel.spatial_splitting.loops: COUT=8, HO=8, WO=2
DRAM.temporal_permutation.loops:  WO=8, HO=2, WO=2, HO=2
```

- `8 (COUT) x 8 (HO) x 2 (WO) = 128`, exactly `loas_multinode.yaml`'s
  `NodeLevel.instances: 128` -- self-consistent.
- Confirms `schedule.spatial_factors` (from `decode()`) is **purely
  inter-core** fanout, read straight from `NoCLevel.spatial_splitting.loops`.
  It does not conflate with the dataflow's own intra-core PE cap
  (`configs/dataflow/loas.yaml`'s `COUT: {spatial: 4}`), which composes
  multiplicatively on top (8-way inter-core x 4-way intra-core PE = 32-way
  total COUT parallelism), matching how single-node's `node_bound[COUT]`
  already treats a full PE-spatial burst as one node-level range.
- Confirms a "core" is generally a **multi-dimensional coordinate**
  (here: `cout_idx x ho_idx x wo_idx`), not addressable by a single
  dimension's index -- the toy 2-core/1-dim examples used earlier in
  planning undersold this; the real case needs the encoding below.

## `core_id` encoding

Mixed-radix, inner -> outer: **T, WO, HO, CIN, KW, KH, COUT**. This order is
deliberate, not arbitrary -- it matches `combine.py`'s existing Way-2 NoC
layout exactly (`X = sf[T]*sf[WO]*sf[HO]`, `Y = sf[CIN]*sf[KW]*sf[KH]*sf[COUT]`),
so `core_id` decomposes directly into `NoC.get_xy`'s `pe_id = x + y*X` scheme
with no separate translation layer needed if a later stage wants NoC-hop
consistency.

```python
_CORE_ID_ORDER = [DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT]

def encode_core_id(idx: Dict[int, int], spatial_factors: Dict[int, int]) -> int:
    core_id, running_base = 0, 1
    for d in _CORE_ID_ORDER:
        core_id += idx.get(d, 0) * running_base
        running_base *= spatial_factors.get(d, 1)
    return core_id

def decode_core_id(core_id: int, spatial_factors: Dict[int, int]) -> Dict[int, int]:
    idx, rem = {}, core_id
    for d in _CORE_ID_ORDER:
        radix = spatial_factors.get(d, 1)
        idx[d], rem = rem % radix, rem // radix
    return idx
```

A dim absent from `spatial_factors` (radix 1) contributes nothing and its
index is always 0 -- no special-casing for schedules that don't spatially
split every dim. Verified against the real loas schedule above:
`decode_core_id(57, {COUT:8, HO:8, WO:2})` -> `wo_idx=1, ho_idx=4, cout_idx=3`
(all other dims 0).

## Implementation plan (file by file)

**`src/archmodels/__init__.py`** -- extend `NodeTileSpec` with `noc_i: int`
and `core_id: int` (default 0 for existing single-node call sites, fully
backward compatible).

**`src/nocsim/schedule/tiles.py`** -- generalize `iter_node_tiles`:
- Enumerate `(dram_i, noc_i, core_id)` instead of just `dram_i`. Degenerates
  exactly to today's behavior for single-node (`noc_i=0, core_id=0`).
- `node_bound[dim]`/`tile_offset[dim]` additionally divided/offset by that
  core's slice of `spatial_factors[dim]`, using `decode_core_id` above.
  `tile_offset[dim]` for a spatially-split dim needs **additive
  composition**: `(that core's spatial slice start) + (this tile's own
  DRAM/NoC-temporal offset within the slice)` -- single-node never needed
  this since it never has a spatial slice offset to add.
- Fix: `is_last_K` must use the **combined** `si.k_position(dram_i, noc_i)`
  (already used by `combine.py`) instead of the current DRAM-only
  `si.dram_k_position(dram_i)`, which is only correct because single-node's
  NoC level is empty (DRAM-only and combined coincide there by construction).
  Multi-node breaks that coincidence whenever K is a NoC-temporal dim.

**`src/tracegen.py`**:
- New dataclasses: `CoreEntry {core_id, weight_addresses}`,
  `TickEntry {tick, cores: List[CoreEntry]}`.
- `TileWeightTrace` gains `noc_i`; its flat `weight_addresses`/`tick_ids`
  pair is replaced by `ticks: List[TickEntry]`.
- `LayerWeightTrace` gains `noc_num_steps`.
- New `merge_cores_by_tick()`: merges N cores' own already-tick-grouped
  results (see native-bridge change below) into one tile's `ticks` list.
  This is the one piece that structurally cannot move into native code --
  no single per-core native-bridge call has visibility into other cores'
  results, so the cross-core merge is inherently Python's job.
- `reconstruct_samples()`: calls the native bridge once per core (per
  `(dram_i, noc_i)` tile) instead of once per tile, feeds results through
  `merge_cores_by_tick`.

**Per-arch native bridges** (`src/archmodels/{loas,ptb,gustavsnn,prosperity,spinalflow}/`):
- `native_bridge.py`'s `_pack_task`, `task.bin`'s wire format, `TileSpec`
  structs, and each arch's `<Arch>Gen.h` reconstruction math need **no
  change** -- confirmed by reading all 5: they already consume arbitrary
  per-tile offsets/bounds for every dim generically (e.g. `LoASGen.h`'s
  `cout_off`/`cout_n` are already free parameters, never hardcoded).
  Correctness is entirely owned by `iter_node_tiles`-multinode computing the
  right values; the native side just consumes whatever it's given, as today.
- The one real per-arch change is `main.cpp`'s output-writing loop: emit
  each core's own within-core tick grouping directly (a small shared C++
  helper across all 5 bridges, not duplicated 5x) instead of the current
  flat parallel `(weight_addresses, tick_ids)` arrays. Checked each arch's
  tick assignment:

  | Arch | Tick assignment | Same-tick ties? |
  |---|---|---|
  | loas | `tick = mac_cycles++` | No -- sequential |
  | ptb | `tick = i` | No -- sequential |
  | prosperity | `tick = mac_cycles++` | No -- sequential |
  | spinalflow | `tick = mac_cycles++` | No -- sequential |
  | gustavsnn | `tick = wave_start_of[i] + j` | **Yes** -- real same-cycle parallelism |

  For 4 of 5 archs this change is nearly a no-op (each address is already
  its own singleton tick group). GustavSNN is the one arch needing real
  bucketing logic in the output loop.

**Explicitly not touched**: `src/cachesim/` (its `_write_events` flattening
reads the old flat schema and only needs updating once Stage 2 actually
consumes the new format); `nocsim/combine.py` and everything under
`nocsim/transactions/`/`nocsim/core/` (separate system, see "out of scope"
above).

**New script**: one demo/generation driver under `scripts/tmp/` (this
repo's existing rule: multi-node runner scripts never live in `src/`,
`debug/`, `profiling/`, `log/`, or the repo root).

## Hand-made tests

Tiny hand-checkable multi-node fixture (small dims, 2-4 cores), extending
the existing `debug/schedules/loas/tiny/` / `debug/weight_traces/loas/tiny/`
convention:

1. **Tile derivation**: hand-compute expected `node_bound`/`tile_offset` per
   `(dram_i, noc_i, core_id)` on the tiny fixture; assert `iter_node_tiles`
   matches exactly.
2. **`merge_cores_by_tick`**: concrete synthetic input/output (worked in
   planning discussion, real event tuples not letters), asserting exact
   nested output, zero events created or dropped
   (`n_in == n_out`), and that a core absent from a tick is omitted, not
   padded with an empty entry.
3. **Single-node losslessness**: run the *existing* `loas`/`tiny` fixture
   through the new code path and diff its reshaped output against today's
   `debug/weight_traces/loas/tiny/layer_00/sample_00000.json.gz` -- direct
   test of "pure reshape, zero information loss for the single-node case."
4. **`is_last_K` combined-position fix**: a tiny schedule where K is
   deliberately a NoC-temporal dim, confirming `si.k_position(dram_i, noc_i)`
   is used and the DRAM-only version would give the wrong answer.
5. **`mac_cycles = max(cores)`**: hand-computed per-core local cycle counts
   on the tiny fixture, checking the stored tile-level value is the max.
6. **`core_id` encode/decode round-trip**: for the real loas
   `spatial_factors = {COUT:8, HO:8, WO:2}`, verify
   `encode_core_id(decode_core_id(c, sf), sf) == c` for a range of `c`, and
   that `decode_core_id(57, sf)` matches the worked example
   (`wo_idx=1, ho_idx=4, cout_idx=3`).

## Demo run

```bash
python scripts/tmp/generate_multinode_weight_trace_demo.py \
  --arch loas \
  --arch-yaml configs/arch/loas_multinode.yaml \
  --dataflow-yaml configs/dataflow/loas.yaml \
  --trace-dir resnet19_T4_all \
  --layer layer_01_layer1_0_conv1 \
  --sample-start 0 --sample-count 5 \
  --out-dir scripts/tmp/outputs/weight_traces_demo
```

- Reuses the already-cached schedule at
  `outputs/schedules/multinode/loas/resnet19_T4_all/layer_01_layer1_0_conv1.json`
  if present (confirmed to exist and solved, 2026-08-02) -- no fresh Gurobi
  solve needed for this demo.
- Output goes to `scripts/tmp/outputs/`, never `outputs/weight_traces/` (the
  real corpus location), matching this repo's existing verification-run
  convention (2026-07-30 plan's A.4).
- After running: print one sample's JSON to confirm the nesting matches this
  spec, then delete the scratch output unless kept deliberately for Stage 2
  hookup testing.

## Milestones

1. Shared pieces: `NodeTileSpec` extension, `core_id` encode/decode,
   `iter_node_tiles`-multinode, `merge_cores_by_tick`, hand-made tests 1/2/6
   above (no native code touched yet -- pure Python, testable in isolation).
2. Walking skeleton on one arch (loas): native `main.cpp` output-loop change
   (trivial case, per the table above), tiny-fixture tests 3/4/5, then the
   demo run above.
3. Extend the `main.cpp` output-loop change to `ptb`/`prosperity`/`spinalflow`
   (same trivial case as loas) and `gustavsnn` (real bucketing logic, needs
   its own dedicated check given the same-tick-tie case).
4. Full regeneration: all 5 archs x both workloads x all layers x canonical
   100 samples, in the new format, into `outputs/weight_traces/` (or a
   clearly-named successor directory, TBD at implementation time).

## Open items carried into Stage 2 (not resolved here)

- Where the new `outputs/weight_traces/` (or successor) directory sits
  relative to the still-live old single-node corpus, given no migration.
- Everything about L1/L2 cache policy itself, and any question of costing
  L1-miss-driven NoC transaction latency (explicitly deferred, see "out of
  scope" above).