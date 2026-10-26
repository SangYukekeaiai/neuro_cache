# Code atlas index

Commit: 39efd64 (branch wcache-rebuild-phase-a); the previous version of this atlas described 8fa0916. Built only from reading code (.py/.cpp/.h/.sh/Makefile/.yaml/.json) and `git diff` of it; no .md/.txt/log files were read. Paths are relative to the repo root.

**Stored WCTS version-1 streams are rejected by the HEAD reader** (src/wcache/native/include/wcache/stream_format.h:221-228, `kFormatVersion = 2` at :42) and must be regenerated with src/tracegen.py, e.g. `scripts/generate_weight_traces.py --stream`.

| File | Lines | Scope |
|---|---|---|
| [wcache_native.md](wcache_native.md) | 1059 | src/wcache/native C++ cache simulator (libwcache.a, wcache_run / wcache_sweep, tests), the WCTS v2 wire format, src/wcache/examples/*.py |
| [pipeline.md](pipeline.md) | 1148 | tracegen, util, parsers, archmodels, mip_solver, scripts/, configs/, input_trace/, tests/, profiling/common.py and the 13 profiling stages |
| [nocsim.md](nocsim.md) | 453 | src/nocsim (schedule -> NoC transactions -> eventsim makespan) and src/cachesim (predecessor of wcache) |

## 10 cross-cutting facts

1. WCTS v2 burst record is `[kh, kw, cin, cout, run_end]`: the reader sets `anchor = Coord{kh, kw, cin, cout}`, `run_start = coord_on(anchor, burst_dim)` and refuses `run_end <= run_start` (src/wcache/native/src/stream_trace.cpp:288-305), so bursts on every axis decode. Version 1 is refused; every `.wcts` written before 725474f is v1, including the 155 untracked files in profiling/0831_all_layer_streams/streams/ (wcache_native.md 1.7, pipeline.md top note).
2. The three mappers (block_pack, split_cin, khkw_split) share their checks, burst walk (`detail::expand_burst`) and placement through src/wcache/native/src/layout_common.h / .cpp; src/wcache/native/tests/test_layout_golden.cpp pins the mapping with 185 cases, each folded into one FNV-1a hash (wcache_native.md 2.2, 2.4).
3. wcache output: `wcache_run` writes the CSV header by default and `--no-header` turns it off (src/wcache/native/apps/wcache_run.cpp:141, :184-185); `l2_pf_timely` always equals `l2_pf_retriggers`, since src/wcache/native/src/engine.cpp:423-424 increments both at one site, as engine.h:265 and stats.cpp:362 now state.
4. L2 MSHR floor: an unset `l2_demand_reserve` (-1) resolves to `lines_per_burst` and must stay below `l2_mshrs` (default 20, src/wcache/native/include/wcache/config.h:71), else `validate` refuses the config (src/wcache/native/src/config.cpp:629-636).
5. Data kept outside git lives under `$NEURO_CACHE_DATA` (default `<repo>/data`, fallback not logged) via `data_root()` (src/util.py:15). Scripts and profiling drivers find the repo root from `__file__`; still cwd-relative: `python -m mip_solver` (src/mip_solver/cli.py:20-24) and `python -m nocsim.sim` (run from the repo root with `PYTHONPATH=src`), plus five dump/scripts files (pipeline.md 1.6, 3.4).
6. profiling/common.py holds the wcache base config (`BASE`, `base_config` :28), `tags()` :42 and `next_cin_for` :53 (next layer's CIN); 20 driver files in 9 stage directories import it (pipeline.md 2.9.1).
7. `FLITS_PER_PACKET = 4` has one source, src/nocsim/eventsim/constants.h:5; src/nocsim/core/transaction.py:28-37 parses it at import, and tests/test_flits_per_packet.py checks it.
8. nocsim is the baseline: profiling drivers parse the eventsim makespan `total_cycles` from `python -m nocsim.sim --simulate` stdout into CSV/JSON that later stages read to report wcache as a speedup over nocsim; that CSV is the only link, and no wcache code calls nocsim (nocsim.md 1.3). The C++ in src/wcache/native has no code dependency on Python in either direction: Python reaches it only as the wcache_run / wcache_sweep binaries (its test helper src/wcache/examples/to_stream.py calls tracegen). src/cachesim is wcache's predecessor and has no imports to or from nocsim (nocsim.md 3.1).
9. Dependency direction: the Python pipeline (mip_solver via scripts/solve_schedules.py, tracegen, scripts/generate_weight_traces.py) produces schedule JSON, weight-trace `.json.gz` (read by nocsim through `tracegen.load_step_cycles`, src/nocsim/sim.py:335) and WCTS streams (piped into `wcache_sweep --trace -`, profiling/0820_phaseD_spad_vs_cache/run_sweep.py:249-254); the simulators emit CSV/stdout that profiling drivers read back. nocsim and the pipeline import each other: src/tracegen.py:39-40 and src/archmodels/dense.py:18 import nocsim.schedule; src/nocsim/combine.py:74-77 and src/nocsim/sim.py:49 import archmodels at module top, and sim.py:335 imports tracegen lazily.
10. Build and reproduce: GNU make only (no CMakeLists.txt, C++17, no third-party libraries); `make release` builds only libwcache.a (src/wcache/native/Makefile:206-207), the CLIs need `make MODE=release apps`. Any solve needs a Gurobi license (not needed to reuse cached schedules); input captures, outputs/schedules and outputs/weight_traces are not in git (wcache_native.md 4, pipeline.md 4).

## Reading guide

**30-minute pass (overall structure).** This README's facts, then in each file the top note and the first three subsections of "1. Top-down": wcache_native.md 1.1 Purpose, 1.2 Entry points, 1.3 Data flow (one `wcache_run`); pipeline.md 1.1 Purpose, 1.2 Entry points, 1.3 End-to-end data flow; nocsim.md 1.1 Purpose, 1.2 Entry points, 1.3 Who calls nocsim.

**2-hour pass (how each component works).** The rest of "1. Top-down" in each file (wcache_native.md 1.4-1.7, pipeline.md 1.4-1.7, nocsim.md 1.4-1.6), then these 15 functions in the code, with their "2. Bottom-up" entries:

| # | Function | Location |
|---|---|---|
| 1 | `decode_header` | src/wcache/native/include/wcache/stream_format.h:208 |
| 2 | `StreamingTileTrace::advance` | src/wcache/native/src/stream_trace.cpp:176 |
| 3 | `detail::expand_burst` | src/wcache/native/src/layout_common.h:120 |
| 4 | `validate` | src/wcache/native/src/config.cpp:521 |
| 5 | `Engine::run_to_barrier` | src/wcache/native/src/engine.cpp:128 |
| 6 | `CacheLevel::triage` | src/wcache/native/src/cache_level.cpp:112 |
| 7 | `solve_best_schedule` | src/mip_solver/solve.py:281 |
| 8 | `tracegen.solve_and_cache_schedule` | src/tracegen.py:72 |
| 9 | `tracegen.reconstruct_samples` | src/tracegen.py:294 |
| 10 | `tracegen.stream_weight_trace` | src/tracegen.py:642 |
| 11 | `run_stream` | scripts/generate_weight_traces.py:293 |
| 12 | `schedule_from_strategy` | src/nocsim/schedule/decode.py:238 |
| 13 | `iter_node_tiles` | src/nocsim/schedule/tiles.py:99 |
| 14 | `combine` | src/nocsim/combine.py:120 |
| 15 | `simulate` | src/nocsim/eventsim/EventSim.h:54 |

**Full pass.** Every section of every file, in the order wcache_native.md -> pipeline.md -> nocsim.md. wcache_native comes first because it stands alone: its C++ consumes only WCTS and depends on no other code. The pipeline comes next because it produces every simulator input, WCTS included. nocsim comes last: it imports pipeline modules (archmodels, tracegen) and reads the pipeline's weight traces. The pipeline does import nocsim.schedule back (fact 9), but only `schedule_from_strategy` and `iter_node_tiles`, which can be read as black boxes on the first pass and are covered in nocsim.md 2.4.
