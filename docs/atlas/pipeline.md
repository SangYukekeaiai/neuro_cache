# Code atlas: the pipeline (input trace -> schedule -> weight trace -> cachesim / nocsim -> results)

Repo `neuro_cache-wcache`, branch `wcache-rebuild-phase-a`, commit `ef48902`
plus the uncommitted working-tree changes to `scripts/pipeline.py`,
`src/snn_scheduler/cli.py`, `tests/test_snn_scheduler_cli.py` and
`src/cachesim/examples/manifest.json`; every `file:N` below is line N of the
file as it is in that working tree, and a bare `:N` refers to the file named
last before it. Built only from code (`.py .cpp .h
Makefile .yaml .json .toml`) and directory listings; no notes, logs or result
files were read, so anything a README states and the code does not is absent
here. Paths are relative to the repo root.

Scope: `src/util.py`, `src/parsers/`, `src/snn_scheduler/`,
`src/weight_trace_gen/`, the two files the pipeline writes for the simulators
(`src/nocsim/step_cycles.py`, `src/cachesim/stream.py`), the cache grid and
CLI wrapper (`src/cachesim/grid.py`, `src/cachesim/cli.py`), `scripts/`,
`configs/`, `input_trace/`, `tests/`, and the build files (`Makefile`,
`pyproject.toml`, `conftest.py`, `requirements.txt`). The simulator internals
are in `docs/atlas/nocsim.md` (NoC simulator) and
`docs/atlas/cachesim_native.md` (C++ cache simulator, including the WCTS
reader); here only how the pipeline calls them.

---------------------------------------------------------------------------

## 1. Top-down

### 1.1 Purpose

The code measures how the weight fetches of spiking-neural-network (SNN)
accelerators behave in an on-chip memory system. For one layer it (a) derives
the layer shape from a captured spike trace, (b) solves a Gurobi MIP
(CoSA-style) for a loop schedule on a given architecture (the SNN scheduler),
(c) replays the real spikes of each input sample through a per-architecture
C++ model (LoAS, PTB, SpinalFlow, Prosperity, GustavSNN) to get, per schedule
tile and per core, the ordered weight addresses and MAC-cycle counts (the
weight-trace generator), and (d) feeds those cycle counts to the NoC simulator
`nocsim` (as a gzip JSON file) and the weight addresses to the cache simulator
`cachesim` (as a binary WCTS v2 stream). `scripts/pipeline.py` runs (a)-(d)
for a set of layers and samples and joins the two simulators' cycle counts
into one table, with speedup = nocsim cycles / cache-simulator cycles
(`scripts/pipeline.py:60-61`).

### 1.2 Entry points

Each module is a package under `src/` with its own `python -m` CLI;
`pyproject.toml:10-11` makes `src/` the package root and `:12` installs
`util` as a top-level module, so after `pip install -e .` the CLIs run from
any cwd.

| Entry point | What it does | Flags (default) |
|---|---|---|
| `python -m snn_scheduler solve` (`src/snn_scheduler/__main__.py:1-2` -> `cli.main` `src/snn_scheduler/cli.py:28`) | Solve one layer YAML in one TrafficMode, write the result JSON | `--layer` (`configs/workloads/sample_snn_layer.yaml`), `--arch` (`configs/arch/spinalflow.yaml`), `--dataflow` (`configs/node_mapspace/spinalflow.yaml`), `--out` (`outputs/schedule.json`), `--time-limit`, `--mip-gap`, `--solver-log`; defaults are cwd-relative strings (`src/snn_scheduler/cli.py:22-25`) |
| `python -m snn_scheduler enumerate` | Solve all 13 TrafficModes, report the best, write JSON plus a `.txt` summary | as `solve`, `--out` (`outputs/enumeration.json`, :78), `--w-u 0.1 --w-tr 1.0 --w-dl 10.0` (:86-97) |
| `python -m snn_scheduler solve-trace` (`_run_solve_trace` `src/snn_scheduler/cli.py:192`) | Solve and cache the schedule of every valid layer (or of `--layers`) of captured trace dirs; skip cached ones; write `summary.csv` | `--arch` (required, one of the 5 bridges, :103), `--arch-yaml` (`configs/arch/loas_inst16_node32kb.yaml` for loas, else `configs/arch/<arch>.yaml`; `src/snn_scheduler/cli.py:183-189`), `--node-mapspace` (`configs/node_mapspace/<arch>.yaml`, :198), `--trace-root` (`<repo>/input_trace/loas`, :116), `--trace-dirs` (`vgg16_T4_n5 resnet19_T4_n5`, :117), `--layers` (each name applies only to the dirs whose meta.json has it, :215-216; a name in no dir exits 2, :207-211), `--cache-dir` (required), `--force` |
| `python -m weight_trace_gen gen` (`src/weight_trace_gen/__main__.py:1-4` -> `cli.main` `src/weight_trace_gen/cli.py:421`) | Load a cached schedule, reconstruct samples through the native bridge; three modes: one combo (step-cycles files), `--all-layers`, `--stream` (one WCTS stream on stdout) | `--arch` (required), `--trace-dir`, `--layer`, `--trace-dirs` (`resnet19_T4_n5 vgg16_T4_n5`, `--all-layers` only), `--trace-root` (`<repo>/input_trace/loas`), `--schedule-cache` (`<repo>/configs/schedules`), `--out-dir` (`<repo>/outputs/weight_traces`), `--combo-tag` (`""`), `--sample-start` (0), `--sample-count`, `--n-samples` (100), `--seed` (0), `--workers` (1), `--force`, `--all-layers`, `--stream`, `--dump-trace PATH`, `--dump-trace-tiles N` (`src/weight_trace_gen/cli.py:353-392`) |
| `python -m nocsim` (`src/nocsim/__main__.py:1-4` -> `nocsim.sim.main` `src/nocsim/sim.py:313`) | NoC simulation of one schedule; with `--weight-trace` it charges each step the step-cycles file's MAC cycles, with `--simulate` it runs eventsim and prints `total_cycles` | see `docs/atlas/nocsim.md` |
| `python -m cachesim grid` (`src/cachesim/cli.py:28`) | Write the khkw grid (`configs/cache/base.json` x `configs/cache/khkw_sweep.json`) as one JSON file per `cin_block`, print the paths | `--out` (required), `--base`, `--sweep` (`src/cachesim/cli.py:38-41`) |
| `python -m cachesim sweep` / `run` | Run the native `cachesim_sweep` / `cachesim_run` with every later argument passed through, building them first if missing (`src/cachesim/cli.py:20-25`, dispatch :32-33) | native flags; see `docs/atlas/cachesim_native.md` |
| `scripts/pipeline.py` `main` :451 | End to end for one benchmark (1.5); or `--verify-baseline [DIR]`; or `--check-bench BENCH` | `--bench` (`loas`), `--layers` (`V8 V9 R9 R16`; also `trace_dir/layer` or `all`), `--sample-start` (0), `--sample-count` (5), `--out` (`$NEURO_CACHE_DATA/demo/<bench>`), `--grid` (the khkw grid), `--jobs` (`min(8, cpu_count)`), `--verify-baseline` (`<repo>/.baseline/after`), `--check-bench` (`scripts/pipeline.py:452-466`) |
| `scripts/subset_input_traces.py` `main` :96 | Cut an N-sample subset out of the full 10,000-sample captures | `--src` (`$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas`, :44), `--dest` (`<repo>/input_trace/loas`), `--captures` (`vgg16_T4_all resnet19_T4_all`), `--n` (5), `--seed` (0) |
| `make build` / `demo` / `test` (`Makefile:5-14`) | build the cache simulator apps, eventsim and `loasgen`; `scripts/pipeline.py` with defaults; `pytest tests -q` | `PYTHON` (`.baseline/venv/bin/python` when present, else `python3`, `Makefile:2`) |
| Native `src/weight_trace_gen/<arch>/<arch>gen` | `<bin> <trace.bin> <task.bin> <out.bin or ->` (`src/weight_trace_gen/loas/main.cpp:3-4`) | built by each arch's `Makefile` |

Settings read from the environment: only `NEURO_CACHE_DATA`, through
`util.data_root()` (`src/util.py:15`, default `<repo>/data`, :23-24). It sets
the pipeline's default output directory (`scripts/pipeline.py:312-313`) and
the subset tool's source (`scripts/subset_input_traces.py:44`). The pipeline
runs every child with `PYTHONPATH=<repo>/src` prepended
(`scripts/pipeline.py:53-54`) and `cwd=<repo>` (:91).

### 1.3 End-to-end data flow

```
input_trace/<bench>/<trace_dir>/meta.json + <layer>.npy   (uint8 [T,B,Cin,Hin,Win])
   | weight_trace_gen.trace.build_workload_from_trace  (KH=KW=3, PAD=1, COUT from meta.json layer_params)
   v
{"problem": {KH,KW,CIN,COUT,HO,WO,T,shape}}  -> temp YAML -> parsers.SNNProb
   | snn_scheduler.solve.solve_best_schedule  (13 TrafficModes, Gurobi, keep lowest score)
   |   [python -m snn_scheduler solve-trace; Gurobi needed]
   v
ScheduleArtifact JSON  <cache>/<arch>/<trace_dir>/<layer>.json    (tracked copies: configs/schedules/)
   | snn_scheduler.artifact.check_schedule_matches_trace, then weight_trace_gen.weight_trace.load_schedule
   |   -> nocsim.schedule.decode.schedule_from_strategy -> nocsim.schedule.tiles.iter_node_tiles
   v
list[NodeTileSpec]  (dram_i, noc_i, core_id, node_bound{dim}, tile_offset{dim})
   | weight_trace_gen/<arch>/native_bridge: task.bin + trace.bin -> <arch>gen -> out.bin
   | weight_trace_gen.weight_trace.assemble_layer_traces (group by (dram_i,noc_i), merge cores per tick, mac = max over cores)
   v
LayerWeightTrace (one per sample)                                 [python -m weight_trace_gen gen]
   |-- nocsim.step_cycles.save_step_cycles -> sample_NNNNN.json.gz --> python -m nocsim --weight-trace F --simulate
   |                                                                       -> stdout "total_cycles  : N"
   '-- cachesim.stream.stream_weight_trace -> WCTS v2 bytes (stdout, or the --dump-trace file)
                                                     --> python -m cachesim sweep --config-grid G --trace X
                                                           -> CSV, one row per config (G from cachesim.grid)
   scripts/pipeline.py: join on (trace_dir, layer, sample) -> results.csv (speedup_vs_nocsim), summary.md
```

Formats crossing each boundary:

1. **Input trace.** `meta.json` `layers` maps layer name -> `[T, B, Cin, Hin, Win]`
   (stored subset: T=4, B=5); the `.npy` is that array, uint8.
   `load_layer_trace` refuses a shape that differs from meta.json
   (`src/weight_trace_gen/trace.py:75-80`). `meta.json` `layer_params` maps the
   same names -> `{"cout", "kernel", "stride"}`; `layer_params()`
   (`src/weight_trace_gen/trace.py:84`) raises `ValueError` when the dict, the
   entry, or a positive-int field is missing (keys `LAYER_PARAM_KEYS`, :29;
   bools refused, :97-99). The whole contract (dtype, shape, one `B` per dir,
   `n_samples`, `layer_params`, tracked-schedule staleness) is checked by
   `scripts/pipeline.py --check-bench` (`check_bench`, `scripts/pipeline.py:170`).
2. **Workload dict.** `build_workload_from_trace` (`src/weight_trace_gen/trace.py:132`):
   KH=KW=3 (:26), stride 1, PAD=1 (:30), so HO=Hin, WO=Win (:156); COUT =
   `layer_params[layer]["cout"]` (:159). It raises for a layer `exclusion_reason`
   (:108) names: kernel != 3 or stride != 1 (:117-119; the arch models replay
   only 3x3 stride-1 windows, e.g. `src/weight_trace_gen/loas/LoASGen.h:74`
   reads input row `tile.ho + kh - pad_h`), or HO/WO < 1 (`src/weight_trace_gen/trace.py:121-122`).
   `valid_layer_names` (:126) keeps the rest: 25 of the 31 `_n5` layers
   (resnet19 loses layers 01, 08, 15, which are 3x3 stride 2, and the
   shortcuts 03, 10, 17, which are 1x1 stride 2).
   `check_schedule_matches_trace` (`src/snn_scheduler/artifact.py:115`) refuses
   a schedule whose `workload.problem` differs from this dict (:127-137) and
   names the `solve-trace --force` command to re-solve it.
3. **Schedule JSON** (`ScheduleArtifact`, `src/snn_scheduler/artifact.py:27`):
   `{arch, trace_dir, layer_name, workload:{problem:{...}}, result:{status,
   has_solution, objective, strategy:{NodeLevel{temporal_tile,spatial_split},
   NoCLevel{temporal_permutation,spatial_splitting}, DRAM{temporal_permutation}},
   metrics:{util, spatial_cost, temporal_traffic, delay, capacity},
   configs:{arch, dataflow}}, dram_num_steps, mode}`. `configs` holds the two
   paths as given (`src/snn_scheduler/solve.py:169-172`); the strategy block
   comes from `util.build_strategy` (`src/util.py:27`, called at
   `src/snn_scheduler/solve.py:234`). Written with `indent=1`
   (`src/snn_scheduler/artifact.py:103-104`).
4. **Native bridge wire format** (all int32, native endian;
   `src/weight_trace_gen/loas/main.cpp:6-20`, packer
   `src/weight_trace_gen/loas/native_bridge.py:26`): `task.bin` =
   `T,B,Cin,Hin,Win`, `num_tiles`, `num_samples`, then 11 int32 per tile (12
   for GustavSNN, `src/weight_trace_gen/gustavsnn/native_bridge.py:38`), then
   sample indices; `trace.bin` = uint8 row-major `[T,B,Cin,Hin,Win]` of only the
   requested samples; `out.bin` = per sample (outer) per tile (inner):
   `tile_idx, sample_idx, mac_cycles, num_ticks`, then per tick
   `tick, n_addr`, then `n_addr` x `(kh,kw,cin,cout_start,cout_end)`
   (`write_tick_grouped`, `src/weight_trace_gen/tick_output.h:34`).
5. **Step-cycles JSON.gz** (`save_step_cycles`, `src/nocsim/step_cycles.py:27`):
   `{format: "step_cycles_v1" (:24), arch, trace_dir, layer_name, sample_idx,
   workload_dims (the inner "problem" dict, includes "shape"), dram_num_steps,
   noc_num_steps, tiles:[{dram_i, noc_i, mac_cycles, lif_cycles (always null)}]}`
   (:40-54). No weight addresses; those leave only as the WCTS stream (item 6).
   Path: `<out-dir>/<arch>/[<combo-tag>/]<trace_dir>/<layer>/sample_<5 digits>.json.gz`
   (`src/weight_trace_gen/cli.py:113-116`). `load_step_cycles`
   (`src/nocsim/step_cycles.py:142`) also
   reads an older full form (no `format` key, each tile also carrying `ticks`,
   ignored) and raises `ValueError` on any other `format` (:162-165).
6. **WCTS v2 stream** (`src/cachesim/stream.py:16-53`): 56-byte fixed header
   (layout table :28-35; magic `WCTRACE1` :42, version 2 :43), then the 5
   field codes `0=KH 1=KW 2=CIN 3=COUT 4=RUN_END` (:50-52), `(dim_id, factor)`
   spatial pairs, `(dim_id, extent)` for all 7 dims (wire codes 0=KH..6=T,
   :49), identity `arch\0trace_dir\0layer\0sample_idx\0` (:78-80). Per tile
   frame `<iiqQ` = tile_index, cores in frame, mac_cycles, payload bytes
   (:106); per core `<ii` core_id, n_bursts (:116); per burst `<q5i` =
   local_tick, the run's anchor `kh, kw, cin, cout`, then `run_end` (28 B,
   :53, :130). The run walks `burst_dim` from the anchor's coordinate on that
   axis to `run_end` (exclusive). Trailer `<iQ` = -1, total bursts (:137). The
   header writer accepts `burst_dim` 0..3 (:65-66); `stream_weight_trace` emits
   only `burst_dim=3` (COUT) and refuses others (:195-200), because
   `LayerWeightTrace` addresses are COUT runs. The C++ reader is described in
   `docs/atlas/cachesim_native.md` (WCTS v2 wire format).
7. **Simulator outputs.** `cachesim_sweep` prints CSV to stdout (or `--out`),
   with the header on by default
   (`src/cachesim/native/apps/cachesim_sweep.cpp:44-45`, :85); the pipeline
   still passes `--header` (`scripts/pipeline.py:375`) and keeps
   `total_cycles` and the `KEY_FIELDS` columns `layout, line_size_bytes,
   l2_size_bytes, l2_banks, prefetch_policy, prefetch_distance` (:51-52,
   :390-392). `nocsim` writes a transaction CSV (`--out`) and, with
   `--simulate`, prints `total_cycles`, `unicast_cycles`, `multicast_cycles`,
   `count_cycles`, `dram_cycles` lines (`src/nocsim/sim.py:393-397`); the
   pipeline parses the `total_cycles` line (`scripts/pipeline.py:378-383`).

### 1.4 Key abstractions

```
parsers.SNNProb ---- prime factors per dim -----+
parsers.SNNArch (3 levels, S fanout) -----------+--> snn_scheduler.solve.solve_schedule (one TrafficMode)
parsers.SNNDataflow (node mapspace) ------------+        |  x[(level,dim,factor,k)], y[(var,level)]
parsers.SNNBitwidths (BW_*, DRAM_LATENCY) ------+        v
                                               solve_best_schedule (13 modes, score) --> strategy dict
                                                                                          |
snn_scheduler.artifact.ScheduleArtifact (persisted) <-------------------------------------+
   | weight_trace_gen.weight_trace.load_schedule
   v
nocsim Schedule + [weight_trace_gen.NodeTileSpec] --> ARCH_NATIVE_BRIDGES[arch].reconstruct_samples_native
                                                          | (subprocess <arch>gen)
                                                          v
                weight_trace_gen.weight_trace.LayerWeightTrace{TileWeightTrace{TickEntry{CoreEntry}}}
                nocsim.step_cycles.StepCycles  (read-back of mac_cycles only, used by nocsim)
```

Imports across the module packages (the Python packages depend on each other
in both directions; only the native binaries are one-way):

- `snn_scheduler.artifact` imports `weight_trace_gen.trace` and
  `nocsim.schedule.decode` (`src/snn_scheduler/artifact.py:18-19`);
  `snn_scheduler.cli` imports `weight_trace_gen` for the arch list
  (`src/snn_scheduler/cli.py:16`).
- `weight_trace_gen.weight_trace` imports `nocsim.schedule.decode`,
  `nocsim.schedule.tiles` and `snn_scheduler.artifact`
  (`src/weight_trace_gen/weight_trace.py:17-20`); `weight_trace_gen.cli` also
  imports `cachesim.stream` and `nocsim.step_cycles`
  (`src/weight_trace_gen/cli.py:48-54`); `weight_trace_gen.dense` imports
  `snn_scheduler.constants` and `nocsim.schedule.decode`
  (`src/weight_trace_gen/dense.py:17-18`).
- `nocsim` imports `weight_trace_gen` (`src/nocsim/combine.py:74-76`,
  `src/nocsim/sim.py:49`, `src/nocsim/schedule/tiles.py:40`,
  `src/nocsim/step_cycles.py:17`) and `snn_scheduler.constants`
  (`src/nocsim/schedule/decode.py:39`, `src/nocsim/schedule/buf_spatial.py:47`).
- `cachesim.stream` needs only `struct` at run time
  (`src/cachesim/stream.py:9-13`); the C++ under `src/cachesim/native` has no
  Python dependency.
- `scripts/pipeline.py` imports `cachesim.grid`, `snn_scheduler.artifact`,
  `util` and `weight_trace_gen` (`scripts/pipeline.py:33-37`) and runs every
  module step as a `python -m` subprocess.

### 1.5 One run, step by step (`scripts/pipeline.py` `demo` :316)

1. `resolve_layers` (:117) turns `--layers` into `(trace_dir, layer)` pairs:
   `trace_dir/layer` as is, a tag `V<n>`/`R<n>` built by `tags` (:105) from the
   valid layers of `vgg16_T4_n5`/`resnet19_T4_n5` (`WORKLOADS` :49), or `all`
   (:128-129).
2. `check_inputs` (:138) refuses a missing bench dir, a bench without a nocsim
   arch (`NOCSIM_ARCH` :45 has only loas), a missing meta.json or `.npy`, an
   excluded layer, or samples beyond `B` (:164-166). A missing schedule plus a
   `gurobipy` that does not import is also refused (:322-325). All problems
   are printed before anything is written (:326-327).
3. `schedules_for` (:265): if `configs/schedules/<bench>` (`SCHEDULES` :43)
   has every layer, use it; else copy it into `<out>/schedules` (:274-275) and
   make one `python -m snn_scheduler solve-trace` call for the missing dirs and
   layer names (:276-283); exit if a requested schedule is still absent
   (:286-289). Every schedule is then checked against meta.json with
   `check_schedule_matches_trace` (:290-297).
4. Builds (:333-337): `make -C src/cachesim/native MODE=release apps`,
   `make -C src/nocsim/eventsim`, and the bench's own `src/weight_trace_gen/<bench>`.
5. Weight traces (:339-351), in parallel under `--jobs`: per layer one
   `python -m weight_trace_gen gen ... --out-dir <out>/weight_traces
   --sample-start S --sample-count N --force` (step-cycles files), and per
   (layer, sample) one `gen ... --stream --sample-count 1 --dump-trace
   <out>/streams/<dir>/<layer>_sNNNNN.wcts`. `run` sends a child's stdout to
   `/dev/null` unless it is captured (:92), so the stream that reaches the
   cache simulator is the `--dump-trace` file, not the pipe.
6. nocsim (:353-366): the schedule's `workload` block is written as
   `<out>/layers/<dir>/<layer>.yaml` (:358); per (layer, sample) one
   `python -m nocsim --schedule ... --layer ... --arch <NOCSIM_ARCH> --weight-trace
   <step-cycles file> --out <out>/nocsim/<dir>/<layer>_sNNNNN.csv --simulate`.
7. Cache simulator (:368-376): `write_grid` writes one grid file per
   `cin_block` under `<out>/grid` (one file per line size for the khkw grid);
   per (layer, sample, grid file) one `python -m cachesim sweep --config-grid G
   --trace <stream> --arm cache --tier <grid name> --run-id ... --header`.
8. Collect (:378-392): nocsim `total_cycles` per (dir, layer, sample); cache
   rows, refusing a row count that differs from the grid's config count
   (:388-389).
9. `join_results` (:68) pairs each cache row with its nocsim cycles (a cache
   row without one is a `KeyError`), adds `speedup_vs_nocsim`; the rows go to
   `<out>/results.csv` (:394-398) and `write_summary` (:404) writes
   `<out>/summary.md`: geomean speedup per config (`summarize` :82) and every
   command run, as JSON lines (:414-418).

`--verify-baseline DIR` (`verify` :422) compares `<out>/results.csv` with
`DIR/wcache/khkw_sweep.csv` and `DIR/nocsim/stage3_results.csv` (:424-429) and
exits 1 on any mismatch or missing key (:448).

### 1.6 Canonical commands

The R9 example (`resnet19_T4_n5 / layer_09_layer2_0_conv2`, sample 0, bench
loas), one module at a time, then the composition. `OUT` is the pipeline's
output directory (default `$NEURO_CACHE_DATA/demo/loas`).

```
make build                                   # cachesim apps, eventsim, loasgen
make test                                    # pytest tests -q
make demo                                    # = python scripts/pipeline.py (V8 V9 R9 R16, samples 0..4)
python scripts/pipeline.py --verify-baseline # compare $OUT/results.csv with .baseline/after
python scripts/pipeline.py --check-bench loas

# 1. SNN scheduler (Gurobi)
python -m snn_scheduler solve-trace --arch loas --trace-root input_trace/loas \
    --trace-dirs resnet19_T4_n5 --layers layer_09_layer2_0_conv2 --cache-dir $OUT/schedules

# 2. weight-trace generator: step cycles, then the WCTS stream
python -m weight_trace_gen gen --arch loas --trace-root input_trace/loas --trace-dir resnet19_T4_n5 \
    --layer layer_09_layer2_0_conv2 --schedule-cache configs/schedules \
    --sample-start 0 --sample-count 1 --out-dir $OUT/weight_traces
python -m weight_trace_gen gen --arch loas --trace-root input_trace/loas --trace-dir resnet19_T4_n5 \
    --layer layer_09_layer2_0_conv2 --schedule-cache configs/schedules \
    --sample-start 0 --sample-count 1 --stream > $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts

# 3. NoC simulator ($OUT/layers/... is the schedule's workload block, written by the pipeline)
python -m nocsim --schedule configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json \
    --layer $OUT/layers/resnet19_T4_n5/layer_09_layer2_0_conv2.yaml \
    --arch configs/arch/loas_inst16_node32kb.yaml \
    --weight-trace $OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz \
    --out $OUT/nocsim/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.csv --simulate

# 4. cache simulator
python -m cachesim grid --out $OUT/grid
python -m cachesim sweep --config-grid $OUT/grid/khkw_0.json \
    --trace $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts --out $OUT/R9_s0_khkw_0.csv
```

All four module CLIs and `scripts/pipeline.py` resolve their repo-relative
defaults from `__file__` (`src/snn_scheduler/cli.py:21`,
`src/weight_trace_gen/cli.py:46`, `src/cachesim/grid.py:7`,
`scripts/pipeline.py:39`), except the `solve`/`enumerate` defaults, which are
cwd-relative (`src/snn_scheduler/cli.py:22-25`). The input paths in the
commands above are repo-relative, so run them from the repo root.

---------------------------------------------------------------------------

## 2. Bottom-up

### 2.1 `src/snn_scheduler/artifact.py` (137 lines): the schedule artifact

- `ScheduleArtifact` :27 dataclass; `mode` defaults to `"base"` (:36).
- `_dump_workload_path(workload)` :39 writes a temp YAML with `delete=False`
  (:40) and never removes it; `_prob_from_workload` :45 wraps it in `SNNProb`.
- `solve_and_cache_schedule(arch_name, arch_yaml, dataflow_yaml, trace_dir_name, layer_name, meta, cache_dir)` :49:
  builds the workload, calls `snn_scheduler.solve.solve_best_schedule`
  (imported lazily, :77, so reading a cached schedule needs no `gurobipy`,
  :22-24), decodes it to get `dram_num_steps` (:90), writes
  `cache_dir/<arch>/<trace_dir>/<layer>.json` (:101-104). Always re-solves;
  raises `ValueError` when every mode is infeasible (:85-89).
- `read_artifact(path)` :108.
- `check_schedule_matches_trace(schedule_path, trace_dir, layer_name)` :115:
  raises `ValueError` naming the schedule path, the differing fields, and the
  `result.configs.arch` it was solved with (:128-137), or the layer's
  exclusion reason (:122-125). Called before every schedule load in
  `src/weight_trace_gen/cli.py` (:135, :206, :317) and by `scripts/pipeline.py`
  (:242, :293).

### 2.2 `src/weight_trace_gen/weight_trace.py` (226 lines): the weight-trace data model

- `load_schedule(path)` :23 -> `(artifact, prob, tiles)`; tiles rebuilt with
  `iter_node_tiles`, not stored (:30-34).
- `CoreEntry` :38, `TickEntry` :49, `TileWeightTrace` :85, `LayerWeightTrace` :98:
  the nested trace shape. Absent cores are omitted, not padded (:51-53).
- `merge_cores_by_tick(core_results)` :58: cross-core merge, ticks ascending (:81).
- `assemble_layer_traces(tiles, sample_indices, unpacked, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :109:
  keys on each record's own indices; `noc_num_steps = max(noc_i)+1` (:134);
  `mac_cycles = max` over cores (:149); `lif_cycles=None` always (:151).
- `reconstruct_samples(arch_name, trace, tiles, sample_indices, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :163:
  the single dispatcher to `ARCH_NATIVE_BRIDGES` (`KeyError` for an unknown
  arch, :182-187).
- `sample_indices(n=100, seed=0, n_total=10000)` :199: canonical 100 =
  sorted `random.Random(0).sample(range(10000), 100)` (:219); n>100 adds more
  drawn at `seed`; n<100 raises (:220-221). Indices refer to the full
  10,000-sample capture.

### 2.3 `src/nocsim/step_cycles.py` (193 lines): the step-cycles file

- `STEP_CYCLES_FORMAT = "step_cycles_v1"` :24.
- `save_step_cycles(trace, path)` :27: format 5 of 1.3, gzip JSON, written to
  a temp file then `os.replace` (:56-64), so no partial files.
- `StepCycles` :68 + `check_against(artifact, schedule)` :94: six identity
  checks reported together; compares `artifact.workload["problem"]` to
  `workload_dims` (:123-125).
- `load_step_cycles(path)` :142: `.json` or `.json.gz` (:159); rejects an
  unknown `format` (:162), a duplicate tile (:170-171) or a tile count other
  than `dram_num_steps*noc_num_steps` (:176-182). Read by
  `python -m nocsim --weight-trace` (`src/nocsim/sim.py:335-337`).

### 2.4 `src/cachesim/` Python: `stream.py`, `grid.py`, `cli.py`

- `src/cachesim/stream.py` (219 lines): constants :42-53 (`_WCTS_BURST_BYTES` = 28, :53).
  - `write_stream_header(...)` :56: checks `burst_dim` in 0..3 (:65-66) before
    writing a byte, then `prod(spatial_factors) == n_cores` (:70-74) and all 7
    dims present (:75-76).
  - `write_tile_frame(fh, *, tile_index, mac_cycles, cores, burst_dim)` :98:
    each burst is `(local_tick, (kh, kw, cin, cout, run_end))`; checks core
    ids ascending (:111), no empty cores (:113), ticks strictly ascending
    (:119), and a run not empty along `burst_dim` (:124-128).
  - `write_stream_trailer` :135.
  - `_wcts_tile_frames(tiles, n_cores)` :140: tick-major -> core-major;
    rejects core ids outside `[0, n_cores)` (:154), empty COUT runs (:161),
    and measures `burst_span` as the largest `cout_end - cout_start` (:166).
  - `stream_weight_trace(trace, fh, *, n_cores, spatial_factors, burst_dim=3, burst_stride=1, weight_bytes=1, max_tiles=None)` :177:
    refuses any `burst_dim` but 3 (:195-200); `max_tiles` truncates before the
    header so `n_tiles` stays right (:201-202). A non-COUT stream has to be
    written with `write_stream_header` + `write_tile_frame` directly (only
    `tests/test_stream_writer.py` does).
- `src/cachesim/grid.py` (53 lines): `BASE_JSON` :8, `SWEEP_JSON` :9; `grid_for(line_bytes)`
  :20 sets `cin_block = line_bytes // (cout_block * weight_bytes)` (:26) and
  crosses `l2_banks` with `(prefetch_policy, prefetch_distance)` (:27-29);
  `full_grid` :32 loops line sizes slowest; `write_grid(out_dir, grid, name)`
  :39 writes one `<name>_<k>.json` per `cin_block` (:49-52), because one
  `cachesim_sweep` call takes one mapper.
- `src/cachesim/cli.py` (47 lines): `NATIVE`, `BINS` :15-17; `native` :20 runs
  `make -C src/cachesim/native MODE=release apps` when the binary is missing
  (:22-24); `main` :28 dispatches `sweep`/`run` before argparse sees the
  native flags (:32-33); `grid` :38-46.
- `src/cachesim/examples/to_stream.py` (70 lines): a checked-in fixture -> WCTS on stdout
  with `n_cores` 8 (:38), stubbing `weight_trace_gen.trace` when that
  import fails, e.g. without numpy (:19-32); see `docs/atlas/cachesim_native.md`.

### 2.5 `src/util.py` (155 lines)

- `data_root()` :15: `Path($NEURO_CACHE_DATA)` when set and non-empty, else
  `<repo>/data` (:23-24), with no log of the fallback. Layout in the
  docstring (:18-21): `neuro_cache_trace/input_trace/loas/<capture>/` for the
  full captures, `neuro_cache_outputs/weight_traces/` for generated traces.
  Callers: `scripts/pipeline.py:313`, `scripts/subset_input_traces.py:44`.
- `build_strategy(levels)` `src/util.py:27`: fuses solver factor placements into the
  `NodeLevel / NoCLevel / DRAM` strategy dict. Helpers `_region_levels` :66,
  `_strategy_block` :70, `_tile_block` :82, `_loops` :89, `_fuse_kind` :96
  (fuses adjacent same-dim), `_fuse_same_dim_kind` :106 (fuses all same-dim),
  `_append_or_fuse` :126, `_new_segment` :137, `_format_order` :149.
  `REGIONS`, `KINDS` :11-12 are unused.

### 2.6 `src/parsers/`

- `src/parsers/__init__.py:1-4`: re-exports the four parsers.
- `src/parsers/layer.py`: `DIM_KH..DIM_T = 0..6` :35-41; `SNN_REDUCTION_DIMS` = {KH,KW,CIN} :47;
  `_get_prime_factors` :50; `parse_snn_layer` :67; `SNNProb` :85
  (`prob_bound`, `prob_factors`, name/index maps); `config_str` :159,
  `is_reduction_dim` :163, `print` :167.
- `src/parsers/arch.py`: levels must be exactly `[NodeLevel, NoCLevel, OffChip]`
  (`_REQUIRED_LEVELS` :58, check :125-129); `MEM_NODE/NOC/OFFCHIP` :63-65;
  `parse_snn_arch` :68; `SNNArch` :86; `node_dim_capacity` in an arch YAML is
  an error (:111-113); `S[i] = instances[i]//instances[i+1]`
  (`_gen_spatial_constraints` :199); `single_node` flag (:172); properties
  `has_local_buffer` :186, `has_noc_buffer` :191; private parsers :210-335;
  `config_str` :341.
- `src/parsers/bitwidths.py`: defaults :32-35 (BW_WEIGHT 8, BW_PSUM 32, BW_VMEM 32,
  DRAM_LATENCY 0.25); `parse_snn_bitwidths` :38; `SNNBitwidths` :55.
- `src/parsers/node_mapspace.py` (the "node mapspace": per-dim NodeLevel residency):
  `FULL = "full"` :15; `parse_snn_dataflow` :18; `SNNDataflow` :22: a value is
  a positive int cap, `full`, or `{spatial: N}`; omitted dims are barred from
  NodeLevel (:23-28); `validate_for_arch` :109 checks the spatial product is
  at most `num_pes`.

### 2.7 `src/weight_trace_gen/`

Python:

- `src/weight_trace_gen/__init__.py`: `ARCH_NATIVE_BRIDGES` :30 (arch -> bridge module path);
  `NodeTileSpec` :40 (`dram_i, node_bound, tile_offset, is_last_K, noc_i=0,
  core_id=0`); `ComputeCycles` :55 (`lif_cycles=None` = no MAC/LIF split);
  `ArchComputeModel` Protocol :67 (`format_input` :70, `format_input_batch`
  :74, `compute_cycles` :81, `weight_addresses` :85, `weight_ticks` :95).
  Only `DenseStaticComputeModel` implements it.
- `src/weight_trace_gen/dense.py`: `_dim_totals` :24; `DenseStaticComputeModel(schedule, prob)` :32:
  the same MAC/LIF count for every tile from the loop factors (`_pe_cycles`
  :52, `_lif_cycles` :67 counts only dims with `_A[j][VAR_VMEM]`, :72). Used
  by nocsim when no weight trace is given (`src/nocsim/combine.py:225`).
- `src/weight_trace_gen/trace.py`: `KH = KW = 3` :26, `LAYER_PARAM_KEYS` :29, `PAD = 1` :30;
  `load_layer_trace(trace_dir, layer_name, mmap=False)` :39;
  `layer_params(meta, layer_name)` :84; `exclusion_reason(meta, layer_name)` :108
  (kernel/stride, then HO,WO >= 1); `valid_layer_names(meta)` :126;
  `build_workload_from_trace(meta, layer_name)` :132.
- `src/weight_trace_gen/weight_trace.py`: 2.2.
- `src/weight_trace_gen/cli.py` (427 lines): `ROOT` :46; `DEFAULT_TRACE_ROOT` :59,
  `DEFAULT_TRACE_DIRS` :60; `_resolve_samples` :76 (explicit range, else
  `sample_indices`).
  - Mode 1, one combo: `run_one_combo` :128: refuses a missing schedule
    (:131-133) or a stale one (:134-138) before skipping existing samples
    (:145-148, unless `--force`); `_STATE` :91, `_init_worker` :94,
    `_process_chunk` :106, `_chunks` :121; `--workers > 1` uses a
    `multiprocessing.Pool` (:169-175).
  - Mode 2, `--all-layers`: `run_all_layers` :259 with `_layers_for` :188,
    `_all_layer_targets` :194, `_regenerate_layer` :202 (checks the schedule,
    :206, then skips existing samples, :210; chunks of `SAMPLE_CHUNK_SIZE=10`,
    :66), `_regenerate_one_layer_task` :228, `_run_pass` :234 (two passes,
    `FIRST_PASS_SAMPLES=10` :69; `--workers 0` = `len(os.sched_getaffinity(0))`, :265).
  - Mode 3, `--stream`: `run_stream` :301 (exactly one sample, :305-309;
    `n_cores` = product of `schedule.spatial_factors`, :330-334, so idle cores
    count), `emit_stream` :280 (a second pass writes the `--dump-trace` file,
    optionally truncated to `--dump-trace-tiles` frames, :293-297).
  - `parse_args` :353 (`--sample-count` vs `--n-samples` uses the default
    100 as sentinel, :395; `--stream` refuses `--all-layers`, `--workers > 1`
    and a missing `--trace-dir/--layer`, :399-407); `main` :421.
- `<arch>/__init__.py` (5 files): docstrings only (paper, fixed deployment),
  e.g. `src/weight_trace_gen/loas/__init__.py:12-18`.
- `<arch>/native_bridge.py` (5 near-identical files; loas lines given):
  `_BINARY` `src/weight_trace_gen/loas/native_bridge.py:23`; `_pack_task(trace_shape, tiles, sample_indices)` :26;
  `_unpack_output(data, num_tiles, sample_indices)` :45 (asserts every byte
  consumed, :69); `reconstruct_samples_native(...)` :72: slice
  `trace[:, samples]` to contiguous uint8 (:103), write `trace.bin` and
  `task.bin` in a temp dir, run `loasgen trace.bin task.bin out.bin`
  (:116-119), then `assemble_layer_traces` (:123-126). The binary sees local
  indices 0..n-1 (:104) but the returned traces carry the caller's indices.
  Per-arch tile record: loas/ptb/spinalflow `dram_i, ho, wo, kh_n, kw_n,
  cin_off, cin_n, t_off, t_n, cout_off, cout_n` (`src/weight_trace_gen/loas/native_bridge.py:31-39`);
  prosperity `dram_i, ho_off, ho_n, wo_off, wo_n, kh_n, kw_n, cin, t,
  cout_off, cout_n` (`src/weight_trace_gen/prosperity/native_bridge.py:32-41`);
  gustavsnn 12 fields with a T offset and HO/WO ranges
  (`src/weight_trace_gen/gustavsnn/native_bridge.py:38`).

C++ (each `Makefile`: `g++ -O2 -std=c++17 -Wall -Wextra`,
`src/weight_trace_gen/loas/Makefile:1-2`):

- `src/weight_trace_gen/tick_output.h`: `write_tick_grouped(out, addresses)` :34 buckets by
  `.tick` (ascending).
- `<arch>/main.cpp` `main` (`src/weight_trace_gen/loas/main.cpp:54`;
  `src/weight_trace_gen/ptb/main.cpp:53`, the same line in spinalflow and
  prosperity; `src/weight_trace_gen/gustavsnn/main.cpp:62`): reads task/trace, output path `-` = stdout, loops
  sample-outer / tile-inner (`src/weight_trace_gen/loas/main.cpp:134-143`),
  and every arch calls `write_tick_grouped` (e.g.
  `src/weight_trace_gen/ptb/main.cpp:140`). The 5 files differ only in names
  and the tile-record fields.
- `src/weight_trace_gen/loas/LoASGen.h` `reconstruct_sample` :64: one tile = one (ho, wo) pixel;
  walk (kh, kw, cin), emit an address when that input site spikes at any t in
  the tile's T range; tick = emission index (:22-27).
- `src/weight_trace_gen/ptb/PTBGen.h`: `TW_SIZE=8, PE_ROWS_MAX=16, PE_COLS_MAX=8` :41-43;
  `compute_cycle_count(ln, cout_n, total_t)` :77 systolic fill/drain;
  `reconstruct_sample` :87: Pass 1 silence removal (addresses), Pass 2 merge
  of non-overlapping neighbours gives `ln`; `mac_cycles = max(access,
  compute)` (:24-28).
- `src/weight_trace_gen/spinalflow/SpinalFlowGen.h` `reconstruct_sample` :56: one address per spike
  event, t outermost (:65, :69); tick = event index.
- `src/weight_trace_gen/prosperity/ProsperityGen.h`: `popcount64` :80; `reconstruct_sample` :90.
- `src/weight_trace_gen/gustavsnn/GustavGen.h`: `PE_COUNT_MAX=8` :35; `reconstruct_tile` :82
  (per-HO-row submatrices), `addresses_and_ticks` :132 (waves of 8
  submatrices, so several addresses share a tick), `reconstruct_sample` :171.

### 2.8 `src/snn_scheduler/` (the rest)

- `src/snn_scheduler/__init__.py:1-5`: re-exports constants only, no
  `gurobipy`. `src/snn_scheduler/__main__.py:1-2`: `cli.main()`.
- `src/snn_scheduler/constants.py` (96 lines): `SNN_GB_START_LEVEL=1` :51; `VAR_WEIGHT/PSUM/VMEM`
  0/1/2 :57-59; `TRAFFIC_MULT=[1,2,2]` :68; `_A` :76 (dim -> var size
  relation); `_B` all ones :92.
- `src/snn_scheduler/schedule.py`: `create_schedule_vars(m, prob, arch, gb_start_level=1)` :49:
  binary `x[(i,j,n,k)]` (k 0=spatial 1=temporal) over `total_levels = 1+2P`
  (P = total prime-factor count, :73-76); integer `y[(v,i)]` over NoC+DRAM slots.
- `src/snn_scheduler/modes.py`: `TrafficMode` :53 (13 values: base, psum_{dram,gb}_otok,
  vmem_{dram,gb}_xxxt, dram_{oooo,ooot,oook}, both_dram_ootk,
  gb_{oooo,ooot,oook,ootk}); `_ModeSpec` :73; `_MODE_SPECS` :79 maps each to a
  constraint adder + `zero_vars` / `gb_only_vars`.
- `src/snn_scheduler/solve.py`: `solve_schedule(layer_path, arch_path, dataflow_path, time_limit=None, mip_gap=None, output_flag=False, traffic_mode=BASE, return_metrics=False)` :53:
  parses layer, arch, node mapspace and bitwidths (:68-72), sets only
  `OutputFlag`, `TimeLimit`, `MIPGap` (:75-79), adds vars, constraints and
  objective, `model.dispose()` in `finally` (:160-167), records the arch and
  node-mapspace paths (:169-172). `_collect_result` :176,
  `_extract_strategy` :210, `_region` :237, `_status_name` :245,
  `_safe_attr` :249, weights `0.1, 1.0, 10.0` (:259), `_mode_score` :262,
  `solve_best_schedule(layer, arch, dataflow)` :269 (loops all 13 modes with
  no time limit, :290-298).
- `src/snn_scheduler/enumerator.py`: `enumerate_modes(...)` :29 (same loop, returns all
  candidates; weight defaults :33-35); `_comparison_score` :101 (same
  formula as `_mode_score`).
- `src/snn_scheduler/cli.py` (421 lines): `main` :28, `_build_parser` :44, `_run_solve` :132
  (exit 2 on a load/solver error, 3 if no solution, :145-152),
  `_run_enumerate` :155 (also writes the `.txt` summary, :179),
  `_default_arch_yaml` :183, `_run_solve_trace` :192 (rows OK / SKIPPED /
  INFEASIBLE / ERROR into `summary.csv`, :242-248; exit 1 if any row is
  INFEASIBLE or ERROR, :255), `_write_json` :258, `_print_summary` :265,
  `_print_enumeration_summary` :277, `format_enumeration_summary` :352,
  `_fmt_perm` :364, `_fmt_unordered` :379, `_autoscale` :394,
  `_print_wrapped` :402.
- `src/snn_scheduler/metrics.py`: `extract_metrics(...)` :158 (util, spatial_cost,
  temporal_traffic, delay, capacity); helpers `_eval_util` :33,
  `_eval_spatial_cost` :59, `_eval_temporal_traffic` :85, `_eval_delay` :139.
- `src/snn_scheduler/constraints/assignment.py`: `add_assignment_constraints` :39,
  `_add_y_monotonicity` :125.
- `src/snn_scheduler/constraints/spatial.py`: `add_spatial_constraints` :35 (per-region fanout
  <= S).
- `src/snn_scheduler/constraints/node_level.py`: `_largest_divisor_leq` :46,
  `add_pe_spatial_split_constraints` :60 (pins `{spatial: N}` dims at level 0).
- `src/snn_scheduler/constraints/node_capacity.py`: `_max_product_leq` :64,
  `add_node_capacity_constraints` :80 (temporal caps at level 0),
  `add_no_noc_level_constraints` :162 (single-node archs: no NoC perm slots).
- `src/snn_scheduler/constraints/temporal_order.py`: big-M slot helpers `_wslot` :49,
  `_in_region` :58, `_above_all_k` :67, `_above_all_t` :81, `_t_above_all_o` :94;
  one adder per mode: `add_ootk_gb` :113, `add_ootk_dram` :173, `add_otok_dram` :220,
  `add_otok_gb` :272, `add_xxxt_dram` :329, `add_xxxt_gb` :369, `add_oooo_dram` :419,
  `add_oooo_gb` :457, `add_ooot_gb` :491, `add_ooot_dram` :534, `add_oook_gb` :575,
  `add_oook_dram` :619. All take `(m, x, prob, gb_start_level, dram_start, perm_levels)`.
- `src/snn_scheduler/objectives/combined.py`: `build_objective(...)` :15:
  `10*comp_hat - 0.1*util_hat + 1.0*traffic_hat`, minimized (weights :25-27).
- `src/snn_scheduler/objectives/compute.py`: `build_compute_objective` :24 (sum of ln(factor)
  over temporal placements).
- `src/snn_scheduler/objectives/utilization.py`: `build_utilization_terms` :41,
  `_build_noc_utilization` :76, `_build_node_util_reward` :109,
  `_build_data_size` :147 (coefficients `0.8+0.04*i`, :168),
  `add_utilization_capacity_constraints` :177, `_bytes_by_var` :197,
  `_loop_upper_for_global_buffer` :205.
- `src/snn_scheduler/objectives/traffic/spatial.py` `compute_spatial_traffic` :38;
  `src/snn_scheduler/objectives/traffic/temporal.py` `compute_temporal_traffic` :55;
  `src/snn_scheduler/objectives/traffic/total.py` `build_traffic_cost` :32
  (`0.99*data_size + 0.99*spatial + temporal`, :57-58).
- `src/snn_scheduler/analysis/dram_permutation.py`: `SUPER_DIM` :23, `classify_permutation(loops)`
  :31 (M/N/K/T string), `classify_schedule_file(path)` :43. No caller (3.1).

### 2.9 `scripts/`

- `scripts/pipeline.py` (483 lines; walk-through in 1.5). Constants: `ROOT` :39,
  `INPUT_TRACE` :41, `SCHEDULES` :43, `NOCSIM_ARCH` :45, `TAGS` :47,
  `WORKLOADS` :49, `KEY_FIELDS` :51-52, `ENV` :53-54, `DEFAULT_JOBS` :57
  (comment :55-56: one command peaked at 14 GB RSS). Pure helpers: `speedup`
  :60, `geomean` :64, `join_results` :68, `summarize` :82. Process helpers: `run` :90 (exits with the child's last
  3000 stderr bytes on failure, :94-95), `run_all` :99 (records the commands,
  runs them on a thread pool). Layer and input handling: `tags` :105,
  `resolve_layers` :117, `check_inputs` :138, `check_bench` :170,
  `missing_schedules` :252, `can_solve` :257, `schedules_for` :265. Run:
  `load_grid` :301 (`--grid` must be a non-empty JSON array, :307-308),
  `out_dir` :312, `demo` :316, `write_summary` :404, `verify` :422, `main` :451.
  Tests: `tests/test_pipeline.py`.
- `scripts/subset_input_traces.py` (129 lines): `ROOT` from `__file__` (:41), imports
  `util.data_root` (:42); `subset_one(src_dir, dest_dir, n, seed)` :49:
  `np.random.default_rng(seed).choice`, sorted (:59-60), the same indices for
  every layer, rewrites `B` and `n_samples` and adds `meta["subset"]`
  (:74-89); `main` :96; the output dir name replaces `_all` with `_n<N>` (:119).

### 2.10 `configs/`

- `arch/` (15 files): `<arch>.yaml` x5 (single node, `single_node: true`,
  e.g. `configs/arch/loas.yaml:12`; num_pes loas 16, gustavsnn 64, the other
  three 128), `<arch>_multinode.yaml` x5 (128 nodes, NoC 1 MiB per tensor,
  `configs/arch/loas_multinode.yaml:13`, :17-20), `{loas,ptb,spinalflow}_inst16.yaml`
  (16 nodes, no NodeLevel `local_buffer`, reason in
  `configs/arch/loas_inst16.yaml:8-18`), `loas_inst16_node32kb.yaml` (16 nodes
  x 16 PEs, NodeLevel local buffer weight 30720 / psum 1024 / vmem 1024, NoC
  1966080 / 65536 / 65536; `configs/arch/loas_inst16_node32kb.yaml:10-22`;
  the default `--arch-yaml` of `solve-trace --arch loas` and the pipeline's
  nocsim arch), `snn_arch.yaml` (generic example). Every file has
  `DRAM_LATENCY: 0.25`; `configs/arch/ptb.yaml:2` marks the PTB file as
  reconstructed.
- `node_mapspace/<arch>.yaml` x5: `node_dim_capacity` per dim (e.g. loas
  KH/KW/CIN/T `full`, COUT `{spatial: 4}`, `configs/node_mapspace/loas.yaml:5-9`).
- `cache/base.json`: the cache simulator's base point (layout `khkw_split`,
  `cin_block` 16 x `cout_block` 4 x 1 B = 64 B line, L1 16 KB 8-way latency 0,
  L2 512 KB 16-way latency 2 miss 24 with 32 MSHRs, 1 bank, no prefetch;
  `configs/cache/base.json:2-16`). `configs/cache/khkw_sweep.json:2-4`: the axes
  `line_bytes` [16, 32, 64], `l2_banks` [1, 2, 4, 8], `prefetch` none or
  `next_burst` 1/2/4, so `full_grid` has 3 x 4 x 4 = 48 points.
- `schedules/loas/{vgg16_T4_n5,resnet19_T4_n5}/`: the tracked schedules for
  V8, V9, R9, R16 (`layer_08_features_27`, `layer_09_features_30`,
  `layer_09_layer2_0_conv2`, `layer_16_layer3_0_conv2`). Their
  `result.configs` paths name the files they were solved with, outside the
  current tree (e.g.
  `configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json:125-127`).
- `workloads/sample_snn_layer.yaml`: 3x3, CIN 64, COUT 128, 56x56, T 4; the
  `solve`/`enumerate` default.

### 2.11 `input_trace/`

`input_trace/loas/` (14 MB, 34 tracked files including `input_trace/README.md`,
kept in git by `.gitignore:44-45` although `.gitignore:22` ignores
`input_trace/`): `vgg16_T4_n5/` (12 layers `layer_01_features_3` ..
`layer_12_features_40`) and `resnet19_T4_n5/` (19 layers incl. 3
`*_shortcut_0`), each with `meta.json` (T=4, B=5, dataset cifar10, dtype
uint8, `layer_params`, `subset.sample_indices` `[2697, 3078, 5110, 6367,
8502]`, seed 0, made by `scripts/subset_input_traces.py`). Only LoAS-captured
traces exist; every arch model reads these same spikes. The full `_all`
captures are expected under `$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas/`
(`src/util.py:18-21`).

### 2.12 `tests/` (pytest; `conftest.py:5` puts `scripts/` on `sys.path`)

- `tests/test_trace.py`: `build_workload_from_trace` takes COUT from `layer_params`
  (:24), refuses missing or non-int params (:30-71), excludes 1x1 and
  stride-2 layers with a reason (:42), and the stored resnet19 meta chains
  as the network does (:73, :88).
- `tests/test_snn_scheduler_cli.py`: `solve-trace` skips a cached schedule without
  importing `gurobipy` (:11), defaults loas to the 16-node arch (:25), and
  applies `--layers` per dir (:33).
- `tests/test_weight_trace_gen_cli.py`: `check_schedule_matches_trace` passes and
  refuses (:45-74), one-combo mode and `--all-layers` refuse a stale schedule
  even when outputs exist (:93, :102), step-cycles write and read (:122-145), and `gen --stream`
  on R9 sample 0 matches a SHA-256 (:152-170; skips without `loasgen`).
- `tests/test_step_cycles.py`: `save_step_cycles` / `load_step_cycles` round trip
  (:23) and `StepCycles.check_against` (:35).
- `tests/test_stream_writer.py` (14 tests): WCTS byte layout and rejection rules
  (:40-138), a Python reader `decode_stream` (:154), round trip of a
  fixture from `src/cachesim/examples` (`tests/test_stream_writer.py:217`), one
  burst per axis 0..3 (:250), and the `burst_dim` refusals (:262-297).
- `tests/test_stream_dump.py`: `emit_stream` dump is byte-identical, or a valid
  short stream when truncated (:26, :36).
- `tests/test_nocsim_cli.py`: `python -m nocsim --help` runs (:18); an unknown
  step-cycles `format` is refused (:24) and makes the CLI exit 2 (:34).
- `tests/test_cachesim_grid.py`: `write_grid` equals the demo's grid files
  (:19; reference `data/demo/loas/grid`, else `.baseline/wcache/_khkw_grid`,
  else skip, :12-25) and `python -m cachesim grid` writes three files (:32).
- `tests/test_pipeline.py` (33 test functions): `speedup`, `geomean`, `join_results`,
  `summarize` (:21-43), `resolve_layers` (:71-80), `check_inputs` (:85-124),
  `load_grid` (:130), `schedules_for` without a solver (:145-163), `main`
  argument checks (:180), `check_bench` (:195-257), the commands
  `summary.md` records (:272), and `--layers all` (:311).
- `tests/test_weight_resend.py`: a weight tile is resent only on a reload, on the
  four tracked schedules (:55) and on a synthetic nest (:81).
- `tests/test_flits_per_packet.py`, `tests/test_eventsim_deps.py`: eventsim checks that
  skip without the binary; see `docs/atlas/nocsim.md`.

### 2.13 Build and packaging

- `Makefile` (14 lines): `build` :5-8, `demo` :10-11, `test` :13-14; `PYTHON`
  prefers `.baseline/venv/bin/python` (:2).
- `pyproject.toml`: setuptools (:1-3), `requires-python >= 3.10` (:8),
  packages found under `src` (:10-15) plus the `util` module (:12).
- `conftest.py`: puts `scripts/` on `sys.path` so tests import `pipeline` (:4-5).
- `requirements.txt:1-4`: `gurobipy==13.0.2`, `numpy==2.4.6`, `PyYAML==6.0.3`,
  `matplotlib` (unpinned).
- `.gitignore`: native binaries (:53-58), `/data/` (:81), `.baseline/`
  (:78), and re-includes `configs/**` (:32), `src/cachesim/examples/*.json`
  (:38) and `input_trace/loas/**` (:44-45).

---------------------------------------------------------------------------

## 3. Findings for cleanup (code-evidenced)

### 3.1 Dead or unused code

- `util.REGIONS`, `util.KINDS` `src/util.py:11-12`: no reader.
- `snn_scheduler.analysis` (`src/snn_scheduler/analysis/dram_permutation.py:31`,
  :43): no caller in `src/`, `scripts/` or `tests/`.
- `StepCycles.check_against` `src/nocsim/step_cycles.py:94`: called only by
  `tests/test_step_cycles.py:44`; `python -m nocsim` reads only `.by_step`
  (`src/nocsim/sim.py:337`).
- `ArchComputeModel` Protocol `src/weight_trace_gen/__init__.py:67`: its sole
  implementer `DenseStaticComputeModel` (`src/weight_trace_gen/dense.py:32`)
  has no `format_input_batch`; nocsim still types against it
  (`src/nocsim/combine.py:74`).
- `lif_cycles` is always `None` in generated traces
  (`src/weight_trace_gen/weight_trace.py:151`).
- `stream_weight_trace` has a `burst_dim` parameter
  (`src/cachesim/stream.py:178`) whose only legal value is its default 3 (:195).
- `matplotlib` in `requirements.txt:4`: no file in `src/`, `scripts/` or
  `tests/` imports it. `pytest`, which `make test` runs (`Makefile:14`), is
  not listed.
- Not dead but unused by `scripts/pipeline.py`: `weight_trace_gen gen
  --all-layers`, `--workers > 1`, `--combo-tag` and `--n-samples`; the
  pipeline passes `--workers 1` (`scripts/pipeline.py:341`) and explicit
  sample ranges.

### 3.2 Duplicated logic

- Mode score defined twice with the same weights:
  `src/snn_scheduler/solve.py:259-266` and `src/snn_scheduler/enumerator.py:101`
  (defaults :33-35); the weights also in `src/snn_scheduler/cli.py:86-97` and
  `src/snn_scheduler/objectives/combined.py:25-27`.
- Five arch `main.cpp` and five `native_bridge.py` differ only in names and
  the tile record (2.7).
- The three `gen` modes each locate and check the schedule:
  `src/weight_trace_gen/cli.py:130-138`, :205-206, :311-321.
- The WCTS byte layout lives in three places: the writer's comment
  (`src/cachesim/stream.py:28-39`), a Python reader in the tests
  (`decode_stream`, `tests/test_stream_writer.py:154`), and the C++ reader.

### 3.3 Hardcoded paths and host values

- The tracked schedules record the absolute arch and node-mapspace paths of
  the tree that solved them (`configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json:125-127`),
  and `solve_schedule` keeps recording paths as given
  (`src/snn_scheduler/solve.py:169-172`).
- `--verify-baseline` defaults to `<repo>/.baseline/after`
  (`scripts/pipeline.py:463`), a git-ignored local directory (`.gitignore:78`).
- `tests/test_cachesim_grid.py:12-16` reads its reference from `data/demo` or
  `.baseline/`, both outside git.

### 3.4 Environment assumptions

- cwd-relative defaults: `python -m snn_scheduler solve` / `enumerate`
  (`src/snn_scheduler/cli.py:22-25`, :78).
- `data_root()` falls back to `<repo>/data` without logging it
  (`src/util.py:23-24`).
- Gurobi: required for every solve; only `OutputFlag`/`TimeLimit`/`MIPGap`
  are set (`src/snn_scheduler/solve.py:75-79`), never `Threads`/`Seed`;
  :160-167 documents a long-lived-worker bug worked around by `dispose`.
- `os.sched_getaffinity` (Linux only) for `--workers 0`
  (`src/weight_trace_gen/cli.py:265`).
- Memory: one pipeline command can hold several GB, so `--jobs` defaults to
  at most 8 (`scripts/pipeline.py:55-57`).
- `python -m cachesim sweep/run` runs `make` on first use
  (`src/cachesim/cli.py:22-24`), so the first call needs g++ and make.

### 3.5 Scattered config literals

(Audit of "one canonical source": values defined in more than one place.)

- The 16-node loas arch is named in two places: `scripts/pipeline.py:45`
  (nocsim) and `src/snn_scheduler/cli.py:188` (solve). Minimal collapse: the
  pipeline reads the solve default, or both read one constant.
- The default trace root `input_trace/loas` and the two `_n5` trace dirs:
  `src/snn_scheduler/cli.py:116-117`, `src/weight_trace_gen/cli.py:59-60`,
  `scripts/pipeline.py:41`, :49; the two CLIs list the dirs in opposite order.
- The data sub-path `neuro_cache_trace/input_trace/loas` after
  `data_root()`: `scripts/subset_input_traces.py:44`, restated in comments at
  `src/snn_scheduler/cli.py:115`, `src/weight_trace_gen/cli.py:58`,
  `src/util.py:19`.
- Scoring weights 0.1/1.0/10.0 in four places (3.2).
- Output defaults under `<repo>/outputs/` (`src/snn_scheduler/cli.py:25`,
  :78, `src/weight_trace_gen/cli.py:367`) while the pipeline writes under
  `data_root()` (`scripts/pipeline.py:313`).
- The cache base config has one source, `configs/cache/base.json`, read only
  through `src/cachesim/grid.py:8`, :12.

### 3.6 Inconsistent conventions and wrong comments

- Node-mapspace comments vs values: `configs/node_mapspace/prosperity.yaml:2`
  "128 output columns" with `COUT: {spatial: 8}` (:7);
  `configs/node_mapspace/spinalflow.yaml:3` "128-PE array" with
  `{spatial: 8}` (:8); `src/weight_trace_gen/loas/__init__.py:12` "COUT
  node-level spatial capacity 16" while `configs/node_mapspace/loas.yaml:9`
  has `{spatial: 4}`.
- `--n-samples` conflict check uses the default as sentinel
  (`src/weight_trace_gen/cli.py:395`), so `--n-samples 100 --sample-count 5` passes.
- `--all-layers` ignores `--combo-tag` (`_regenerate_layer`,
  `src/weight_trace_gen/cli.py:207`).
- The cache simulator is `cachesim` everywhere in code, but the pipeline's
  result columns and comments still say `wcache` (`wcache_total_cycles`,
  `scripts/pipeline.py:76`; `KEY_FIELDS` comment :50; `--grid` help :460),
  and `--verify-baseline` reads `DIR/wcache/khkw_sweep.csv` (:424).
- `solve-trace` exits 2 for an unknown layer name (`src/snn_scheduler/cli.py:211`)
  but 1 when a layer is infeasible (:255); `gen` uses 1 for a missing or
  stale schedule (`src/weight_trace_gen/cli.py:133`, :138) and 2 for a bad
  `--stream` sample count (:309).

### 3.7 Stale references in code comments

- `src/weight_trace_gen/weight_trace.py:196`, :201-203 cite a stored index
  list `sample_indices.json` that is not in the repo.
- `src/nocsim/step_cycles.py:75` cites a `PROGRESS.md` under `src/cachesim`,
  and :102 its entries B173/B179; no such file exists.
- `tests/test_stream_dump.py:3` points at a shell test `test_stream_flag.sh`
  that is not in `tests/`.
- `scripts/subset_input_traces.py:27` shows `conda run -n ${CONDA_ENV:-cosa_snn}`;
  nothing in the repo defines `CONDA_ENV` any more.
- A "Phase D campaign plan" is cited in `src/weight_trace_gen/weight_trace.py:127`,
  `src/weight_trace_gen/cli.py:285`, :404, `src/cachesim/stream.py:21` and
  each `main.cpp` (e.g. `src/weight_trace_gen/loas/main.cpp:116`, :133); no
  such document is in the repo.
- `src/weight_trace_gen/__init__.py:85-110` describes per-arch `address.py`
  modules, and `src/weight_trace_gen/trace.py:40` an example trace dir `vgg16_T4_B1`;
  neither exists.
- `src/weight_trace_gen/cli.py:24-25` advises running `--all-layers` "via
  srun on a compute node"; no Slurm file is in the repo.

### 3.8 Tracked data and build products

- Native binaries (`<arch>gen`, `eventsim`) are ignored (`.gitignore:53-58`);
  the cache simulator builds into `src/cachesim/native/build/`.
- Tracked data: `input_trace/loas` (14 MB), the four schedules under
  `configs/schedules/loas`, and the fixtures in `src/cachesim/examples/`.

---------------------------------------------------------------------------

## 4. Reproducibility gaps (fresh machine)

What a fresh machine needs:

- Python >= 3.10 (`pyproject.toml:8`) with `numpy`, `PyYAML`, `gurobipy`
  (`requirements.txt:1-3`) and `pytest` (not listed); `pip install -e .`, or
  `PYTHONPATH=src` as the pipeline sets for its children
  (`scripts/pipeline.py:53-54`).
- A Gurobi license for any solve. Not needed while every requested layer has
  a tracked schedule: the pipeline asks for `gurobipy` only when a schedule
  is missing (`scripts/pipeline.py:322-325`), and `solve-trace` imports it
  only when it solves (`src/snn_scheduler/cli.py:18-19`).
- g++ with C++17 and GNU make: `make build` (`Makefile:5-8`) builds the cache
  simulator apps, eventsim and `loasgen`; the other four arch generators
  build from their own `Makefile`.

Inputs missing from the repo:

- The full captures `vgg16_T4_all`, `resnet19_T4_all` (10,000 samples, 25.8 GB
  per `scripts/subset_input_traces.py:3-4`), expected under
  `data_root()/neuro_cache_trace/input_trace/loas/`. Only the `_n5` subset is
  stored.
- `gen`'s default `--n-samples 100` draws indices from `range(10000)`
  (`src/weight_trace_gen/weight_trace.py:199`), out of range for the stored
  B=5 arrays; use `--sample-start/--sample-count` with indices 0-4. The saved
  `sample_idx` is then the array index, not the CIFAR-10 index in
  `meta.json["subset"]`.
- Tracked schedules exist only for 4 loas layers (`configs/schedules/loas`);
  any other layer or arch needs Gurobi.
- Only loas has a nocsim arch (`scripts/pipeline.py:45`), so the pipeline
  refuses any other bench (:144-145, :187-188).
- `--verify-baseline` needs the reference CSVs under `.baseline/after`
  (`scripts/pipeline.py:424-429`), which are not in git.
- Only LoAS-captured spike traces exist; the PTB, SpinalFlow, Prosperity and
  GustavSNN models replay the same spikes.

---------------------------------------------------------------------------

## 5. Open questions the code alone cannot answer

1. Is `configs/arch/loas_inst16_node32kb.yaml` identical to the arch file the
   tracked schedules record in `result.configs.arch`? The code asserts it
   (`src/snn_scheduler/cli.py:186-187`); that file is not in the tree.
2. Are Gurobi solutions deterministic across machines and versions without
   `Seed`/`Threads` (`src/snn_scheduler/solve.py:75-79`)?
3. Should saved traces carry the CIFAR-10 index from `meta["subset"]` instead
   of the 0-4 array index?
4. Is `configs/arch/ptb.yaml` (marked reconstructed, :2) equal to the one any
   past PTB schedule was solved with?
5. Is a non-COUT burst axis meant to be produced from layer traces some day?
   The writer accepts `burst_dim` 0..3 (`src/cachesim/stream.py:65`), but
   `stream_weight_trace` refuses anything but 3 (:195).
6. LoAS COUT node-level spatial capacity: 16 (`src/weight_trace_gen/loas/__init__.py:12`)
   or 4 (`configs/node_mapspace/loas.yaml:9`)?
