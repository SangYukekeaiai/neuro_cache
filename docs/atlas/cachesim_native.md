# Code atlas: `src/lays/cachesim` (cache simulator)

Branch `wcache-rebuild-phase-a`, commit `6e9aca1`, re-stamped from `0c55f2f` on 2026-11-04.

**Scope of this stamp.** Paths, module names and policy spellings are true at `0c55f2f`, and
every line number was re-resolved across the three restructure commits (`aa6c593` src-layout,
`ed926d1` `examples/`+`zoo/`, `0c55f2f` policy rename): in those, every edit to a cited file was an in-place substitution at the
same line number, so no line number moved. Method: of the 305 entries in `git diff -M b2c4a88 0c55f2f`,
git pairs 294 by rename or modification, and every hunk of those pairs starts at the same line and spans
the same count on both sides; the 5 moves git reported as an unpaired add plus delete were checked the
same way by hand (`khkw_sweep.json`, `l2pf_demo.json`, `parsers/__init__.py`, `scheduler/__main__.py`,
`scheduler/objectives/traffic/__init__.py`, each one balanced hunk at an identical position), and the one
genuinely new file, `src/lays/__init__.py` (1 line), is cited nowhere. The
three exceptions - `.gitignore`, `pyproject.toml` and `zoo/demo_l2pf/compare_l2pf.py` - were
re-resolved by content. Coverage claim: this applies to BOTH citation forms (`path:N` attached and
bare `:N`) in BOTH backtick states.

Re-verified since, so nothing here is left uncovered. The nineteen feature commits between
`1934fd4` (this file's previous stamp) and `b2c4a88` - the touch filter, `pf_lru` and BarrierLog work -
moved 261 of this file's citations off their targets, in BOTH forms: 62 attached and 199 bare, measured
by comparing the text at each cited line number at `1934fd4` and at `b2c4a88`; with the one citation no
text comparison could reach (below), that is 262 exposed of 962. Every one of them has
since been read against the code at `0c55f2f` and repointed, except two that reading certified as
already correct (`src/prefetch/prefetcher.cpp:13-32` and its `:25-26`, whose text changed only because
`NextTile` was renamed `DistanceAware`) and one never-measured citation
(`examples/cache/khkw_sweep.json:2-4`, whose old blob git reports as an unpaired add plus delete rather
than a rename, so no text comparison was possible; it was read instead). Three cautions this pass
earned. First, the count is per citation, not per file, and it is measured on the cited TEXT rather
than on where hunks fall: a citation can sit far above every hunk in its file and be unaffected, and a
citation in a file that never moved a line can still be stale because the line was rewritten in place.
Second, never-measured is not measured-clean. Third, and most important, text comparison is a candidate
list and not a defect list in either direction: it cannot see a citation that was never right, and it
cannot see one that shifted onto a coincidentally identical line - a blank, a `};`, a comment.
Reading the target is the only detector for "was this ever right", so every citation above was
read, not merely repointed.

**Re-stamp 2026-11-04, `0c55f2f` -> `6e9aca1`.** Everything above was true at `0c55f2f` and stands
as written. `6e9aca1` added the fourth layout mapper and its tests; between the two commits eleven
non-documentation files changed - `.gitignore` and ten under `src/lays/cachesim/native/`, of which
`include/cachesim/layout/cin_khkw_concat.h`, `src/layout/cin_khkw_concat.cpp` and
`tests/layout/test_cin_khkw_concat.cpp` are new - plus eleven new files under `zoo/` that this file
cites nowhere; the intervening commit `aaedfe7` touched documentation only. Of the changed files,
the ones cited here are `.gitignore`, `Makefile`, `include/cachesim/enum_names.h`,
`include/cachesim/layout/mapper.h`, `src/config.cpp`, `src/layout/factory.cpp`, the two new
`cin_khkw_concat` files and `tests/layout/test_layout_golden.cpp`; `tests/layout/test_neighbour.cpp`
and `tests/layout/test_cin_khkw_concat.cpp` are named in 2.4 but carry no line citation. Every
citation into all of them has been read at `6e9aca1`, not repointed by arithmetic, and the ones whose
target had moved were repointed: the whole `include/cachesim/layout/mapper.h` entry in 2.1 (the new
enumerator and the two comment lines describing it moved the enum declaration by two and everything
below it by three), the `enum_names.h` entry in 2.1 (one line added to each of its `name_of` and
`parse` pairs for `LayoutKind`), and all eight `Makefile` citations at or below that file's new line
42 - one in convention 5, three in 1.2, two in 2.4 and two in section 4 - by one. Also repointed:
`make_mapper`'s range in 1.3, which `6e9aca1` moved when it rewrote `src/layout/factory.cpp`'s header
comment, and every citation in 2.4's `test_layout_golden.cpp` bullet - its grid, its refusal cases,
its set counts, `kGolden` and `--print-golden` - which moved when the fourth layout's cases and
golden rows were added to that file. `src/config.cpp` changed only by an in-place substitution of two
comment lines, `:592,594`, and kept its 845 lines, so no citation into it moved. The four-mapper
facts and the new 2.2 entry cite the new files at `6e9aca1` directly. Every code file cited in this
file is committed at `6e9aca1`.

Written from code only: `.cpp`, `.h`, `.sh`,
`.py`, `Makefile`, `.json`. No markdown, text or log file was read, so any design rationale below is
what the code's own comments state.

**Path and citation conventions.** Every path and every citation below obeys these six rules, and a
resolver needs nothing else to read the file.

1. **Repo-root paths.** A path that starts with `src/lays/cachesim/native/`, `src/lays/cachesim/`,
   `src/lays/weight_trace_gen/`, `examples/`, `scripts/` or `docs/` is relative to the repo root. So is a
   bare `.gitignore`, which always means the repo-root file; the two-line native twin is spelled in
   full as `src/lays/cachesim/native/.gitignore` wherever it is meant (3.5).
2. **Every other path is relative to `src/lays/cachesim/native/`**, including a bare `Makefile`, which is
   the GNU make native build (`src/lays/cachesim/native/Makefile`) and never the repo-root one, and every
   `tests/` path: the repo-root `tests/` holds pytest `.py` files only and is never cited in this
   file, so `tests/run_cli.sh`, `tests/test_config.cpp` and `tests/layout/test_block_pack.cpp` are
   all native.
3. **The implied first component.** The native tree spells the same directory names three times
   (`core/`, `index/`, `instrument/`, `layout/`, `prefetch/`, `replacement/`, `trace/` under each of
   `include/cachesim/`, `src/` and `tests/`), and a path whose first component is one of those names
   is written without the tree above it. The file kind supplies the missing component: a `.h` is
   under `include/cachesim/` (`trace/stream_format.h` is
   `include/cachesim/trace/stream_format.h`), a `test_*.cpp` is under `tests/`
   (`prefetch/test_neighbour.cpp` is `tests/prefetch/test_neighbour.cpp`), any other `.cpp` is under
   `src/` (`core/engine.cpp` is `src/core/engine.cpp`). The same rule names the four headers at the
   top of the include tree: `config.h`, `enum_names.h`, `sweep.h`, `types.h`.
4. **A path that already starts with `include/`, `src/`, `apps/` or `tests/` is taken as written**,
   and `src/` here is the native library's own source tree, never another of the repo's `src/`
   subtrees: those are always written with their second component, as in rule 1. Writing the prefix
   out is what distinguishes the headers private to the library, which are not installed under
   `include/`, from the public ones: `src/layout/layout_common.h` is a `src/` header, and
   `tests/stream_builder.h` a test one.
5. **Bare file names.** A name with no directory component is the file of that name anywhere in
   `src/lays/cachesim/`, the tree this atlas covers and which contains `native/`. Section 2.5's
   example fixtures and their `to_stream.py` converter are the one part of this atlas that sits
   OUTSIDE that tree, under the repo-root `examples/cachesim/`; they are resolved by the third
   clause below, not by this one. Every name in the tree is unique, so the lookup needs no
   section context: `cachesim_run.cpp` is `apps/cachesim_run.cpp`,
   `engine.cpp` is `src/core/engine.cpp`, `check.h` is `tests/check.h`, `test_block_pack.cpp` is
   `tests/layout/test_block_pack.cpp`, and `stream.py` is `src/lays/cachesim/stream.py`. A section or
   entry heading that names a directory (`apps/` in 2.3, `tests/` in 2.4, `prefetch/` in 2.2) says
   where that section's files sit; it does not change where a name resolves. Exactly one name occurs
   twice in the tree, and the second copy is always spelled with its directory: a bare
   `test_neighbour.cpp` is `tests/layout/test_neighbour.cpp`, and the prefetch one is written
   `prefetch/test_neighbour.cpp`. Three kinds of bare name are not files of that tree: a sweep
   config name (`base.json`, `khkw_sweep.json`) is the file under `examples/cache/`, while
   `l2pf_demo.json` is the campaign's own copy under `zoo/demo_l2pf/`; a run output such as
   `results.csv` is written at run time and is not in the repo at all; and a `*_v2.json` or
   `*_v1_legacy.json` fixture name, `manifest.json`, and `to_stream.py` are the files of those
   names under `examples/cachesim/`. Nor are the POSIX headers `fcntl.h` and `unistd.h` named in
   4, or the `CMakeLists.txt` the repo does not have, nor `libcachesim.a`, which `Makefile:46`
   names as the library target and no commit tracks.
6. **Citations.** `path:N` cites line N of that path, `path:A-B` a line range, and `path:A,B` two
   separate lines. A bare `:N` cites the file its entry is about: the file the entry heading names,
   or the file named by a bullet that opens with one of its own, until a later citation inside that
   entry names a different file, which the bare citations after it then follow. One bullet can hold
   several entries this way, each with its own run of bares - 2.1 lists `none.h`, `next_access.h`,
   `neighbour.h` and `distance_aware.h` in a single bullet.
   Three things never retarget a bare `:N`. First, a name rule 5 places outside the tree (a
   config, a run output, a POSIX header). Second, a path named inside an entry as a
   cross-reference to another file: a bare `:N` belongs to the entry's own SUBJECT, so a
   cross-reference never retargets the bares that follow it, wherever in the entry it appears.
   That makes this a per-ENTRY rule and not a per-path one, and the same path is a
   cross-reference in one entry and a subject in another: `include/cachesim/enum_names.h` is a
   cross-reference in 2.2's `instrument/stats.cpp` entry and again in 2.2's `sweep.cpp` entry, so
   the bares there stay on `src/instrument/stats.cpp` and `src/sweep.cpp`;
   `src/lays/cachesim/stream.py` is a cross-reference in 2.1's `trace/stream_format.h` entry, so
   the bares there stay on `include/cachesim/trace/stream_format.h`, and a subject in the two
   places named below; and 2.5's `core/engine.h` entry cites `src/core/engine.cpp` and
   `src/instrument/stats.cpp` in the middle of a bullet while its `:257-258`, `:268-273`, `:318`,
   `:325` and `:341` stay lines of `core/engine.h`. Third, a citation that closes one entry does
   not reach into the next. Because a bare filename such as `engine.cpp:N` is not a path, a
   cross-reference that would otherwise be written that way is given its full path, so the bares
   after it cannot be read against it.
   A path DOES anchor the bares after it wherever it is
   an entry's own subject - a path opening a sub-entry as `` `path`: ``, or heading a bold
   paragraph. `src/lays/cachesim/stream.py` is a cross-reference in one entry and a subject in
   two: 2.5's own `src/lays/cachesim/stream.py` bullet, and the "Upstream connection" paragraph,
   whose nine bares after `src/lays/cachesim/stream.py:44` are lines of
   `src/lays/cachesim/stream.py` (`:53`, `:57`, `:99`, `:125`, `:136`, `:141`, `:167`, `:178`,
   `:196`), each verified against that file.
   In an entry whose heading names a header and source pair, a bare `:N` is always the header and
   `.cpp:N` is line N of the source: under 2.2's
   `src/layout/layout_common.h / src/layout/layout_common.cpp`, `reject` `:30` is
   `src/layout/layout_common.h:30` and `.cpp:10` is `src/layout/layout_common.cpp:10`. Where an
   entry heading names a `.cpp` and its header and a bare `:N` means the header, the prose says so:
   2.2's `src/layout/block_pack.cpp` writes "Ctor `:41` (header `:64`)" for
   `src/layout/block_pack.cpp:41` and `include/cachesim/layout/block_pack.h:64`.
   A `:N` quoted inside this conventions section is an EXAMPLE of the form, not a citation of
   this file's own: the two above are the only ones, and the sentence resolves both.

> **The reader accepts WCTS version 2 only.** `decode_header` throws `std::invalid_argument` for any
> `format_version` other than 2 and says in the message to regenerate the stream
> (`src/lays/cachesim/native/include/cachesim/trace/stream_format.h:221-228`, `kFormatVersion = 2` at
> `trace/stream_format.h:42`). The writer is `lays.cachesim.stream.stream_weight_trace`
> (`src/lays/cachesim/stream.py:178`), which writes `WCTS_VERSION = 2` (`src/lays/cachesim/stream.py:44`).

There is **no `CMakeLists.txt`**. The native build is `src/lays/cachesim/native/Makefile` (GNU make).

---

## 1. Top-down

### 1.1 Purpose

cachesim is an event-driven, deterministic simulator of the weight-fetch side of a multi-core
accelerator. It reads one layer's weight-access trace (a "WCTS" binary stream of bursts per core per
tile) and replays it through a private L1 per core, one shared banked L2, and a pipelined DRAM
channel, with MSHR files, ports and optional prefetchers. Logical weight coordinates
`[KH][KW][CIN][COUT]` are mapped to cache lines at run time by a swappable `AddressMapper` (four
layouts), so one trace can be replayed under several memory layouts. The output is one CSV row per
configuration (cycles, stretch over the trace's own timeline, hit rates, stall breakdown, prefetch
outcomes, model-health counters). A tile barrier joins all cores between tiles, and each core issues
its next burst at `max(trace gap, core_accept_ii)` after its previous burst was served.

### 1.2 Entry points

**`python -m lays.cachesim {grid, sweep, run}`** (`src/lays/cachesim/__main__.py:1-4` calls `main` in
`src/lays/cachesim/cli.py`):
- `grid --out DIR [--base PATH] [--sweep PATH]`: crosses the base config `examples/cache/base.json`
  with the sweep axes `examples/cache/khkw_sweep.json` (`BASE_JSON`, `SWEEP_JSON`,
  `src/lays/cachesim/grid.py:8-9`) and writes one JSON array per `cin_block` to `DIR/khkw_<k>.json`
  (`write_grid`, `src/lays/cachesim/grid.py:51-65`), printing the paths. Each line size
  `line_bytes` sets `cin_block = line_bytes // (cout_block * weight_bytes)`
  (`src/lays/cachesim/grid.py:30`); a sweep without an `l2_prefetch` key gives points at one line size
  of `l2_banks x prefetch`, banks slowest, each carrying the base config's L2 settings
  (`src/lays/cachesim/grid.py:32-35`); a sweep that declares that key crosses in an L2-prefetch axis as
  well, between the two (`src/lays/cachesim/grid.py:36-41`). With the committed files that is 3 line sizes x 4 banks x 4
  prefetch settings: three files of 16 points (`examples/cache/khkw_sweep.json:2-4`).
- `sweep ARGS...` / `run ARGS...`: runs `src/lays/cachesim/native/build/release/cachesim_sweep` /
  `cachesim_run` with every later argument passed unchanged (`--help` included) and returns its exit
  code; if the binary is missing it first runs `make -C src/lays/cachesim/native MODE=release apps`
  (`native` in `src/lays/cachesim/cli.py`).

Two native programs, both `main()` in `src/lays/cachesim/native/apps/`, sharing `apps/cli_args.h`,
`apps/oracle_io.h`, and `apps/output.h`. Exit codes: 0 ok, 2 usage error (`UsageError`,
`cli_args.h:25-27`), 1 any other exception.

**`cachesim_run`** (`src/lays/cachesim/native/apps/cachesim_run.cpp:458`): one config, one trace, one CSV
row. Flags parsed in `parse_args` (`cachesim_run.cpp:160`); help text `kUsage` (`cachesim_run.cpp:43`).

| flag | default | meaning |
|---|---|---|
| `--config PATH` | required | flat JSON object, `parse_config` |
| `--trace PATH` | required | WCTS v2 stream; `-` = stdin, `fd:N` = open descriptor |
| `--out PATH` | `-` (stdout) | CSV destination (file is truncated, `output.h:133`) |
| `--header` / `--no-header` | **on** (`cachesim_run.cpp:152`) | CSV header line |
| `--arm NAME` | `cache` | one of `cache, spad_oracle, spad_wcache, spad_nocsim` (`cli_args.h:53-59`) |
| `--tier`, `--run-id`, `--git-commit` | empty, random UUIDv4, empty | identity columns |
| `--hist PATH` | off | per-(core,tile) distinct-address CSV |
| `--cache-state PATH` (+`-core/-tile/-limit N`, default -1) | off | every array fill/evict/invalidate |
| `--line-trace PATH` (+`-level l1\|l2\|both` default l1, `-core/-tile/-line/-limit N` default -1) | off | one row per residency episode |
| `--oracle PATH` | off | prior run's access log, builds per-core L1 + shared L2 next-use oracles (Belady) |
| `--l2-oracle PATH` | off | same file, L2 records only; mutually exclusive with `--oracle` |
| `--access-log PATH` | off | binary demand-reference log (input for `--oracle`) |
| `--oracle-only` | off | decode only; row with `total_cycles == tick_base_total`, no engine |

Narrowing flags without their file are refused (`cachesim_run.cpp:203-215`). The header does not
depend on whether `--out` exists, so a rerun to the same path leaves one header and one row (pinned
by `src/lays/cachesim/native/tests/run_cli.sh:203-220`).

**`cachesim_sweep`** (`src/lays/cachesim/native/apps/cachesim_sweep.cpp:262`): one grid, one trace read once,
N engines in lock-step, one row per grid point. Flags (`cachesim_sweep.cpp:94`): `--config-grid PATH`
(required; JSON array of configs, or `{"base":{...},"axes":{key:[values]}}` cross product, first axis
slowest), `--trace` (required), `--out` (`-`), `--header`/`--no-header` (default **on**,
`cachesim_sweep.cpp:88`), `--arm`, `--tier`, `--run-id`, `--git-commit`, `--hist`, `--oracle`,
`--max-engines N` (default 256), `--progress`. No instruments, no `--l2-oracle`, no `--oracle-only`.

**Build targets** (`src/lays/cachesim/native/Makefile`): `make` = `lib apps` in `build/fixture` (`-O0 -g`,
asserts live); `make test` = compile-fail driver + every `tests/test_*.cpp` binary;
`make test-cli` = builds apps, runs `run_cli.sh`, `sweep_cli.sh`, `v1_pipe.sh`, `cout_golden.sh`
(`Makefile:143-147`, needs python3); `make test-run` = test binaries only; `make release` =
**library only** (`libcachesim.a`, `Makefile:46`) in `build/release` (`-O2 -DNDEBUG`,
`Makefile:182-183`); `make MODE=release apps` builds the release programs that `python -m lays.cachesim`
runs; `make clean`.

### 1.3 Data flow (one `cachesim_run`)

Inputs come from two Python producers. The configs: `python -m lays.cachesim grid` turns
`examples/cache/base.json` and `examples/cache/khkw_sweep.json` into grid files (1.2); `cachesim_run`
takes one object, `cachesim_sweep` a whole file. The trace: `python -m lays.weight_trace_gen gen --stream`
writes one layer-sample as a WCTS stream on stdout (`--stream` flag
`src/lays/weight_trace_gen/cli.py:383`, `emit_stream` `src/lays/weight_trace_gen/cli.py:280`, which calls
`lays.cachesim.stream.stream_weight_trace` at `src/lays/weight_trace_gen/cli.py:290`), and
`python -m lays.cachesim sweep --config-grid GRID --trace STREAM` replays it.

1. **Config text -> `RunConfig`**: `parse_config` (`src/lays/cachesim/native/src/config.cpp:419`), a strict
   JSON subset (integers and quoted strings only, unknown or duplicate key = error).
2. **Trace bytes -> `StreamHeader`**: `TraceFd` (`apps/cli_args.h:77-102`) -> `FdByteSource`
   (`include/cachesim/trace/byte_source.h:51`) -> `StreamingTileTrace` ctor reads and validates the header
   (`src/trace/stream_trace.cpp:26`, `decode_header` at `trace/stream_format.h:208`).
3. **Header -> `WeightShape`** via `shape_of` (`src/trace/stream_trace.cpp:354`).
4. **Validation**: a `BlockPackMapper` "probe" computes `lines_per_burst` (`apps/output.h:38-44`), then
   `validate(cfg, lines_per_burst, warnings)` (`src/config.cpp:542`) resolves the `-1` sentinels
   (`l1_demand_reserve`, `l2_demand_reserve`, `cin_lo_blocks`, `l2_policy`) and refuses bad configs.
5. **Mapper**: `make_mapper` (`include/cachesim/layout/factory.h:12-14`, `src/layout/factory.cpp:32-66`) builds
   `BlockPackMapper` / `SplitCinMapper` / `KhkwSplitMapper` /
   `CinKhkwConcatMapper` -> `const AddressMapper&`. All four share `src/layout/layout_common.h`.
6. **`RunConfig` -> `EngineParams`**: `to_engine_params` (`src/config.cpp:793`) -> two `LevelParams`.
7. **Engine**: `Engine(mapper, trace, params)` (`src/core/engine.cpp:58`) builds N L1 `CacheLevel`s, one L2
   `CacheLevel`, a DRAM `Port`, and one level-owned `Prefetcher` per `CacheLevel`.
8. **Tile loop** (`cachesim_run.cpp:395-404`): `trace.advance()` decodes tile N into the one-tile window
   -> `DistinctAddressHistogram::observe`, `PaddingMeter::observe_tile` -> `engine.run_to_barrier()`
   runs events until tile N's barrier is next; then `engine.finish()`.
9. **Stats -> CSV**: `RunStats(id, cfg, hdr, engine.stats(), tile_origin(n_tiles), tick_base(n_tiles),
   padding, wall, hist.p50, hist.max)` (`src/instrument/stats.cpp:243-247`), `check_invariants()`, `csv_row()`;
   `write_out` (`apps/output.h:127-136`).

`cachesim_sweep` is the same with steps 4-9 per grid point, `BroadcastSweep` (`src/sweep.cpp:32`)
driving all engines over one window (`src/sweep.cpp:112`).

**Upstream connection (visible in code).** The WCTS writer is `src/lays/cachesim/stream.py` (2.5). The
pieces that fix the wire format: `WCTS_VERSION = 2` (`src/lays/cachesim/stream.py:44`),
`WCTS_ADDR_FIELDS = (0, 1, 2, 3, 4)` (`:53`), `write_stream_header` (`:57`), `write_tile_frame` (`:99`,
refuses a run that is empty along `burst_dim` at `:125`), `write_stream_trailer` (`:136`),
`_wcts_tile_frames` (`:141`, measures `burst_span` as the largest `cout_end - cout_start` at `:167`)
and `stream_weight_trace` (`:178`, refuses any `burst_dim != 3` at `:196`). `scripts/pipeline.py`
writes each layer-sample's stream to a `.wcts` file with `python -m lays.weight_trace_gen gen ... --stream`
and runs `python -m lays.cachesim sweep` on it once per grid file. `--access-log` output is read back
only by `--oracle` / `--l2-oracle` (`read_oracle_lines`, `apps/oracle_io.h:46-88`).

### 1.4 Key abstractions

```
             WCTS bytes                         RunConfig --validate--> EngineParams
                 |                                                           |
   ByteSource -> StreamingTileTrace : TileTrace           AddressMapper (BlockPack|SplitCin|KhkwSplit|CinKhkwConcat)
                 |   (one-tile window)                         |   expand(Burst)->[LineId]
                 v                                             |   locate(LineId,num_sets)->Placement
              Engine  <-----------------------------------------+   neighbour(line,axis,d)
   EventQueue<EventPayload> (total order: time,class,age,core,seq)    (expand/locate/checks shared
     |-- cores_[c] : CoreState (cursor, pending_lines, phase)          via src/layout/layout_common.h)
     |-- l1_[c] : CacheLevel ----+-- SetAssociativeArray : CacheArray (slots_[] of LineId)
     |-- l2_    : CacheLevel     +-- ReplacementPolicy (LRU|FIFO|Belady|LFU|RRIP), sized by num_slots
     |                           +-- Port[banks] (ii, latency)
     |                           +-- MshrFile (entries_ line->Mshr, slot_wait_, RefusalCounter&)
     |                           +-- NextUseOracle* (Belady only)
     |-- dram_ : Port
     |-- each CacheLevel.prefetcher_ : Prefetcher (None|NextAccess|Neighbour)
     |-- optional: CacheStateLog*, LineTrace*, AccessLog*   (observers, never change results)
     `-- stats_ : EngineStats  --> RunStats --> CSV row
```

The `Request` (one line of one burst, `include/cachesim/core/request.h:43`) is the unit that travels. It lives
in `Engine::arena_` (a `std::deque`, stable addresses) with a free list (`core/engine.h:644,662`). An
`Mshr` (`core/mshr.h:48`) is one outstanding line per level; `targets` are satisfied directly by the
fill, `line_wait` are requests that found the target list full.

Strongly typed scalars (`include/cachesim/types.h`): `LineId`, `CoreId`, `SlotId`, `SetIndex`,
`TagId`, `BurstIndex`, `SimTime`, `LocalTick`, `RefusalOrder`, `EventSeq` are distinct
`Tagged<Rep,Tag>` types with no default constructor and no narrowing constructor, so mixing them is
a compile error (checked by `tests/compile_fail.sh`).

### 1.5 One run, step by step (engine semantics)

Times are integer cycles (`SimTime`). Trace ticks (`LocalTick`) are offsets inside a tile.

1. `run_to_barrier` first call (`src/core/engine.cpp:148`): `tile_origin[0]=0`, `start_tile(0, 0)`.
2. `start_tile(t, now)` (`src/core/engine_core.cpp:55`): every core reset (cursor 0, phase Computing),
   each level's prefetcher reset; a core with 0 bursts arrives at the barrier at once; otherwise an `Issue`
   event is scheduled at `now + local_tick(core, t, 0)` (the only absolute tick used).
3. `on_issue` (`src/core/engine_core.cpp:156`): checks `k == cursor` and `pending_lines == 0`; `expand`
   turns the burst into sorted distinct lines; `pending_lines = #lines`, phase Stalled; per line a
   demand `Request` reserves the L1 port and schedules `L1Probe` at `accept + l1_latency`. Then the
   L1 prefetcher is asked for ordered `PrefetchTarget`s below the demand port.
4. `on_l1_probe` (`src/core/engine.cpp:274`) -> `CacheLevel::triage` (`src/core/cache_level.cpp:115`), probe
   order **array -> own MSHR -> MSHR pool**:
   - Hit: policy `on_hit`; `core_line_done`; request released.
   - Merged (entry exists, target list not full): subscribes, nothing scheduled.
   - BlockedTargets / BlockedPool: put on that entry's `line_wait` / the file's `slot_wait`, stamped
     with a global refusal counter value on first refusal (write-once).
   - Forwarded (allocated a new entry): request now holds the L1 entry (`mshr1`, `level = L2`), L2
     bank port reserved, `L2Probe` at `accept + l2_latency`.
   - A prefetch at issue is **dropped**, never queued: `DroppedArrayHit/Entry/NoSlot/Reserve`.
5. `on_l2_probe` (`src/core/engine.cpp:459`): same triage at L2. Hit -> `L1Fill` at `now +
   l2_to_l1_latency`. Forwarded -> `dram_.reserve(now)` -> `L2Fill` at `accept + l2_miss_latency`.
   An L2 demand miss (or demand hit on an L2-prefetched line) asks the L2 prefetcher for targets.
6. `on_l2_fill` (`src/core/engine.cpp:612`): install in L2 (free way first, then policy victim);
   back-invalidate the victim from every L1 if `inclusive`; retire the L2 entry; every target with an
   L1 entry gets `L1Fill` at `now + l2_to_l1_latency`; woken requests re-enter through their port.
7. `on_l1_fill` (`src/core/engine.cpp:683`): install in L1, update prefetch outcome bookkeeping, clear
   `mshr1` on every target, retire the L1 entry, `core_line_done` per demand target, return the
   prefetch credit per prefetch target, reinject wake list.
8. `core_line_done` (`src/core/engine_core.cpp:229`): `--pending_lines`; at 0 the burst is served
   (bursts are atomic) and the last line's `StallCause` is charged.
9. `serve` (`src/core/engine_core.cpp:251`): `want = tile_origin[t] + local_tick(0)` for burst 0, else
   `served_time + max(gap(k-1), core_accept_ii)`; `stall = now - want` (throws if negative);
   `fetch_latency += now - burst_anchor`. Next `Issue` at `now + max(gap(k), core_accept_ii)`, or
   barrier arrival after the last burst.
10. `barrier_arrive` (`src/core/engine_core.cpp:95`): countdown; the last core schedules `Barrier` at
    `now + tile_tail(t)` (`tile_tail = mac_cycles - max_tick`, must be >= 1).
11. `run_to_barrier` returns *before* dispatching a Barrier, so the driver can advance the shared
    window; the next call dispatches it. `on_barrier` (`src/core/engine_core.cpp:114`) sets
    `tile_origin[t+1] = now`, charges barrier slack per core, and starts tile t+1 or marks all Done.
12. When the queue empties: L1 prefetched-but-unused lines are charged as wasted (L2 ones are not,
    finding H4), then `check_no_work_outstanding` throws on any deadlock (`src/core/engine.cpp:190`).

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
| `layout` | `block_pack` (`split_cin`, `khkw_split`, `cin_khkw_concat`) | `l2_tgts_per_mshr` | 12 |
| `cin_lo_blocks` | -1 (= L1 sets, split_cin only) | `l1_demand_reserve` | -1 (= lines_per_burst) |
| `l1_size_bytes` | 8192 | `l1_latency` | 0 |
| `l1_assoc` | 8 | `l1_ii` | 1 |
| `l2_size_bytes` | 524288 | `l2_latency` | 10 |
| `l2_assoc` | 16 | `l2_to_l1_latency` | 0 |
| `policy` | `lru` (`fifo`,`belady`,`rrip`,`lfu`; `random` refused) | `l2_miss_latency` | 100 |
| `l2_policy` | unset -> `policy` | `l2_banks` | 1 |
| `rrip_bits` | 2 (1..8) | `l2_ii`, `dram_ii`, `core_accept_ii` | 1, 1, 1 |
| `inclusion` | `non_inclusive` (`inclusive`; `exclusive` refused) | `prefetch_policy` | `none` (`next_access`, `neighbour`) alias for L1 |
| `l1_prefetch_policy` | `none` (`next_access`, `neighbour`/`neighbor`) | `prefetch_distance` / `l1_prefetch_distance` | 0 |
| `l1_prefetch_axis` | `cin` (`cout`,`kh`/`pos`,`kw`) | `l1_prefetch_up` / `_down` | 1 / 1 (integers) |
| `l2_prefetch_policy` | `none` (`next_access`, `neighbour`/`neighbor`, `distance_aware`) | `l2_prefetch_distance` | 1 |
| `l2_prefetch_axis` | `cin` (`cout`,`kh`/`pos`,`kw`) | `l2_prefetch_up` / `_down` | 1 / 1 (integers) |
| `l2_demand_reserve` | -1 (= lines_per_burst) |  |  |

Derived: `line_size_bytes = cin_block*cout_block*weight_bytes`; `l{1,2}_num_lines = size/line`;
`num_sets = num_lines/assoc` (`src/config.cpp:409-415`). Warnings returned by `validate`:
`W_MSHR_VS_LINES`, `W_FEW_SETS`, `W_CIN_LO_VS_SETS`, `W_PREFETCH_BUDGET`, `W_ZERO_II`
(`src/config.cpp:745-789`); `make_mapper` adds `W_CIN_LO_UNREACHABLE` (`src/layout/factory.cpp`).

The L2 MSHR floor: with `l2_demand_reserve` unset it resolves to `lines_per_burst`
(`config.cpp:706`) and must stay below `l2_mshrs` whatever the L2 prefetch policy is
(`config.cpp:711-715`). With the default `l2_mshrs = 20`, a 19-line burst passes and a 20-line burst
is refused; `tests/test_config.cpp:211` pins both and pins that the message does not mention
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

Paths below are under `src/lays/cachesim/native/` unless a full path is given. Inside an entry, a bare `:N`
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

**include/cachesim/layout/mapper.h**
- `enum class LayoutKind {BlockPack, SplitCin, KhkwSplit, CinKhkwConcat}` `include/cachesim/layout/mapper.h:43`.
- `struct Placement {SetIndex set_index; TagId tag;}` `:75`; identity `line == tag*num_sets + set`.
- `class AddressMapper` `:87` (abstract). Error vocabulary: `invalid_argument` malformed,
  `out_of_range` outside the layer, `logic_error` programmer error (`:91-106`).
  - `expand(const Burst&, vector<LineId>& out)` `:157`: APPENDS this burst's distinct lines, strictly
    increasing within one call; `count<1` or `stride<1` throws; all checks before the first append.
    The comment above it (`:110-114`) names the v2 record for a CIN burst.
  - `locate(LineId, int64 num_sets) -> Placement` `:167`: range-checks before dividing.
  - `neighbour(LineId, Axis, int32 delta) -> optional<LineId>` `:184`: step `delta` BLOCKS along an
    axis, `nullopt` if it leaves the layer.
  - `num_lines()` `:187` (one past max id), `line_size_bytes()` `:193`,
    `line_size_terms(int64)` `:220` (diagnostic, default prints the number).

**index/cache_array.h**
- `struct Candidate {SlotId slot; LineId line;}` `index/cache_array.h:38` (line = NoLine if free).
- `struct InsertResult {bool evicted; LineId evicted_line;}` `:51`.
- `class CacheArray` `:68`: `probe` `:79` (const, not an access), `free_slot` `:84`,
  `victim_candidates` `:102` (REPLACES `out`), `insert` `:107`, `invalidate` `:121`,
  `num_slots` `:132`. Copy/move protected (`:162-166`).

**replacement/policy.h**
- `class ReplacementPolicy` `replacement/policy.h:38`: `on_hit` `:51`, `on_fill` `:59`, `on_invalidate` `:65`,
  optional `note_next_use(slot, next_use)` `:82` (default no-op; called right before
  `on_fill`/`on_hit` when an oracle is attached), optional `note_protected(slot, is_protected)`
  `:97` (default no-op, for the same reason; `pf_lru` is the only policy that reads it),
  `pick_victim(candidates)` `:122` (must not depend on
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
- `struct Request` `core/request.h:43`: `core, line, burst` `:44-46`; `demand(=true)` `:48-52`;
  `issued_at` `:54-58`; `refusal(=NoRefusal)` `:60-64`; `reason` `:66-74`; `level(=L1, where to
  RE-ENTER)` `:76-77`; `mshr1` (L1 entry once forwarded) `:79-87`; `reserved` `:89-92`,
  `on_wait_index` `:94-111`, `cause` `:113-114`, and `line_resident_at_wake` `:116-124`.

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
- `enum class PolicyKind {LRU, FIFO, RANDOM, BELADY, RRIP, LFU}` `:145`.
- `make_policy(kind, num_slots, rrip_bits=2)` `:161-162`.
**replacement/next_use.h** (header-only)
- `class NextUseOracle` `replacement/next_use.h:39`: `kNever`=INT64_MAX `:41`; ctor from a reference sequence
  (one backward pass, then grouped by line) `:45`; `next_use(line, occurrence)` `:73` returns the
  position of the next reference after the `occurrence`-th one, or kNever and counts an overrun;
  `references` `:83`, `distinct_lines` `:84`, `overruns` `:85`; `optimal_hit_rate(lines, n_lines)`
  `:92` (fully-associative MIN, O(n * capacity)).

**prefetch/prefetcher.h**
- `PrefetchContext` `prefetch/prefetcher.h:37` carries level, core, tile, burst, triggering line,
  time, mapper and trace; `PrefetchTarget` `:53-58` carries a line and its burst tag.
- `PrefetchKind {None, NextAccess, Neighbour, DistanceAware}` `:61` and `PrefetchParams` `:63-71` are shared by
  both levels. `Prefetcher` `:74` has `on_tile_start` `:80`, ordered `on_demand` `:85`, and
  `on_issued` feedback `:90`; `make_prefetcher` `:112-114` constructs the selected policy.
- `none.h`: `NoPrefetcher` `:7-10`; `next_access.h`: `NextAccessPrefetcher(distance>=1, n_cores)`
  `:14-30` with per-core `pf_cursor`; `neighbour.h`: `NeighbourPrefetcher(axis, distance>=1,
  up, down)` `:9-25`; `distance_aware.h`: `DistanceAwarePrefetcher(distance>=1, min_touches=0)`
  `:21-30`, which keeps per-line touch records for the touch filter (`:33-41`) and is
  fixed to `Axis::COUT` forward, which the header states ignores `axis`, `up` and `down` `:10-11`.

**core/cache_level.h**
- `enum class TriageOutcome {Hit, Merged, BlockedTargets, BlockedPool, Forwarded, DroppedArrayHit,
  DroppedEntry, DroppedNoSlot, DroppedReserve}` `core/cache_level.h:76`; `is_dropped` `:90`.
- `struct LevelParams` `:107`: `cache_size_bytes, associativity, policy, rrip_bits, latency, ii,
  banks, bank_high_bits, mshrs, tgts_per_mshr, demand_reserve`, plus `prefetch_kind` and
  `prefetch_params` `:139-140`.
- `class CacheLevel` `:143`: ctor `(Level, mapper, LevelParams, RefusalCounter&, n_cores)` `:156-160`;
  `triage(r, granted)` `:182`; `install(line)` `:206`; `bank_of(line)` `:215`; `level`, `array`,
  `policy` `:217-220`; `prefetcher` `:234-235`; `attach_next_use(oracle)` `:248`,
  `next_use_oracle` `:249`; `mshrs` `:250-251`; `port(bank)` `:252`; `banks` `:253`;
  `num_sets` `:254`. Holds Belady
  occurrence counters `occurrence_` and `pending_next_use_` (`:266,272`).

**core/engine.h**
- `enum class Inclusion {NonInclusive, Inclusive}` `core/engine.h:60`; `enum class Phase {Computing,
  Stalled, AtBarrier, Done}` `:77`.
- `struct CoreState` `:86`: `tile, cursor, phase, pending_lines, burst_anchor,
  barrier_arrival, served_time`.
- `struct EngineStats` `:134`: per-core vectors `core_stall, fetch_latency, stall_l1_slot ...
  stall_barrier, stall_total, pf_outstanding`; scalar counters for prefetch outcomes (L1 `:200-217`,
  L2 `:247-278`), `l1/l2_hits/accesses` `:242-243`, `dram_accesses` `:279`, health counters
  `hits_downgraded_to_miss, max_wait_depth, events` `:286,290,294`, MSHR occupancy samples `:299-300`.
- Comments on the L2 block: the outcomes plus drops sum to **at most** `l2_pf_issued`
  because L2 lines still tagged at end of run are not charged (`:249-250`), and that bound is the
  whole of the slack: the tag is set only behind the L2-originated gate at the L2 fill
  (`src/core/engine.cpp:626-628`), so no L1 prefetch fill reaches these counters and the sum cannot
  exceed `l2_pf_issued` (H4 in 3.3; the guard is `src/instrument/stats.cpp:445-452`). Also
  `l2_pf_timely` equals `l2_pf_retriggers` in MISS mode only (`:257-258`, `:268-273`): both are
  incremented at one site, `src/core/engine.cpp:528-530`, but the retrigger half sits behind an
  `if (miss_mode)` guard `:529`, and in TOUCH mode a second site counts `l2_pf_timely` with no
  retrigger at all (`:536-547`), so a touch-mode row reads `l2_pf_retriggers = 0` while
  `l2_pf_timely` counts. `src/instrument/stats.cpp:353` still carries the unqualified
  "always equals" comment.
- `struct EventPayload {Request* req; Mshr* entry; BurstIndex burst; int32 tile;}` `:318`;
  `using EngineQueue = EventQueue<EventPayload>` `:325`.
- `struct EngineParams` `:341`: `l1, l2` LevelParams, `l2_to_l1_latency, dram_ii, l2_miss_latency,
  `core_accept_ii`, `inclusion`, and source-compatible L1 aliases `prefetch_policy/distance` plus
  `l2_prefetch_*`. No validation by design.
- `class Engine` `core/engine.h:383`: ctor `:390`; `run` `:399`; `run_to_barrier` `:420`
  (returns pending barrier's tile or -1); `step_tile` `:432`; `finish` `:444`; `tile_origin(t)` `:450`
  (size n_tiles+1); `core` `:452`; `stats` `:453`; `queue` `:454`; `l1(c)` `:456`; `l2` `:457`;
  `set_cache_state_log` `:473`, `set_line_trace` `:474`, `set_access_log` `:480`; `n_bursts_in_tile`
  `:487`. Private section from `:489`: the six event handlers `:495-500`, then helpers and scratch members.
- `as_duration(LocalTick) -> SimTime` `:690`: the one trace-gap-to-duration crossing.

**config.h**
- `struct RunConfig` `config.h:27` (fields in 1.6) with `line_size_bytes, l1_num_lines, l1_num_sets,
  l2_num_lines, l2_num_sets` `:132-136`. The `rrip_bits` comment (`:53-57`) and the `l2_policy`
  comment (`:59-65`) sit above their own fields; `l2_policy_set` reads "true when l2_policy was
  given explicitly" (`:67`).
- `struct Warning {code, message}` `:142`.
- `parse_config(json)` `:155` (its comment `:150-151` calls `l2_demand_reserve` an ordinary key),
  `parse_config_grid(json)` `:176`, `validate(cfg&, lines_per_burst, warnings&)` `:186` (mutates
  cfg), `to_engine_params(cfg)` `:191`.

**trace/stream_format.h** (namespace `cachesim::stream`, header-only; file comment `:1-3` says WCTS v2 and
`:10-12` names `src/lays/cachesim/stream.py` as the producer)
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
  non-COUT anchor and to regenerate with `src/lays/cachesim/stream.py`. `burst_span >= 1` is the only check on
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

**include/cachesim/instrument/access_log.h** (header-only)
- `struct AccessRecord {u8 level, core, demand, pad; u32 line}` `include/cachesim/instrument/access_log.h:63`, 8 bytes
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
- `class RunStats` `:69`: ctor `:71`, `csv_row` `:80`, `check_invariants` `:94`.
- `oracle_row(id, cfg, hdr, tick_base_total)` `:115`.

**sweep.h**
- `class BroadcastSweep` `sweep.h:31`: `TileObserver` `:37`; ctor `(trace, mapper, configs,
  max_engines)` `:53`; `run(on_tile)` `:60`; `size` `:62`; `engine(i)` const `:63` / mutable `:71`;
  `config(i)` `:72`; `wall_seconds(i)` `:77` (time inside engine dispatch only).

**enum_names.h** (header-only)
- `kUnknownEnumName` `include/cachesim/enum_names.h:15` is the sentinel shared with the CSV guard;
  the five overloaded `name_of`/`parse` pairs `:17-110` are the single source for `LayoutKind`,
  `PolicyKind`, `PrefetchKind`, `L2Trigger` and `Inclusion` used by config parsing, CSV emission,
  and sweep
  diagnostics. Their invalid-enum fallbacks return the sentinel at `:24`, `:47`, `:70`, `:87` and
  `:102`.

**layout mappers**: see 2.2 with their sources (`include/cachesim/layout/block_pack.h`, `include/cachesim/layout/split_cin.h`, `include/cachesim/layout/khkw_split.h`, `include/cachesim/layout/cin_khkw_concat.h`) and
the shared `src/layout/layout_common.h`.

### 2.2 `src/` (library `libcachesim.a`)

**config.cpp**
- `fail(what, pos)` `config.cpp:30`: `invalid_argument("config: ... at byte N")`.
- `struct Value` `:34`; `class Reader` `:40` (`skip_space`, `at`, `expect`, `expect_end`, `pos`,
  `read_string` (no escapes) `:71`, `read_value` (integer or string; rejects `.`/`e`) `:86`).
- Key tables `kI32Fields` `:136` (`l2_demand_reserve` at `:148`), `kI64Fields` `:154`; `to_i32`
  `:168`, `to_i64` `:177`, `enum_text` `:182`.
- `assign(cfg, key, value, pos)` `:187`: the single key dispatcher used by both parsers (comment
  `:188-189` describes the table lookup); the hand-written branches after the tables - the enum
  keys, the `prefetch_distance`/`l1_prefetch_distance` alias and the two L2 direction booleans -
  are `:203-322`; unknown key fails `:324`.
- `reject` `:329`, `reject_below_one` `:333`, `reject_negative` `:339`, `check_level_geometry`
  `:345` (size >= one set, whole lines, whole sets), `warn` `:364`.
- `read_object_into(reader, cfg)` `:373` (duplicate keys refused); `struct GridAxis` `:399`.
- `RunConfig::line_size_bytes` etc. `:409-415` (integer division; validated later).
- `parse_config` `:419`; `parse_config_grid` `:429` (array form `:433-449`; base/axes form
  `:457-518`; mixed-radix enumeration with last axis fastest `:520-537`).
- `validate` `:542`: alias synchronization `:543-560`; positivity `:562-581`; geometry and
  `cin_lo_blocks` `:583-609`; `l2_policy` follows `policy` if unset `:611`; random refused
  `:618-629` (the same lambda re-checks `policy` `:636`, and `pf_lru`/`pf_lru_rand` are refused
  as an L1 policy `:643-647`); rrip_bits in [1,8] `:633-634`;
  `lines_per_burst <= l1_mshrs` `:648-650`;
  `core_accept_ii >= 1` `:652-654`; L1/L2 prefetch distance and direction checks `:656-732`,
  among them `distance_aware` refused at distance 0 `:671-674` and refused as an L1 policy at all
  `:718-720`; `l2_demand_reserve` resolved to lines_per_burst and must be `< l2_mshrs` `:703-715`;
  `l1_demand_reserve` resolved and must be `< l1_mshrs` `:734-743`; warnings `:745-789`.
- `to_engine_params` `:793`: copies both levels' prefetch kind/axis/distance/directions and the
  legacy aliases; throws if not validated.

**core/engine.cpp** (loop, memory-side handlers, inclusion, instruments)
- anonymous `engine_error` `:18`, `idx` `:22`, `is_blocked` `:52`.
- `Engine::Engine` `:58`: needs n_cores >= 1; `l1_.reserve` before emplace (CacheLevel holds refs)
  `:70-77`; sizes per-core stats; `tile_origin_` sized n_tiles+1 `:104`.
- `tile_origin` `:107`, `core` `:111`, `l1` `:113`.
- `acquire` `:117` (reuse from free list, whole-struct assign), `release` `:132` (throws if still
  referenced).
- `run_to_barrier` `:148`, `run` `:176` (= loop of run_to_barrier), `step_tile` `:181`, `finish`
  `:183` (= run), `check_no_work_outstanding` `:190`, `dispatch` `:216` (increments `events`).
- `reinject` `:237` (re-enters at `r.level` through that level's port, keeps original stamp),
  `reinject_all` `:258`.
- `on_l1_probe` `:274`, `prefetch_on_demand` `:376` (applies ordered targets through the selected
  level's budget/port/triage path), `on_l2_probe` `:459` (the one site that increments both
  `l2_pf_timely` and `l2_pf_retriggers`, `:528-530`, the retrigger half under `if (miss_mode)`),
  `on_l2_fill` `:612` (L2 tag set behind the
  L2-originated gate, `l2_prefetched_` update `:622-645`), `on_l1_fill` `:683`.
- Prefetch accounting: `demand_anchor_on_probe` `:752` (timely / pollution), `note_prefetch_resident`
  `:776`, `note_line_left_l1` `:780` (wasted), `close_out_prefetch_stats` `:788` (L1 only; the
  comment `:800-802` says so).
- Instruments: `current_tile` `:812` (core 0's tile), `way_of` `:816` (`slot % assoc`), `note_fill`
  `:831`, `note_leave` `:845`, `note_hit` `:856`.
- `back_invalidate(line, now)` `:866`, under its section header `:864`:
  scans all L1s by core id, invalidates + `on_invalidate`.

**core/engine_core.cpp** (core state machine and barrier)
- `step_after(c, tile, k)` `:48` = `max(gap_k, core_accept_ii)`.
- `start_tile` `:55` resets every level-owned prefetcher per core; `barrier_arrive` `:95`,
  `on_barrier` `:114`, `on_issue` `:156` (re-throws a mapper `out_of_range` with tile/tick/core/burst
  context `:195-198`), `core_line_done` `:229` (prefetch completes nobody), `serve` `:251`.
- `on_issue` asks the L1 prefetcher once per expanded demand line (`:220-226`); the common issue
  mechanics live in `Engine::prefetch_on_demand` (`src/core/engine.cpp:376-455`). `n_bursts_in_tile`
  remains the compatibility query at `src/core/engine_core.cpp:346-349`.

**core/cache_level.cpp**
- `refuse_if_waiting` `:32`; `charge_path(r, cause)` `:48` sets cause only if never refused.
- `CacheLevel::CacheLevel` `:54`: array first, then `make_policy` sized by `num_slots`, then
  `banks` ports; `sets_per_bank` clamped >= 1 `:95-96`.
- `bank_of` `:102`: 1 bank -> 0; else low bits `set % banks` or high bits `set / sets_per_bank`.
- `triage` `:115`: Belady occurrence consumed on every demand probe `:137-144`; array hit `:146-170`
  (a hit also ends prefetch protection with `note_protected(slot, false)` `:162`);
  matching entry `:172-196`; no slot `:198-214` (prefetch: DroppedReserve if free > 0 else NoSlot);
  primary miss `:216-228`.
- `install` `:231`: throws if already resident; free slot first, else `pick_victim`; passes the
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
- `make_policy` `replacement/policy.cpp:22` constructs the selected concrete policy and rejects RANDOM.

**replacement/stamp.cpp**
- `StampPolicy` constructor `replacement/stamp.cpp:19`, bound check `:28`, stamp/fill/invalidate/victim
  operations `:36-61`; LRU/FIFO hit behavior `:63-65`.

**replacement/belady.cpp**
- `BeladyPolicy` constructor `replacement/belady.cpp:18`, bound check `:26`, next-use notifications `:45-47`,
  maximum-next-use victim selection `:49`.

**replacement/lfu.cpp**
- `LfuPolicy` constructor `replacement/lfu.cpp:17`, count updates `:35-41`, victim selection `:43`.

**replacement/rrip.cpp**
- `RripPolicy` constructor `replacement/rrip.cpp:19`, RRPV updates `:45-53`, uniform aging and tie-break
  in `pick_victim` `:55-71`.
**prefetch/**
- `prefetcher.cpp`: `make_prefetcher` `:13-32` constructs `NoPrefetcher`, `NextAccessPrefetcher`,
  `DistanceAwarePrefetcher`, or `NeighbourPrefetcher` from the shared `PrefetchKind`/`PrefetchParams`;
  the `DistanceAware` case passes `params.distance` alone `:25-26`, where the `Neighbour` case passes all
  four fields `:27-29`.
- `next_access.cpp`: ctor `:9`, `pf_cursor` `:25`, `on_tile_start` `:29` (cursor 0), `on_demand`
  `:36` expands ordered bursts while `cursor <= k+d` and `< n_bursts`; a budget-exhausted burst
  leaves the cursor there until the next demand pulls it past the core's current burst; `on_issued`
  `:66` advances only after a complete burst.
- `neighbour.cpp`: ctor `:8`, `on_demand` `:22` emits nearest `+1, -1, +2, -2, ...` targets
  through `mapper.neighbour`; `none.cpp` is the split source for the no-op implementation.
- `distance_aware.cpp`: ctor `:9` refuses `distance < 1` `:11-14` and `min_touches < 0` `:15-18`;
  `on_access` `:21` is the touch counter, one `TouchRecord` per line reset on a tile change, and it
  returns true on the `max(min_touches, 1)`-th touch of the tile `:28`; `on_demand` `:31` applies
  the touch filter first - skipped for a retrigger and when `min_touches == 0`, and a line below
  the threshold increments `filtered_` and emits nothing `:33-41` - then emits
  `mapper.neighbour(line, Axis::COUT, i+1)` for `i = 0 .. distance-1` `:42-46`, keeping `ctx.k` as
  the burst tag and skipping a `nullopt` target. At distance 1 and `min_touches 0` this is the
  `neighbour` stream with
  axis `cout` and `down` off, with the axis and direction fixed in the type instead of in config.

**index/set_index.h**
- `set_index(LineId, num_sets) -> Placement` `index/set_index.h:14`: shared modulo mapping, with
  `set = line % num_sets` and `tag = line / num_sets`; malformed set counts and negative line ids are refused.

**src/layout/layout_common.h / src/layout/layout_common.cpp** (namespace `cachesim::detail`, private to
`src/`, not installed under `include/`)
- The four mappers share argument checks, shape validation, burst walking and line-size diagnostics;
  each mapper keeps its own flatten, placement call and `neighbour`.
- `kAxes[4]` `src/layout/layout_common.h:28`; `reject` `:30` / `.cpp:10` (`invalid_argument`),
  `reject_range` `:31` / `.cpp:14` (`out_of_range`); `positive_or_reject` `:36`;
  `checked_mul` `:43` / `.cpp:18`; `blocks_covering` `:48`; `block_size_on` `:56`.
- `check_shape_and_blocking` `:72` / `.cpp:26`, `line_size_bytes` `:80` / `.cpp:41`,
  `check_in_shape` `:87`, `expand_burst<Mapper>` `:120-148`, and `line_size_terms` `:154` / `.cpp:47`.
**include/cachesim/layout/factory.h / src/layout/factory.cpp**
- `make_mapper(cfg, shape, warnings)` is the library-owned layout factory. It builds the selected
  mapper and emits `W_CIN_LO_UNREACHABLE` for a SplitCin width above the layer's CIN-block count;
  both native drivers call this same function after validation.
**src/layout/block_pack.cpp** (`BlockPackMapper`, header `include/cachesim/layout/block_pack.h:42`; 241 lines)
- Nesting `[KH][KW][cin_blk][cout_blk]`, cout innermost; `kName` `src/layout/block_pack.cpp:15`; Axis-order `static_assert`s
  `:34-37`.
- Ctor `:41` (header `:64`): `check_shape_and_blocking` `:58`; block counts `:64-65`;
  `line_size_bytes_` `:78`; `num_lines = KH*KW*ncb*nkb` via `checked_mul` `:92-95`; strides
  `:119-125` (COUT 1, CIN `n_cout_blocks`, KW `n_cin_blocks*n_cout_blocks`, KH `KW*stride_KW`).
- `line_stride(Axis)` `:137`, `block_len(Axis)` `:153` (KH,KW raw; CIN,COUT block counts),
  `line_of(Coord)` `:163` (`check_in_shape` `:170`, then one loop over `kAxes` `:178-186`),
  `expand` `:201` (= `detail::expand_burst`), `locate` `:207` (= `set_index`),
  `line_size_terms` `:218`, `neighbour` `:226`. Accessors in header `:159-164`.

**src/layout/split_cin.cpp** (`SplitCinMapper`, header `include/cachesim/layout/split_cin.h:110`; 339 lines)
- Nesting `[KH][KW][cin_hi][cout_blk][cin_lo]`, `cin_lo = cin_blk % n_cin_lo` innermost, so with
  `n_cin_lo = L1 sets` the L1 set index is the CIN digit. `enum Digit` header `:99`;
  `static_assert`s on Digit order `:22-26`; `kName` `src/layout/split_cin.cpp:14`.
- `ceil_div` `:32` (int64 ceiling, see 3.2 item 1).
- Ctor `:38` (extra arg `n_cin_lo >= 1`, `:60`); `n_cin_hi = ceil(ncb / n_cin_lo)` `:70`;
  `radix_product` as an overflow guard `:100-106`; strides `:128-137`; `num_lines` = max id + 1
  `:156-161`, may be below the radix product (holes when n_cin_lo does not divide ncb), sanity check
  `:168-172`.
- `digit_stride` `:182`, `digit_radix` `:194`, `block_len` `:211`, `line_of` `:223` (the only cin
  split `:243-244`), `expand` `:276` (= `detail::expand_burst`), `locate` `:287`, `line_size_terms`
  `:300`, `neighbour` `:306` (CIN step recombines the two digits, `:333-336`). Accessors header
  `:189-196`.

**src/layout/khkw_split.cpp** (`KhkwSplitMapper`, header `include/cachesim/layout/khkw_split.h:70`; 192 lines)
- Nesting `[pos_hi][cout_blk][cin_blk][pos_lo]`, `pos = kh*KW + kw`, split at `n_pos_lo =
  min(kPosLoRadix=8, KH*KW)` (`include/cachesim/layout/khkw_split.h:89`, `src/layout/khkw_split.cpp:34-35`). `enum Digit` header `:79`;
  `kName` `src/layout/khkw_split.cpp:15`.
- Ctor `:19`; `n_pos`, `n_pos_lo`, `n_pos_hi` `:34-36`; strides `:40-46`; `radix_product` `:51-53`;
  `num_lines` = max id + 1 via a loop over every `pos` `:64-72` (see 3.1 item 1 on its comment).
- `digit_stride` `:81`, `digit_radix` `:92`, `block_len` `:102`, `line_of` `:112`, `expand` `:135`
  (= `detail::expand_burst`; comment `:131-134`), `locate` `:139`, `line_size_terms` `:148`,
  `neighbour` `:154` (KH/KW step via pos, `:176-189`).

**src/layout/cin_khkw_concat.cpp** (`CinKhkwConcatMapper`, header `include/cachesim/layout/cin_khkw_concat.h:42`; 108 lines)
- Nesting `[cout_blk][d]` with `pos = kh*KW + kw`, `d = cin_blk*(KH*KW) + pos` and
  `D = n_cin_blocks*KH*KW`, so `line = cout_blk*D + d` (header `:8-14`, `line_of` `:55-62`). Every
  kernel position sits in the one dense digit, and `num_lines` is the exact product
  `n_cout_blocks * D`, partial channel blocks included (header `:18-19`), not the max id + 1 of the
  two split layouts. `enum Digit {COUT, D}` header `:44`; `kName` `src/layout/cin_khkw_concat.cpp:12`.
- Ctor `:16` (same four arguments as `KhkwSplitMapper`, header `:46-48`, so no split width and
  `cin_lo_blocks` stays the -1 sentinel, header `:29`): `check_shape_and_blocking` `:20`, block
  counts `:21-22`, `n_pos_` `:23`, `n_d_` and `num_lines_` through `checked_mul` `:24-25`,
  `line_size_bytes_` `:26`.
- `digit_stride` `:29` (COUT `n_d_`, D 1), `digit_radix` `:37`, `block_len` `:45`, `expand` `:64`
  (= `detail::expand_burst`), `locate` `:68` (= `set_index`), `line_size_terms` `:77`, `neighbour`
  `:81` (CIN and COUT one stride each `:89-95`, KH and KW rebuilt through `pos` `:99-105`).
  Accessors header `:63-70`.
- `layout = cin_khkw_concat` is `LayoutKind::CinKhkwConcat`
  (`include/cachesim/enum_names.h:22,31`); the factory case is `src/layout/factory.cpp:45-48`.

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
- Uses the shared `name_of` overloads from `include/cachesim/enum_names.h`; `total` and `quantile`
  remain local helpers.
- `class Row` `:43`: `str` (refuses `, " \n \r`) `:45`, `i64` `:58`, `f64` (`%.6f`) `:63`, `ratio`
  (empty cell when denominator 0) `:73`, `blank` `:81`, `blank_rest` `:87`, `take` `:92`; every
  cell checked against the schema position (`expect` `:102`).
- `emit_identity` `:116`, `emit_config` `:128` (comment `:150-151` points to where
  `l2_demand_reserve` is written), `emit_headline` `:167`.
- `csv_columns` `:175` (117 columns; `l2_demand_reserve` `:199`), each later column appended at the
  end for positional stability: `rrip_bits` `:215`, then `l2_prefetch_min_touches` and
  `l2_pf_filtered` `:219`, `l2_prefetch_trigger` `:225`, and last `l2_policy` `:230`. Three of
  those four are config cells read from `cfg` (`:396`, `:398`, `:399`) with the runtime counter
  `l2_pf_filtered` interleaved between them, read from `es` (`:397`). Of the three config cells
  `l2_policy` is the one validation rewrites, inheriting `policy` when unset
  (`src/config.cpp:611`), and `l2_prefetch_trigger` is settled to `miss` outside a
  `distance_aware` run (`src/config.cpp:685-694`), so both cells name the engine that ran rather
  than the text that was typed; `l2_prefetch_min_touches` is validated (refused below 0,
  `src/config.cpp:695-697`) but never rewritten. `csv_header` `src/instrument/stats.cpp:234`,
  written with its path because the config cross-references above it would otherwise anchor the
  bare (rule 6).
- `RunStats::RunStats` `:243`: `hidden_latency = fetch_latency_sum - core_stall_sum` `:262`, derived
  `dram_bytes = dram_accesses*line_size` `:282`, `pf_coverage = (timely+late) / demand_bursts`
  `:325-326`, L2 prefetch config then outcomes `:335-347` (`l2_demand_reserve` `:340`),
  `l2_pf_coverage = l2_pf_timely / l2_accesses` `:355-356` (comment `:352-354`: also the retrigger
  ratio, which holds in miss mode only), `port_bound_threshold = miss_frac * l2_miss_latency *
  l2_banks / l2_ii` `:358-371`, MSHR
  occupancy p50/p95/max `:374-384`, `events_per_cycle` `:391`.
- `csv_row` `:404`; `check_invariants` `:413-453`: stall causes sum == stall_total, hidden_latency >=
  0, L1 prefetch outcomes + drops == pf_issued (`:440-444`), and the L2 outcomes plus drops at most
  `l2_pf_issued`, invariant 4.6 with `H4` as its alias (`:445-452`; 3.3 item 2).
- `oracle_row` `:455`: identity + config + `total_cycles = tick_base_total`, rest blank.

**sweep.cpp**
- Uses `name_of(LayoutKind)` from `include/cachesim/enum_names.h`; `rethrow_with_index` prefixes
  "sweep: configuration i:" while preserving exception type.
- Ctor `:32`: non-empty grid, `size <= max_engines`, all points share `cin_block, cout_block,
  weight_bytes, layout, cin_lo_blocks` `:64-66`, mapper line size matches `:81`, then builds engines.
- `run` `:100`: per tile `advance` -> observer -> `step_tile` on each engine (timed); then `finish`
  each. Accessors `:134-140`.

### 2.3 `apps/`

**apps/cli_args.h** (namespace `cachesim::app`)
- `UsageError` `:25-27`, `value_of` `:29-32`, `int_value_of` `:37-49` (whole-string integer),
  `check_arm` `:53-59`, and `uuid4` `:63-73` (version 4, unseeded by design).
- `class TraceFd(spec)` `:77-102`: `-`, `fd:N`, or a path (owned and closed in the destructor).

**apps/output.h** (namespace `cachesim::app`)
- `lines_per_burst(mapper, hdr)` `:38-44`: expands the widest burst `{origin, burst_dim, burst_span,
  burst_stride}` and counts lines. Both apps pass a BlockPackMapper for any layout; the rationale is
  the mapper-count argument in the comment at `:24-37`.
- `class PaddingMeter` `:59-125`: observes bursts or a whole tile and reports
  `(lines_touched*cin_block*cout_block - elements_touched) / (lines_touched*...)`; dense bitmap
  sizing and the per-run/per-layout meaning are stated at `:46-58`.
- `write_out(path, text)` `:127-136`: `-` means stdout; otherwise the truncating ofstream is opened
  at `:133`.

**apps/oracle_io.h** (namespace `cachesim::app`)
- `read_oracle_lines(path, n_cores, l1_by_core*, l2_lines&)` `:46-88`: reads demand records from an
  AccessLog into per-core L1 lists and one shared L2 list; the nullable L1 convention and its memory
  reason are stated at `:23-44`, and the L2-only branch is annotated at `:72`.
- `OracleSet` `:100-108` (reserved L1 vector, optional shared L2, attached flag), `build_oracles`
  `:110-128` (frees each source bucket after construction), `attach_oracles` `:139-153` (only
  levels whose policy is Belady), `report_oracles` `:160-172`, and `report_overruns` `:197-211`.

**cachesim_run.cpp**: `kUsage` `:43` (header help `:50-51`), `struct Options` `:128` (`header = true`
`:152`), `parse_args` `:160` (`--header`/`--no-header` `:196-197`), `run` `:229` (steps in 1.3;
Belady oracle checks `:323-342`; instruments `:294-388`; truncation notes `:411-433`; header
emitted iff `opt.header` `:445`), `main` `:458`.

**cachesim_sweep.cpp**: `kUsage` `:37`, `struct Options` `:80`, `parse_args` `:94`, `read_file` `:126`,
`run` `:134` (validate every point with grid[0]'s probe `:148-172`; one mapper from grid[0]
`:175-182`; shared oracles `:193-204`; observer does hist/padding/progress `:212-220`; rows `:241-249`),
`main` `:262`.

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

Unit test binaries (`Makefile:58`, one binary per `tests/test_*.cpp`):
- `test_types.cpp`: Tagged scalars and tensor geometry helpers.
- `test_layout.cpp`: `Placement` and `AddressMapper` contracts via conformance checks.
- `test_layout_golden.cpp`: pins the observable mapping of all four layouts. 216 cases: 6 shapes x 5
  blockings x {block_pack, split_cin at 4 `cin_lo` values, khkw_split, cin_khkw_concat} (`:271-286`)
  plus 6 refusal cases (`:292-309`). Each case folds `num_lines`, `line_size_bytes`,
  `line_size_terms`, `line_of` of every coordinate, `expand` of bursts on every axis and `locate`
  under set counts {1,3,8,64} (`:123`) into one FNV-1a hash, compared with `kGolden` (`:314`).
  `--print-golden` regenerates the table (`:539-545`).
- `test_block_pack.cpp`: BlockPackMapper construction, validation, strides, `line_of`, `expand`,
  `locate`.
- `test_split_cin.cpp`: SplitCinMapper end to end, including the "count is layout-independent"
  property `lines_per_burst` relies on.
- `test_khkw_split.cpp`: KhkwSplitMapper flatten, per-core set coverage, interface contracts.
- `test_cin_khkw_concat.cpp`: CinKhkwConcatMapper two digits and hand-computed flatten, dense
  coverage under non-dividing blocks, 1x1 agreement with khkw_split line for line, placement and
  set coverage at small D, neighbour boundaries, refusals and overflow, the config and factory
  path, and burst counts plus the shared conformance checks.
- `test_neighbour.cpp`: `neighbour` on all four mappers, checked against `line_of` of the
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
- `prefetch/test_next_access.cpp`: prefetch interface, `none` vs `next_access`, engine integration and
  L1 drop rules; `prefetch/test_neighbour.cpp`: line-order neighbour behavior, cross-level policy
  placement, and L2 accounting; `prefetch/test_distance_aware.cpp`: exact forward COUT targets and the
  cout-extent boundary `:15`, a nonpositive distance refused `:66`, a negative `min_touches` refused
  `:246`, the touch filter opening exactly at `min_touches` and counting per line and per tile
  `:80-243`, and an L2 engine run that issues
  forward and drains every MSHR `:251`, with `:306` pinning that an L1 hit feeds the L2 touch
  counter and `:324` that a fully filtered `distance_aware` degrades to `none`.
- `test_config.cpp`: RunConfig parse, defaults, validation rules, among them
  `test_the_l2_mshr_floor_holds_a_burst_with_one_to_spare` (`test_config.cpp:211`): default
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
  (`mutation_check.sh:80`, helpers `mutate_lc_h` / `mutate_lc` at `:227-228`).
- `run_cli.sh`: `cachesim_run` end to end on a fixture converted by `examples/cachesim/to_stream.py`. Step
  11 (`run_cli.sh:203-220`): `--out` gets a header by default on a new and on an overwritten file,
  and `--no-header` drops it.
- `sweep_cli.sh`: `cachesim_sweep` end to end, compares with `cachesim_run` rows.
- `v1_pipe.sh`: invariant V1 (unbounded cache, zero latency -> `tile_origin[N] == tick_base[N]`),
  plus two deliberately broken runs that must fail. ("V1" here is the invariant name, not the WCTS
  version.)
- `cout_golden.sh` + `cout_golden.csv` (run by `make test-cli`,
  `Makefile:147`): converts the committed loas example to a v2 stream, asserts the stream's version
  is 2 (`cout_golden.sh:35-36`), runs a 4-point grid through `build/fixture/cachesim_sweep`
  (`:12,30-31`), and requires the CSV to equal the golden captured from the v1 reader on the same
  stream, ignoring only `git_commit` and `sim_wall_seconds` (`:38-48`).

### 2.5 `src/lays/cachesim/*.py` and `examples/cachesim/`

- `src/lays/cachesim/__init__.py`: docstring only (`src/lays/cachesim/__init__.py:1`).
- `src/lays/cachesim/__main__.py`: `python -m lays.cachesim` runs `lays.cachesim.cli.main` (`src/lays/cachesim/__main__.py:1-4`).
- `src/lays/cachesim/cli.py`: the `grid` / `sweep` / `run` dispatcher of 1.2. `sweep` and `run` are dispatched before
  argparse sees the arguments, so every native flag (and `--help`) reaches the binary unchanged.
- `src/lays/cachesim/grid.py`: `ROOT` = repo root from `__file__` (`src/lays/cachesim/grid.py:7`), `BASE_JSON` /
  `SWEEP_JSON` (`:8-9`); `load_base` `:12`, `load_sweep` `:16`; `grid_for(line_bytes, base, sweep)`
  `:20` (the points at one line size; keys stay in `base.json` order); `full_grid` `:44` (line size
  slowest); `write_grid(out_dir, grid, name="khkw")` `:51` (one file per `cin_block` in order of first
  appearance, because `cachesim_sweep` builds one mapper per grid file; returns `{cin_block: path}`).
- `src/lays/cachesim/stream.py`: the WCTS v2 writer (module docstring `:1-5`; byte layout comment `:29-40`). Constants
  `WCTS_MAGIC` `:43`, `WCTS_VERSION = 2` `:44`, `WCTS_FIXED_HEADER_BYTES = 56` `:45`,
  `WCTS_END_MAGIC = -1` `:46`, `WCTS_DIM_CODES` `:50`, `WCTS_ADDR_FIELDS` `:53`.
  `write_stream_header` `:57`; `write_tile_frame` `:99` (core ids strictly ascending `:112`, no empty
  core `:114`, ticks strictly ascending `:120`, non-empty run `:125`); `write_stream_trailer` `:136`;
  `_wcts_tile_frames(tiles, n_cores)` `:141` (tick-major to core-major, core id range check `:155`,
  `burst_span` = largest `cout_end - cout_start` `:167`, no bursts refused `:173`);
  `stream_weight_trace(trace, fh, *, n_cores, spatial_factors, burst_dim=3, burst_stride=1,
  weight_bytes=1, max_tiles=None)` `:178` (only `burst_dim = 3` `:196`; `max_tiles` cut before the
  header `:202`; returns the burst count `:220`).
- `examples/cachesim/to_stream.py`: `python3 to_stream.py <fixture.json> [max_tiles] > slice.wcts`
  (docstring `:3`). `load(path)` `:41` turns a v2 example JSON into `lays.weight_trace_gen.weight_trace`
  dataclasses; `main` `:60` calls `stream_weight_trace(..., n_cores=N_CORES, spatial_factors={3:
  N_CORES}, max_tiles=...)` (`:64-65`, `N_CORES = 8` at `:38`) to stdout. Adds `src/` to `sys.path`
  (`:20`) and stubs `lays.weight_trace_gen.trace` when its import fails (numpy absent, `:22-32`). Used by
  the four CLI test scripts.
- Data: `loas_vgg16_layer01_v2.json`, `ptb_resnet19_layer01_v2.json`,
  `prosperity_vgg16_layer01_v2.json`, `spinalflow_vgg16_layer01_v2.json` (JSON v2: tiles -> ticks ->
  cores -> `weight_addresses` `[kh,kw,cin,cout_start,cout_end]`),
  `gustavsnn_vgg16_layer01_v1_legacy.json` (JSON v1, cannot drive the engine, `examples/cachesim/to_stream.py:5-6`),
  `manifest.json` (provenance). The `_v1` / `_v2` in the file names is the weight-trace JSON shape,
  not the WCTS version.

---

## 3. Findings for cleanup (code-evidenced)

### 3.1 Dead code, stale comments, stale references
1. **`src/layout/khkw_split.cpp` comments state a false premise about the sort and the max loop.** The comment
   above `expand` says the sort in `expand_burst` is load-bearing because "line_of is NOT monotone in
   pos" and a wrap "can move the line down" (`src/lays/cachesim/native/src/layout/khkw_split.cpp:131-134`). By the
   code's own arithmetic it cannot: the position term is `(pos / L) * S + pos % L` with
   `L = n_pos_lo` and `S = stride[POS_HI] = n_cout_blocks * n_cin_blocks * L >= L`
   (`src/layout/khkw_split.cpp:40-46,124,127`). Stepping `pos` inside a group adds 1; a wrap adds
   `S - (L - 1) >= 1`. So `line_of` is strictly increasing in `pos`, the sort is a no-op on this
   layout exactly as on block_pack and split_cin (`src/layout/block_pack.cpp:196-200`, `src/layout/split_cin.cpp:261-275`), and the
   ctor comment "the largest sum is not in general at the largest pos" (`src/layout/khkw_split.cpp:60-63`) is
   wrong for the same reason. The code is correct (the sort is harmless and the loop finds the true
   maximum); only the stated reasons are wrong. Derived by hand, not by running code.
2. Stale test names that contradict their own group strings: `test_l2_demand_reserve_is_rejected_by_name`
   checks that the key is live (`tests/test_config.cpp:185-186`); `test_l2_demand_reserve_is_not_a_column`
   checks that it is a column (`tests/instrument/test_stats.cpp:164-165`). `test_stream_format.cpp:158` labels
   the v2 field-order check "v1 address field order".
3. The comment above the L2 reserve rule still gives prefetching as its reason ("makes prefetching
   unreachable while claiming to be on", `src/config.cpp:703-705`), while the message itself
   describes an MSHR floor that holds whatever the prefetch policy is (`config.cpp:711-715`) and
   `test_config.cpp:211-233` asserts the message does not mention prefetching.
4. References to an archive that is not in the repo: `src/layout/block_pack.cpp:168` ("the v1 lesson the archive
   preserved"), `tests/layout/test_block_pack.cpp:831`, `tests/index/test_set_associative.cpp:21`. Also
   `src/layout/block_pack.cpp:26-30` says "the expression is not written yet", while `line_of` (`:163`) is.
5. Doubled prefix in the `neighbour` range messages: `reject_range(kName, "BlockPackMapper::neighbour:
   ...")` prints "BlockPackMapper: BlockPackMapper::neighbour: ..." (`src/layout/block_pack.cpp:229`; same
   at `src/layout/split_cin.cpp:309`, `src/layout/khkw_split.cpp:157`). Runs of three blank lines: `src/layout/block_pack.cpp:221-223`, `src/layout/split_cin.cpp:303-305`, `src/layout/khkw_split.cpp:151-153`.
6. `EngineStats::pf_dropped_targets_full` (`include/cachesim/core/engine.h:217`) is never incremented
   anywhere in `src/`; it is always 0 by construction (read only at `src/instrument/stats.cpp:255-258,317`).
   `Request::reason` (`include/cachesim/core/request.h:66-74`) is written (`src/core/mshr.cpp:64`) but never read in
   `src/` or `apps/`.
7. `replacement/next_use.h:29` includes `<istream>`, which nothing in the file uses.
8. `LevelParams::bank_high_bits` (`include/cachesim/core/cache_level.h:133`) has no config key (absent from
   `config.cpp:136-166`, never set in `to_engine_params`), so the high-bits banking branch
   (`src/core/cache_level.cpp:106`) is reachable only from tests.
9. Output still names the simulator `wcache`: the comment line the line trace writes
   (`include/cachesim/instrument/line_trace.h:71`) and the one the cache-state log writes
   (`include/cachesim/instrument/cache_state_log.h:60`). The writer's comment points at a plan and a ruling that
   are not in the repo (`src/lays/cachesim/stream.py:22`, `:26`).

### 3.2 Duplicated logic
1. Mapper helpers: the checks, `expand`, `locate` and `line_size_terms` live in
   `src/layout/layout_common.h` / `.cpp` (2.2). What is still duplicated: an int64 ceiling written twice more,
   `ceil_div` (`src/layout/split_cin.cpp:32`) and the inline `n_pos_hi_` ceiling
   (`src/layout/khkw_split.cpp:36`), beside `detail::blocks_covering` (`src/layout/layout_common.h:48`, int32
   extent); and the same `neighbour` range-check block in each mapper (`src/layout/block_pack.cpp:228-232`,
   `src/layout/split_cin.cpp:308-312`, `src/layout/khkw_split.cpp:156-160`,
   `src/layout/cin_khkw_concat.cpp:83-87`, which writes a different message and repeats the block in
   its own `locate` at `src/layout/cin_khkw_concat.cpp:69-73`). `neighbour` staying per mapper is by design
   (`src/layout/layout_common.h:5-6`).
2. Nearest-rank quantile twice: `include/cachesim/instrument/hist.h:85-92` and `src/instrument/stats.cpp:29-36`.
3. `engine_error` / `idx` twice: `src/core/engine.cpp:18-22`, `src/core/engine_core.cpp:31-35`. Way-from-slot
   arithmetic twice: `core/engine.cpp:816-828` and `core/engine.cpp:886-890`.
4. Per-policy `index_or_reject` four times: `src/replacement/{stamp,belady,lfu,rrip}.cpp`.
5. The two apps duplicate the config/trace/mapper/validate setup and drift:
   - `--max-engines` uses bare `std::stoi` (`apps/cachesim_sweep.cpp:107-110`, accepts `"12abc"`) while
     `cachesim_run` uses `int_value_of` (`apps/cli_args.h:37-49`).
   - Oracle help text disagrees: L1 oracles "exact WHILE NOTHING BLOCKS" (`cachesim_run.cpp:92-97`) vs
     "EXACT" (`cachesim_sweep.cpp:67-69`).
   - Sweep has no `--l2-oracle`, instruments, or `--oracle-only`.
   - AccessLog batch size `1 << 16` duplicated in `include/cachesim/instrument/access_log.h:141` and `apps/oracle_io.h:60`.

### 3.3 Behaviour hazards worth a look before trusting new runs
1. **H2** `LineTrace::key` packs `core+1` into 6 bits with no check (`include/cachesim/instrument/line_trace.h:179-182`); the comment says a wider machine "would trip the encoding" (`:175-178`), but nothing
   trips, so with more than 62 cores keys alias silently. `AccessLog` allows 255 cores
   (`include/cachesim/instrument/access_log.h:136`); the code mentions 256-core targets (`core/event.h:240-243`).
2. **H4** L2 prefetch accounting is closed in one direction only: the L2-policy outcomes plus the
   four drop reasons sum to **at most** `l2_pf_issued`, and `check_invariants` enforces exactly that
   bound, throwing "H4 violated" when the sum exceeds the issue count
   (`src/instrument/stats.cpp:447-452`, inside `check_invariants` `:413-453`). The bound is written
   as invariant 4.6 with `H4` as its alias (`include/cachesim/instrument/stats.h:92-93`) and
   restated beside the CSV emission (`src/instrument/stats.cpp:331-334`). What it judges is summed
   per row at `src/instrument/stats.cpp:265-268`: `l2_pf_timely + l2_pf_late + l2_pf_wasted` plus the
   four `l2_pf_dropped_*` counters, with `l2_pf_retriggers` deliberately not a term.
   - **The open direction is the undercount.** `close_out_prefetch_stats` charges the L1 prefetcher
     only (`src/core/engine.cpp:788-808`), so L2 lines still tagged in `l2_prefetched_` when the run
     ends are never charged as wasted and the outcomes can sum to less than `l2_pf_issued`. Stated
     in the function's closing comment (`:800-802`), beside the CSV emission
     (`src/instrument/stats.cpp:332-334`) and in the invariant itself
     (`include/cachesim/instrument/stats.h:93`). `tests/instrument/test_stats.cpp:403-435` pins the
     direction: with any one outcome or drop reason set to 1, the row refuses at `l2_pf_issued` 0 and
     passes at 1 and 2.
   - **The counters are scoped to the L2 policy.** The tag is inserted at one chokepoint, the L2
     fill, and only when the MSHR's primary target is a prefetch at issue
     (`src/core/engine.cpp:626-628`, predicate `include/cachesim/core/mshr.h:140`); the primary
     keeps its L1 entry until L1 fill, so an L1 prefetch's own L2 fill opens no tag, which is what
     the gate's comment says (`src/core/engine.cpp:622-625`). Eviction of a still-tagged line
     charges `l2_pf_wasted` (`:640-645`) and a demand hit on one charges `l2_pf_timely`, clears the
     tag and, in miss mode, retriggers (`:522-530`), so every L2 outcome counter belongs to a
     prefetch the L2
     policy issued. `tests/prefetch/test_neighbour.cpp:86-113` pins it: an L1 `next_access` run with
     `pf_issued > 0` and `pf_timely > 0` has `l2_pf_issued`, `l2_pf_timely`, `l2_pf_late`,
     `l2_pf_wasted` and `l2_pf_retriggers` all 0; `:115-143` repeats it for an L1-prefetched line
     used by a second core.
   - **The surface the invariant is checkable on.** Only the simulator's own per-run CSV carries the
     four `l2_pf_dropped_*` columns (`src/instrument/stats.cpp:201-203`), so the sum can be checked
     there. The demo's `results.csv` is 32 columns and carries `l2_pf_issued`, `l2_pf_timely`,
     `l2_pf_late`, `l2_pf_wasted` and `l2_pf_coverage` only (`zoo/demo_l2pf/compare_l2pf.py:28-37`), with
     no drop counters, so the invariant cannot be checked on that file.
3. **H6** MSHR occupancy samples are appended on every forward and retire
   (`src/core/engine.cpp:287,484,661,730`) and kept for the whole run per engine; memory grows with miss
   count times grid size (up to 256 engines).
4. **H7** `TraceFd` parses `fd:N` with unchecked `std::stoi` (`apps/cli_args.h:77-102`).
5. **H8** The decoded run length ignores `burst_stride`: `count = run_end - run_start`
   (`src/trace/stream_trace.cpp:306`) while `expand_burst` walks `start + i*stride` for `i < count`
   (`src/layout/layout_common.h:138-139`). For stride `s > 1` a run `[start, end)` holds
   `ceil((end - start) / s)` elements, but the decoder asks for `end - start` of them, so the walk
   runs past `run_end` (or is refused as out of range). The writer does the same: `burst_span` is the
   largest `cout_end - cout_start` (`src/lays/cachesim/stream.py:167`) and `lines_per_burst` expands
   `burst_span` elements at `burst_stride` (`apps/output.h:38-44`). Unreachable today because
   `stream_weight_trace` defaults `burst_stride=1` (`src/lays/cachesim/stream.py:178`) and every test uses 1
   (`tests/stream_builder.h:110`).
6. **H9** The header's `burst_span` is never checked against the bursts. `decode_header` only
   requires `burst_span >= 1` (`trace/stream_format.h:258-262`) and `advance` never reads it
   (`src/trace/stream_trace.cpp:176-335`), yet `lines_per_burst` (`apps/output.h:38-44`) is computed
   from it and sets the `l1_mshrs` check (`config.cpp:648-650`) and both demand-reserve defaults
   (`config.cpp:706,734`). A header that understates the span passes validation. Separately,
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
- `CXX := g++` pinned, ignoring the environment (`src/lays/cachesim/native/Makefile:24`, rationale about the
  Delta Cray wrapper at `:19-22`), while `compile_fail.sh` honours `${CXX:-g++}`
  (`tests/compile_fail.sh:21`).
- `JOBS` default 32 = the dev machine's `nproc` (`tests/compile_fail.sh:35,56`,
  `tests/mutation_check.sh:120`).
- `cout_golden.sh` always runs `build/fixture/cachesim_sweep` (`tests/cout_golden.sh:12`), so
  `make MODE=release test-cli` builds release apps and then tests the fixture binary (or fails if
  it was never built).
- `to_stream.py` hardcodes 8 cores and `spatial_factors={3: 8}`
  (`examples/cachesim/to_stream.py:38,64-65`).
- `python -m lays.cachesim sweep` / `run` always run the `build/release` binaries and build them only when
  the file is missing (`native` in `src/lays/cachesim/cli.py`), so a binary older than the sources is run
  as is.
- The grid defaults are fixed files: `examples/cache/base.json` and `examples/cache/khkw_sweep.json`
  (`src/lays/cachesim/grid.py:8-9`), found from the repo root `ROOT` (`src/lays/cachesim/grid.py:7`).
- Magic numbers in code: `kPosLoRadix = 8` (`include/cachesim/layout/khkw_split.h:89`); RRIP width cap 8 twice
  (`src/replacement/rrip.cpp:11`, `src/config.cpp:633`); `--max-engines` 256
  (`apps/cachesim_sweep.cpp:87`); AccessLog record limits 32-bit line / 8-bit core
  (`include/cachesim/instrument/access_log.h:135-136`).
- `trace/stream_format.h:35-37` requires the GCC/Clang `__BYTE_ORDER__` macro.
- No absolute paths or hostnames appear in any `.cpp/.h/.sh/.py` file in scope (grep for `/home/`,
  `/projects/`, `/scratch`, `delta`, `ncsa` hits comments only).

### 3.5 Build products in git
None: `git ls-files src/lays/cachesim/native/build` is empty; `build/` is ignored by
`src/lays/cachesim/native/.gitignore:1`; `__pycache__/` by the root `.gitignore:2`. Local
`src/lays/cachesim/native/build/fixture/` and `build/release/` exist (untracked). Note the repo-wide `*.json`
ignore (`.gitignore:23`) with exceptions only for the five config directories under `examples/`
(`.gitignore:32-36`) and `examples/cachesim/*.json` (`.gitignore:42`): a run config written anywhere
else is silently untracked.

---

## 4. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

What the code needs:
- **Compiler/build**: GNU make and `g++` with C++17 (`Makefile:24-26`); flags `-Wall -Wextra
  -Wpedantic -Wsign-conversion -Wconversion -Wshadow` (`Makefile:27`), `-O0 -g` (fixture) or
  `-O2 -DNDEBUG` (release, `Makefile:31-34`). No CMake (no `CMakeLists.txt` exists). No third-party
  libraries; POSIX headers (`unistd.h`, `fcntl.h` in `trace/byte_source.h:17`, `apps/cli_args.h:9-10`).
  `ar` for the archive. Minimum g++ version is not pinned anywhere. `src/layout/layout_common.cpp` is picked
  up by `SRCS := $(sort $(shell find src -type f -name '*.cpp' -print))` (`Makefile:43`).
- **Release programs**: `make release` builds only `libcachesim.a` (`Makefile:182-183`).
  `python -m lays.cachesim sweep` / `run` need `build/release/cachesim_sweep` / `cachesim_run` and build
  them with `make MODE=release apps` when they are missing (`src/lays/cachesim/cli.py`).
- **Tests**: `make test` needs only the compiler and bash; `wait -n` in `compile_fail.sh:109` needs
  bash >= 4.3. `make test-cli` needs `python3` (override with `PYTHON`) and importable `lays.cachesim.stream`
  and `lays.weight_trace_gen.weight_trace` (`examples/cachesim/to_stream.py:20`, `:34-36`); numpy is optional thanks to the
  stub.
- **Inputs**: real runs need WCTS **v2** streams, written by `python -m lays.weight_trace_gen gen --stream`
  (`stream_weight_trace`, `src/lays/cachesim/stream.py:178`) from a schedule and the input traces under
  `examples/input_trace/`; `scripts/pipeline.py` writes them under its output directory. Only the five small
  example slices are committed (`examples/cachesim/`). A version-1 stream is refused (top note).
  For COUT streams a v2 stream gives the same rows as the v1 reader did (`tests/cout_golden.sh` checks
  this on one fixture).
- **Two-pass Belady**: `policy/l2_policy = belady` needs `--oracle` / `--l2-oracle` from a prior
  run's `--access-log` over the same trace and layout (`cachesim_run.cpp:323-342`); results are only
  sound when `max_wait_depth == 0` (`apps/oracle_io.h:204-210`).
- **Non-deterministic columns**: `run_id` defaults to a random UUID (`apps/cli_args.h:63-73`),
  `sim_wall_seconds` is wall time, and `git_commit` is empty unless the driver passes it
  (`cachesim_run.cpp:56-57`). Everything else is designed to be bit-identical across runs (total event
  order, vectors iterated by index; `unordered_map`s are never iterated in decision paths, though
  `LineTrace::flush` sorts its map keys `instrument/line_trace.h:148-151`).
- **Binary formats**: the AccessLog is written in host byte order with no endianness marker
  (`include/cachesim/instrument/access_log.h:129-130`), unlike WCTS, which is explicitly little-endian. The WCTS magic did not
  change between v1 and v2 (`trace/stream_format.h:41`); only the version field tells them apart.
- **Paths**: `src/lays/cachesim/cli.py` and `scripts/pipeline.py` locate the binaries and configs from the
  repo root (`ROOT`, `src/lays/cachesim/grid.py:7`), not through absolute paths.

---

## 5. Open questions the code alone cannot answer

1. Should `burst_stride > 1` be supported? If so, should the record's `run_end` stay an element
   bound (and the decoder compute `ceil((run_end - run_start) / stride)`), or become a count (H8)?
2. Should the reader check each burst against the header's `burst_span`, and should
   `lines_per_burst` account for anchors that are not block-aligned (H9)?
3. Should tagged-but-unused L2 prefetched lines be charged as wasted at end of run? `check_invariants`
   bounds the L2 outcomes by `l2_pf_issued` (4.6/H4, `src/instrument/stats.cpp:445-452`) but nothing
   charges the lines still resident at finish, so the sum trails the issue count by exactly those
   lines and the code alone does not say whether that is the intended reading of waste.
4. Is `l2_policy` meant to appear in the CSV? The schema has only `policy` (`src/instrument/stats.cpp:184-186`), so
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
- `src/lays/cachesim/native/compile_flags.txt` was not read (`.txt` is excluded by the reading rules).
- `src/lays/weight_trace_gen`, which builds the `LayerWeightTrace` that `stream.py` writes, is covered in
  `docs/atlas/pipeline.md`.
- `src/lays/cachesim/cli.py` is described without line numbers.
- `python -m lays.cachesim grid`, `sweep` and `run` were run once on one stream (resnet19 layer 9,
  sample 0) to check 1.2; every other behaviour claim comes from reading the code.
