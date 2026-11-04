# Code atlas index

Commit `0c55f2f` (branch `wcache-rebuild-phase-a`).

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

Re-verified since, so nothing here is left uncovered: the 13 citations whose cited text changed
between this file's previous stamp `0c598d1` and `b2c4a88` have each been read against the code at
`0c55f2f` and repointed. In BOTH forms: 11 attached and 2 bare - `src/config.cpp` 3,
`src/core/engine.cpp` 2, `include/cachesim/config.h` 2 (the attached `:110` and the bare `:71`, which
named `l1_mshrs` where the sentence means `l2_mshrs`, now `:73`), `src/lays/cachesim/grid.py` 2, and one
each in `apps/cachesim_run.cpp` (with its bare `:143`), `include/cachesim/core/engine.h`,
`src/instrument/stats.cpp` and `src/lays/scheduler/solve.py`. The count is per citation, not per file,
and it is measured on the cited TEXT rather than on where hunks fall, so it covers citations into files
that never moved a line as well; a file carrying two citations counts twice. Text comparison is only a
candidate list: it cannot see a citation that was never right, nor one that shifted onto a
coincidentally identical line, so each of the 13 was read against the code rather than repointed by
arithmetic.
Every code file cited here is committed at `0c55f2f` except one: the new layout
mapper `src/lays/cachesim/native/src/layout/cin_khkw_concat.cpp`, cited in fact 3,
is untracked, so its citation was read against the working tree rather than that
commit. Whether the documentation around a cited file has been committed yet does
not affect this.
The only `.gitignore` line this atlas does not cover is an ignore rule at the end
of the file, below every line of it cited here.
Built only from reading code (`.py .cpp .h Makefile .yaml .json .toml`) and
directory listings; no notes or logs were read. Paths are relative to the repo
root; `file:N` is line N of that file, and a bare `:N` refers to the file
named last before it.

## Files

| File | Scope |
|---|---|
| [pipeline.md](pipeline.md) | The pipeline end to end: `src/lays/util.py`, `src/lays/parsers/`, `src/lays/scheduler/` (SNN scheduler, Gurobi MIP, schedule artifact), `src/lays/weight_trace_gen/` (weight-trace generator, five native arch models), the files the pipeline writes for the simulators (`src/lays/nocsim/step_cycles.py`, `src/lays/cachesim/stream.py`), `src/lays/cachesim/grid.py` and `cli.py`, `scripts/`, `examples/`, `examples/input_trace/`, `tests/`, and the build files |
| [nocsim.md](nocsim.md) | `src/lays/nocsim/`: schedule -> NoC transactions -> eventsim makespan, and `python -m lays.nocsim` |
| [cachesim_native.md](cachesim_native.md) | `src/lays/cachesim/native/`: the C++ cache simulator (`libcachesim.a`, `cachesim_run`, `cachesim_sweep`, tests), the WCTS v2 reader, and `examples/cachesim/` |

Where each part of the tree is described:

| Path | Atlas file |
|---|---|
| `src/lays/scheduler/`, `src/lays/weight_trace_gen/`, `src/lays/parsers/`, `src/lays/util.py` | pipeline.md, section 2 |
| `src/lays/nocsim/` (`step_cycles.py` also in pipeline.md 2.3) | nocsim.md |
| `src/lays/cachesim/native/`, `examples/cachesim/` | cachesim_native.md |
| `src/lays/cachesim/stream.py`, `grid.py`, `cli.py` | pipeline.md 2.4 |
| `scripts/pipeline.py` | pipeline.md 1.5, 2.9 |
| `examples/` (`arch`, `node_mapspace`, `cache`, `schedules`, `workloads`) | pipeline.md 2.10 |
| `examples/input_trace/` | pipeline.md 2.11 |
| `tests/` | pipeline.md 2.12 (nocsim tests also in nocsim.md) |
| `Makefile`, `pyproject.toml`, `conftest.py`, `requirements.txt` | pipeline.md 2.13 |

## 10 cross-cutting facts

1. Four modules, four CLIs, one driver: `python -m lays.scheduler {solve,
   enumerate, solve-trace}` (`src/lays/scheduler/cli.py:44`), `python -m
   weight_trace_gen gen` (`src/lays/weight_trace_gen/cli.py:353`), `python -m lays.nocsim`
   (`src/lays/nocsim/__main__.py:1`), `python -m lays.cachesim {grid, sweep, run}`
   (`src/lays/cachesim/cli.py:28`). `scripts/pipeline.py` composes them only as
   subprocesses (`scripts/pipeline.py:280-283`, :339-351, :362-366, :373-376)
   and joins the two simulators on (trace_dir, layer, sample) with speedup =
   nocsim cycles / cache-simulator cycles (`join_results` :68, `speedup` :60).
2. WCTS v2 burst record is `[kh, kw, cin, cout, run_end]`: the writer packs it
   as `<q5i` after the tick (`src/lays/cachesim/stream.py:131`); the reader sets
   the anchor to `Coord{kh, kw, cin, cout}`, takes `run_start` on the burst
   axis and refuses `run_end <= run_start`
   (`src/lays/cachesim/native/src/trace/stream_trace.cpp:292-294`), so bursts on every
   axis decode. Any other format version is refused
   (`src/lays/cachesim/native/include/cachesim/trace/stream_format.h:42`, :221).
3. The four mappers (block_pack, split_cin, khkw_split, cin_khkw_concat) share
   their checks and burst walk (`detail::expand_burst`,
   `src/lays/cachesim/native/src/layout/layout_common.h:120`), included by
   `src/lays/cachesim/native/src/layout/block_pack.cpp:7`,
   `src/lays/cachesim/native/src/layout/split_cin.cpp:8`,
   `src/lays/cachesim/native/src/layout/khkw_split.cpp:9` and
   `src/lays/cachesim/native/src/layout/cin_khkw_concat.cpp:6`;
   `src/lays/cachesim/native/tests/layout/test_layout_golden.cpp:6-10` pins every mapping
   and refusal with one FNV-1a hash per case.
4. Cache simulator output: both apps write the CSV header by default and
   `--no-header` turns it off (`src/lays/cachesim/native/apps/cachesim_run.cpp:50-51`,
   :152; `src/lays/cachesim/native/apps/cachesim_sweep.cpp:47-48`, :88);
   `l2_pf_timely` always equals `l2_pf_retriggers`, since
   `src/lays/cachesim/native/src/core/engine.cpp:528-530` increments both at one site
   (`src/lays/cachesim/native/include/cachesim/core/engine.h:268-273`,
   `src/lays/cachesim/native/src/instrument/stats.cpp:353-354`).
5. L2 MSHR floor: an unset `l2_demand_reserve` (-1,
   `src/lays/cachesim/native/include/cachesim/config.h:127`) resolves to
   `lines_per_burst` and must stay below `l2_mshrs` (default 20, :73), else
   `validate` resolves the reserve (`src/lays/cachesim/native/src/config.cpp:706`) and refuses the config
   when it leaves no MSHR free (`src/lays/cachesim/native/src/config.cpp:711-716`).
6. The cache simulator's base point and sweep axes have one source each,
   `examples/cache/base.json` and `examples/cache/khkw_sweep.json`, read only
   through `src/lays/cachesim/grid.py:8-17`. One `cachesim_sweep` call takes one
   address mapper, so grids are written one file per `cin_block`
   (`src/lays/cachesim/grid.py:51-54`) and the pipeline runs one sweep per file
   (`scripts/pipeline.py:368-376`).
7. `FLITS_PER_PACKET = 4` has one source,
   `src/lays/nocsim/eventsim/constants.h:5`; `src/lays/nocsim/core/transaction.py:28-37`
   parses it at import, and `tests/test_flits_per_packet.py` checks the built
   binary agrees.
8. Data kept outside git lives under `$NEURO_CACHE_DATA` (default
   `<repo>/data`, fallback not logged) via `data_root()` (`src/lays/util.py:15`,
   :23-24); the pipeline writes to `data_root()/demo/<bench>` by default
   (`scripts/pipeline.py:313`). Every CLI resolves its repo-relative defaults
   from `__file__` except `lays.scheduler solve`/`enumerate`, whose defaults are
   cwd-relative (`src/lays/scheduler/cli.py:22-25`).
9. Dependency direction: the pipeline produces the schedule JSON
   (`src/lays/scheduler/artifact.py:101-104`), the step-cycles file nocsim reads
   (`src/lays/nocsim/step_cycles.py:27`, read at `src/lays/nocsim/sim.py:335-337`) and the
   WCTS stream the cache simulator reads (`src/lays/cachesim/stream.py:178`). The
   two simulators never call each other; their numbers meet only in
   `scripts/pipeline.py:394`. The Python packages import each other in both
   directions (`lays.scheduler` <-> `lays.weight_trace_gen` <-> `lays.nocsim`; pipeline.md
   1.4); the C++ in `src/lays/cachesim/native` and `src/lays/nocsim/eventsim` depends on
   no Python.
10. Build and reproduce: GNU make, C++17, no CMake. `make build`
    (`Makefile:5-8`) builds the cache simulator apps, eventsim and `loasgen`;
    in `src/lays/cachesim/native`, `make release` builds only the library
    (`src/lays/cachesim/native/Makefile:182-183`), so the apps need `make
    MODE=release apps`, which is what `src/lays/cachesim/cli.py:23` and
    `scripts/pipeline.py:333` run. A Gurobi license is needed only to solve:
    the tracked schedules in `examples/schedules/loas` cover V8, V9, R9 and R16,
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
| 2 | `solve_best_schedule` | `src/lays/scheduler/solve.py:271` |
| 3 | `solve_and_cache_schedule` | `src/lays/scheduler/artifact.py:49` |
| 4 | `reconstruct_samples` | `src/lays/weight_trace_gen/weight_trace.py:163` |
| 5 | `run_stream` | `src/lays/weight_trace_gen/cli.py:301` |
| 6 | `stream_weight_trace` | `src/lays/cachesim/stream.py:178` |
| 7 | `decode_header` | `src/lays/cachesim/native/include/cachesim/trace/stream_format.h:208` |
| 8 | `StreamingTileTrace::advance` | `src/lays/cachesim/native/src/trace/stream_trace.cpp:176` |
| 9 | `detail::expand_burst` | `src/lays/cachesim/native/src/layout/layout_common.h:120` |
| 10 | `validate` | `src/lays/cachesim/native/src/config.cpp:542` |
| 11 | `Engine::run_to_barrier` | `src/lays/cachesim/native/src/core/engine.cpp:148` |
| 12 | `CacheLevel::triage` | `src/lays/cachesim/native/src/core/cache_level.cpp:115` |
| 13 | `schedule_from_strategy` | `src/lays/nocsim/schedule/decode.py:238` |
| 14 | `iter_node_tiles` | `src/lays/nocsim/schedule/tiles.py:98` |
| 15 | `combine` | `src/lays/nocsim/combine.py:120` |
| 16 | `simulate` | `src/lays/nocsim/eventsim/EventSim.h:54` |

**Full pass.** Every section of every file, in the order cachesim_native.md
-> pipeline.md -> nocsim.md. cachesim_native comes first because it stands
alone: its C++ consumes only WCTS and depends on no other code. The pipeline
comes next because it produces every simulator input, WCTS included. nocsim
comes last: it imports `weight_trace_gen` and reads the pipeline's
step-cycles files. `lays.scheduler` and `lays.weight_trace_gen` import
`lays.nocsim.schedule` back (fact 9), but only `schedule_from_strategy` and
`iter_node_tiles`, which can be read as black boxes on the first pass.
