# Phase D Implementation Plan (A3 + producer stream + D1 + D2 + D3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the streaming trace reader (A3), the in-flight producer that feeds it,
and the three Phase D units (config load, statistics + results CSV, sweep driver), so
that a weight trace generated in flight streams over a pipe into a grid of wcache
engines and comes out as one CSV row per run.

**Architecture:** A binary stream replaces the JSON round trip. The producer
(`tracegen.py` plus the five archmodel `main.cpp` files) emits a stream header followed
by one length-prefixed frame per tile; the consumer (`StreamingTileTrace`) holds a
one-tile sliding window and satisfies the existing pure-virtual `TileTrace` interface
unchanged, so the engine never learns which reader it has. `wcache_sweep` reads that
stream once and drives every configuration in a grid over it in broadcast lockstep: all
engines consume the same tile, and the window advances when all of them have finished it.

**Tech Stack:** C++17 (g++, `-std=c++17`, hand-rolled `make`, no external libraries),
Python 3 in the `cosa_snn` conda environment, Slurm on NCSA Delta.

**Spec:**
- `/home/ya867177/neuro_cache-wcache/log/2026-08-20-phaseD-sweep-profiling-plan.md`
  (campaign plan; §10 is the streaming design, §9.2 the row schema, §4.5 the D1 guards)
- `/home/ya867177/neuro_cache-wcache/log/2026-08-17-wcache-event-driven-plan-v3.md`
  (engine plan; Phase D at lines 1358-1364, Part 8 stats at 1417-1471, V1/V21/V27 at 1380/1402/1409)
- `/home/ya867177/neuro_cache-wcache/log/2026-08-05-cachesim-redesign-plan.md:534-575`
  (the process-boundary CLI contract)

---

## Global Constraints

Every task's requirements implicitly include this section.

- **No commits.** This build leaves everything in the working tree. Do not run
  `git commit`, `git add`, `git push`, or `git stash` at any point. The "Commit" step
  that `superpowers:writing-plans` normally ends a task with is replaced throughout by a
  **Checkpoint** step that runs the full suite and stops.
- **No em-dashes in any prose** written into the repo (markdown, comments, docstrings,
  help text). Use a comma, a colon, or a full stop.
- **Python runs through conda:** `conda run -n cosa_snn python ...`. Never a bare
  `python`/`pip`/`pytest`.
- **LaTeX, if any, builds through `latexmk`.** No task here builds LaTeX.
- **Build modes:** `make` in `/home/ya867177/neuro_cache-wcache/src/wcache/native`
  defaults to `MODE=fixture` (`-O0 -g`). `MODE=release` is `-O2 -DNDEBUG`. Every
  validation that must survive the sweep is a `throw`, never an `assert`, because the
  sweep build is `-DNDEBUG` (v3 `:1362`, D12).
- **Warning flags are load-bearing:** `-Wall -Wextra -Wpedantic -Wsign-conversion
  -Wconversion -Wshadow`. New code must compile warning-clean at those flags.
- **Baseline that must never regress:** `make clean && make test` green, **316 compile
  cases and 24,850 checks, 0 failures** (`PROGRESS.md` B161). Every task's Checkpoint
  step re-runs it, and the check count may only ever go **up**.
- **`tests/mutation_check.sh` has an explicit `FILES=` list at line 65.** Every new
  `include/wcache/*.h` and `src/*.cpp` this plan creates must be added to it by hand, or
  it is silently never mutation-tested.
- **The Makefile globs `src/*.cpp` into `libwcache.a`.** A translation unit defining
  `main()` must therefore **not** live in `src/`, or every test binary fails to link with
  a duplicate `main`. Programs live in a new `apps/` directory with explicit rules.
- **`tests/test_*.cpp` is the glob for test binaries.** A new test must be named
  `tests/test_<name>.cpp`, define its own `main()`, and end with `return check::summary();`.
  There is no registration mechanism: a new case must be called from `main()` by hand.
- **Fixed parameter values this campaign adopts** (§6.3, §7.3), all sweepable, these are
  defaults: `l1_assoc = 8`, `l2_assoc = 16`, `policy = lru`, `inclusion = non_inclusive`,
  `l1_mshrs = 16`, `l1_tgts_per_mshr = 20`, `l2_mshrs = 20`, `l2_tgts_per_mshr = 12`,
  `l1_latency = 0`, `l2_latency = 10`, `l2_miss_latency = 100`, `l1_ii = 1`, `l2_ii = 1`,
  `l2_banks = 1`, `l2_to_l1_latency = 0`, `core_accept_ii = 1`,
  `l1_demand_reserve = lines_per_burst`, `prefetch_policy = none`, `prefetch_distance = 0`.
- **`l2_demand_reserve` is rejected at config load** (ruling Q8) and is **not** a CSV
  column (G11).
- **This machine is build, test and demo only** (R7). No campaign tier, no full trace
  corpus, no Delta submission. The Slurm scripts are written here and run elsewhere.

---

## File Structure

Everything below is under `/home/ya867177/neuro_cache-wcache/`.

**New C++ headers** (`src/wcache/native/include/wcache/`)

| File | Responsibility |
|---|---|
| `stream_format.h` | The wire format as data: magic, version, field codes, the two frame layouts, and the `read_le` / `write_le` byte helpers. No I/O policy, no trace semantics. |
| `byte_source.h` | `ByteSource` interface plus `FdByteSource` and `MemByteSource`. Isolates "where the bytes come from" from "what they mean". |
| `stream_trace.h` | `StreamingTileTrace`: the one-tile window, implementing `TileTrace`. Plan unit A3. |
| `config.h` | `RunConfig` (the flat parameter set), `parse_config`, `validate`, `to_engine_params`. Plan unit D1, the single source of truth. |
| `stats.h` | `RunStats`, the CSV column list in order, `csv_header()`, `csv_row()`. Plan unit D2. |
| `sweep.h` | `BroadcastSweep`: the lockstep driver over one stream and N engines. Plan unit D3. |

**New C++ sources** (`src/wcache/native/src/`): `stream_trace.cpp`, `config.cpp`,
`stats.cpp`, `sweep.cpp`. `byte_source.h` and `stream_format.h` are header-only.

**New C++ programs** (`src/wcache/native/apps/`, a new directory): `wcache_run.cpp`,
`wcache_sweep.cpp`. These are the two `main()`s that gap G2 names.

**New C++ tests** (`src/wcache/native/tests/`): `test_stream_format.cpp`,
`test_stream_trace.cpp`, `test_config.cpp`, `test_stats.cpp`, `test_sweep.cpp`.

**Modified C++** : `include/wcache/event.h` (add `peek_min`), `include/wcache/engine.h`
and `src/engine.cpp` (add `run_to_barrier`, extend `EngineStats`), `src/engine_core.cpp`
(stall attribution and prefetch outcome counters), `include/wcache/types.h` and
`include/wcache/layout.h` (B161's two comments become wrong the day the header lands),
`Makefile`, `tests/mutation_check.sh`.

**Modified Python**: `src/tracegen.py` (`stream_weight_traces`, the sibling to
`save_weight_trace`), `src/archmodels/tick_output.h` and the five
`src/archmodels/{loas,ptb,spinalflow,prosperity,gustavsnn}/main.cpp` (loop swap plus
stdout), `scripts/generate_weight_traces.py` (`--stream`, `--dump-trace`,
`--dump-trace-tiles`).

**New campaign directory**: `profiling/0820_phaseD_spad_vs_cache/` with `README.md`,
`run_sweep.py`, `run_sweep.slurm`, `grids/`, `results/`.

---

## Unit index

Dependency-ordered. Each unit ends with an independently testable deliverable.

| # | Unit | Depends on |
|---|---|---|
| 1 | Wire format header (`stream_format.h`) + byte source | - |
| 2 | `StreamingTileTrace`, header decode | 1 |
| 3 | `StreamingTileTrace`, tile frames and the sliding window | 2 |
| 4 | `EventQueue::peek_min` + `Engine::run_to_barrier` | - |
| 5 | Producer: `write_tick_grouped` takes `std::ostream&`, `argv[3]` accepts `-` | - |
| 6 | Producer: swap the tile/sample loops in the five `main.cpp` | 5 |
| 7 | Producer: `tracegen.stream_weight_trace` emits the wire format | 1, 6 |
| 8 | Producer: `generate_weight_traces.py --stream` and the debug tee | 7 |
| 9 | D1: `RunConfig`, parse, defaults | - |
| 10 | D1: validation, the three guards and the `l2_demand_reserve` rejection | 9 |
| 11 | D2a: extend `EngineStats` with the stall breakdown and prefetch outcomes | 4 |
| 12 | D2b: line-anchored `fetch_latency` and `hidden_latency` (ruling R8) | 11 |
| 13 | D2c: `RunStats` and the CSV schema | 10, 11, 12 |
| 14 | D2d: the G14 distinct-address diagnostic | 3, 13 |
| 15 | `wcache_run` (`apps/wcache_run.cpp`) | 3, 9, 10, 13 |
| 16 | V1 end-to-end over the real pipe | 8, 15 |
| 17 | D3a: `BroadcastSweep` lockstep over one stream | 3, 4, 13 |
| 18 | D3b: `wcache_sweep` (`apps/wcache_sweep.cpp`) and `--config-grid` | 17 |
| 19 | D3c: per-unit atomic result cache, resume, merge | 18 |
| 20 | The local demo smoke run | 19 |
| 21 | Slurm and driver scripts under `profiling/0820_phaseD_spad_vs_cache/` | 19 |

---

## The wire format, in full

Name: **WCTS** (weight cache trace stream), version 1. Written by the producer, read by
`StreamingTileTrace`. This is the normative definition; Task 1 implements it and every
later task refers back here.

**Endianness and alignment.** Every multi-byte field is **little-endian**. The stream has
**no alignment guarantee**: a reader must load through `memcpy` or byte-wise, never by
casting a pointer into the buffer. This matches the existing `read_pod` convention in
`src/cachesim/main_hierarchical.cpp` and costs nothing.

**Types.** `i32` = `std::int32_t`, `u32` = `std::uint32_t`, `i64` = `std::int64_t`,
`u64` = `std::uint64_t`.

### Stream header

Written once, at byte 0.

```
off  size  field                 value / constraint
---  ----  --------------------  --------------------------------------------------
  0     8  magic                 the 8 ASCII bytes "WCTRACE1", no NUL
  8     4  u32 format_version    == 1
 12     4  u32 header_bytes      total header length in bytes, including this fixed part
 16     4  i32 n_tiles           >= 0                                    (U25 sibling)
 20     4  i32 n_cores           >= 1, the MACHINE size, not max(core_id)+1   (U25)
 24     4  i32 weight_bytes      >= 1; 1 for this corpus (BW_WEIGHT: 8)
 28     4  i32 burst_dim         Axis wire code: 0=KH 1=KW 2=CIN 3=COUT       (U27)
 32     4  i32 burst_stride      >= 1                                        (U27)
 36     4  i32 burst_span        >= 1, MAXIMUM elements per burst in this layer (Q-D)
 40     4  i32 n_addr_fields     == 5 in v1                                  (U28)
 44     4  i32 n_spatial         >= 0, number of spatial-factor entries       (U26)
 48     4  i32 n_dims            == 7 in v1
 52     4  i32 identity_bytes    >= 0, length of the identity block
```

`burst_span` is ruling Q-D, adopted 2026-08-20: `l1_demand_reserve` defaults to
`lines_per_burst = burst_span / cout_block`, and D1 validates that before the first burst
has been seen, so the generator emits the span rather than the reader guessing it. Same
argument R1 already accepted for `burst_dim` and `burst_stride`.

The field is the maximum burst span in this layer, used to size `l1_demand_reserve`; each
burst's actual extent is derivable from its own `run_start` and `run_end`. A layer with a
ragged final COUT run is therefore emitted normally, not rejected.

then, in this order and with no padding between them:

```
 56   4*n_addr_fields   i32 addr_field_id[]
                        0=KH 1=KW 2=CIN 3=RUN_START 4=RUN_END
                        v1 must be exactly {0,1,2,3,4}, i.e. [kh,kw,cin,cout_start,cout_end]

  .    8*n_spatial      (i32 dim_id, i32 factor) pairs, dim_id ascending
                        dim_id: 0=KH 1=KW 2=CIN 3=COUT 4=HO 5=WO 6=T
                        factor >= 1; the product over all pairs MUST equal n_cores

  .    8*n_dims         (i32 dim_id, i32 extent) pairs, dim_id ascending, == 0..6
                        the workload_dims bound N11/V15 checks a coordinate against

  .    identity_bytes   UTF-8, four NUL-separated fields then a trailing NUL:
                        arch \0 workload \0 layer \0 sample_idx \0
```

**Reader must check:** `header_bytes == 56 + 4*n_addr_fields + 8*n_spatial + 8*n_dims +
identity_bytes`. A mismatch is `std::invalid_argument` naming both numbers. This one
equality catches every truncation and every producer/consumer version skew, which is why
it is a field rather than something the reader infers.

### Tile frame

Repeated exactly `n_tiles` times, immediately after the header.

```
off  size  field                 constraint
---  ----  --------------------  --------------------------------------------------
  0     4  i32 tile_index        == the reader's running counter, 0-based
  4     4  i32 n_core_blocks     0 <= n_core_blocks <= n_cores
  8     8  i64 mac_cycles        >= 1
 16     8  u64 payload_bytes     byte length of everything after this field, up to
                                 the end of the frame. Lets a reader skip a tile
                                 without decoding it.
```

then `n_core_blocks` core blocks, in **strictly ascending `core_id`**:

```
  0     4  i32 core_id           0 <= core_id < n_cores, strictly ascending
  4     4  i32 n_bursts          >= 1  (a core with zero bursts is OMITTED, never
                                 written as an empty block; this matches
                                 tracegen's own "omitted, never padded" rule)
```

then `n_bursts` burst records, in **strictly ascending `local_tick`**:

```
  0     8  i64 local_tick        >= 0, strictly increasing inside a core block
  8   4*n_addr_fields  i32 addr[]  the address record, in header field order
```

### Stream trailer

Immediately after the last tile frame:

```
  0     4  i32 end_magic         == -1
  4     8  u64 total_bursts      the exact number of burst records in the whole stream
```

The reader accumulates its own burst count and throws `std::runtime_error` naming both
numbers when they disagree. This is the end-to-end check that a truncated pipe cannot
pass silently.

### Derived quantities the reader computes, not the producer

- `Burst` from an address record `[kh, kw, cin, run_start, run_end]`:
  `anchor = Coord{kh, kw, cin, run_start}`, `axis = header.burst_dim`,
  `count = run_end - run_start`, `stride = header.burst_stride`.
  `count >= 1` is checked; `run_end <= run_start` throws.
- `max_tick(tile)` = the largest `local_tick` in the frame, or `0` when
  `n_core_blocks == 0`.
- `tile_tail(tile)` = `mac_cycles - max_tick`. Checked `>= 1`, throwing when it is not,
  because `trace.h` documents it as `>= 1 by construction` and the engine relies on it to
  advance the tile seam.
- `tick_base(tile)` = the running sum of `mac_cycles` over tiles `0 .. tile-1`, with
  `tick_base(0) = 0`. This is the `spad_oracle` arm and V1's right-hand side.
- `gap(c, tile, k)` = `local_tick(k+1) - local_tick(k)`.

### What the reader retains outside the window

The window holds **one tile's burst payload**. Two per-tile **scalars** are retained for
every tile already streamed, because the engine reads them after the window may have
moved on and they cost 8 bytes each:

- `tile_tail(tile)`, read by `Engine::barrier_arrive` for the tile that is ending.
- `mac_cycles(tile)`, from which `tick_base` accumulates for the V1 check and the
  `tick_base_total` column.

At 128 tiles that is 2 KB. The four per-`(core, tile)` queries (`n_bursts`, `burst`,
`local_tick`, `gap`) answer **only** for `window_tile()`; any other tile throws
`std::out_of_range` naming both indices, which is what makes a lockstep-driver bug loud
instead of silently wrong.

---

## The CSV schema, in full

One row per `(arm, arch, n_cores, workload, layer, sample_idx, config)`. Columns in
**exactly** this order. `csv_header()` returns this list and `test_stats.cpp` pins it, so
a reordering is a test failure rather than a silent join break downstream.

```
run_id, git_commit, arm, tier,
arch, n_cores, workload, layer, sample_idx,
l1_size_bytes, l1_assoc, l1_num_lines, l1_num_sets,
l2_size_bytes, l2_assoc, l2_num_lines, l2_num_sets,
line_size_bytes, cin_block, cout_block, weight_bytes,
l1_mshrs, l1_tgts_per_mshr, l2_mshrs, l2_tgts_per_mshr, l1_demand_reserve,
prefetch_policy, prefetch_distance,
l1_latency, l1_ii, l2_latency, l2_to_l1_latency, l2_miss_latency,
l2_banks, l2_ii, dram_ii, core_accept_ii, inclusion, policy,
total_cycles, tick_base_total, stretch_cycles,
l1_hits, l1_accesses, l1_hit_rate, l2_hits, l2_accesses, l2_hit_rate,
dram_accesses, dram_bytes,
stall_l1_slot, stall_l1_line, stall_l1_port, stall_l2_slot, stall_l2_line,
stall_l2_port, stall_channel, stall_barrier, stall_total,
core_stall_sum, fetch_latency_sum, hidden_latency, hidden_fraction,
pf_issued, pf_timely, pf_late, pf_wasted,
pf_dropped_array_hit, pf_dropped_matching, pf_dropped_no_slot,
pf_dropped_targets_full, pf_dropped_reserve,
pf_coverage, pf_coverage_ceiling, pf_budget_exhausted, pf_pollution_evictions,
padding_fraction, port_bound_threshold,
l1_mshr_occ_p50, l1_mshr_occ_p95, l1_mshr_occ_max,
l2_mshr_occ_p50, l2_mshr_occ_p95, l2_mshr_occ_max,
max_wait_depth, hits_downgraded_to_miss, events, events_per_cycle, sim_wall_seconds,
distinct_addr_per_core_tile_p50, distinct_addr_per_core_tile_max
```

91 columns. It was 90 (the plan's prose said 91 against a 90-entry list, which
was an unrelated arithmetic error and was corrected to 90); `stall_l1_port` is
the 91st, added because V21's partition had no bucket for the cycles a demand
spends waiting on the L1 port -- its `ii` occupancy and its access latency --
when nothing ever refused it. Notes on the ones that are not a straight copy of §9.2:

- `l1_ii`, `l2_to_l1_latency`, `dram_ii` are **added** to §9.2's configuration block.
  Every one of them is a settable `EngineParams`/`LevelParams` field, and a knob with no
  column cannot be reconstructed from the row. See OPEN QUESTION 5.
- `l2_num_lines`, `l2_num_sets` are added for symmetry with §4.5's mandated
  `l1_num_lines` / `l1_num_sets`.
- `hidden_fraction = hidden_latency / fetch_latency_sum`, or the empty string when
  `fetch_latency_sum == 0`.
- `distinct_addr_per_core_tile_p50` / `_max` summarise G14's histogram; the histogram
  itself goes to a sidecar file (Task 14).
- `l2_demand_reserve` is **not** here (G11) and Task 10 rejects it at config load.

---

## The CLI, in full

### `wcache_run`

One config, one trace, one CSV row on stdout.

```
wcache_run --config <path.json> --trace <path|-> [options]

  --config PATH          required. The run configuration as JSON (Task 9).
  --trace PATH           required. A WCTS stream. `-` means stdin. `fd:N` means
                         an already-open file descriptor N.
  --out PATH             where the CSV goes. Default `-` (stdout).
  --header               emit the CSV header line before the row. Default on when
                         --out is a path that does not exist, off otherwise.
  --no-header            never emit the header line.
  --arm NAME             the `arm` column: spad_oracle | spad_wcache | spad_nocsim
                         | cache. Default `cache`.
  --tier NAME            the `tier` column, free text. Default the empty string.
  --run-id STRING        the `run_id` column. Default a UUIDv4 generated here.
  --git-commit STRING    the `git_commit` column. Default the empty string; the
                         driver fills it, because the binary must not shell out.
  --hist PATH            write the G14 per-(core, tile) distinct-address histogram
                         here as CSV. Off by default (Task 14).
  --oracle-only          decode the stream, compute tick_base_total, emit a row with
                         total_cycles == tick_base_total and every simulated column
                         empty, and run no engine. This is the `spad_oracle` arm,
                         which §2 says costs nothing.
  --help                 usage on stdout, exit 0.
```

Exit codes: `0` success, `1` a run-time failure (a throw, named on stderr), `2` a usage
error.

### `wcache_sweep`

One config grid, one trace, one CSV row per grid point, broadcast lockstep over a single
pass of the stream.

```
wcache_sweep --config-grid <path.json> --trace <path|-> [options]

  --config-grid PATH     required. A JSON array of run configurations, OR an object
                         with `base` (one config) and `axes` (name -> list of values)
                         which is expanded to the full cross product in the order the
                         axes are declared (Task 18).
  --trace PATH           required. A WCTS stream. `-` means stdin, `fd:N` a descriptor.
  --out PATH             where the CSV goes. Default `-` (stdout).
  --header / --no-header as wcache_run. Default on for a sweep.
  --arm NAME             as wcache_run, applied to every row.
  --tier NAME            as wcache_run, applied to every row.
  --run-id STRING        as wcache_run. Every row of one sweep shares it.
  --git-commit STRING    as wcache_run.
  --hist PATH            as wcache_run. The histogram is a property of the trace, not
                         of a configuration, so it is written once per sweep.
  --max-engines N        refuse a grid larger than N live engines, so an oversized
                         grid fails at startup rather than by OOM three hours in.
                         Default 256.
  --progress             one line per completed tile on stderr, for a long run.
  --help                 usage on stdout, exit 0.
```

### `scripts/generate_weight_traces.py`, new flags

```
  --stream               emit one WCTS stream on stdout instead of writing
                         sample_NNNNN.json.gz files. Requires exactly one
                         (arch, trace_dir, layer, sample) to be selected.
  --dump-trace PATH      tee the stream to PATH as it passes, byte-identical to what
                         the consumer sees (§10.6). Off by default.
  --dump-trace-tiles N   with --dump-trace, stop the tee after N tile frames and
                         write the trailer, so the dump is a valid short stream.
                         A two-tile slice is what src/wcache/examples/ already uses.
```

---

## Task 1: Wire format header and byte source

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/stream_format.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/byte_source.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_stream_format.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/mutation_check.sh:65`
  (add both headers to `FILES=`)

**Interfaces:**
- Consumes: `wcache/types.h` for `Axis`, `Coord`, `Burst`, `WeightShape`.
- Produces, and every later task uses these exact names:

```cpp
namespace wcache::stream {

inline constexpr char        kMagic[8]        = {'W','C','T','R','A','C','E','1'};
inline constexpr std::uint32_t kFormatVersion = 1;
inline constexpr std::size_t kFixedHeaderBytes = 56;
inline constexpr std::int32_t kEndMagic       = -1;

// Wire codes. Deliberately NOT the same enum as `Axis`, so a renumbering of
// `Axis` cannot silently change the format (U28's whole point).
enum class DimCode : std::int32_t { KH = 0, KW = 1, CIN = 2, COUT = 3, HO = 4, WO = 5, T = 6 };
enum class FieldCode : std::int32_t { KH = 0, KW = 1, CIN = 2, RunStart = 3, RunEnd = 4 };

Axis     axis_of(std::int32_t burst_dim);   // throws std::invalid_argument out of range
std::int32_t code_of(Axis a);

// Little-endian, alignment-free. `src` need not be aligned.
template <typename T> T read_le(const unsigned char* src);
template <typename T> void write_le(unsigned char* dst, T v);

struct StreamHeader {
    std::int32_t n_tiles       = 0;
    std::int32_t n_cores       = 0;
    std::int32_t weight_bytes  = 1;
    Axis         burst_dim     = Axis::COUT;
    std::int32_t burst_stride  = 1;
    std::int32_t burst_span    = 1;   // ruling Q-D
    std::vector<FieldCode>                              addr_fields;
    std::vector<std::pair<DimCode, std::int32_t>>       spatial_factors;
    std::vector<std::pair<DimCode, std::int32_t>>       dims;
    std::string arch, workload, layer;
    std::int32_t sample_idx = 0;
};

// Decodes and VALIDATES a header from a complete byte buffer. Throws
// std::invalid_argument naming the offending field on any violation listed in
// "The wire format, in full".
StreamHeader decode_header(const unsigned char* buf, std::size_t len);

// The inverse, for tests and for the C++ side of any future dump tool. Appends.
void encode_header(const StreamHeader& h, std::vector<unsigned char>& out);

}  // namespace wcache::stream
```

```cpp
namespace wcache {

class ByteSource {
public:
    virtual ~ByteSource() = default;
    // Fills exactly `n` bytes. Returns false ONLY on a clean end of stream, that
    // is when zero bytes were available. A partial read is a truncated stream and
    // throws std::runtime_error naming how many bytes were wanted and got.
    virtual bool read_exact(void* dst, std::size_t n) = 0;
protected:
    ByteSource() = default;
    ByteSource(const ByteSource&) = default;
    ByteSource(ByteSource&&) = default;
    ByteSource& operator=(const ByteSource&) = default;
    ByteSource& operator=(ByteSource&&) = default;
};

// Reads from an already-open POSIX descriptor, retrying short reads and EINTR.
// Does NOT own the descriptor.
class FdByteSource final : public ByteSource {
public:
    explicit FdByteSource(int fd);
    bool read_exact(void* dst, std::size_t n) override;
};

// Reads from a buffer in memory. This is what every test uses.
class MemByteSource final : public ByteSource {
public:
    MemByteSource(const unsigned char* data, std::size_t len);
    explicit MemByteSource(const std::vector<unsigned char>& v);
    bool read_exact(void* dst, std::size_t n) override;
    std::size_t consumed() const;
};

}  // namespace wcache
```

The protected defaulted special members on `ByteSource` follow the same reason decision
B67 settled at `CacheArray` and B92 reused at `ReplacementPolicy`: through two base
references `a = b` would compile and assign the base subobject only.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_format.cpp`:

```cpp
#include <wcache/byte_source.h>
#include <wcache/stream_format.h>
#include <wcache/types.h>

#include <cstdint>
#include <string>
#include <vector>

#include "check.h"

using namespace wcache;
using wcache::stream::DimCode;
using wcache::stream::FieldCode;
using wcache::stream::StreamHeader;

namespace {

StreamHeader good_header() {
    StreamHeader h;
    h.n_tiles      = 2;
    h.n_cores      = 8;
    h.weight_bytes = 1;
    h.burst_dim    = Axis::COUT;
    h.burst_stride = 1;
    h.addr_fields  = {FieldCode::KH, FieldCode::KW, FieldCode::CIN,
                      FieldCode::RunStart, FieldCode::RunEnd};
    h.spatial_factors = {{DimCode::COUT, 8}};
    h.dims = {{DimCode::KH, 3},  {DimCode::KW, 3},  {DimCode::CIN, 64},
              {DimCode::COUT, 64}, {DimCode::HO, 32}, {DimCode::WO, 32},
              {DimCode::T, 4}};
    h.arch = "loas";  h.workload = "vgg16_T4_all";
    h.layer = "layer_01_features_3";  h.sample_idx = 0;
    return h;
}

void test_header_round_trips() {
    check::group("Task 1: encode_header then decode_header is the identity");
    std::vector<unsigned char> buf;
    stream::encode_header(good_header(), buf);
    const StreamHeader got = stream::decode_header(buf.data(), buf.size());
    CHECK_EQ(got.n_tiles, 2);
    CHECK_EQ(got.n_cores, 8);
    CHECK_EQ(got.burst_stride, 1);
    CHECK_TRUE(got.burst_dim == Axis::COUT);
    CHECK_EQ(check::ssize(got.addr_fields), std::int64_t{5});
    CHECK_EQ(check::ssize(got.dims), std::int64_t{7});
    CHECK_TRUE(got.arch == "loas");
    CHECK_TRUE(got.layer == "layer_01_features_3");
    CHECK_EQ(got.sample_idx, 0);
}

void test_header_bytes_mismatch_throws() {
    check::group("Task 1: a header_bytes that disagrees with the field counts throws");
    std::vector<unsigned char> buf;
    stream::encode_header(good_header(), buf);
    // header_bytes lives at offset 12. Corrupt it by one.
    const std::uint32_t bad = stream::read_le<std::uint32_t>(buf.data() + 12) + 1u;
    stream::write_le<std::uint32_t>(buf.data() + 12, bad);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_spatial_product_must_equal_n_cores() {
    check::group("Task 1: prod(spatial_factors) != n_cores throws (U25, U26)");
    StreamHeader h = good_header();
    h.spatial_factors = {{DimCode::COUT, 4}};   // 4 != n_cores 8
    std::vector<unsigned char> buf;
    stream::encode_header(h, buf);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_bad_magic_throws() {
    check::group("Task 1: a wrong magic throws rather than decoding garbage");
    std::vector<unsigned char> buf;
    stream::encode_header(good_header(), buf);
    buf[0] = 'X';
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_read_le_is_alignment_free() {
    check::group("Task 1: read_le works from an odd offset");
    std::vector<unsigned char> buf(16, 0);
    stream::write_le<std::int64_t>(buf.data() + 3, std::int64_t{-1234567890123LL});
    CHECK_EQ(stream::read_le<std::int64_t>(buf.data() + 3), std::int64_t{-1234567890123LL});
}

void test_mem_byte_source_partial_read_throws() {
    check::group("Task 1: a truncated record throws, a clean end returns false");
    const std::vector<unsigned char> v(4, 0);
    MemByteSource src(v);
    std::int32_t out = 0;
    CHECK_TRUE(src.read_exact(&out, 4));
    CHECK_TRUE(!src.read_exact(&out, 4));          // clean end
    MemByteSource short_src(v);
    std::int64_t wide = 0;
    CHECK_THROWS(std::runtime_error, short_src.read_exact(&wide, 8));  // truncated
}

}  // namespace

int main() {
    test_header_round_trips();
    test_header_bytes_mismatch_throws();
    test_spatial_product_must_equal_n_cores();
    test_bad_magic_throws();
    test_read_le_is_alignment_free();
    test_mem_byte_source_partial_read_throws();
    return check::summary();
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_stream_format
```
Expected: FAIL, `fatal error: wcache/stream_format.h: No such file or directory`.

- [ ] **Step 3: Write `include/wcache/byte_source.h`**

Header-only. `FdByteSource::read_exact` loops on `::read`, treating `EINTR` as a retry,
`0` on the first iteration as a clean end (return `false`), and `0` after some bytes were
read as truncation (throw). `MemByteSource` is a pointer plus a cursor with the same
contract.

- [ ] **Step 4: Write `include/wcache/stream_format.h`**

`read_le`/`write_le` are `std::memcpy` into a local `T` followed by a byte swap that is a
no-op on a little-endian host, guarded by `if constexpr` on
`__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__`. `decode_header` checks, in this order and
throwing `std::invalid_argument` naming the field: magic, `format_version == 1`,
`len >= kFixedHeaderBytes`, `header_bytes == len`, `n_tiles >= 0`, `n_cores >= 1`,
`weight_bytes >= 1`, `burst_dim` in range, `burst_stride >= 1`, `burst_span >= 1`, `n_addr_fields == 5`,
`addr_field_id[] == {0,1,2,3,4}`, `n_dims == 7`, `dims` ids exactly `0..6` ascending,
`spatial_factors` dim ids ascending and each factor `>= 1`, the product of the factors
`== n_cores`, `header_bytes == 56 + 4*n_addr_fields + 8*n_spatial + 8*n_dims +
identity_bytes`, and the identity block containing exactly four NUL-terminated fields.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_stream_format
```
Expected: PASS, ending in `N checks, 0 failures`.

- [ ] **Step 6: Add both headers to the mutation list**

Edit `tests/mutation_check.sh:65`, adding `include/wcache/stream_format.h` and
`include/wcache/byte_source.h` to the `FILES=` string.

- [ ] **Step 7: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: every test binary green, `0 failures` on each, the compile-fail script green,
and the total check count strictly above 24,850. **Do not commit.**

---

## Task 2: `StreamingTileTrace`, header decode

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/stream_trace.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/stream_trace.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_stream_trace.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/mutation_check.sh:65`

**Interfaces:**
- Consumes: Task 1's `stream::StreamHeader`, `stream::decode_header`, `ByteSource`;
  `wcache/trace.h`'s `TileTrace`, exactly as it exists today, with no change to it.
- Produces, and this is the signature the brief asks be pinned against the real
  interface:

```cpp
namespace wcache {

class StreamingTileTrace final : public TileTrace {
public:
    // Reads and validates the stream header immediately, then leaves the window
    // EMPTY: `window_tile()` is -1 until the first `advance()`. Throws
    // std::invalid_argument (a bad header) or std::runtime_error (a truncated one).
    // `src` must outlive the trace.
    explicit StreamingTileTrace(ByteSource& src);

    // --- TileTrace, the seven pure virtuals, unchanged in signature -----------
    std::int32_t n_tiles() const override;
    std::int32_t n_cores() const override;
    std::int32_t n_bursts(CoreId core, std::int32_t tile) const override;
    const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const override;
    LocalTick tile_tail(std::int32_t tile) const override;

    // --- the window, which the ENGINE never touches --------------------------
    // -1 before the first advance(), otherwise the one tile the four
    // per-(core, tile) queries answer for.
    std::int32_t window_tile() const;

    // Decodes the next tile frame. Returns false at the trailer, having verified
    // the end magic and the total burst count. Throws when `tile_index` is not the
    // expected counter, when a core id is out of range or not ascending, when a
    // local_tick is not ascending, when `run_end <= run_start`, or when the
    // derived tile_tail is below 1.
    bool advance();

    // --- header and per-tile scalars, for D1, D2 and the V1 check ------------
    const stream::StreamHeader& header() const;
    // Retained for EVERY tile already streamed, because barrier_arrive reads
    // tile_tail after the window may have moved on.
    std::int64_t mac_cycles(std::int32_t tile) const;
    // Running sum of mac_cycles over tiles [0, tile). tick_base(0) == 0. Defined
    // for every tile already streamed plus one past it.
    std::int64_t tick_base(std::int32_t tile) const;
    // G14, Task 14: distinct LineId count for `core` in the WINDOW tile.
    std::int32_t distinct_addresses(CoreId core) const;
};

}  // namespace wcache
```

Storage: one `std::vector<Burst>` and one `std::vector<std::int64_t>` of ticks per window
tile, plus a `std::vector<std::int32_t>` of per-core `[begin, end)` offsets into them, so
`burst()` can return a reference into a stable buffer, which the interface requires. Both
buffers are `clear()`ed and refilled by `advance()`, never reallocated in steady state.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_trace.cpp` with a builder that produces a stream in memory, so
no test ever touches a file:

```cpp
#include <wcache/byte_source.h>
#include <wcache/stream_format.h>
#include <wcache/stream_trace.h>
#include <wcache/trace.h>

#include <cstdint>
#include <stdexcept>
#include <vector>

#include "check.h"

using namespace wcache;
using wcache::stream::DimCode;
using wcache::stream::FieldCode;

namespace {

// Builds a WCTS stream in memory. Deliberately a SECOND implementation of the
// format rather than a call into a shared writer: a reader tested against its own
// writer tests only that they agree with each other.
class StreamBuilder {
public:
    StreamBuilder(std::int32_t n_tiles, std::int32_t n_cores);
    void begin_tile(std::int32_t tile_index, std::int64_t mac_cycles);
    void begin_core(std::int32_t core_id);
    void add_burst(std::int64_t tick, std::int32_t kh, std::int32_t kw,
                   std::int32_t cin, std::int32_t run_start, std::int32_t run_end);
    void end_tile();
    std::vector<unsigned char> finish();   // appends the trailer
    // Escape hatches the negative cases need:
    void set_end_magic(std::int32_t v);
    void set_total_bursts(std::uint64_t v);
};

void test_header_is_read_and_the_window_starts_empty() {
    check::group("Task 2: the constructor reads the header, window_tile() is -1");
    StreamBuilder b(2, 8);
    b.begin_tile(0, 24); b.begin_core(0); b.add_burst(0, 1, 1, 6, 0, 16); b.end_tile();
    b.begin_tile(1, 24); b.begin_core(0); b.add_burst(0, 1, 0, 8, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_EQ(tr.n_tiles(), 2);
    CHECK_EQ(tr.n_cores(), 8);
    CHECK_EQ(tr.window_tile(), -1);
}

void test_a_query_before_the_first_advance_throws() {
    check::group("Task 2: querying tile 0 before advance() throws");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::out_of_range, tr.n_bursts(CoreId{0}, 0));
}

void test_bad_magic_in_the_constructor_throws() {
    check::group("Task 2: a corrupt header throws from the constructor");
    StreamBuilder b(0, 1);
    std::vector<unsigned char> bytes = b.finish();
    bytes[1] = 'Z';
    MemByteSource src(bytes);
    CHECK_THROWS(std::invalid_argument, StreamingTileTrace{src});
}

}  // namespace

int main() {
    test_header_is_read_and_the_window_starts_empty();
    test_a_query_before_the_first_advance_throws();
    test_bad_magic_in_the_constructor_throws();
    return check::summary();
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_stream_trace
```
Expected: FAIL, `fatal error: wcache/stream_trace.h: No such file or directory`.

- [ ] **Step 3: Write the header and the constructor half of the source**

`stream_trace.h` as declared above. In `src/stream_trace.cpp`, the constructor reads the
56 fixed bytes, reads `header_bytes - 56` further bytes into the same buffer, calls
`stream::decode_header` on the whole buffer, stores the result, sizes
`mac_cycles_`/`tick_base_` to `n_tiles + 1`, and sets `window_ = -1`. The seven
`TileTrace` overrides are written now; the four per-`(core, tile)` ones begin with

```cpp
void StreamingTileTrace::require_window(std::int32_t tile) const {
    if (tile != window_) {
        throw std::out_of_range(
            "StreamingTileTrace: tile " + std::to_string(tile) +
            " is outside the window, which holds tile " + std::to_string(window_) +
            ". A one-tile sliding window answers only for the tile it holds.");
    }
}
```

and `advance()` is a stub that throws `std::logic_error("not implemented")`, so Task 2's
three cases pass and Task 3's do not.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_stream_trace
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Add the new files to the mutation list**

Add `include/wcache/stream_trace.h` and `src/stream_trace.cpp` to `FILES=` in
`tests/mutation_check.sh:65`.

- [ ] **Step 6: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green, `0 failures`. **Do not commit.**

---

## Task 3: `StreamingTileTrace`, tile frames and the sliding window

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/stream_trace.cpp`
  (replace the `advance()` stub)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_stream_trace.cpp`

**Interfaces:**
- Consumes: Task 2's declarations, unchanged.
- Produces: a working `advance()`, so a `StreamingTileTrace` is a drop-in `TileTrace` for
  the engine as long as the driver advances the window in step with the tile barrier.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stream_trace.cpp` and call each from `main()`:

```cpp
void test_one_tile_decodes_and_the_window_moves() {
    check::group("Task 3: advance() decodes a frame and the queries answer for it");
    StreamBuilder b(2, 4);
    b.begin_tile(0, 10);
    b.begin_core(0);
    b.add_burst(0, 1, 1, 6, 0, 16);
    b.add_burst(1, 1, 1, 7, 0, 16);
    b.begin_core(2);
    b.add_burst(3, 0, 0, 0, 16, 32);
    b.end_tile();
    b.begin_tile(1, 8);
    b.begin_core(1);
    b.add_burst(0, 2, 2, 2, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);

    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.window_tile(), 0);
    CHECK_EQ(tr.n_bursts(CoreId{0}, 0), 2);
    CHECK_EQ(tr.n_bursts(CoreId{1}, 0), 0);   // omitted core: zero is legal
    CHECK_EQ(tr.n_bursts(CoreId{2}, 0), 1);
    CHECK_EQ(tr.n_bursts(CoreId{3}, 0), 0);
    CHECK_EQ(tr.local_tick(CoreId{0}, 0, BurstIndex{0}), LocalTick{0});
    CHECK_EQ(tr.local_tick(CoreId{0}, 0, BurstIndex{1}), LocalTick{1});
    CHECK_EQ(tr.gap(CoreId{0}, 0, BurstIndex{0}), LocalTick{1});
    // max_tick is 3 (core 2), mac_cycles is 10, so the tail is 7.
    CHECK_EQ(tr.tile_tail(0), LocalTick{7});
    CHECK_EQ(tr.mac_cycles(0), std::int64_t{10});
    CHECK_EQ(tr.tick_base(0), std::int64_t{0});

    const Burst& first = tr.burst(CoreId{0}, 0, BurstIndex{0});
    CHECK_EQ(first.count, 16);
    CHECK_EQ(first.stride, 1);
    CHECK_TRUE(first.axis == Axis::COUT);
    CHECK_EQ(coord_on(first.anchor, Axis::CIN), 6);
    CHECK_EQ(coord_on(first.anchor, Axis::COUT), 0);

    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.window_tile(), 1);
    CHECK_EQ(tr.tick_base(1), std::int64_t{10});
    CHECK_EQ(tr.tile_tail(0), LocalTick{7});   // retained past the window
    CHECK_THROWS(std::out_of_range, tr.n_bursts(CoreId{0}, 0));  // payload is not
    CHECK_TRUE(!tr.advance());                 // clean trailer
}

void test_out_of_order_tile_index_throws() {
    check::group("Task 3: a frame whose tile_index is not the counter throws");
    StreamBuilder b(2, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.begin_tile(7, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_descending_core_id_throws() {
    check::group("Task 3: core blocks must ascend");
    StreamBuilder b(1, 4);
    b.begin_tile(0, 4);
    b.begin_core(2); b.add_burst(0, 0, 0, 0, 0, 16);
    b.begin_core(1); b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_core_id_at_or_above_n_cores_throws() {
    check::group("Task 3: a core id outside [0, n_cores) throws (U25)");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4); b.begin_core(2); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_non_ascending_local_tick_throws() {
    check::group("Task 3: local_tick must strictly increase inside a core block");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8);
    b.begin_core(0);
    b.add_burst(3, 0, 0, 0, 0, 16);
    b.add_burst(3, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_tile_tail_below_one_throws() {
    check::group("Task 3: tile_tail >= 1 is checked, not assumed (trace.h, Q10)");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 3);                       // mac_cycles 3
    b.begin_core(0); b.add_burst(3, 0, 0, 0, 0, 16);   // max_tick 3, tail 0
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_empty_run_throws() {
    check::group("Task 3: run_end <= run_start throws rather than making count 0");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 16, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_wrong_total_bursts_in_the_trailer_throws() {
    check::group("Task 3: the trailer's burst count is checked end to end");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.set_total_bursts(99);
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_a_tile_with_no_cores_is_legal() {
    check::group("Task 3: a tile in which no core issues is legal (trace.h)");
    StreamBuilder b(1, 4);
    b.begin_tile(0, 5); b.end_tile();          // no core blocks at all
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.n_bursts(CoreId{0}, 0), 0);
    CHECK_EQ(tr.tile_tail(0), LocalTick{5});   // max_tick 0, so the tail is mac_cycles
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_stream_trace && ./build/fixture/test_stream_trace
```
Expected: FAIL, every new case reporting the `std::logic_error("not implemented")` from
the `advance()` stub.

- [ ] **Step 3: Implement `advance()`**

Replace the stub. In order: read the 24-byte frame prefix; check `tile_index ==
window_ + 1`; check `0 <= n_core_blocks <= n_cores`; read `payload_bytes` into the frame
buffer in one `read_exact`; decode the core blocks from that buffer, filling `ticks_`,
`bursts_` and the per-core `[begin, end)` table, checking every constraint listed in
Task 2's `advance()` contract; compute `max_tick`; set
`mac_cycles_[tile] = mac_cycles` and `tick_base_[tile + 1] = tick_base_[tile] +
mac_cycles`; check `mac_cycles - max_tick >= 1` and store the tail; set
`window_ = tile_index`; return `true`. When `window_ + 1 == n_tiles`, instead read the
trailer, check `end_magic == kEndMagic` and `total_bursts == bursts_seen_`, and return
`false`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_stream_trace
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Correct the two comments ruling R1 invalidates**

`PROGRESS.md` B161 records that `types.h`'s comment above `struct Burst` and `layout.h`'s
comment above `expand` both say the axis and the stride are supplied by the reader, and
that both "become wrong the day the header lands". Edit both to say the two values come
from the WCTS stream header's `burst_dim` and `burst_stride`, and that U27 is ruled
(R1, 2026-08-20) rather than open. Do not change `expand`'s contract: an implementation
still reads the walked axis out of the burst and may not assume COUT (B22).

- [ ] **Step 6: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green, `0 failures`, check count above 24,850. **Do not commit.**

---

## Task 4: `EventQueue::peek_min` and `Engine::run_to_barrier`

Broadcast lockstep needs to stop every engine at the same tile boundary and resume it
after the window has moved. The engine reads `tile_tail(N)` in `barrier_arrive` (before
the `E_Barrier(N)` event fires) and reads tile `N+1`'s bursts in `start_tile`, called
from `on_barrier`. The one safe pause point is therefore **after the barrier event has
been scheduled and before it is dispatched**.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/event.h`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/engine.h`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/engine.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_event.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_engine.cpp`

**Interfaces:**
- Produces:

```cpp
// event.h, inside EventQueue
const Event<Payload>& peek_min() const;   // throws std::logic_error when empty

// engine.h, inside Engine, public
// Pops and dispatches events until the queue's next event is a Barrier, which it
// leaves UNDISPATCHED, or until the queue empties.
//
// Returns the tile of that pending barrier, or -1 when the run is complete, in
// which case the D12 deadlock checks have already run.
//
// `run()` is now exactly `while (run_to_barrier() >= 0) {}`, so the event order,
// and therefore V3's byte-identical event log, is unchanged.
std::int32_t run_to_barrier();
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_event.cpp` and call from its `main()`:

```cpp
void test_peek_min_does_not_pop() {
    check::group("Task 4: peek_min returns the same event pop_min would, twice");
    EventQueue<int> q;
    q.schedule(SimTime{5}, EventKind::Issue, NoRefusal, CoreId{0}, 7);
    q.schedule(SimTime{3}, EventKind::Issue, NoRefusal, CoreId{0}, 9);
    CHECK_EQ(q.peek_min().payload, 9);
    CHECK_EQ(q.peek_min().payload, 9);
    CHECK_EQ(q.pop_min().payload, 9);
    CHECK_EQ(q.peek_min().payload, 7);
}

void test_peek_min_on_an_empty_queue_throws() {
    check::group("Task 4: peek_min on an empty queue throws");
    EventQueue<int> q;
    CHECK_THROWS(std::logic_error, q.peek_min());
}
```

Add to `tests/test_engine.cpp` and call from its `main()`:

```cpp
void test_run_to_barrier_stops_at_every_tile_and_matches_run() {
    check::group("Task 4: run_to_barrier walks the same timeline run() does");
    // Two tiles, three cores, the unbounded baseline.
    fx::FakeTrace tr(3);
    const std::int32_t t0 = tr.add_tile(3);
    tr.add_burst(t0, 0, 0, 0);  tr.add_burst(t0, 0, 1, 1);
    tr.add_burst(t0, 1, 0, 2);  tr.add_burst(t0, 2, 0, 3);
    const std::int32_t t1 = tr.add_tile(2);
    tr.add_burst(t1, 0, 0, 4);  tr.add_burst(t1, 1, 1, 5);

    fx::LinearMapper mapper;
    const EngineParams p = fx::unbounded_params();

    Engine whole(mapper, tr, p);
    whole.run();

    Engine stepped(mapper, tr, p);
    CHECK_EQ(stepped.run_to_barrier(), 0);       // pending barrier for tile 0
    CHECK_EQ(stepped.run_to_barrier(), 1);       // pending barrier for tile 1
    CHECK_EQ(stepped.run_to_barrier(), -1);      // complete
    for (std::int32_t t = 0; t <= tr.n_tiles(); ++t)
        CHECK_EQ(stepped.tile_origin(t), whole.tile_origin(t));
    CHECK_EQ(stepped.stats().core_stall, whole.stats().core_stall);
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_event build/fixture/test_engine
```
Expected: FAIL to compile, `'peek_min' is not a member of 'wcache::EventQueue<int>'` and
`'class wcache::Engine' has no member named 'run_to_barrier'`.

- [ ] **Step 3: Implement both**

`EventQueue::peek_min` mirrors `pop_min`'s empty check and returns `q_.front()` by const
reference.

In `src/engine.cpp`, replace `run()`'s body with:

```cpp
std::int32_t Engine::run_to_barrier() {
    if (!started_) {
        tile_origin_.at(0) = SimTime{0};
        if (trace_.n_tiles() > 0) start_tile(0, SimTime{0});
        started_ = true;
        if (!queue_.empty() && queue_.peek_min().kind == EventKind::Barrier)
            return queue_.peek_min().payload.tile;
    }
    while (!queue_.empty()) {
        if (queue_.peek_min().kind == EventKind::Barrier)
            return queue_.peek_min().payload.tile;
        const Event<EventPayload> e = queue_.pop_min();
        dispatch(e);
    }
    check_no_work_outstanding();   // the existing D12 block, factored out verbatim
    return -1;
}

void Engine::run() {
    while (run_to_barrier() >= 0) {
        const Event<EventPayload> e = queue_.pop_min();
        dispatch(e);
    }
}
```

The D12 deadlock block that `run()` held moves verbatim into a private
`check_no_work_outstanding()`; nothing about its messages changes. Add a `bool started_ =
false;` member.

Note the shape: `run_to_barrier` **returns with the barrier still queued**, and the
caller is what pops it. That is what lets the driver advance the trace window in between,
and it is why `run()` is the two-line loop above rather than a call in a loop.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_event && ./build/fixture/test_engine
```
Expected: PASS on both, `0 failures`.

- [ ] **Step 5: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green. Because this task touches `engine.cpp`, confirm `test_engine`,
`test_prefetch` and `test_cache_level` are all still `0 failures`: V3's byte-identical
event log depends on nothing here having reordered a dispatch. **Do not commit.**

---

## Task 5: Producer, `write_tick_grouped` takes `std::ostream&` and `argv[3]` accepts `-`

The five archmodel binaries write through an `std::ofstream` given as `argv[3]`
(`§10.3(b)`). Pointing that stream at stdout makes the producer a true stream with no
logic change, but the concrete `std::ofstream` type is baked into two signatures.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/tick_output.h:32`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/loas/main.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/ptb/main.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/spinalflow/main.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/prosperity/main.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/gustavsnn/main.cpp`

**Interfaces:**
- Produces: `write_tick_grouped(std::ostream& out_fh, const std::vector<AddressRow>&)`,
  and in each `main.cpp` a `static void write_i32(std::ostream& fh, int32_t v)` plus an
  output selector:

```cpp
    // `-` means stdout, which is what makes this binary a stream producer with no
    // change to what it writes (see §10.3(b) of the Phase D campaign plan).
    std::ofstream out_file;
    std::ostream* out = nullptr;
    if (out_path == "-") {
        out = &std::cout;
    } else {
        out_file.open(out_path, std::ios::binary);
        if (!out_file) {
            std::cerr << "loasgen: cannot open output file " << out_path << "\n";
            return 2;
        }
        out = &out_file;
    }
    std::ostream& out_fh = *out;
```

On Windows this would need `_setmode`; this repo is Linux only, so no binary-mode call is
needed. What **is** needed: nothing else in these programs may write to stdout. Confirm
with a grep that every diagnostic goes to `std::cerr`.

- [ ] **Step 1: Write the failing test**

There is no C++ test harness for `src/archmodels`. The check is a behavioural one, run
through the existing Python path, and it is written as a shell one-liner that fails today.
Create `/home/ya867177/neuro_cache-wcache/src/archmodels/tests/stdout_roundtrip.sh`:

```sh
#!/bin/sh
# Task 5: the arch binary must write the SAME bytes to stdout as to a file.
# Usage: stdout_roundtrip.sh <binary> <trace.bin> <task.bin>
set -e
bin=$1; trace=$2; task=$3
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
"$bin" "$trace" "$task" "$tmp/via_file.bin"
"$bin" "$trace" "$task" - > "$tmp/via_stdout.bin"
cmp "$tmp/via_file.bin" "$tmp/via_stdout.bin"
echo "stdout_roundtrip: identical"
```

`chmod +x` it.

- [ ] **Step 2: Run it to verify it fails**

Build the binaries first with whatever `make` target `src/archmodels` uses, then:

```bash
ls src/archmodels/loas/ && \
  src/archmodels/tests/stdout_roundtrip.sh <loas binary> <a trace.bin> <a task.bin>
```
Expected: FAIL, because `-` is opened as a file literally named `-` and the stdout file is
empty, so `cmp` reports a difference. If the harness for producing a `trace.bin`/`task.bin`
pair is not obvious, generate one by running
`conda run -n cosa_snn python -m scripts.generate_weight_traces --help` and following the
existing single-layer path, keeping the temporary inputs under the scratch directory.

- [ ] **Step 3: Change the two signatures and add the selector**

`tick_output.h`: change the parameter type to `std::ostream&` and add `#include <ostream>`.
Each `main.cpp`: change the file-local `write_i32` to take `std::ostream&`, add
`#include <iostream>`, and insert the selector shown above, keeping each program's own
name in the error string.

- [ ] **Step 4: Run the script to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache && \
  src/archmodels/tests/stdout_roundtrip.sh <loas binary> <a trace.bin> <a task.bin>
```
Expected: `stdout_roundtrip: identical`. Repeat for all five binaries.

- [ ] **Step 5: Confirm nothing else pollutes stdout**

```bash
cd /home/ya867177/neuro_cache-wcache && grep -n "std::cout\|printf\|puts(" src/archmodels/*/main.cpp src/archmodels/tick_output.h
```
Expected: the only `std::cout` hits are the five selector lines added in Step 3.

- [ ] **Step 6: Checkpoint**

Rebuild the archmodels and re-run one existing end-to-end trace generation for a single
layer, confirming the produced `sample_00000.json.gz` is byte-identical to one generated
before the change. **Do not commit.**

---

## Task 6: Producer, swap the tile and sample loops

`main.cpp` runs `for tile_idx { for sample_idx }`, so one sample's tiles are interleaved
across the whole output and a stream would have to buffer everything
(§10.4, break 5). The fix is to swap the two loops in the five files.

Two facts make this the right change rather than the "one process per sample"
alternative. First, `tile_idx` in these programs indexes a `NodeTileSpec`, which is a
`(dram_i, noc_i, core_id)` triple, so one invocation already covers **every core**:
`assemble_layer_traces` (`src/tracegen.py:240`) groups the results by `(dram_i, noc_i)`
across `spec.core_id`. Second, nothing in `reconstruct_sample` carries state between
iterations, so the swap changes only the emission order.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/loas/main.cpp:121-131`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/ptb/main.cpp:120-130`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/spinalflow/main.cpp:120-130`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/prosperity/main.cpp:120-130`
- Modify: `/home/ya867177/neuro_cache-wcache/src/archmodels/gustavsnn/main.cpp:130-140`
- Modify: `/home/ya867177/neuro_cache-wcache/src/cachesim/native_bridge.py`
  (`_unpack_output`, if it assumes the old order)
- Modify: `/home/ya867177/neuro_cache-wcache/src/tracegen.py` (`assemble_layer_traces`
  docstring, which states the order)

**Interfaces:**
- Produces: the out.bin record order becomes `sample -> tile_idx`, with each record's
  header still `(tile_idx, sample_idx, mac_cycles, num_ticks)`, so the record **format**
  is unchanged and only the **order** moves. `_unpack_output` yields
  `(tile_idx, local_sample_idx, mac_cycles, ticks)` and must keep doing so.

- [ ] **Step 1: Write the failing test**

Create `/home/ya867177/neuro_cache-wcache/src/archmodels/tests/test_emission_order.py`:

```python
"""Task 6: the arch binaries must emit sample-outer, tile-inner.

A stream consumer sees one sample's tiles contiguously, which is what lets it
emit a tile the moment every core has reported it. Under the old tile-outer
order it would have to buffer every sample before it could emit tile 1.
"""
import struct
import sys


def record_order(path):
    """[(tile_idx, sample_idx), ...] in emission order, from out.bin."""
    out = []
    with open(path, "rb") as fh:
        data = fh.read()
    off = 0
    while off < len(data):
        tile_idx, sample_idx, _mac, n_ticks = struct.unpack_from("<iiii", data, off)
        off += 16
        for _ in range(n_ticks):
            _tick, n_addr = struct.unpack_from("<ii", data, off)
            off += 8 + 20 * n_addr
        out.append((tile_idx, sample_idx))
    return out


def test_sample_outer(path):
    order = record_order(path)
    samples = [s for _t, s in order]
    # Sample-outer means the sample index is non-decreasing over the whole file.
    assert samples == sorted(samples), f"not sample-outer: {samples[:20]}"
    # And within one sample the tile index ascends from 0.
    seen = {}
    for tile_idx, sample_idx in order:
        prev = seen.get(sample_idx, -1)
        assert tile_idx > prev, f"tiles out of order in sample {sample_idx}"
        seen[sample_idx] = tile_idx
    print(f"emission order: sample-outer over {len(set(samples))} samples, OK")


if __name__ == "__main__":
    test_sample_outer(sys.argv[1])
```

- [ ] **Step 2: Run it to verify it fails**

Produce an `out.bin` with at least two samples and two tiles, then:

```bash
cd /home/ya867177/neuro_cache-wcache && \
  conda run -n cosa_snn python src/archmodels/tests/test_emission_order.py /path/to/out.bin
```
Expected: `AssertionError: not sample-outer: [0, 1, 0, 1, ...]`.

- [ ] **Step 3: Swap the loops in all five files**

In each, replace

```cpp
    for (int32_t tile_idx = 0; tile_idx < num_tiles; ++tile_idx) {
        const TileSpec& tile = tiles[tile_idx];
        for (int32_t sample_idx : sample_indices) {
```

with

```cpp
    // Sample-outer, tile-inner. A stream consumer needs one sample's tiles
    // contiguously; under the old nesting it would have to buffer every sample
    // before it could emit tile 1. See §10.4 of the Phase D campaign plan.
    for (int32_t sample_idx : sample_indices) {
        for (int32_t tile_idx = 0; tile_idx < num_tiles; ++tile_idx) {
            const TileSpec& tile = tiles[tile_idx];
```

and fix the brace nesting. The four `write_i32` calls and `write_tick_grouped` are
untouched.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache && \
  conda run -n cosa_snn python src/archmodels/tests/test_emission_order.py /path/to/out.bin
```
Expected: `emission order: sample-outer over N samples, OK`.

- [ ] **Step 5: Confirm the JSON output is unchanged**

`assemble_layer_traces` groups by `(tile_idx, local_sample_idx)` into a dict, so it is
already order-independent; this step proves it rather than assuming it.

```bash
cd /home/ya867177/neuro_cache-wcache && \
  conda run -n cosa_snn python -c "
import gzip, json, hashlib, sys
h = hashlib.sha256(gzip.open(sys.argv[1]).read()).hexdigest()
print(h)
" /path/to/sample_00000.json.gz
```
Expected: the same digest as the one recorded before Task 5. If it differs, the swap
changed the data and not only the order, which is a bug in the swap.

- [ ] **Step 6: Update the two docstrings that state the order**

`src/tracegen.py:240` `assemble_layer_traces` and each `main.cpp`'s header comment
describe the out.bin record order. Change both to say sample-outer, tile-inner, and cite
§10.4. The **canonical on-disk order of the trace itself** (`dram_i -> noc_i -> tick ->
core`) is unchanged; only the intermediate binary's record order moved.

- [ ] **Step 7: Checkpoint**

Regenerate one layer end to end and diff against the pre-change output. **Do not commit.**

---

## Task 7: Producer, `tracegen.stream_weight_trace` emits the WCTS format

`save_weight_trace` stays, for the debug dump (§10.6). It gains a sibling that writes the
stream to an already-open binary file object instead of to a path.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/tracegen.py`
- Create: `/home/ya867177/neuro_cache-wcache/src/tests/test_stream_writer.py`

**Interfaces:**
- Consumes: `LayerWeightTrace`, `TileWeightTrace`, `TickEntry`, `CoreEntry` as they are;
  `nocsim.schedule.decode.Schedule.spatial_factors` for the header's `spatial_factors` and
  for `n_cores`.
- Produces:

```python
WCTS_MAGIC = b"WCTRACE1"
WCTS_VERSION = 1

def write_stream_header(fh, *, n_tiles, n_cores, weight_bytes, burst_dim,
                        burst_stride, spatial_factors, dims,
                        arch, workload, layer, sample_idx) -> None:
    """Writes the WCTS stream header. `spatial_factors` and `dims` are
    {dim_id: value} mappings using the wire codes 0=KH 1=KW 2=CIN 3=COUT
    4=HO 5=WO 6=T. `burst_dim` is one of those codes. Raises ValueError when
    prod(spatial_factors.values()) != n_cores, which is U25's check on the
    producer side."""

def write_tile_frame(fh, *, tile_index, mac_cycles, cores) -> int:
    """Writes one tile frame and returns the number of burst records written.
    `cores` is [(core_id, [(local_tick, (kh, kw, cin, run_start, run_end)), ...]),
    ...], which MUST be sorted by core_id and, inside each core, by local_tick.
    A core with no bursts must be omitted, never passed as an empty list."""

def write_stream_trailer(fh, total_bursts: int) -> None:
    """Writes the -1 end magic and the total burst count."""

def stream_weight_trace(trace: LayerWeightTrace, fh, *, n_cores, spatial_factors,
                        burst_dim=3, burst_stride=1, weight_bytes=1,
                        max_tiles=None) -> int:
    """Writes one whole LayerWeightTrace as a WCTS stream to the binary file
    object `fh`, header first, and returns the total burst count. The sibling to
    save_weight_trace: same data, a stream instead of a document, and no
    intermediate storage. `max_tiles` truncates the stream after that many tile
    frames, which is what --dump-trace-tiles uses to produce a valid short
    stream. Does not close `fh`."""
```

The tile-frame conversion, stated exactly because it is where a mistake is invisible:

```
tick-major -> core-major
    for each TileWeightTrace t, in the order it appears in trace.tiles:
        by_core = {}
        for entry in t.ticks:                     # entry.tick, entry.cores
            for c in entry.cores:                 # c.core_id, c.weight_addresses
                for addr in c.weight_addresses:   # [kh, kw, cin, cout_start, cout_end]
                    by_core.setdefault(c.core_id, []).append((entry.tick, tuple(addr)))
        cores = [(cid, by_core[cid]) for cid in sorted(by_core)]
    mac_cycles = t.mac_cycles                     # already the max over that tile's cores
```

Note what this does **not** do: it does not renumber ticks, does not pad an absent core,
and does not sort inside a core, because `t.ticks` is already ascending in `tick` and the
corpus survey found no `(core, tick)` pair carrying more than one burst
(`PROGRESS.md:942`), so appending in tick order is already ascending. Add an assertion
that it is, so a future generator that breaks that property fails here rather than
producing a stream the reader rejects three stages downstream.

- [ ] **Step 1: Write the failing test**

Create `src/tests/test_stream_writer.py`:

```python
"""Task 7: the Python writer and the C++ reader must agree on the wire format.

This is a round-trip test through the REAL reader: it writes a stream from a
hand-built LayerWeightTrace and feeds it to wcache_run's decode-only path. Until
wcache_run exists (Task 15) it checks the byte layout directly, which is the half
that can be checked without it.
"""
import io
import struct

from tracegen import (CoreEntry, LayerWeightTrace, TickEntry, TileWeightTrace,
                      stream_weight_trace)


def tiny_trace():
    t0 = TileWeightTrace(dram_i=0, noc_i=0, mac_cycles=10, lif_cycles=None, ticks=[
        TickEntry(tick=0, cores=[CoreEntry(core_id=0, weight_addresses=[[1, 1, 6, 0, 16]]),
                                 CoreEntry(core_id=2, weight_addresses=[[0, 0, 0, 16, 32]])]),
        TickEntry(tick=1, cores=[CoreEntry(core_id=0, weight_addresses=[[1, 1, 7, 0, 16]])]),
    ])
    t1 = TileWeightTrace(dram_i=0, noc_i=1, mac_cycles=8, lif_cycles=None, ticks=[
        TickEntry(tick=0, cores=[CoreEntry(core_id=1, weight_addresses=[[2, 2, 2, 0, 16]])]),
    ])
    return LayerWeightTrace(arch="loas", trace_dir="vgg16_T4_all",
                            layer_name="layer_01_features_3", sample_idx=0,
                            workload_dims={"KH": 3, "KW": 3, "CIN": 64, "COUT": 64,
                                           "HO": 32, "WO": 32, "T": 4},
                            dram_num_steps=1, noc_num_steps=2, tiles=[t0, t1])


def test_header_and_frames():
    buf = io.BytesIO()
    total = stream_weight_trace(tiny_trace(), buf, n_cores=4,
                                spatial_factors={3: 4})
    assert total == 4, total
    data = buf.getvalue()
    assert data[:8] == b"WCTRACE1"
    version, header_bytes = struct.unpack_from("<II", data, 8)
    assert version == 1
    n_tiles, n_cores, weight_bytes, burst_dim, burst_stride = struct.unpack_from(
        "<iiiii", data, 16)
    assert (n_tiles, n_cores, weight_bytes, burst_dim, burst_stride) == (2, 4, 1, 3, 1)
    n_addr, n_spatial, n_dims, ident = struct.unpack_from("<iiii", data, 36)
    assert (n_addr, n_spatial, n_dims) == (5, 1, 7)
    assert header_bytes == 52 + 4 * n_addr + 8 * n_spatial + 8 * n_dims + ident
    # First tile frame, immediately after the header.
    tile_index, n_blocks, mac, payload = struct.unpack_from("<iiQQ", data, header_bytes)
    assert (tile_index, n_blocks, mac) == (0, 2, 10)
    assert payload > 0
    # Trailer.
    end_magic, total_bursts = struct.unpack_from("<iQ", data, len(data) - 12)
    assert end_magic == -1 and total_bursts == 4


def test_spatial_product_must_match_n_cores():
    buf = io.BytesIO()
    try:
        stream_weight_trace(tiny_trace(), buf, n_cores=8, spatial_factors={3: 4})
    except ValueError:
        return
    raise AssertionError("expected ValueError: prod(spatial_factors) != n_cores")


def test_max_tiles_truncates_to_a_valid_short_stream():
    buf = io.BytesIO()
    total = stream_weight_trace(tiny_trace(), buf, n_cores=4, spatial_factors={3: 4},
                                max_tiles=1)
    data = buf.getvalue()
    n_tiles = struct.unpack_from("<i", data, 16)[0]
    assert n_tiles == 1, "the header must declare the TRUNCATED tile count"
    end_magic, total_bursts = struct.unpack_from("<iQ", data, len(data) - 12)
    assert end_magic == -1 and total_bursts == total == 3


if __name__ == "__main__":
    test_header_and_frames()
    test_spatial_product_must_match_n_cores()
    test_max_tiles_truncates_to_a_valid_short_stream()
    print("test_stream_writer: OK")
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src && \
  conda run -n cosa_snn python tests/test_stream_writer.py
```
Expected: `ImportError: cannot import name 'stream_weight_trace' from 'tracegen'`.

- [ ] **Step 3: Implement the four functions in `src/tracegen.py`**

Put them directly below `save_weight_trace`, with a module-level comment saying they are
the in-flight sibling and pointing at §10 of the campaign plan and at this plan's wire
format section. Note that `max_tiles` must be applied **before** the header is written,
because `n_tiles` is a header field: build the tile list, slice it, then write.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src && \
  conda run -n cosa_snn python tests/test_stream_writer.py
```
Expected: `test_stream_writer: OK`.

- [ ] **Step 5: Checkpoint**

Re-run Task 6's Step 5 digest check to confirm `save_weight_trace` still produces the
same bytes. **Do not commit.**

---

## Task 8: Producer, `generate_weight_traces.py --stream` and the debug tee

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/scripts/generate_weight_traces.py`

**Interfaces:**
- Consumes: Task 7's `stream_weight_trace`; the existing single-layer generation path.
- Produces: the three flags in "The CLI, in full", and this contract:
  with `--stream`, the script writes **one** WCTS stream to `sys.stdout.buffer` and
  nothing else to stdout; every log line goes to stderr; the selection must resolve to
  exactly one `(arch, trace_dir, layer, sample_idx)` or the script exits 2 with a message
  naming how many it resolved to.

Worker parallelism moves up a level (§10.4, break 7). Inside `--stream` the script is
strictly serial: N workers cannot share one stdout pipe. The replacement for
`--workers` inside a stream is **N independent producer-consumer pipeline pairs**, which
is Task 21's driver, not this script's job. `--stream` must therefore **reject**
`--workers > 1` with a message saying so, rather than silently ignoring it.

- [ ] **Step 1: Write the failing test**

Create `/home/ya867177/neuro_cache-wcache/scripts/tests/test_stream_flag.sh`:

```sh
#!/bin/sh
# Task 8: --stream writes exactly one valid WCTS stream on stdout and nothing else.
set -e
cd /home/ya867177/neuro_cache-wcache
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

conda run -n cosa_snn python scripts/generate_weight_traces.py \
    --stream --arch loas --trace-dir vgg16_T4_all \
    --layer layer_01_features_3 --sample 0 \
    --dump-trace "$tmp/dump.bin" --dump-trace-tiles 2 \
    > "$tmp/stream.bin" 2> "$tmp/log.txt"

# 1. stdout starts with the magic.
head -c 8 "$tmp/stream.bin" | grep -q 'WCTRACE1'
# 2. the tee is a byte-identical PREFIX of what the consumer saw, up to 2 tiles.
conda run -n cosa_snn python - "$tmp/stream.bin" "$tmp/dump.bin" <<'PY'
import struct, sys
full = open(sys.argv[1], "rb").read()
dump = open(sys.argv[2], "rb").read()
assert dump[:8] == b"WCTRACE1"
assert struct.unpack_from("<i", dump, 16)[0] == 2, "dump must declare 2 tiles"
assert struct.unpack_from("<i", dump, len(dump) - 12)[0] == -1, "dump needs a trailer"
# The two headers differ only in n_tiles; every tile frame that both carry must match.
hb_full = struct.unpack_from("<I", full, 12)[0]
hb_dump = struct.unpack_from("<I", dump, 12)[0]
assert hb_full == hb_dump
body_dump = dump[hb_dump:len(dump) - 12]
assert full[hb_full:hb_full + len(body_dump)] == body_dump, "tee is not byte-identical"
print("stream + tee: OK")
PY
# 3. nothing but the stream on stdout: the file size equals what the reader consumes.
test -s "$tmp/log.txt"
echo "test_stream_flag: OK"
```

`chmod +x` it.

- [ ] **Step 2: Run it to verify it fails**

```bash
/home/ya867177/neuro_cache-wcache/scripts/tests/test_stream_flag.sh
```
Expected: FAIL, `unrecognized arguments: --stream`.

- [ ] **Step 3: Implement the three flags**

Add `--stream`, `--dump-trace`, `--dump-trace-tiles` to the parser. In the `--stream`
branch: resolve the selection, reject a non-singleton and reject `--workers > 1`, redirect
every existing print to `sys.stderr`, generate the one sample through the existing path,
and call `stream_weight_trace(trace, sys.stdout.buffer, ...)`. When `--dump-trace` is set,
wrap the output in a small tee class:

```python
class _Tee:
    """Writes to the real sink and, for the first `max_tiles` tile frames, to a
    debug file as well. Off by default, so the normal path materialises nothing
    (§10.6, ruling R4)."""
    def __init__(self, sink, dump_path, max_tiles):
        ...
    def write(self, b):
        ...
```

The simplest correct implementation, and the one to use, is not a byte tee at all: call
`stream_weight_trace` twice, once into `sys.stdout.buffer` with `max_tiles=None` and once
into the dump file with `max_tiles=N`. It is one extra pass over data already in memory,
it produces a **valid short stream** rather than a truncated one, and it cannot get the
trailer wrong. Say so in a comment, because "tee" in §10.6 suggests the byte-copy version.

`n_cores` and `spatial_factors` come from the decoded schedule
(`nocsim.schedule.decode`), not from the trace: `spatial_factors` is a
`{dim_idx: factor}` mapping and `n_cores = prod(spatial_factors.values())`. Assert
`max(core_id over the sample) < n_cores`, which is the check U25 says
`max(core_id) + 1` fails (prosperity implies 126 where the machine is 128).

- [ ] **Step 4: Run the script to verify it passes**

```bash
/home/ya867177/neuro_cache-wcache/scripts/tests/test_stream_flag.sh
```
Expected: `stream + tee: OK` then `test_stream_flag: OK`.

- [ ] **Step 5: Checkpoint**

Run the script **without** `--stream` on the same layer and confirm the
`sample_00000.json.gz` digest is unchanged from Task 6 Step 5. **Do not commit.**

---

## Task 9: D1a, `RunConfig`, parse and defaults

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/config.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/config.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_config.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/mutation_check.sh:65`

**Interfaces:**
- Consumes: `EngineParams`, `LevelParams`, `PolicyKind`, `PrefetchKind`, `Inclusion`.
- Produces the single source of truth for the parameter set (v3 D1's own words):

```cpp
namespace wcache {

struct RunConfig {
    // --- layout, which fixes line_size_bytes = cin_block*cout_block*weight_bytes
    std::int32_t cin_block    = 1;
    std::int32_t cout_block   = 16;
    std::int32_t weight_bytes = 1;

    // --- geometry
    std::int64_t l1_size_bytes = 8 * 1024;
    std::int32_t l1_assoc      = 8;
    std::int64_t l2_size_bytes = 512 * 1024;
    std::int32_t l2_assoc      = 16;
    PolicyKind   policy        = PolicyKind::LRU;   // one knob, both levels (§9.2)
    Inclusion    inclusion     = Inclusion::NonInclusive;

    // --- concurrency
    std::int32_t l1_mshrs          = 16;
    std::int32_t l1_tgts_per_mshr  = 20;
    std::int32_t l2_mshrs          = 20;
    std::int32_t l2_tgts_per_mshr  = 12;
    // -1 means "the default, lines_per_burst", resolved by validate() once the
    // trace's burst span is known. A sentinel rather than an optional, because a
    // config that DECLARES 0 and a config that omits the field must not be the
    // same config.
    std::int32_t l1_demand_reserve = -1;

    // --- timing
    std::int64_t l1_latency      = 0;
    std::int64_t l1_ii           = 1;
    std::int64_t l2_latency      = 10;
    std::int64_t l2_to_l1_latency = 0;
    std::int64_t l2_miss_latency = 100;
    std::int32_t l2_banks        = 1;
    std::int64_t l2_ii           = 1;
    std::int64_t dram_ii         = 1;
    std::int64_t core_accept_ii  = 1;

    // --- prefetch
    PrefetchKind prefetch_policy   = PrefetchKind::None;
    std::int32_t prefetch_distance = 0;

    std::int64_t line_size_bytes() const;   // cin_block * cout_block * weight_bytes
    std::int64_t l1_num_lines() const;      // l1_size_bytes / line_size_bytes
    std::int64_t l1_num_sets() const;       // l1_num_lines / l1_assoc
    std::int64_t l2_num_lines() const;
    std::int64_t l2_num_sets() const;
};

// Parses a JSON object. Every field is optional and falls back to the struct's
// default. An UNKNOWN key is an ERROR, not a warning: a typo in a swept knob
// that loads silently is a run that measures the default while claiming to
// measure the sweep. `l2_demand_reserve` is rejected by name with its own
// message (Task 10, ruling Q8).
RunConfig parse_config(const std::string& json_text);

// Expands a grid document into configurations, in declaration order (Task 18).
std::vector<RunConfig> parse_config_grid(const std::string& json_text);

}  // namespace wcache
```

JSON: this tree has no JSON library and adds none. `src/config.cpp` carries a
~200-line recursive-descent parser for the subset the configs use, which is objects,
arrays, strings, integers, floats and the three literals, with no comments and no
trailing commas. It rejects anything else with `std::invalid_argument` naming the byte
offset. That is smaller than vendoring a library, and it is the same choice the tree
already made for its other primitives.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.cpp`:

```cpp
#include <wcache/cache_level.h>
#include <wcache/config.h>
#include <wcache/engine.h>

#include <stdexcept>
#include <string>

#include "check.h"

using namespace wcache;

namespace {

void test_an_empty_object_gives_the_documented_defaults() {
    check::group("Task 9: {} is the §6.3 / §7.3 default configuration");
    const RunConfig c = parse_config("{}");
    CHECK_EQ(c.l1_assoc, 8);
    CHECK_EQ(c.l2_assoc, 16);
    CHECK_EQ(c.l1_mshrs, 16);
    CHECK_EQ(c.l1_tgts_per_mshr, 20);
    CHECK_EQ(c.l2_mshrs, 20);
    CHECK_EQ(c.l2_tgts_per_mshr, 12);
    CHECK_EQ(c.l1_latency, std::int64_t{0});
    CHECK_EQ(c.l2_latency, std::int64_t{10});
    CHECK_EQ(c.l2_miss_latency, std::int64_t{100});
    CHECK_EQ(c.core_accept_ii, std::int64_t{1});
    CHECK_EQ(c.prefetch_distance, 0);
    CHECK_TRUE(c.policy == PolicyKind::LRU);
    CHECK_TRUE(c.inclusion == Inclusion::NonInclusive);
    CHECK_TRUE(c.prefetch_policy == PrefetchKind::None);
    CHECK_EQ(c.l1_demand_reserve, -1);   // the "resolve me from the trace" sentinel
}

void test_line_size_and_geometry_are_derived_not_declared() {
    check::group("Task 9: line_size_bytes = cin_block * cout_block * weight_bytes");
    const RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "weight_bytes": 1,
            "l1_size_bytes": 2048, "l1_assoc": 8})");
    CHECK_EQ(c.line_size_bytes(), std::int64_t{64});
    CHECK_EQ(c.l1_num_lines(), std::int64_t{32});
    CHECK_EQ(c.l1_num_sets(), std::int64_t{4});   // §4.5's extreme point
}

void test_an_unknown_key_is_rejected() {
    check::group("Task 9: an unknown key throws rather than loading silently");
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"l1_sz": 2048})"));
}

void test_every_enum_spelling_round_trips() {
    check::group("Task 9: the string spellings the grids use all parse");
    CHECK_TRUE(parse_config(R"({"policy": "fifo"})").policy == PolicyKind::FIFO);
    CHECK_TRUE(parse_config(R"({"inclusion": "inclusive"})").inclusion
               == Inclusion::Inclusive);
    CHECK_TRUE(parse_config(R"({"prefetch_policy": "next_burst",
                                "prefetch_distance": 4})").prefetch_policy
               == PrefetchKind::NextBurst);
    CHECK_THROWS(std::invalid_argument, parse_config(R"({"policy": "clock"})"));
}

}  // namespace

int main() {
    test_an_empty_object_gives_the_documented_defaults();
    test_line_size_and_geometry_are_derived_not_declared();
    test_an_unknown_key_is_rejected();
    test_every_enum_spelling_round_trips();
    return check::summary();
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_config
```
Expected: FAIL, `fatal error: wcache/config.h: No such file or directory`.

- [ ] **Step 3: Write `config.h` and the parse half of `config.cpp`**

`validate` and `to_engine_params` are declared but not yet defined, so Task 10's cases
fail to link and Task 9's pass.

- [ ] **Step 4: Run it to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_config
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Add to the mutation list, then Checkpoint**

Add `include/wcache/config.h` and `src/config.cpp` to `FILES=`, then

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green. **Do not commit.**

---

## Task 10: D1b, validation, the three guards and the `l2_demand_reserve` rejection

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/config.h`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/config.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_config.cpp`

**Interfaces:**
- Produces:

```cpp
// A validation finding. Warnings are RETURNED rather than printed, so the caller
// decides where they go: wcache_run puts them on stderr, wcache_sweep folds them
// into a column, and a test reads them without capturing a stream.
struct Warning { std::string code; std::string message; };

// Checks every rule below and RESOLVES l1_demand_reserve from `lines_per_burst`
// when it is the -1 sentinel. `lines_per_burst` comes from the trace's burst span
// under this config's layout, so validation is not possible before the stream
// header is read. Throws std::invalid_argument, naming the offending field and the
// rule, on any rejection. Appends to `warnings` on any warning.
void validate(RunConfig& cfg, std::int32_t lines_per_burst,
              std::vector<Warning>& warnings);

// The engine's knobs, from a validated config. Precondition: validate() has run,
// enforced by throwing when l1_demand_reserve is still -1.
EngineParams to_engine_params(const RunConfig& cfg);
```

The complete rule list, which is what makes this the single source of truth:

**Rejections** (each throws `std::invalid_argument`):

| Rule | Source |
|---|---|
| `l2_demand_reserve` present as a key at all | ruling Q8, G11, B159. The message must say the knob is dead and that D1 must not offer it as a sweep dimension. |
| `l1_size_bytes < l1_assoc * line_size_bytes` (fewer than one set), and the same for L2 | §4.5 finding (4) |
| `l1_size_bytes % line_size_bytes != 0`, and the same for L2 | geometry: a partial line is not a cache |
| `l1_num_lines() % l1_assoc != 0`, and the same for L2 | a partial set is not a set |
| `inclusion == exclusive` | v3 V19, G1. Not silently downgraded. |
| `policy == random` | v3 V29, A5 Q5. Random is a placeholder. |
| `lines_per_burst > l1_mshrs` | v3 V12, N7 |
| `core_accept_ii < 1` | v3 D1 row |
| `prefetch_distance < 0` | v3 D1 row |
| `prefetch_policy == next_burst && prefetch_distance == 0` | v3 D1 row: it must not silently mean `none` |
| `l1_demand_reserve >= l1_mshrs` | v3 D1 row: prefetching unreachable while claiming to be on |
| any of `l1_assoc, l2_assoc, l1_mshrs, l1_tgts_per_mshr, l2_mshrs, l2_tgts_per_mshr, l2_banks, cin_block, cout_block, weight_bytes < 1` | arithmetic |
| any of `l1_ii, l2_ii, dram_ii < 0`, or any latency `< 0` | v3 B1 |

**Warnings** (appended to `warnings`, never fatal):

| Code | Condition | Source |
|---|---|---|
| `W_MSHR_VS_LINES` | `l1_mshrs >= l1_num_lines() / 2` | §4.5 finding (1). Fires exactly at 2 KB / 64 B / 8-way: 16 >= 16. |
| `W_FEW_SETS` | `l1_num_sets() < 8` | §4.5 finding (2), naming G10 and the power-of-two radix aliasing |
| `W_PREFETCH_BUDGET` | `l1_mshrs - l1_demand_reserve < lines_per_burst` | v3 D1 row: the run measures the pool, not the policy |
| `W_ZERO_II` | `l1_ii == 0 or l2_ii == 0` | v3 B1, N13 |

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.cpp` and call each from `main()`:

```cpp
void test_l2_demand_reserve_is_rejected_by_name() {
    check::group("Task 10: l2_demand_reserve is REJECTED at load (ruling Q8, G11)");
    // Not merely unknown: it must be rejected with its own message, so a sweeper
    // who tries it learns the knob is dead rather than that they mistyped.
    bool named = false;
    try {
        parse_config(R"({"l2_demand_reserve": 4})");
    } catch (const std::invalid_argument& e) {
        named = std::string(e.what()).find("l2_demand_reserve") != std::string::npos;
    }
    CHECK_TRUE(named);
}

void test_fewer_than_one_set_is_rejected() {
    check::group("Task 10: l1_size < l1_assoc * line_size is rejected (§4.5(4))");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 256, "l1_assoc": 8})");
    std::vector<Warning> w;
    CHECK_THROWS(std::invalid_argument, validate(c, 4, w));   // 8*64 = 512 > 256
}

void test_the_two_small_cache_warnings_fire_at_the_extreme_point() {
    check::group("Task 10: 2 KB / 64 B / 8-way warns twice and runs (§4.5(1),(2))");
    RunConfig c = parse_config(
        R"({"cin_block": 4, "cout_block": 16, "l1_size_bytes": 2048, "l1_assoc": 8,
            "l1_mshrs": 16})");
    std::vector<Warning> w;
    validate(c, 4, w);                       // must NOT throw: the corner is kept
    CHECK_EQ(c.l1_num_lines(), std::int64_t{32});
    CHECK_EQ(c.l1_num_sets(), std::int64_t{4});
    bool mshr = false, sets = false;
    for (const Warning& x : w) {
        if (x.code == "W_MSHR_VS_LINES") mshr = true;
        if (x.code == "W_FEW_SETS")      sets = true;
    }
    CHECK_TRUE(mshr);    // 16 >= 32/2
    CHECK_TRUE(sets);    // 4 < 8
}

void test_demand_reserve_defaults_to_lines_per_burst() {
    check::group("Task 10: the -1 sentinel resolves to lines_per_burst");
    RunConfig c = parse_config("{}");
    std::vector<Warning> w;
    validate(c, 4, w);                       // Spinalflow's 64-cout burst at cout_block 16
    CHECK_EQ(c.l1_demand_reserve, 4);
}

void test_the_v3_d1_row_rejections() {
    check::group("Task 10: every rejection the v3 D1 row names");
    std::vector<Warning> w;
    RunConfig a = parse_config(R"({"inclusion": "exclusive"})");
    CHECK_THROWS(std::invalid_argument, validate(a, 1, w));
    RunConfig b = parse_config(R"({"policy": "random"})");
    CHECK_THROWS(std::invalid_argument, validate(b, 1, w));
    RunConfig c = parse_config(R"({"core_accept_ii": 0})");
    CHECK_THROWS(std::invalid_argument, validate(c, 1, w));
    RunConfig d = parse_config(R"({"prefetch_distance": -1})");
    CHECK_THROWS(std::invalid_argument, validate(d, 1, w));
    RunConfig e = parse_config(R"({"prefetch_policy": "next_burst"})");
    CHECK_THROWS(std::invalid_argument, validate(e, 1, w));   // distance still 0
    RunConfig f = parse_config(R"({"l1_mshrs": 4, "l1_demand_reserve": 4})");
    CHECK_THROWS(std::invalid_argument, validate(f, 4, w));   // reserve >= mshrs
    RunConfig g = parse_config(R"({"l1_mshrs": 2})");
    CHECK_THROWS(std::invalid_argument, validate(g, 4, w));   // lines_per_burst > mshrs
}

void test_the_classic_gem5_l1_warns_for_spinalflow() {
    check::group("Task 10: l1_mshrs = 4 with a 4-line burst warns (§6.3, Q4)");
    RunConfig c = parse_config(R"({"l1_mshrs": 5, "l1_demand_reserve": 4})");
    std::vector<Warning> w;
    validate(c, 4, w);
    bool budget = false;
    for (const Warning& x : w) if (x.code == "W_PREFETCH_BUDGET") budget = true;
    CHECK_TRUE(budget);                      // budget 1 < lines_per_burst 4
}

void test_to_engine_params_requires_validation_first() {
    check::group("Task 10: to_engine_params on an unvalidated config throws");
    const RunConfig c = parse_config("{}");
    CHECK_THROWS(std::invalid_argument, to_engine_params(c));   // reserve still -1
}

void test_to_engine_params_carries_every_knob() {
    check::group("Task 10: every RunConfig knob reaches EngineParams");
    RunConfig c = parse_config(
        R"({"l1_size_bytes": 4096, "l1_assoc": 8, "l2_size_bytes": 262144,
            "l2_assoc": 16, "l1_latency": 0, "l2_latency": 10,
            "l2_miss_latency": 100, "l2_banks": 1, "l2_ii": 1, "dram_ii": 1,
            "core_accept_ii": 1, "l1_mshrs": 16, "l1_tgts_per_mshr": 20,
            "l2_mshrs": 20, "l2_tgts_per_mshr": 12,
            "prefetch_policy": "next_burst", "prefetch_distance": 4})");
    std::vector<Warning> w;
    validate(c, 1, w);
    const EngineParams p = to_engine_params(c);
    CHECK_EQ(p.l1.cache_size_bytes, std::int64_t{4096});
    CHECK_EQ(p.l1.associativity, 8);
    CHECK_EQ(p.l1.mshrs, 16);
    CHECK_EQ(p.l1.tgts_per_mshr, 20);
    CHECK_EQ(p.l1.demand_reserve, 1);
    CHECK_EQ(p.l2.cache_size_bytes, std::int64_t{262144});
    CHECK_EQ(p.l2.associativity, 16);
    CHECK_EQ(p.l2.demand_reserve, 0);   // L2 reserve is DEAD: always 0 (G11)
    CHECK_EQ(p.l2.latency, SimTime{10});
    CHECK_EQ(p.l2_miss_latency, SimTime{100});
    CHECK_EQ(p.core_accept_ii, SimTime{1});
    CHECK_EQ(p.prefetch_distance, 4);
    CHECK_TRUE(p.prefetch_policy == PrefetchKind::NextBurst);
}
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_config
```
Expected: FAIL to link, `undefined reference to 'wcache::validate(...)'`.

- [ ] **Step 3: Implement `validate` and `to_engine_params`**

Rejections in the table's order, so the first message a user sees is the most structural
one. `to_engine_params` sets `p.l2.demand_reserve = 0` unconditionally and carries a
comment saying G11 killed the knob, which is what makes the deletion visible in the code
rather than only in a plan.

- [ ] **Step 4: Run them to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_config
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green. **Do not commit.**

---

## Task 11: D2a, extend `EngineStats` with the stall breakdown and prefetch outcomes

`EngineStats` today holds nine fields, and its own comment says Part 8 "asks for far more
than this ... and all of it is D2's". §9.2's schema needs the eight-way stall
attribution, the four prefetch outcome states, the memory counters, the MSHR occupancy
histograms and the model-health counters, none of which exist. This task adds the
counters; Task 12 handles `fetch_latency`, which is a redefinition rather than an
addition, and Task 13 turns them into a row.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/engine.h`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/engine.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/engine_core.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/cache_level.h`
  and `src/cache_level.cpp` (hit and access counters per level)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/mshr.h`
  and `src/mshr.cpp` (occupancy sampling)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_engine.cpp`

**Interfaces:**
- Produces, appended to `EngineStats` with the existing nine fields untouched:

```cpp
    // --- Part 8 "Time": the stall breakdown. Per core, and the eight MUST sum:
    // stall_total[c] == the sum of the eight causes (V21).
    std::vector<std::int64_t> stall_l1_slot;
    std::vector<std::int64_t> stall_l1_line;
    std::vector<std::int64_t> stall_l2_slot;
    std::vector<std::int64_t> stall_l2_line;
    std::vector<std::int64_t> stall_l1_port;
    std::vector<std::int64_t> stall_l2_port;
    std::vector<std::int64_t> stall_channel;
    std::vector<std::int64_t> stall_barrier;
    std::vector<std::int64_t> stall_total;

    // --- Part 8 "Prefetch": the four outcome states, which MUST sum to pf_issued
    // together with the five drop counts already present.
    std::int64_t pf_issued  = 0;
    std::int64_t pf_timely  = 0;   // the demand access hit the prefetched line
    std::int64_t pf_late    = 0;   // the demand merged onto it while outstanding
    std::int64_t pf_wasted  = 0;   // evicted or invalidated before the core arrived
    std::int64_t pf_dropped_targets_full = 0;   // the fifth drop reason §9.2 names
    std::int64_t pf_pollution_evictions  = 0;
    std::int64_t pf_bursts_eligible      = 0;   // not-first-in-tile, the coverage ceiling

    // --- Part 8 "Model health" and the memory counters
    std::int64_t l1_hits = 0, l1_accesses = 0;
    std::int64_t l2_hits = 0, l2_accesses = 0;
    std::int64_t dram_accesses = 0;
    std::int64_t hits_downgraded_to_miss = 0;   // D4
    std::int64_t max_wait_depth = 0;            // against the I11 bound
    std::int64_t events = 0;                    // every dispatch
    // Occupancy samples, one per allocate and one per retire, per level. Task 13
    // reduces them to p50/p95/max; keeping the samples rather than a running
    // histogram keeps the reduction out of the hot path.
    std::vector<std::int32_t> l1_mshr_occupancy;
    std::vector<std::int32_t> l2_mshr_occupancy;
```

The stall attribution rule, stated because it is where an implementation invents its own
answer: a core is charged for the cycles between `want(c, k)` and `served(c, k)`, and
those cycles are attributed to the **reason its request was last blocked**. Concretely,
each `Request` carries a `StallCause cause` field set at every refusal point, and
`core_line_done` adds `served - want` to the bucket named by the cause of the **last**
line of the burst to land. `stall_barrier` is charged separately, in `barrier_arrive`, as
`tile_origin[N+1] - (that core's own arrival time)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine.cpp`:

```cpp
void test_the_stall_breakdown_sums_to_total_stall() {
    check::group("Task 11: V21, the stall breakdown sums to total stall");
    // A bounded L1 and a slow L2, so several causes actually fire.
    fx::FakeTrace tr(4);
    for (std::int32_t t = 0; t < 3; ++t) {
        const std::int32_t tile = tr.add_tile(6);
        for (std::int32_t c = 0; c < 4; ++c)
            for (std::int32_t k = 0; k < 4; ++k)
                tr.add_burst(tile, c, k, (t * 16) + (c * 4) + k);
    }
    fx::LinearMapper mapper;
    EngineParams p = fx::unbounded_params(4, 2);   // 4 sets, 2-way: it evicts
    p.l1.mshrs = 2;  p.l1.tgts_per_mshr = 2;  p.l1.demand_reserve = 1;
    p.l2.latency = SimTime{10};  p.l2_miss_latency = SimTime{100};
    Engine e(mapper, tr, p);
    e.run();
    const EngineStats& s = e.stats();
    for (std::size_t c = 0; c < s.stall_total.size(); ++c) {
        const std::int64_t parts = s.stall_l1_slot[c] + s.stall_l1_line[c] +
                                   s.stall_l1_port[c] + s.stall_l2_slot[c] +
                                   s.stall_l2_line[c] + s.stall_l2_port[c] +
                                   s.stall_channel[c] + s.stall_barrier[c];
        CHECK_EQ(parts, s.stall_total[c]);
    }
    CHECK_TRUE(s.l1_accesses > 0);
    CHECK_EQ(s.l1_hits + (s.l1_accesses - s.l1_hits), s.l1_accesses);
    CHECK_TRUE(s.events > 0);
}

void test_the_four_prefetch_states_sum_to_issued() {
    check::group("Task 11: timely + late + wasted + still-live == pf_issued");
    fx::FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(8);
    for (std::int32_t c = 0; c < 2; ++c)
        for (std::int32_t k = 0; k < 6; ++k) tr.add_burst(t0, c, k, (c * 6) + k);
    fx::LinearMapper mapper;
    EngineParams p = fx::unbounded_params(8, 2);
    p.l1.mshrs = 8;  p.l1.demand_reserve = 1;
    p.l2.latency = SimTime{10};
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 2;
    Engine e(mapper, tr, p);
    e.run();
    const EngineStats& s = e.stats();
    const std::int64_t dropped = s.pf_dropped_array_hit + s.pf_dropped_entry +
                                 s.pf_dropped_no_slot + s.pf_dropped_reserve +
                                 s.pf_dropped_targets_full;
    CHECK_EQ(s.pf_timely + s.pf_late + s.pf_wasted, s.pf_issued);
    CHECK_TRUE(dropped >= 0);
    CHECK_TRUE(s.pf_bursts_eligible > 0);
}

void test_prefetch_off_leaves_every_new_counter_at_zero() {
    check::group("Task 11: with prefetching off the prefetch block is all zero");
    fx::FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(4);
    tr.add_burst(t0, 0, 0, 0);  tr.add_burst(t0, 1, 0, 1);
    fx::LinearMapper mapper;
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    const EngineStats& s = e.stats();
    CHECK_EQ(s.pf_issued, std::int64_t{0});
    CHECK_EQ(s.pf_timely, std::int64_t{0});
    CHECK_EQ(s.pf_late, std::int64_t{0});
    CHECK_EQ(s.pf_wasted, std::int64_t{0});
    CHECK_EQ(s.pf_pollution_evictions, std::int64_t{0});
}
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_engine
```
Expected: FAIL to compile, `'struct wcache::EngineStats' has no member named 'stall_total'`.

- [ ] **Step 3: Implement the counters**

Add the fields, size the per-core vectors in the `Engine` constructor, and increment at
the points named in the attribution rule above. `l1_hits`/`l1_accesses` come from
`CacheLevel::triage` outcomes; the MSHR occupancy sample is one `push_back` in
`MshrFile::allocate` and one in `retire`. `events` is one increment at the top of
`dispatch`. `pf_wasted` is charged in the eviction path when the evicted line has a
"prefetched, not yet demanded" bit; `pf_pollution_evictions` is charged when such an
evicted line is subsequently demanded within the same tile.

- [ ] **Step 4: Run them to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_engine
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green, including `test_prefetch`, whose V22 case asserts that
`prefetch_policy = none` produces a byte-identical event log. Counters do not schedule
events, so that must still hold; if it does not, a counter was added inside a scheduling
decision. **Do not commit.**

---

## Task 12: D2b, line-anchored `fetch_latency` and `hidden_latency` (ruling R8)

This is the Q5 decision, recorded as ruling **R8**. It replaces the definition
`EngineStats::fetch_latency` carries today.

**The ruling, verbatim in its consequences.** `fetch_latency` is **line-anchored**:

```
fetch_latency[c] = Σ_k ( served(c, k) − t_first_request(line) )
```

where `t_first_request` is the **prefetch's issue time** when the line was brought in by
a prefetch, or merged onto an outstanding prefetch, and the **demand's issue time**
otherwise. `core_stall` is unchanged: `Σ_k (served(c, k) − want(c, k))`.

```
hidden_latency  = fetch_latency − core_stall        guaranteed >= 0
hidden_fraction = hidden_latency / fetch_latency    (empty when fetch_latency == 0)
```

**The one ambiguity R8 leaves, resolved here and flagged as OPEN QUESTION 1.** The
formula sums over **bursts** `k` but anchors on a **line**, and a burst is
`lines_per_burst` lines (4 for Spinalflow). Two readings exist. This plan takes:

> `t_first_request(burst k)` = the **minimum** `t_first_request` over the lines of burst
> `k`, so each burst contributes exactly one term.

That reading is forced, not chosen. The alternative, one term per line, makes
`fetch_latency` scale with `lines_per_burst` and therefore **breaks the `d = 0` identity
`fetch_latency == core_stall`** that v3 `:1438` calls "equal by construction" and that
§5.4 relies on as a per-row consistency check. A definition that breaks a documented
identity on the control arm is the wrong reading of an ambiguous formula.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/mshr.h`
  (`Mshr` gains `SimTime first_request`)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/mshr.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/engine.h`
  (`CoreState` gains `SimTime burst_anchor`)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/engine_core.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_engine.cpp`

**Interfaces:**
- Produces:

```cpp
// mshr.h, inside Mshr
// The instant the line was FIRST requested, which is the prefetch's issue time
// when a prefetch opened the entry and the demand's issue time otherwise. It is
// set once, at allocate, and is NOT updated when a demand promotes the entry
// (ruling R8): the promotion is exactly the case whose head start we want to
// keep. Distinct from the entry's own allocation time only because a future
// change might make them differ; today they are the same instant and the field
// exists so R8's definition is readable in the code.
SimTime first_request{0};

// engine.h, inside CoreState
// min over the lines of the current burst of that line's `first_request`.
// Reset to `issued_at` at the start of every burst and lowered as each line
// resolves, so `served - burst_anchor` is R8's per-burst term.
SimTime burst_anchor{0};
```

`core_line_done` lowers `burst_anchor` to `min(burst_anchor, entry.first_request)` for
each landing line, and the burst's completion adds `served - burst_anchor` to
`fetch_latency[c]`, in place of today's `served - issued_at`.

- [ ] **Step 1: Write the failing tests, which are the three worked cases**

Add to `tests/test_engine.cpp`. These are the three the brief names, plus the `d = 0`
invariant:

```cpp
void test_r8_timely_prefetch_contributes_its_whole_line_latency_to_hidden() {
    check::group("Task 12, R8 case 1 (timely): stall 0, fetch 10, hidden 10");
    // One core, two bursts, gap 1. l2_latency 10, everything else free, the L1
    // empty. A prefetch at distance 1 issues burst 1's line at burst 0's issue
    // time, so it has landed by the time the core wants it: the core does not
    // stall at all, and the whole 10 cycles were hidden.
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(20);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 11, 1);       // far enough ahead that the prefetch lands
    fx::LinearMapper mapper;
    EngineParams p = fx::unbounded_params();
    p.l2.latency        = SimTime{10};
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 1;
    Engine e(mapper, tr, p);
    e.run();
    const EngineStats& s = e.stats();
    // Burst 0 is a cold demand miss: 10 cycles of fetch, 10 of stall, 0 hidden.
    // Burst 1 is timely: 0 of stall, 10 of fetch, 10 hidden.
    CHECK_EQ(s.core_stall[0], std::int64_t{10});
    CHECK_EQ(s.fetch_latency[0], std::int64_t{20});
    CHECK_EQ(s.fetch_latency[0] - s.core_stall[0], std::int64_t{10});
    CHECK_EQ(s.pf_timely, std::int64_t{1});
}

void test_r8_late_merge_contributes_exactly_its_head_start() {
    check::group("Task 12, R8 case 2 (late merge): head start 3 -> hidden 3");
    // The prefetch for burst 1 issues 3 cycles before the demand would have, and
    // the demand merges onto it while it is still outstanding. The core stalls
    // for 10 - 3 = 7; the fetch, anchored on the PREFETCH's issue, is 10; so
    // exactly the 3-cycle head start is hidden.
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(30);
    tr.add_burst(t0, 0, 0, 0);
    tr.add_burst(t0, 0, 3, 1);        // 3 ticks later: the head start
    fx::LinearMapper mapper;
    EngineParams p = fx::unbounded_params();
    p.l2.latency        = SimTime{10};
    p.prefetch_policy   = PrefetchKind::NextBurst;
    p.prefetch_distance = 1;
    Engine e(mapper, tr, p);
    e.run();
    const EngineStats& s = e.stats();
    CHECK_EQ(s.fetch_latency[0] - s.core_stall[0], std::int64_t{3});
    CHECK_EQ(s.pf_late, std::int64_t{1});
    CHECK_EQ(s.pf_timely, std::int64_t{0});
}

void test_r8_hidden_latency_is_identically_zero_at_distance_zero() {
    check::group("Task 12, R8 case 3: at d = 0, hidden_latency is IDENTICALLY 0");
    // The invariant the brief names. Run a nontrivial workload with prefetching
    // off and assert the two integrals are equal, per core AND in total.
    fx::FakeTrace tr(4);
    for (std::int32_t t = 0; t < 4; ++t) {
        const std::int32_t tile = tr.add_tile(9);
        for (std::int32_t c = 0; c < 4; ++c)
            for (std::int32_t k = 0; k < 5; ++k)
                tr.add_burst(tile, c, k, (t * 20) + (c * 5) + k);
    }
    fx::LinearMapper mapper;
    EngineParams p = fx::unbounded_params(8, 2);
    p.l1.mshrs = 4;  p.l1.demand_reserve = 1;
    p.l2.latency = SimTime{10};  p.l2_miss_latency = SimTime{100};
    p.prefetch_policy   = PrefetchKind::None;
    p.prefetch_distance = 0;
    Engine e(mapper, tr, p);
    e.run();
    const EngineStats& s = e.stats();
    std::int64_t stall = 0, fetch = 0;
    for (std::size_t c = 0; c < s.core_stall.size(); ++c) {
        CHECK_EQ(s.fetch_latency[c], s.core_stall[c]);   // per core
        stall += s.core_stall[c];
        fetch += s.fetch_latency[c];
    }
    CHECK_EQ(fetch - stall, std::int64_t{0});            // hidden_latency
}

void test_r8_hidden_latency_is_never_negative() {
    check::group("Task 12: hidden_latency >= 0 under contention at every distance");
    for (std::int32_t d : {0, 1, 2, 4, 8}) {
        fx::FakeTrace tr(4);
        for (std::int32_t t = 0; t < 3; ++t) {
            const std::int32_t tile = tr.add_tile(9);
            for (std::int32_t c = 0; c < 4; ++c)
                for (std::int32_t k = 0; k < 6; ++k)
                    tr.add_burst(tile, c, k, (t * 24) + (c * 6) + k);
        }
        fx::LinearMapper mapper;
        EngineParams p = fx::unbounded_params(4, 2);
        p.l1.mshrs = 4;  p.l1.demand_reserve = 1;
        p.l2.latency = SimTime{10};  p.l2_miss_latency = SimTime{100};
        p.prefetch_policy   = (d == 0) ? PrefetchKind::None : PrefetchKind::NextBurst;
        p.prefetch_distance = d;
        Engine e(mapper, tr, p);
        e.run();
        const EngineStats& s = e.stats();
        for (std::size_t c = 0; c < s.core_stall.size(); ++c)
            CHECK_TRUE(s.fetch_latency[c] >= s.core_stall[c]);
    }
}
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_engine && ./build/fixture/test_engine
```
Expected: FAIL. The timely and late cases fail on the `fetch_latency` value, because
today's definition anchors on the **demand** issue and therefore reports 10 and 7 rather
than 20 and 10. The `d = 0` case passes even before the change, which is the point: R8
must not disturb the control arm.

- [ ] **Step 3: Implement the line anchor**

Add `Mshr::first_request`, set once in `MshrFile::allocate` from the allocating request's
issue time and explicitly **not** touched by the demand promotion path (add a comment
saying R8 requires this, because a future reader will otherwise "fix" it). Add
`CoreState::burst_anchor`, initialise it to `issued_at` at burst issue, lower it in
`core_line_done`, and change the `fetch_latency` accumulation to use it.

Update `EngineStats::fetch_latency`'s comment: it currently says
`Σ served(c,k) - issued_at(c,k)`, which R8 supersedes. Give the new definition in full and
cite ruling R8 and Q5.

- [ ] **Step 4: Run them to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_engine
```
Expected: PASS, `0 failures`, all four cases green.

- [ ] **Step 5: Confirm U19's measurement is now explained**

`PROGRESS.md:869` (U19) recorded `core_stall - fetch_latency == 0` throughout, which G7
calls "the prefetch study currently has no metric". Under R8 that identity holds at
`d = 0` **only**. Re-run the U19 shape at `d in {1, 2, 4, 8}` and confirm
`fetch_latency > core_stall` at every one of them.

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_engine 2>&1 | grep -A2 "hidden_latency"
```
Expected: the "never negative" case green, and a nonzero hidden latency at `d > 0`.

- [ ] **Step 6: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green. **Do not commit.**

---

## Task 13: D2c, `RunStats` and the CSV schema

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/stats.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/stats.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_stats.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/mutation_check.sh:65`

**Interfaces:**
- Consumes: `RunConfig` (Task 10), `EngineStats` (Tasks 11 and 12), `Engine::tile_origin`,
  `StreamingTileTrace::tick_base` and `::header`, `AddressMapper` for the padding term.
- Produces:

```cpp
namespace wcache {

// Identity a row carries that neither the engine nor the trace knows.
struct RowIdentity {
    std::string run_id, git_commit, arm = "cache", tier;
};

// The exactly 91 columns of "The CSV schema, in full", in order. A test pins this
// list, so a reordering is a test failure rather than a silent join break.
const std::vector<std::string>& csv_columns();
std::string csv_header();

// Collects one row. `n_tiles` and `tick_base_total` come from the trace, which the
// engine deliberately never sees (Part 5: "the engine never uses tick_base").
struct RunStats {
    RunStats(const RowIdentity& id, const RunConfig& cfg,
             const stream::StreamHeader& hdr, const EngineStats& es,
             std::int64_t total_cycles, std::int64_t tick_base_total,
             double padding_fraction, double sim_wall_seconds,
             std::int32_t distinct_p50, std::int32_t distinct_max);

    // One CSV line, no trailing newline, fields in csv_columns() order. Integers
    // are printed exactly; doubles with "%.6f"; an undefined ratio as the empty
    // string, never as NaN, because NaN is not portable across CSV readers.
    std::string csv_row() const;

    // V21 and the prefetch sum, checked HERE rather than only in a test, so a
    // sweep row that violates them fails loudly instead of being written.
    // Throws std::logic_error naming the two sides.
    void check_invariants() const;
};

// The spad_oracle arm: a row with total_cycles == tick_base_total and every
// simulated column empty. §2 says it costs nothing, and this is why.
std::string oracle_row(const RowIdentity& id, const RunConfig& cfg,
                       const stream::StreamHeader& hdr, std::int64_t tick_base_total);

}  // namespace wcache
```

`total_cycles` is `engine.tile_origin(trace.n_tiles())`: `tile_origin` is sized
`n_tiles + 1` and its last entry is the end of the run, so the layer makespan is one
array read. That is gap G3 closed.

`padding_fraction` is `(lines_touched * elements_per_line - distinct_elements_touched) /
(lines_touched * elements_per_line)`, computed by the mapper over the run's expanded
lines. §3.3 says it must be 0 for all four chosen layers, so a nonzero value on them
means the address mapper is wrong.

`port_bound_threshold` is `miss_fraction * l2_miss_latency * l2_banks / l2_ii`
(v3 `:1464`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_stats.cpp`:

```cpp
#include <wcache/config.h>
#include <wcache/engine.h>
#include <wcache/stats.h>
#include <wcache/stream_format.h>

#include <sstream>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;

namespace {

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> out;
    std::string cell;
    std::istringstream in(line);
    while (std::getline(in, cell, ',')) out.push_back(cell);
    return out;
}

void test_the_column_list_is_pinned() {
    check::group("Task 13: the CSV schema is exactly 91 columns, in order");
    const std::vector<std::string>& cols = csv_columns();
    CHECK_EQ(check::ssize(cols), std::int64_t{91});
    CHECK_TRUE(cols.front() == "run_id");
    CHECK_TRUE(cols.back() == "distinct_addr_per_core_tile_max");
    // The four §9.2 / G3 columns the campaign turns on.
    bool has_total = false, has_pad = false, has_hidden = false, has_sets = false;
    for (const std::string& c : cols) {
        if (c == "total_cycles")      has_total  = true;
        if (c == "padding_fraction")  has_pad    = true;
        if (c == "hidden_latency")    has_hidden = true;
        if (c == "l1_num_sets")       has_sets   = true;
    }
    CHECK_TRUE(has_total);  CHECK_TRUE(has_pad);
    CHECK_TRUE(has_hidden); CHECK_TRUE(has_sets);
}

void test_l2_demand_reserve_is_not_a_column() {
    check::group("Task 13: l2_demand_reserve is NOT a column (G11)");
    for (const std::string& c : csv_columns())
        CHECK_TRUE(c != "l2_demand_reserve");
}

void test_the_header_and_a_row_have_the_same_field_count() {
    check::group("Task 13: header and row agree on arity");
    // Build a real run so the row is not hand-made.
    fx::FakeTrace tr(2);
    const std::int32_t t0 = tr.add_tile(4);
    tr.add_burst(t0, 0, 0, 0);  tr.add_burst(t0, 1, 0, 1);
    fx::LinearMapper mapper;
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();

    RunConfig cfg = parse_config("{}");
    std::vector<Warning> w;
    validate(cfg, 1, w);
    stream::StreamHeader hdr;
    hdr.n_tiles = tr.n_tiles();  hdr.n_cores = tr.n_cores();
    hdr.arch = "loas";  hdr.workload = "vgg16_T4_all";
    hdr.layer = "layer_01_features_3";  hdr.sample_idx = 0;

    const RowIdentity id{"run-0", "deadbeef", "cache", "tier0"};
    const RunStats st(id, cfg, hdr, e.stats(),
                      /*total_cycles=*/e.tile_origin(tr.n_tiles()).get(),
                      /*tick_base_total=*/4, /*padding_fraction=*/0.0,
                      /*sim_wall_seconds=*/0.001, /*distinct_p50=*/1,
                      /*distinct_max=*/1);
    const std::vector<std::string> head = split_csv(csv_header());
    const std::vector<std::string> row  = split_csv(st.csv_row());
    CHECK_EQ(check::ssize(row), check::ssize(head));
    st.check_invariants();   // must not throw
}

void test_check_invariants_catches_a_broken_stall_sum() {
    check::group("Task 13: a stall breakdown that does not sum throws (V21)");
    fx::FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile(2);
    tr.add_burst(t0, 0, 0, 0);
    fx::LinearMapper mapper;
    Engine e(mapper, tr, fx::unbounded_params());
    e.run();
    EngineStats broken = e.stats();
    broken.stall_total[0] += 1;             // deliberately break the sum
    RunConfig cfg = parse_config("{}");
    std::vector<Warning> w;
    validate(cfg, 1, w);
    stream::StreamHeader hdr;
    hdr.n_tiles = 1;  hdr.n_cores = 1;
    const RowIdentity id{"run-0", "", "cache", ""};
    const RunStats st(id, cfg, hdr, broken, 2, 2, 0.0, 0.0, 0, 0);
    CHECK_THROWS(std::logic_error, st.check_invariants());
}

void test_the_oracle_row_needs_no_engine() {
    check::group("Task 13: the spad_oracle arm is a row with no simulation (§2)");
    RunConfig cfg = parse_config("{}");
    std::vector<Warning> w;
    validate(cfg, 1, w);
    stream::StreamHeader hdr;
    hdr.n_tiles = 32;  hdr.n_cores = 8;  hdr.arch = "loas";
    const RowIdentity id{"run-0", "", "spad_oracle", "tier1"};
    const std::vector<std::string> row = split_csv(oracle_row(id, cfg, hdr, 4096));
    const std::vector<std::string> head = split_csv(csv_header());
    CHECK_EQ(check::ssize(row), check::ssize(head));
    for (std::size_t i = 0; i < head.size(); ++i) {
        if (head[i] == "total_cycles")    CHECK_TRUE(row[i] == "4096");
        if (head[i] == "tick_base_total") CHECK_TRUE(row[i] == "4096");
        if (head[i] == "stretch_cycles")  CHECK_TRUE(row[i] == "0");
        if (head[i] == "l1_hits")         CHECK_TRUE(row[i].empty());
        if (head[i] == "arm")             CHECK_TRUE(row[i] == "spad_oracle");
    }
}

void test_a_cell_never_contains_a_comma_or_a_nan() {
    check::group("Task 13: no cell can break the CSV or emit a NaN");
    RunConfig cfg = parse_config("{}");
    std::vector<Warning> w;
    validate(cfg, 1, w);
    stream::StreamHeader hdr;
    hdr.n_tiles = 1;  hdr.n_cores = 1;
    hdr.layer = "layer,with,commas";        // a hostile identity
    const RowIdentity id{"run-0", "", "cache", ""};
    // fetch_latency_sum 0 must give an EMPTY hidden_fraction, never nan or inf.
    const std::string row = oracle_row(id, cfg, hdr, 0);
    CHECK_TRUE(row.find("nan") == std::string::npos);
    CHECK_TRUE(row.find("inf") == std::string::npos);
    CHECK_EQ(check::ssize(split_csv(row)), check::ssize(split_csv(csv_header())));
}

}  // namespace

int main() {
    test_the_column_list_is_pinned();
    test_l2_demand_reserve_is_not_a_column();
    test_the_header_and_a_row_have_the_same_field_count();
    test_check_invariants_catches_a_broken_stall_sum();
    test_the_oracle_row_needs_no_engine();
    test_a_cell_never_contains_a_comma_or_a_nan();
    return check::summary();
}
```

The hostile-identity case forces a decision: a value containing a comma must be quoted
per RFC 4180, or rejected. **Reject it**, throwing `std::invalid_argument`, because every
identity in this campaign is a filesystem-safe name and a CSV writer that quotes is a
CSV writer that also has to escape quotes. Say so in a comment.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_stats
```
Expected: FAIL, `fatal error: wcache/stats.h: No such file or directory`.

- [ ] **Step 3: Implement `stats.h` and `stats.cpp`**

`csv_columns()` is a function-local `static const std::vector<std::string>` initialised
from a single brace list copied verbatim from "The CSV schema, in full". `csv_row()`
builds into a `std::string` with a small `append_int` / `append_double` / `append_str`
trio, and `append_str` throws on a comma, a quote or a newline.

- [ ] **Step 4: Run it to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_stats
```
Expected: PASS, `0 failures`.

- [ ] **Step 5: Add to the mutation list, then Checkpoint**

Add `include/wcache/stats.h` and `src/stats.cpp` to `FILES=`, then

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test 2>&1 | tail -20
```
Expected: all green. **Do not commit.**

---

## Task 14: D2d, the G14 distinct-address diagnostic

Ruling R6 demoted this from an axis-siting gate to an explanatory diagnostic: it explains,
per architecture, why each L1 curve has the shape it has, and in particular the
LoAS/Spinalflow versus PTB cross-tile reuse difference. **It gates nothing and its outcome
does not change the axis.** It is free because the reader already touches every burst.

**Files:**
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/stream_trace.cpp`
  (fill `distinct_addresses` during `advance()`)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_stream_trace.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/hist.h`
  (the sidecar writer)
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_hist.cpp`

**Interfaces:**
- Produces:

```cpp
// hist.h
namespace wcache {

// The per-(core, tile) distinct-address histogram, G14's diagnostic. It is a
// property of the TRACE and of the LAYOUT, not of a cache configuration, so it is
// collected once per stream and written to its own file rather than smeared over
// every row of a sweep.
class DistinctAddressHistogram {
public:
    DistinctAddressHistogram(std::int32_t n_cores, const stream::StreamHeader& hdr);
    // Call once per tile, after StreamingTileTrace::advance() returns true.
    void observe(const StreamingTileTrace& trace, const AddressMapper& mapper);
    // "arch,workload,layer,sample_idx,tile,core,distinct_addresses" plus a header.
    void write_csv(std::ostream& out) const;
    std::int32_t p50() const;
    std::int32_t max() const;
};

}  // namespace wcache
```

`StreamingTileTrace::distinct_addresses(core)` is the per-tile count for the window tile,
computed in `advance()` by expanding each burst through the mapper and inserting into a
small `std::vector<LineId>` that is sorted and uniqued once per core per tile. At 24
addresses per core per tile (the measured figure, §1.3 G14) that is free.

**One subtlety the plan must state.** `advance()` needs an `AddressMapper` to expand a
burst into lines, and the mapper is a function of the **configuration** (`cin_block`,
`cout_block`), while the trace is not. Resolving it: `StreamingTileTrace` counts
**distinct address tuples**, not distinct lines, so it needs no mapper at all. The
line-level count, which does depend on the layout, is what
`DistinctAddressHistogram::observe` computes, and it takes the mapper explicitly. The two
are different quantities and the CSV's summary columns report the **address-tuple** one,
which is what §1.3's table measured (24 addresses, 384 B) and therefore what is
comparable to it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_stream_trace.cpp`:

```cpp
void test_distinct_addresses_counts_tuples_not_bursts() {
    check::group("Task 14: G14's per-(core, tile) distinct-address count");
    StreamBuilder b(1, 3);
    b.begin_tile(0, 20);
    b.begin_core(0);
    b.add_burst(0, 1, 1, 6, 0, 16);
    b.add_burst(1, 1, 1, 6, 0, 16);      // the SAME address again: not distinct
    b.add_burst(2, 1, 1, 7, 0, 16);      // a different one
    b.begin_core(2);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.distinct_addresses(CoreId{0}), 2);
    CHECK_EQ(tr.distinct_addresses(CoreId{1}), 0);
    CHECK_EQ(tr.distinct_addresses(CoreId{2}), 1);
}
```

Create `tests/test_hist.cpp` with a case that streams three tiles, observes each, and
checks that `write_csv` produces `n_tiles * n_cores` data rows plus a header, that `p50`
and `max` match a hand-computed answer, and that a core absent from a tile appears with
`0` rather than being omitted, because an omitted zero would bias the p50 upwards.

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_stream_trace build/fixture/test_hist
```
Expected: FAIL on both, the first on the `distinct_addresses` value and the second on the
missing header.

- [ ] **Step 3: Implement both**

- [ ] **Step 4: Run them to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_stream_trace && ./build/fixture/test_hist
```
Expected: PASS on both, `0 failures`.

- [ ] **Step 5: Add to the mutation list, then Checkpoint**

Add `include/wcache/hist.h` to `FILES=`, then `make clean && make test`. **Do not commit.**

---

## Task 15: `wcache_run`

The first half of what gap G2 names: `src/wcache/native/src/` has no `main.cpp`, no config
loader and no CSV writer, and this task delivers the program that ties the other three
together.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/apps/wcache_run.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/Makefile`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/run_cli.sh`

**Interfaces:**
- Consumes: `parse_config`, `validate`, `to_engine_params`, `StreamingTileTrace`,
  `BlockPackMapper`, `Engine`, `RunStats`, `DistinctAddressHistogram`.
- Produces: the `wcache_run` CLI exactly as given in "The CLI, in full".

The program's shape, in order, because the order is what makes the errors land in the
right place:

```
1. parse argv; --help exits 0; a bad flag exits 2 with usage on stderr
2. read the config file into a string, parse_config
3. open the trace: "-" -> FdByteSource(STDIN_FILENO), "fd:N" -> FdByteSource(N),
   otherwise open(2) the path
4. construct StreamingTileTrace, which reads and validates the header
5. lines_per_burst = mapper.expand(a synthetic burst of the header's own span).size()
   -- but the span is a property of the DATA, not the header, so instead:
   lines_per_burst = ceil(cout_block_span / cout_block), which for this corpus is
   burst_span / cout_block. See OPEN QUESTION 4.
6. validate(cfg, lines_per_burst, warnings); print each warning to stderr as
   "wcache_run: warning [CODE] message"
7. --oracle-only: decode every tile with advance(), accumulate tick_base, emit
   oracle_row, exit 0. No engine is ever constructed.
8. otherwise: construct BlockPackMapper and Engine, then the lockstep loop of ONE
   engine, which is the degenerate case of Task 17's driver:
       while (trace.advance()) { ... }  is WRONG here: the engine must consume
       tile N before the window moves. The correct loop is
       for (;;) {
           if (!trace.advance()) break;         // window now holds tile t
           const std::int32_t pending = engine.run_to_barrier();
           if (pending < 0) break;
           // the barrier for tile `pending` is still queued; the next advance()
           // moves the window, and the FOLLOWING run_to_barrier dispatches it.
       }
       engine.finish();   // pops the last barrier and runs the D12 checks
9. collect RunStats, check_invariants(), write the header line if wanted, write the row
10. --hist: write the sidecar
```

Step 8 exposes one more `Engine` need: a `finish()` that dispatches the final pending
barrier and drains. Add it beside `run_to_barrier`:

```cpp
// engine.h, public
// Dispatches the pending barrier, if any, then drains the queue and runs the D12
// checks. Calling it when nothing is pending is legal and is a no-op plus the
// checks. After it returns, tile_origin(n_tiles) is the layer makespan.
void finish();
```

**Makefile.** Add, after the existing `TEST_BINS` block:

```make
APP_SRCS := $(wildcard apps/*.cpp)
APP_BINS := $(patsubst apps/%.cpp,$(BUILDDIR)/%,$(APP_SRCS))

apps: $(APP_BINS)

$(BUILDDIR)/%: apps/%.cpp $(LIB_HDRS) $(LIB) | $(BUILDDIR)
	$(CXX) $(CXXFLAGS) $< $(LIB) -o $@
```

and add `apps` to `.PHONY` and to `all`. The pattern rule `$(BUILDDIR)/%` is broader than
`$(BUILDDIR)/test_%`, so make will prefer the more specific test rule for test binaries;
confirm that with `make -n` in Step 5 rather than trusting it.

- [ ] **Step 1: Write the failing test**

Create `tests/run_cli.sh`:

```sh
#!/bin/sh
# Task 15: wcache_run end to end over a stream produced by the Python writer.
set -e
root=/home/ya867177/neuro_cache-wcache
native=$root/src/wcache/native
bin=$native/build/fixture/wcache_run
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# A stream built from one of the checked-in fixture slices, so this test needs no
# corpus and no Delta.
conda run -n cosa_snn python - "$tmp/fixture.wcts" <<'PY'
import json, sys
sys.path.insert(0, "/home/ya867177/neuro_cache-wcache/src")
from tracegen import (CoreEntry, LayerWeightTrace, TickEntry, TileWeightTrace,
                      stream_weight_trace)
doc = json.load(open("/home/ya867177/neuro_cache-wcache/src/wcache/examples/"
                     "loas_vgg16_layer01_v2.json"))
tiles = [TileWeightTrace(dram_i=t["dram_i"], noc_i=t["noc_i"],
                         mac_cycles=t["mac_cycles"], lif_cycles=t.get("lif_cycles"),
                         ticks=[TickEntry(tick=k["tick"],
                                          cores=[CoreEntry(core_id=c["core_id"],
                                                           weight_addresses=c["weight_addresses"])
                                                 for c in k["cores"]])
                                for k in t["ticks"]])
         for t in doc["tiles"]]
lt = LayerWeightTrace(arch=doc["arch"], trace_dir=doc["trace_dir"],
                      layer_name=doc["layer_name"], sample_idx=doc["sample_idx"],
                      workload_dims=doc["workload_dims"],
                      dram_num_steps=doc["dram_num_steps"],
                      noc_num_steps=doc["noc_num_steps"], tiles=tiles)
with open(sys.argv[1], "wb") as fh:
    n = stream_weight_trace(lt, fh, n_cores=8, spatial_factors={3: 8})
print(f"wrote {n} bursts", file=sys.stderr)
PY

cat > "$tmp/cfg.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 8192, "l1_assoc": 8,
 "l2_size_bytes": 524288, "l2_assoc": 16,
 "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100}
JSON

# 1. A path trace, header plus one row.
"$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" --header > "$tmp/a.csv"
test "$(wc -l < "$tmp/a.csv")" -eq 2

# 2. The same trace on stdin gives a byte-identical row.
"$bin" --config "$tmp/cfg.json" --trace - --header < "$tmp/fixture.wcts" > "$tmp/b.csv"
cmp "$tmp/a.csv" "$tmp/b.csv"

# 3. The row's arity matches the header's.
conda run -n cosa_snn python - "$tmp/a.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
assert len(rows) == 2, rows
assert len(rows[0]) == len(rows[1]) == 90, (len(rows[0]), len(rows[1]))
row = dict(zip(rows[0], rows[1]))
assert int(row["total_cycles"]) > 0
assert int(row["l1_accesses"]) > 0
assert float(row["padding_fraction"]) == 0.0, row["padding_fraction"]
print("wcache_run: OK")
PY

# 4. The oracle arm needs no engine and reproduces tick_base.
"$bin" --config "$tmp/cfg.json" --trace "$tmp/fixture.wcts" \
       --oracle-only --arm spad_oracle --header > "$tmp/o.csv"
conda run -n cosa_snn python - "$tmp/o.csv" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
row = dict(zip(rows[0], rows[1]))
assert row["arm"] == "spad_oracle"
assert row["total_cycles"] == row["tick_base_total"] == "48"   # 24 + 24
assert row["l1_hits"] == ""
print("oracle arm: OK")
PY

# 5. A rejected config exits 1 and names the knob.
cat > "$tmp/bad.json" <<'JSON'
{"l2_demand_reserve": 4}
JSON
if "$bin" --config "$tmp/bad.json" --trace "$tmp/fixture.wcts" 2> "$tmp/err.txt"; then
    echo "expected a nonzero exit for l2_demand_reserve"; exit 1
fi
grep -q l2_demand_reserve "$tmp/err.txt"
echo "run_cli: OK"
```

`chmod +x` it.

- [ ] **Step 2: Run it to verify it fails**

```bash
/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/run_cli.sh
```
Expected: FAIL, `wcache_run: No such file or directory`.

- [ ] **Step 3: Write `apps/wcache_run.cpp`, `Engine::finish`, and the Makefile rules**

- [ ] **Step 4: Build and run the script**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make apps && tests/run_cli.sh
```
Expected: `wcache_run: OK`, `oracle arm: OK`, `run_cli: OK`.

- [ ] **Step 5: Confirm the new pattern rule did not capture the test binaries**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make -n build/fixture/test_engine | head -3
```
Expected: the recipe still carries `-Itests`, which only the test rule adds. If it does
not, make chose the app rule and every test now compiles without its own headers.

- [ ] **Step 6: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make clean && make test && make apps
```
Expected: all green. **Do not commit.**

---

## Task 16: V1 end to end over the real pipe

The calibration of the whole comparison (v3 V1, §2, G8): unbounded cache,
`l1_latency = 0`, and `tile_origin[N] == tick_base[N]` for every tile, exactly. This task
runs it through the **full pipe**, producer to consumer, on a checked-in fixture slice, so
it exercises the producer, the wire format, the reader, the engine and the CSV in one go.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/v1_pipe.sh`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/apps/wcache_run.cpp`
  (add `--check-v1`)

**Interfaces:**
- Produces: `wcache_run --check-v1`, which after the run compares
  `engine.tile_origin(t)` against `trace.tick_base(t)` for every `t` in `[0, n_tiles]` and
  exits 1 naming the first tile that differs, printing both numbers. It is a flag rather
  than an always-on check because V1 holds only under the unbounded configuration.

- [ ] **Step 1: Write the failing test**

Create `tests/v1_pipe.sh`:

```sh
#!/bin/sh
# Task 16: invariant V1 end to end, producer -> pipe -> wcache_run.
#
# Unbounded cache, l1_latency = 0 -> tile_origin[N] == tick_base[N] EXACTLY,
# for every tile. v3 :1380, and §2's "known-answer check 1".
set -e
root=/home/ya867177/neuro_cache-wcache
bin=$root/src/wcache/native/build/fixture/wcache_run
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# The unbounded baseline: ii = 0 never delays, every latency 0, and a cache large
# enough that nothing is ever evicted.
cat > "$tmp/unbounded.json" <<'JSON'
{"cin_block": 1, "cout_block": 16, "weight_bytes": 1,
 "l1_size_bytes": 16777216, "l1_assoc": 8,
 "l2_size_bytes": 16777216, "l2_assoc": 16,
 "l1_latency": 0, "l1_ii": 0,
 "l2_latency": 0, "l2_to_l1_latency": 0, "l2_miss_latency": 0,
 "l2_ii": 0, "dram_ii": 0, "l2_banks": 1,
 "l1_mshrs": 64, "l1_tgts_per_mshr": 64,
 "l2_mshrs": 64, "l2_tgts_per_mshr": 64,
 "core_accept_ii": 1, "prefetch_policy": "none", "prefetch_distance": 0}
JSON

for fixture in loas_vgg16_layer01_v2 ptb_resnet19_layer01_v2 \
               spinalflow_vgg16_layer01_v2 prosperity_vgg16_layer01_v2; do
    conda run -n cosa_snn python "$root/src/wcache/examples/to_stream.py" \
        "$root/src/wcache/examples/$fixture.json" > "$tmp/$fixture.wcts"
    "$bin" --config "$tmp/unbounded.json" --trace - --check-v1 --header \
        < "$tmp/$fixture.wcts" > "$tmp/$fixture.csv"
    conda run -n cosa_snn python - "$tmp/$fixture.csv" "$fixture" <<'PY'
import csv, sys
rows = list(csv.reader(open(sys.argv[1])))
row = dict(zip(rows[0], rows[1]))
assert row["total_cycles"] == row["tick_base_total"], (sys.argv[2], row["total_cycles"],
                                                       row["tick_base_total"])
assert row["stretch_cycles"] == "0", (sys.argv[2], row["stretch_cycles"])
print(f"V1 exact on {sys.argv[2]}: total_cycles == tick_base_total == "
      f"{row['total_cycles']}")
PY
done
echo "v1_pipe: OK"
```

`chmod +x` it. It needs one helper: create
`/home/ya867177/neuro_cache-wcache/src/wcache/examples/to_stream.py`, the fixture-JSON to
WCTS converter that Task 15's inline heredoc used, factored out so both scripts share it.
It takes the fixture path and the core count from the fixture's own `cores` list, and
`spatial_factors = {3: n_cores}`, which is exact for these fixtures because the example
manifest records 8 cores for all four.

- [ ] **Step 2: Run it to verify it fails**

```bash
/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/v1_pipe.sh
```
Expected: FAIL, `unrecognized option --check-v1`.

- [ ] **Step 3: Implement `--check-v1` and `examples/to_stream.py`**

- [ ] **Step 4: Run it to verify it passes**

```bash
/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/v1_pipe.sh
```
Expected, four lines then `v1_pipe: OK`:
```
V1 exact on loas_vgg16_layer01_v2: total_cycles == tick_base_total == 48
V1 exact on ptb_resnet19_layer01_v2: total_cycles == tick_base_total == 42
V1 exact on spinalflow_vgg16_layer01_v2: total_cycles == tick_base_total == ...
V1 exact on prosperity_vgg16_layer01_v2: total_cycles == tick_base_total == ...
```
The loas number is `24 + 24` and the ptb number is `21 + 21`, both from
`examples/manifest.json`'s `mac_cycles` after the slice rewrite. If a fixture's
`total_cycles` differs from the sum of its two `mac_cycles`, the reader's `tile_tail`
derivation is wrong, not the engine.

- [ ] **Step 5: Also check V27, the exact-drift companion**

Re-run the loas fixture with `"l1_latency": 1` and confirm the drift equals the
trace-computed sum over tiles before `N` of that tile's maximum per-core burst count.
For the two-tile loas slice every core issues 24 bursts in each tile, so tile 0's maximum
is 24 and the expected `stretch_cycles` is 24.

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && \
  sed 's/"l1_latency": 0/"l1_latency": 1/' /tmp/unbounded.json > /tmp/v27.json && \
  ./build/fixture/wcache_run --config /tmp/v27.json --trace - --header \
    < /tmp/loas_vgg16_layer01_v2.wcts | tail -1 | cut -d, -f41
```
Expected: `24`. (Field 41 is `stretch_cycles`; confirm the index against `csv_header()`
rather than trusting this number.)

- [ ] **Step 6: Checkpoint**

`make clean && make test && make apps && tests/v1_pipe.sh`. **Do not commit.**

---

## Task 17: D3a, `BroadcastSweep`, lockstep over one stream

§10.5's recommended answer to the single-pass problem: one reader holds the current tile
window, every engine in the grid consumes that same tile, and the window advances when
all engines have finished it. Each engine keeps its own simulated clock, and they diverge,
which is fine because the window is indexed by tile number and not by cycle.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/include/wcache/sweep.h`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/sweep.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_sweep.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/mutation_check.sh:65`

**Interfaces:**
- Consumes: `StreamingTileTrace`, `Engine::run_to_barrier`, `Engine::finish`,
  `to_engine_params`, `BlockPackMapper`.
- Produces:

```cpp
namespace wcache {

// Runs N configurations over ONE pass of a stream. Single-threaded and
// cooperative: no threads, no coroutines. `Engine::run_to_barrier` is what makes
// that possible, because it returns with the barrier still queued, so every
// engine can be parked at the same tile seam while the window moves.
class BroadcastSweep {
public:
    // Every configuration must share the same LAYOUT (cin_block, cout_block,
    // weight_bytes), because one mapper serves the whole hierarchy and a layout
    // change would change what a "line" is mid-stream. Throws
    // std::invalid_argument naming the first configuration that differs. A line
    // size sweep is therefore several sweeps, one per line size, which is what
    // §4.2's "the axis varies only the cin packing" already implies.
    BroadcastSweep(StreamingTileTrace& trace, std::vector<RunConfig> configs,
                   std::int32_t max_engines);

    // One pass. Advances the window tile by tile, letting every engine reach that
    // tile's barrier before the window moves. Throws whatever an engine throws,
    // with the offending configuration index prepended.
    void run();

    std::size_t size() const;
    const Engine& engine(std::size_t i) const;
    const RunConfig& config(std::size_t i) const;
    // Wall seconds spent inside engine dispatch for configuration i, for the
    // sim_wall_seconds column.
    double wall_seconds(std::size_t i) const;
};

}  // namespace wcache
```

`run()`'s loop, which is the whole of the design and must be written exactly:

```cpp
void BroadcastSweep::run() {
    for (;;) {
        if (!trace_.advance()) break;            // window now holds the next tile
        for (std::size_t i = 0; i < engines_.size(); ++i) {
            // Dispatches the barrier of the PREVIOUS tile (a no-op on the first
            // pass), then runs this tile to its own barrier and parks there.
            engines_[i]->step_tile();
        }
    }
    for (auto& e : engines_) e->finish();
}
```

which needs one more `Engine` method, and it is the last:

```cpp
// engine.h, public
// Dispatches the pending barrier if there is one, then runs to the next barrier
// and parks. Exactly one tile of progress per call. Returns false when the run
// is complete.
bool step_tile();
```

`step_tile()` is `if (a barrier is pending) { pop and dispatch it; } return
run_to_barrier() >= 0;`.

**Memory.** §10.5's arithmetic: 180 engines at the measured 11 MB peak
(`FINDINGS.md:340`) is about 2.0 GB, plus one tile window of about 2.5 MB. `max_engines`
defaults to 256 and exists so an oversized grid fails at startup rather than by OOM.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sweep.cpp`:

```cpp
#include <wcache/config.h>
#include <wcache/stream_trace.h>
#include <wcache/sweep.h>

#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"

using namespace wcache;

namespace {

void test_broadcast_lockstep_equals_running_each_config_alone() {
    check::group("Task 17: N engines over one stream == N separate runs");
    // The whole correctness claim of the design, checked directly: build a stream,
    // run three configurations through BroadcastSweep, then run each one alone
    // over its own copy of the stream, and require identical tile_origin vectors.
    const std::vector<unsigned char> bytes = build_three_tile_stream();  // in-file helper
    const std::vector<std::string> cfgs = {
        R"({"cout_block": 16, "l1_size_bytes": 2048, "l1_assoc": 8,
            "l2_size_bytes": 65536, "l2_assoc": 16, "l2_latency": 10})",
        R"({"cout_block": 16, "l1_size_bytes": 8192, "l1_assoc": 8,
            "l2_size_bytes": 65536, "l2_assoc": 16, "l2_latency": 10})",
        R"({"cout_block": 16, "l1_size_bytes": 8192, "l1_assoc": 8,
            "l2_size_bytes": 65536, "l2_assoc": 16, "l2_latency": 10,
            "prefetch_policy": "next_burst", "prefetch_distance": 2})"};

    std::vector<RunConfig> parsed;
    for (const std::string& s : cfgs) {
        RunConfig c = parse_config(s);
        std::vector<Warning> w;
        validate(c, 1, w);
        parsed.push_back(c);
    }

    MemByteSource shared(bytes);
    StreamingTileTrace trace(shared);
    BroadcastSweep sweep(trace, parsed, 256);
    sweep.run();

    for (std::size_t i = 0; i < parsed.size(); ++i) {
        MemByteSource own(bytes);
        StreamingTileTrace alone_trace(own);
        BroadcastSweep alone(alone_trace, {parsed[i]}, 256);
        alone.run();
        for (std::int32_t t = 0; t <= trace.n_tiles(); ++t)
            CHECK_EQ(sweep.engine(i).tile_origin(t), alone.engine(0).tile_origin(t));
        CHECK_EQ(sweep.engine(i).stats().core_stall,
                 alone.engine(0).stats().core_stall);
        CHECK_EQ(sweep.engine(i).stats().fetch_latency,
                 alone.engine(0).stats().fetch_latency);
    }
}

void test_a_mixed_layout_grid_is_rejected() {
    check::group("Task 17: one mapper, so one layout per sweep");
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace trace(src);
    std::vector<RunConfig> parsed;
    for (const std::string& s : {R"({"cin_block": 1, "cout_block": 16})",
                                 R"({"cin_block": 4, "cout_block": 16})"}) {
        RunConfig c = parse_config(s);
        std::vector<Warning> w;
        validate(c, 1, w);
        parsed.push_back(c);
    }
    CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, parsed, 256));
}

void test_max_engines_is_enforced_at_construction() {
    check::group("Task 17: an oversized grid fails at startup, not by OOM");
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace trace(src);
    RunConfig c = parse_config("{}");
    std::vector<Warning> w;
    validate(c, 1, w);
    const std::vector<RunConfig> many(9, c);
    CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, many, 8));
}

void test_the_window_never_holds_more_than_one_tile() {
    check::group("Task 17: a query for a tile off the window still throws");
    // The lockstep loop must never leave an engine one tile behind. This checks
    // the guard is live during a sweep rather than only in a unit test.
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace trace(src);
    RunConfig c = parse_config("{}");
    std::vector<Warning> w;
    validate(c, 1, w);
    BroadcastSweep sweep(trace, {c}, 8);
    sweep.run();
    CHECK_THROWS(std::out_of_range, trace.n_bursts(CoreId{0}, 0));
}

}  // namespace

int main() {
    test_broadcast_lockstep_equals_running_each_config_alone();
    test_a_mixed_layout_grid_is_rejected();
    test_max_engines_is_enforced_at_construction();
    test_the_window_never_holds_more_than_one_tile();
    return check::summary();
}
```

`build_three_tile_stream()` is the same in-file `StreamBuilder` Task 2 introduced; lift it
into `tests/stream_fixture.h` in this task so both test files share one implementation,
and have `test_stream_trace.cpp` include it rather than defining its own.

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_sweep
```
Expected: FAIL, `fatal error: wcache/sweep.h: No such file or directory`.

- [ ] **Step 3: Implement `Engine::step_tile`, `sweep.h` and `sweep.cpp`**

- [ ] **Step 4: Run it to verify it passes**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && ./build/fixture/test_sweep
```
Expected: PASS, `0 failures`. The first case is the one that matters: broadcast lockstep
is only a valid optimisation if it produces exactly what N separate runs produce.

- [ ] **Step 5: Add to the mutation list, then Checkpoint**

Add `include/wcache/sweep.h` and `src/sweep.cpp` to `FILES=`, then
`make clean && make test`. **Do not commit.**

---

## Task 18: D3b, `wcache_sweep` and `--config-grid`

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/apps/wcache_sweep.cpp`
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/src/config.cpp`
  (`parse_config_grid`)
- Modify: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/test_config.cpp`
- Create: `/home/ya867177/neuro_cache-wcache/src/wcache/native/tests/sweep_cli.sh`

**Interfaces:**
- Produces: the `wcache_sweep` CLI exactly as given in "The CLI, in full", and:

```cpp
// Two accepted grid documents.
//
// 1. An ARRAY of complete configurations, used verbatim and in order:
//      [ {...}, {...} ]
//
// 2. An OBJECT with `base` and `axes`, expanded to the full cross product with
//    the FIRST declared axis varying SLOWEST, so the row order of a grid file is
//    stable and readable:
//      {"base": {"cout_block": 16},
//       "axes": {"l1_size_bytes": [2048, 4096], "prefetch_distance": [0, 2]}}
//    gives four configurations in the order (2048,0) (2048,2) (4096,0) (4096,2).
//
// An axis naming a key `base` does not carry is still legal: `base` is a
// partial config and every key falls back to RunConfig's default.
std::vector<RunConfig> parse_config_grid(const std::string& json_text);
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.cpp`:

```cpp
void test_a_grid_array_is_used_verbatim_and_in_order() {
    check::group("Task 18: an array grid keeps its declared order");
    const std::vector<RunConfig> g = parse_config_grid(
        R"([{"l1_size_bytes": 2048}, {"l1_size_bytes": 4096}])");
    CHECK_EQ(check::ssize(g), std::int64_t{2});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});
    CHECK_EQ(g[1].l1_size_bytes, std::int64_t{4096});
}

void test_axes_expand_first_axis_slowest() {
    check::group("Task 18: the first declared axis varies slowest");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"cout_block": 16},
            "axes": {"l1_size_bytes": [2048, 4096],
                     "prefetch_distance": [0, 2]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{4});
    CHECK_EQ(g[0].l1_size_bytes, std::int64_t{2048});  CHECK_EQ(g[0].prefetch_distance, 0);
    CHECK_EQ(g[1].l1_size_bytes, std::int64_t{2048});  CHECK_EQ(g[1].prefetch_distance, 2);
    CHECK_EQ(g[2].l1_size_bytes, std::int64_t{4096});  CHECK_EQ(g[2].prefetch_distance, 0);
    CHECK_EQ(g[3].l1_size_bytes, std::int64_t{4096});  CHECK_EQ(g[3].prefetch_distance, 2);
    for (const RunConfig& c : g) CHECK_EQ(c.cout_block, 16);
}

void test_the_campaign_grid_expands_to_exactly_180() {
    check::group("Task 18: §4.2's grid is 5 x 3 x 3 x 4 = 180");
    const std::vector<RunConfig> g = parse_config_grid(
        R"({"base": {"cout_block": 16, "weight_bytes": 1, "l1_assoc": 8,
                     "l2_assoc": 16, "l1_mshrs": 16, "l2_mshrs": 20},
            "axes": {"l1_size_bytes": [2048, 4096, 8192, 16384, 32768],
                     "cin_block": [1, 2, 4],
                     "l2_size_bytes": [262144, 524288, 1048576],
                     "prefetch_distance": [0, 2, 4, 8]}})");
    CHECK_EQ(check::ssize(g), std::int64_t{180});
}
```

Create `tests/sweep_cli.sh`, which builds the same fixture stream Task 15 used, runs a
four-point grid, and asserts: four data rows plus a header; every row's arity 91; the row
whose `l1_size_bytes` and `prefetch_distance` match a `wcache_run` invocation is
**byte-identical** to that invocation's row after blanking `run_id` and
`sim_wall_seconds`; and the stall breakdown, the prefetch outcomes and the four
`total_cycles >= tick_base_total` relations all hold on every row.

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && make build/fixture/test_config
```
Expected: FAIL to link, `undefined reference to 'wcache::parse_config_grid'`.

- [ ] **Step 3: Implement `parse_config_grid` and `apps/wcache_sweep.cpp`**

- [ ] **Step 4: Run both to verify they pass**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && \
  ./build/fixture/test_config && make apps && tests/sweep_cli.sh
```
Expected: `0 failures` then `sweep_cli: OK`.

- [ ] **Step 5: Confirm the sweep row equals the single-run row**

This is D3's exit criterion in miniature: the same configuration must produce the same
numbers whether it ran alone or inside a grid.

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && tests/sweep_cli.sh 2>&1 | grep "identical"
```
Expected: `sweep row == run row: identical`.

- [ ] **Step 6: Checkpoint**

`make clean && make test && make apps`. **Do not commit.**

---

## Task 19: D3c, per-unit atomic result cache, resume and merge

The Python side of D3. The unit of work is one `(arch, n_cores, layer, sample)` trace: one
unit generates its trace once, runs every configuration in its tier against it in one
`wcache_sweep` process, and writes one atomic per-unit file. Rerunning resumes the missing
units. §8.2 makes this mandatory rather than a convenience, because R2 pushed Stage 3 to
about 1.97 h against a 2 h Slurm wall cap.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/run_sweep.py`
- Create: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/grids/tier0.json`
- Create: `.../grids/tier1_spad.json`, `.../grids/tier2_ridge.json`,
  `.../grids/tier3_full.json`, `.../grids/tier4_latency.json`
- Create: `.../grids/demo.json` (Task 20's small grid)

**Interfaces:**
- Mirrors `profiling/0803_l1_l2_cache/run_sweep.py`'s flags exactly, which is what makes
  the pattern transferable: `--run`, `--workers`, `--unit-index`, `--merge-only`,
  `--results-dir`, `--out`. New ones this campaign needs:

```
  --run                  execute; without it, print the preview only (the 0803 default)
  --workers N            parallel PIPELINE PAIRS, not parallel producers. Each pair is
                         one generator process piped into one wcache_sweep process
                         (§10.4 break 7). Default 1.
  --unit-index I         run only unit I, for a Slurm array
  --merge-only           validate and merge the cached unit results, run nothing
  --results-dir PATH     per-unit atomic caches. Default ./results
  --out PATH             the merged CSV. Default ./spad_vs_cache.csv
  --grid PATH            the tier definition. Required unless --merge-only.
  --tier NAME            the `tier` column and the results subdirectory
  --arms LIST            comma separated subset of
                         spad_oracle,spad_wcache,spad_nocsim,cache. Default all but nocsim.
  --dry-run-units        print the unit list and exit, so a Slurm array size is
                         derived rather than guessed
```

The atomicity rule, stated because it is the whole point of the cache: a unit writes to
`<results-dir>/<tier>/<unit_key>.csv.tmp` and `os.replace`s it into
`<unit_key>.csv` only after `wcache_sweep` exits 0 **and** the row count equals the grid
size. A killed job therefore leaves either a complete unit file or none, never a partial
one. This is `save_weight_trace`'s own tempfile-then-replace discipline, reused.

Resume replaces `generate_weight_traces.py`'s skip-existing, which §10.4 break 6 says
disappears with the intermediate files. Resuming on **results** rather than on inputs is
strictly better: it also catches a unit whose trace was regenerated.

- [ ] **Step 1: Write the failing test**

Create `profiling/0820_phaseD_spad_vs_cache/tests/test_resume.sh`:

```sh
#!/bin/sh
# Task 19: the per-unit cache is atomic and resume is exact.
set -e
here=/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# 1. The preview runs without --run and writes nothing.
conda run -n cosa_snn python "$here/run_sweep.py" --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" > "$tmp/preview.txt"
test ! -d "$tmp/results"
grep -q "units" "$tmp/preview.txt"

# 2. A full run produces one file per unit.
conda run -n cosa_snn python "$here/run_sweep.py" --run --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
units=$(conda run -n cosa_snn python "$here/run_sweep.py" --dry-run-units \
        --grid "$here/grids/demo.json" | wc -l)
test "$(ls "$tmp/results/demo" | wc -l)" -eq "$units"

# 3. Deleting one unit file and rerunning regenerates ONLY that one.
first=$(ls "$tmp/results/demo" | head -1)
cp "$tmp/results/demo/$first" "$tmp/gold.csv"
touch -d '2000-01-01' "$tmp/results/demo"/*
rm "$tmp/results/demo/$first"
conda run -n cosa_snn python "$here/run_sweep.py" --run --grid "$here/grids/demo.json" \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
# only the regenerated file has a new mtime
test "$(find "$tmp/results/demo" -newermt '2001-01-01' | wc -l)" -eq 1
# 4. and it is byte-identical to the first run, ignoring run_id and wall time.
conda run -n cosa_snn python - "$tmp/gold.csv" "$tmp/results/demo/$first" <<'PY'
import csv, sys
def norm(p):
    rows = list(csv.reader(open(p)))
    head = rows[0]
    drop = {head.index("run_id"), head.index("sim_wall_seconds")}
    return [[c for i, c in enumerate(r) if i not in drop] for r in rows]
a, b = norm(sys.argv[1]), norm(sys.argv[2])
assert a == b, "resume is not byte-identical"
print("resume: byte-identical")
PY

# 5. --merge-only produces the merged CSV and validates the row count.
rm -f "$tmp/out.csv"
conda run -n cosa_snn python "$here/run_sweep.py" --merge-only \
    --results-dir "$tmp/results" --out "$tmp/out.csv" --tier demo
test -s "$tmp/out.csv"
echo "test_resume: OK"
```

`chmod +x` it.

- [ ] **Step 2: Run it to verify it fails**

```bash
/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/tests/test_resume.sh
```
Expected: FAIL, `can't open file '.../run_sweep.py'`.

- [ ] **Step 3: Write `run_sweep.py` and the six grid files**

`grids/demo.json` is the small grid Task 20 needs: four configurations over the
`examples/` fixture slices, chosen from the 180 so that the demo exercises the two §4.5
warnings and both prefetch states:

```json
{"base": {"cout_block": 16, "weight_bytes": 1, "l1_assoc": 8, "l2_assoc": 16,
          "l1_mshrs": 16, "l1_tgts_per_mshr": 20,
          "l2_mshrs": 20, "l2_tgts_per_mshr": 12,
          "l1_latency": 0, "l2_latency": 10, "l2_miss_latency": 100,
          "l2_size_bytes": 524288},
 "axes": {"l1_size_bytes": [2048, 8192],
          "cin_block": [4],
          "prefetch_distance": [0, 4]},
 "fixtures": ["loas_vgg16_layer01_v2", "ptb_resnet19_layer01_v2"]}
```

`grids/tier0.json` is the full 180 at LoAS / 16 cores / vgg16 layer_01 / 1 sample.
`grids/tier2_ridge.json` is the 14 distinct one-factor-at-a-time configurations of §4.4,
pivoting on L1 8 KB, line 32 B, L2 512 KB, `d = 4`, plus the labelled `l1_mshrs = 4`
calibration row as a fifteenth. `grids/tier4_latency.json` is §7.3's two sensitivity axes,
`l2_latency` in `{3, 10, 17}` and `l2_miss_latency` in `{50, 100, 200}`, at the nominal
only. Write each grid's arithmetic in a comment field so the count is checkable, and add
an assertion in `run_sweep.py` that each grid expands to the count its filename promises.

- [ ] **Step 4: Run it to verify it passes**

```bash
/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/tests/test_resume.sh
```
Expected: `resume: byte-identical` then `test_resume: OK`.

- [ ] **Step 5: Confirm the grid counts**

```bash
cd /home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache && \
  for g in grids/*.json; do
    printf '%s ' "$g"
    conda run -n cosa_snn python run_sweep.py --grid "$g" --dry-run-units 2>/dev/null | wc -l
  done
```
Expected: `tier0.json` 1 unit, `tier2_ridge.json` 36 units, `tier3_full.json` 12 units,
`demo.json` 2 units. The **configuration** counts (180, 15, 180, 4) are asserted inside
`run_sweep.py`, not here.

- [ ] **Step 6: Checkpoint. Do not commit.**

---

## Task 20: The local demo smoke run

R7: this machine runs demo and smoke runs only. This is the pre-Delta smoke test that
precedes Tier 0. It produces no campaign result and is not a tier.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/tests/demo_smoke.sh`
- Create: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a valid CSV over a few of the 180 configurations against the `examples/`
  fixture slices, through `wcache_sweep`, with every §2 known-answer check applied to it.

- [ ] **Step 1: Write the failing test**

Create `tests/demo_smoke.sh`. It runs `run_sweep.py --run --grid grids/demo.json` and then
applies, in one Python block, every check §2 lists as "must pass before any sweep row is
trusted", plus the two the brief names:

```python
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
assert rows, "no rows"
for r in rows:
    # 1. total_cycles exists, is positive, and is at least the oracle.
    assert int(r["total_cycles"]) >= int(r["tick_base_total"]) > 0
    assert int(r["stretch_cycles"]) == int(r["total_cycles"]) - int(r["tick_base_total"])
    # 2. V21: the stall breakdown sums.
    parts = sum(int(r[k]) for k in
                ("stall_l1_slot", "stall_l1_line", "stall_l2_slot", "stall_l2_line",
                 "stall_l1_port", "stall_l2_port", "stall_channel", "stall_barrier"))
    assert parts == int(r["stall_total"]), (parts, r["stall_total"])
    # 3. the four prefetch outcome states sum to pf_issued.
    assert (int(r["pf_timely"]) + int(r["pf_late"]) + int(r["pf_wasted"])
            == int(r["pf_issued"]))
    # 4. hidden_latency = fetch_latency - core_stall, and it is never negative (R8).
    hid = int(r["fetch_latency_sum"]) - int(r["core_stall_sum"])
    assert int(r["hidden_latency"]) == hid >= 0, (r["hidden_latency"], hid)
    # 5. at d = 0 hidden_latency is identically zero (R8, §5.4).
    if int(r["prefetch_distance"]) == 0:
        assert int(r["hidden_latency"]) == 0, r["hidden_latency"]
    # 6. padding_fraction is 0 on these layers: they divide exactly (§3.3).
    assert float(r["padding_fraction"]) == 0.0, r["padding_fraction"]
    # 7. non_inclusive means no back-invalidation (C4's exit criterion).
    if r["inclusion"] == "non_inclusive":
        assert int(r.get("back_invalidations", 0) or 0) == 0
    # 8. the §4.5 geometry is reconstructable from the row alone.
    assert (int(r["l1_size_bytes"]) // int(r["line_size_bytes"])
            == int(r["l1_num_lines"]))
    assert int(r["l1_num_lines"]) // int(r["l1_assoc"]) == int(r["l1_num_sets"])
print(f"demo_smoke: {len(rows)} rows, every known-answer check passed")
```

- [ ] **Step 2: Run it to verify it fails**

Before `run_sweep.py` produces a merged CSV, this exits on `no rows`.

- [ ] **Step 3: Run the demo for real**

```bash
cd /home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache && \
  conda run -n cosa_snn python run_sweep.py --run --grid grids/demo.json \
    --tier demo --out demo_results.csv && tests/demo_smoke.sh demo_results.csv
```
Expected: `demo_smoke: 8 rows, every known-answer check passed` (4 configurations x 2
fixtures).

- [ ] **Step 4: Also run the `d = 16` duplicate check**

§2 known-answer check 6, which this campaign gets for free: a prefetch distance above the
MSHR budget must reproduce the last in-budget point exactly. The LoAS budget is
`16 - 1 = 15`, so `d = 16` must reproduce `d = 15`.

```bash
cd /home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache && \
  conda run -n cosa_snn python run_sweep.py --run \
    --grid grids/duplicate_check.json --tier dupcheck --out dup.csv && \
  conda run -n cosa_snn python - dup.csv <<'PY'
import csv, sys
rows = {int(r["prefetch_distance"]): r for r in csv.DictReader(open(sys.argv[1]))}
a, b = rows[15], rows[16]
ignore = {"run_id", "sim_wall_seconds", "prefetch_distance", "events_per_cycle"}
diff = {k for k in a if k not in ignore and a[k] != b[k]}
assert not diff, f"d=16 does not reproduce d=15: {sorted(diff)}"
print("duplicate check: d=16 reproduces d=15 exactly")
PY
```
Expected: `duplicate check: d=16 reproduces d=15 exactly`. A failure means the
`min(d, budget)` model is wrong (v3 `:1592-1595`), which is a finding rather than a
harness bug. Create `grids/duplicate_check.json` alongside.

- [ ] **Step 5: Write the README**

`profiling/0820_phaseD_spad_vs_cache/README.md` recording what was run locally, the row
counts, the wall time, and an explicit statement that **no campaign tier ran here** and
that the Slurm scripts are for Delta (R7).

- [ ] **Step 6: Checkpoint**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && \
  make clean && make test && make apps && tests/v1_pipe.sh && tests/run_cli.sh && \
  tests/sweep_cli.sh
```
Expected: all green. **Do not commit.**

---

## Task 21: Slurm and driver scripts for Delta

Written here, run elsewhere (R7). Nothing in this task executes a campaign tier.

**Files:**
- Create: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm`
- Modify: `/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/README.md`

**Interfaces:**
- Mirrors `profiling/0803_l1_l2_cache/run_sweep.slurm`: 16 CPUs, 128 GB, a **2 h** wall
  cap, account `bebv-delta-gpu`, partition `gpuA40x4` with one otherwise-unused A40
  because the account is GPU-only, project root `/u/yyu9/projects/neuro_cache`.

Two things this campaign's script must do that the 0803 one did not:

1. **Be a Slurm array over units**, sized from `run_sweep.py --dry-run-units`, because
   §8.2 says Stage 3 alone is now at least two jobs: 1.97 h against a 2 h cap is not a
   margin. Each array task runs `--unit-index $SLURM_ARRAY_TASK_ID`.
2. **Run the pipeline as a pipe**, which is the whole point of §10:

```sh
conda run -n cosa_snn python scripts/generate_weight_traces.py --stream \
    --arch "$ARCH" --trace-dir "$TRACE_DIR" --layer "$LAYER" --sample "$SAMPLE" \
  | src/wcache/native/build/release/wcache_sweep \
      --config-grid "$GRID" --trace - --header \
      --arm cache --tier "$TIER" --git-commit "$(git rev-parse HEAD)" \
      --out "$RESULTS/$UNIT.csv.tmp"
```

with `set -o pipefail` so a generator crash fails the task rather than producing a short
CSV, and the `.tmp` to `.csv` rename done by `run_sweep.py`, never by the shell.

- [ ] **Step 1: Write the failing test**

Create `tests/test_slurm_shape.sh`, which does not submit anything:

```sh
#!/bin/sh
# Task 21: the Slurm script's shape, checked without a scheduler.
set -e
f=/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm
grep -q '^#SBATCH --time=02:00:00' "$f"
grep -q '^#SBATCH --cpus-per-task=16' "$f"
grep -q '^#SBATCH --mem=128' "$f"
grep -q '^#SBATCH --account=bebv-delta-gpu' "$f"
grep -q '^#SBATCH --partition=gpuA40x4' "$f"
grep -q '^#SBATCH --array=' "$f"
grep -q 'set -o pipefail' "$f"
grep -q 'generate_weight_traces.py --stream' "$f"
grep -q 'wcache_sweep' "$f"
grep -q -- '--trace -' "$f"
# and it must NOT write an intermediate trace file
if grep -q 'weight_traces' "$f"; then
    echo "the Slurm script must not reference an on-disk trace corpus"; exit 1
fi
echo "test_slurm_shape: OK"
```

`chmod +x` it.

- [ ] **Step 2: Run it to verify it fails**

```bash
/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/tests/test_slurm_shape.sh
```
Expected: FAIL, `grep: ...run_sweep.slurm: No such file or directory`.

- [ ] **Step 3: Write `run_sweep.slurm`**

- [ ] **Step 4: Run it to verify it passes**

```bash
/home/ya867177/neuro_cache-wcache/profiling/0820_phaseD_spad_vs_cache/tests/test_slurm_shape.sh
```
Expected: `test_slurm_shape: OK`.

- [ ] **Step 5: Build the release binaries the script names**

```bash
cd /home/ya867177/neuro_cache-wcache/src/wcache/native && \
  make MODE=release lib && make MODE=release apps && \
  ls -l build/release/wcache_run build/release/wcache_sweep
```
Expected: both binaries exist. Then re-run the demo against the **release** build and
confirm the CSV is byte-identical to the fixture build's, ignoring `sim_wall_seconds`:
a `-DNDEBUG` build that produces different numbers means an assert had a side effect.

- [ ] **Step 6: Record in the README, then Checkpoint**

Add to `README.md`: the array size, the per-unit command, the expected wall time from
§8.2 (about 2.0 h on 16 CPUs, bracket 0.4 to 3.3 h), and the note that Tier 0 replaces
the 15 core-second planning figure with a measurement. **Do not commit.**

---

## OPEN QUESTIONS

Places where the two specs are ambiguous, silent, or in tension. Each names the reading
this plan takes, so an executor is never guessing, and each is flagged so a coordinator
can overrule it before the code is written.

**Q-A. Ruling R8 mixes a per-burst `served` with a per-line `t_first_request`, and a
burst is several lines.** `fetch_latency[c] = Σ_k (served(c,k) − t_first_request(line))`
sums over bursts `k` but anchors on a line, and Spinalflow's 64-COUT burst is 4 lines at
`cout_block = 16`. Two readings: **(i)** one term per burst, anchored on the **minimum**
`t_first_request` over the burst's lines; **(ii)** one term per line. Reading (ii) makes
`fetch_latency` scale with `lines_per_burst` and **breaks the documented `d = 0` identity
`fetch_latency == core_stall`** (v3 `:1438`, §5.4). *This plan takes reading (i)* (Task
12) and says why in the task. Confirm, because the choice changes every prefetch number in
the campaign and cannot be changed after the grid runs.

**Q-B. Broadcast lockstep needs an incremental engine API that neither spec mentions.**
§10.5 says "the window advances when all engines have finished it" and never says how 180
engines interleave inside one process. `Engine::run()` is a single event loop that runs to
completion. Three answers: **(i)** add `run_to_barrier` / `step_tile` / `finish` and drive
them cooperatively, single-threaded; **(ii)** one thread per engine, blocking inside the
trace on a window barrier; **(iii)** buffer the whole sample and replay it per engine,
which §10.5 calls "acceptable but timid" at 315.8 MB resident. *This plan takes (i)*
(Tasks 4, 15, 17), which is the smallest change and keeps the event order, and therefore
V3's byte-identical event log, provably untouched. Confirm that extending the `Engine`
public surface is acceptable, since it is a Phase C class and Phase C is closed.

**Q-C. The authoritative source of `n_cores` for the stream header is unstated.** U25
proves `max(core_id) + 1` is wrong: prosperity implies 126 on resnet19 `layer_01` where
the same layer under three other architectures implies 128. §10.4 says the header carries
`n_cores` but never says where the producer gets it. *This plan takes*
`n_cores = prod(spatial_factors.values())` from the decoded schedule, with an assertion
that `max(core_id) < n_cores` (Tasks 7, 8). Confirm, and confirm that the product is over
**all** dims rather than a subset.

**Q-D. `lines_per_burst` is a property of the data, not of the header, but D1 needs it
before the first tile.** `l1_demand_reserve` defaults to `lines_per_burst`, and validation
must run before the engine is built, which is before any burst has been seen. Three
answers: **(i)** derive it from the config alone as `burst_span / cout_block`, which needs
`burst_span` and the header does not carry it; **(ii)** add `burst_span` to the header,
which is a fifth header field beyond the four R1 ruled; **(iii)** validate lazily, after
the first tile frame. *This plan assumes* the header should carry the burst span and
flags it, because (i) is impossible as the format stands and (iii) means a config error is
reported after the pipe has already started producing. **This is the one place the plan
cannot proceed without a ruling**: Task 15 step 5 is written against a value it has no
source for. Recommended: add `i32 burst_span` to the header beside `burst_dim` and
`burst_stride`, which is the same argument R1 already accepted for those two.

**Q-E. Three settable knobs have no §9.2 column.** `l1_ii`, `l2_to_l1_latency` and
`dram_ii` are all `LevelParams`/`EngineParams` fields with defaults this campaign relies
on, and none appears in §9.2's configuration block. A knob with no column cannot be
reconstructed from the row. *This plan adds all three* plus `l2_num_lines` and
`l2_num_sets`, taking the schema from 86 columns to 90. Confirm, or say which to drop.

**Q-F. D2's remit as v3 writes it is "statistics and the results CSV", but most of §9.2's
columns do not exist in the engine.** `EngineStats` today has nine fields. The stall
breakdown, the four prefetch outcome states, the memory counters, the MSHR occupancy
histograms, `hits_downgraded_to_miss`, `max_wait_depth` and `events` are all new
instrumentation inside Phase C code. *This plan builds all of it* (Task 11), which makes
Task 11 the largest single task here. Confirm that instrumenting Phase C classes is in
scope for D2, or say which columns may be left empty for the demo.

**Q-G. `padding_fraction` has a mandate but no definition.** `PROGRESS.md:894` mandates
the column on every row and §3.3 says it must be 0 for all four chosen layers, but no
document defines the ratio. *This plan defines it* as
`(lines_touched * elements_per_line − distinct_elements_touched) /
(lines_touched * elements_per_line)`, computed by the mapper over the run's expanded
lines (Task 13). Confirm the denominator: the alternative is per-burst rather than
per-run, and the two differ whenever a line is touched by more than one burst.

**Q-H. The stream carries no run identity, and §10.4's header list does not include one.**
Without `arch`, `workload`, `layer` and `sample_idx` on the wire, a CSV row produced from a
pipe cannot be joined to its `spad_*` pair, and the driver has to pass four strings on the
command line that must agree with what the producer actually generated. *This plan adds an
identity block to the header* and flags it as an addition beyond the four ruled fields.
Confirm.

**Q-I. Q12 is open and this plan takes a position on it.** §10.8 Q12: with a stream, the
generator enters D3's "reproduces byte-identically" claim. *This plan reads D3's exit
criterion as satisfied by the `--dump-trace` replay path*: a result is byte-identical when
replaying the dumped stream through `wcache_run` reproduces it, and the generator's own
determinism (seeded `sample_indices`, cached schedule) is asserted but not proved. Task 19
step 4 tests the replay half. Confirm, or require the dump-and-replay path for any result
that goes in a paper, which is the stricter option §10.8 offers.

**Q-J. Streaming requires the `NodeTileSpec` sequence to be sorted, and nothing says it
is.** `assemble_layer_traces` groups into a dict and then `sorted(groups[i])`, so the
current code is order-independent by construction. A streaming producer cannot sort: it
must emit tile `(dram_i, noc_i)` as soon as every core has reported it, which requires the
specs to arrive grouped by `(dram_i, noc_i)`. *This plan requires* the producer to sort
the `NodeTileSpec` list by `(dram_i, noc_i, core_id)` before the binary is invoked, and to
assert the arriving order matches (Task 7). Confirm there is no reason the solver's own
order must be preserved.

**Q-K. Two campaign questions are still open and gate the grid, not this plan.** Q3 (the
VGG16 and ResNet-19 deep-layer picks), Q4 (`l1_mshrs` 16 or 4), Q6 (the Q13 grid merge)
and Q7 (keep or drop nocsim) are all open in §11 and none of them changes any code here.
Q4 in particular: this plan hard-codes `l1_mshrs = 16` as the **default** and Task 19's
`grids/tier2_ridge.json` carries `l1_mshrs = 4` as the labelled calibration row, so both
gem5 families are reported and the ruling can arrive after the code lands.

---

## Self-review

Run against the two specs with fresh eyes, as the skill requires.

**1. Spec coverage.** Every gap and every scoped item, with the task that implements it:

| Item | Task |
|---|---|
| G1, A3 the trace reader, built as the streaming reader | 1, 2, 3 |
| G2, no `main.cpp`, no config loader, no CSV writer | 9, 13, 15, 18 |
| G3, `total_cycles` (layer makespan) | 13 |
| G4, `l2_latency` and `l2_miss_latency` values | 9 (defaults 10 and 100) |
| G6 / U25-U28, the four header fields, ruled by R1 | 1, 3 step 5, 7 |
| G7 / Q5, the prefetch figure of merit, ruled as R8 | 12 |
| G11, `l2_demand_reserve` rejected and not a column | 10, 13 |
| G13, the random-access interface against an in-flight stream | 2, 3, 4, 17 |
| G14, the distinct-address diagnostic, explanatory only | 14 |
| §4.5 D1 guards: two warnings, one rejection, two columns | 10, 13 |
| §9.2 row schema | 13 |
| §10.4 wire format, header, per-tile framing | 1, 3, 7 |
| §10.4 the five `main.cpp`, stdout and the loop swap | 5, 6 |
| §10.4 `save_weight_trace`'s streaming sibling | 7 |
| §10.4 worker parallelism moved to pipeline pairs | 8, 19 |
| §10.5 broadcast lockstep | 17 |
| §10.6 `--dump-trace` / `--dump-trace-tiles` | 8 |
| §9.1 per-unit atomic cache, resume, merge, driver flags | 19 |
| D3 exit: a grid point runs end to end and reproduces | 18, 19 |
| V1 end to end on a real fixture through the pipe | 16 |
| V21 stall breakdown sums | 11, 13, 20 |
| V27 exact drift at `l1_latency = 1` | 16 step 5 |
| The three R8 worked cases and the `d = 0` invariant | 12 |
| A local demo over a small grid, valid CSV | 20 |
| Slurm and driver scripts under `profiling/0820_...` | 21 |
| `make test` stays green at 24,850 checks or more | every Checkpoint |

**Gaps found and closed during this review:** the `Engine` incremental API (added as Task
4 after reading `engine_core.cpp`'s `barrier_arrive` and finding `tile_tail` is read
before the barrier dispatches), the `apps/` directory (added after finding the Makefile
globs `src/*.cpp` into `libwcache.a`, so a `main()` in `src/` breaks every test link), and
the mutation-list edits (added after finding `mutation_check.sh` has an explicit `FILES=`
rather than a glob).

**Gaps found and NOT closed, because they need a ruling rather than a decision:** Q-D,
`lines_per_burst` has no source before the first tile. Task 15 step 5 is the one step in
this plan written against a value the format does not carry.

**2. Placeholder scan.** No "TBD", no "implement later", no "add appropriate error
handling", no "similar to Task N". Every test step carries the actual test code. Three
implementation steps describe an algorithm in prose rather than showing the code (Task 1
step 4's `decode_header` validation order, Task 3 step 3's `advance()`, Task 11 step 3's
counter placement); each names every check and every increment point explicitly, and each
is under a test that fails if any one of them is missing.

**3. Type consistency.** Checked across tasks: `StreamingTileTrace::advance` /
`window_tile` / `tick_base` / `mac_cycles` / `distinct_addresses` are spelled identically
in Tasks 2, 3, 14, 15 and 17. `Engine::run_to_barrier` (Task 4), `Engine::finish`
(Task 15) and `Engine::step_tile` (Task 17) are three distinct methods with distinct jobs
and no overlap. `RunConfig` field names in Task 9 match the CSV column names in Task 13
one for one, except the five derived ones (`line_size_bytes`, `l1_num_lines`,
`l1_num_sets`, `l2_num_lines`, `l2_num_sets`) which are member functions, not fields.
`validate(RunConfig&, std::int32_t, std::vector<Warning>&)` has the same signature in
Tasks 10, 13, 17 and 18. `stream::StreamHeader` is the parameter type in Tasks 1, 13, 14
and 15.

---

## Execution handoff

Plan complete and saved to
`/home/ya867177/neuro_cache-wcache/log/2026-08-20-phaseD-implementation-plan.md`.

**Before Task 1 begins, Q-D needs a ruling**, because Task 15 depends on a header field
that does not yet exist. Everything from Task 1 through Task 14 can proceed regardless: if
the ruling adds `burst_span` to the header, it is a one-line change to Task 1's layout and
Task 7's writer, both of which are pinned by tests that will fail loudly.

Two execution options:

1. **Subagent-driven (recommended).** A fresh subagent per task, review between tasks,
   fast iteration. The task boundaries here are drawn so that a reviewer could reject one
   and accept its neighbour.
2. **Inline execution.** Batch execution with checkpoints for review.

Nothing in either path commits. Every task ends at a Checkpoint that runs `make clean &&
make test` and stops.
