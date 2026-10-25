# Code atlas index

Commit: 8fa0916 (branch wcache-rebuild-phase-a). Built only from reading code (.py/.cpp/.h/.sh/Makefile/.yaml/.json); no .md/.txt/log files were read.

| File | Scope |
|---|---|
| [wcache_native.md](wcache_native.md) | src/wcache/native C++ cache simulator, wcache_run / wcache_sweep, native_v1_archive, src/wcache/*.py |
| [nocsim.md](nocsim.md) | src/nocsim (schedule -> NoC transactions -> eventsim makespan) and src/cachesim |
| [pipeline.md](pipeline.md) | tracegen, parsers, archmodels, mip_solver, scripts/, tests/, configs/, input_trace/, the 13 profiling stages |

## 10 cross-cutting facts

1. End-to-end flow: input trace (`meta.json` + uint8 `.npy` `[T,B,Cin,Hin,Win]`) -> Gurobi MIP (`scripts/solve_schedules.py`) -> schedule JSON -> `scripts/generate_weight_traces.py` -> `LayerWeightTrace`, written either as gzip JSON (read by `python -m nocsim.sim --simulate`) or as a binary stream piped into `wcache_sweep --trace -` (profiling/0820*/run_sweep.py:251-253) -> per-unit CSV -> merged CSV + HTML page.
2. nocsim is the baseline: its C++ `eventsim` makespan is the denominator of wcache's `speedup_vs_nocsim`. `nocsim.schedule` is also a library used by `src/tracegen.py`, so editing it changes the weight traces that wcache reads.
3. src/cachesim is the predecessor of wcache (sibling of nocsim, no imports between them); its only live caller is profiling/0803_l1_l2_cache. native_v1_archive is referenced by no code file.
4. wcache builds with GNU make (src/wcache/native/Makefile, C++17, no third-party libs; there is no CMakeLists.txt). `make release` builds only the library (Makefile:205-206); the CLIs need `make MODE=release apps`. The engine is event-driven with a fixed tie-break order, so runs repeat exactly.
5. Runnable today without Gurobi: 4 LoAS layers x 5 samples, using the schedules tracked under profiling/0823_stagewise_verify, plus the 0820 fixture grids. Pass `--sample-start/--sample-count` in 0-4; the default `--n-samples 100` draws indices from range(10000), which are out of range for the stored B=5 arrays.
6. Cleanup 1: dead code, e.g. nocsim `get_deps`/`write_deps`, `lif_hist` (src/nocsim/combine.py:512, written but never read), pipeline `tick_entries_from_flat`/`build_Z`, wcache's never-built `u19_check.cpp`, and a dead store at src/wcache/native/src/config.cpp:718-720 that line 727 overwrites.
7. Cleanup 2: logic copied across files: wcache's 3 layouts (block_pack/split_cin/khkw_split) repeat the same helpers and `expand`/`locate` bodies; the profiling stages repeat next-layer COUT (8x), `tags()` (8x), and the base config (15+); constants like FLITS_PER_PACKET=4 are kept in sync by hand between Python and C++.
8. Cleanup 3: possible bugs to triage before refactoring: `wcache_run --out` overwrites the file while the header logic assumes appending (app_support.h:292 vs wcache_run.cpp:252); `l2_pf_timely` always equals `l2_pf_retriggers` (engine.cpp:423-424); stream_trace.cpp:302-303 decodes bursts on non-COUT axes wrongly; docstrings are stale (e.g. profiling/0907_assoc/run_sweep.py says 8 points, but the grid has 12).
9. Cleanup 4-5: about 312 MB of run outputs are tracked in git under profiling/0823_stagewise_verify; the mapspace config is parsed but has no effect.
10. Reproducibility blockers: (a) missing inputs: full `*_T4_all` captures, `outputs/schedules/*`, `outputs/weight_traces`, and the 16 GB untracked 0831_all_layer_streams that every stage after 0831 needs; (b) 23 .py/.sh files hardcode `/u/yyu9` or `/work/hdd/bebv` paths, scripts assume the repo root as cwd with PYTHONPATH=src, and conda env names disagree (`base` vs `cosa_snn`); (c) Gurobi license required, with no Threads/Seed set, and the eventsim binary on disk (dated 2026-08-20) predates its source change (ba468ed), so it must be rebuilt.
