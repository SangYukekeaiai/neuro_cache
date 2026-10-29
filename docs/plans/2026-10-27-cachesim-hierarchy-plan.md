# cachesim: hierarchical layout plan (DRAFT, awaiting review)

Status: proposal only. No code has been touched. Nothing below runs until the
owner approves this document.

Scope: `src/cachesim/native/` (27 headers, 15 .cpp, 2 apps, 22 test binaries,
6 shell drivers). The Python layer (`cli.py`, `grid.py`, `stream.py`,
`examples/`) and the binary names `cachesim_run` / `cachesim_sweep` do not
change, so `scripts/pipeline.py`, `tests/*.py`, and the WCTS format are
untouched.

## 1. Diagnosis: what is messy and what is not

The design underneath is sound and already pluggable. Every policy axis is a
virtual base + a factory switch + a string match in `config.cpp`; the engine
never branches on a policy kind. So this is a *file organisation* problem,
not an architecture problem. Three things make it feel messy:

1. **Flat namespace of 42 files.** `include/cachesim/*.h` and `src/*.cpp`
   put the address mapper, the replacement policies, the MSHR, the trace
   reader, and three debug logs side by side with no grouping.
2. **Files that hold several concerns** (the real source of the "messy"
   feeling):
   - `stamp_policy.h` holds the `StampPolicy` base, LRU, FIFO, Belady, LFU,
     RRIP, the `PolicyKind` enum, and `make_policy`. The name says "stamp";
     it holds every policy.
   - `prefetcher.h` holds two independent axes: the L1 `Prefetcher`
     (None/NextBurst) and the L2 `L2Prefetcher` (None/Neighbour).
   - `mshr.h` holds the MSHR *and* engine-wide types `Level`, `WaitReason`,
     `StallCause`, `Request`. Three logging headers include `mshr.h` only to
     get `Level`.
   - `apps/app_support.h` (491 lines) holds CLI arg parsing, `uuid4`, the
     layout factory `make_mapper`, Belady oracle loading, and CSV output.
     `make_mapper` is the only factory that lives outside the library.
3. **Layering nits.** `cache_level.h` includes the concrete
   `stamp_policy.h` just for `PolicyKind`/`make_policy`; enum-to-string
   tables for layouts are spelled out three times (`config.cpp`,
   `stats.cpp`, `sweep.cpp`) plus a two-way ternary at `config.cpp:560` that
   `sweep.cpp:10-13` explicitly warns against; RANDOM is rejected in three
   places.

One fact that shapes the "indexing" folder: **there is no indexing policy
today.** All three layouts (`block_pack`, `split_cin`, `khkw_split`) map a
line to a set with the same rule, `set = line % num_sets`, in
`src/layout_common.h:154-162`. The layouts differ only in how they flatten
(kh, kw, cin, cout) coordinates into a `LineId`. So "indexing" splits into
two real axes:
- **layout** (coordinate -> LineId): the three mappers, the paper's axis.
- **index** (LineId -> set, tag): a single modulo function, currently a
  private helper. Making it a named, swappable unit is cheap and is the
  hook for hashed or skewed indexing later.

## 2. Target tree

```
src/cachesim/native/
  include/cachesim/
    types.h                  root; unchanged
    layout/                  coordinate -> LineId  (paper: weight layout)
      mapper.h               was layout.h: AddressMapper, Placement, LayoutKind
      block_pack.h
      split_cin.h
      khkw_split.h
      factory.h              make_mapper, moved from apps/app_support.h
    index/                   LineId -> (set, tag) and the array that applies it
      set_index.h            NEW: the modulo rule lifted from layout_common.h
      cache_array.h          was cache.h: CacheArray, Candidate, InsertResult
      set_associative.h
    replacement/
      policy.h               ReplacementPolicy base + PolicyKind + make_policy decl
      stamp.h                StampPolicy base, LRU, FIFO
      belady.h
      lfu.h
      rrip.h
      next_use.h             NextUseOracle (Belady's future knowledge)
    prefetch/                third policy axis, same shape as replacement/
      prefetcher.h           Prefetcher base + PrefetchContext + PrefetchTarget
                             + PrefetchKind {None, NextBurst, Neighbour} + make_prefetcher
      none.h
      next_burst.h           NextBurstPrefetcher: bursts k+1..k+d of the triggering core
      neighbour.h            NeighbourPrefetcher: mapper.neighbour(line, axis, +-d)
    core/                    timing machinery, policy-agnostic
      request.h              NEW: Level, WaitReason, StallCause, Request (out of mshr.h)
      mshr.h
      port.h
      event.h
      cache_level.h
      engine.h
    trace/
      tile_trace.h           was trace.h
      stream_format.h
      byte_source.h
      stream_trace.h
    instrument/
      access_log.h
      cache_state_log.h
      line_trace.h
      hist.h
      stats.h
    config.h
    sweep.h
    enum_names.h             NEW: single source for every enum <-> string table
  src/                       mirrors include/ one-to-one (src/replacement/stamp.cpp, ...)
    layout/layout_common.h   stays private; loses locate_line (moved to index/)
  apps/
    cachesim_run.cpp
    cachesim_sweep.cpp
    cli_args.h               from app_support.h: arg helpers, uuid4
    oracle_io.h              from app_support.h: build_oracles, attach_oracles
    output.h                 from app_support.h: writers, PaddingMeter
  tests/
    <mirrors include/>       tests/replacement/test_lru.cpp, tests/core/test_mshr.cpp, ...
    *.sh, check.h, engine_fixture.h, mapper_conformance.h, stream_builder.h  unchanged location
```

Conventions:
- Include form becomes `#include "cachesim/replacement/policy.h"`. `-Iinclude`
  stays, so `compile_flags.txt` is unchanged.
- **One C++ namespace, `cachesim`.** No sub-namespaces. Directories give the
  grouping; sub-namespaces would touch every symbol for no gain in a
  research simulator.
- A directory exists only if it holds two or more files. `config.h`,
  `sweep.h`, `types.h`, `enum_names.h` stay at the top.
- Mixed-concern headers are split along class families, not one class per
  file (LRU and FIFO share `stamp.h` because they share `StampPolicy`).
- **Every policy axis is per level.** `LevelParams` carries a replacement
  kind and a prefetch kind (plus their parameters); `CacheLevel` owns one
  `ReplacementPolicy` and one `Prefetcher`, both built by a factory in its
  constructor. Any prefetcher can be plugged into L1 or L2.

## 3. Phases and gates

Each phase is a separate commit and must pass the full gate before the next
starts. Pure-move phases use `git mv` so blame survives.

**Gate (run after every phase):**
```
make -C src/cachesim/native MODE=fixture test        # 22 unit binaries + compile_fail.sh
make -C src/cachesim/native MODE=fixture test-cli    # run_cli, sweep_cli, v1_pipe, cout_golden
make -C src/cachesim/native MODE=release apps
make demo && sha256sum data/demo/loas/results.csv    # must be 95cbdfd8bd298056...
python scripts/pipeline.py --verify-baseline
make test                                            # pytest tests/
```
Phase 0 snapshots `results.csv` and the `test-cli` outputs to a scratch
`gate/` directory for `cmp`.

### Phase 1: pure moves (no semantic change)
- `git mv` headers, sources and tests into the tree above. No file is split
  yet; `stamp_policy.h` moves to `replacement/stamp_policy.h` whole,
  `prefetcher.h` to `prefetch/prefetcher.h`, and so on. Renames limited to
  `layout.h -> layout/mapper.h`, `cache.h -> index/cache_array.h`,
  `trace.h -> trace/tile_trace.h`.
- Rewrite every `#include <cachesim/X.h>` to its new path (sed, then build).
- Makefile: replace the five flat wildcards (`src/*.cpp`,
  `include/cachesim/*.h`, `tests/test_*.cpp`, `tests/*.h`, `apps/*.h`) with
  recursive ones (`$(shell find ... )`) and add `mkdir -p $(@D)` to the
  object and test rules so `build/$(MODE)/` mirrors the tree. The Makefile
  comment at lines 69-87 ("every unit is header-only today") is stale and
  gets removed.
- Update hardcoded lists: `tests/compile_fail.sh` include names (lines
  117-182), `tests/mutation_check.sh` `FILES=` list (line 79, 227-257).
- Docs: rewrite the native-relative paths in `docs/atlas/cachesim_native.md`
  (99 lines) and `docs/atlas/README.md`. The convention stated at
  `cachesim_native.md:3-8` still holds.
- Gate.

### Phase 2: split the mixed-concern files
- `replacement/stamp_policy.h` -> `policy.h` (base + `PolicyKind` +
  `make_policy`), `stamp.h`, `belady.h`, `lfu.h`, `rrip.h`; `.cpp` likewise.
  `cache_level.h` then includes only `replacement/policy.h`.
- `prefetch/prefetcher.h` is moved whole in this phase; its unification
  is Phase 3, because it changes an interface.
- `core/mshr.h` -> lift `Level`, `WaitReason`, `StallCause`, `Request` into
  `core/request.h`; the three instrument headers include that instead.
- Lift `locate_line` into `index/set_index.h` as a named function
  `set_index(LineId, num_sets) -> Placement`; the three mappers call it.
- Tests: split `test_stamp_policy.cpp` and `test_prefetch.cpp` to match.
- Gate.

### Phase 3: one pluggable prefetch axis (interface change, behaviour-preserving)
Today L1 and L2 have unrelated prefetch interfaces: L1 `Prefetcher` works
in trace bursts through the engine's `PrefetchIssuer` callback
(`engine_core.cpp:340-375`), L2 `L2Prefetcher::suggest` works in lines
(`engine.cpp:348-367`). Only the *decision* differs; the *mechanics* (which
port, which budget, which stats counters) belong to the level. This phase
separates the two.

- **Interface** (`prefetch/prefetcher.h`):
  ```
  struct PrefetchContext { Level level; CoreId core; int tile; BurstIndex k;
                           LineId line; SimTime now;
                           const AddressMapper& mapper; const TileTrace& trace; };
  struct PrefetchTarget  { LineId line; BurstIndex burst; };   // burst tags timely/late
  class Prefetcher {
    virtual void on_tile_start(CoreId) {}
    virtual void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) = 0;
    virtual void on_issued(CoreId, BurstIndex last_complete_burst) {}  // feedback for cursors
  };
  enum class PrefetchKind { None, NextBurst, Neighbour };
  struct PrefetchParams { int distance; Axis axis; bool up; bool down; };
  std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind, PrefetchParams, int n_cores);
  ```
  `NextBurst` reads `trace.burst(core, tile, k+1..k+d)` and expands through
  the mapper, keeping its per-core cursor exactly as today; `Neighbour`
  returns `mapper.neighbour(line, axis, +-d)`. Both are now legal at either
  level.
- **Ownership**: `CacheLevel` gets `prefetcher_` next to `policy_`, built
  from `LevelParams{prefetch_kind, prefetch_params}`. The engine keeps the
  two issue mechanics as they are (L1: in-flight cap
  `capacity - demand_reserve`, L1 port, burst tag; L2: bank port, drops
  resolved in triage) but asks the level's prefetcher for targets instead
  of calling two differently shaped objects. `PrefetchIssuer` goes away.
- **Config keys**: `l1_prefetch_policy`, `l1_prefetch_distance`,
  `l1_prefetch_axis`, `l1_prefetch_up`, `l1_prefetch_down`, and the same
  five with `l2_`. The old `prefetch_policy` / `prefetch_distance` are
  accepted as aliases for `l1_*` so `configs/cache/*.json` and `grid.py`
  keep working. `l1_demand_reserve` / `l2_demand_reserve` already exist.
- **CSV columns**: unchanged in this phase (`prefetch_policy`,
  `prefetch_distance`, `l2_prefetch_*`), so the results.csv gate still
  applies byte for byte. Renaming the columns to the `l1_` spelling is a
  separate decision because it forces a baseline rebase (decision 7).
- **Equivalence hazards the gate must catch**: issue order of prefetch
  lines within a burst; NextBurst's cursor stopping on a budget-exhausted
  burst (today `issue_prefetch` returns false mid-burst and the cursor does
  not advance); `pf_budget_exhausted` and the four outcome counters;
  L2 `up`/`down` counting by line order. The demo grid sweeps
  `next_burst` at L1 (`configs/cache/khkw_sweep.json`), so results.csv
  exercises the L1 path; an L2-neighbour case is added to `sweep_cli.sh`
  with its row captured in Phase 0 as a second golden.
- Tests: `test_prefetch.cpp` splits into `prefetch/test_next_burst.cpp`,
  `prefetch/test_neighbour.cpp`, plus a cross-level test that runs each
  policy at the other level.
- Gate.

### Phase 4: factories and single-source tables
- Move `make_mapper` from `apps/app_support.h` into `layout/factory.h` +
  `src/layout/factory.cpp`, so all four factories live in the library.
- Split `apps/app_support.h` into `cli_args.h`, `oracle_io.h`, `output.h`.
- Add `enum_names.h`: one `name_of` / `parse` pair per enum
  (`LayoutKind`, `PolicyKind`, `PrefetchKind`, `Inclusion`). `config.cpp`, `stats.cpp`, `sweep.cpp` use it; the ternary at
  `config.cpp:560` and the `stats.cpp:344` ternary go away. RANDOM rejection
  collapses to `make_policy` only; `validate()` reports it by calling the
  same check.
- Gate. Output CSV must be byte-identical: the string tables are
  consolidated, not changed.

### Phase 5 (optional, not recommended now)
- Promote `set_index` to a virtual `IndexPolicy` with a `"set_index"` config
  key. Only worth it when a second index function (hashed/skewed) is
  actually planned. Adds a config key and a results column; needs a paper
  decision first.

## 4. What is deliberately out of scope
- No CMake. The GNU Makefile works; recursive wildcards are a 10-line change.
- No behaviour fixes from the atlas debt list (H2/H4/H6-H10, stale
  comments, `cli.py` never rebuilding a stale binary). Those are separate,
  gated changes; mixing them into moves would make the byte-identical gate
  meaningless.
- No Python restructure. `cli.py`/`grid.py`/`stream.py` are already thin.

## 5. Risks
- **Makefile wildcards are the main trap.** The Makefile comments (lines
  59-72) say a past move silently stopped header changes from triggering
  rebuilds. Phase 1 verifies with `touch` on a deep header followed by
  `make -n`.
- **`mutation_check.sh` and `compile_fail.sh` carry hardcoded path lists**
  and are not Makefile targets, so they do not fail loudly. Both run in the
  gate explicitly.
- **Atlas drift.** 99 path references in `cachesim_native.md`. Rewritten in
  the same commit as Phase 1.
- **Dirty worktree.** `neuro_cache-wcache` currently has uncommitted edits
  (`.gitignore`, `README.md`, `docs/REPRODUCE.md`, `scripts/pipeline.py`,
  `src/snn_scheduler/cli.py`, `src/util.py`, a deleted
  `scripts/subset_input_traces.py`). Those should be committed or set aside
  before Phase 0 so the gate compares like with like.

## 6. Decisions for the owner
1. Directory names and the layout/index split (section 2). In particular:
   is `index/` the right home for `cache_array.h` + `set_associative.h`, or
   should those sit in `core/`?
2. Flat `cachesim` namespace (recommended) vs sub-namespaces per directory.
3. Mirror the tree under `tests/` (recommended, Phase 2) vs keep tests flat.
4. Run Phases 1-4, or Phase 1 only first and review again.
5. Phase 5: skip unless hashed indexing is on the roadmap.
6. How to handle the current uncommitted edits before starting.
7. Prefetch key and column naming: keep the old `prefetch_policy` /
   `prefetch_distance` spelling as the canonical L1 name, or rename
   everything to `l1_prefetch_*` and rebase the results.csv baseline
   (header changes, data rows do not).
8. Prefetch interface: is the `PrefetchContext` / `PrefetchTarget` shape
   in Phase 3 acceptable, or should prefetchers return bursts rather than
   lines? (Lines are recommended: they make Neighbour-at-L1 and
   NextBurst-at-L2 definable without special cases.)
9. Folder names: section 2 (`index/`, `core/`) or the taxonomy-aligned
   names (`indexing/`, `miss_handling/`, `engine/`) proposed at the end of
   the taxonomy mapping file.

## 7. What each folder and file does (reference for the target tree)

Written against the current sources; "was X" names today's file. Line
numbers refer to today's files under `src/cachesim/native/`.

### How the pieces fit: life of one weight access

1. `trace/stream_trace` decodes one tile frame of the WCTS stream into
   `Burst{anchor, axis, count, stride}` records with local ticks
   (`src/stream_trace.cpp:176-306`).
2. `core/engine` schedules each core's first Issue event
   (`src/engine_core.cpp:55`). On Issue it asks the `layout/` mapper to
   `expand` the burst into a sorted list of `LineId`s (`engine_core.cpp:172`).
3. Each line becomes a `Request`, reserves the L1 `core/port`, and gets an
   L1Probe event (`engine_core.cpp:207-210`). The `prefetch/` L1 prefetcher
   may add prefetch probes for later bursts (`engine_core.cpp:216`).
4. L1Probe calls `core/cache_level::triage`. It asks the `index/`
   set-associative array to `probe`; the array computes
   `set = line % num_sets` through the mapper's `locate`
   (`src/set_associative.cpp:190`, `src/layout_common.h:154`).
5. Hit: `replacement/` policy `on_hit`, done. Miss: the `core/mshr` file
   merges into an existing entry, parks the request on a slot or line wait,
   or allocates and forwards to L2 (`src/cache_level.cpp:164-218`).
6. L2Probe repeats triage on the shared L2; the `prefetch/` L2 neighbour
   prefetcher may add lines (`src/engine.cpp:348-367`). A miss reserves DRAM
   and schedules an L2Fill after `l2_miss_latency`.
7. On fill, `cache_level::install` takes a free slot or asks the
   `replacement/` policy to `pick_victim` among the set's ways
   (`src/cache_level.cpp:237-251`). Inclusive mode back-invalidates L1s.
   The MSHR entry retires; one L1Fill per merged target, waiters reinjected.
8. When a core's pending lines reach zero, `engine_core::serve` charges the
   stall to one cause and schedules the next Issue. The last core to finish
   a tile schedules the Barrier; the driver advances the stream window.
9. `instrument/stats` turns `EngineStats` into one CSV row and checks the
   invariants.

### `types.h` (top level, unchanged)
Strongly typed scalars so ids, trace time and simulated time cannot be
mixed: `LineId`, `CoreId`, `SlotId`, `SetIndex`, `TagId`, `BurstIndex`,
`SimTime`, `LocalTick`, `RefusalOrder`, `EventSeq`, the sentinels `NoSlot`
/ `NoLine`, and the tensor geometry `Axis`, `Coord`, `Burst`, `WeightShape`.
Root of the include graph; depends on nothing.

### `layout/` : coordinate -> LineId (the paper's weight-layout axis)
Answers "which cache line holds weight (kh, kw, cin, cout)?" Resolved at
simulation time, so one trace replays under several layouts.
- `mapper.h` (was `layout.h`): abstract `AddressMapper` with `expand`
  (burst -> line ids), `locate` (line -> set, tag), `neighbour` (one block
  step along an axis, used by L2 prefetch), `num_lines`, `line_size_bytes`;
  `Placement`; `LayoutKind {BlockPack, SplitCin, KhkwSplit}`.
- `block_pack.h/.cpp`: default layout. One line = a `cin_block x cout_block`
  sub-block, flattened row-major over (kh, kw, cin_blk, cout_blk). Keys:
  `cin_block`, `cout_block`, `weight_bytes`.
- `split_cin.h/.cpp`: splits the cin block index into hi/lo digits so
  `cin_lo` lands at the bottom of the set index. Nesting
  [KH][KW][cin_hi][cout][cin_lo]. Key: `cin_lo_blocks` (-1 = l1 sets).
- `khkw_split.h/.cpp`: splits kernel position `pos = kh*KW+kw` into hi/lo
  (lo radix fixed at 8). Nesting [pos_hi][cout][cin][pos_lo]. No extra key.
- `src/layout/layout_common.h/.cpp` (private): shared checks and the
  `expand_burst<Mapper>` template (validate, call `line_of` per element,
  sort, dedup). Today also holds `locate_line`; that moves to `index/`.
- `factory.h/.cpp` (new, from `6f05fd2:apps/app_support.h:116`): `make_mapper(cfg,
  shape)` picks the concrete mapper from `cfg.layout`.

### `index/` : LineId -> (set, way)
Answers "which physical slot can hold this line?" Pure geometry, no
recency information.
- `set_index.h` (new; lifted from `layout_common.h:154-162`): the one set
  function used by every layout, `Placement{line % num_sets, line /
  num_sets}`. Also used by `bank_of` to pick an L2 bank. This is the hook
  for a hashed or skewed index later.
- `cache_array.h` (was `cache.h`): abstract `CacheArray` with `probe`,
  `free_slot`, `victim_candidates` (all ways of the set), `insert`,
  `invalidate`; `Candidate`, `InsertResult`.
- `set_associative.h/.cpp`: the concrete array for L1 and L2. Owns the
  per-slot `LineId` vector; slot = set*assoc + way. Constructor rejects
  sizes that are not a whole number of lines or sets. Keys: `l1_size_bytes`,
  `l1_assoc`, `l2_size_bytes`, `l2_assoc`.

### `replacement/` : which resident line to evict
Sees only `SlotId`s handed to it by the array; never computes sets.
- `policy.h` (base part of today's `policy.h` + the enum and factory from
  `stamp_policy.h:273-294`): abstract `ReplacementPolicy` with `on_hit`,
  `on_fill`, `on_invalidate`, `pick_victim(candidates)`, and the no-op
  `note_next_use` that only Belady overrides; `PolicyKind {LRU, FIFO,
  RANDOM, BELADY, RRIP, LFU}`; `make_policy(kind, num_slots, rrip_bits)`
  (RANDOM is refused here). Keys: `policy`, `l2_policy` (defaults to
  `policy`), `rrip_bits` in [1, 8].
- `stamp.h/.cpp`: `StampPolicy` keeps one int64 stamp per slot and evicts
  the lowest; `LruPolicy` re-stamps on hit, `FifoPolicy` does not.
- `belady.h/.cpp`: keeps next-use per slot, evicts the farthest. Needs an
  oracle attached; the apps refuse Belady without `--oracle`.
- `lfu.h/.cpp`: hit count per slot, reset on fill, evicts the lowest.
- `rrip.h/.cpp`: RRPV per slot; hit -> 0, fill -> max-1, invalidate -> max;
  victim = age the set until one reaches max, take the lowest slot there.
- `next_use.h`: `NextUseOracle`, header-only. Built from a WCALOG01 access
  log by a backward scan; answers "when is line L next referenced after its
  k-th occurrence". Also computes a fully associative OPT hit rate.

### `prefetch/` : what to fetch before demand (third policy axis)
Same shape as `replacement/`: one interface, concrete policies, one
factory, one instance per level chosen by config. The policy decides *which
lines*; the level and engine decide *how* they are issued (port, budget,
accounting), so the same policy works at L1 and L2.
- `prefetcher.h`: `PrefetchContext` (level, core, tile, triggering burst
  index and line, time, the mapper, the trace); `PrefetchTarget` (line +
  the burst it belongs to, used for timely / late / wasted accounting);
  abstract `Prefetcher` with `on_demand(ctx, out)`, `on_tile_start(core)`
  and the `on_issued` feedback that lets a cursor-based policy stop when
  the level ran out of budget; `PrefetchKind {None, NextBurst, Neighbour}`;
  `PrefetchParams {distance, axis, up, down}`; `make_prefetcher`.
- `none.h`: returns nothing.
- `next_burst.h/.cpp` (was the L1 half of `prefetcher.h`): on a demand
  burst k it returns the lines of bursts k+1..k+distance of the same core,
  expanded through the mapper, and keeps a per-core cursor so a burst is
  never prefetched twice. At L1 the engine caps it by
  `l1_mshrs - l1_demand_reserve` in flight; at L2 the same cap uses the
  L2 values.
- `neighbour.h/.cpp` (was the L2 half): on a demand line it returns
  `mapper.neighbour(line, axis, +-d)` for d = 1..distance, up and/or down.
  Works at L1 as well, where it becomes a spatial prefetcher into the
  private cache.
- Config keys: `l1_prefetch_policy`, `l1_prefetch_distance`,
  `l1_prefetch_axis`, `l1_prefetch_up`, `l1_prefetch_down`, and the `l2_`
  five; `prefetch_policy` / `prefetch_distance` stay as aliases for the
  `l1_` pair. Budgets: `l1_demand_reserve`, `l2_demand_reserve`.

### `core/` : the timing machinery (policy-agnostic)
- `request.h` (new, lifted from `mshr.h:49-205`): `Level {L1, L2}`,
  `WaitReason`, `StallCause {L1Slot, L1Line, L1Port, L2Slot, L2Line,
  L2Port, Channel, Barrier}`, and `Request` (core, line, burst, demand flag,
  issue time, refusal stamp, level, L1 MSHR pointer, stall cause). The
  three instrument headers include this instead of `mshr.h`.
- `mshr.h/.cpp`: `MshrFile(capacity, targets_per_entry, demand_reserve)`.
  `find`, `has_slot` (a prefetch needs `free > demand_reserve`), `allocate`,
  `add_target`, `push_line_wait` / `push_slot_wait`, `retire` (returns
  merged targets plus waiters sorted by refusal stamp). No clock. Keys:
  `l1_mshrs`, `l1_tgts_per_mshr`, `l1_demand_reserve`, and the `l2_*` trio.
- `port.h/.cpp`: `Port(ii, latency)`; `reserve(now)` returns the accept
  time and bumps `next_accept` by `ii`. Models L1 port, each L2 bank, DRAM.
  Keys: `l1_ii`, `l1_latency`, `l2_ii`, `l2_latency`, `l2_banks`, `dram_ii`,
  `l2_miss_latency`.
- `event.h`: `EventQueue` min-heap with total order (time, class, refusal
  age, core, seq); `EventClass {Fill, Barrier, Probe, Issue}` so fills run
  before probes at equal time.
- `cache_level.h/.cpp`: one level = array + policy + ports + MSHR file.
  `triage(r)` decides Hit / Merged / BlockedTargets / BlockedPool /
  Forwarded / Dropped-prefetch; `install(line)` takes a free slot or a
  victim and inserts; `bank_of`; `attach_next_use` for Belady. Built from
  `LevelParams`.
- `engine.h` + `engine.cpp` + `engine_core.cpp`: the whole machine. Owns
  one L1 per core, one shared L2, DRAM port, event queue, per-core
  `CoreState` and `EngineStats`. `engine_core.cpp` is the core side:
  `start_tile`, `on_issue`, `serve` (stall accounting), `barrier_arrive`,
  `issue_prefetch`. `engine.cpp` is the memory side: `on_l1_probe`,
  `on_l2_probe`, `on_l2_fill`, `on_l1_fill`, reinjection,
  `back_invalidate`, prefetch outcome accounting (timely / late / wasted /
  pollution), and the instrument hooks. `Inclusion {NonInclusive,
  Inclusive}` and `EngineParams` live here. Keys: `inclusion`,
  `l2_to_l1_latency`, `core_accept_ii`.

### `trace/` : reading the weight access stream
- `tile_trace.h` (was `trace.h`): abstract `TileTrace`: `n_tiles`,
  `n_cores`, `n_bursts(c,t)`, `burst(c,t,k)`, `local_tick`, `gap`,
  `tile_tail`. The engine only ever sees this interface.
- `stream_format.h`: the WCTS v2 wire format as constants and a header
  codec (`WCTRACE1`, 56-byte fixed header, 7 dims, 5 address fields,
  `decode_header` validates everything). Mirror of Python `stream.py`.
- `byte_source.h`: `ByteSource::read_exact`; `FdByteSource` (file, pipe,
  `fd:N`) and `MemByteSource` (tests).
- `stream_trace.h/.cpp`: `StreamingTileTrace`, a `TileTrace` over a
  one-tile sliding window. `advance()` reads the next frame (24-byte prefix,
  then per-core 28-byte `<q5i>` records) and checks the trailer after the
  last tile.

### `instrument/` : optional outputs and the results row
- `access_log.h`: binary WCALOG01 dump of every demand probe (level, core,
  line). Input to Belady's oracle. Flag `--access-log`.
- `cache_state_log.h`: CSV of every slot transition (fill / evict /
  invalidate) with per-set occupancy. Flags `--cache-state*`.
- `line_trace.h`: CSV of each residency episode of a line, fill to leave,
  with hit counts. Flags `--line-trace*`.
- `hist.h`: distinct addresses per core per tile; p50 and max feed the row.
- `stats.h/.cpp`: `RunStats` and `csv_columns()`, the results CSV schema;
  `check_invariants` (stall causes sum to total, hidden latency >= 0,
  prefetch outcomes + drops = issued); `oracle_row` for the scratchpad arm.

### Top level
- `config.h/.cpp`: `RunConfig` (every knob with its default and the derived
  `l1_num_sets` etc.), `parse_config` (flat JSON, unknown keys are errors),
  `parse_config_grid` (array, or `{base, axes}` cross product), `validate`
  (rules, warnings W_*, resolves the -1 sentinels), `to_engine_params`.
- `sweep.h/.cpp`: `BroadcastSweep(trace, mapper, configs)` runs N engines
  over one stream pass, one `step_tile` each per window move. All configs
  must share the layout, since they share one mapper.
- `enum_names.h` (new): one `name_of` / `parse` per enum, replacing the
  three copies in `config.cpp`, `stats.cpp`, `sweep.cpp`.

### `apps/`
- `cachesim_run.cpp`: one config + one trace -> one CSV row, with optional
  instruments and oracle files.
- `cachesim_sweep.cpp`: one grid + one trace -> one row per point from a
  single stream pass.
- `app_support.h` today; after Phase 3 split into `cli_args.h` (flag
  helpers, `uuid4`, `TraceFd`), `oracle_io.h` (`read_oracle_lines`,
  `build_oracles`, `attach_oracles`), `output.h` (`write_out`,
  `PaddingMeter`, `lines_per_burst`).

### `tests/`
- `check.h`: minimal assertion harness; failures do not abort.
- `engine_fixture.h`: `FakeTrace`, `LinearMapper`, event recorders, and
  parameter builders for engine-level tests.
- `mapper_conformance.h`: the `AddressMapper` contract checks every layout
  must pass.
- `stream_builder.h`: an independent WCTS writer for trace tests.
- `test_*.cpp`: one binary per file, mirrored into subfolders in Phase 2.
- `compile_fail.sh` (must-not-compile snippets, run by `make test`),
  `mutation_check.sh` (mutations must break a test), and the four CLI
  drivers `run_cli.sh`, `sweep_cli.sh`, `v1_pipe.sh`, `cout_golden.sh`
  (`make test-cli`), all fed by `examples/to_stream.py`.

### Python (`src/cachesim/`, unchanged by this plan)
- `cli.py`: `python -m cachesim {grid, sweep, run}`; builds the release
  binary if missing and forwards args.
- `grid.py`: builds the khkw sweep grid from `configs/cache/base.json` and
  `khkw_sweep.json`, one JSON file per `cin_block`.
- `stream.py`: producer-side WCTS v2 writer; must match `stream_format.h`.
- `examples/`: five fixture slices, `manifest.json` provenance, and
  `to_stream.py` for the CLI tests.

### Side findings (not part of this plan, logged for later)
- `bank_high_bits` in `LevelParams` is never set by `to_engine_params`, so
  L2 banking is always `set % banks`.
- `l2_policy` is not a results CSV column; two rows differing only in
  `l2_policy` are indistinguishable.

## 8. Taxonomy alignment

Moved to `docs/plans/2026-10-27-cachesim-taxonomy-mapping.md`.
