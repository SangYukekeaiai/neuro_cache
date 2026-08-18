# 2026-08-05 Weight Cache Simulator Redesign Plan (from scratch)

> Status: DRAFT, awaiting review. Nothing implemented. This plan is a full
> survey and design; implementation is a separate, later plan.
>
> Ground rules set by the user for this phase:
> 1. The existing `src/cachesim/` engine is out of scope as a starting
>    point. Every cache mechanism below is specified from scratch.
> 2. The simulator's front end is Python; its back end is C++.
> 3. The design must plug into the current pipeline without modifying it.

This plan follows `log/2026-08-04-gem5-l2-cache-survey-plan.md` (survey
executed 2026-08-04, note filed in the vault) and consumes the weight
trace format defined by `log/2026-08-02-multinode-core-driven-weight-trace-plan.md`
(Stage 1, implemented).

---

## Part 0. Summary of the four findings that drive the design

1. The weight trace format is structurally correct and matches how
   accelerator simulators represent per-cycle memory traffic. It should
   gain six scalar header fields plus one per-tile field, all additive,
   so the existing 7.7 GB corpus stays readable.
2. In a read-only weight cache, an MSHR reduces to a line tag, an issue
   time, and one ordered target list. Two of gem5's three block causes
   survive; the write-buffer cause and the deferred-target list are
   structurally absent.
3. Concurrency pressure is entirely a function of the spatial fanout.
   Measured on real `loas` traces: 16 cores demand exactly 16 distinct
   lines per tick, and 1024 cores demand a mean of 627 and a maximum of
   1024. MSHR bounds should be a swept structural parameter over the
   range 16 to 1024.
4. The Python front end should never parse a trace body. Measured on one
   real sample: gzip decompression takes 0.86 s and Python JSON parsing
   takes 20.8 s for the same file. Trace reading belongs entirely in C++.

---

## Part 1. Weight trace format review

### 1.1 The format as it stands

Defined in `src/tracegen.py:149-221`, written by `save_weight_trace`
(`src/tracegen.py:326`) as gzip-compressed JSON.

```
LayerWeightTrace
  arch, trace_dir, layer_name, sample_idx
  workload_dims {KH, KW, CIN, COUT, HO, WO, T, shape}
  dram_num_steps, noc_num_steps
  tiles[]
    TileWeightTrace  {dram_i, noc_i, mac_cycles, lif_cycles, ticks[]}
      TickEntry      {tick, cores[]}
        CoreEntry    {core_id, weight_addresses[]}
          event      [kh, kw, cin, cout_start, cout_end]
```

Canonical on-disk order is `dram_i -> noc_i -> tick -> core`, with core
fastest-varying. `tick` is tile-local and restarts at 0 for every tile.
A core with no fetch in a tick is omitted from that tick's `cores` list.

### 1.2 Measured properties of the real corpus

Read directly from
`/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/loas/`, which
holds 620 sample files across 4 arch configs and 2 workloads, 7.7 GB
compressed. Sample measured:
`resnet19_T4_all / layer_19_layer3_1_conv2 / sample_00002`,
`workload_dims = {KH:3, KW:3, CIN:512, COUT:512, HO:4, WO:4, T:4}`.

| Property | `inst16_node32kb_noc512kb` | `inst1024_node32kb_noc4096kb` |
|---|---|---|
| Tiles | 128 | 2 |
| Total ticks | 316,280 | 7,158 |
| Distinct `core_id` | 16 | 1024 |
| Total weight events | 5,060,480 | 5,060,480 |
| Events per core per tick | exactly 1 | exactly 1 |
| Burst width (`cout_end - cout_start`) | exactly 4 | exactly 4 |
| Distinct `(kh, kw)` | 9 | 9 |
| Max `cin` observed | 511 | 511 |
| `noc_i` values present | {0} | {0} |
| Cores active per tick | exactly 16 | 1024 in 44% of ticks, 256 in 31% |

Structural invariants confirmed on all 128 tiles of the 16-core file:
`ticks` is dense `0 .. mac_cycles-1`, and `len(ticks) == mac_cycles`.

Ingest cost for that single file (15.54 MB gzipped, 315.8 MB expanded):
gzip decompression 0.86 s, `json.loads` 20.84 s. Extrapolated across the
620-file corpus, Python-side JSON parsing alone costs roughly 3.6 hours
before any cache work happens.

### 1.3 Comparison against established trace formats

Surveyed to answer whether the format needs a structural change.

| Simulator | Record shape | Time axis | Address form |
|---|---|---|---|
| ChampSim | one record per access: hex address plus `R`/`W` | implicit program order | flat byte address |
| Ramulator / Ramulator 2.0 | address plus type, with a count of non-memory instructions between consecutive accesses | inter-arrival gap | flat byte address, mapped to DRAM organization by a separate address-mapper component |
| Accel-Sim | per-instruction record ending in `mem_width [addresscompress?] [mem_addresses]`, a compressed multi-address list per warp | per-instruction order | flat byte addresses, compressed |
| SCALE-Sim | CSV row per cycle, listing every address transferred in that cycle, grouped by buffer and memory level | explicit global cycle | flat SRAM/DRAM addresses |

The weight trace already matches the SCALE-Sim shape, which is the
closest analogue: one time step, a set of addresses fetched at that time
step, grouped by the unit that fetched them. The bursted event
`[kh, kw, cin, cout_start, cout_end]` is the same compression idea as
Accel-Sim's compressed per-warp address list. Ramulator 2.0's design
places the address mapper inside the memory system as its own pluggable
component, which supports keeping logical coordinates in the trace and
resolving them to lines inside the simulator.

### 1.4 Verdict and proposed changes

**The event body stays exactly as it is.** Keeping logical tensor
coordinates rather than pre-flattened byte addresses is the right call
for this project: the address mapping is a swept parameter, and baking
addresses into the trace would force a full 7.7 GB regeneration for each
new layout. This mirrors Ramulator 2.0's separation of the trace from
the address mapper.

**Seven additive fields should be added**, all in headers, none in the
per-event body, so every existing file remains readable and no
regeneration is required.

Layer header:

| Field | Value | Purpose |
|---|---|---|
| `format_version` | `2` | Distinguishes this from the Stage 1 nested schema, which becomes version 1 by convention. |
| `weight_bytes` | `1` | Makes element width explicit rather than an assumption held by each consumer. |
| `burst_dim` | `"COUT"` | Names which dimension the `[start, end)` run walks, so a future arch can emit a `cin` run and readers can tell. |
| `burst_stride` | `1` | States that the run is unit-stride and the interval is half-open. |
| `spatial_factors` | e.g. `{"COUT": 8, "HO": 8, "WO": 2}` | Lets `core_id` be decoded without opening the schedule artifact under `outputs/schedules/`, removing a cross-file dependency. |
| `timing_model` | `"zero_latency_issue_schedule"` | Records that the tick timeline was produced under an assumption of zero memory latency, so a simulator that adds stalls knows the trace is an issue order and a future re-timed trace is distinguishable. |

Tile header:

| Field | Value | Purpose |
|---|---|---|
| `tick_base` | prefix sum of preceding tiles' `mac_cycles` | Gives a global monotonic time axis. Every other surveyed format has one; this format's tick is tile-local. |

`tick_base` is derivable by any reader from `mac_cycles` under the
assumption that tiles run back to back with no gap. Writing it into the
file turns that assumption into recorded data. Readers of version-1
files derive it and record that they did.

The generator change is confined to `src/tracegen.py` (the two dataclass
definitions and `assemble_layer_traces`). No arch model, native bridge,
schedule solver, or NoC code is touched.

### 1.5 Worked example of the extended header

Below is one real file's header,
`loas / inst16_node32kb_noc512kb / resnet19_T4_all /
layer_19_layer3_1_conv2 / sample_00002.json.gz`, with the seven new
fields marked. Existing fields carry their measured values; the event
body is unchanged.

```json
{
  "format_version": 2,                          // NEW
  "arch": "loas",
  "trace_dir": "resnet19_T4_all",
  "layer_name": "layer_19_layer3_1_conv2",
  "sample_idx": 2,
  "workload_dims": {
    "KH": 3, "KW": 3, "CIN": 512, "COUT": 512,
    "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"
  },
  "weight_bytes": 1,                            // NEW
  "burst_dim": "COUT",                          // NEW
  "burst_stride": 1,                            // NEW
  "spatial_factors": {"COUT": 4, "HO": 2, "WO": 2},   // NEW
  "timing_model": "zero_latency_issue_schedule",     // NEW
  "dram_num_steps": 128,
  "noc_num_steps": 1,
  "tiles": [
    {
      "dram_i": 0,
      "noc_i": 0,
      "mac_cycles": 1618,
      "lif_cycles": null,
      "tick_base": 0,                           // NEW
      "ticks": [
        {"tick": 0, "cores": [
          {"core_id": 0,  "weight_addresses": [[1, 1, 0, 0, 4]]},
          {"core_id": 1,  "weight_addresses": [[1, 0, 0, 0, 4]]}
        ]},
        {"tick": 1, "cores": [ ... ]}
      ]
    },
    {
      "dram_i": 1,
      "noc_i": 0,
      "mac_cycles": 1594,
      "lif_cycles": null,
      "tick_base": 1618,                        // NEW: 0 + 1618
      "ticks": [ ... ]
    }
  ]
}
```

Field notes:

- `weight_bytes: 1` follows from `BW_WEIGHT: 8` in
  `configs/arch/loas_multinode.yaml`, so bytes and elements coincide.
- `burst_dim: "COUT"` with `burst_stride: 1` states that
  `[kh, kw, cin, cout_start, cout_end]` walks `cout` from `cout_start`
  up to and excluding `cout_end` in unit steps. Every burst in the
  measured corpus has width 4.
- `spatial_factors` is copied verbatim from `schedule.spatial_factors`
  at generation time; its product equals the core count. The shape is
  the same one `decode_core_id` already consumes (the verified 128-core
  `loas` case is `{"COUT": 8, "HO": 8, "WO": 2}`).
- `tick_base` is the running sum of preceding tiles' `mac_cycles`, so
  global time for any event is `tick_base + tick`. The example's second
  tile starts at 1618 because the first tile has `mac_cycles: 1618` and
  its ticks are dense `0..1617`.
- `timing_model` records that the tick timeline was produced assuming
  zero memory latency. Once the simulator stalls cores, it treats these
  ticks as a desired issue order rather than a ground-truth timeline.

---

## Part 2. MSHRs for a read-only L1/L2 weight cache

### 2.1 The gem5 mechanism, as established 2026-08-04

Source citations below come from the survey note filed at
`research/surveys/gem5-l2-cache-modeling/` in the vault, all pinned to
gem5 commit `cbf0eae` and its source notes.

- An MSHR is one block address plus two ordered target lists
  (`mshr.cc:300-326`). MSHRs live in a fixed pool built on a generic
  `Queue<Entry>` template (`queue.hh:69-71`).
- Every miss first calls `mshrQueue.findMatch(blk_addr, ...)`
  (`cache.cc:370`). A match appends a target and issues nothing
  downstream, counted as an MSHR hit (`base.cc:387-401`). A non-match
  allocates a new MSHR and schedules a memory-side send, counted as an
  MSHR miss (`base.cc:448`).
- Two bounds exist: `mshrs` on distinct in-flight lines, and
  `tgts_per_mshr` on waiters per line (`Cache.py:101-104`).
- Both bounds are checked after the allocation, so effective capacity is
  the bound plus a one-request transient overshoot
  (`base.hh:1181-1183`, `base.cc:400-409`).
- Overflow sets a cause bit in an 8-bit mask and blocks the CPU-side
  port (`base.hh:1208-1218`). Three causes exist: `Blocked_NoMSHRs`,
  `Blocked_NoWBBuffers`, `Blocked_NoTargets` (`base.hh:119-125`).
- Blocking is all or nothing: once blocked, the cache refuses every new
  request including ones that would have hit (`base.cc:2606-2637`).
- Release is per cause. The MSHR block clears when a response frees a
  slot (`base.cc:649-657`); the target block clears on the first response
  to the offending MSHR, tracked through one saved pointer
  (`base.cc:571-575`).
- Prefetches are throttled by `canPrefetch()`, which requires
  `demand_mshr_reserve + 1` free slots (`mshr_queue.hh:158-163`), and are
  dropped when the target is already resident or already pending
  (`base.cc:960-977`).
- gem5's own L2 convention is `mshrs = 20, tgts_per_mshr = 12`; its L1
  convention is `mshrs = 4, tgts_per_mshr = 20` (`Caches.py:52-78`).
- `NoncoherentCache` keeps the entire MSHR pool, blocked-cause mask, and
  both ports while dropping coherence, which is the in-tree evidence that
  concurrency machinery is separable from coherence machinery
  (`noncoherent_cache.hh:41-80`).

### 2.2 Glossary of the gem5 terms used below

**`deferredTargets`.** A gem5 MSHR holds *two* ordered target lists
(`mshr.cc:300-326`). `targets` holds requests the in-flight response can
legally satisfy. `deferredTargets` holds requests that arrived while the
MSHR was already in service but that the coming response **cannot**
satisfy, so they must wait for a second round trip. After the fill, gem5
promotes the deferred list into the main list and marks the MSHR pending
again rather than deallocating it (`mshr.cc:394-406`,
`base.cc:641-648`). There are exactly two triggers for deferral: a cache
maintenance operation (invalidate or clean), and a target that needs a
*writable* copy when the response will not be writable. Both are write
or coherence concerns, so a read-only cache never populates the list.

**`Blocked_NoWBBuffers`.** One of gem5's three block causes
(`base.hh:119-125`). gem5's *write buffer* holds dirty lines that were
evicted from the cache and still owe a writeback to memory. When that
buffer fills, the cache blocks with this cause. A cache that never writes
has no dirty lines, therefore no writebacks, therefore no write buffer,
therefore this cause can never be raised. The two causes that remain are
`Blocked_NoMSHRs` (no free MSHR for a new line) and `Blocked_NoTargets`
(the matched MSHR already holds `tgts_per_mshr` waiters).

**Critical-word-first.** A memory fill returns a whole line, but the
word the requester actually asked for can be delivered ahead of the rest.
gem5 models this by charging a target an extra `pkt->payloadDelay` when
its offset within the line differs from the first target's offset
(`noncoherent_cache.cc:262-281`), so two cores waiting on the same line
for different words complete at different times.

**`demand_mshr_reserve`.** A gem5 cache parameter, default 1
(`Cache.py:101-104`), enforced by
`MSHRQueue::canPrefetch()`, which reads
`allocated < numEntries - (numReserve + 1 + demandReserve)`
(`mshr_queue.hh:158-163`). It reserves MSHR headroom for demand misses
so that speculative prefetches cannot consume the last slots and block a
real request. With `l2_mshrs = 20` and `demand_mshr_reserve = 1`, a
prefetch may allocate only while fewer than 18 MSHRs are occupied, while
a demand miss may use all 20.

**`hit_under_block`.** gem5 blocks at the port, so once the cache is
blocked for any cause it refuses *every* new request, including requests
that would have hit in the array (`base.cc:2606-2637`). A hit needs no
MSHR, so refusing it is a property of where gem5 places the block rather
than a requirement. This design exposes the choice: `true` serves a hit
while the MSHR pool is full, `false` reproduces gem5's behavior.

**`bound_check_order`.** gem5 allocates first and checks fullness after,
in both overflow cases (`base.hh:1181-1183`, `base.cc:400-409`), so the
request that consumes the last slot succeeds and the *next* one is
refused. Effective capacity is therefore the bound plus a one-request
transient overshoot. `before_allocate` checks first and refuses at
exactly the bound, giving a hard capacity of N.

### 2.3 What read-only removes

Applying the read-only, no-coherence, no-writeback property of this
project's cache to the list above:

| gem5 element | Status in a read-only weight cache |
|---|---|
| `deferredTargets` second list | Structurally empty, since both deferral triggers are write or coherence concerns (`mshr.cc:394-406`). The MSHR carries **one** target list. |
| `promoteWritable`, `postInvalidate` | Absent. |
| `Blocked_NoWBBuffers`, `write_buffers`, `WriteQueue`, `write_allocator`, `writeback_clean` | Absent. **Two** block causes survive: `NoMSHRs` and `NoTargets`. |
| Snooping, coherence state bits, clusivity | Absent. Inclusion is a fixed design property. |
| Critical-word-first per-target payload delay | Not modeled. A fill delivers the whole line at `ready_time` and every waiting core is released together. This is a deliberate simplification rather than a structural consequence: when `cin_block > 1`, two cores can genuinely want different quarters of the same line, and gem5 would separate their completion times. Modeling that requires sub-line delivery order, which this design does not carry. |
| Per-target payload | Reduces to a requester identity. A target is "which core to wake", carrying no other state. |
| Eviction of an in-flight line | Becomes a pure pinning rule: a line with an outstanding MSHR is excluded from the victim set. No dirty-writeback interaction exists. |

The resulting MSHR entry is:

```
MshrEntry {
  LineId   line;          // the line being fetched
  Tick     issue_time;    // when it was allocated
  Tick     ready_time;    // issue_time + miss latency of the level below
  bool     in_service;    // request has been sent downstream
  bool     from_prefetch; // target 0 origin, so prefetch fills stay separable
  vector<CoreId> targets; // ordered waiters, bounded by tgts_per_mshr
}
```

### 2.4 Measured concurrency demand

Distinct lines demanded per tick, computed on the real trace above under
a 4-wide `cout` line, aggregated over every core in the tick:

| Metric | `inst16` | `inst1024` |
|---|---|---|
| Line requests per tick, mean / max | 16.0 / 16 | 707.0 / 1024 |
| Distinct lines per tick, mean / median / max | 16.0 / 16 / 16 | 627.4 / 704 / 1024 |
| Merge ratio (total / distinct), mean / max | 1.00 / 1.00 | 1.13 / 4.00 |
| Fraction of ticks above 20 distinct | 0.000 | 1.000 |
| Fraction of ticks above 64 distinct | 0.000 | 0.994 |

These counts are demand at the top of the hierarchy, so they are an
upper bound on what reaches the L2 after L1 filtering. Three conclusions
follow directly:

1. **Concurrency pressure is set by spatial fanout.** At 16 cores, gem5's
   L2 convention of 20 MSHRs is never binding. At 1024 cores, it is
   binding in every single tick. The MSHR bound therefore belongs in the
   swept structural grid rather than in a fixed default.
2. **The value of MSHR modeling here is the bound, not the merge.** Same
   line merging saves 0% at 16 cores and 13% at 1024 cores, because the
   spatial split is on `COUT` and cores work on disjoint `cout` blocks by
   construction.
3. **`tgts_per_mshr` is expected to stay inert.** Maximum observed
   waiters per line is 4, against gem5's convention of 12. It should be
   implemented for completeness and reported, with the expectation that
   it never binds on this workload.

### 2.5 MSHRs at L1

Each core issues exactly one bursted event per tick, and a 4-wide `cout`
burst resolves to exactly one line under a `cout_block >= 4` layout. A
private L1 therefore sees at most one outstanding line at a time on this
workload, and `l1_mshrs = 4` (gem5's convention) is never binding.

The L1 MSHR pool should still exist, for three reasons:

- It is the same code as the L2 pool, so it costs nothing to instantiate.
- It becomes binding as soon as the layout narrows (a `cout_block` of 1
  turns one burst into 4 line requests) or an arch emits multiple events
  per core per tick, both of which the format already permits.
- It is the structure that holds a core's backpressure once the L2 can
  refuse requests, which is where per-core stall time is accumulated.

### 2.6 MSHRs at L2

The shared L2 is where the bound binds. `l2_mshrs` has a direct physical
reading here: the number of distinct weight lines the accelerator can
have in flight to off-chip memory at once. At 1024 cores, any realistic
bound throttles, which makes this the one mechanism in the design capable
of showing that adding cores stops helping.

Off-chip bandwidth should be a **separate** knob,
`l2_fill_lines_per_tick`, rather than being folded into `l2_mshrs`.
gem5 puts bandwidth in the crossbar (`XBar.py:154-163`, `width = 32`
bytes) and concurrency in the cache, and the crossbar's own comment
concedes that the layering is a modeling convenience
(`XBar.py:152-154`). Keeping the two knobs distinct is what makes a
result attributable to MSHR occupancy or to fill bandwidth.

### 2.7 The engine: bounded, timed, blocking

There is one engine, `TimedEngine`, with real bounded concurrency and
time. An MSHR occupies its slot from allocation until its fill lands,
spanning ticks. When allocation fails, the requesting core is refused and
retries. The engine re-times the trace: the reported timeline differs
from the trace's own tick timeline, and the deliverable is cycles and a
stall breakdown alongside hit rates.

The unbounded, zero-latency behavior remains available as a **config
point**, `baseline_unbounded`, rather than as a second code path:

```
l1_mshrs = unbounded, l2_mshrs = unbounded,
l1_miss_latency_ticks = 0, l2_miss_latency_ticks = 0,
l2_fill_lines_per_tick = unbounded
```

Under that setting no MSHR is ever occupied past the tick it was
allocated in, nothing ever blocks, and the timeline collapses back onto
the trace's own ticks. It serves three purposes: the pure hit-rate answer
when concurrency is not the question, the anchor point at one end of the
`l2_mshrs` sweep, and the fixture-level regression that proves the timing
machinery adds nothing when its mechanisms are disabled.

The engine requires four semantics that the trace cannot supply, stated
as named assumptions:

- **Core response to refusal: `stall_in_order`.** A refused core holds
  its request and re-issues it on the next tick without advancing its
  trace pointer. Its whole remaining stream shifts later. This models an
  in-order issue stage, which is what an SNN PE is.
- **Issue time.** The simulator maintains `core_ready_time` per core. A
  request issues at `max(tick_base + tick, core_ready_time)`.
  Backpressure advances `core_ready_time`.
- **Tile barrier.** A tile's tick 0 begins after every core has completed
  the previous tile, matching the lock-step assumption the trace was
  generated under (`mac_cycles = max` over cores, Stage 1 plan).
- **Miss latency.** Two integers, `l1_miss_latency_ticks` (L2 round trip)
  and `l2_miss_latency_ticks` (off-chip round trip). These are what make
  an MSHR occupied long enough for the bound to bind.

### 2.8 Parameter set

| Parameter | Default | Sweep range | Notes |
|---|---|---|---|
| `l1_mshrs` | 4 | {4, 8, unbounded} | gem5 L1 convention. Expected inert on this workload. |
| `l1_tgts_per_mshr` | 20 | fixed | gem5 L1 convention. Expected inert. |
| `l2_mshrs` | 20 | {16, 32, 64, 128, 256, 512, 1024, unbounded} | Range chosen to span measured demand of 16 to 1024. gem5's L2 convention is the low end. |
| `l2_tgts_per_mshr` | 12 | fixed | gem5 L2 convention. Max observed demand is 4. |
| `demand_mshr_reserve` | 1 | fixed | Prefetch throttle, see glossary 2.2. |
| `l2_fill_lines_per_tick` | unbounded | {1, 4, 16, 64, unbounded} | Off-chip fill bandwidth, kept separate from `l2_mshrs` following gem5's crossbar split. |
| `l1_miss_latency_ticks` | 2 | {2, 10} | Round trip to L2. |
| `l2_miss_latency_ticks` | 100 | {50, 100, 200} | Round trip to off-chip memory. |
| `hit_under_block` | `true` | {true, false} | `false` reproduces gem5's all-or-nothing port block, see glossary 2.2. |
| `bound_check_order` | `before_allocate` | fixed | Hard bound of exactly N, see glossary 2.2 and decision 1 below. |

### 2.9 Named decisions to sign off

1. **Bound checking happens before allocation**, giving a hard bound of
   exactly N. gem5 checks after allocation, giving N plus a one-request
   transient (`base.hh:1181-1183`). A hard bound is easier to interpret
   across a sweep of `l2_mshrs`, and the divergence is one slot.
2. **`hit_under_block` defaults to true.** A hit needs no MSHR, so
   serving it while blocked is safe in a read-only cache. gem5's
   all-or-nothing behavior remains reachable by setting the switch false.
3. **The unbounded, zero-latency baseline is a config point**, named
   `baseline_unbounded`, and it is the one config in the grid whose hit
   rates carry no timing interaction.
4. **Prefetching carries forward as a pluggable module** with the
   gem5-sourced rules attached: throttle via `demand_mshr_reserve`, and
   drop a prefetch whose target is already resident or already pending
   (`base.cc:960-977`). Prefetch fills stay separable from demand
   accesses in the statistics.

---

## Part 3. Decoupled architecture

### 3.1 The seam in the current pipeline

Everything upstream stays untouched:

```
configs/arch/*.yaml + configs/dataflow/*.yaml
        |
        v
scripts/solve_schedules.py  -->  outputs/schedules/**.json
        |
        v
scripts/generate_weight_traces.py + src/tracegen.py
        |
        v
/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/
    <arch>/<arch_cfg>/<workload>/<layer>/sample_*.json.gz
        |
        v
   [ NEW: src/wcache/ ]                      <-- the only new component
        |
        v
profiling/0805_wcache/results/*.csv  -->  artifact/data.js + index.html
```

The new simulator's entire contract with the repo is: it reads trace
files and a config, and it writes result rows. `src/archmodels/`,
`src/nocsim/`, `src/mip_solver/`, `src/parsers/`, and
`scripts/*` are unchanged. The single upstream edit is the additive trace
header from Part 1.4, confined to `src/tracegen.py`.

Naming the new tree `src/wcache/` keeps it fully independent of
`src/cachesim/`, so the two can coexist during validation and the old
tree can be removed on its own schedule.

### 3.2 The front end / back end contract

**Python owns:** which runs to perform, config grid expansion, file
discovery, job partitioning and Slurm submission, result aggregation,
plotting, and artifact construction.

**C++ owns:** reading one trace file, address mapping, cache arrays,
replacement, MSHRs, the tick engine, and statistics.

**The boundary is a process boundary with JSON on both sides.** The
back end binary takes a config JSON path and a trace path, and writes one
result JSON to stdout.

```
wcache_run --config cfg.json --trace sample_00002.json.gz > result.json
wcache_sweep --config-grid grid.json --trace sample_00002.json.gz > results.jsonl
```

Rationale for a process boundary over pybind11 bindings:

- The unit of work is one (trace, config grid) job lasting seconds to
  minutes, so invocation overhead is irrelevant.
- A sweep point that crashes or exceeds memory takes down one process
  rather than the Python driver holding the whole grid.
- The binary is directly runnable from a shell, which makes reproducing
  and bisecting a single sweep point trivial.
- Slurm arrays over independent processes is the pattern this repo
  already uses.

**The Python side never parses a trace body.** This is a hard rule
justified by the 20.84 s versus 0.86 s measurement in Part 1.2: the cost
is the JSON text encoding, not the compression, so a C++ parser reading
the same 315.8 MB resolves it in a fraction of a second. Python reads
only headers when it needs metadata, and even that is optional.

`wcache_sweep` exists so one parsed trace serves an entire config grid.
With 24 or more configuration points per trace, parsing once instead of
per point is the difference between minutes and hours across the corpus.

### 3.3 Module inventory

Each interface below is a pure-virtual C++ class with implementations
registered in a name-to-factory registry, following Ramulator 2.0's
registry approach, so a new implementation is added by writing one class
and one registration line.

| Module | Interface | Implementations at build time | Why it is separable |
|---|---|---|---|
| `TraceReader` | `bool next(TickBatch&)` yielding `{global_tick, [(core_id, burst)]}` | `JsonWeightTraceReader` (format versions 1 and 2), `SyntheticReader` | Isolates the entire Part 1 format question. A format change touches this class only. |
| `AddressMapper` | `expand(burst) -> [LineId]`, `locate(LineId) -> {set_index, tag}` | `BlockPackMapper(cin_block, cout_block)`, `LinearMapper(line_bytes)` | Isolates layout. Layouts become a sweep axis without regenerating traces. |
| `CacheArray` | `probe`, `insert`, `victim` | `SetAssociativeArray`, `FullyAssociativeArray` | Geometry independent of policy. |
| `ReplacementPolicy` | `on_hit`, `on_fill`, `pick_victim(candidates)` | `LRU`, `FIFO`, `Random`, `PinnedDecorator` | `PinnedDecorator` implements the in-flight-line exclusion from 2.2, wrapping any base policy. |
| `MshrPool` | `find_match`, `allocate`, `add_target`, `deallocate`, `is_full`, `can_prefetch` | one implementation | The whole of Part 2, in one class shared by L1 and L2. |
| `Prefetcher` | `on_miss(LineId) -> [LineId]` | `NullPrefetcher`, `NextCoutBlock` | Prefetch policy becomes a sweep axis. |
| `CacheLevel` | one array, one policy, one MSHR pool, one prefetcher, one downstream pointer | one implementation | L1 and L2 are the same class with different config. The hierarchy is a `vector<CacheLevel>`, so a third level needs no new code. |
| `Engine` | `run() -> Stats` | `TimedEngine` | One engine. The four named assumptions of 2.7 live in this one class, and the unbounded zero-latency baseline is reached by config rather than by a second implementation. |
| `Stats` | counters plus histograms | one implementation | Single output schema across all modes, so results merge safely. |

Making `CacheLevel` uniform and the hierarchy a vector is the structural
choice that keeps L1 and L2 from being special cases, and it is what
allows the MSHR work of Part 2 to be written once.

### 3.4 Directory layout

```
configs/wcache/
  default.yaml            # the hierarchy to edit by hand, see 3.5
  baseline_unbounded.yaml # unbounded MSHRs, zero latency
  sweep_mshr.yaml         # grid file for the multi-point run
src/wcache/
  __init__.py
  config.py          # dataclasses mirroring the C++ config, field for field
  cli.py             # single-config run: build config, invoke binary, parse result
  sweep.py           # grid expansion, preview printing, Slurm submission
  results.py         # result rows -> CSV, and artifact data.js generation
  reference/         # small pure-Python model, used only to cross-check fixtures
  native/
    Makefile
    include/wcache/
      types.h  config.h  trace.h  layout.h  cache.h  repl.h
      mshr.h   prefetch.h  engine.h  stats.h  registry.h
    src/*.cpp
    tools/wcache_run.cpp
    tools/wcache_sweep.cpp
    tests/            # C++ fixture tests, one file per interface
debug/                # hand-checkable verification scripts, continuing 18+
profiling/0805_wcache/
  results/            # sweep output
  artifact/           # index.html + data.js, following profiling/0803_l1_l2_cache/
```

### 3.5 Where L1 and L2 configuration lives

Cache configuration is a YAML file under `configs/wcache/`, matching how
`configs/arch/` and `configs/dataflow/` already work in this repo. One
file describes a complete hierarchy, with an `l1:` and an `l2:` block
carrying the same field set, since both are the same `CacheLevel` class.

`configs/wcache/default.yaml`:

```yaml
wcache:
  layout:
    cin_block:  4          # elements of CIN packed per line
    cout_block: 4          # elements of COUT packed per line
                           # line_size_bytes = cin_block * cout_block * weight_bytes

  l1:                      # private, one instance per core
    cache_size_bytes: 32768        # 32 KB
    cache_type: set_associative    # fully_associative | set_associative | direct_mapped
    associativity: 4               # required when cache_type: set_associative
    replacement: lru               # lru | fifo | random
    mshrs: 4                       # unbounded | <int>
    tgts_per_mshr: 20
    miss_latency_ticks: 2          # round trip to L2
    prefetcher: null               # null | next_cout_block

  l2:                      # shared, one instance
    cache_size_bytes: 524288       # 512 KB
    cache_type: set_associative
    associativity: 32
    replacement: lru
    mshrs: 20                      # the parameter of interest, see 2.6
    tgts_per_mshr: 12
    demand_mshr_reserve: 1
    miss_latency_ticks: 100        # round trip to off-chip
    fill_lines_per_tick: unbounded # off-chip fill bandwidth
    prefetcher: next_cout_block

  engine:
    core_stall_policy: stall_in_order
    hit_under_block: true
    bound_check_order: before_allocate
```

`configs/wcache/baseline_unbounded.yaml` is the same file with `mshrs`
unbounded, both `miss_latency_ticks` at 0, and `fill_lines_per_tick`
unbounded, per decision 2.9.3.

Three ways to set configuration, in increasing precedence:

1. **The YAML file**, as above. This is the normal path and the one to
   edit by hand.
   ```
   python -m wcache.cli --cache-config configs/wcache/default.yaml --trace <path>
   ```
2. **CLI overrides** for one-off changes, using dotted paths that mirror
   the YAML tree, so nothing needs a new file to try one value.
   ```
   python -m wcache.cli --cache-config configs/wcache/default.yaml \
       --set l2.mshrs=64 --set l2.cache_size_bytes=1048576 --trace <path>
   ```
3. **A sweep grid file** for the multi-point runs, where any field may
   carry a list and the driver takes the cross product.
   ```yaml
   # configs/wcache/sweep_mshr.yaml
   base: configs/wcache/default.yaml
   grid:
     l2.mshrs:            [16, 32, 64, 128, 256, 512, 1024, unbounded]
     l2.cache_size_bytes: [131072, 262144, 524288, 1048576]
     l2.associativity:    [4, 32]
   ```

The chain is: YAML plus overrides resolve in Python into a
`WcacheConfig` dataclass, which serializes to the JSON the back end
consumes. YAML never reaches C++.

### 3.6 Config as a single source of truth

`src/wcache/config.py` and `include/wcache/config.h` describe the same
fields. To keep them from drifting, `config.py` emits the JSON the binary
consumes, and the binary supports `--dump-config-schema`, which prints
its own field list. A test asserts the two lists are identical. Any field
added on one side and forgotten on the other fails that test immediately.

---

## Part 4. Build order

**M0. Trace header extension.** Add the seven fields from Part 1.4 to
`src/tracegen.py`. Confirm a version-1 file still loads through a reader
that derives the missing fields.

**M1. Back end skeleton at `baseline_unbounded`.** `TraceReader`,
`AddressMapper`, `CacheArray`, `ReplacementPolicy`, `CacheLevel`,
`TimedEngine`, `Stats`, and `wcache_run`. The engine is the real timed
one from the start; this milestone runs it only at unbounded MSHRs and
zero latency, so the timeline collapses onto the trace's ticks and the
output is hit rates. Verified on hand-made tiny fixtures.

**M2. Front end.** `configs/wcache/*.yaml`, `config.py`, `cli.py`, the
`--set` override path, and the schema equality test. One real trace runs
end to end from a Python command.

**M3. MSHRs and blocking.** `MshrPool`, `find_match` merging, both
bounds, the two block causes, `hit_under_block`, `PinnedDecorator`, and
the full accounting: distinct versus total missing lines, MSHR hits and
misses, per-cause blocked ticks.

**M4. Time.** Non-zero `miss_latency_ticks` at both levels,
`core_ready_time`, the `stall_in_order` retry path, tile barriers, and
`fill_lines_per_tick`. This is the milestone at which the reported
timeline diverges from the trace's own.

**M5. Prefetch module.** `NextCoutBlock` with the throttle and drop rules
from 2.9, reported separately from demand accesses.

**M6. Sweep, preview, artifact.** `sweep.py`, `wcache_sweep`, results
aggregation, and the artifact under `profiling/0805_wcache/artifact/`.

---

## Part 5. Verification

Hand-made fixture tests continue the `debug/NN_verify_*.py` numbering
from 17. Each carries a hand-computed expected result.

Structural:
1. Burst expansion under `BlockPackMapper` for several `(cin_block, cout_block)` values.
2. Set index reachability: every set is reachable for the true layer shape.
3. Two-level miss-fill and inclusion on a hand-traced sequence.

MSHR, one test per rule in Part 2:
4. A second request to a pending line merges as a target and issues nothing downstream.
5. Allocation succeeds at exactly `mshrs` occupancy and fails at `mshrs + 1`.
6. Target overflow at `tgts_per_mshr` raises the no-targets cause.
7. A fill releases the corresponding cause and only that cause.
8. `hit_under_block` true serves a hit while blocked; false refuses it.
9. A prefetch is refused while fewer than `demand_mshr_reserve + 1` slots are free.
10. A prefetch whose target is resident or pending is dropped.
11. A line with an outstanding MSHR is excluded from the victim set.

Engine:
12. At `baseline_unbounded`, every fixture's reported timeline equals the
    trace's own tick timeline, nothing blocks, and no MSHR survives past
    the tick it was allocated in. This is the standing regression that
    the timing machinery adds nothing when its mechanisms are disabled.
13. Hit rates at `baseline_unbounded` are invariant to `l2_mshrs` and to
    both latencies when `hit_under_block` is true and no prefetcher is
    active, on every fixture.
14. `stall_in_order` on a hand-traced two-core, three-tick case with a
    forced refusal, verifying the shifted timeline and the stall
    attribution.
15. `fill_lines_per_tick` of 1 on a hand-traced case with 4 concurrent
    distinct misses, verifying that fills serialize across ticks while
    MSHR occupancy stays at 4.

Cross-check:
16. `src/wcache/reference/` reproduces the native result on every fixture.

### An optional validation to sign off

Running the existing `src/cachesim/` binary as a black-box oracle on one
real trace would confirm that `baseline_unbounded` reproduces the known
hit rates from `profiling/0803_l1_l2_cache/`. This
uses the old engine only through its command line output, with no reading
of its source. Flagged for a decision, since the standing rule for this
phase places that tree out of scope.

---

## Part 6. Deliverable

A sweep over the grid below, its results under
`profiling/0805_wcache/results/`, and an artifact under
`profiling/0805_wcache/artifact/` following the
`profiling/0803_l1_l2_cache/artifact/` convention.

Per this repo's standing requirement, the sweep prints a full preview and
waits for a go-ahead before running. The preview states: cache structures
and sizes, layout parameters, MSHR, latency and bandwidth parameters,
arch configs, workloads, layers, sample count, total sweep points,
expected output columns, and the destination directory.

### 6.1 The results CSV

One row per (arch config, workload, layer, sample, config point). Every
column is a scalar, so the file loads directly into a DataFrame and
merges safely across sweep shards. Sixteen identity and config columns
followed by the statistics.

**Identity (5 columns)**

| Column | Type | Example |
|---|---|---|
| `arch` | str | `loas` |
| `arch_config` | str | `inst1024_node32kb_noc4096kb` |
| `workload` | str | `resnet19_T4_all` |
| `layer` | str | `layer_19_layer3_1_conv2` |
| `sample_idx` | int | `2` |

**Config echo (11 columns)** so a row is self-describing and no join
against a separate config table is ever needed.

| Column | Example |
|---|---|
| `config_id` | `l2m64_l2s512k_a32` (short label used by the artifact) |
| `cin_block`, `cout_block` | `4`, `4` |
| `l1_size_bytes`, `l1_assoc`, `l1_mshrs` | `32768`, `4`, `4` |
| `l2_size_bytes`, `l2_assoc`, `l2_mshrs` | `524288`, `32`, `64` |
| `l2_fill_lines_per_tick` | `unbounded` |
| `l2_miss_latency_ticks` | `100` |

**Hit rates (6 columns)**

| Column | Meaning |
|---|---|
| `l1_accesses`, `l1_hits` | Aggregate over every core's private L1. |
| `l1_hit_rate` | `l1_hits / l1_accesses`. |
| `l2_accesses`, `l2_hits` | L1-missed traffic only. |
| `l2_hit_rate` | `l2_hits / l2_accesses`. |
| `overall_hit_rate` | `(l1_hits + l2_hits) / l1_accesses`. |

**MSHR accounting (6 columns)**

| Column | Meaning |
|---|---|
| `l2_mshr_misses` | Misses that allocated a new MSHR, gem5's sense. |
| `l2_mshr_hits` | Misses that merged into an existing MSHR. |
| `l2_merge_ratio` | `(mshr_hits + mshr_misses) / mshr_misses`. |
| `l2_distinct_per_tick_mean`, `_p99`, `_max` | Distribution of distinct missing lines per tick. |

**Concurrency pressure (5 columns)**

| Column | Meaning |
|---|---|
| `l2_mshr_occupancy_mean`, `_max` | Occupied MSHR slots, sampled per tick. |
| `ticks_over_mshrs` | Ticks whose distinct-miss demand exceeded `l2_mshrs`. |
| `excess_mean`, `excess_max` | Size of that overshoot. |

**Blocking and time (8 columns)**

| Column | Meaning |
|---|---|
| `blocked_ticks_no_mshrs` | Ticks blocked because the pool was full. |
| `blocked_ticks_no_targets` | Ticks blocked because an MSHR hit `tgts_per_mshr`. |
| `blocked_ticks_total`, `avg_blocked` | Total, and mean length of a blocked interval. |
| `core_stall_ticks_mean`, `_max` | Per-core stall, aggregated across cores. |
| `simulated_ticks` | Total simulated time. |
| `slowdown` | `simulated_ticks / trace_ticks`, so `1.0` means nothing stalled. |

**Prefetch (5 columns)**

| Column | Meaning |
|---|---|
| `pf_issued` | Prefetches that allocated an MSHR. |
| `pf_dropped_resident`, `pf_dropped_pending`, `pf_dropped_throttle` | Drops by reason, the third being the `demand_mshr_reserve` throttle. |
| `pf_useful` | Prefetched lines later hit by a demand access before eviction. |

Prefetch fills never count toward `l2_accesses` or `l2_hits`, so the hit
rate columns describe demand traffic only.

### 6.2 Example row

```csv
arch,arch_config,workload,layer,sample_idx,config_id,cin_block,cout_block,l1_size_bytes,l1_assoc,l1_mshrs,l2_size_bytes,l2_assoc,l2_mshrs,l2_fill_lines_per_tick,l2_miss_latency_ticks,l1_accesses,l1_hits,l1_hit_rate,l2_accesses,l2_hits,l2_hit_rate,overall_hit_rate,l2_mshr_misses,l2_mshr_hits,l2_merge_ratio,l2_distinct_per_tick_mean,l2_distinct_per_tick_p99,l2_distinct_per_tick_max,l2_mshr_occupancy_mean,l2_mshr_occupancy_max,ticks_over_mshrs,excess_mean,excess_max,blocked_ticks_no_mshrs,blocked_ticks_no_targets,blocked_ticks_total,avg_blocked,core_stall_ticks_mean,core_stall_ticks_max,simulated_ticks,slowdown,pf_issued,pf_dropped_resident,pf_dropped_pending,pf_dropped_throttle,pf_useful
loas,inst1024_node32kb_noc4096kb,resnet19_T4_all,layer_19_layer3_1_conv2,2,l2m64_l2s512k_a32,4,4,32768,4,4,524288,32,64,unbounded,100,5060480,4211903,0.8323,848577,391204,0.4610,0.9096,347118,44086,1.1270,627.4,1010,1024,63.2,64,7116,563.4,960,7116,0,7116,88.4,71204.5,73990,712358,99.52,52034,18877,9455,3126,31890
```

The `slowdown` of 99.52 in this illustration is what the sweep exists to
find: it states how far a bounded L2 pushes the real timeline past the
zero-latency schedule the trace was generated under. At
`baseline_unbounded` that column reads `1.0` by construction.

---

## Open items for sign-off

1. The `l2_mshrs` sweep range in Part 2.8 spans 16 to 1024 plus
   unbounded, which is 8 points. Crossing it with existing cache
   structures and sizes multiplies the grid, so the intended breadth of
   the first real run needs confirming.
2. The latency values (`l2_miss_latency_ticks` of 50, 100, 200) are
   placeholders pending a target memory technology. `DRAM_LATENCY: 17`
   in `configs/arch/loas_multinode.yaml` is one candidate anchor.
3. Whether the first sweep covers `loas` only, matching the corpus that
   exists today, or waits for other archs to be generated.
4. The optional old-engine black-box validation in Part 5.
5. Whether `src/cachesim/` is removed once `baseline_unbounded` is
   validated, or kept alongside.

---

## Sources

gem5 mechanism claims come from the survey filed 2026-08-04 at
`research/surveys/gem5-l2-cache-modeling/` in the Obsidian vault, and its
source notes `gem5 MSHR and MSHRQueue`, `gem5 BaseCache miss path and
blocking`, `gem5 BaseCache SimObject parameters`, `gem5 classic
memory-system ports`, `gem5 NoncoherentCache`, and `gem5 example L1 and
L2 cache configurations`, all pinned to commit `cbf0eae` with the local
clone at `/u/yyu9/gem5`.

Trace-format comparison (Part 1.3):

- [ChampSim](https://github.com/ChampSim/ChampSim)
- [Ramulator 2.0](https://github.com/CMU-SAFARI/ramulator2) and its paper, [arXiv:2308.11030](https://arxiv.org/html/2308.11030v2)
- [Accel-Sim NVBit tracer trace format](https://github.com/accel-sim/accel-sim-framework/blob/release/util/tracer_nvbit/README.md)
- [SCALE-Sim](https://github.com/scalesim-project/scale-sim-v2) and [SCALE-Sim v3](https://arxiv.org/html/2504.15377)

MSHR scaling background (Part 2.4's conclusion that bounds belong in the
sweep):

- [Scalable Cache Miss Handling for High Memory-Level Parallelism, MICRO 2006](https://iacoma.cs.uiuc.edu/iacoma-papers/micro06_mshr.pdf)
- [MiCache: An MSHR-inclusive Non-blocking Cache Design for FPGAs, FPGA 2024](https://dl.acm.org/doi/10.1145/3626202.3637571)
