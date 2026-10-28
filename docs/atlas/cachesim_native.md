# Code atlas: `src/cachesim` (cache simulator)

Branch `wcache-rebuild-phase-a`, commit `94a5b34`. Written from code only: `.cpp`, `.h`, `.sh`,
`.py`, `Makefile`, `.json`. No markdown, text or log file was read, so any design rationale below is
what the code's own comments state. Paths that start with `src/cachesim/native/`, `src/cachesim/`,
`configs/`, `scripts/`, `tests/` or `docs/` are relative to the repo root; every other path (such as
`src/core/engine.cpp`, `include/cachesim/config.h`, `apps/app_support.h`, `tests/run_cli.sh`, `Makefile`)
is relative to `src/cachesim/native/`.

> **The reader accepts WCTS version 2 only.** `decode_header` throws `std::invalid_argument` for any
> `format_version` other than 2 and says in the message to regenerate the stream
> (`src/cachesim/native/include/cachesim/trace/stream_format.h:221-228`, `kFormatVersion = 2` at
> `trace/stream_format.h:42`). The writer is `cachesim.stream.stream_weight_trace`
> (`src/cachesim/stream.py:177`), which writes `WCTS_VERSION = 2` (`src/cachesim/stream.py:43`).

There is **no `CMakeLists.txt`**. The native build is `src/cachesim/native/Makefile` (GNU make).

---

## 1. Top-down

### 1.1 Purpose

cachesim is an event-driven, deterministic simulator of the weight-fetch side of a multi-core
accelerator. It reads one layer's weight-access trace (a "WCTS" binary stream of bursts per core per
tile) and replays it through a private L1 per core, one shared banked L2, and a pipelined DRAM
channel, with MSHR files, ports and optional prefetchers. Logical weight coordinates
`[KH][KW][CIN][COUT]` are mapped to cache lines at run time by a swappable `AddressMapper` (three
layouts), so one trace can be replayed under several memory layouts. The output is one CSV row per
configuration (cycles, stretch over the trace's own timeline, hit rates, stall breakdown, prefetch
outcomes, model-health counters). A tile barrier joins all cores between tiles, and each core issues
its next burst at `max(trace gap, core_accept_ii)` after its previous burst was served.

### 1.2 Entry points

**`python -m cachesim {grid, sweep, run}`** (`src/cachesim/__main__.py:1-4` calls `main` in
`src/cachesim/cli.py`):
- `grid --out DIR [--base PATH] [--sweep PATH]`: crosses the base config `configs/cache/base.json`
  with the sweep axes `configs/cache/khkw_sweep.json` (`BASE_JSON`, `SWEEP_JSON`,
  `src/cachesim/grid.py:8-9`) and writes one JSON array per `cin_block` to `DIR/khkw_<k>.json`
  (`write_grid`, `src/cachesim/grid.py:39-53`), printing the paths. Each line size
  `line_bytes` sets `cin_block = line_bytes // (cout_block * weight_bytes)`
  (`src/cachesim/grid.py:26`); the points at one line size are `l2_banks x prefetch`, banks slowest
  (`src/cachesim/grid.py:27-29`). With the committed files that is 3 line sizes x 4 banks x 4
  prefetch settings: three files of 16 points (`configs/cache/khkw_sweep.json:2-4`).
- `sweep ARGS...` / `run ARGS...`: runs `src/cachesim/native/build/release/cachesim_sweep` /
  `cachesim_run` with every later argument passed unchanged (`--help` included) and returns its exit
  code; if the binary is missing it first runs `make -C src/cachesim/native MODE=release apps`
  (`native` in `src/cachesim/cli.py`).

Two native programs, both `main()` in `src/cachesim/native/apps/`, sharing `apps/app_support.h`.
Exit codes: 0 ok, 2 usage error (`UsageError`, `app_support.h:48`), 1 any other exception.

**`cachesim_run`** (`src/cachesim/native/apps/cachesim_run.cpp:430`): one config, one trace, one CSV
row. Flags parsed in `parse_args` (`cachesim_run.cpp:148`); help text `kUsage` (`cachesim_run.cpp:39`).

| flag | default | meaning |
|---|---|---|
| `--config PATH` | required | flat JSON object, `parse_config` |
| `--trace PATH` | required | WCTS v2 stream; `-` = stdin, `fd:N` = open descriptor |
| `--out PATH` | `-` (stdout) | CSV destination (file is truncated, `app_support.h:288`) |
| `--header` / `--no-header` | **on** (`cachesim_run.cpp:140`) | CSV header line |
| `--arm NAME` | `cache` | one of `cache, spad_oracle, spad_wcache, spad_nocsim` (`app_support.h:76`) |
| `--tier`, `--run-id`, `--git-commit` | empty, random UUIDv4, empty | identity columns |
| `--hist PATH` | off | per-(core,tile) distinct-address CSV |
| `--cache-state PATH` (+`-core/-tile/-limit N`, default -1) | off | every array fill/evict/invalidate |
| `--line-trace PATH` (+`-level l1\|l2\|both` default l1, `-core/-tile/-line/-limit N` default -1) | off | one row per residency episode |
| `--oracle PATH` | off | prior run's access log, builds per-core L1 + shared L2 next-use oracles (Belady) |
| `--l2-oracle PATH` | off | same file, L2 records only; mutually exclusive with `--oracle` |
| `--access-log PATH` | off | binary demand-reference log (input for `--oracle`) |
| `--oracle-only` | off | decode only; row with `total_cycles == tick_base_total`, no engine |

Narrowing flags without their file are refused (`cachesim_run.cpp:192-202`). The header does not
depend on whether `--out` exists, so a rerun to the same path leaves one header and one row (pinned
by `src/cachesim/native/tests/run_cli.sh:203-220`).

**`cachesim_sweep`** (`src/cachesim/native/apps/cachesim_sweep.cpp:259`): one grid, one trace read once,
N engines in lock-step, one row per grid point. Flags (`cachesim_sweep.cpp:91`): `--config-grid PATH`
(required; JSON array of configs, or `{"base":{...},"axes":{key:[values]}}` cross product, first axis
slowest), `--trace` (required), `--out` (`-`), `--header`/`--no-header` (default **on**,
`cachesim_sweep.cpp:85`), `--arm`, `--tier`, `--run-id`, `--git-commit`, `--hist`, `--oracle`,
`--max-engines N` (default 256), `--progress`. No instruments, no `--l2-oracle`, no `--oracle-only`.

**Build targets** (`src/cachesim/native/Makefile`): `make` = `lib apps` in `build/fixture` (`-O0 -g`,
asserts live); `make test` = compile-fail driver + every `tests/test_*.cpp` binary;
`make test-cli` = builds apps, runs `run_cli.sh`, `sweep_cli.sh`, `v1_pipe.sh`, `cout_golden.sh`
(`Makefile:142-146`, needs python3); `make test-run` = test binaries only; `make release` =
**library only** (`libcachesim.a`, `Makefile:45`) in `build/release` (`-O2 -DNDEBUG`,
`Makefile:181-182`); `make MODE=release apps` builds the release programs that `python -m cachesim`
runs; `make clean`.

### 1.3 Data flow (one `cachesim_run`)

Inputs come from two Python producers. The configs: `python -m cachesim grid` turns
`configs/cache/base.json` and `configs/cache/khkw_sweep.json` into grid files (1.2); `cachesim_run`
takes one object, `cachesim_sweep` a whole file. The trace: `python -m weight_trace_gen gen --stream`
writes one layer-sample as a WCTS stream on stdout (`--stream` flag
`src/weight_trace_gen/cli.py:383`, `emit_stream` `src/weight_trace_gen/cli.py:280`, which calls
`cachesim.stream.stream_weight_trace` at `src/weight_trace_gen/cli.py:290`), and
`python -m cachesim sweep --config-grid GRID --trace STREAM` replays it.

1. **Config text -> `RunConfig`**: `parse_config` (`src/cachesim/native/src/config.cpp:398`), a strict
   JSON subset (integers and quoted strings only, unknown or duplicate key = error).
2. **Trace bytes -> `StreamHeader`**: `TraceFd` (`app_support.h:255`) -> `FdByteSource`
   (`include/cachesim/trace/byte_source.h:51`) -> `StreamingTileTrace` ctor reads and validates the header
   (`src/trace/stream_trace.cpp:26`, `decode_header` at `trace/stream_format.h:208`).
3. **Header -> `WeightShape`** via `shape_of` (`src/trace/stream_trace.cpp:354`).
4. **Validation**: a `BlockPackMapper` "probe" computes `lines_per_burst` (`app_support.h:163`), then
   `validate(cfg, lines_per_burst, warnings)` (`src/config.cpp:521`) resolves the `-1` sentinels
   (`l1_demand_reserve`, `l2_demand_reserve`, `cin_lo_blocks`, `l2_policy`) and refuses bad configs.
5. **Mapper**: `make_mapper` (`app_support.h:116`) builds `BlockPackMapper` / `SplitCinMapper` /
   `KhkwSplitMapper` -> `const AddressMapper&`. All three share `src/layout/layout_common.h`.
6. **`RunConfig` -> `EngineParams`**: `to_engine_params` (`src/config.cpp:691`) -> two `LevelParams`.
7. **Engine**: `Engine(mapper, trace, params)` (`src/core/engine.cpp:33`) builds N L1 `CacheLevel`s, one L2
   `CacheLevel`, a DRAM `Port`, a `Prefetcher` and an `L2Prefetcher`.
8. **Tile loop** (`cachesim_run.cpp:372-385`): `trace.advance()` decodes tile N into the one-tile window
   -> `DistinctAddressHistogram::observe`, `PaddingMeter::observe_tile` -> `engine.run_to_barrier()`
   runs events until tile N's barrier is next; then `engine.finish()`.
9. **Stats -> CSV**: `RunStats(id, cfg, hdr, engine.stats(), tile_origin(n_tiles), tick_base(n_tiles),
   padding, wall, hist.p50, hist.max)` (`src/instrument/stats.cpp:256`), `check_invariants()`, `csv_row()`;
   `write_out` (`app_support.h:282`).

`cachesim_sweep` is the same with steps 4-9 per grid point, `BroadcastSweep` (`src/sweep.cpp:44`)
driving all engines over one window (`src/sweep.cpp:112`).

**Upstream connection (visible in code).** The WCTS writer is `src/cachesim/stream.py` (2.5). The
pieces that fix the wire format: `WCTS_VERSION = 2` (`src/cachesim/stream.py:43`),
`WCTS_ADDR_FIELDS = (0, 1, 2, 3, 4)` (`:52`), `write_stream_header` (`:56`), `write_tile_frame` (`:98`,
refuses a run that is empty along `burst_dim` at `:124`), `write_stream_trailer` (`:135`),
`_wcts_tile_frames` (`:140`, measures `burst_span` as the largest `cout_end - cout_start` at `:166`)
and `stream_weight_trace` (`:177`, refuses any `burst_dim != 3` at `:195`). `scripts/pipeline.py`
writes each layer-sample's stream to a `.wcts` file with `python -m weight_trace_gen gen ... --stream`
and runs `python -m cachesim sweep` on it once per grid file. `--access-log` output is read back
only by `--oracle` / `--l2-oracle` (`read_oracle_lines`, `app_support.h:322`).

### 1.4 Key abstractions

```
             WCTS bytes                         RunConfig --validate--> EngineParams
                 |                                                           |
   ByteSource -> StreamingTileTrace : TileTrace           AddressMapper (BlockPack|SplitCin|KhkwSplit)
                 |   (one-tile window)                         |   expand(Burst)->[LineId]
                 v                                             |   locate(LineId,num_sets)->Placement
              Engine : PrefetchIssuer  <------------------------+   neighbour(line,axis,d)
   EventQueue<EventPayload> (total order: time,class,age,core,seq)    (expand/locate/checks shared
     |-- cores_[c] : CoreState (cursor, pending_lines, phase)          via src/layout/layout_common.h)
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

The `Request` (one line of one burst, `include/cachesim/core/request.h:27`) is the unit that travels. It lives
in `Engine::arena_` (a `std::deque`, stable addresses) with a free list (`core/engine.h:629,653`). An
`Mshr` (`core/mshr.h:48`) is one outstanding line per level; `targets` are satisfied directly by the
fill, `line_wait` are requests that found the target list full.

Strongly typed scalars (`include/cachesim/types.h`): `LineId`, `CoreId`, `SlotId`, `SetIndex`,
`TagId`, `BurstIndex`, `SimTime`, `LocalTick`, `RefusalOrder`, `EventSeq` are distinct
`Tagged<Rep,Tag>` types with no default constructor and no narrowing constructor, so mixing them is
a compile error (checked by `tests/compile_fail.sh`).

### 1.5 One run, step by step (engine semantics)

Times are integer cycles (`SimTime`). Trace ticks (`LocalTick`) are offsets inside a tile.

1. `run_to_barrier` first call (`src/core/engine.cpp:128`): `tile_origin[0]=0`, `start_tile(0, 0)`.
2. `start_tile(t, now)` (`src/core/engine_core.cpp:55`): every core reset (cursor 0, phase Computing),
   prefetch cursor reset; a core with 0 bursts arrives at the barrier at once; otherwise an `Issue`
   event is scheduled at `now + local_tick(core, t, 0)` (the only absolute tick used).
3. `on_issue` (`src/core/engine_core.cpp:148`): checks `k == cursor` and `pending_lines == 0`; `expand`
   turns the burst into sorted distinct lines; `pending_lines = #lines`, phase Stalled; per line a
   demand `Request` reserves the L1 port and schedules `L1Probe` at `accept + l1_latency`. Then the
   prefetcher hook `on_demand_issue` runs.
4. `on_l1_probe` (`src/core/engine.cpp:254`) -> `CacheLevel::triage` (`src/core/cache_level.cpp:112`), probe
   order **array -> own MSHR -> MSHR pool**:
   - Hit: policy `on_hit`; `core_line_done`; request released.
   - Merged (entry exists, target list not full): subscribes, nothing scheduled.
   - BlockedTargets / BlockedPool: put on that entry's `line_wait` / the file's `slot_wait`, stamped
     with a global refusal counter value on first refusal (write-once).
   - Forwarded (allocated a new entry): request now holds the L1 entry (`mshr1`, `level = L2`), L2
     bank port reserved, `L2Probe` at `accept + l2_latency`.
   - A prefetch at issue is **dropped**, never queued: `DroppedArrayHit/Entry/NoSlot/Reserve`.
5. `on_l2_probe` (`src/core/engine.cpp:369`): same triage at L2. Hit -> `L1Fill` at `now +
   l2_to_l1_latency`. Forwarded -> `dram_.reserve(now)` -> `L2Fill` at `accept + l2_miss_latency`.
   An L2 demand miss (or demand hit on an L2-prefetched line) triggers `l2_prefetch_from`.
6. `on_l2_fill` (`src/core/engine.cpp:492`): install in L2 (free way first, then policy victim);
   back-invalidate the victim from every L1 if `inclusive`; retire the L2 entry; every target with an
   L1 entry gets `L1Fill` at `now + l2_to_l1_latency`; woken requests re-enter through their port.
7. `on_l1_fill` (`src/core/engine.cpp:555`): install in L1, update prefetch outcome bookkeeping, clear
   `mshr1` on every target, retire the L1 entry, `core_line_done` per demand target, return the
   prefetch credit per prefetch target, reinject wake list.
8. `core_line_done` (`src/core/engine_core.cpp:219`): `--pending_lines`; at 0 the burst is served
   (bursts are atomic) and the last line's `StallCause` is charged.
9. `serve` (`src/core/engine_core.cpp:241`): `want = tile_origin[t] + local_tick(0)` for burst 0, else
   `served_time + max(gap(k-1), core_accept_ii)`; `stall = now - want` (throws if negative);
   `fetch_latency += now - burst_anchor`. Next `Issue` at `now + max(gap(k), core_accept_ii)`, or
   barrier arrival after the last burst.
10. `barrier_arrive` (`src/core/engine_core.cpp:95`): countdown; the last core schedules `Barrier` at
    `now + tile_tail(t)` (`tile_tail = mac_cycles - max_tick`, must be >= 1).
11. `run_to_barrier` returns *before* dispatching a Barrier, so the driver can advance the shared
    window; the next call dispatches it. `on_barrier` (`src/core/engine_core.cpp:114`) sets
    `tile_origin[t+1] = now`, charges barrier slack per core, and starts tile t+1 or marks all Done.
12. When the queue empties: L1 prefetched-but-unused lines are charged as wasted (L2 ones are not,
    finding H4), then `check_no_work_outstanding` throws on any deadlock (`src/core/engine.cpp:170`).

Tie-break classes at equal time (`include/cachesim/core/event.h:43`): Fill(0) < Barrier(1) < Probe(2) <
Issue(3); then refusal stamp (older refused first, never-refused last), core id, schedule seq.
`total_cycles = tile_origin[n_tiles]`; `tick_base_total = sum(mac_cycles)`;
`stretch_cycles = total_cycles - tick_base_total`.

### 1.6 Config knobs (`RunConfig`, `include/cachesim/config.h:27`) and defaults

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
`num_sets = num_lines/assoc` (`src/config.cpp:388-394`). Warnings returned by `validate`:
`W_MSHR_VS_LINES`, `W_FEW_SETS`, `W_CIN_LO_VS_SETS`, `W_PREFETCH_BUDGET`, `W_ZERO_II`
(`src/config.cpp:657-686`); `make_mapper` adds `W_CIN_LO_UNREACHABLE` (`app_support.h:138`).

The L2 MSHR floor: with `l2_demand_reserve` unset it resolves to `lines_per_burst`
(`config.cpp:629`) and must stay below `l2_mshrs` whatever the L2 prefetch policy is
(`config.cpp:634-639`). With the default `l2_mshrs = 20`, a 19-line burst passes and a 20-line burst
is refused; `tests/test_config.cpp:204` pins both and pins that the message does not mention
prefetching.

### 1.7 WCTS v2 wire format (as decoded)

Little-endian, unaligned. Fixed header 56 bytes (`include/cachesim/trace/stream_format.h:46`): magic
`WCTRACE1` (unchanged from v1, `:41`), u32 version=2 (`:42`), u32 header_bytes, i32 n_tiles, n_cores,
weight_bytes, burst_dim (0..3), burst_stride, burst_span, n_addr_fields (=5), n_spatial, n_dims (=7),
identity_bytes; then 5 i32 field codes, which must be 0..4 in order and mean
`KH, KW, CIN, COUT, RunEnd` (`FieldCode`, `:54`); n_spatial `(dim,factor)` pairs (ascending,
product must equal n_cores), 7 `(dim,extent)` pairs (ids 0..6: KH,KW,CIN,COUT,HO,WO,T), identity
block of 4 NUL-terminated strings (arch, workload, layer, sample_idx). Per tile frame
(`src/trace/stream_trace.cpp:14-18,176`): 24-byte prefix `i32 tile_index, i32 n_core_blocks, i64
mac_cycles, u64 payload_bytes`; per core block `i32 core_id (ascending), i32 n_bursts (>=1)`; per
burst 28 bytes `i64 local_tick (strictly ascending per core), i32 kh, kw, cin, cout, run_end`
(`src/trace/stream_trace.cpp:270-275`). Trailer 12 bytes: `i32 -1, u64 total_bursts`
(`src/trace/stream_trace.cpp:337`).

Decode of one record (`src/trace/stream_trace.cpp:289-306`): `anchor = Coord{kh, kw, cin, cout}`;
`run_start = coord_on(anchor, burst_dim)`; refused if `run_end <= run_start`; the burst is
`Burst{anchor, burst_dim, run_end - run_start, burst_stride}`. The record therefore holds the run's
full anchor on every axis, and `run_end` is the exclusive end along `burst_dim`. For a COUT stream
(`burst_dim = 3`, the only kind `stream_weight_trace` writes) the v2 bytes equal the v1 bytes except
for the version field; `tests/cout_golden.sh:2-8` states this and checks it end to end.

---

## 2. Bottom-up

Paths below are under `src/cachesim/native/` unless a full path is given. Inside an entry, a bare `:N`
is a line of the file the entry is named after (a source file, not the header named beside it), and
`.cpp:N` is the paired `.cpp`.

### 2.1 `include/cachesim/` (headers)

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
- `struct Coord {kh,kw,cin,cout}` `:263`; `struct Burst {anchor, axis, count, stride}` `:284` (its
  comment `:270-274` describes the v2 decode); `struct WeightShape {KH,KW,CIN,COUT}` `:292`.
- `extent_on` `:300`, `coord_on` `:314`, `with_coord_on` `:329`, `axis_name` `:340`: switch over
  `Axis`, throw `logic_error` on unknown value.
- `std::hash<Tagged<..>>` `:355` (for `unordered_map<LineId,...>`).

**layout/mapper.h**
- `enum class LayoutKind {BlockPack, SplitCin, KhkwSplit}` `layout/mapper.h:41`.
- `struct Placement {SetIndex set_index; TagId tag;}` `:72`; identity `line == tag*num_sets + set`.
- `class AddressMapper` `:84` (abstract). Error vocabulary: `invalid_argument` malformed,
  `out_of_range` outside the layer, `logic_error` programmer error (`:88-103`).
  - `expand(const Burst&, vector<LineId>& out)` `:154`: APPENDS this burst's distinct lines, strictly
    increasing within one call; `count<1` or `stride<1` throws; all checks before the first append.
    The comment above it (`:107-111`) names the v2 record for a CIN burst.
  - `locate(LineId, int64 num_sets) -> Placement` `:164`: range-checks before dividing.
  - `neighbour(LineId, Axis, int32 delta) -> optional<LineId>` `:181`: step `delta` BLOCKS along an
    axis, `nullopt` if it leaves the layer.
  - `num_lines()` `:184` (one past max id), `line_size_bytes()` `:190`,
    `line_size_terms(int64)` `:217` (diagnostic, default prints the number).

**index/cache_array.h**
- `struct Candidate {SlotId slot; LineId line;}` `index/cache_array.h:38` (line = NoLine if free).
- `struct InsertResult {bool evicted; LineId evicted_line;}` `:51`.
- `class CacheArray` `:68`: `probe` `:79` (const, not an access), `free_slot` `:84`,
  `victim_candidates` `:102` (REPLACES `out`), `insert` `:107`, `invalidate` `:121`,
  `num_slots` `:132`. Copy/move protected (`:162-166`).

**replacement/policy.h**
- `class ReplacementPolicy` `replacement/policy.h:37`: `on_hit` `:50`, `on_fill` `:58`, `on_invalidate` `:64`,
  optional `note_next_use(slot, next_use)` `:81` (default no-op; called right before
  `on_fill`/`on_hit` when an oracle is attached), `pick_victim(candidates)` `:106` (must not depend on
  candidate order; non-const).

**core/event.h**
- `enum class EventClass {Fill=0, Barrier=1, Probe=2, Issue=3}` `core/event.h:43`.
- `enum class EventKind {Issue, L1Probe, L2Probe, L2Fill, L1Fill, Barrier}` `:68`.
- `class_of(EventKind)` `:82`: Fills->Fill, Barrier->Barrier, probes->Probe, Issue->Issue.
- `struct EventKey {time, cls, age, core, seq}` `:111`; `key_less` `:125` lexicographic; total
  because `seq` is unique.
- `template<P> struct Event {key, kind, payload}` `:142`.
- `template<P> class EventQueue` `:155`: `schedule(time, kind, age, core, payload)` `:177` assigns
  `seq` itself, throws `logic_error` if `time < now`; `pop_min` `:193` sets `now`; `peek_min` `:210`;
  `empty`/`size` `:215-216`; `now` `:223`; `scheduled` `:229` (total events ever scheduled).
  `std::priority_queue` with reversed comparator (`:232-238`).

**trace/tile_trace.h**
- `class TileTrace` `trace/tile_trace.h:45` (abstract, read-only): `n_tiles` `:52`, `n_cores` `:53`,
  `n_bursts(core,tile)` `:57` (0 legal), `burst(core,tile,k)` `:64`, `local_tick` `:72` (offset in
  tile), `gap(core,tile,k)` `:87` (= tick[k+1]-tick[k]), `tile_tail(tile)` `:104`
  (= mac_cycles - max_tick).

**core/request.h**
- `Level`, `WaitReason` and `StallCause` are the shared request enums (`core/request.h:12-25`).
- `struct Request` `core/request.h:27`: `core, line, burst, demand(=true), issued_at, refusal(=NoRefusal),
  reason, level(=L1, where to RE-ENTER), mshr1 (L1 entry once forwarded), reserved, on_wait_index,
  cause, line_resident_at_wake`.

**core/mshr.h**
- `struct Mshr` `core/mshr.h:48`: `line, core (unused at L2), demand (promoted by a merging demand),
  pf_opened (fixed), first_request, targets, line_wait`.
- `class RefusalCounter` `:100`: `next()` `:105`, `issued()` `:110`. One per run, shared by all levels.
- `is_prefetch_at_issue(r)` `:140` = `!demand && mshr1==nullptr`.
- `mark_refused(r, reason, counter)` `:149`; `key_less(Request,Request)` `:154` (by refusal stamp).
- `struct RetireResult {targets; wake;}` `:162`.
- `class MshrFile` `:187`: ctor `:215`, `find` `:224`, `has_slot` `:237`, `allocate` `:255`,
  `add_target` `:268`, `push_line_wait`/`push_slot_wait` `:291-292`, `release_reservation` `:303`,
  `retire` `:321`, `collect_grants` `:335`; `entries_` `:374` is an `unordered_map`.
**core/port.h**
- `class Port` `core/port.h:37`: ctor `(ii, latency)` `:57` (both >= 0); `reserve(now)` `:74` returns
  `max(now, next_accept)` and sets `next_accept = accept + ii`; `ii()` `:76`, `latency()` `:82`
  (callers add it), `next_accept()` `:90`. Reservations are never released.

**index/set_associative.h**
- `class SetAssociativeArray final : CacheArray` `index/set_associative.h:48`; ctor `(mapper,
  cache_size_bytes, associativity)` `:72`; five verbs `:88-92`; `num_slots` `:107`, `num_sets` `:108`,
  `associativity` `:109`; private `base_slot` `:131`. Slots of set s are `[s*assoc, s*assoc+assoc)`;
  stores full `LineId` per slot (`:160`).

**replacement/stamp.h**
- `class StampPolicy` `replacement/stamp.h:12` (abstract; one i64 stamp per slot, victim = smallest stamp,
  tie -> smallest slot), protected `stamp()` `:21`.
- `LruPolicy` `:29` (hit restamps), `FifoPolicy` `:35` (hit ignored).

**replacement/belady.h**
- `class BeladyPolicy` `replacement/belady.h:12`: per-slot next-use; victim = LARGEST next use, tie smallest slot.

**replacement/lfu.h**
- `class LfuPolicy` `replacement/lfu.h:12`: per-slot hit count, reset on fill; victim = smallest count.

**replacement/rrip.h**
- `class RripPolicy(num_slots, bits=2)` `replacement/rrip.h:12`: uint8 RRPV; hit->0, fill->max-1,
  invalidate->max.

**replacement/policy.h**
- `enum class PolicyKind {LRU, FIFO, RANDOM, BELADY, RRIP, LFU}` `:130`.
- `make_policy(kind, num_slots, rrip_bits=2)` `:139`.
**replacement/next_use.h** (header-only)
- `class NextUseOracle` `replacement/next_use.h:39`: `kNever`=INT64_MAX `:41`; ctor from a reference sequence
  (one backward pass, then grouped by line) `:45`; `next_use(line, occurrence)` `:73` returns the
  position of the next reference after the `occurrence`-th one, or kNever and counts an overrun;
  `references` `:83`, `distinct_lines` `:84`, `overruns` `:85`; `optimal_hit_rate(lines, n_lines)`
  `:92` (fully-associative MIN, O(n * capacity)).

**prefetch/prefetcher.h**
- `enum class PrefetchKind {None, NextBurst}` `prefetch/prefetcher.h:34`.
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

**core/cache_level.h**
- `enum class TriageOutcome {Hit, Merged, BlockedTargets, BlockedPool, Forwarded, DroppedArrayHit,
  DroppedEntry, DroppedNoSlot, DroppedReserve}` `core/cache_level.h:74`; `is_dropped` `:88`.
- `struct LevelParams` `:105`: `cache_size_bytes, associativity, policy, rrip_bits, latency, ii,
  banks, bank_high_bits, mshrs, tgts_per_mshr, demand_reserve`.
- `class CacheLevel` `:138`: ctor `(Level, mapper, LevelParams, RefusalCounter&)` `:151`;
  `triage(r, granted)` `:176`; `install(line)` `:200`; `bank_of(line)` `:209`; `level`, `array`,
  `policy` `:211-214`; `attach_next_use(oracle)` `:227`, `next_use_oracle` `:228`; `mshrs` `:229-230`;
  `port(bank)` `:231`; `banks` `:232`; `num_sets` `:233`. Holds Belady occurrence counters
  `occurrence_` and `pending_next_use_` (`:244,250`).

**core/engine.h**
- `enum class Inclusion {NonInclusive, Inclusive}` `core/engine.h:59`; `enum class Phase {Computing,
  Stalled, AtBarrier, Done}` `:68`.
- `struct CoreState` `:77`: `tile, cursor, phase, pending_lines, issued_at, burst_anchor,
  barrier_arrival, served_time`.
- `struct EngineStats` `:128`: per-core vectors `core_stall, fetch_latency, stall_l1_slot ...
  stall_barrier, stall_total, pf_outstanding`; scalar counters for prefetch outcomes (L1 `:205-224`,
  L2 `:252-268`), `l1/l2_hits/accesses` `:239-240`, `dram_accesses` `:269`, health counters
  `hits_downgraded_to_miss, max_wait_depth, events` `:276-284`, MSHR occupancy samples `:289-290`.
- Comments on the L2 block: the outcomes plus drops sum to **at most** `l2_pf_issued`
  because L2 lines still tagged at end of run are not charged (`:244-247`), and `l2_pf_timely` is
  always equal to `l2_pf_retriggers` (`:254-255`, `:265-267`): both are incremented at one site,
  `src/core/engine.cpp:423-424`.
- `struct EventPayload {Request* req; Mshr* entry; BurstIndex burst; int32 tile;}` `:308`;
  `using EngineQueue = EventQueue<EventPayload>` `:315`.
- `struct EngineParams` `:331`: `l1, l2` LevelParams, `l2_to_l1_latency, dram_ii, l2_miss_latency,
  core_accept_ii, inclusion, prefetch_policy/distance, l2_prefetch_*`. No validation by design.
- `class Engine final : PrefetchIssuer` `core/engine.h:368`: ctor `:375`; `run` `:384`; `run_to_barrier` `:405`
  (returns pending barrier's tile or -1); `step_tile` `:417`; `finish` `:429`; `tile_origin(t)` `:435`
  (size n_tiles+1); `core` `:437`; `stats` `:438`; `queue` `:439`; `l1(c)` `:441`; `l2` `:442`;
  `prefetcher` `:443`; `set_cache_state_log` `:459`, `set_line_trace` `:460`, `set_access_log` `:466`;
  overrides `n_bursts_in_tile` `:469`, `issue_prefetch` `:470`. Private handlers listed `:474-574`.
- `as_duration(LocalTick) -> SimTime` `:681`: the one trace-gap-to-duration crossing.

**config.h**
- `struct RunConfig` `config.h:27` (fields in 1.6) with `line_size_bytes, l1_num_lines, l1_num_sets,
  l2_num_lines, l2_num_sets` `:109-113`. The `rrip_bits` comment (`:53-57`) and the `l2_policy`
  comment (`:59-63`) sit above their own fields; `l2_policy_set` reads "true when l2_policy was
  given explicitly" (`:65`).
- `struct Warning {code, message}` `:119`.
- `parse_config(json)` `:132` (its comment `:127-128` calls `l2_demand_reserve` an ordinary key),
  `parse_config_grid(json)` `:153`, `validate(cfg&, lines_per_burst, warnings&)` `:163` (mutates
  cfg), `to_engine_params(cfg)` `:168`.

**trace/stream_format.h** (namespace `cachesim::stream`, header-only; file comment `:1-3` says WCTS v2 and
`:10-12` names `src/cachesim/stream.py` as the producer)
- Constants `kMagic` `:41`, `kFormatVersion = 2` `:42`, `kFixedHeaderBytes`=56 `:46`, `kEndMagic`=-1
  `:47`, `kAddrFields`=5 `:48`, `kDims`=7 `:49`; `enum DimCode` `:53`, `enum FieldCode {KH, KW, CIN,
  COUT, RunEnd}` `:54`; `kHostIsLittleEndian` `:56` (requires
  `__BYTE_ORDER__`, `:35-37`).
- `read_le<T>` `:60`, `write_le<T>` `:73`; `axis_of(int32)` `:86` (only 0..3), `code_of(Axis)` `:98`.
- `struct StreamHeader` `:102` (the `burst_span` comment `:108-113` says a burst's extent is
  `run_end` minus the anchor's coordinate on `burst_dim`); `detail::identity_block` `:126`,
  `detail::append_le` `:137`, `detail::Cursor` `:146`.
- `encode_header(h, out)` `:174` (no validation; for tests; writes `kFormatVersion`, so it can only
  produce v2 headers); `decode_header(buf, len)` `:208` validates every field (see 1.7). Version
  check `:221-228`: any value other than 2 throws, and the message says that v1 records cannot hold a
  non-COUT anchor and to regenerate with `src/cachesim/stream.py`. `burst_span >= 1` is the only check on
  the span (`:258-262`).

**trace/byte_source.h** (header-only)
- `class ByteSource` `trace/byte_source.h:28`: `read_exact(dst, n)` `:36` returns false only on clean EOF,
  throws on partial read.
- `FdByteSource(int fd)` `:51` (does not own fd; retries EINTR/short reads); `MemByteSource` `:81`
  with `consumed()` `:100`.

**trace/stream_trace.h**
- `class StreamingTileTrace final : TileTrace` `trace/stream_trace.h:31`: ctor reads header `:37`; the
  seven `TileTrace` overrides `:40-46` (all except `n_tiles/n_cores/tile_tail` answer only for the
  window tile); `window_tile()` `:51` (-1 before first advance); `advance()` `:58`;
  `distinct_addresses(core)` `:76` (key comment `:69` names `[kh, kw, cin, cout, run_end]`);
  `header()` `:79`; `mac_cycles(t)` `:82`; `tick_base(t)` `:86` (prefix sum of mac_cycles, defined up
  to streamed+1).
- `shape_of(StreamHeader) -> WeightShape` `:119`.

**instrument/access_log.h** (header-only)
- `struct AccessRecord {u8 level, core, demand, pad; u32 line}` `instrument/access_log.h:63`, 8 bytes
  (`static_assert` `:70`).
- `class AccessLog(ostream&)` `:72,75`: `write_header` `:85` (u64 magic `0x5743414C4F473031`
  "WCALOG01", `:134`), `observe(level, core, line)` `:93` (throws if line > 2^32-1 or core > 255,
  `:135-136`), `records` `:125`, `flush` `:127`; batch 65536 records (`:141`); host-endian raw write.

**instrument/cache_state_log.h** (header-only)
- `class CacheStateLog` `instrument/cache_state_log.h:37`: ctor `(out, n_cores, l1_sets, l2_sets, l1_assoc,
  l2_assoc, core, tile, max_rows)` `:44`; `write_header` `:59` (CSV
  `time,tile,level,core,set,way,action,line,tag,ways_used`); `record(action, now, tile, level, core,
  line, set, tag, way)` `:74` (occupancy updated BEFORE filtering); `wants` `:89`; `written` `:95`;
  `truncated` `:96`; private `bump` `:104` (action starting with 'f' = fill).

**instrument/line_trace.h** (header-only)
- `class LineTrace` `instrument/line_trace.h:37`: ctor `(out, want_l1, want_l2, core, tile, line, max_rows)`
  `:60`; `write_header` `:70`; `on_fill` `:102` (filters applied here); `on_hit` `:118`; `on_leave`
  `:127`; `flush(now)` `:147` (emits open episodes as `end_of_run`, sorted by key); `written` `:159`;
  `truncated` `:160`; `still_open` `:161`; private `key` `:179` packs `(line<<7)|((core+1)<<1)|level`.
  CSV columns `:98-99`. Rows are in episode END order.

**instrument/hist.h** (header-only)
- `class DistinctAddressHistogram(StreamHeader)` `instrument/hist.h:35,40`: `observe(trace)` `:47` once per
  tile; `write_csv` `:56`; `p50` `:73` (nearest rank `min(n-1, floor(q*n))`); `max` `:75`; `samples`
  `:82`.

**instrument/stats.h**
- `struct RowIdentity {run_id, git_commit, arm="cache", tier}` `instrument/stats.h:24`.
- `csv_columns()` `:38` (single schema), `csv_header()` `:41`.
- `class RunStats` `:69`: ctor `:71`, `csv_row` `:80`, `check_invariants` `:92`.
- `oracle_row(id, cfg, hdr, tick_base_total)` `:111`.

**sweep.h**
- `class BroadcastSweep` `sweep.h:31`: `TileObserver` `:37`; ctor `(trace, mapper, configs,
  max_engines)` `:53`; `run(on_tile)` `:60`; `size` `:62`; `engine(i)` const `:63` / mutable `:71`;
  `config(i)` `:72`; `wall_seconds(i)` `:77` (time inside engine dispatch only).

**layout mappers**: see 2.2 with their sources (`layout/block_pack.h`, `layout/split_cin.h`, `layout/khkw_split.h`) and
the shared `src/layout/layout_common.h`.

### 2.2 `src/` (library `libcachesim.a`)

**config.cpp**
- `fail(what, pos)` `config.cpp:29`: `invalid_argument("config: ... at byte N")`.
- `struct Value` `:33`; `class Reader` `:39` (`skip_space`, `at`, `expect`, `expect_end`, `pos`,
  `read_string` (no escapes) `:70`, `read_value` (integer or string; rejects `.`/`e`) `:85`).
- Key tables `kI32Fields` `:135` (`l2_demand_reserve` at `:147`), `kI64Fields` `:153`; `to_i32`
  `:167`, `to_i64` `:176`, `enum_text` `:181`.
- `assign(cfg, key, value, pos)` `:186`: the single key dispatcher used by both parsers (comment
  `:187-188` describes the table lookup); enum spellings `:202-301`; unknown key fails `:303`.
- `reject` `:308`, `reject_below_one` `:312`, `reject_negative` `:318`, `check_level_geometry`
  `:324` (size >= one set, whole lines, whole sets), `warn` `:343`.
- `read_object_into(reader, cfg)` `:352` (duplicate keys refused); `struct GridAxis` `:378`.
- `RunConfig::line_size_bytes` etc. `:388-394` (integer division; validated later).
- `parse_config` `:398`; `parse_config_grid` `:408` (array form `:412-429`; base/axes form,
  mixed-radix enumeration with last axis fastest `:502-515`).
- `validate` `:521`: positivity `:523-541`; geometry `:543-545`; `cin_lo_blocks` resolved only under
  split_cin, must stay -1 otherwise `:551-570`; `l2_policy` follows `policy` if unset `:572`; random
  refused `:586,595`; rrip_bits in [1,8] `:592`; `lines_per_burst <= l1_mshrs` `:598`;
  `core_accept_ii >= 1` `:602`; L2 prefetch consistency `:613-625`; `l2_demand_reserve` resolved to
  lines_per_burst, must be `< l2_mshrs` `:629-639`, with the message "the reserve
  (lines_per_burst when unset) must leave at least one L2 MSHR free" (`:634-639`); `next_burst` needs
  distance > 0 `:641`; `l1_demand_reserve` resolved, must be `< l1_mshrs` `:646-655`; warnings
  `:657-686`.
- `to_engine_params` `:691`: copies fields; L1 has 1 bank; throws if not validated. The dead
  `p.l2.demand_reserve = 0` store is gone; the reserve is copied once (`:724`).

**core/engine.cpp** (loop, memory-side handlers, inclusion, instruments)
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
  stamp NoRefusal), `on_l2_probe` `:369` (the one site that increments both `l2_pf_timely` and
  `l2_pf_retriggers`, `:423-424`), `on_l2_fill` `:492` (L2 tag set `l2_prefetched_` update
  `:505-518`), `on_l1_fill` `:555`.
- Prefetch accounting: `demand_anchor_on_probe` `:624` (timely / pollution), `note_prefetch_resident`
  `:648`, `note_line_left_l1` `:652` (wasted), `close_out_prefetch_stats` `:660` (L1 only; the
  comment `:672-674` says so).
- Instruments: `current_tile` `:679` (core 0's tile), `way_of` `:683` (`slot % assoc`), `note_fill`
  `:698`, `note_leave` `:712`, `note_hit` `:723`.
- `back_invalidate(line, now)` `:733`, under its section header `:731`:
  scans all L1s by core id, invalidates + `on_invalidate`.

**core/engine_core.cpp** (core state machine, barrier, prefetch sink)
- `step_after(c, tile, k)` `:48` = `max(gap_k, core_accept_ii)`.
- `start_tile` `:55`, `barrier_arrive` `:95`, `on_barrier` `:114`, `on_issue` `:148` (re-throws a
  mapper `out_of_range` with tile/tick/core/burst context `:186-189`), `core_line_done` `:219`
  (prefetch completes nobody), `serve` `:241`.
- `n_bursts_in_tile` `:336`; `issue_prefetch` `:341`: budget `cap = l1_mshrs - l1_demand_reserve`
  per core; stops mid-burst when exhausted (already-issued lines of that burst stay in flight).

**core/cache_level.cpp**
- `refuse_if_waiting` `:32`; `charge_path(r, cause)` `:48` sets cause only if never refused.
- `CacheLevel::CacheLevel` `:54`: array first, then `make_policy` sized by `num_slots`, then
  `banks` ports; `sets_per_bank` clamped >= 1 `:95-96`.
- `bank_of` `:99`: 1 bank -> 0; else low bits `set % banks` or high bits `set / sets_per_bank`.
- `triage` `:112`: Belady occurrence consumed on every demand probe `:133-140`; array hit `:143-161`;
  matching entry `:164-187`; no slot `:190-205` (prefetch: DroppedReserve if free > 0 else NoSlot);
  primary miss `:208-219`.
- `install` `:222`: throws if already resident; free slot first, else `pick_victim`; passes the
  stored next-use to Belady; `on_fill`.

**core/mshr.cpp**
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

**core/port.cpp**: `Port::Port` `:32` (non-negative), `Port::reserve` `:54` (three lines).

**index/set_associative.cpp**
- `slot_or_reject` `:44`; ctor `:86` (order: size>=1, assoc>=1, line>=1, size % line == 0, lines <=
  INT32_MAX, assoc <= lines, lines % assoc == 0); `base_slot` `:190` (via `mapper.locate`).
- `probe` `:209`, `free_slot` `:221` (lowest free way), `victim_candidates` `:240` (clears then
  fills, whole set), `insert` `:264` (slot range-checked, line not), `invalidate` `:274`.

**replacement/policy.cpp**
- `make_policy` `replacement/policy.cpp:19` constructs the selected concrete policy and rejects RANDOM.

**replacement/stamp.cpp**
- `StampPolicy` constructor `replacement/stamp.cpp:23`, bound check `:28`, stamp/fill/invalidate/victim
  operations `:38-84`; LRU/FIFO hit behavior `:99-101`.

**replacement/belady.cpp**
- `BeladyPolicy` constructor `replacement/belady.cpp:18`, bound check `:26`, next-use notifications `:45-47`,
  maximum-next-use victim selection `:49`.

**replacement/lfu.cpp**
- `LfuPolicy` constructor `replacement/lfu.cpp:18`, count updates `:35-41`, victim selection `:43`.

**replacement/rrip.cpp**
- `RripPolicy` constructor `replacement/rrip.cpp:22`, RRPV updates `:45-53`, uniform aging and tie-break
  in `pick_victim` `:55-76`.
**prefetch/prefetcher.cpp**
- `NoPrefetcher` `:10-11`; `NextBurstPrefetcher` ctor `:13`, `pf_cursor` `:27`, `on_tile_start`
  `:31` (cursor 0), `on_demand_issue` `:39`: cursor = max(cursor, k+1); issue bursts while `cursor <=
  k+d` and `< n_bursts`; on budget failure returns WITHOUT advancing (retry next issue).
- `make_prefetcher` `:64`.
- `NoL2Prefetcher::suggest` `:92`; `NeighbourL2Prefetcher` ctor `:94`, `suggest` `:109` (order: +1,
  -1, +2, -2, ...); `make_l2_prefetcher` `:127`.

**index/set_index.h**
- `set_index(LineId, num_sets) -> Placement` `index/set_index.h:14`: shared modulo mapping, with
  `set = line % num_sets` and `tag = line / num_sets`; malformed set counts and negative line ids are refused.

**layout/layout_common.h / layout/layout_common.cpp** (namespace `cachesim::detail`, private to
`src/`, not installed under `include/`)
- The three mappers share argument checks, shape validation, burst walking and line-size diagnostics;
  each mapper keeps its own flatten, placement call and `neighbour`.
- `kAxes[4]` `layout/layout_common.h:28`; `reject` `:30` / `.cpp:10` (`invalid_argument`),
  `reject_range` `:31` / `.cpp:14` (`out_of_range`); `positive_or_reject` `:36`;
  `checked_mul` `:43` / `.cpp:18`; `blocks_covering` `:48`; `block_size_on` `:56`.
- `check_shape_and_blocking` `:72` / `.cpp:26`, `line_size_bytes` `:80` / `.cpp:41`,
  `check_in_shape` `:87`, `expand_burst<Mapper>` `:120-148`, and `line_size_terms` `:154` / `.cpp:47`.
**layout/block_pack.cpp** (`BlockPackMapper`, header `include/cachesim/layout/block_pack.h:42`; 235 lines)
- Nesting `[KH][KW][cin_blk][cout_blk]`, cout innermost; `kName` `layout/block_pack.cpp:14`; Axis-order `static_assert`s
  `:33-36`.
- Ctor `:40` (header `:64`): `check_shape_and_blocking` `:57`; block counts `:63-64`;
  `line_size_bytes_` `:77`; `num_lines = KH*KW*ncb*nkb` via `checked_mul` `:91-94`; strides
  `:118-124` (COUT 1, CIN `n_cout_blocks`, KW `n_cin_blocks*n_cout_blocks`, KH `KW*stride_KW`).
- `line_stride(Axis)` `:136`, `block_len(Axis)` `:152` (KH,KW raw; CIN,COUT block counts),
  `line_of(Coord)` `:162` (`check_in_shape` `:169`, then one loop over `kAxes` `:176-185`),
  `expand` `:200` (= `detail::expand_burst`), `locate` `:207` (= `set_index`),
  `line_size_terms` `:218`, `neighbour` `:226`. Accessors in header `:159-164`.

**layout/split_cin.cpp** (`SplitCinMapper`, header `include/cachesim/layout/split_cin.h:110`; 333 lines)
- Nesting `[KH][KW][cin_hi][cout_blk][cin_lo]`, `cin_lo = cin_blk % n_cin_lo` innermost, so with
  `n_cin_lo = L1 sets` the L1 set index is the CIN digit. `enum Digit` header `:99`;
  `static_assert`s on Digit order `:21-25`; `kName` `layout/split_cin.cpp:13`.
- `ceil_div` `:31` (int64 ceiling, see 3.2 item 1).
- Ctor `:37` (extra arg `n_cin_lo >= 1`, `:59`); `n_cin_hi = ceil(ncb / n_cin_lo)` `:69`;
  `radix_product` as an overflow guard `:99-104`; strides `:127-136`; `num_lines` = max id + 1
  `:155-160`, may be below the radix product (holes when n_cin_lo does not divide ncb), sanity check
  `:167-171`.
- `digit_stride` `:181`, `digit_radix` `:193`, `block_len` `:210`, `line_of` `:222` (the only cin
  split `:242-243`), `expand` `:275` (= `detail::expand_burst`), `locate` `:287`, `line_size_terms`
  `:300`, `neighbour` `:306` (CIN step recombines the two digits, `:333-341`). Accessors header
  `:189-196`.

**layout/khkw_split.cpp** (`KhkwSplitMapper`, header `include/cachesim/layout/khkw_split.h:70`; 186 lines)
- Nesting `[pos_hi][cout_blk][cin_blk][pos_lo]`, `pos = kh*KW + kw`, split at `n_pos_lo =
  min(kPosLoRadix=8, KH*KW)` (`layout/khkw_split.h:89`, `layout/khkw_split.cpp:34`). `enum Digit` header `:79`;
  `kName` `layout/khkw_split.cpp:14`.
- Ctor `:18`; `n_pos`, `n_pos_lo`, `n_pos_hi` `:33-35`; strides `:39-45`; `radix_product` `:50-52`;
  `num_lines` = max id + 1 via a loop over every `pos` `:63-71` (see 3.1 item 1 on its comment).
- `digit_stride` `:80`, `digit_radix` `:91`, `block_len` `:101`, `line_of` `:111`, `expand` `:135`
  (= `detail::expand_burst`; comment `:130-133`), `locate` `:139`, `line_size_terms` `:148`,
  `neighbour` `:154` (KH/KW step via pos, `:176-189`).

**trace/stream_trace.cpp**
- Constants: frame prefix 24, burst record 28, trailer 12 bytes `:14-18`.
- Ctor `:26` (reads fixed header, peeks `header_bytes` at offset 12, reads the rest, decodes).
- `n_tiles` `:59`, `n_cores` `:61`, `require_window` `:63`, `require_core` `:72`,
  `require_streamed` `:79`, `n_bursts` `:87`, `burst` `:94`, `local_tick` `:105`, `gap` `:116`
  (k in [0, n-1)), `distinct_addresses` `:130` (unique `(kh,kw,cin,cout,count)` tuples, `:146-152`),
  `tile_tail` `:157`, `mac_cycles` `:162`, `tick_base` `:167`.
- `advance` `:176`: decodes one frame into reused buffers; validates tile index, core ordering,
  n_bursts >= 1, strictly increasing ticks, non-empty runs, payload length, `tail = mac - max_tick
  >= 1` (`:319-325`). v2 record fields read at `:270-275` (field 3 is `cout`); anchor
  `Coord{kh, kw, cin, cout}` `:292`; `run_start = coord_on(anchor, axis)` `:293`; empty-run refusal
  names the axis `:294-301`; `Burst{anchor, header.burst_dim, run_end - run_start,
  header.burst_stride}` `:306`.
- `read_trailer` `:337`; `shape_of` `:354`.

**instrument/stats.cpp**
- `name_of` overloads for PolicyKind `:16`, LayoutKind `:28`, Inclusion `:37`, PrefetchKind `:45`;
  `total` `:53`; `quantile` `:60`.
- `class Row` `:71`: `str` (refuses `, " \n \r`) `:73`, `i64` `:86`, `f64` (`%.6f`) `:91`, `ratio`
  (empty cell when denominator 0) `:101`, `blank` `:109`, `blank_rest` `:115`, `take` `:120`; every
  cell checked against the schema position (`expect` `:130`).
- `emit_identity` `:144`, `emit_config` `:156` (comment `:178-179` points to where
  `l2_demand_reserve` is written), `emit_headline` `:195`.
- `csv_columns` `:203` (112 columns; `l2_demand_reserve` `:227`; `rrip_bits` appended last `:243`),
  `csv_header` `:247`.
- `RunStats::RunStats` `:256`: `hidden_latency = fetch_latency_sum - core_stall_sum` `:274`, derived
  `dram_bytes = dram_accesses*line_size` `:291`, `pf_coverage = (timely+late) / demand_bursts`
  `:334`, L2 prefetch config then outcomes `:340-363` (`l2_demand_reserve` `:349`),
  `l2_pf_coverage = l2_pf_timely / l2_accesses` `:364` (comment `:361-363`: also the retrigger
  ratio), `port_bound_threshold = miss_frac * l2_miss_latency * l2_banks / l2_ii` `:373-381`, MSHR
  occupancy p50/p95/max `:383-395`, `events_per_cycle` `:400`.
- `csv_row` `:409`; `check_invariants` `:418-450`: stall causes sum == stall_total, hidden_latency >=
  0, L1 prefetch outcomes + drops == pf_issued.
- `oracle_row` `:452`: identity + config + `total_cycles = tick_base_total`, rest blank.

**sweep.cpp**
- `layout_text` `:14`; `rethrow_with_index` `:27` (prefixes "sweep: configuration i:" preserving
  exception type).
- Ctor `:44`: non-empty grid, `size <= max_engines`, all points share `cin_block, cout_block,
  weight_bytes, layout, cin_lo_blocks` `:76-91`, mapper line size matches `:93`, then builds engines.
- `run` `:112`: per tile `advance` -> observer -> `step_tile` on each engine (timed); then `finish`
  each. Accessors `:146-152`.

### 2.3 `apps/`

**app_support.h** (namespace `cachesim::app`)
- `UsageError` `:48`; `value_of` `:52`; `int_value_of` `:60` (whole-string integer); `check_arm`
  `:76`; `uuid4` `:86` (`std::random_device`, unseeded by design).
- `make_mapper(cfg, shape, warnings)` `:116`.
- `lines_per_burst(mapper, hdr)` `:163`: expands the widest burst `{origin, burst_dim, burst_span,
  burst_stride}` (`:165`) and counts lines. Both apps pass a BlockPackMapper for any layout
  (`:156-161`).
- `class PaddingMeter` `:184`: `observe(burst)` `:197`, `observe_tile(trace)` `:215`, `fraction()`
  `:226` = `(lines_touched*cin_block*cout_block - elements_touched) / (lines_touched*...)`.
- `class TraceFd(spec)` `:255`: `-`, `fd:N`, or path (owned, closed in dtor); `get` `:275`.
- `write_out(path, text)` `:282` (`-` = stdout; else truncating ofstream `:288`).
- `read_oracle_lines(path, n_cores, l1_by_core*, l2_lines&)` `:322`: reads an AccessLog file;
  demand records only; per-core L1 lists + one L2 list.
- `struct OracleSet {l1 vector, optional l2, attached}` `:376`; `build_oracles` `:386`;
  `attach_oracles(oracles, cfg, engine)` `:416` (only levels whose policy is Belady);
  `report_oracles` `:437`; `report_overruns` `:474` (warns if `max_wait_depth != 0` with Belady,
  `:481-487`: re-probes shift occurrence indices).

**cachesim_run.cpp**: `kUsage` `:39` (header help `:46-47`), `struct Options` `:117` (`header = true`
`:140`), `parse_args` `:148` (`--header`/`--no-header` `:183-184`), `run` `:216` (steps in 1.3;
Belady oracle checks `:310-340`; instruments `:281-365`; truncation notes `:391-406`; header
emitted iff `opt.header` `:417`), `main` `:430`.

**cachesim_sweep.cpp**: `kUsage` `:34`, `struct Options` `:77`, `parse_args` `:91`, `read_file` `:123`,
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
- `stream_builder.h`: an independent second WCTS writer used by the reader tests. Writes
  version 2 (`stream_builder.h:104`), takes a `burst_dim` argument defaulting to COUT (`:23`), and
  `add_burst(tick, kh, kw, cin, cout, run_end)` (`:44`).

Unit test binaries (`Makefile:57`, one binary per `tests/test_*.cpp`):
- `test_types.cpp`: Tagged scalars and tensor geometry helpers.
- `test_layout.cpp`: `Placement` and `AddressMapper` contracts via conformance checks.
- `test_layout_golden.cpp`: pins the observable mapping of all three layouts. 185 cases: 6 shapes x 5
  blockings x {block_pack, split_cin at 4 `cin_lo` values, khkw_split} (`:202-230`) plus 5 refusal
  cases (`:231-248`). Each case folds `num_lines`, `line_size_bytes`, `line_size_terms`, `line_of`
  of every coordinate, `expand` of bursts on every axis and `locate` under set counts {1,3,8,64}
  (`:69`) into one FNV-1a hash, compared with `kGolden` (`:253`). `--print-golden` regenerates the
  table (`:447-453`).
- `test_block_pack.cpp`: BlockPackMapper construction, validation, strides, `line_of`, `expand`,
  `locate`.
- `test_split_cin.cpp`: SplitCinMapper end to end, including the "count is layout-independent"
  property `lines_per_burst` relies on.
- `test_khkw_split.cpp`: KhkwSplitMapper flatten, per-core set coverage, interface contracts.
- `test_neighbour.cpp`: `neighbour` on all three mappers, checked against `line_of` of the
  neighbouring coordinate.
- `test_cache.cpp`: `CacheArray` interface shape, `Candidate`, `InsertResult`.
- `test_set_associative.cpp`: SetAssociativeArray geometry refusals and the five verbs.
- `test_stamp.cpp`, `test_belady.cpp`, `test_lfu.cpp`, `test_rrip.cpp`: the replacement interface and
  each policy family behavior and order independence.
- `test_port.cpp`: `Port` reservation arithmetic.
- `test_event.cpp`: EventQueue total order and determinism.
- `test_mshr.cpp`: MshrFile entries, targets, waits, refusal counter, grant loop.
- `test_cache_level.cpp`: CacheLevel triage table branch by branch.
- `test_engine.cpp`: event loop handlers, core state machine, tile barrier, inclusion.
- `test_prefetcher.cpp`: prefetch interface and `none` vs `next_burst`; `test_prefetch_engine.cpp`:
  engine integration and drop rules.
- `test_config.cpp`: RunConfig parse, defaults, validation rules, among them
  `test_the_l2_mshr_floor_holds_a_burst_with_one_to_spare` (`test_config.cpp:204`): default
  `l2_mshrs` is 20, `lines_per_burst` 19 passes and resolves the reserve to 19, 20 is refused with
  the reserve message and without the word "prefetch".
- `test_stats.cpp`: CSV schema, RunStats, invariants, oracle row.
- `test_stream_format.cpp`: WCTS header round trip and corruption cases, byte sources, among them
  `test_v1_header_is_refused_with_the_regenerate_message` (`test_stream_format.cpp:113`, versions 1
  and 3).
- `test_stream_trace.cpp`: StreamingTileTrace against the TileTrace contract, format rejections, among them
  `test_every_burst_axis_round_trips` (`test_stream_trace.cpp:225`, one burst per axis decodes
  to its full anchor and count) and `test_empty_run_on_a_non_cout_axis_throws` (`:253`).
- `test_hist.cpp`: distinct-address histogram and sidecar.
- `test_sweep.cpp`: BroadcastSweep equals N independent runs.

Drivers:
- `compile_fail.sh`: negative compile cases (type mixing, abstractness, const overrides), `-fsyntax-only`.
- `mutation_check.sh`: mutates library files in place, expects `make test` to go red; restores from
  backups. Its file list and the A2b mutations target `src/layout/layout_common.h` / `.cpp`
  (`mutation_check.sh:79`, helpers `mutate_lc_h` / `mutate_lc` at `:227-228`).
- `run_cli.sh`: `cachesim_run` end to end on a fixture converted by `examples/to_stream.py`. Step
  11 (`run_cli.sh:203-220`): `--out` gets a header by default on a new and on an overwritten file,
  and `--no-header` drops it.
- `sweep_cli.sh`: `cachesim_sweep` end to end, compares with `cachesim_run` rows.
- `v1_pipe.sh`: invariant V1 (unbounded cache, zero latency -> `tile_origin[N] == tick_base[N]`),
  plus two deliberately broken runs that must fail. ("V1" here is the invariant name, not the WCTS
  version.)
- `cout_golden.sh` + `cout_golden.csv` (run by `make test-cli`,
  `Makefile:146`): converts the committed loas example to a v2 stream, asserts the stream's version
  is 2 (`cout_golden.sh:35-36`), runs a 4-point grid through `build/fixture/cachesim_sweep`
  (`:12,30-31`), and requires the CSV to equal the golden captured from the v1 reader on the same
  stream, ignoring only `git_commit` and `sim_wall_seconds` (`:38-48`).

### 2.5 `src/cachesim/*.py` and `src/cachesim/examples/`

- `src/cachesim/__init__.py`: docstring only (`src/cachesim/__init__.py:1`).
- `src/cachesim/__main__.py`: `python -m cachesim` runs `cachesim.cli.main` (`src/cachesim/__main__.py:1-4`).
- `src/cachesim/cli.py`: the `grid` / `sweep` / `run` dispatcher of 1.2. `sweep` and `run` are dispatched before
  argparse sees the arguments, so every native flag (and `--help`) reaches the binary unchanged.
- `src/cachesim/grid.py`: `ROOT` = repo root from `__file__` (`src/cachesim/grid.py:7`), `BASE_JSON` /
  `SWEEP_JSON` (`:8-9`); `load_base` `:12`, `load_sweep` `:16`; `grid_for(line_bytes, base, sweep)`
  `:20` (the points at one line size; keys stay in `base.json` order); `full_grid` `:32` (line size
  slowest); `write_grid(out_dir, grid, name="khkw")` `:39` (one file per `cin_block` in order of first
  appearance, because `cachesim_sweep` builds one mapper per grid file; returns `{cin_block: path}`).
- `src/cachesim/stream.py`: the WCTS v2 writer (module docstring `:1-5`; byte layout comment `:28-39`). Constants
  `WCTS_MAGIC` `:42`, `WCTS_VERSION = 2` `:43`, `WCTS_FIXED_HEADER_BYTES = 56` `:44`,
  `WCTS_END_MAGIC = -1` `:45`, `WCTS_DIM_CODES` `:49`, `WCTS_ADDR_FIELDS` `:52`.
  `write_stream_header` `:56`; `write_tile_frame` `:98` (core ids strictly ascending `:111`, no empty
  core `:113`, ticks strictly ascending `:119`, non-empty run `:124`); `write_stream_trailer` `:135`;
  `_wcts_tile_frames(tiles, n_cores)` `:140` (tick-major to core-major, core id range check `:154`,
  `burst_span` = largest `cout_end - cout_start` `:166`, no bursts refused `:172`);
  `stream_weight_trace(trace, fh, *, n_cores, spatial_factors, burst_dim=3, burst_stride=1,
  weight_bytes=1, max_tiles=None)` `:177` (only `burst_dim = 3` `:195`; `max_tiles` cut before the
  header `:201`; returns the burst count `:219`).
- `src/cachesim/examples/to_stream.py`: `python3 to_stream.py <fixture.json> [max_tiles] > slice.wcts`
  (docstring `:3`). `load(path)` `:41` turns a v2 example JSON into `weight_trace_gen.weight_trace`
  dataclasses; `main` `:60` calls `stream_weight_trace(..., n_cores=N_CORES, spatial_factors={3:
  N_CORES}, max_tiles=...)` (`:64-65`, `N_CORES = 8` at `:38`) to stdout. Adds `src/` to `sys.path`
  (`:20`) and stubs `weight_trace_gen.trace` when its import fails (numpy absent, `:22-32`). Used by
  the four CLI test scripts.
- Data: `loas_vgg16_layer01_v2.json`, `ptb_resnet19_layer01_v2.json`,
  `prosperity_vgg16_layer01_v2.json`, `spinalflow_vgg16_layer01_v2.json` (JSON v2: tiles -> ticks ->
  cores -> `weight_addresses` `[kh,kw,cin,cout_start,cout_end]`),
  `gustavsnn_vgg16_layer01_v1_legacy.json` (JSON v1, cannot drive the engine, `src/cachesim/examples/to_stream.py:5-6`),
  `manifest.json` (provenance). The `_v1` / `_v2` in the file names is the weight-trace JSON shape,
  not the WCTS version.

---

## 3. Findings for cleanup (code-evidenced)

### 3.1 Dead code, stale comments, stale references
1. **`layout/khkw_split.cpp` comments state a false premise about the sort and the max loop.** The comment
   above `expand` says the sort in `expand_burst` is load-bearing because "line_of is NOT monotone in
   pos" and a wrap "can move the line down" (`src/cachesim/native/src/layout/khkw_split.cpp:130-133`). By the
   code's own arithmetic it cannot: the position term is `(pos / L) * S + pos % L` with
   `L = n_pos_lo` and `S = stride[POS_HI] = n_cout_blocks * n_cin_blocks * L >= L`
   (`layout/khkw_split.cpp:39-45,123,126`). Stepping `pos` inside a group adds 1; a wrap adds
   `S - (L - 1) >= 1`. So `line_of` is strictly increasing in `pos`, the sort is a no-op on this
   layout exactly as on the other two (`layout/block_pack.cpp:195-199`, `layout/split_cin.cpp:260-274`), and the
   ctor comment "the largest sum is not in general at the largest pos" (`layout/khkw_split.cpp:59-62`) is
   wrong for the same reason. The code is correct (the sort is harmless and the loop finds the true
   maximum); only the stated reasons are wrong. Derived by hand, not by running code.
2. Stale test names that contradict their own group strings: `test_l2_demand_reserve_is_rejected_by_name`
   checks that the key is live (`tests/test_config.cpp:178-179`); `test_l2_demand_reserve_is_not_a_column`
   checks that it is a column (`tests/instrument/test_stats.cpp:155-156`). `test_stream_format.cpp:158` labels
   the v2 field-order check "v1 address field order".
3. The comment above the L2 reserve rule still gives prefetching as its reason ("makes prefetching
   unreachable while claiming to be on", `src/config.cpp:626-628`), while the message itself
   describes an MSHR floor that holds whatever the prefetch policy is (`config.cpp:634-639`) and
   `test_config.cpp:204-226` asserts the message does not mention prefetching.
4. References to an archive that is not in the repo: `src/layout/block_pack.cpp:167` ("the v1 lesson the archive
   preserved"), `tests/layout/test_block_pack.cpp:831`, `tests/index/test_set_associative.cpp:21`. Also
   `layout/block_pack.cpp:26-29` says "the expression is not written yet", while `line_of` (`:162`) is.
5. Doubled prefix in the `neighbour` range messages: `reject_range(kName, "BlockPackMapper::neighbour:
   ...")` prints "BlockPackMapper: BlockPackMapper::neighbour: ..." (`src/layout/block_pack.cpp:223`; same
   at `src/layout/split_cin.cpp:303`, `src/layout/khkw_split.cpp:151`). Runs of three blank lines: `layout/block_pack.cpp:215-217`, `layout/split_cin.cpp:297-299`, `layout/khkw_split.cpp:145-147`.
6. `EngineStats::pf_dropped_targets_full` (`include/cachesim/core/engine.h:214`) is never incremented
   anywhere in `src/`; it is always 0 by construction (read only at `src/instrument/stats.cpp:270,326`).
   `Request::reason` (`include/cachesim/core/request.h:34`) is written (`src/core/mshr.cpp:64`) but never read in
   `src/` or `apps/`. `CoreState::issued_at` is written (`src/core/engine_core.cpp:64,193`) and never read
   in `src/`/`apps/`.
7. `replacement/next_use.h:29` includes `<istream>`, which nothing in the file uses.
8. `LevelParams::bank_high_bits` (`include/cachesim/core/cache_level.h:131`) has no config key (absent from
   `config.cpp:135-165`, never set in `to_engine_params`), so the high-bits banking branch
   (`src/core/cache_level.cpp:103`) is reachable only from tests.
9. Output still names the simulator `wcache`: the comment line the line trace writes
   (`include/cachesim/instrument/line_trace.h:71`) and the one the cache-state log writes
   (`include/cachesim/instrument/cache_state_log.h:60`). The writer's comment points at a plan and a ruling that
   are not in the repo (`src/cachesim/stream.py:21`, `:25`).

### 3.2 Duplicated logic
1. Mapper helpers: the checks, `expand`, `locate` and `line_size_terms` live in
   `src/layout/layout_common.h` / `.cpp` (2.2). What is still duplicated: an int64 ceiling written twice more,
   `ceil_div` (`src/layout/split_cin.cpp:31`) and the inline `n_pos_hi_` ceiling
   (`src/layout/khkw_split.cpp:35`), beside `detail::blocks_covering` (`layout/layout_common.h:48`, int32
   extent); and the same `neighbour` range-check block in each mapper (`layout/block_pack.cpp:222-226`,
   `layout/split_cin.cpp:302-306`, `layout/khkw_split.cpp:150-154`). `neighbour` staying per mapper is by design
   (`layout/layout_common.h:5-6`).
2. Enum spellings are written in several places: parse (`src/config.cpp:202-301`), emit
   (`src/instrument/stats.cpp:16-51`), `layout_text` (`src/sweep.cpp:14-21`), a two-way ternary over the
   three-valued `LayoutKind` (`config.cpp:560`, exactly the pattern `sweep.cpp:10-13` warns against;
   correct today only because SplitCin is excluded by the branch), and an inline ternary for
   `L2PrefetchKind` (`instrument/stats.cpp:344`).
3. Nearest-rank quantile twice: `include/cachesim/instrument/hist.h:85-92` and `src/instrument/stats.cpp:60-65`.
4. `engine_error` / `idx` twice: `src/core/engine.cpp:18-22`, `src/core/engine_core.cpp:31-35`. Way-from-slot
   arithmetic twice: `core/engine.cpp:692-695` and `core/engine.cpp:755-758`.
5. Per-policy `index_or_reject` four times: `src/replacement/{stamp,belady,lfu,rrip}.cpp`.
6. The two apps duplicate the config/trace/mapper/validate setup and drift:
   - `--max-engines` uses bare `std::stoi` (`apps/cachesim_sweep.cpp:107`, accepts `"12abc"`) while
     `cachesim_run` uses `int_value_of` (`app_support.h:60`).
   - Oracle help text disagrees: L1 oracles "exact WHILE NOTHING BLOCKS" (`cachesim_run.cpp:88-93`) vs
     "EXACT" (`cachesim_sweep.cpp:64-66`).
   - Sweep has no `--l2-oracle`, instruments, or `--oracle-only`.
   - AccessLog batch size `1 << 16` duplicated in `instrument/access_log.h:141` and `app_support.h:336`.

### 3.3 Behaviour hazards worth a look before trusting new runs
1. **H2** `LineTrace::key` packs `core+1` into 6 bits with no check (`include/cachesim/instrument/line_trace.h:179-182`); the comment says a wider machine "would trip the encoding" (`:175-178`), but nothing
   trips, so with more than 62 cores keys alias silently. `AccessLog` allows 255 cores
   (`instrument/access_log.h:136`); the code mentions 256-core targets (`core/event.h:240-243`).
2. **H4** L2 prefetch accounting is not closed: `close_out_prefetch_stats` handles L1 only
   (`src/core/engine.cpp:660-675`), lines still tagged in `l2_prefetched_` at end of run are not charged
   as wasted, and `check_invariants` checks only the L1 identity (`src/instrument/stats.cpp:418-450`). The gap is
   stated in comments (`core/engine.cpp:672-674`, `core/engine.h:244-247`,
   `instrument/stats.cpp:341-343`).
3. **H6** MSHR occupancy samples are appended on every forward and retire
   (`src/core/engine.cpp:267,394,533,602`) and kept for the whole run per engine; memory grows with miss
   count times grid size (up to 256 engines).
4. **H7** `TraceFd` parses `fd:N` with unchecked `std::stoi` (`app_support.h:261`).
5. **H8** The decoded run length ignores `burst_stride`: `count = run_end - run_start`
   (`src/trace/stream_trace.cpp:306`) while `expand_burst` walks `start + i*stride` for `i < count`
   (`layout/layout_common.h:138-139`). For stride `s > 1` a run `[start, end)` holds
   `ceil((end - start) / s)` elements, but the decoder asks for `end - start` of them, so the walk
   runs past `run_end` (or is refused as out of range). The writer does the same: `burst_span` is the
   largest `cout_end - cout_start` (`src/cachesim/stream.py:166`) and `lines_per_burst` expands
   `burst_span` elements at `burst_stride` (`app_support.h:165`). Unreachable today because
   `stream_weight_trace` defaults `burst_stride=1` (`src/cachesim/stream.py:178`) and every test uses 1
   (`tests/stream_builder.h:110`).
6. **H9** The header's `burst_span` is never checked against the bursts. `decode_header` only
   requires `burst_span >= 1` (`trace/stream_format.h:258-262`) and `advance` never reads it
   (`src/trace/stream_trace.cpp:176-335`), yet `lines_per_burst` (`app_support.h:163-169`) is computed
   from it and sets the `l1_mshrs` check (`config.cpp:598`) and both demand-reserve defaults
   (`config.cpp:629,646`). A header that understates the span passes validation. Separately,
   `lines_per_burst` expands the burst at the origin; a burst whose anchor is not block-aligned can
   touch one more line than that (span 16 at `cout_block` 16 starting at cout 8 covers 2 lines, not
   1). Derived from the code; the engine's response to a burst wider than the reserve was not traced.
7. **H10** `run_end - run_start` is an `int32_t` subtraction (`src/trace/stream_trace.cpp:306`). The
   decoder checks only `run_end > run_start` (`:294`); coordinates are range-checked later, by the
   mapper. A corrupt record with a very negative anchor coordinate and a large `run_end` overflows
   the subtraction (undefined behaviour) before any range check runs. Corrupt input only.
8. `mutation_check.sh` edits library sources in place and restores from a backup dir
   (`tests/mutation_check.sh:80-82`); an interrupted run can leave mutated sources behind.

### 3.4 Hardcoded values, paths, host assumptions
- `CXX := g++` pinned, ignoring the environment (`src/cachesim/native/Makefile:24`, rationale about the
  Delta Cray wrapper at `:19-22`), while `compile_fail.sh` honours `${CXX:-g++}`
  (`tests/compile_fail.sh:21`).
- `JOBS` default 32 = the dev machine's `nproc` (`tests/compile_fail.sh:35,56`,
  `tests/mutation_check.sh:119`).
- `cout_golden.sh` always runs `build/fixture/cachesim_sweep` (`tests/cout_golden.sh:12`), so
  `make MODE=release test-cli` builds release apps and then tests the fixture binary (or fails if
  it was never built).
- `to_stream.py` hardcodes 8 cores and `spatial_factors={3: 8}`
  (`src/cachesim/examples/to_stream.py:38,64-65`).
- `python -m cachesim sweep` / `run` always run the `build/release` binaries and build them only when
  the file is missing (`native` in `src/cachesim/cli.py`), so a binary older than the sources is run
  as is.
- The grid defaults are fixed files: `configs/cache/base.json` and `configs/cache/khkw_sweep.json`
  (`src/cachesim/grid.py:8-9`), found from the repo root `ROOT` (`src/cachesim/grid.py:7`).
- Magic numbers in code: `kPosLoRadix = 8` (`include/cachesim/layout/khkw_split.h:89`); RRIP width cap 8 twice
  (`src/replacement/rrip.cpp:11`, `src/config.cpp:592`); `--max-engines` 256
  (`apps/cachesim_sweep.cpp:84`); AccessLog record limits 32-bit line / 8-bit core
  (`instrument/access_log.h:135-136`).
- `trace/stream_format.h:35-37` requires the GCC/Clang `__BYTE_ORDER__` macro.
- No absolute paths or hostnames appear in any `.cpp/.h/.sh/.py` file in scope (grep for `/home/`,
  `/projects/`, `/scratch`, `delta`, `ncsa` hits comments only).

### 3.5 Build products in git
None: `git ls-files src/cachesim/native/build` is empty; `build/` is ignored by
`src/cachesim/native/.gitignore:1`; `__pycache__/` by the root `.gitignore:2`. Local
`src/cachesim/native/build/fixture/` and `build/release/` exist (untracked). Note the repo-wide `*.json`
ignore (`.gitignore:23`) with exceptions only for `configs/**` (`.gitignore:32`) and
`src/cachesim/examples/*.json` (`.gitignore:38`): a run config written anywhere else is silently
untracked.

---

## 4. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

What the code needs:
- **Compiler/build**: GNU make and `g++` with C++17 (`Makefile:24-26`); flags `-Wall -Wextra
  -Wpedantic -Wsign-conversion -Wconversion -Wshadow` (`Makefile:27`), `-O0 -g` (fixture) or
  `-O2 -DNDEBUG` (release, `Makefile:31-34`). No CMake (no `CMakeLists.txt` exists). No third-party
  libraries; POSIX headers (`unistd.h`, `fcntl.h` in `trace/byte_source.h:17`, `app_support.h:15-16`).
  `ar` for the archive. Minimum g++ version is not pinned anywhere. `src/layout/layout_common.cpp` is picked
  up by `SRCS := $(sort $(shell find src -type f -name '*.cpp' -print))` (`Makefile:42`).
- **Release programs**: `make release` builds only `libcachesim.a` (`Makefile:181-182`).
  `python -m cachesim sweep` / `run` need `build/release/cachesim_sweep` / `cachesim_run` and build
  them with `make MODE=release apps` when they are missing (`src/cachesim/cli.py`).
- **Tests**: `make test` needs only the compiler and bash; `wait -n` in `compile_fail.sh:109` needs
  bash >= 4.3. `make test-cli` needs `python3` (override with `PYTHON`) and importable `cachesim.stream`
  and `weight_trace_gen.weight_trace` (`src/cachesim/examples/to_stream.py:20`, `:34-36`); numpy is optional thanks to the
  stub.
- **Inputs**: real runs need WCTS **v2** streams, written by `python -m weight_trace_gen gen --stream`
  (`stream_weight_trace`, `src/cachesim/stream.py:177`) from a schedule and the input traces under
  `input_trace/`; `scripts/pipeline.py` writes them under its output directory. Only the five small
  example slices are committed (`src/cachesim/examples/`). A version-1 stream is refused (top note).
  For COUT streams a v2 stream gives the same rows as the v1 reader did (`tests/cout_golden.sh` checks
  this on one fixture).
- **Two-pass Belady**: `policy/l2_policy = belady` needs `--oracle` / `--l2-oracle` from a prior
  run's `--access-log` over the same trace and layout (`cachesim_run.cpp:310-340`); results are only
  sound when `max_wait_depth == 0` (`app_support.h:481-487`).
- **Non-deterministic columns**: `run_id` defaults to a random UUID (`app_support.h:86`),
  `sim_wall_seconds` is wall time, and `git_commit` is empty unless the driver passes it
  (`cachesim_run.cpp:52-53`). Everything else is designed to be bit-identical across runs (total event
  order, vectors iterated by index; `unordered_map`s are never iterated in decision paths, though
  `LineTrace::flush` sorts its map keys `instrument/line_trace.h:148-151`).
- **Binary formats**: the AccessLog is written in host byte order with no endianness marker
  (`instrument/access_log.h:129-130`), unlike WCTS, which is explicitly little-endian. The WCTS magic did not
  change between v1 and v2 (`trace/stream_format.h:41`); only the version field tells them apart.
- **Paths**: `src/cachesim/cli.py` and `scripts/pipeline.py` locate the binaries and configs from the
  repo root (`ROOT`, `src/cachesim/grid.py:7`), not through absolute paths.

---

## 5. Open questions the code alone cannot answer

1. Should `burst_stride > 1` be supported? If so, should the record's `run_end` stay an element
   bound (and the decoder compute `ceil((run_end - run_start) / stride)`), or become a count (H8)?
2. Should the reader check each burst against the header's `burst_span`, and should
   `lines_per_burst` account for anchors that are not block-aligned (H9)?
3. Should tagged-but-unused L2 prefetched lines be charged as wasted at end of run, and should the L2
   identity be enforced in `check_invariants` (H4)?
4. Is `l2_policy` meant to appear in the CSV? The schema has only `policy` (`src/instrument/stats.cpp:214`), so
   a row with a different L2 policy is not self-describing.
5. Is `bank_high_bits` meant to be a sweepable knob (3.1 item 8)?
6. What core-count ceiling must the instruments support (LineTrace 62, AccessLog 255)?
7. Which g++ version produced the committed results, and do Delta runs use the same one?
8. Is the separate `l2_pf_retriggers` column kept for a reason beyond history, given it always equals
   `l2_pf_timely`?

---

### Not covered
- `tests/*.cpp` and the two big shell drivers were summarised from their header comments and
  targeted greps, not read line by line.
- `src/cachesim/native/compile_flags.txt` was not read (`.txt` is excluded by the reading rules).
- `src/weight_trace_gen`, which builds the `LayerWeightTrace` that `stream.py` writes, is covered in
  `docs/atlas/pipeline.md`.
- `src/cachesim/cli.py` is described without line numbers.
- `python -m cachesim grid`, `sweep` and `run` were run once on one stream (resnet19 layer 9,
  sample 0) to check 1.2; every other behaviour claim comes from reading the code.
