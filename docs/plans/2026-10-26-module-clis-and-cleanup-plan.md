# Module CLIs, one end-to-end driver, repo cleanup — Implementation Plan (v2, 2026-10-26)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Commits are made ONLY from the main session (git inside subagents hangs on permission prompts); workers stop before `git add`.

**Goal:** The four pipeline modules are named as in the paper draft (`2027_ASPLOS_neuro_cache`): `snn_scheduler`, `weight_trace_gen`, `nocsim`, `cachesim`. Each is driven by its own `python -m <module>` CLI; `src/tracegen.py` disappears into the modules that own its pieces; `scripts/` shrinks to one end-to-end driver plus the data-prep tool; everything dead, duplicated, or unrelated is deleted.

**Architecture:** Renames first (pure `git mv` + import rewrite), then the tracegen split (pure move), then CLI absorption per module, then the driver, then deletion, then docs. The acceptance gate after every task is `data/demo/loas/results.csv` byte-identical to the snapshot taken in Task 0, so nothing in this plan may change a number.

**Tech stack:** Python 3.12 in `.baseline/venv`, argparse, pytest; C++17 native pieces unchanged (`loasgen` and the other four `*gen`, `eventsim`, the cache simulator library and apps).

## Global Constraints

- Numbers never change: `results.csv` byte-identical after each task; `python scripts/pipeline.py --verify-baseline` passes at the end.
- Commits local only, never push. One commit per task, from the main session, with explicit paths; never `git add -A`.
- `gurobi.lic` content never printed or copied. `GRB_LICENSE_FILE=/home/ya867177/gurobi.lic` when solving.
- Behaviour-preserving: no new features beyond the CLIs themselves, `--layers all`, and the cache base config file.
- The WCTS magic `WCTRACE1`, the stream format, and the schedule JSON `result` block do not change (on-disk artifacts and `.baseline/` must stay readable).
- `docs/atlas/` stays the home of code documentation; cite `file:line`.

## Decisions (all taken 2026-10-26)

- **D1** `pyproject.toml` + `pip install -e .` into `.baseline/venv`; drop the 30+ `sys.path.insert` lines.
- **D2** Delete all of `profiling/` after moving its load-bearing inputs (recoverable with `git checkout d1b5e3d -- profiling/<dir>`); delete the ignored 16 GB `profiling/0831_all_layer_streams/streams/` from disk.
- **D3** Commit the three untracked notes first (`log/2026-09-22-gem5-prefetch-to-demand-upgrade.md`, `log/2026-09-22-l1-prefetch-vs-gem5-survey.md`, `profiling/0907_index_policy/PROGRESS.md`) so history keeps them, then delete `log/` and `profiling/`.
- **D4** Drop `scripts/profile_all_layers.py` + `scripts/slurm/`; `pipeline.py --layers all` covers it.
- **D5** Keep all five core models (loas, ptb, spinalflow, prosperity, gustavsnn), their native bridges, binaries and configs.
- **D6** Delete `configs/arch/multinode_sweep/` (400 generated yamls).
- **D7** Thin `python -m cachesim` wrapper over the native binaries, plus the grid generator.
- **D8 (DECIDED 2026-10-26: full rename)** Cache simulator rename covers everything: directory `src/wcache/` → `src/cachesim/`, Python `python -m cachesim`, app sources and binaries `wcache_run`/`wcache_sweep` → `cachesim_run`/`cachesim_sweep`, atlas `wcache_native.md` → `cachesim_native.md`, C++ `namespace wcache` → `namespace cachesim` (72 files), header dir `include/wcache/` → `include/cachesim/` with every `#include "wcache/..."` rewritten, library `libwcache.a` → `libcachesim.a`, Makefile variables. NOT changed: the on-disk WCTS magic `WCTRACE1` and format (streams in `.baseline/` and `data/` must stay readable).
- **D9 (new)** `configs/mapspace/mapspace.yaml`, `src/parsers/mapspace.py` and the `--mapspace` flag are deleted: `solve.py:77-79` says no constraint or objective reads the mapspace, and the pipeline path (`solve_and_cache_schedule`) never passes one. The freed name is used for `configs/node_mapspace/` (the paper's "node mapspace", today's `configs/dataflow/`).
- **D10 (new)** `configs/cache/` becomes the cache simulator's configuration: `base.json` (the khkw_split base point: 64 B line = cin_block 16 × cout_block 4 × 1 B, L1 16 KB 8-way lat 0, L2 512 KB 16-way lat 2 miss 24 32 MSHRs, no prefetch) and `khkw_sweep.json` (the axes: line_bytes [16,32,64], l2_banks [1,2,4,8], prefetch [none, next_burst 1/2/4]). `python -m cachesim grid` reads both. The two old `cache_config*.yaml` (cachesim-v0 readers, dead) are deleted.

## Facts the plan rests on (verified 2026-10-26 at d1b5e3d; paths as they are BEFORE Task 1)

- `src/tracegen.py` (764 lines) holds four unrelated groups: schedule artifact (:50-172, Gurobi via lazy import at :101), weight-trace data model + assembly (:175-350, :733-764), step-cycles file (:353-522, written by the trace generator, read only by `nocsim/sim.py:336`), WCTS v2 writer (:553-730, read only by the cache simulator's C++). `tick_entries_from_flat` (:249) has no caller.
- Existing CLIs: `python -m mip_solver {solve,enumerate}` (`cli.py:41`, workload-YAML in); `python -m nocsim.sim` (`sim.py:258`, no `__main__.py`); native `loasgen <trace.bin> <task.bin> <out.bin>`; native `wcache_run`/`wcache_sweep`. `src/archmodels` has no Python CLI; `scripts/generate_weight_traces.py` (428 lines) is it.
- `scripts/demo.py` imports from `profiling/`: `0823_stagewise_verify/stage4_wcache/run_khkw_sweep.py` (grid `grid_for`, `BIN`, `TAGS`, `SAMPLES`, `LINE_BYTES`), `stage3_nocsim/run_stage3.py` (`ARCH_YAML`), `profiling/common.py` (`BASE`, `KHKW_KEYS`, `tags`, `INPUT_TRACE`), and `scripts/wcache_baseline.py` (`SCHEDULES` = tracked schedules under 0823 stage2).
- Latent bug: `scripts/solve_schedules.py:35` solves with `configs/arch/loas.yaml` (single_node, 1 instance, DRAM_LATENCY 0.25) but every tracked schedule records `profiling/0823_stagewise_verify/stage1_mip_solver/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml` (16 nodes × 16 PEs, weight buffer 30720, DRAM_LATENCY 17), which is also nocsim's arch. `configs/dataflow/loas.yaml` is identical to the 0823 copy.
- Paper terminology (`/home/ya867177/2027_ASPLOS_neuro_cache/src/05_theory.tex:40-47,59-65`): "SNN scheduler" takes "the workload, the node mapspace, and the hardware configuration"; "weight-trace generator"; "NoC simulator"; "cache simulator".
- No pyproject/conftest: 30+ files do `sys.path.insert(0, ROOT/"src")`.
- Markdown: 109 tracked `.md`. Load-bearing: `README.md`, `docs/REPRODUCE.md`, `docs/atlas/{README,pipeline,nocsim,wcache_native}.md`, `input_trace/README.md`.
- Dangling code comments that cite files to be deleted: `src/wcache/native/include/wcache/config.h:93`, `native/tests/test_config.cpp:180`, `stamp_policy.h:120`, `next_use.h:3`, `access_log.h:3,8`, `native/tests/test_stamp_policy.cpp:897`, `native/tests/sweep_cli.sh:187`, `native/apps/wcache_run.cpp:111`, `src/mip_solver/constraints/node_level.py:28`, `src/tracegen.py:9,200,226,250,531`, `src/nocsim/schedule/tiles.py:58,106`, `src/nocsim/combine.py:214`, `src/archmodels/**/native_bridge.py` and `*Gen.h` (dump/python_reference). `src/wcache/native/Makefile:160` `test-cli` needs an importable `tracegen` (via `examples/to_stream.py`).
- Tests: 8 proper pytest modules; 4 script-style files produce the 17 "errors" and read data that no longer exists; 2 files collect 0 items; 2 shell tests point at missing data.

## Target layout (names AFTER Task 1)

```
pyproject.toml, conftest.py       pip install -e . → python -m <module> works from any cwd
src/
  parsers/  (arch, bitwidths, dataflow→renamed node_mapspace.py, layer)   util.py
  snn_scheduler/     python -m snn_scheduler {solve, enumerate, solve-trace}     (was mip_solver)
    artifact.py        ScheduleArtifact, solve_and_cache_schedule, read_artifact, check_schedule_matches_trace
  weight_trace_gen/  python -m weight_trace_gen gen                             (was archmodels)
    cli.py, weight_trace.py, trace.py, dense.py, loas/ ptb/ spinalflow/ prosperity/ gustavsnn/
  nocsim/            python -m nocsim                                           (unchanged name)
    __main__.py, step_cycles.py
  cachesim/          python -m cachesim {grid, sweep, run}                      (was wcache)
    cli.py, grid.py, stream.py, examples/, native/ (apps cachesim_run.cpp, cachesim_sweep.cpp)
scripts/
  pipeline.py, subset_input_traces.py
configs/
  arch/<arch>*.yaml            hardware configuration (incl. loas_inst16_node32kb.yaml, moved from profiling)
  node_mapspace/<arch>.yaml    was dataflow/
  cache/base.json, cache/khkw_sweep.json
  schedules/loas/<wl>/<layer>.json   tracked schedules (moved from profiling)
  workloads/sample_snn_layer.yaml    (python -m snn_scheduler solve default)
```

## Review Focus

1. A layer the tracked schedules do not cover: `solve-trace` must use `configs/arch/loas_inst16_node32kb.yaml`, the same file nocsim gets, never `configs/arch/loas.yaml`. Test in Task 3.
2. `python -m weight_trace_gen gen --stream` to stdout must stay byte-identical to the old `generate_weight_traces.py --stream`. Test in Task 4.
3. `nocsim` must refuse the old full weight-trace JSON and accept the slim step-cycles file exactly as before. Test in Task 5.
4. `python -m cachesim grid` must emit the same 48 configs in the same order as `run_khkw_sweep.grid_for` for 16/32/64 B, now derived from `configs/cache/*.json`. Test in Task 6.
5. `pipeline.py` with the default layers must write a `results.csv` byte-identical to the snapshot and pass `--verify-baseline`. Test in Task 7.

---

### Task 0: Snapshot the gate

- [ ] Copy `data/demo/loas/results.csv`, `summary.md`, `grid/khkw_{0,1,2}.json` to `<scratchpad>/gate/`; record `sha256sum` of `results.csv` and of `data/demo/loas/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts`.
- [ ] Record `.baseline/venv/bin/python -m pytest tests -q 2>&1 | tail -3` (expected: 86 passed, 17 errors).
- [ ] D3 commit (main session): `git add` the three untracked notes; commit `notes: track the September prefetch notes and 0907 progress before removal`.

### Task 1: Renames and the installable package (no behaviour change)

**Files:**
- `git mv src/mip_solver src/snn_scheduler`; `git mv src/archmodels src/weight_trace_gen`; `git mv src/wcache src/cachesim`; `git mv src/cachesim/native/apps/wcache_run.cpp .../cachesim_run.cpp`, same for `wcache_sweep.cpp`; `git mv src/cachesim/native/include/wcache src/cachesim/native/include/cachesim`; sed `namespace wcache` → `namespace cachesim`, `wcache::` → `cachesim::`, `#include "wcache/` → `#include "cachesim/`, `libwcache` → `libcachesim` across `src/cachesim/native/**` [D8]; `git mv configs/dataflow configs/node_mapspace`; `git mv src/parsers/dataflow.py src/parsers/node_mapspace.py`; `git mv docs/atlas/wcache_native.md docs/atlas/cachesim_native.md`.
- Delete: `configs/mapspace/`, `src/parsers/mapspace.py`, `configs/cache/cache_config.yaml`, `configs/cache/cache_config_tiny.yaml` [D9, D10].
- Modify: every `import mip_solver|archmodels|wcache`, every `parsers.dataflow`/`parsers.mapspace` import, `--mapspace` flag + `mapspace` handling in `snn_scheduler/{cli,solve,enumerator}.py` (drop; the `"mapspace"` key in `result["configs"]` goes too), `configs/dataflow` strings in `scripts/*.py` and `profiling/common.py` is NOT touched (deleted later; demo keeps working through `wcache_baseline` → fix its `sys.path` entries to the new dirs), `src/cachesim/native/Makefile:100-116` binary names, `demo.py:311-314` make targets, `.gitignore` binary paths (`src/archmodels/...` → `src/weight_trace_gen/...`), `native/tests/*.sh` binary names, `src/weight_trace_gen/__init__.py` `ARCH_NATIVE_BRIDGES` module strings.
- Create: `pyproject.toml` (`[project] name="neuro-cache"`, `[tool.setuptools.packages.find] where=["src"]`, `py-modules=["util","tracegen"]` until Task 2 removes tracegen), `conftest.py` (adds `scripts/` to `sys.path`). Remove `sys.path.insert(0, ROOT/"src")` in `scripts/` and `tests/`.

- [ ] `.baseline/venv/bin/pip install -e .`; from `/`: `python -c "import snn_scheduler, weight_trace_gen, nocsim, cachesim, parsers, util, tracegen"` prints nothing.
- [ ] `grep -rn "mip_solver\|archmodels\|import wcache\|from wcache\|parsers.dataflow\|parsers.mapspace\|configs/dataflow\|configs/mapspace" src scripts tests Makefile .gitignore` → no hits (profiling/ and docs/ excluded; they are deleted/rewritten later).
- [ ] `make -C src/cachesim/native MODE=release apps test test-cli` passes; `make -C src/nocsim/eventsim`; `make -C src/weight_trace_gen/loas`.
- [ ] `pytest tests -q` → 86 passed, 17 errors (unchanged).
- [ ] `python scripts/demo.py --layers R9 --sample-count 1 --out <scratch>/t1`; its 48 rows equal the matching gate rows.
- [ ] Commit: `refactor: rename packages to the paper's names (snn_scheduler, weight_trace_gen, cachesim), dataflow→node_mapspace, drop unused mapspace; installable src/`.

### Task 2: Split `src/tracegen.py` into module-owned files (pure move)

**Files:**
- Create: `src/snn_scheduler/artifact.py` (tracegen :50-172; `load_schedule` → `read_artifact(path) -> ScheduleArtifact`, no tiles expansion).
- Create: `src/weight_trace_gen/weight_trace.py` (tracegen :175-350 minus `tick_entries_from_flat`, plus :733-764, plus `load_schedule(path) -> (ScheduleArtifact, SNNProb, List[NodeTileSpec])` built on `read_artifact` + `schedule_from_strategy` + `iter_node_tiles`).
- Create: `src/nocsim/step_cycles.py` (tracegen :353-522).
- Create: `src/cachesim/__init__.py`, `src/cachesim/stream.py` (tracegen :553-730).
- Modify importers: the five `native_bridge.py` (lazy `assemble_layer_traces`), `src/nocsim/sim.py:336`, `src/cachesim/examples/to_stream.py`, `scripts/{demo,generate_weight_traces,solve_schedules,solve_inst16_subset,profile_all_layers}.py`, `tests/{test_tracegen,test_stream_writer,test_step_cycles,test_combine_cycles_table}.py`; drop `tracegen` from `pyproject.toml` py-modules.
- Delete: `src/tracegen.py`.

**Interfaces produced:** `snn_scheduler.artifact.{ScheduleArtifact, solve_and_cache_schedule, read_artifact, check_schedule_matches_trace}`; `weight_trace_gen.weight_trace.{LayerWeightTrace, TileWeightTrace, TickEntry, CoreEntry, assemble_layer_traces, reconstruct_samples, load_schedule, sample_indices}`; `nocsim.step_cycles.{save_step_cycles, load_step_cycles, StepCycles, STEP_CYCLES_FORMAT}`; `cachesim.stream.{stream_weight_trace, write_stream_header, write_tile_frame, write_stream_trailer, WCTS_*}`.

- [ ] `grep -rn "tracegen" src scripts tests Makefile pyproject.toml` → only comments (fixed in Task 9).
- [ ] `make -C src/cachesim/native MODE=release test-cli` passes.
- [ ] `pytest tests -q` → 86 passed, 17 errors.
- [ ] `demo.py --layers R9 --sample-count 1` rows == gate rows.
- [ ] Commit: `refactor: split tracegen into snn_scheduler.artifact, weight_trace_gen.weight_trace, nocsim.step_cycles, cachesim.stream`.

### Task 3: `python -m snn_scheduler solve-trace` absorbs `scripts/solve_schedules.py`

**Files:**
- Modify: `src/snn_scheduler/cli.py` (new subparser `solve-trace`; handler calls `artifact.solve_and_cache_schedule`).
- Move: `profiling/0823_stagewise_verify/stage1_mip_solver/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml` → `configs/arch/loas_inst16_node32kb.yaml`; `profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules/loas/**` → `configs/schedules/loas/**`.
- Modify: `scripts/demo.py:258-262` (call the new CLI with `--arch-yaml configs/arch/loas_inst16_node32kb.yaml`), `scripts/wcache_baseline.py:28` (`SCHEDULES = configs/schedules`).
- Delete: `scripts/solve_schedules.py`, `scripts/solve_inst16_subset.py`.
- Test: `tests/test_snn_scheduler_cli.py` (new).

**Interfaces produced:** `python -m snn_scheduler solve-trace --arch NAME [--arch-yaml PATH] [--node-mapspace PATH] --trace-root DIR --trace-dirs D... [--layers L...] --cache-dir DIR [--force]`; writes `<cache-dir>/<arch>/<trace_dir>/<layer>.json` + `summary.csv`; exit 1 if any layer failed. Defaults: loas `--arch-yaml` = `configs/arch/loas_inst16_node32kb.yaml`, other archs `configs/arch/<arch>.yaml`; `--node-mapspace` = `configs/node_mapspace/<arch>.yaml`.

- [ ] Tests: `test_solve_trace_skips_cached` (pre-seeded cache → exit 0, file unchanged, no gurobipy needed); `test_default_arch_yaml_is_the_16_node_one`.
- [ ] Run → FAIL; implement; run → PASS.
- [ ] `GRB_LICENSE_FILE=/home/ya867177/gurobi.lic python -m snn_scheduler solve-trace --arch loas --trace-root input_trace/loas --trace-dirs resnet19_T4_n5 --layers layer_09_layer2_0_conv2 --cache-dir <scratch>/t3 --force`; the JSON `result` block equals `configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json`'s except recorded paths. If it differs, stop and report.
- [ ] `demo.py --layers R9 --sample-count 1` rows == gate rows.
- [ ] Commit: `feat(snn_scheduler): solve-trace subcommand; schedules and the loas arch yaml move to configs/`.

### Task 4: `python -m weight_trace_gen gen` absorbs `scripts/generate_weight_traces.py`

**Files:**
- Create: `src/weight_trace_gen/__main__.py`, `src/weight_trace_gen/cli.py` (body of the script; `parse_args` kept; subcommand `gen`; `--schedule-cache` default `configs/schedules`).
- Modify: `scripts/demo.py:317`, `scripts/wcache_baseline.py:40`, `scripts/profile_all_layers.py:84`, `tests/test_tracegen.py:16` → rename `tests/test_weight_trace_gen_cli.py`, `tests/test_stream_dump.py:20`, `src/nocsim/sim.py:295` help, `src/weight_trace_gen/trace.py:51` comment.
- Delete: `scripts/generate_weight_traces.py`.

**Interfaces produced:** `python -m weight_trace_gen gen --arch loas --trace-root DIR --trace-dir D --layer L [--schedule-cache DIR] [--out-dir DIR | --stream [--dump-trace PATH]] [--sample-start N --sample-count N | --n-samples N --seed S] [--workers N] [--force]`.

- [ ] Test `test_stream_is_byte_identical_to_snapshot` (R9 sample 0 `--stream` sha == Task 0 sha).
- [ ] Run → FAIL; move code; run → PASS; `pytest tests -q` counts unchanged.
- [ ] `demo.py --layers R9 --sample-count 1` rows == gate rows.
- [ ] Commit: `feat(weight_trace_gen): python -m weight_trace_gen gen replaces scripts/generate_weight_traces.py`.

### Task 5: `python -m nocsim`

- Create `src/nocsim/__main__.py`; `sim.py:258` `prog="python -m nocsim"`; `demo.py:341` command.
- [ ] Tests `tests/test_nocsim_cli.py`: `test_rejects_old_full_trace_format`, `test_dash_m_nocsim_help`. FAIL → implement → PASS.
- [ ] Commit: `feat(nocsim): python -m nocsim entry point`.

### Task 6: `python -m cachesim {grid, sweep, run}`; cache config in `configs/cache/` [D7, D10]

**Files:**
- Create: `configs/cache/base.json` (= `profiling/common.py` BASE, same keys and values, in `KHKW_KEYS` order), `configs/cache/khkw_sweep.json` (`{"line_bytes":[16,32,64],"cout_block":4,"weight_bytes":1,"l2_banks":[1,2,4,8],"prefetch":[["none",0],["next_burst",1],["next_burst",2],["next_burst",4]]}` — the worker reads `run_khkw_sweep.grid_for` to confirm the exact axes before writing).
- Create: `src/cachesim/grid.py` (`load_base(path)`, `grid_for(line_bytes, base, sweep)`, `write_grid(out_dir, base_path, sweep_path) -> dict[cin_block, path]` writing `khkw_{0,1,2}.json` exactly as `demo.py:343-355` does), `src/cachesim/__main__.py`, `src/cachesim/cli.py` (`grid --out DIR [--base configs/cache/base.json] [--sweep configs/cache/khkw_sweep.json]`; `sweep`/`run` forward unknown args to `src/cachesim/native/build/release/cachesim_{sweep,run}`, building with `make -C src/cachesim/native MODE=release apps` when missing).
- Modify: `scripts/demo.py` grid/`sweep.BIN`/`TAGS` uses, `scripts/wcache_baseline.py`.

- [ ] Tests `tests/test_cachesim_grid.py`: `test_grid_matches_0823_sweep` (vs `profiling/.../run_khkw_sweep.grid_for`, deleted in Task 9), `test_grid_files_equal_demo_grid` (== gate `khkw_{0,1,2}.json`). FAIL → implement → PASS.
- [ ] `python -m cachesim sweep --help` prints the native usage.
- [ ] `demo.py --layers R9 --sample-count 1` rows == gate rows.
- [ ] Commit: `feat(cachesim): python -m cachesim grid|sweep|run; base config and sweep axes in configs/cache`.

### Task 7: `scripts/pipeline.py` replaces `demo.py`, `wcache_baseline.py`, `profile_all_layers.py`

- Create `scripts/pipeline.py` from `demo.py` (≤ 300 lines): no `profiling/` or `wcache_baseline` imports; `tags()` moves in; `NOCSIM_ARCH["loas"] = configs/arch/loas_inst16_node32kb.yaml`; `SCHEDULES = configs/schedules`; the four stages are `python -m snn_scheduler solve-trace`, `python -m weight_trace_gen gen`, `python -m nocsim --simulate`, `python -m cachesim sweep`; flags as today plus `--layers all`.
- Modify `Makefile` (`build`, `demo`, `test`), `tests/test_demo.py` → `tests/test_pipeline.py` (+ `test_summary_lists_module_commands`).
- Delete `scripts/{demo,wcache_baseline,profile_all_layers}.py`, `scripts/slurm/`, `scripts/env.sh`, `scripts/tmp/`, `tests/test_profile_all_layers.py`.
- [ ] Tests FAIL → implement → PASS.
- [ ] Full gate: `make demo`; `cmp data/demo/loas/results.csv <scratch>/gate/results.csv`; `python scripts/pipeline.py --verify-baseline` → OK.
- [ ] Commit: `refactor(scripts): one end-to-end driver scripts/pipeline.py`.

### Task 8: Tests

- Delete `tests/{test_combine_cycles_table,test_sim_weight_trace,test_step_cycles,test_emission_order}.py`, `tests/test_stream_flag.sh`, `tests/stdout_roundtrip.sh`; convert `test_eventsim_deps.py`, `test_weight_resend.py` (`check_*` → `test_*`); new `tests/test_step_cycles.py` (round trip; `check_against` mismatch raises).
- [ ] `pytest tests -q` → 0 errors, 0 failures. Commit: `test: pytest-only suite`.

### Task 9: Delete dead code, notes, and unrelated files [D2, D3, D6]

- Delete (tracked): `profiling/` (incl. `common.py`), `log/`, `dump/`, `debug/`, `EXPLAIN.md`, `src/cachesim/*.md` (18), `src/cachesim/examples/{make_examples,survey_corpus}.py`, `scripts/README.md`, `configs/arch/multinode_sweep/`; stage the pre-existing deletions of `survey-output/` and the two root ColumnDisturb files.
- Delete (ignored, disk): `profiling/` outputs incl. the 16 GB streams.
- Modify: `.gitignore` pruned; the dangling comments listed in Facts (cite the atlas section or drop the sentence); `src/cachesim/examples/README.md` trimmed; `tests/test_cachesim_grid.py::test_grid_matches_0823_sweep` removed.
- [ ] `grep -rn "profiling/\|dump/\|log/20\|EXPLAIN.md\|tracegen\|wcache_run\|wcache_sweep" src scripts tests Makefile configs --include=*.py --include=*.cpp --include=*.h --include=*.sh --include=Makefile` → no hits.
- [ ] native `test` + `test-cli` pass; `pytest` 0 errors; `pipeline.py --layers R9 --sample-count 1` rows == gate rows.
- [ ] Commit: `chore: remove profiling history, dump, debug, logs, cache phase notes, generated arch sweep`.

### Task 10: Docs

- Rewrite `README.md` (≤ 60 lines), `docs/REPRODUCE.md` (the four CLIs with the R9 example each, `pipeline.py`, `--verify-baseline`, adding a benchmark, writing a sweep script); update `docs/atlas/{README,pipeline,nocsim,cachesim_native}.md` with the new names and fresh `file:line`; `input_trace/README.md`.
- [ ] A 10-line checker confirms every `path:line` in the atlas resolves; every REPRODUCE command executed once with exit code recorded.
- [ ] Commit: `docs: README, REPRODUCE and atlas for the renamed modules and pipeline.py`.

### Task 11: Final gate

- [ ] `make demo` from a clean `data/demo`: `results.csv` byte-identical; `--verify-baseline` OK; `pytest` 0 errors; native tests pass.
- [ ] `git status --porcelain` empty except `docs/plans/` (commit it with the docs task or leave untracked, user's call).
- [ ] Report: commit list; line counts before/after for `src/`, `scripts/`, `tests/`; tracked `.md` count (109 → 9 incl. this plan).

## Appendix A: expected tree after Task 11

```
neuro_cache-wcache/
├── Makefile  pyproject.toml  conftest.py  README.md  requirements.txt  .gitignore
├── docs/
│   ├── REPRODUCE.md
│   ├── plans/2026-10-26-module-clis-and-cleanup-plan.md
│   └── atlas/{README,pipeline,nocsim,cachesim_native}.md
├── configs/
│   ├── arch/            <arch>.yaml <arch>_inst16.yaml <arch>_multinode.yaml (×5 archs), loas_inst16_node32kb.yaml, snn_arch.yaml
│   ├── node_mapspace/   loas.yaml ptb.yaml spinalflow.yaml prosperity.yaml gustavsnn.yaml      (was dataflow/)
│   ├── cache/           base.json khkw_sweep.json
│   ├── schedules/loas/{resnet19_T4_n5,vgg16_T4_n5}/<layer>.json
│   └── workloads/       sample_snn_layer.yaml
├── input_trace/
│   ├── README.md
│   └── loas/{resnet19_T4_n5,vgg16_T4_n5}/{meta.json, layer_NN_*.npy}
├── src/
│   ├── parsers/           arch.py bitwidths.py node_mapspace.py layer.py        util.py
│   ├── snn_scheduler/     __main__.py cli.py artifact.py solve.py enumerator.py schedule.py modes.py metrics.py constants.py constraints/ objectives/ analysis/
│   ├── weight_trace_gen/  __main__.py cli.py weight_trace.py trace.py dense.py tick_output.h
│   │                      loas/ ptb/ spinalflow/ prosperity/ gustavsnn/   (main.cpp, *Gen.h, Makefile, native_bridge.py, binary)
│   ├── nocsim/            __main__.py sim.py step_cycles.py combine.py core/ schedule/ transactions/ eventsim/
│   └── cachesim/          __init__.py __main__.py cli.py grid.py stream.py
│                          examples/ (fixtures *.json, to_stream.py, README.md)
│                          native/   (include/cachesim/*.h, src/, apps/cachesim_run.cpp apps/cachesim_sweep.cpp, tests/, Makefile)
├── scripts/
│   ├── pipeline.py
│   └── subset_input_traces.py
├── tests/   test_trace.py test_snn_scheduler_cli.py test_weight_trace_gen_cli.py test_step_cycles.py test_nocsim_cli.py
│            test_cachesim_grid.py test_stream_writer.py test_stream_dump.py test_pipeline.py
│            test_flits_per_packet.py test_eventsim_deps.py test_weight_resend.py
└── data/ (ignored)   .baseline/ (ignored)
```

## Appendix B: each module alone, and the end-to-end composition

Example: R9 = `resnet19_T4_n5 / layer_09_layer2_0_conv2`, sample 0, benchmark `loas`. `$OUT` = `data/demo/loas`.

| # | Module | Command | Inputs | Outputs |
|---|---|---|---|---|
| 1 | snn_scheduler | `python -m snn_scheduler solve-trace --arch loas --trace-root input_trace/loas --trace-dirs resnet19_T4_n5 --layers layer_09_layer2_0_conv2 --cache-dir $OUT/schedules` | `input_trace/loas/resnet19_T4_n5/meta.json`; `configs/arch/loas_inst16_node32kb.yaml`; `configs/node_mapspace/loas.yaml`; Gurobi | `$OUT/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json`; `summary.csv`. Tracked copies: `configs/schedules/`. |
| 2 | weight_trace_gen | `python -m weight_trace_gen gen --arch loas --trace-root input_trace/loas --trace-dir resnet19_T4_n5 --layer layer_09_layer2_0_conv2 --schedule-cache configs/schedules --sample-start 0 --sample-count 1 --out-dir $OUT/weight_traces`; and `... --stream > $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts` | schedule JSON; `meta.json` + `layer_09_layer2_0_conv2.npy`; `src/weight_trace_gen/loas/loasgen` | `$OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz` (step cycles); WCTS stream |
| 3 | nocsim | `python -m nocsim --schedule configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json --layer $OUT/layers/resnet19_T4_n5/layer_09_layer2_0_conv2.yaml --arch configs/arch/loas_inst16_node32kb.yaml --weight-trace $OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz --out $OUT/nocsim/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.csv --simulate` | schedule JSON; workload yaml (pipeline writes it from meta.json); arch yaml; step cycles; `src/nocsim/eventsim/eventsim` | transaction CSV; stdout `total_cycles: 172768` |
| 4 | cachesim | `python -m cachesim grid --out $OUT/grid` then `python -m cachesim sweep --config-grid $OUT/grid/khkw_0.json --trace $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts --out $OUT/cachesim/R9_s0_khkw_0.csv` | `configs/cache/base.json` + `khkw_sweep.json` → grid JSON (48 configs over khkw_0/1/2); the `.wcts`; `src/cachesim/native/build/release/cachesim_sweep` | CSV, one row per config, 112 columns incl. `total_cycles`, `l1_hit`, `l2_hit`, `dram_bytes` |
| E2E | pipeline | `make demo` = `python scripts/pipeline.py --bench loas --layers V8 V9 R9 R16 --sample-count 5` | the four CLIs above | `$OUT/results.csv`, `$OUT/summary.md` |

Pipeline order per benchmark: (1) tracked schedule from `configs/schedules` or step 1 into `$OUT/schedules`; (2) step 2 twice per (layer, sample): step cycles and stream; (3) step 3 per (layer, sample); (4) step 4 once per (layer, sample, line size); (5) join on (trace_dir, layer, sample) → `results.csv`, `summary.md`. Steps 2–4 run in parallel across (layer, sample) under `--jobs`.

A future sweep (other grids, other layers, other archs) is a new file under `scripts/` that imports `pipeline.py`'s `run_all`/`join_results` helpers or just shells out to the four CLIs, and writes its own CSV.
