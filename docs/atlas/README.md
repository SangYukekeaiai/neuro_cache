# Code atlas index

Commit `ef48902` (branch `wcache-rebuild-phase-a`) plus the uncommitted
working-tree changes to `scripts/pipeline.py`, `src/snn_scheduler/cli.py`,
`tests/test_snn_scheduler_cli.py` and `src/cachesim/examples/manifest.json`.
Built only from reading code (`.py .cpp .h Makefile .yaml .json .toml`) and
directory listings; no notes or logs were read. Paths are relative to the repo
root; `file:N` is line N of that file, and a bare `:N` refers to the file
named last before it.

## Files

| File | Scope |
|---|---|
| [pipeline.md](pipeline.md) | The pipeline end to end: `src/util.py`, `src/parsers/`, `src/snn_scheduler/` (SNN scheduler, Gurobi MIP, schedule artifact), `src/weight_trace_gen/` (weight-trace generator, five native arch models), the files the pipeline writes for the simulators (`src/nocsim/step_cycles.py`, `src/cachesim/stream.py`), `src/cachesim/grid.py` and `cli.py`, `scripts/`, `configs/`, `input_trace/`, `tests/`, and the build files |
| [nocsim.md](nocsim.md) | `src/nocsim/`: schedule -> NoC transactions -> eventsim makespan, and `python -m nocsim` |
| [cachesim_native.md](cachesim_native.md) | `src/cachesim/native/`: the C++ cache simulator (`libcachesim.a`, `cachesim_run`, `cachesim_sweep`, tests), the WCTS v2 reader, and `src/cachesim/examples/` |

Where each part of the tree is described:

| Path | Atlas file |
|---|---|
| `src/snn_scheduler/`, `src/weight_trace_gen/`, `src/parsers/`, `src/util.py` | pipeline.md, section 2 |
| `src/nocsim/` (`step_cycles.py` also in pipeline.md 2.3) | nocsim.md |
| `src/cachesim/native/`, `src/cachesim/examples/` | cachesim_native.md |
| `src/cachesim/stream.py`, `grid.py`, `cli.py` | pipeline.md 2.4 |
| `scripts/pipeline.py` | pipeline.md 1.5, 2.9 |
| `configs/` (`arch`, `node_mapspace`, `cache`, `schedules`, `workloads`) | pipeline.md 2.10 |
| `input_trace/` | pipeline.md 2.11 |
| `tests/` | pipeline.md 2.12 (nocsim tests also in nocsim.md) |
| `Makefile`, `pyproject.toml`, `conftest.py`, `requirements.txt` | pipeline.md 2.13 |

## 10 cross-cutting facts

1. Four modules, four CLIs, one driver: `python -m snn_scheduler {solve,
   enumerate, solve-trace}` (`src/snn_scheduler/cli.py:44`), `python -m
   weight_trace_gen gen` (`src/weight_trace_gen/cli.py:353`), `python -m nocsim`
   (`src/nocsim/__main__.py:1`), `python -m cachesim {grid, sweep, run}`
   (`src/cachesim/cli.py:28`). `scripts/pipeline.py` composes them only as
   subprocesses (`scripts/pipeline.py:280-283`, :339-351, :362-366, :373-376)
   and joins the two simulators on (trace_dir, layer, sample) with speedup =
   nocsim cycles / cache-simulator cycles (`join_results` :68, `speedup` :60).
2. WCTS v2 burst record is `[kh, kw, cin, cout, run_end]`: the writer packs it
   as `<q5i` after the tick (`src/cachesim/stream.py:130`); the reader sets
   the anchor to `Coord{kh, kw, cin, cout}`, takes `run_start` on the burst
   axis and refuses `run_end <= run_start`
   (`src/cachesim/native/src/stream_trace.cpp:292-294`), so bursts on every
   axis decode. Any other format version is refused
   (`src/cachesim/native/include/cachesim/stream_format.h:42`, :221).
3. The three mappers (block_pack, split_cin, khkw_split) share their checks
   and burst walk (`detail::expand_burst`,
   `src/cachesim/native/src/layout_common.h:120`), included by
   `src/cachesim/native/src/block_pack.cpp:7`,
   `src/cachesim/native/src/split_cin.cpp:8` and
   `src/cachesim/native/src/khkw_split.cpp:9`;
   `src/cachesim/native/tests/test_layout_golden.cpp:6-10` pins every mapping
   and refusal with one FNV-1a hash per case.
4. Cache simulator output: both apps write the CSV header by default and
   `--no-header` turns it off (`src/cachesim/native/apps/cachesim_run.cpp:46-47`,
   :140; `src/cachesim/native/apps/cachesim_sweep.cpp:44-45`, :85);
   `l2_pf_timely` always equals `l2_pf_retriggers`, since
   `src/cachesim/native/src/engine.cpp:423-424` increments both at one site
   (`src/cachesim/native/include/cachesim/engine.h:265`,
   `src/cachesim/native/src/stats.cpp:362`).
5. L2 MSHR floor: an unset `l2_demand_reserve` (-1,
   `src/cachesim/native/include/cachesim/config.h:104`) resolves to
   `lines_per_burst` and must stay below `l2_mshrs` (default 20, :71), else
   `validate` refuses the config (`src/cachesim/native/src/config.cpp:629-639`).
6. The cache simulator's base point and sweep axes have one source each,
   `configs/cache/base.json` and `configs/cache/khkw_sweep.json`, read only
   through `src/cachesim/grid.py:8-17`. One `cachesim_sweep` call takes one
   address mapper, so grids are written one file per `cin_block`
   (`src/cachesim/grid.py:39-52`) and the pipeline runs one sweep per file
   (`scripts/pipeline.py:368-376`).
7. `FLITS_PER_PACKET = 4` has one source,
   `src/nocsim/eventsim/constants.h:5`; `src/nocsim/core/transaction.py:28-37`
   parses it at import, and `tests/test_flits_per_packet.py` checks the built
   binary agrees.
8. Data kept outside git lives under `$NEURO_CACHE_DATA` (default
   `<repo>/data`, fallback not logged) via `data_root()` (`src/util.py:15`,
   :23-24); the pipeline writes to `data_root()/demo/<bench>` by default
   (`scripts/pipeline.py:313`). Every CLI resolves its repo-relative defaults
   from `__file__` except `snn_scheduler solve`/`enumerate`, whose defaults are
   cwd-relative (`src/snn_scheduler/cli.py:22-25`).
9. Dependency direction: the pipeline produces the schedule JSON
   (`src/snn_scheduler/artifact.py:101-104`), the step-cycles file nocsim reads
   (`src/nocsim/step_cycles.py:27`, read at `src/nocsim/sim.py:335-337`) and the
   WCTS stream the cache simulator reads (`src/cachesim/stream.py:177`). The
   two simulators never call each other; their numbers meet only in
   `scripts/pipeline.py:394`. The Python packages import each other in both
   directions (`snn_scheduler` <-> `weight_trace_gen` <-> `nocsim`; pipeline.md
   1.4); the C++ in `src/cachesim/native` and `src/nocsim/eventsim` depends on
   no Python.
10. Build and reproduce: GNU make, C++17, no CMake. `make build`
    (`Makefile:5-8`) builds the cache simulator apps, eventsim and `loasgen`;
    in `src/cachesim/native`, `make release` builds only the library
    (`src/cachesim/native/Makefile:206-207`), so the apps need `make
    MODE=release apps`, which is what `src/cachesim/cli.py:23` and
    `scripts/pipeline.py:333` run. A Gurobi license is needed only to solve:
    the tracked schedules in `configs/schedules/loas` cover V8, V9, R9 and R16,
    and the pipeline asks for `gurobipy` only when a requested schedule is
    missing (`scripts/pipeline.py:322-325`).

## Reading guide

**30-minute pass (overall structure).** This README's facts, then in each
file the header note and the first subsections of "1. Top-down" (purpose,
entry points, data flow): pipeline.md 1.1-1.3 first, since it shows how the
four modules connect, then cachesim_native.md and nocsim.md.

**2-hour pass (how each component works).** The rest of "1. Top-down" in
each file (pipeline.md 1.4-1.6), then these 16 functions in the code, with
their "2. Bottom-up" entries:

| # | Function | Location |
|---|---|---|
| 1 | `demo` (the end-to-end driver) | `scripts/pipeline.py:316` |
| 2 | `solve_best_schedule` | `src/snn_scheduler/solve.py:269` |
| 3 | `solve_and_cache_schedule` | `src/snn_scheduler/artifact.py:49` |
| 4 | `reconstruct_samples` | `src/weight_trace_gen/weight_trace.py:163` |
| 5 | `run_stream` | `src/weight_trace_gen/cli.py:301` |
| 6 | `stream_weight_trace` | `src/cachesim/stream.py:177` |
| 7 | `decode_header` | `src/cachesim/native/include/cachesim/stream_format.h:208` |
| 8 | `StreamingTileTrace::advance` | `src/cachesim/native/src/stream_trace.cpp:176` |
| 9 | `detail::expand_burst` | `src/cachesim/native/src/layout_common.h:120` |
| 10 | `validate` | `src/cachesim/native/src/config.cpp:521` |
| 11 | `Engine::run_to_barrier` | `src/cachesim/native/src/engine.cpp:128` |
| 12 | `CacheLevel::triage` | `src/cachesim/native/src/cache_level.cpp:112` |
| 13 | `schedule_from_strategy` | `src/nocsim/schedule/decode.py:238` |
| 14 | `iter_node_tiles` | `src/nocsim/schedule/tiles.py:98` |
| 15 | `combine` | `src/nocsim/combine.py:120` |
| 16 | `simulate` | `src/nocsim/eventsim/EventSim.h:54` |

**Full pass.** Every section of every file, in the order cachesim_native.md
-> pipeline.md -> nocsim.md. cachesim_native comes first because it stands
alone: its C++ consumes only WCTS and depends on no other code. The pipeline
comes next because it produces every simulator input, WCTS included. nocsim
comes last: it imports `weight_trace_gen` and reads the pipeline's
step-cycles files. `snn_scheduler` and `weight_trace_gen` import
`nocsim.schedule` back (fact 9), but only `schedule_from_strategy` and
`iter_node_tiles`, which can be read as black boxes on the first pass.
