# Code atlas: `src/wcache/native` (wcache cache simulator)

Branch `wcache-rebuild-phase-a`, commit `8fa0916`. Written from code only: `.cpp`, `.h`, `.sh`,
`.py`, `Makefile`, `.json`. No `.md`, `.txt`, log, dump or notes file was read, so any design
rationale below is what the code's own comments state. Every path is relative to the repo root.
`N := src/wcache/native` is used as shorthand in citations only where noted; otherwise full paths.

There is **no `CMakeLists.txt`**. The build is `src/wcache/native/Makefile` (GNU make).

---

## 1. Top-down

### 1.1 Purpose

wcache is an event-driven, deterministic simulator of the weight-fetch side of a multi-core
accelerator. It reads one layer's weight-access trace (a "WCTS" binary stream of bursts per core per
tile) and replays it through a private L1 per core, one shared banked L2, and a pipelined DRAM
channel, with MSHR files, ports and optional prefetchers. Logical weight coordinates
`[KH][KW][CIN][COUT]` are mapped to cache lines at run time by a swappable `AddressMapper` (three
layouts), so one trace can be replayed under several memory layouts. The output is one CSV row per
configuration (cycles, stretch over the trace's own timeline, hit rates, stall breakdown, prefetch
outcomes, model-health counters). A tile barrier joins all cores between tiles, and each core issues
its next burst at `max(trace gap, core_accept_ii)` after its previous burst was served.

### 1.2 Entry points

Two programs, both `main()` in `src/wcache/native/apps/`, sharing `apps/app_support.h`. Exit codes:
0 ok, 2 usage error (`UsageError`, `app_support.h:48`), 1 any other exception.

**`wcache_run`** (`src/wcache/native/apps/wcache_run.cpp:434`): one config, one trace, one CSV row.
Flags parsed in `parse_args` (`wcache_run.cpp:151`); help text `kUsage` (`wcache_run.cpp:39`).

| flag | default | meaning |
|---|---|---|
| `--config PATH` | required | flat JSON object, `parse_config` |
| `--trace PATH` | required | WCTS stream; `-` = stdin, `fd:N` = open descriptor |
| `--out PATH` | `-` (stdout) | CSV destination (file is truncated, see finding H1) |
| `--header` / `--no-header` | on iff `--out` is a path that does not exist (`wcache_run.cpp:252`) | CSV header line |
| `--arm NAME` | `cache` | one of `cache, spad_oracle, spad_wcache, spad_nocsim` (`app_support.h:76`) |
| `--tier`, `--run-id`, `--git-commit` | empty, random UUIDv4, empty | identity columns |
| `--hist PATH` | off | per-(core,tile) distinct-address CSV |
| `--cache-state PATH` (+`-core/-tile/-limit N`, default -1) | off | every array fill/evict/invalidate |
| `--line-trace PATH` (+`-level l1\|l2\|both` default l1, `-core/-tile/-line/-limit N` default -1) | off | one row per residency episode |
| `--oracle PATH` | off | prior run's access log, builds per-core L1 + shared L2 next-use oracles (Belady) |
| `--l2-oracle PATH` | off | same file, L2 records only; mutually exclusive with `--oracle` |
| `--access-log PATH` | off | binary demand-reference log (input for `--oracle`) |
| `--oracle-only` | off | decode only; row with `total_cycles == tick_base_total`, no engine |

Narrowing flags without their file are refused (`wcache_run.cpp:195-205`).

**`wcache_sweep`** (`src/wcache/native/apps/wcache_sweep.cpp:259`): one grid, one trace read once,
N engines in lock-step, one row per grid point. Flags (`wcache_sweep.cpp:91`): `--config-grid PATH`
(required; JSON array of configs, or `{"base":{...},"axes":{key:[values]}}` cross product, first axis
slowest), `--trace` (required), `--out` (`-`), `--header`/`--no-header` (default **on**),
`--arm`, `--tier`, `--run-id`, `--git-commit`, `--hist`, `--oracle`, `--max-engines N` (default 256),
`--progress`. No instruments, no `--l2-oracle`, no `--oracle-only`.

**Build targets** (`src/wcache/native/Makefile`): `make` = `lib apps` in `build/fixture` (`-O0 -g`,
asserts live); `make test` = compile-fail driver + every `tests/test_*.cpp` binary;
`make test-cli` = builds apps, runs `run_cli.sh`, `sweep_cli.sh`, `v1_pipe.sh` (needs python3);
`make test-run` = test binaries only; `make release` = **library only** in `build/release`
(`-O2 -DNDEBUG`, `Makefile:205-206`); `make MODE=release apps` builds release programs; `make clean`.

### 1.3 Data flow (one `wcache_run`)

1. **Config text -> `RunConfig`**: `parse_config` (`src/wcache/native/src/config.cpp:399`), a strict
   JSON subset (integers and quoted strings only, unknown or duplicate key = error).
2. **Trace bytes -> `StreamHeader`**: `TraceFd` (`app_support.h:255`) -> `FdByteSource`
   (`include/wcache/byte_source.h:51`) -> `StreamingTileTrace` ctor reads and validates the header
   (`src/stream_trace.cpp:26`, `stream_format.h:205`).
3. **Header -> `WeightShape`** via `shape_of` (`src/stream_trace.cpp:353`).
4. **Validation**: a `BlockPackMapper` "probe" computes `lines_per_burst` (`app_support.h:163`), then
   `validate(cfg, lines_per_burst, warnings)` (`src/config.cpp:522`) resolves the `-1` sentinels
   (`l1_demand_reserve`, `l2_demand_reserve`, `cin_lo_blocks`, `l2_policy`) and refuses bad configs.
5. **Mapper**: `make_mapper` (`app_support.h:116`) builds `BlockPackMapper` / `SplitCinMapper` /
   `KhkwSplitMapper` -> `const AddressMapper&`.
6. **`RunConfig` -> `EngineParams`**: `to_engine_params` (`src/config.cpp:691`) -> two `LevelParams`.
7. **Engine**: `Engine(mapper, trace, params)` (`src/engine.cpp:33`) builds N L1 `CacheLevel`s, one L2
   `CacheLevel`, a DRAM `Port`, a `Prefetcher` and an `L2Prefetcher`.
8. **Tile loop** (`wcache_run.cpp:376-389`): `trace.advance()` decodes tile N into the one-tile window
   -> `DistinctAddressHistogram::observe`, `PaddingMeter::observe_tile` -> `engine.run_to_barrier()`
   runs events until tile N's barrier is next; then `engine.finish()`.
9. **Stats -> CSV**: `RunStats(id, cfg, hdr, engine.stats(), tile_origin(n_tiles), tick_base(n_tiles),
   padding, wall, hist.p50, hist.max)` (`src/stats.cpp:256`), `check_invariants()`, `csv_row()`;
   `write_out` (`app_support.h:286`).

`wcache_sweep` is the same with steps 4-9 per grid point, `BroadcastSweep` (`src/sweep.cpp:44`)
driving all engines over one window (`src/sweep.cpp:112`).

**Upstream connection (visible in code).** The WCTS producer is Python `src/tracegen.py`
(`stream_weight_trace`, `src/tracegen.py:633`; header writer `:522`, frame writer `:561`, trailer
`:591`). Drivers under `profiling/*/run_sweep.py` pipe `stream_weight_trace` output into
`src/wcache/native/build/release/wcache_sweep` (e.g. `profiling/0907_assoc/run_sweep.py:44`,
`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:45,227`). The corpus root is
`outputs/weight_traces` (`src/wcache/examples/make_examples.py:42`), which is git-ignored and absent
from this worktree. `--access-log` output is consumed by `profiling/0831_reuse_distance/reuse_tool`
(per `wcache_run.cpp:112`).

### 1.4 Key abstractions

```
             WCTS bytes                         RunConfig --validate--> EngineParams
                 |                                                           |
   ByteSource -> StreamingTileTrace : TileTrace           AddressMapper (BlockPack|SplitCin|KhkwSplit)
                 |   (one-tile window)                         |   expand(Burst)->[LineId]
                 v                                             |   locate(LineId,num_sets)->Placement
              Engine : PrefetchIssuer  <------------------------+   neighbour(line,axis,d)
   EventQueue<EventPayload> (total order: time,class,age,core,seq)
     |-- cores_[c] : CoreState (cursor, pending_lines, phase)
     |-- l1_[c] : CacheLevel ----+-- SetAssociativeArray : CacheArray (slots_[] of LineId)
     |-- l2_    : CacheLevel     +-- ReplacementPolicy (LRU|FIFO|Belady|LFU|RRIP), sized by num_slots
     |                           +-- Port[banks] (ii, latency)
     |                           +-- MshrFile (entries_ line->Mshr, slot_wait_, RefusalCounter&)
     |                           +-- NextUseOracle* (Belady only)
     |-- dram_ : Port
     |-- prefetcher_ : Prefetcher (None|NextBurst), l2_prefetcher_ : L2Prefetcher (None|Neighbour)
     |-- optional: CacheStateLog*, LineTrace*, AccessLog*   (observers, never change results)
     `-- stats_ : EngineStats  --> RunStats --> CSV row
```

The `Request` (one line of one burst, `include/wcache/mshr.h:117`) is the unit that travels. It lives
in `Engine::arena_` (a `std::deque`, stable addresses) with a free list (`engine.h:623,647`). An
`Mshr` (`mshr.h:207`) is one outstanding line per level; `targets` are satisfied directly by the
fill, `line_wait` are requests that found the target list full.

Strongly typed scalars (`include/wcache/types.h`): `LineId`, `CoreId`, `SlotId`, `SetIndex`,
`TagId`, `BurstIndex`, `SimTime`, `LocalTick`, `RefusalOrder`, `EventSeq` are distinct
`Tagged<Rep,Tag>` types with no default constructor and no narrowing constructor, so mixing them is
a compile error (checked by `tests/compile_fail.sh`).

### 1.5 One run, step by step (engine semantics)

Times are integer cycles (`SimTime`). Trace ticks (`LocalTick`) are offsets inside a tile.

1. `run_to_barrier` first call (`src/engine.cpp:128`): `tile_origin[0]=0`, `start_tile(0, 0)`.
2. `start_tile(t, now)` (`src/engine_core.cpp:55`): every core reset (cursor 0, phase Computing),
   prefetch cursor reset; a core with 0 bursts arrives at the barrier at once; otherwise an `Issue`
   event is scheduled at `now + local_tick(core, t, 0)` (the only absolute tick used).
3. `on_issue` (`src/engine_core.cpp:148`): checks `k == cursor` and `pending_lines == 0`; `expand`
   turns the burst into sorted distinct lines; `pending_lines = #lines`, phase Stalled; per line a
   demand `Request` reserves the L1 port and schedules `L1Probe` at `accept + l1_latency`. Then the
   prefetcher hook `on_demand_issue` runs.
4. `on_l1_probe` (`src/engine.cpp:254`) -> `CacheLevel::triage` (`src/cache_level.cpp:112`), probe
   order **array -> own MSHR -> MSHR pool**:
   - Hit: policy `on_hit`; `core_line_done`; request released.
   - Merged (entry exists, target list not full): subscribes, nothing scheduled.
   - BlockedTargets / BlockedPool: put on that entry's `line_wait` / the file's `slot_wait`, stamped
     with a global refusal counter value on first refusal (write-once).
   - Forwarded (allocated a new entry): request now holds the L1 entry (`mshr1`, `level = L2`), L2
     bank port reserved, `L2Probe` at `accept + l2_latency`.
   - A prefetch at issue is **dropped**, never queued: `DroppedArrayHit/Entry/NoSlot/Reserve`.
5. `on_l2_probe` (`src/engine.cpp:369`): same triage at L2. Hit -> `L1Fill` at `now +
   l2_to_l1_latency`. Forwarded -> `dram_.reserve(now)` -> `L2Fill` at `accept + l2_miss_latency`.
   An L2 demand miss (or demand hit on an L2-prefetched line) triggers `l2_prefetch_from`.
6. `on_l2_fill` (`src/engine.cpp:492`): install in L2 (free way first, then policy victim);
   back-invalidate the victim from every L1 if `inclusive`; retire the L2 entry; every target with an
   L1 entry gets `L1Fill` at `now + l2_to_l1_latency`; woken requests re-enter through their port.
7. `on_l1_fill` (`src/engine.cpp:555`): install in L1, update prefetch outcome bookkeeping, clear
   `mshr1` on every target, retire the L1 entry, `core_line_done` per demand target, return the
   prefetch credit per prefetch target, reinject wake list.
8. `core_line_done` (`src/engine_core.cpp:219`): `--pending_lines`; at 0 the burst is served
   (bursts are atomic) and the last line's `StallCause` is charged.
9. `serve` (`src/engine_core.cpp:241`): `want = tile_origin[t] + local_tick(0)` for burst 0, else
   `served_time + max(gap(k-1), core_accept_ii)`; `stall = now - want` (throws if negative);
   `fetch_latency += now - burst_anchor`. Next `Issue` at `now + max(gap(k), core_accept_ii)`, or
   barrier arrival after the last burst.
10. `barrier_arrive` (`src/engine_core.cpp:95`): countdown; the last core schedules `Barrier` at
    `now + tile_tail(t)` (`tile_tail = mac_cycles - max_tick`, must be >= 1).
11. `run_to_barrier` returns *before* dispatching a Barrier, so the driver can advance the shared
    window; the next call dispatches it. `on_barrier` (`src/engine_core.cpp:114`) sets
    `tile_origin[t+1] = now`, charges barrier slack per core, and starts tile t+1 or marks all Done.
12. When the queue empties: L1 prefetched-but-unused lines are charged as wasted, then
    `check_no_work_outstanding` throws on any deadlock (`src/engine.cpp:170`).

Tie-break classes at equal time (`include/wcache/event.h:43`): Fill(0) < Barrier(1) < Probe(2) <
Issue(3); then refusal stamp (older refused first, never-refused last), core id, schedule seq.
`total_cycles = tile_origin[n_tiles]`; `tick_base_total = sum(mac_cycles)`;
`stretch_cycles = total_cycles - tick_base_total`.

### 1.6 Config knobs (`RunConfig`, `include/wcache/config.h:27`) and defaults

| knob | default | knob | default |
|---|---|---|---|
| `cin_block` | 1 | `l1_mshrs` | 16 |
| `cout_block` | 16 | `l1_tgts_per_mshr` | 20 |
| `weight_bytes` | 1 | `l2_mshrs` | 20 |
| `layout` | `block_pack` (`split_cin`, `khkw_split`) | `l2_tgts_per_mshr` | 12 |
| `cin_lo_blocks` | -1 (= L1 sets, split_cin only) | `l1_demand_reserve` | -1 (= lines_per_burst) |
| `l1_size_bytes` | 8192 | `l1_latency` | 0 |
| `l1_assoc` | 8 | `l1_ii` | 1 |
| `l2_size_bytes` | 524288 | `l2_latency` | 10 |
| `l2_assoc` | 16 | `l2_to_l1_latency` | 0 |
| `policy` | `lru` (`fifo`,`belady`,`rrip`,`lfu`; `random` refused) | `l2_miss_latency` | 100 |
| `l2_policy` | unset -> `policy` | `l2_banks` | 1 |
| `rrip_bits` | 2 (1..8) | `l2_ii`, `dram_ii`, `core_accept_ii` | 1, 1, 1 |
| `inclusion` | `non_inclusive` (`inclusive`; `exclusive` refused) | `prefetch_policy` | `none` (`next_burst`) |
| `l2_prefetch_policy` | `none` (`neighbour`/`neighbor`) | `prefetch_distance` | 0 |
| `l2_prefetch_axis` | `cin` (`cout`,`kh`/`pos`,`kw`) | `l2_prefetch_distance` | 1 |
| `l2_prefetch_up` / `_down` | 1 / 1 (integers) | `l2_demand_reserve` | -1 (= lines_per_burst) |

Derived: `line_size_bytes = cin_block*cout_block*weight_bytes`; `l{1,2}_num_lines = size/line`;
`num_sets = num_lines/assoc` (`src/config.cpp:389-395`). Warnings returned by `validate`:
`W_MSHR_VS_LINES`, `W_FEW_SETS`, `W_CIN_LO_VS_SETS`, `W_PREFETCH_BUDGET`, `W_ZERO_II`
(`src/config.cpp:657-686`); `make_mapper` adds `W_CIN_LO_UNREACHABLE` (`app_support.h:138`).

### 1.7 WCTS v1 wire format (as decoded)

Little-endian, unaligned. Fixed header 56 bytes (`include/wcache/stream_format.h:44`): magic
`WCTRACE1`, u32 version=1, u32 header_bytes, i32 n_tiles, n_cores, weight_bytes, burst_dim (0..3),
burst_stride, burst_span, n_addr_fields (=5), n_spatial, n_dims (=7), identity_bytes; then 5 i32
field codes (must be 0..4 in order), n_spatial `(dim,factor)` pairs (ascending, product must equal
n_cores), 7 `(dim,extent)` pairs (ids 0..6: KH,KW,CIN,COUT,HO,WO,T), identity block of 4
NUL-terminated strings (arch, workload, layer, sample_idx). Per tile frame
(`src/stream_trace.cpp:14-16,176`): 24-byte prefix `i32 tile_index, i32 n_core_blocks, i64
mac_cycles, u64 payload_bytes`; per core block `i32 core_id (ascending), i32 n_bursts (>=1)`; per
burst 28 bytes `i64 local_tick (strictly ascending per core), i32 kh, kw, cin, run_start, run_end`.
Trailer 12 bytes: `i32 -1, u64 total_bursts` (`src/stream_trace.cpp:336`).

---

## 2. Bottom-up

Paths below are under `src/wcache/native/` unless a full path is given.

### 2.1 `include/wcache/` (headers)

**types.h**
- `detail::converts_without_narrowing<To,From>` `types.h:34-39`: SFINAE trait; `To{declval<From>()}`
  well-formed.
- `template<Rep,Tag> class Tagged` `types.h:50`: deleted default ctor (`:55`); single `explicit`
  ctor constrained to non-narrowing sources (`:82-84`); `get()` (`:86`). Comparisons only between the
  same instantiation (`:94-105`).
- Aliases: `LineId` i64 `:126`, `CoreId` i32 `:128`, `SlotId` i32 `:133`, `SetIndex` i64 `:150`,
  `TagId` i64 `:166`, `BurstIndex` i32 `:182`, `SimTime` i64 `:186`, `LocalTick` i64 `:190`,
  `RefusalOrder` i64 `:195`, `EventSeq` i64 `:210`. All signed by convention.
- Sentinels at the top of range so `<` sorts them last: `NoSlot`=INT32_MAX `:214`, `NoLine`=INT64_MAX
  `:222`, `NoRefusal`=INT64_MAX `:227` (so "refused beats fresh" is a single `<`).
- Arithmetic: `SimTime +,-,+=` `:231-233`; the one cross-type op `SimTime + LocalTick -> SimTime`
  `:241`; `LocalTick +,-` `:245-246`.
- `enum class Axis {KH,KW,CIN,COUT}` `:260` (order = row-major nesting, mappers depend on it).
- `struct Coord {kh,kw,cin,cout}` `:263`; `struct Burst {anchor, axis, count, stride}` `:284`;
  `struct WeightShape {KH,KW,CIN,COUT}` `:292`.
- `extent_on` `:300`, `coord_on` `:314`, `with_coord_on` `:329`, `axis_name` `:340`: switch over
  `Axis`, throw `logic_error` on unknown value.
- `std::hash<Tagged<..>>` `:355` (for `unordered_map<LineId,...>`).

**layout.h**
- `enum class LayoutKind {BlockPack, SplitCin, KhkwSplit}` `layout.h:41`.
- `struct Placement {SetIndex set_index; TagId tag;}` `:72`; identity `line == tag*num_sets + set`.
- `class AddressMapper` `:84` (abstract). Error vocabulary: `invalid_argument` malformed,
  `out_of_range` outside the layer, `logic_error` programmer error (`:88-103`).
  - `expand(const Burst&, vector<LineId>& out)` `:154`: APPENDS this burst's distinct lines, strictly
    increasing within one call; `count<1` or `stride<1` throws; all checks before the first append.
  - `locate(LineId, int64 num_sets) -> Placement` `:164`: range-checks before dividing.
  - `neighbour(LineId, Axis, int32 delta) -> optional<LineId>` `:181`: step `delta` BLOCKS along an
    axis, `nullopt` if it leaves the layer.
  - `num_lines()` `:184` (one past max id), `line_size_bytes()` `:190`,
    `line_size_terms(int64)` `:217` (diagnostic, default prints the number).

**cache.h**
- `struct Candidate {SlotId slot; LineId line;}` `cache.h:38` (line = NoLine if free).
- `struct InsertResult {bool evicted; LineId evicted_line;}` `:51`.
- `class CacheArray` `:68`: `probe` `:79` (const, not an access), `free_slot` `:84`,
  `victim_candidates` `:102` (REPLACES `out`), `insert` `:107`, `invalidate` `:121`,
  `num_slots` `:132`. Copy/move protected (`:162-166`).

**policy.h**
- `class ReplacementPolicy` `policy.h:37`: `on_hit` `:50`, `on_fill` `:58`, `on_invalidate` `:64`,
  optional `note_next_use(slot, next_use)` `:81` (default no-op; called right before
  `on_fill`/`on_hit` when an oracle is attached), `pick_victim(candidates)` `:106` (must not depend on
  candidate order; non-const).

**event.h**
- `enum class EventClass {Fill=0, Barrier=1, Probe=2, Issue=3}` `event.h:43`.
- `enum class EventKind {Issue, L1Probe, L2Probe, L2Fill, L1Fill, Barrier}` `:68`.
- `class_of(EventKind)` `:82`: Fills->Fill, Barrier->Barrier, probes->Probe, Issue->Issue.
- `struct EventKey {time, cls, age, core, seq}` `:111`; `key_less` `:125` lexicographic; total
  because `seq` is unique.
- `template<P> struct Event {key, kind, payload}` `:142`.
- `template<P> class EventQueue` `:155`: `schedule(time, kind, age, core, payload)` `:177` assigns
  `seq` itself, throws `logic_error` if `time < now`; `pop_min` `:193` sets `now`; `peek_min` `:210`;
  `empty`/`size` `:215-216`; `now` `:223`; `scheduled` `:229` (total events ever scheduled).
  `std::priority_queue` with reversed comparator (`:232-238`).

**trace.h**
- `class TileTrace` `trace.h:45` (abstract, read-only): `n_tiles` `:52`, `n_cores` `:53`,
  `n_bursts(core,tile)` `:57` (0 legal), `burst(core,tile,k)` `:64`, `local_tick` `:72` (offset in
  tile), `gap(core,tile,k)` `:87` (= tick[k+1]-tick[k]), `tile_tail(tile)` `:104`
  (= mac_cycles - max_tick).

**mshr.h**
- `enum class Level {L1, L2}` `mshr.h:49`; `enum class WaitReason {None, Slot, Line}` `:63`;
  `enum class StallCause {None, L1Slot, L1Line, L1Port, L2Slot, L2Line, L2Port, Channel, Barrier}`
  `:89`.
- `struct Request` `:117`: `core, line, burst, demand(=true), issued_at, refusal(=NoRefusal),
  reason, level(=L1, where to RE-ENTER), mshr1 (L1 entry once forwarded), reserved, on_wait_index,
  cause, line_resident_at_wake`. Invariant I6: `level==L2 <=> mshr1!=null` (except L2-originated
  prefetches).
- `struct Mshr` `:207`: `line, core (unused at L2), demand (promoted by a merging demand),
  pf_opened (fixed), first_request, targets, line_wait`.
- `class RefusalCounter` `:259`: `next()` `:264`, `issued()` `:269`. One per run, shared by all
  levels.
- `is_prefetch_at_issue(r)` `:299` = `!demand && mshr1==nullptr`.
- `mark_refused(r, reason, counter)` `:308`; `key_less(Request,Request)` `:313` (by refusal stamp).
- `struct RetireResult {targets; wake;}` `:321`.
- `class MshrFile` `:346`: ctor `(capacity, tgts_per_mshr, demand_reserve, counter&)` `:374`;
  `find` `:383`, `has_slot` `:396`, `allocate` `:414`, `add_target` `:427`, `push_line_wait` `:450`,
  `push_slot_wait` `:451`, `release_reservation` `:462`, `retire` `:480`, `collect_grants` `:494`,
  accessors `:496-509`. `entries_` is an `unordered_map` and is never iterated (`:533`).

**port.h**
- `class Port` `port.h:37`: ctor `(ii, latency)` `:57` (both >= 0); `reserve(now)` `:74` returns
  `max(now, next_accept)` and sets `next_accept = accept + ii`; `ii()` `:76`, `latency()` `:82`
  (callers add it), `next_accept()` `:90`. Reservations are never released.

**set_associative.h**
- `class SetAssociativeArray final : CacheArray` `set_associative.h:48`; ctor `(mapper,
  cache_size_bytes, associativity)` `:72`; five verbs `:88-92`; `num_slots` `:107`, `num_sets` `:108`,
  `associativity` `:109`; private `base_slot` `:131`. Slots of set s are `[s*assoc, s*assoc+assoc)`;
  stores full `LineId` per slot (`:160`).

**stamp_policy.h**
- `class StampPolicy : ReplacementPolicy` `stamp_policy.h:35` (abstract; one i64 stamp per slot,
  victim = smallest stamp, tie -> smallest slot), protected `stamp()` `:74`.
- `LruPolicy` `:96` (hit restamps), `FifoPolicy` `:105` (hit ignored).
- `BeladyPolicy` `:132`: per-slot next-use; victim = LARGEST next use, tie smallest slot.
- `LfuPolicy` `:177`: per-slot hit count, reset on fill; victim = smallest count.
- `RripPolicy(num_slots, bits=2)` `:218`: uint8 RRPV; hit->0, fill->max-1, invalidate->max.
- `enum class PolicyKind {LRU, FIFO, RANDOM, BELADY, RRIP, LFU}` `:273`.
- `make_policy(kind, num_slots, rrip_bits=2)` `:294`.

**next_use.h** (header-only)
- `class NextUseOracle` `next_use.h:40`: `kNever`=INT64_MAX `:42`; ctor from a reference sequence
  (one backward pass, then grouped by line) `:46`; `next_use(line, occurrence)` `:74` returns the
  position of the next reference after the `occurrence`-th one, or kNever and counts an overrun;
  `references` `:84`, `distinct_lines` `:85`, `overruns` `:86`; `optimal_hit_rate(lines, n_lines)`
  `:93` (fully-associative MIN, O(n * capacity)).

**prefetcher.h**
- `enum class PrefetchKind {None, NextBurst}` `prefetcher.h:34`.
- `class PrefetchIssuer` `:44` (implemented by `Engine`): `n_bursts_in_tile(core)` `:51`,
  `issue_prefetch(core, k, now) -> bool` `:63` (false = budget exhausted).
- `class Prefetcher` `:74`: `on_demand_issue(mem, core, k, now)` `:82`, `on_tile_start(core)` `:92`.
- `NoPrefetcher` `:108`; `NextBurstPrefetcher(distance>=1, n_cores)` `:122,128`, `distance()` `:133`,
  `pf_cursor(core)` `:143`.
- `make_prefetcher(kind, distance, n_cores)` `:156`.
- `enum class L2PrefetchKind {None, Neighbour}` `:173`; `class L2Prefetcher` `:175` with
  `suggest(mapper, line, out)` `:185` (appends); `NoL2Prefetcher` `:200`;
  `NeighbourL2Prefetcher(axis, distance>=1, up, down)` `:213,218` + accessors `:223-226`;
  `make_l2_prefetcher` `:235`.

**cache_level.h**
- `enum class TriageOutcome {Hit, Merged, BlockedTargets, BlockedPool, Forwarded, DroppedArrayHit,
  DroppedEntry, DroppedNoSlot, DroppedReserve}` `cache_level.h:74`; `is_dropped` `:88`.
- `struct LevelParams` `:105`: `cache_size_bytes, associativity, policy, rrip_bits, latency, ii,
  banks, bank_high_bits, mshrs, tgts_per_mshr, demand_reserve`.
- `class CacheLevel` `:138`: ctor `(Level, mapper, LevelParams, RefusalCounter&)` `:151`;
  `triage(r, granted)` `:176`; `install(line)` `:200`; `bank_of(line)` `:209`; `level`, `array`,
  `policy` `:211-214`; `attach_next_use(oracle)` `:227`, `next_use_oracle` `:228`; `mshrs` `:229-230`;
  `port(bank)` `:231`; `banks` `:232`; `num_sets` `:233`. Holds Belady occurrence counters
  `occurrence_` and `pending_next_use_` (`:244,250`).

**engine.h**
- `enum class Inclusion {NonInclusive, Inclusive}` `engine.h:59`; `enum class Phase {Computing,
  Stalled, AtBarrier, Done}` `:68`.
- `struct CoreState` `:77`: `tile, cursor, phase, pending_lines, issued_at, burst_anchor,
  barrier_arrival, served_time`.
- `struct EngineStats` `:128`: per-core vectors `core_stall, fetch_latency, stall_l1_slot ...
  stall_barrier, stall_total, pf_outstanding`; scalar counters for prefetch outcomes (L1 `:205-224`,
  L2 `:251-262`), `l1/l2_hits/accesses` `:239-240`, `dram_accesses` `:263`, health counters
  `hits_downgraded_to_miss, max_wait_depth, events` `:270-278`, MSHR occupancy samples `:283-284`.
- `struct EventPayload {Request* req; Mshr* entry; BurstIndex burst; int32 tile;}` `:302`;
  `using EngineQueue = EventQueue<EventPayload>` `:309`.
- `struct EngineParams` `:325`: `l1, l2` LevelParams, `l2_to_l1_latency, dram_ii, l2_miss_latency,
  core_accept_ii, inclusion, prefetch_policy/distance, l2_prefetch_*`. No validation by design.
- `class Engine final : PrefetchIssuer` `:362`: ctor `:369`; `run` `:378`; `run_to_barrier` `:399`
  (returns pending barrier's tile or -1); `step_tile` `:411`; `finish` `:423`; `tile_origin(t)` `:429`
  (size n_tiles+1); `core` `:431`; `stats` `:432`; `queue` `:433`; `l1(c)` `:435`; `l2` `:436`;
  `prefetcher` `:437`; `set_cache_state_log` `:453`, `set_line_trace` `:454`, `set_access_log` `:460`;
  overrides `n_bursts_in_tile` `:463`, `issue_prefetch` `:464`. Private handlers listed `:468-568`.
- `as_duration(LocalTick) -> SimTime` `:675`: the one trace-gap-to-duration crossing.

**config.h**
- `struct RunConfig` `config.h:27` (fields in 1.6) with `line_size_bytes, l1_num_lines, l1_num_sets,
  l2_num_lines, l2_num_sets` `:109-113`.
- `struct Warning {code, message}` `:119`.
- `parse_config(json)` `:132`, `parse_config_grid(json)` `:153`, `validate(cfg&, lines_per_burst,
  warnings&)` `:163` (mutates cfg), `to_engine_params(cfg)` `:168`.

**stream_format.h** (namespace `wcache::stream`, header-only)
- Constants `kMagic` `:39`, `kFormatVersion` `:40`, `kFixedHeaderBytes`=56 `:44`, `kEndMagic`=-1 `:45`,
  `kAddrFields`=5 `:46`, `kDims`=7 `:47`; `enum DimCode` `:51`, `enum FieldCode` `:52`;
  `kHostIsLittleEndian` `:54` (requires `__BYTE_ORDER__`, `:33-35`).
- `read_le<T>` `:58`, `write_le<T>` `:71`; `axis_of(int32)` `:84` (only 0..3), `code_of(Axis)` `:96`.
- `struct StreamHeader` `:100`; `detail::identity_block` `:123`, `detail::append_le` `:134`,
  `detail::Cursor` `:143`.
- `encode_header(h, out)` `:171` (no validation; for tests); `decode_header(buf, len)` `:205`
  validates every field (see 1.7).

**byte_source.h** (header-only)
- `class ByteSource` `byte_source.h:28`: `read_exact(dst, n)` `:36` returns false only on clean EOF,
  throws on partial read.
- `FdByteSource(int fd)` `:51` (does not own fd; retries EINTR/short reads); `MemByteSource` `:81`
  with `consumed()` `:100`.

**stream_trace.h**
- `class StreamingTileTrace final : TileTrace` `stream_trace.h:31`: ctor reads header `:37`; the
  seven `TileTrace` overrides `:40-46` (all except `n_tiles/n_cores/tile_tail` answer only for the
  window tile); `window_tile()` `:51` (-1 before first advance); `advance()` `:58`;
  `distinct_addresses(core)` `:76`; `header()` `:79`; `mac_cycles(t)` `:82`; `tick_base(t)` `:86`
  (prefix sum of mac_cycles, defined up to streamed+1).
- `shape_of(StreamHeader) -> WeightShape` `:119`.

**access_log.h** (header-only)
- `struct AccessRecord {u8 level, core, demand, pad; u32 line}` `access_log.h:65`, 8 bytes
  (`static_assert` `:72`).
- `class AccessLog(ostream&)` `:74,77`: `write_header` `:87` (u64 magic `0x5743414C4F473031`
  "WCALOG01", `:136`), `observe(level, core, line)` `:95` (throws if line > 2^32-1 or core > 255,
  `:137-138`), `records` `:127`, `flush` `:129`; batch 65536 records (`:143`); host-endian raw write.

**cache_state_log.h** (header-only)
- `class CacheStateLog` `cache_state_log.h:37`: ctor `(out, n_cores, l1_sets, l2_sets, l1_assoc,
  l2_assoc, core, tile, max_rows)` `:44`; `write_header` `:59` (CSV
  `time,tile,level,core,set,way,action,line,tag,ways_used`); `record(action, now, tile, level, core,
  line, set, tag, way)` `:74` (occupancy updated BEFORE filtering); `wants` `:89`; `written` `:95`;
  `truncated` `:96`; private `bump` `:104` (action starting with 'f' = fill).

**line_trace.h** (header-only)
- `class LineTrace` `line_trace.h:37`: ctor `(out, want_l1, want_l2, core, tile, line, max_rows)`
  `:60`; `write_header` `:70`; `on_fill` `:102` (filters applied here); `on_hit` `:118`; `on_leave`
  `:127`; `flush(now)` `:147` (emits open episodes as `end_of_run`, sorted by key); `written` `:159`;
  `truncated` `:160`; `still_open` `:161`; private `key` `:179` packs `(line<<7)|((core+1)<<1)|level`.
  CSV columns `:98-99`. Rows are in episode END order.

**hist.h** (header-only)
- `class DistinctAddressHistogram(StreamHeader)` `hist.h:35,40`: `observe(trace)` `:47` once per
  tile; `write_csv` `:56`; `p50` `:73` (nearest rank `min(n-1, floor(q*n))`); `max` `:75`; `samples`
  `:82`.

**stats.h**
- `struct RowIdentity {run_id, git_commit, arm="cache", tier}` `stats.h:24`.
- `csv_columns()` `:38` (single schema), `csv_header()` `:41`.
- `class RunStats` `:69`: ctor `:71`, `csv_row` `:80`, `check_invariants` `:92`.
- `oracle_row(id, cfg, hdr, tick_base_total)` `:111`.

**sweep.h**
- `class BroadcastSweep` `sweep.h:31`: `TileObserver` `:37`; ctor `(trace, mapper, configs,
  max_engines)` `:53`; `run(on_tile)` `:60`; `size` `:62`; `engine(i)` const `:63` / mutable `:71`;
  `config(i)` `:72`; `wall_seconds(i)` `:77` (time inside engine dispatch only).

**layout mappers**: see 2.2 with their sources (`block_pack.h`, `split_cin.h`, `khkw_split.h`).

### 2.2 `src/` (library `libwcache.a`)

**config.cpp**
- `fail(what, pos)` `config.cpp:29`: `invalid_argument("config: ... at byte N")`.
- `struct Value` `:33`; `class Reader` `:39` (`skip_space`, `at`, `expect`, `expect_end`, `pos`,
  `read_string` (no escapes) `:70`, `read_value` (integer or string; rejects `.`/`e`) `:85`).
- Key tables `kI32Fields` `:135`, `kI64Fields` `:153`; `to_i32` `:167`, `to_i64` `:176`,
  `enum_text` `:181`.
- `assign(cfg, key, value, pos)` `:186`: the single key dispatcher used by both parsers; enum
  spellings `:203-302`; unknown key fails `:304`.
- `reject` `:309`, `reject_below_one` `:313`, `reject_negative` `:319`, `check_level_geometry`
  `:325` (size >= one set, whole lines, whole sets), `warn` `:344`.
- `read_object_into(reader, cfg)` `:353` (duplicate keys refused); `struct GridAxis` `:379`.
- `RunConfig::line_size_bytes` etc. `:389-395` (integer division; validated later).
- `parse_config` `:399`; `parse_config_grid` `:409` (array form `:413-430`; base/axes form,
  mixed-radix enumeration with last axis fastest `:503-516`).
- `validate` `:522`: positivity `:524-542`; geometry `:544-546`; `cin_lo_blocks` resolved only under
  split_cin, must stay -1 otherwise `:552-571`; `l2_policy` follows `policy` if unset `:573`; random
  refused `:587,596`; rrip_bits in [1,8] `:593`; `lines_per_burst <= l1_mshrs` `:599`;
  `core_accept_ii >= 1` `:603`; L2 prefetch consistency `:614-626`; `l2_demand_reserve` resolved to
  lines_per_burst, must be `< l2_mshrs` `:630-639`; `next_burst` needs distance > 0 `:641`;
  `l1_demand_reserve` resolved, must be `< l1_mshrs` `:646-655`; warnings `:657-686`.
- `to_engine_params` `:691`: copies fields; L1 has 1 bank; throws if not validated.

**engine.cpp** (loop, memory-side handlers, inclusion, instruments)
- anonymous `engine_error` `:18`, `idx` `:22`, `is_blocked` `:27`.
- `Engine::Engine` `:33`: needs n_cores >= 1; `l1_.reserve` before emplace (CacheLevel holds refs)
  `:49-52`; sizes per-core stats; `tile_origin_` sized n_tiles+1 `:84`.
- `tile_origin` `:87`, `core` `:91`, `l1` `:93`.
- `acquire` `:97` (reuse from free list, whole-struct assign), `release` `:112` (throws if still
  referenced).
- `run_to_barrier` `:128`, `run` `:156` (= loop of run_to_barrier), `step_tile` `:161`, `finish`
  `:163` (= run), `check_no_work_outstanding` `:170`, `dispatch` `:196` (increments `events`).
- `reinject` `:217` (re-enters at `r.level` through that level's port, keeps original stamp),
  `reinject_all` `:238`.
- `on_l1_probe` `:254`, `l2_prefetch_from` `:348` (acquire `demand=false`, `level=L2`, burst 0,
  stamp NoRefusal), `on_l2_probe` `:369`, `on_l2_fill` `:492` (L2 tag set `l2_prefetched_` update
  `:505-518`), `on_l1_fill` `:555`.
- Prefetch accounting: `demand_anchor_on_probe` `:624` (timely / pollution), `note_prefetch_resident`
  `:648`, `note_line_left_l1` `:652` (wasted), `close_out_prefetch_stats` `:660`.
- Instruments: `current_tile` `:678` (core 0's tile), `way_of` `:682` (`slot % assoc`), `note_fill`
  `:697`, `note_leave` `:711`, `note_hit` `:722`.
- `back_invalidate(line, now)` `:730`: scans all L1s by core id, invalidates + `on_invalidate`.

**engine_core.cpp** (core state machine, barrier, prefetch sink)
- `step_after(c, tile, k)` `:48` = `max(gap_k, core_accept_ii)`.
- `start_tile` `:55`, `barrier_arrive` `:95`, `on_barrier` `:114`, `on_issue` `:148` (re-throws a
  mapper `out_of_range` with tile/tick/core/burst context `:186-189`), `core_line_done` `:219`
  (prefetch completes nobody), `serve` `:241`.
- `n_bursts_in_tile` `:336`; `issue_prefetch` `:341`: budget `cap = l1_mshrs - l1_demand_reserve`
  per core; stops mid-burst when exhausted (already-issued lines of that burst stay in flight).

**cache_level.cpp**
- `refuse_if_waiting` `:32`; `charge_path(r, cause)` `:48` sets cause only if never refused.
- `CacheLevel::CacheLevel` `:54`: array first, then `make_policy` sized by `num_slots`, then
  `banks` ports; `sets_per_bank` clamped >= 1 `:95-96`.
- `bank_of` `:99`: 1 bank -> 0; else low bits `set % banks` or high bits `set / sets_per_bank`.
- `triage` `:112`: Belady occurrence consumed on every demand probe `:133-140`; array hit `:143-161`;
  matching entry `:164-187`; no slot `:190-205` (prefetch: DroppedReserve if free > 0 else NoSlot);
  primary miss `:208-219`.
- `install` `:222`: throws if already resident; free slot first, else `pick_victim`; passes the
  stored next-use to Belady; `on_fill`.

**mshr.cpp**
- `RefusalCounter::next` `:49`; `mark_refused` `:61` (write-once).
- `MshrFile::MshrFile` `:68` (capacity>=1, tgts>=1, 0<=reserve<=capacity).
- `live` `:89`, `slot_wait_depth` `:91`, `find` `:93`.
- `has_slot` `:98`: reserved requests always admitted; else `free = cap - live - reserved`; prefetch
  at issue needs `free > demand_reserve`, others `free > 0`.
- `allocate` `:117` (primary is first target; spends its reservation), `add_target` `:158`
  (`demand |= r.demand`), `push_line_wait` `:168`, `push_slot_wait` `:177` (both refuse prefetches),
  `release_reservation` `:186`.
- `collect_grants` `:203`: grant oldest slot waiters while `live + reserved < capacity`
  (O(n) min_element per grant).
- `retire` `:219`: copies targets + line waiters, marks line waiters `line_resident_at_wake`, erases,
  collects grants, stable-sorts wake list by refusal stamp.

**port.cpp**: `Port::Port` `:32` (non-negative), `Port::reserve` `:54` (three lines).

**set_associative.cpp**
- `slot_or_reject` `:44`; ctor `:86` (order: size>=1, assoc>=1, line>=1, size % line == 0, lines <=
  INT32_MAX, assoc <= lines, lines % assoc == 0); `base_slot` `:190` (via `mapper.locate`).
- `probe` `:209`, `free_slot` `:221` (lowest free way), `victim_candidates` `:240` (clears then
  fills, whole set), `insert` `:264` (slot range-checked, line not), `invalidate` `:274`.

**stamp_policy.cpp**
- `kNeverStamped = 0` `:27` (counter starts at 1). `StampPolicy` ctor `:31`, `index_or_reject` `:50`,
  `stamp` `:60`, `on_fill` `:65`, `on_invalidate` `:72` (back to never-stamped), `pick_victim` `:76`.
- `LruPolicy::on_hit` `:102`; `FifoPolicy::on_hit` `:107` (empty).
- `BeladyPolicy` ctor `:118`, `index_or_reject` `:126`, `on_hit/on_fill` `:140-141` (range check
  only), `on_invalidate` `:143`, `note_next_use` `:147`, `pick_victim` `:151`.
- `LfuPolicy` ctor `:172`, `on_hit` `:189`, `on_fill` `:195` (reset 0), `on_invalidate` `:199`,
  `pick_victim` `:203`.
- `RripPolicy` ctor `:234` (`max = 2^bits-1`, `insert = max-1`, initial all max), `on_hit` `:262`,
  `on_fill` `:264`, `on_invalidate` `:270`, `pick_victim` `:274` (one aging step `max - highest`
  applied to all candidates, then smallest slot at max).
- `make_policy` `:307` (RANDOM throws `invalid_argument`).

**prefetcher.cpp**
- `NoPrefetcher` `:10-11`; `NextBurstPrefetcher` ctor `:13`, `pf_cursor` `:27`, `on_tile_start`
  `:31` (cursor 0), `on_demand_issue` `:39`: cursor = max(cursor, k+1); issue bursts while `cursor <=
  k+d` and `< n_bursts`; on budget failure returns WITHOUT advancing (retry next issue).
- `make_prefetcher` `:64`.
- `NoL2Prefetcher::suggest` `:92`; `NeighbourL2Prefetcher` ctor `:94`, `suggest` `:109` (order: +1,
  -1, +2, -2, ...); `make_l2_prefetcher` `:127`.

**block_pack.cpp** (`BlockPackMapper`, header `include/wcache/block_pack.h:42`)
- Nesting `[KH][KW][cin_blk][cout_blk]`, cout innermost. Strides (`:229-234`): COUT 1, CIN
  `n_cout_blocks`, KW `n_cin_blocks*n_cout_blocks`, KH `KW*stride_KW`.
- Helpers: `reject` `:41`, `reject_range` `:56`, `positive_or_reject` `:66`, `checked_mul` `:82`
  (overflow -> invalid_argument), `blocks_covering` `:105` (ceil), `block_size_on` `:119` (KH,KW = 1).
- Ctor `:135` (header `:64`): extents >= 1, blocks >= 1; padding allowed (block need not divide);
  `line_size_bytes = cin_block*cout_block*weight_bytes` `:188`; `num_lines = KH*KW*ncb*nkb` `:203`.
- `line_stride(Axis)` `:246`, `block_len(Axis)` `:262` (KH,KW raw; CIN,COUT block counts),
  `line_of(Coord)` `:272` (checks each coordinate against the shape), `expand` `:359` (checks last
  element, walks, sort+unique, append), `locate` `:398` (`set = id % num_sets`, `tag = id /
  num_sets`), `line_size_terms` `:421`, `neighbour` `:430`. Accessors in header `:159-164`.

**split_cin.cpp** (`SplitCinMapper`, header `include/wcache/split_cin.h:108`)
- Nesting `[KH][KW][cin_hi][cout_blk][cin_lo]`, `cin_lo = cin_blk % n_cin_lo` innermost, so with
  `n_cin_lo = L1 sets` the L1 set index is the CIN digit. `enum Digit` header `:97`.
- Ctor `:106` (extra arg `n_cin_lo >= 1`); `n_cin_hi = ceil(ncb / n_cin_lo)` `:157`; strides
  `:214-221`; `num_lines` = max id + 1 (`:240-245`), may be below the radix product (holes when
  n_cin_lo does not divide ncb).
- `digit_stride` `:265`, `digit_radix` `:277`, `block_len` `:294`, `line_of` `:306`, `expand` `:410`
  (same body as BlockPack), `locate` `:454`, `line_size_terms` `:487`, `neighbour` `:495` (CIN step
  recombines the two digits). Accessors header `:187-194`.

**khkw_split.cpp** (`KhkwSplitMapper`, header `include/wcache/khkw_split.h:70`)
- Nesting `[pos_hi][cout_blk][cin_blk][pos_lo]`, `pos = kh*KW + kw`, split at `n_pos_lo =
  min(kPosLoRadix=8, KH*KW)` (`khkw_split.h:89`, `khkw_split.cpp:75`). `enum Digit` header `:79`.
- Ctor `:50`; strides `:81-87`; `num_lines` = max id + 1 `:104-112`.
- `digit_stride` `:120`, `digit_radix` `:131`, `block_len` `:141`, `line_of` `:151`, `expand` `:188`,
  `locate` `:220`, `line_size_terms` `:233`, `neighbour` `:241` (KH/KW step via pos).

**stream_trace.cpp**
- Constants: frame prefix 24, burst record 28, trailer 12 bytes `:14-18`.
- Ctor `:26` (reads fixed header, peeks `header_bytes` at offset 12, reads the rest, decodes).
- `n_tiles` `:59`, `n_cores` `:61`, `require_window` `:63`, `require_core` `:72`,
  `require_streamed` `:79`, `n_bursts` `:87`, `burst` `:94`, `local_tick` `:105`, `gap` `:116`
  (k in [0, n-1)), `distinct_addresses` `:130` (unique `(kh,kw,cin,cout,count)` tuples), `tile_tail`
  `:157`, `mac_cycles` `:162`, `tick_base` `:167`.
- `advance` `:176`: decodes one frame into reused buffers; validates tile index, core ordering,
  n_bursts >= 1, strictly increasing ticks, non-empty runs, payload length, `tail = mac - max_tick
  >= 1`. Anchor built at `:302-303`; `Burst{anchor, header.burst_dim, run_end - run_start,
  header.burst_stride}`.
- `read_trailer` `:336`; `shape_of` `:353`.

**stats.cpp**
- `name_of` overloads for PolicyKind `:16`, LayoutKind `:28`, Inclusion `:37`, PrefetchKind `:45`;
  `total` `:53`; `quantile` `:60`.
- `class Row` `:71`: `str` (refuses `, " \n \r`) `:73`, `i64` `:86`, `f64` (`%.6f`) `:91`, `ratio`
  (empty cell when denominator 0) `:101`, `blank` `:109`, `blank_rest` `:115`, `take` `:120`; every
  cell checked against the schema position (`expect` `:130`).
- `emit_identity` `:144`, `emit_config` `:156`, `emit_headline` `:195`.
- `csv_columns` `:203` (112 columns; `rrip_bits` appended last `:243`), `csv_header` `:247`.
- `RunStats::RunStats` `:256`: derived `dram_bytes = dram_accesses*line_size` `:291`,
  `hidden_latency = fetch_latency_sum - core_stall_sum` `:275`, `pf_coverage = (timely+late) /
  demand_bursts` `:333`, `l2_pf_coverage = l2_pf_timely / l2_accesses` `:359`,
  `port_bound_threshold = miss_frac * l2_miss_latency * l2_banks / l2_ii` `:368-376`, MSHR
  occupancy p50/p95/max `:378-390`, `events_per_cycle` `:395`.
- `csv_row` `:404`; `check_invariants` `:413`: stall causes sum == stall_total, hidden_latency >= 0,
  L1 prefetch outcomes + drops == pf_issued.
- `oracle_row` `:447`: identity + config + `total_cycles = tick_base_total`, rest blank.

**sweep.cpp**
- `layout_text` `:14`; `rethrow_with_index` `:27` (prefixes "sweep: configuration i:" preserving
  exception type).
- Ctor `:44`: non-empty grid, `size <= max_engines`, all points share `cin_block, cout_block,
  weight_bytes, layout, cin_lo_blocks` `:76-91`, mapper line size matches `:93`, then builds engines.
- `run` `:112`: per tile `advance` -> observer -> `step_tile` on each engine (timed); then `finish`
  each. Accessors `:146-152`.

### 2.3 `apps/`

**app_support.h** (namespace `wcache::app`)
- `UsageError` `:48`; `value_of` `:52`; `int_value_of` `:60` (whole-string integer); `check_arm`
  `:76`; `uuid4` `:86` (`std::random_device`, unseeded by design).
- `make_mapper(cfg, shape, warnings)` `:116`.
- `lines_per_burst(mapper, hdr)` `:163`: expands the widest burst `{origin, burst_dim, burst_span,
  burst_stride}` and counts lines. Both apps pass a BlockPackMapper for any layout (`:157-161`).
- `class PaddingMeter` `:184`: `observe(burst)` `:197`, `observe_tile(trace)` `:215`, `fraction()`
  `:226` = `(lines_touched*cin_block*cout_block - elements_touched) / (lines_touched*...)`.
- `class TraceFd(spec)` `:255`: `-`, `fd:N`, or path (owned, closed in dtor); `get` `:275`.
- `path_exists` `:282`; `write_out(path, text)` `:286` (`-` = stdout; else truncating ofstream).
- `read_oracle_lines(path, n_cores, l1_by_core*, l2_lines&)` `:326`: reads an AccessLog file;
  demand records only; per-core L1 lists + one L2 list.
- `struct OracleSet {l1 vector, optional l2, attached}` `:380`; `build_oracles` `:390`;
  `attach_oracles(oracles, cfg, engine)` `:420` (only levels whose policy is Belady);
  `report_oracles` `:441`; `report_overruns` `:478` (warns if `max_wait_depth != 0` with Belady:
  re-probes shift occurrence indices).

**wcache_run.cpp**: `kUsage` `:39`, `struct Options` `:119`, `parse_args` `:151`, `run` `:219` (steps
in 1.3; Belady oracle checks `:314-344`; instruments `:285-369`; truncation notes `:395-410`),
`main` `:434`.

**wcache_sweep.cpp**: `kUsage` `:34`, `struct Options` `:77`, `parse_args` `:91`, `read_file` `:123`,
`run` `:131` (validate every point with grid[0]'s probe `:148-170`; one mapper from grid[0]
`:178`; shared oracles `:197-208`; observer does hist/padding/progress `:209-219`; rows `:240-247`),
`main` `:259`.

### 2.4 `tests/` (one line each)

Harness and shared fixtures:
- `check.h`: minimal check harness (no gtest, to avoid a conda shared-object dependency); every
  failure prints and the run continues.
- `engine_fixture.h`: Phase C fixtures: `FakeTrace`, `LinearMapper`, an event log and an in-run
  invariant probe.
- `mapper_conformance.h`: interface checks parameterised over `const AddressMapper&` (append-only,
  strictly increasing, nothing appended on throw, exception types).
- `stream_builder.h`: an independent second WCTS writer used by the reader tests.

Unit test binaries (`Makefile:57`, one binary per `tests/test_*.cpp`):
- `test_types.cpp`: Tagged scalars and tensor geometry helpers.
- `test_layout.cpp`: `Placement` and `AddressMapper` contracts via conformance checks.
- `test_block_pack.cpp`: BlockPackMapper construction, validation, strides, `line_of`, `expand`,
  `locate`.
- `test_split_cin.cpp`: SplitCinMapper end to end, including the "count is layout-independent"
  property `lines_per_burst` relies on.
- `test_khkw_split.cpp`: KhkwSplitMapper flatten, per-core set coverage, interface contracts.
- `test_neighbour.cpp`: `neighbour` on all three mappers, checked against `line_of` of the
  neighbouring coordinate.
- `test_cache.cpp`: `CacheArray` interface shape, `Candidate`, `InsertResult`.
- `test_set_associative.cpp`: SetAssociativeArray geometry refusals and the five verbs.
- `test_stamp_policy.cpp`: ReplacementPolicy and LRU/FIFO (plus Belady/LFU/RRIP) behaviour and
  order independence.
- `test_port.cpp`: `Port` reservation arithmetic.
- `test_event.cpp`: EventQueue total order and determinism.
- `test_mshr.cpp`: MshrFile entries, targets, waits, refusal counter, grant loop.
- `test_cache_level.cpp`: CacheLevel triage table branch by branch.
- `test_engine.cpp`: event loop handlers, core state machine, tile barrier, inclusion.
- `test_prefetch.cpp`: prefetch interface, `none` vs `next_burst`, drop rules.
- `test_config.cpp`: RunConfig parse, defaults, validation rules.
- `test_stats.cpp`: CSV schema, RunStats, invariants, oracle row.
- `test_stream_format.cpp`: WCTS header round trip and corruption cases, byte sources.
- `test_stream_trace.cpp`: StreamingTileTrace against the TileTrace contract, format rejections.
- `test_hist.cpp`: distinct-address histogram and sidecar.
- `test_sweep.cpp`: BroadcastSweep equals N independent runs.

Not built by make:
- `u19_check.cpp`: one-off measurement of `core_stall == fetch_latency` across prefetch distances
  (manual g++ line in its comment, `u19_check.cpp:12-13`).

Drivers:
- `compile_fail.sh`: negative compile cases (type mixing, abstractness, const overrides), `-fsyntax-only`.
- `mutation_check.sh`: mutates library files in place, expects `make test` to go red; restores from
  backups.
- `run_cli.sh`: `wcache_run` end to end on a fixture converted by `examples/to_stream.py`.
- `sweep_cli.sh`: `wcache_sweep` end to end, compares with `wcache_run` rows.
- `v1_pipe.sh`: invariant V1 (unbounded cache, zero latency -> `tile_origin[N] == tick_base[N]`),
  plus two deliberately broken runs that must fail.

### 2.5 `src/wcache/native_v1_archive/`

Ten tracked files (`Makefile`, `compile_flags.txt`, `.gitignore`, `include/wcache/{cache,layout,
types}.h`, `src/{cache,layout}.cpp`, `tests/{check.h,test_layout.cpp}`): an earlier version of the
types, an `AddressMapper`/`BlockPackMapper` (`native_v1_archive/include/wcache/layout.h:23,76`) and
a cache. A recursive grep of every `.py/.sh/.cpp/.h/.json/.yaml/Makefile/.slurm` file in the repo for
`native_v1_archive` finds nothing, so **no code references it**. It has its own Makefile and is not
built by `src/wcache/native/Makefile`. It is safe to delete from the code's point of view (the
docs may still mention it; not checked).

### 2.6 `src/wcache/*.py` and `src/wcache/examples/`

There are no `.py` files directly in `src/wcache/`; all three are in `examples/`.
- `examples/to_stream.py`: `load(path)` `:39` turns a v2 example JSON into `tracegen` dataclasses;
  `main` `:58` calls `tracegen.stream_weight_trace(..., n_cores=8, spatial_factors={3: 8})`
  (`:62-63`) to stdout, optional `max_tiles`. Adds `src/` to `sys.path` (`:20`) and stubs
  `archmodels.trace` when numpy is absent (`:22-31`). Used by the three CLI test scripts.
- `examples/make_examples.py`: cuts 2-tile / 8-core / 24-tick slices (`:49-52`) from
  `outputs/weight_traces` (`:42`) into the committed example JSONs and `manifest.json`; each example
  has a `check` predicate (`:57-94`); rewrites `mac_cycles` to keep `tile_tail` (`:121`).
- `examples/survey_corpus.py`: module-level script; walks `outputs/weight_traces` (relative to
  cwd, `:34`) for five archs and two workloads (`:36-37`), reports gap/tail/core statistics; writes
  JSON to `$OUT` (`:78`).
- Data: `loas_vgg16_layer01_v2.json`, `ptb_resnet19_layer01_v2.json`,
  `prosperity_vgg16_layer01_v2.json`, `spinalflow_vgg16_layer01_v2.json` (v2: tiles -> ticks ->
  cores -> `weight_addresses` `[kh,kw,cin,cout_start,cout_end]`),
  `gustavsnn_vgg16_layer01_v1_legacy.json` (v1, cannot drive the engine), `manifest.json`
  (provenance; relative paths only).

---

## 3. Findings for cleanup (code-evidenced)

### 3.1 Dead code, stale comments, stale references
1. **Dead store with stale comment**: `to_engine_params` sets `p.l2.demand_reserve = 0` under the
   comment "a removed knob ... no config key that can change it"
   (`src/wcache/native/src/config.cpp:718-720`), then overwrites it with `cfg.l2_demand_reserve`
   (`config.cpp:727`). The key exists (`config.cpp:147`).
2. Same stale story in three more places: `config.cpp:187-189` ("Removed knob, refused by name" with
   no code under it); `include/wcache/config.h:127-128` (says `l2_demand_reserve` is rejected by
   name); `src/stats.cpp:178-179` (says the column is "deliberately absent") while it is in the schema
   (`stats.cpp:227`) and emitted (`stats.cpp:346`).
3. `EngineStats::pf_dropped_targets_full` (`include/wcache/engine.h:214`) is never incremented
   anywhere in `src/`; it is always 0 by construction. `Request::reason`
   (`include/wcache/mshr.h:148`) is written (`src/mshr.cpp:64`) but never read in `src/` or `apps/`.
   `CoreState::issued_at` is written (`src/engine_core.cpp:64,193`) and never read in `src/`/`apps/`.
4. `l2_pf_timely` and `l2_pf_retriggers` are incremented together and only there
   (`src/engine.cpp:423-424`), so the two CSV columns are always equal.
5. Empty section header `// --- inclusion (C4, 4.4, N8)` (`src/engine.cpp:674`); the function is at
   `engine.cpp:730`.
6. `include/wcache/stamp_policy.h:1` says the file holds "the two ReplacementPolicy implementations";
   it holds five. `src/stamp_policy.cpp:226` says "A 2-bit RRPV, so the maximum is 3" above the
   configurable-width constant.
7. Misplaced comments in `RunConfig`: the `l2_policy` comment sits above `rrip_bits`
   (`include/wcache/config.h:53-62`), and `l2_policy_set` carries the comment "one knob, both levels"
   that describes `rrip_bits` (`config.h:65`).
8. `src/stats.cpp:293-297` refers to `LinearMapper`, which exists only as a test fixture
   (`tests/engine_fixture.h`, used at `tests/test_prefetch.cpp:48`).
9. `include/wcache/stream_format.h:9-10` names `src/cachesim/native_bridge.py` as the producer
   whose byte order this matches; the actual WCTS writer is `src/tracegen.py:508-655`.
10. `tests/u19_check.cpp` is not matched by `TEST_SRCS` (`Makefile:57`), so it is never built or run;
    its own build line writes to `/tmp/u19` (`u19_check.cpp:12-13`).
11. `next_use.h:30` includes `<istream>`, which nothing in the file uses.
12. `LevelParams::bank_high_bits` (`include/wcache/cache_level.h:131`) has no config key (absent from
    `config.cpp:135-165`, never set in `to_engine_params`), so the high-bits banking branch
    (`src/cache_level.cpp:103`) is reachable only from tests.
13. `src/wcache/native_v1_archive/` is unreferenced (2.5).

### 3.2 Duplicated logic
1. The three mappers repeat the same helpers and three identical method bodies: `checked_mul`
   (`src/block_pack.cpp:82`, `src/split_cin.cpp:65`, `src/khkw_split.cpp:26`), `blocks_covering`
   (`block_pack.cpp:105`, `split_cin.cpp:75`, `khkw_split.cpp:34`), `block_size_on`
   (`block_pack.cpp:119`, `split_cin.cpp:91`, `khkw_split.cpp:38`), `expand` (`block_pack.cpp:359`,
   `split_cin.cpp:410`, `khkw_split.cpp:188`), `locate` (`:398`, `:454`, `:220`), `line_size_terms`
   (`:421`, `:487`, `:233`). The code comments say this is deliberate (siblings share no code), but
   `expand`/`locate` only depend on `line_of`/`num_lines`.
2. Enum spellings are written in several places: parse (`src/config.cpp:203-302`), emit
   (`src/stats.cpp:16-51`), `layout_text` (`src/sweep.cpp:14-21`), a two-way ternary over the
   three-valued `LayoutKind` (`config.cpp:561`, exactly the pattern `sweep.cpp:10-13` warns against;
   correct today only because SplitCin is excluded by the branch), and an inline ternary for
   `L2PrefetchKind` (`stats.cpp:341`).
3. Nearest-rank quantile twice: `include/wcache/hist.h:85-92` and `src/stats.cpp:60-65`.
4. `engine_error` / `idx` twice: `src/engine.cpp:18-22`, `src/engine_core.cpp:31-35`. Way-from-slot
   arithmetic twice: `engine.cpp:691-694` and `engine.cpp:752-755`.
5. Per-policy `index_or_reject` four times: `src/stamp_policy.cpp:50,126,179,252`.
6. The two apps duplicate the config/trace/mapper/validate setup and drift:
   - `--max-engines` uses bare `std::stoi` (`apps/wcache_sweep.cpp:107`, accepts `"12abc"`) while
     `wcache_run` uses `int_value_of` (`app_support.h:60`).
   - Oracle help text disagrees: L1 oracles "exact WHILE NOTHING BLOCKS" (`wcache_run.cpp:89-94`) vs
     "EXACT" (`wcache_sweep.cpp:64-66`).
   - Header default: run `wcache_run.cpp:252`, sweep `wcache_sweep.cpp:85`.
   - Sweep has no `--l2-oracle`, instruments, or `--oracle-only`.
   - AccessLog batch size `1 << 16` duplicated in `access_log.h:143` and `app_support.h:340`.

### 3.3 Behaviour hazards worth a look before trusting new runs
1. **H1** `write_out` opens `--out` with a truncating `std::ofstream` (`apps/app_support.h:292`),
   while `wcache_run` turns the header off when the file exists (`wcache_run.cpp:252`). A second run
   to the same path overwrites the first row and leaves a headerless file. The header logic implies
   append semantics that the writer does not have.
2. **H2** `LineTrace::key` packs `core+1` into 6 bits with no check (`include/wcache/line_trace.h:
   179-182`); the comment says a wider machine "would trip the encoding" (`:175-178`), but nothing
   trips, so with more than 62 cores keys alias silently. `AccessLog` allows 255 cores
   (`access_log.h:138`); the code mentions 256-core targets (`event.h:240-243`).
3. **H3** Anchor decode `with_coord_on(Coord{kh, kw, cin, run_start}, axis, run_start)`
   (`src/stream_trace.cpp:302-303`) is right for `burst_dim == COUT`. For any other axis the anchor's
   COUT coordinate is set to `run_start` and the axis coordinate overwritten, so the record's own
   field for that axis is lost. Only COUT streams are tested (`tests/test_stream_trace.cpp:37`).
4. **H4** L2 prefetch accounting is not closed: `close_out_prefetch_stats` handles L1 only
   (`src/engine.cpp:660-672`), lines still tagged in `l2_prefetched_` at end of run are not charged
   as wasted, and `check_invariants` checks only the L1 identity (`src/stats.cpp:413-445`), although
   `engine.h:244-246` says the L2 counters sum to `l2_pf_issued`.
5. **H5** `validate` requires `l2_demand_reserve < l2_mshrs` even when L2 prefetching is off, and
   the reserve defaults to `lines_per_burst` (`src/config.cpp:630-639`). With the default
   `l2_mshrs = 20`, a layer whose widest burst spans 20 or more lines is refused unless
   `l2_demand_reserve` is set by hand.
6. **H6** MSHR occupancy samples are appended on every forward and retire
   (`src/engine.cpp:267,394,533,602`) and kept for the whole run per engine; memory grows with miss
   count times grid size (up to 256 engines).
7. **H7** `TraceFd` parses `fd:N` with unchecked `std::stoi` (`app_support.h:261`).
8. `mutation_check.sh` edits library sources in place and restores from a backup dir
   (`tests/mutation_check.sh:81-82`); an interrupted run can leave mutated sources behind.

### 3.4 Hardcoded values, paths, host assumptions
- `CXX := g++` pinned, ignoring the environment (`src/wcache/native/Makefile:24`, rationale about the
  Delta Cray wrapper at `:19-22`), while `compile_fail.sh` honours `${CXX:-g++}`
  (`tests/compile_fail.sh:21`).
- `JOBS` default 32 = the dev machine's `nproc` (`tests/compile_fail.sh:35,56`,
  `tests/mutation_check.sh:119`).
- `to_stream.py` hardcodes 8 cores and `spatial_factors={3: 8}` (`src/wcache/examples/
  to_stream.py:36,62-63`); `make_examples.py` slice sizes (`make_examples.py:49-52`) and corpus root
  (`:42`); `survey_corpus.py` cwd-relative `ROOT` and fixed arch/workload lists (`:34-37`) and
  requires `$OUT` (`:78`).
- Docstrings assume `conda run -n base` (`make_examples.py:29`, `survey_corpus.py:28`).
- Magic numbers in code: `kPosLoRadix = 8` (`include/wcache/khkw_split.h:89`); RRIP width cap 8 twice
  (`src/stamp_policy.cpp:230`, `src/config.cpp:593`); `--max-engines` 256
  (`apps/wcache_sweep.cpp:84`); AccessLog record limits 32-bit line / 8-bit core
  (`access_log.h:137-138`).
- `stream_format.h:33-35` requires the GCC/Clang `__BYTE_ORDER__` macro.
- No absolute paths or hostnames appear in any `.cpp/.h/.sh/.py` file in scope (grep for `/home/`,
  `/projects/`, `/scratch`, `delta`, `ncsa` hits comments only).

### 3.5 Build products in git
None: `git ls-files src/wcache/native/build` is empty; `build/` is ignored by
`src/wcache/native/.gitignore:1`; `__pycache__/` by the root `.gitignore:2`. A local
`src/wcache/native/build/fixture/` exists (untracked). Note the repo-wide `*.json` ignore
(`.gitignore:23`) with an exception only for `src/wcache/examples/*.json` (`.gitignore:40`) and
`profiling/**/grids/*.json` (`.gitignore:45`): a new run config elsewhere is silently untracked.

---

## 4. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

What the code needs:
- **Compiler/build**: GNU make and `g++` with C++17 (`Makefile:24-27`); flags `-Wall -Wextra
  -Wpedantic -Wsign-conversion -Wconversion -Wshadow`, `-O0 -g` (fixture) or `-O2 -DNDEBUG`
  (release). No CMake (no `CMakeLists.txt` exists). No third-party libraries; POSIX headers
  (`unistd.h`, `fcntl.h` in `byte_source.h:17`, `app_support.h:15-16`). `ar` for the archive.
  Minimum g++ version is not pinned anywhere.
- **Release programs**: `make release` builds only `libwcache.a` (`Makefile:205-206`). Drivers expect
  `build/release/wcache_sweep` (`profiling/0907_assoc/run_sweep.py:44`,
  `profiling/0907_linesize/run_sweep.py:60`), which needs `make MODE=release apps`
  (as `profiling/0820_phaseD_spad_vs_cache/run_sweep.py:34` notes).
- **Tests**: `make test` needs only the compiler and bash; `wait -n` in `compile_fail.sh:109` needs
  bash >= 4.3. `make test-cli` needs `python3` (override with `PYTHON`) and an importable
  `src/tracegen.py` (`to_stream.py:20,33`); numpy is optional thanks to the stub.
- **Inputs**: real runs need WCTS streams, produced by `src/tracegen.py:633` from the weight-trace
  corpus under `outputs/weight_traces`, which is git-ignored (`.gitignore:16`) and not in this
  worktree. Only the five small example slices are committed.
- **Two-pass Belady**: `policy/l2_policy = belady` needs `--oracle` / `--l2-oracle` from a prior
  run's `--access-log` over the same trace and layout (`wcache_run.cpp:314-344`); results are only
  sound when `max_wait_depth == 0` (`app_support.h:485-491`).
- **Non-deterministic columns**: `run_id` defaults to a random UUID (`app_support.h:86`),
  `sim_wall_seconds` is wall time, and `git_commit` is empty unless the driver passes it
  (`wcache_run.cpp:53-54`). Everything else is designed to be bit-identical across runs (total event
  order, vectors iterated by index; `unordered_map`s are never iterated in decision paths, though
  `LineTrace::flush` sorts its map keys `line_trace.h:148-151`).
- **Binary formats**: the AccessLog is written in host byte order with no endianness marker
  (`access_log.h:131-132`), unlike WCTS, which is explicitly little-endian.
- **Driver scripts** that set paths live in `profiling/` (out of scope); they locate the binary
  relative to the repo root, not via absolute paths, in the two files checked.

---

## 5. Open questions the code alone cannot answer

1. Is `burst_dim != COUT` meant to be supported end to end? If so, what should the decoder do with
   the record's third field (finding H3)?
2. Should `l2_demand_reserve` be validated (and resolved) only when `l2_prefetch_policy !=
   none` (H5)? Which committed results depend on the current refusal?
3. Should tagged-but-unused L2 prefetched lines be charged as wasted at end of run, and should the L2
   identity be enforced in `check_invariants` (H4)?
4. Is `l2_policy` meant to appear in the CSV? The schema has only `policy` (`src/stats.cpp:214`), so
   a row with a different L2 policy is not self-describing.
5. Is `bank_high_bits` meant to be a sweepable knob (3.1 item 12)?
6. Is `wcache_run --out` meant to append (H1)? Which drivers write one file per run?
7. What core-count ceiling must the instruments support (LineTrace 62, AccessLog 255)?
8. Which g++ version produced the committed results, and do Delta runs use the same one?
9. Is `native_v1_archive/` kept for any reason outside code (docs, provenance)?
10. Is `u19_check.cpp` still needed, or should it become a `test_*.cpp`?

---

### Not covered
- `tests/*.cpp` and the two big shell drivers were summarised from their header comments and
  targeted greps, not read line by line.
- `src/wcache/native/compile_flags.txt` and `native_v1_archive/compile_flags.txt` were not read
  (`.txt` is excluded by the reading rules).
- `profiling/` drivers and `src/tracegen.py` were only grepped to establish the connection.
