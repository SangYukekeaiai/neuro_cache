# Code atlas: the pipeline (input trace -> schedule -> weight trace -> wcache / nocsim -> results)

Repo `neuro_cache-wcache`, branch `wcache-rebuild-phase-a`, commit `39efd64`
(refreshed from the `8fa0916` version; phase 2 cleanup commits `f17278d`..`39efd64`).
Built only from code (`.py .cpp .h .sh Makefile .yaml .json`), `git diff` of
those, and directory listings. No `.md/.txt/.slurm`, notes, logs, or result
files were opened, so anything a README states and the code does not is
absent here. Paths are relative to the repo root. `file:N` means line N of
that file at this commit.

> **Stored WCTS streams must be regenerated.** The writer now emits WCTS
> format version 2 (`WCTS_VERSION = 2`, `src/tracegen.py:508`), and every
> reader at HEAD rejects version 1: the C++ reader
> (`src/wcache/native/include/wcache/stream_format.h:42`, check at :220-228;
> see `docs/atlas/wcache_native.md`) and the two Python decoders
> (`profiling/0823_stagewise_verify/stage2_weight_trace/wcts_excerpt.py:19-22`,
> `profiling/0903_hot_cin/run.py:40-43`). Any `.wcts` file written before
> commit `725474f`, including the 155 files (16 GB, untracked) in
> `profiling/0831_all_layer_streams/streams/`, must be rewritten with
> `scripts/generate_weight_traces.py --stream` (which calls
> `tracegen.stream_weight_trace`), e.g. through
> `profiling/0831_all_layer_streams/gen_streams.py`.

Scope: `src/tracegen.py`, `src/util.py`, `src/parsers/`, `src/archmodels/`,
`src/mip_solver/`, `scripts/` (incl. `env.sh`), `tests/` (Python and shell,
not nocsim internals), `configs/`, `input_trace/`, `profiling/` (13 stages
plus `profiling/common.py`), and how `dump/` and `debug/` touch the pipeline.
`src/wcache`, `src/nocsim` internals are covered elsewhere
(`docs/atlas/wcache_native.md`, `docs/atlas/nocsim.md`); here only how the
pipeline calls them.

---------------------------------------------------------------------------

## 1. Top-down

### 1.1 Purpose

The code measures how weight fetches of spiking-neural-network (SNN)
accelerators behave in an on-chip memory system. For one layer it (a) derives
the layer shape from a captured spike trace, (b) solves a Gurobi MIP
(CoSA-style) for a loop schedule on a given architecture, (c) replays the real
spikes of each input sample through a per-architecture C++ model (LoAS, PTB,
SpinalFlow, Prosperity, GustavSNN) to get, per schedule tile and per core, the
ordered weight addresses and MAC-cycle counts, and (d) feeds that weight trace
either to the cache simulator `wcache` (as a binary WCTS v2 stream) or to the
NoC simulator `nocsim` (as a gzip JSON file). Each `profiling/<date>_<topic>/`
directory is one experiment: a driver that runs (c)+(d) over a grid and joins
the CSV rows into tables and HTML pages.

### 1.2 Entry points

| Entry point | What it does | Flags (default) |
|---|---|---|
| `scripts/solve_schedules.py` `main` :75 | Stage 1: solve every valid layer x arch once, write schedule JSONs + `summary.csv` | `--trace-root` (`<repo>/input_trace/loas`), `--trace-dirs` (`vgg16_T4_n5 resnet19_T4_n5`), `--archs` (all 5), `--cache-dir` (`<repo>/outputs/schedules`), `--force` |
| `scripts/solve_inst16_subset.py` `main` :34 | Stage 1 for the 16-core study: 3 archs x 4 fixed layers against `configs/arch/<arch>_inst16.yaml` | `--trace-root` (required), `--cache-dir` (`<repo>/outputs/schedules/inst16`), `--force` |
| `scripts/generate_weight_traces.py` `main` :404 | Stage 2: load a cached schedule, reconstruct samples through the native bridge; three modes | `--arch` (required; one of 5), `--trace-dir`, `--layer`, `--trace-dirs` (`resnet19_T4_n5 vgg16_T4_n5`, only `--all-layers`), `--trace-root` (`<repo>/input_trace/loas`), `--schedule-cache` (`<repo>/outputs/schedules`), `--out-dir` (`<repo>/outputs/weight_traces`), `--combo-tag` (`""`), `--sample-start` (0), `--sample-count` (none), `--n-samples` (100), `--seed` (0), `--workers` (1), `--force`, `--all-layers`, `--stream`, `--dump-trace PATH`, `--dump-trace-tiles N` |
| `scripts/subset_input_traces.py` `main` :97 | Cut an N-sample subset out of the full 10,000-sample captures | `--src` (`$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas`, :45), `--dest` (`<repo>/input_trace/loas`), `--captures` (`vgg16_T4_all resnet19_T4_all`), `--n` (5), `--seed` (0) |
| `python -m mip_solver` (`src/mip_solver/__main__.py` -> `cli.main` :27) | Stand-alone solver CLI, `solve` / `enumerate` subcommands | `--layer` (`configs/workloads/sample_snn_layer.yaml`), `--arch` (`configs/arch/spinalflow.yaml`), `--dataflow` (`configs/dataflow/spinalflow.yaml`), `--mapspace` (`configs/mapspace/mapspace.yaml`), `--out` (`outputs/schedule.json` / `outputs/enumeration.json`), `--time-limit`, `--mip-gap`, `--solver-log`, enumerate only: `--w-u 0.1 --w-tr 1.0 --w-dl 10.0`. Defaults are cwd-relative (`src/mip_solver/cli.py:20-24`) |
| `profiling/*/run_sweep.py`, `run.py`, `run_*.py` | One experiment each; see 1.7 | mostly positional `[workers]` |
| Native: `src/archmodels/<arch>/<arch>gen` | `<bin> <trace.bin> <task.bin> <out.bin or ->` | built by each arch's `Makefile` |
| Downstream (not in scope): `src/wcache/native/build/{release,fixture}/wcache_run`, `wcache_sweep`; `python -m nocsim.sim` | invoked by profiling drivers | see 1.4 |

Settings read from the environment (phase 2, commit `d2a9de8`):
`NEURO_CACHE_DATA` (data kept outside git; Python reads it only through
`util.data_root()`, `src/util.py:15`; shell scripts through `scripts/env.sh:3`;
default `<repo>/data`) and `CONDA_ENV` (`scripts/env.sh:4`, default `cosa_snn`).

### 1.3 End-to-end data flow

```
input_trace/loas/<wl>/meta.json + layer_NN_*.npy  (uint8 [T,B,Cin,Hin,Win])
   | archmodels.trace.build_workload_from_trace  (KH=KW=3, PAD=1, COUT from meta.json layer_params)
   v
{"problem": {KH,KW,CIN,COUT,HO,WO,T,shape}}  -> temp YAML -> parsers.SNNProb
   | mip_solver.solve.solve_best_schedule  (13 TrafficModes, Gurobi, keep lowest score)   [Gurobi needed]
   v
ScheduleArtifact JSON  <cache>/<arch>/<trace_dir>/<layer>.json
   | tracegen.check_schedule_matches_trace, then tracegen.load_schedule
   |   -> nocsim.schedule.decode.schedule_from_strategy -> iter_node_tiles
   v
list[NodeTileSpec]  (dram_i, noc_i, core_id, node_bound{dim}, tile_offset{dim})
   | archmodels/<arch>/native_bridge: task.bin + trace.bin -> <arch>gen -> out.bin
   | tracegen.assemble_layer_traces (group by (dram_i,noc_i), merge cores per tick, mac=max over cores)
   v
LayerWeightTrace (one per sample)
   |-- save_weight_trace -> sample_NNNNN.json.gz ----> python -m nocsim.sim --weight-trace ... --simulate
   '-- stream_weight_trace -> WCTS v2 bytes (stdout or --dump-trace file) ----> wcache_run / wcache_sweep
                                                                              |
                                               one CSV row per config  <------'
   profiling driver: per-unit CSV -> merged CSV -> *_by_layer.csv -> make_page*.py / build_artifact.py -> HTML
```

Formats crossing each boundary:

1. **Input trace.** `meta.json` `layers` maps layer name -> `[T, B, Cin, Hin, Win]`
   (stored subset: T=4, B=5); `.npy` is that array, `dtype` "uint8" in
   `meta.json`. `load_layer_trace` checks shape equality (`src/archmodels/trace.py:75-80`).
   `meta.json` `layer_params` maps the same names -> `{"cout", "kernel", "stride"}`;
   `layer_params()` (`src/archmodels/trace.py:84`) raises `ValueError` when an entry or
   field is missing (key list `LAYER_PARAM_KEYS`, :29). Both `_n5` metas carry it
   (added 2026-10-26; resnet19 `layerS_0_conv1` and `layerS_0_shortcut_0` have stride 2,
   the shortcuts kernel 1).
2. **Workload dict.** `build_workload_from_trace` (`src/archmodels/trace.py:127`):
   KH=KW=3, stride 1, PAD=1 so HO=Hin, WO=Win (:151); COUT =
   `layer_params[layer]["cout"]` (:154). It raises for a layer `exclusion_reason`
   (:103) names: kernel != 3 or stride != 1 (:112-114; the arch models replay only
   3x3 stride-1 windows, e.g. `src/archmodels/loas/LoASGen.h:74` reads input row
   `ho + kh - pad_h`), or HO/WO < 1 (:116-117). `valid_layer_names` (:121) keeps the
   rest: 25 of the 31 `_n5` layers (resnet19 loses layers 01, 03, 08, 10, 15, 17).
   `tracegen.check_schedule_matches_trace` (`src/tracegen.py:146`) refuses a
   schedule whose `workload.problem` differs from this dict (:157-164).
3. **Schedule JSON** (`tracegen.ScheduleArtifact`, `src/tracegen.py:50`):
   `{arch, trace_dir, layer_name, workload:{problem:{...}}, result:{status,
   has_solution, objective, strategy:{NodeLevel{temporal_tile,spatial_split},
   NoCLevel{temporal_permutation,spatial_splitting}, DRAM{temporal_permutation}},
   metrics:{util, spatial_cost, temporal_traffic, delay, capacity}, configs:{arch,
   dataflow, mapspace (paths as given)}}, dram_num_steps, mode}`. The strategy
   block comes from `util.build_strategy` (`src/util.py:28`).
4. **Native bridge wire format** (all int32, native endian;
   `src/archmodels/loas/main.cpp:6-20`, `src/archmodels/loas/native_bridge.py:26`):
   `task.bin` = `T,B,Cin,Hin,Win`, `num_tiles`, `num_samples`, then 11 int32 per
   tile (12 for GustavSNN, `src/archmodels/gustavsnn/native_bridge.py:34`), then
   sample indices; `trace.bin` = uint8 row-major `[T,B,Cin,Hin,Win]` of only the
   requested samples; `out.bin` = per sample (outer) per tile (inner):
   `tile_idx, sample_idx, mac_cycles, num_ticks`, then per tick
   `tick, n_addr`, then `n_addr` x `(kh,kw,cin,cout_start,cout_end)`
   (`src/archmodels/tick_output.h:35`).
5. **Weight-trace JSON.gz** (`tracegen.LayerWeightTrace` :211 via `asdict`):
   `{arch, trace_dir, layer_name, sample_idx, workload_dims (the inner
   "problem" dict, includes "shape"), dram_num_steps, noc_num_steps, tiles:[{dram_i,
   noc_i, mac_cycles, lif_cycles (always null), ticks:[{tick, cores:[{core_id,
   weight_addresses:[[kh,kw,cin,cout_start,cout_end],...]}]}]}]}`. Path:
   `<out-dir>/<arch>/[<combo-tag>/]<trace_dir>/<layer>/sample_<5 digits>.json.gz`
   (`scripts/generate_weight_traces.py:111-114`).
6. **WCTS v2 stream** (`src/tracegen.py:479-684`): 56-byte fixed header
   (magic `WCTRACE1`, version 2 (:508), header_bytes, n_tiles, n_cores,
   weight_bytes=1, burst_dim, burst_stride=1, burst_span=max run length in the
   layer, n_addr_fields=5, n_spatial, n_dims=7, identity_bytes), then 5 field
   codes `0=KH 1=KW 2=CIN 3=COUT 4=RUN_END` (:515-517), `(dim_id, factor)`
   spatial pairs, `(dim_id, extent)` for all 7 dims, identity
   `arch\0trace_dir\0layer\0sample_idx\0`. Per tile frame `<iiqQ` = tile_index,
   cores-in-frame, mac_cycles (i64), payload bytes; per core `<ii` core_id,
   n_bursts; per burst `<q5i` = local_tick, then the run's full anchor
   `kh, kw, cin, cout`, then `run_end` (28 B, :503-504, :595). The run walks
   `burst_dim` from the anchor's coordinate on that axis (run_start) to
   `run_end` (exclusive). Trailer `<iQ` = -1, total bursts. Dim wire codes
   0=KH..6=T (`:514`), equal to `parsers.layer.DIM_*`. The header writer
   accepts `burst_dim` 0..3 (:530-531); `stream_weight_trace` emits only
   `burst_dim=3` (COUT) and refuses others (:660-665), because
   `LayerWeightTrace` addresses are COUT runs. For a COUT stream the record
   bytes equal version 1's `[kh,kw,cin,run_start,run_end]`; only the version
   field differs (commit `725474f` message).
7. **Simulator outputs.** `wcache_run`/`wcache_sweep` print CSV to stdout or
   `--out`; the header line is now on by default for both and `--no-header`
   turns it off (`src/wcache/native/apps/wcache_run.cpp:46`, :184-185), so the
   `--header` every driver still passes is redundant but accepted. Drivers read
   columns such as `total_cycles, tick_base_total, l1_hit_rate, l2_hit_rate,
   dram_bytes, dram_accesses, stall_*, pf_*, line_size_bytes, l1_num_sets`.
   `nocsim.sim` writes a transaction CSV (`--out`) and, with `--simulate`,
   prints `total_cycles: N`, `unicast_cycles`, `multicast_cycles`,
   `count_cycles`, `dram_cycles` lines that drivers parse
   (`profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:63`).

### 1.4 Key abstractions

```
parsers.SNNProb ---- prime factors per dim -----+
parsers.SNNArch (3 levels, S fanout) -----------+--> mip_solver.solve_schedule (one TrafficMode)
parsers.SNNDataflow (node_dim_capacity) --------+        |  x[(level,dim,factor,k)], y[(var,level)]
parsers.SNNBitwidths (BW_*, DRAM_LATENCY) ------+        v
                                               solve_best_schedule (13 modes, score) --> strategy dict
                                                                                          |
tracegen.ScheduleArtifact (persisted) <---------------------------------------------------+
   | load_schedule
   v
nocsim Schedule + [archmodels.NodeTileSpec] --> ARCH_NATIVE_BRIDGES[arch].reconstruct_samples_native
                                                     | (subprocess <arch>gen)
                                                     v
                         tracegen.LayerWeightTrace{TileWeightTrace{TickEntry{CoreEntry}}}
                         tracegen.StepCycles  (read-back of mac_cycles only, used by nocsim)
```

Invocations of downstream code made by in-scope code, and the reverse:

- `tracegen` imports `nocsim.schedule.decode.schedule_from_strategy` and
  `nocsim.schedule.tiles.iter_node_tiles` (`src/tracegen.py:39-40`);
  `archmodels.dense` imports `nocsim.schedule.decode.Schedule`
  (`src/archmodels/dense.py:18`). In the other direction nocsim imports
  `archmodels` (`src/nocsim/combine.py:74-76`, `src/nocsim/schedule/tiles.py:40`)
  and `tracegen.load_step_cycles` (`src/nocsim/sim.py:335`). The Python
  packages are therefore mutually dependent; only the binaries are one-way.
- nocsim: `python -m nocsim.sim --schedule S.json --layer L.yaml --arch A.yaml
  --weight-trace sample_NNNNN.json.gz --out tc.csv --simulate` with
  `PYTHONPATH=<repo>/src` set by the driver
  (`profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:64-71`,
  `profiling/0831_all_layer_streams/run_compare.py:128`). `L.yaml` is the
  schedule's own `workload` block dumped to YAML.
- wcache: `wcache_run --config C.json --trace X.wcts [--arm cache|spad_oracle]
  [--tier T] [--run-id R] [--git-commit G] [--header|--no-header] [--out -]
  [--access-log F] [--line-trace F --line-trace-level l1] [--cache-state F
  --cache-state-core 0] [--l2-oracle F] [--oracle-only]`; `wcache_sweep
  --config-grid G.json --trace X.wcts|- [--out F] --arm --tier --run-id
  --git-commit --header`. One `wcache_sweep` call accepts only configs that
  agree on the address mapper (`cin_block`, `cout_block`, `weight_bytes`,
  `layout`), so drivers split grids per mapper
  (`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:115-131`,
  `profiling/0907_linesize/run_sweep.py:87-96`).
- cachesim was removed on 2026-10-26 (superseded by wcache; last used by profiling/0803).

### 1.5 One run, step by step (the stream path used by 0820 and every later stage)

1. `generate_weight_traces.py --stream --arch loas --trace-dir D --layer L
   --sample-start s --sample-count 1 --schedule-cache C` -> `parse_args` :351
   rejects `--workers>1`, `--all-layers`, missing `--trace-dir/--layer`
   (:396-401).
2. `run_stream` :299: `_resolve_samples` :74 gives `[s]`; checks
   `C/loas/D/L.json` against meta.json with `tracegen.check_schedule_matches_trace`
   (:314-319), then loads it.
3. `tracegen.load_schedule` (`src/tracegen.py:130`): JSON -> `ScheduleArtifact`;
   the workload is dumped to a temp YAML (`_dump_workload_path` :62,
   `delete=False` at :63), parsed as `SNNProb`; `schedule_from_strategy`
   decodes the strategy; `iter_node_tiles` yields one `NodeTileSpec` per
   (dram step, NoC step, core).
4. `n_cores` = product of `schedule.spatial_factors` (`scripts/generate_weight_traces.py:330-332`),
   so idle cores still count.
5. `load_layer_trace(..., mmap=True)` maps the `.npy` (:322).
6. `tracegen.reconstruct_samples` (`src/tracegen.py:294`) imports
   `ARCH_NATIVE_BRIDGES[arch]` and calls `reconstruct_samples_native`: slice
   `trace[:, samples]` to contiguous uint8 (`src/archmodels/loas/native_bridge.py:103`),
   write `trace.bin` and `task.bin` in a temp dir, run `loasgen trace.bin
   task.bin out.bin`, parse (`_unpack_output` :45, asserts every byte
   consumed), then `assemble_layer_traces` (`src/tracegen.py:239`).
7. `emit_stream` (`scripts/generate_weight_traces.py:272`) ->
   `stream_weight_trace` (`src/tracegen.py:642`): converts tick-major to
   core-major frames (`_wcts_tile_frames` :605), writes header, frames
   (`write_tile_frame` :563 with `burst_dim=3`), trailer to stdout; with
   `--dump-trace`, a second pass writes the same bytes (or the first N tiles
   plus a valid trailer) to a file.
8. The consumer (`wcache_sweep --trace -`) reads stdin and writes one CSV row
   per config. The 0820 driver wires the pipe and starts the producer with
   `cwd=ROOT` (`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:252-254`),
   checks row count equals config count, then `os.replace`s the per-unit CSV
   into place (:263-268).
9. The driver merges unit CSVs (`merge_results` :280). Later stages instead
   aggregate rows per (layer, arm) as means over 5 samples, join against
   nocsim `all_layers_vs_nocsim.csv`, and render HTML.

### 1.6 Canonical commands

Every `scripts/*.py`, `scripts/tmp/*`, and profiling driver now resolves the
repo root from `__file__` (e.g. `scripts/generate_weight_traces.py:46-47`),
so they run from any cwd. Still cwd-relative: `python -m mip_solver`
(defaults at `src/mip_solver/cli.py:20-24`), `python -m nocsim.sim` (needs
`PYTHONPATH=src`), and the five `dump/scripts` files listed in 3.4.

```
# settings (optional; defaults shown)
export NEURO_CACHE_DATA=<repo>/data CONDA_ENV=cosa_snn

# build (once per machine)
make -C src/archmodels/loas            # also ptb, spinalflow, prosperity, gustavsnn
make -C src/wcache/native MODE=release lib apps      # per comment at 0820 run_sweep.py:34
make -C src/nocsim/eventsim

# Stage 1 (Gurobi)
python scripts/solve_schedules.py --archs loas
python profiling/0831_reuse_distance/solve_31.py   # loas, inst16, all 31 _n5 layers

# Stage 2, file form (sample indices must be < 5 for the stored subset)
python scripts/generate_weight_traces.py --arch loas --trace-dir vgg16_T4_n5 \
    --layer layer_01_features_3 --sample-start 0 --sample-count 5

# Stage 2, stream form (WCTS v2), into wcache
python scripts/generate_weight_traces.py --stream --arch loas --trace-dir vgg16_T4_n5 \
    --layer layer_08_features_27 --sample-start 0 --sample-count 1 \
    --schedule-cache profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules \
  | src/wcache/native/build/release/wcache_sweep --config-grid grid.json --trace - --out rows.csv --arm cache --tier t

# regenerate the 0831 streams as v2 (needed before any 0831+ wcache stage)
python profiling/0831_all_layer_streams/gen_streams.py --workers 16

# nocsim on a saved sample
PYTHONPATH=src python -m nocsim.sim --schedule <sched.json> --layer <workload.yaml> \
    --arch profiling/0823_stagewise_verify/stage3_nocsim/inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml \
    --weight-trace <sample_00000.json.gz> --out tc.csv --simulate
```

Runnable today with tracked inputs:

- **Without Gurobi**: Stage 2 for the 4 layers V8/V9/R9/R16 against the tracked
  16-core schedules in `profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules/loas/*_n5/`
  and single-node schedules in `.../stage3_nocsim/inputs/schedules_single_node/loas/*_n5/`;
  then `wcache_run/wcache_sweep` and `nocsim.sim` with the tracked
  `stage3_nocsim/inputs/{arch,layers}`. Also the 0820 fixture grids
  (`grids/demo.json`, `grids/duplicate_check.json`, read from
  `src/wcache/examples/`), and `tests/test_stream_writer.py`,
  `tests/test_stream_dump.py`, `tests/test_weight_resend.py`.
- **With Gurobi**: `scripts/solve_schedules.py` (defaults already point at
  `_n5`), `profiling/0831_reuse_distance/solve_31.py` followed by
  `run_assoc31.py` / `analyze31.py` (they generate streams on the fly, so
  they get v2), `profiling/0823_stagewise_verify/stage3_nocsim/run_armS_stage12.py`.
- **Not runnable as written**: anything naming `*_T4_all` until
  `$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas/` holds the full
  captures (0803, 0820 campaign grids, 0823 stage1, 0831_all_layer_streams/solve_all_layers.py,
  `scripts/solve_inst16_subset.py`); `tests/test_stream_flag.sh`, which asks for
  `vgg16_T4_all` without `--trace-root` (`tests/test_stream_flag.sh:13-17`), so
  it reads `<repo>/input_trace/loas` and fails even with the data present;
  and every stage after 0831 until `profiling/0831_all_layer_streams/{streams,outputs}`
  are regenerated as v2 (`streams/` holds v1 files that every reader rejects;
  `outputs/` is absent) and `profiling/0823_stagewise_verify/stage4_wcache/inputs/streams`
  is regenerated (absent on this disk).

### 1.7 The 13 profiling stages

All drivers resolve `ROOT` from `__file__`, insert `ROOT/src` into `sys.path`,
and write under the stage's own `outputs/` unless noted. Twenty driver files in
nine stage directories also insert `ROOT/profiling` and import
`profiling/common.py` (2.9.1). "5 samples" means array indices 0-4 of the
`_n5` subset. Tags: `V<n>`/`R<n>` = vgg16/resnet19 layer number n.

| Stage | Driver(s) | Inputs | Simulator invoked | Swept parameters | Outputs |
|---|---|---|---|---|---|
| `0728_status_replay` | `build_artifact.py` `main` :58 | tracked `loas_cout_only.csv`, `loas_cin_cout_2d.csv` | none in this dir; CSV producer not in the stage | validation expects 31 layers x 4 sizes x 3 structures x 3 line sizes per layout, 2 layouts, n=5 (:35-53) | `artifact/data.js` (tracked) |
| `0803_l1_l2_cache` | `run_sweep.py` `main` :219 (`--run`, `--workers`, `--unit-index`, `--merge-only`), `build_artifact.py` :164; `run_sweep.slurm` (not read) | `sample_0000{0..4}.json.gz` under `$NEURO_CACHE_DATA/neuro_cache_outputs/weight_traces/loas/<arch_config>/<wl>_T4_all/<layer>/` (:24); `outputs/schedules/multinode_sweep/classification.csv` (build) | cachesim (removed 2026-10-26 with this stage's `run_sweep.py`/`.slurm`) | 4 arch configs (inst16/inst1024 x noc512kb/noc4096kb, node32kb) x 31 layers x 5 samples = 124 units; per sample 24 configs = {FA, 32-way, 4-way} x L1 {16,32} KB x L2 {128,256,512,1024} KB (:35-47) | `results/*.csv`, `per_core/*.csv.gz`, `hierarchical_cache_results.csv` (absent), `artifact/` (tracked) |
| `0820_phaseD_spad_vs_cache` | `run_sweep.py` `main` :339 (`--grid`, `--run`, `--tier`, `--workers`, `--unit-index`, `--merge-only`, `--dry-run-units`, `--trace-root`, `--results-dir`, `--out`); `tests/*.sh` | `grids/*.json`; units name `*_T4_all` trace dirs and `schedule_cache` (e.g. `outputs/schedules/inst16`); fixtures from `src/wcache/examples/` | `generate_weight_traces.py --stream` piped into `wcache_sweep --trace -` | `tier0`/`tier3_full`: 180 = L1 {2,4,8,16,32} KB x cin_block {1,2,4} x L2 {256K,512K,1M} x prefetch {none, next_burst 2/4/8}; `cache16`: 36 (L1 8 KB; cin_block x L2 x prefetch), 3 archs x 4 layers x 5 samples; `cache16_l1_16k` 12; `cache16_lat` 12 (l2_latency 5, miss 50); `tier2_ridge` 15; `tier4_latency` 5; `tier1_spad` 1 (arm `spad_wcache`); `demo` 4; `duplicate_check` 4 | `results/<tier>/<unit>.csv`, merged `--out` (default `spad_vs_cache.csv`); tracked `cache16*_results.csv` |
| `0823_stagewise_verify` | stage1 `run_stage1.py`; stage2 `run_stage2.py`, `verify_reconstruction.py`, `wcts_excerpt.py`; stage3 `run_stage3.py`, `run_armS_stage12.py`; stage4 `inputs/gen_streams.sh`, `oracle_gate.py`, `run_w5.py`, `run_khkw_sweep.py`, `run_l2_capacity_probe.py`, `run_layout_control.py`, `analyze_khkw_sweep.py`, `build_artifact.py`; `input_trace_audit/audit_density.py` | 4 layers (vgg16 layer_08/09, resnet19 layer_09/16); stage1 reads `_all` `meta.json` under `data_root()` (`run_stage1.py:46`) and `configs/arch/multinode_sweep/loas_inst16_node32kb_noc4096kb.yaml`; stage2+ read `input_trace/loas/*_n5` | Gurobi (stage1); generator + `loasgen` (stage2); `nocsim.sim --simulate` (stage3); `wcache_run`, `wcache_sweep` (stage4) | stage1: num_pes {4,16,64,256}; all 13 TrafficModes; NoC totals {8 KiB..4 MiB} split 30:1:1. stage4: configs C2-C6 x layouts {block_pack, split_cin}; khkw_split line {16,32,64} B x l2_banks {1,2,4,8} x prefetch distance {0,1,2,4} (48 x 20 = 960 rows); L2 {512K..16M}; 3 layouts at the best point | per-stage `inputs/` + `outputs/`; 196 tracked files (about 1.9 MB). Since `9012d22` the 40 bulk stage-3 outputs are untracked and ignored (3.7) |
| `0831_all_layer_streams` | `solve_all_layers.py [--check]`, `gen_streams.py [--check] [--workers]`, `gen_weight_traces.py`, `run_compare.py --workers` | arch/dataflow from 0823 stage1 inputs (`noc2MiB_pe16`); `_all` meta under `data_root()` (solve, :52); `input_trace/loas/*_n5` | Gurobi; generator via `sys.executable` (`gen_streams.py:41`); `wcache_sweep` (one config `BEST`); `nocsim.sim --simulate` | none: 31 layers x 5 samples at one config | `schedules_all/`, `schedules/`, `streams/` (155 files, 16 GB, untracked, WCTS v1), `weight_traces/`, `outputs/{wcache_rows.csv, nocsim_rows.json, all_layers_vs_nocsim.csv}` (absent) |
| `0831_l2_prefetch` | `run_sweep.py [workers=16]`, `analyze.py`, `build_artifact.py <out.html>` | 0831 `streams/`, 0831 `outputs/` | `wcache_sweep` (tier `l2pf`) | `l2_prefetch_policy` none vs `neighbour` on cin, up / down / both (4 configs) | `outputs/l2pf_rows.csv`, `l2pf_by_layer.csv`, HTML |
| `0831_reuse_distance` | `solve_31.py`, `run_assoc31.py`, `analyze31.py`, `run_reuse_hist.py`, `run_belady.py`, `analyze_reuse.py`, `plot_reuse.py`, `build_profile31.py`, `build_assoc31_artifact.py`; C++ `reuse_tool.cpp`, `reuse_distance.h`, `test_reuse_distance.cpp` | `configs/arch/loas_inst16.yaml`; `input_trace/loas/*_n5`; `outputs/schedules/inst16`; 0823 stage4 streams + `_khkw_grid/khkw_64b.json` | Gurobi (solve_31); generator; `wcache_run` with `--access-log`, `--cache-state`, `--l2-oracle`; `reuse_tool` | `l2_assoc` 16 vs 32 over 31 layers; Belady: 6 arms (LRU/Belady x 16-way, 64-way, FA; `run_belady.py:40-47`); reuse histograms at the khkw best config | `outputs/*.csv`, `spectra.svg`; tracked `artifact.html`, `assoc31.html` |
| `0902_l1_evictions` | `run.py [workers=8]` | 0831 `streams/`, sample 0 only | `wcache_run --out - --line-trace F --line-trace-level l1` | none (`CONFIG = base_config()`, :41) | `outputs/l1_evict.csv` |
| `0903_hot_cin` | `run.py [--demo / --tiles / --reuse / --reuse-times / --topn / --hot]` | 0823 stage4 `inputs/streams/{V8,V9,R9,R16}_s*.wcts` | none: decodes WCTS v2 in NumPy (`read_stream` :34) | analysis mode only | `outputs/hot_cin*.json` |
| `0903_l1_8k` | `run_sweep.py [workers=16]` | 0831 `streams/`, `all_layers_vs_nocsim.csv` | `wcache_sweep` (tier `l1cap`) | `l1_size_bytes` {16384, 8192} | `outputs/l1cap_{rows,by_layer,aggregate}.csv` |
| `0907_assoc` | `run_sweep.py [workers]`, `make_page.py` | as 0903_l1_8k | `wcache_sweep` (tier `assoc`) | `l1_assoc` {32, 16, fully assoc} x `policy` {lru, rrip} x L1 {16K, 8K} = 12 points | `outputs/assoc_{rows,by_layer}.csv`, `page_assoc.html` |
| `0907_index_policy` | `run_sweep.py [workers]`, `make_pages.py` | as above | `wcache_sweep` (tier `policy`) | `policy` {lru, rrip, lfu} x L1 {16K, 8K} = 6 | `outputs/policy_{rows,by_layer,aggregate}.csv`, `page_16k.html`, `page_8k.html` |
| `0907_linesize` | `run_sweep.py [workers]`, `make_page.py` | as above | `wcache_sweep`, 3 passes per stream (tier `linesize`) | `cin_block` {16,8,4} (64/32/16 B lines) with `l1_assoc` {32,64,128} so sets stay fixed, x L1 {16K, 8K}; policy rrip, `rrip_bits` 5 | `outputs/line_{rows,by_layer}.csv`, `page_linesize.html` |

Common base config after 0823, now defined once as `BASE` in
`profiling/common.py:13-18`: `layout khkw_split, cin_block 16, cout_block 4,
weight_bytes 1, l1 16 KB 8-way, l2 512 KB 16-way, l2_mshrs 32, l2_banks 1,
l1_latency 0, l2_latency 2, l2_miss_latency 24, prefetch none (distance 0),
l2_prefetch none`. Drivers take subsets or overrides through
`base_config(keys, drop, **extra)` (:28), e.g.
`profiling/0831_all_layer_streams/run_compare.py:62`,
`profiling/0903_l1_8k/run_sweep.py:27`.

---------------------------------------------------------------------------

## 2. Bottom-up

### 2.1 `src/tracegen.py` (718 lines): solve / reconstruct / persist / stream

- `ScheduleArtifact` :50 dataclass. `mode` defaults to `"base"` so old caches load (:59).
- `_dump_workload_path(workload)` :62 writes a temp YAML with `delete=False`
  (:63) and never removes it; `_prob_from_workload` :68 wraps it in `SNNProb`.
- `solve_and_cache_schedule(arch_name, arch_yaml, dataflow_yaml, trace_dir_name, layer_name, meta, cache_dir)` :71
  -> builds workload, calls `mip_solver.solve.solve_best_schedule` (imported
  lazily :99 so the rest of the module needs no `gurobipy`), decodes to get
  `dram_num_steps`, writes `cache_dir/<arch>/<trace_dir>/<layer>.json` (:123-126).
  Always re-solves; raises `ValueError` if all modes infeasible (:107-111).
- `load_schedule(path)` :130 -> `(artifact, prob, tiles)`; tiles rebuilt with
  `iter_node_tiles`, not stored.
- `check_schedule_matches_trace(schedule_path, trace_dir, layer_name)` :146: raises
  `ValueError` naming the schedule path when its `workload.problem` differs from
  `build_workload_from_trace` on `trace_dir/meta.json` (stale schedule, "re-solve with
  `scripts/solve_schedules.py --force`") or the layer is excluded. Called before every
  `load_schedule` in `scripts/generate_weight_traces.py` (:150, :212, :315) and by
  `scripts/demo.py` `schedules_for` (:264).
- `CoreEntry` :149, `TickEntry` :160, `TileWeightTrace` :197, `LayerWeightTrace` :211:
  the nested trace shape. Absent cores are omitted, not padded.
- `merge_cores_by_tick(core_results)` :169: cross-core merge, ticks ascending.
- `tick_entries_from_flat(weight_addresses, tick_ids)` :222: old flat-format
  adapter; no caller in `src/`, `scripts/`, `profiling/`; kept for
  `debug/09_verify_tick_entries_from_flat.py:21` and
  `dump/python_reference/tracegen_reconstruct.py:25` (commit `f17278d`).
- `assemble_layer_traces(tiles, sample_indices, unpacked, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :239:
  keys on each record's own indices; `noc_num_steps = max(noc_i)+1` (:265);
  `mac_cycles = max` over cores (:280); `lif_cycles=None` always (:282).
- `reconstruct_samples(arch_name, trace, tiles, sample_indices, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :294:
  the single dispatcher to `ARCH_NATIVE_BRIDGES` (`KeyError` for an unknown arch).
- `save_weight_trace(trace, path)` :326: gzip JSON written to a temp file then
  `os.replace` (:348; no partial files).
- `StepCycles` :355 + `check_against(artifact, schedule)` :384: read-back of
  per-(dram_i, noc_i) `ComputeCycles` with six identity checks; compares
  `artifact.workload["problem"]` to `workload_dims`.
- `load_step_cycles(path)` :432: accepts `.json` or `.json.gz`; rejects duplicate
  tiles (:454) or tile count != `dram_num_steps*noc_num_steps`. Used by nocsim
  (`src/nocsim/sim.py:335`).
- WCTS v2 (changed in phase 2, commit `725474f`). Constants :507-518
  (`WCTS_VERSION = 2` :508, field codes `0=KH 1=KW 2=CIN 3=COUT 4=RUN_END`
  :515-517, `_WCTS_BURST_BYTES` = 28 :518).
  - `write_stream_header(...)` :521: new check that `burst_dim` is one of
    0..3 (:530-531), before any byte is written; then
    prod(spatial_factors)==n_cores (:535) and all 7 dims present (:540).
  - `write_tile_frame(fh, *, tile_index, mac_cycles, cores, burst_dim)` :563:
    `burst_dim` is a new required keyword. Each burst is
    `(local_tick, (kh, kw, cin, cout, run_end))`; checks core ids ascending
    (:576), no empty cores (:578), ticks strictly ascending (:584), and the new
    rule that the run is not empty along `burst_dim`, i.e.
    `run_end > anchor[burst_dim]` (:589-593).
  - `write_stream_trailer` :600.
  - `_wcts_tile_frames(tiles, n_cores)` :605: tick-major -> core-major; rejects
    core ids outside `[0,n_cores)` (:619), empty COUT runs (:626), and measures
    `burst_span` as the largest `cout_end - cout_start` (:631).
  - `stream_weight_trace(trace, fh, *, n_cores, spatial_factors, burst_dim=3, burst_stride=1, weight_bytes=1, max_tiles=None)` :642:
    refuses any `burst_dim` other than 3 (:660-665) because layer-trace
    addresses are COUT runs; a non-COUT stream has to be written with
    `write_stream_header` + `write_tile_frame` directly (only tests do).
- `sample_indices(n=100, seed=0, n_total=10000)` :691: canonical 100 =
  `random.Random(0).sample(range(10000),100)` (:711), n>100 adds more at
  `seed`; n<100 raises. Indices refer to the full 10,000-sample capture.

### 2.2 `src/util.py` (156 lines)

- `data_root()` :15 (new, commit `d2a9de8`): `Path($NEURO_CACHE_DATA)` when set
  and non-empty, else `<repo>/data` (:24-25), with no log of the fallback.
  Layout documented at :18-23: `neuro_cache_trace/input_trace/loas/<capture>/`
  for full captures, `neuro_cache_outputs/weight_traces/` for generated
  traces. Callers: `scripts/subset_input_traces.py:45`,
  `profiling/0803_l1_l2_cache/build_artifact.py:22` (its `run_sweep.py` was removed 2026-10-26),
  `profiling/0823_stagewise_verify/stage1_mip_solver/run_stage1.py:46`,
  `.../input_trace_audit/audit_density.py:13`,
  `profiling/0831_all_layer_streams/solve_all_layers.py:52`, three
  `scripts/tmp/` files, four `dump/scripts/` files.
- `build_strategy(levels)` :28: fuses solver factor placements into the
  `NodeLevel / NoCLevel / DRAM` strategy dict; NoC/DRAM temporal blocks are
  displayed outer-to-inner (reversed). Helpers `_region_levels` :67,
  `_strategy_block` :71, `_tile_block` :83, `_loops` :90, `_fuse_kind` :97
  (fuses adjacent same-dim), `_fuse_same_dim_kind` :107 (fuses all same-dim),
  `_append_or_fuse` :127, `_new_segment` :138, `_format_order` :150. `REGIONS`,
  `KINDS` :11-12 are unused.

### 2.3 `src/parsers/`

- `__init__.py`: re-exports the five parsers.
- `layer.py`: `DIM_KH..DIM_T = 0..6` :35-41; `SNN_REDUCTION_DIMS` = {KH,KW,CIN} :47;
  `_get_prime_factors` :50 (1 -> [1]); `parse_snn_layer` :67; `SNNProb` :85
  (`prob_bound`, `prob_factors`, name/index maps; unknown keys only warned);
  `config_str` :159, `is_reduction_dim` :163, `print` :167.
- `arch.py`: `MEM_NODE/NOC/OFFCHIP` :63-65; `parse_snn_arch` :68; `SNNArch` :86:
  levels must be exactly `[NodeLevel, NoCLevel, OffChip]`; `node_dim_capacity`
  here is an error (belongs in dataflow); `S[i]=instances[i]//instances[i+1]`
  (`_gen_spatial_constraints` :199); `single_node` flag (:172); properties
  `has_local_buffer` :186, `has_noc_buffer` :191; private parsers :210-335;
  `config_str` :341 (file stem).
- `bitwidths.py`: defaults :32-35 (BW_WEIGHT 8, BW_PSUM 32, BW_VMEM 32,
  DRAM_LATENCY 0.25 cycles per 32-byte packet, fractional on purpose);
  `parse_snn_bitwidths` :38; `SNNBitwidths` :55 (docstring now matches the
  defaults, :59-61).
- `dataflow.py`: `FULL="full"` :15; `parse_snn_dataflow` :18; `SNNDataflow` :22:
  value = positive int cap, `full`, or `{spatial: N}`; omitted dims are barred
  from NodeLevel; `validate_for_arch` :109 checks spatial product <= `num_pes`.
- `mapspace.py`: `parse_snn_mapspace` :39; `SNNMapspace` :52 (`init` :122,
  `get_default_perm` :171, `get_default_factor` :187, `is_spatial_dim` :201,
  `print` :205, `_check_init` :220). Parsed by `solve_schedule` but not used by
  any constraint (see 3.1).

### 2.4 `src/archmodels/`

Python:

- `__init__.py`: `ARCH_NATIVE_BRIDGES` :31 (arch -> bridge module path);
  `NodeTileSpec` :41 (`dram_i, node_bound, tile_offset, is_last_K, noc_i=0, core_id=0`);
  `ComputeCycles` :56 (`lif_cycles=None` = no MAC/LIF split);
  `ArchComputeModel` Protocol :68 (`format_input` :71, `format_input_batch` :75,
  `compute_cycles` :82, `weight_addresses` :86, `weight_ticks` :96), left from
  the Python models now under `dump/python_reference/archmodels/`; only
  `DenseStaticComputeModel` implements it.
- `dense.py`: `_dim_totals` :24; `DenseStaticComputeModel(schedule, prob)` :32:
  same MAC/LIF count for every tile from the loop factors (`_pe_cycles` :52,
  `_lif_cycles` :67 counts only dims with `_A[j][VAR_VMEM]`). Used by nocsim when
  no weight trace is given (`src/nocsim/combine.py:224`).
- `trace.py`: `KH = KW = 3` :26, `LAYER_PARAM_KEYS` :29, `PAD = 1` :30;
  `load_layer_trace(trace_dir, layer_name, mmap=False)` :39 (docstring says uint8, :5 and :54);
  `layer_params(meta, layer_name)` :84; `exclusion_reason(meta, layer_name)` :103
  (kernel/stride, then HO,WO>=1); `valid_layer_names(meta)` :121 (layers whose
  `exclusion_reason` is None); `build_workload_from_trace(meta, layer_name)` :127
  (COUT from `layer_params`).
- `<arch>/__init__.py` (5 files): docstrings only (paper, fixed deployment);
  they now name the C++ header and the Python reference under
  `dump/python_reference/archmodels/<arch>/` (e.g. `src/archmodels/loas/__init__.py:5-7`).
- `<arch>/native_bridge.py` (5 near-identical files; loas lines given):
  `_BINARY` :23; `_pack_task(trace_shape, tiles, sample_indices)` :26;
  `_unpack_output(data, num_tiles, sample_indices)` :45;
  `reconstruct_samples_native(trace, tiles, sample_indices, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :72
  (docstring :82-83 now points at `dump/python_reference/tracegen_reconstruct.py`).
  The binary sees local indices 0..n-1 after slicing, but the returned traces
  carry the caller's indices. Per-arch tile record: loas/ptb/spinalflow
  `dram_i, ho, wo, kh_n, kw_n, cin_off, cin_n, t_off, t_n, cout_off, cout_n`;
  prosperity `dram_i, ho_off, ho_n, wo_off, wo_n, kh_n, kw_n, cin, t, cout_off, cout_n`
  (`src/archmodels/prosperity/native_bridge.py:27`); gustavsnn 12 fields with
  `t_offset` and HO/WO ranges (`src/archmodels/gustavsnn/native_bridge.py:34`).

C++ (each `Makefile`: `g++ -O2 -std=c++17 -Wall -Wextra -o <arch>gen main.cpp`):

- `tick_output.h`: `write_tick_grouped(out, addresses)` :35 buckets by `.tick`
  with `std::map` (ascending).
- `<arch>/main.cpp` `main` (loas :54; ptb/spinalflow/prosperity :53; gustavsnn :62):
  reads task/trace, output path `-` = stdout, loops sample-outer / tile-inner
  (`src/archmodels/loas/main.cpp:134-143`), and every arch calls
  `write_tick_grouped` (e.g. `src/archmodels/ptb/main.cpp:140`). The 5 files
  differ only in names and the tile-record fields.
- `loas/LoASGen.h` `reconstruct_sample` :64: one tile = one (ho, wo) pixel;
  walk (kh, kw, cin), emit an address when that input site spikes at any t in
  `[t_off, t_off+t_n)`; tick = emission index; `mac_cycles` = number emitted.
- `ptb/PTBGen.h`: `TW_SIZE=8, PE_ROWS_MAX=16, PE_COLS_MAX=8` :41-43;
  `compute_cycle_count(ln, cout_n, total_t)` :77 systolic fill/drain;
  `reconstruct_sample` :87: Pass 1 silence removal (addresses), Pass 2 merge of
  non-overlapping neighbours gives `ln`; `mac_cycles = max(access, compute)`.
- `spinalflow/SpinalFlowGen.h` `reconstruct_sample` :56: one address per spike
  event, t outermost (:69); tick = event index.
- `prosperity/ProsperityGen.h`: `popcount64` :80; `reconstruct_sample` :90: rows
  sorted by popcount, prefix row by subset test, address per set bit of the XOR
  pattern; emitted in processing order.
- `gustavsnn/GustavGen.h`: `PE_COUNT_MAX=8` :35; `reconstruct_tile` :82 (per-HO-row
  submatrices), `addresses_and_ticks` :132 (waves of 8 submatrices; tick =
  wave_start + line index, so several addresses share a tick),
  `reconstruct_sample` :171.
- The `<Arch>Gen.h` header comments (line 3 of each) now cite
  `dump/python_reference/archmodels/<arch>/{reconstruct,address,cycles}.py`,
  which exist.

### 2.5 `src/mip_solver/` (3.3k lines)

- `__init__.py`: re-exports constants only (no `gurobipy`); `build_Z` no
  longer exported (removed in `f17278d`). `__main__.py`: `cli.main()`.
- `constants.py` (96 lines): `SNN_GB_START_LEVEL=1` :51; `VAR_WEIGHT/PSUM/VMEM`
  0/1/2 :57-59; `TRAFFIC_MULT=[1,2,2]` :68; `_A` :76 (dim -> var size
  relation); `_B` all ones :92. The `build_Z` function and the Z-matrix text
  are gone.
- `schedule.py`: `create_schedule_vars(m, prob, arch, gb_start_level=1)` :49:
  binary `x[(i,j,n,k)]` (k 0=spatial 1=temporal) over `total_levels = 1+2P`
  (P = total prime-factor count, :73-76); integer `y[(v,i)]` over NoC+DRAM slots.
- `modes.py`: `TrafficMode` :53 (13 values: base, psum_{dram,gb}_otok,
  vmem_{dram,gb}_xxxt, dram_{oooo,ooot,oook}, both_dram_ootk, gb_{oooo,ooot,oook,ootk});
  `_ModeSpec` :73; `_MODE_SPECS` :79 maps each to a constraint adder +
  `zero_vars` / `gb_only_vars`.
- `solve.py`: `solve_schedule(layer_path, arch_path, dataflow_path, mapspace_path=None, time_limit=None, mip_gap=None, output_flag=False, traffic_mode=BASE, return_metrics=False)` :54:
  builds parsers, vars, constraints, objective; a new comment marks the
  mapspace as parsed but unused (:77-83); sets only `OutputFlag`,
  `TimeLimit`, `MIPGap` (:85-90); `model.dispose()` in `finally` (:171-178);
  records config paths (:180-184). `_collect_result` :188,
  `_extract_strategy` :222, `_region` :249, `_status_name` :257, `_safe_attr` :261,
  weights `0.1, 1.0, 10.0` (:271), `_mode_score` :274,
  `solve_best_schedule(layer, arch, dataflow)` :281 (loops all 13 modes; the
  call at :303 passes no mapspace and no time limit).
- `enumerator.py`: `enumerate_modes(...)` :29 (same loop, returns all
  candidates); `_comparison_score` :104 (same formula as `_mode_score`).
- `cli.py`: `main` :27, `_build_parser` :41, `_run_solve` :109 (exit 3 if no
  solution), `_run_enumerate` :131 (also writes `.txt` summary), `_write_json` :158,
  `_print_summary` :165, `_print_enumeration_summary` :177,
  `format_enumeration_summary` :252, `_fmt_perm` :264, `_fmt_unordered` :279,
  `_autoscale` :294, `_print_wrapped` :302.
- `metrics.py`: `extract_metrics(...)` :158 (linear-scale util, spatial_cost,
  temporal_traffic, delay, capacity); helpers `_eval_util` :33,
  `_eval_spatial_cost` :59, `_eval_temporal_traffic` :85, `_eval_delay` :139.
- `constraints/assignment.py`: `add_assignment_constraints` :39 (each factor in
  one level; spatial xor temporal; one factor per perm slot; y monotone),
  `_add_y_monotonicity` :125.
- `constraints/spatial.py`: `add_spatial_constraints` :35 (per-region fanout
  <= S; S==1 regions forbid spatial outright).
- `constraints/node_level.py`: `_largest_divisor_leq` :48,
  `add_pe_spatial_split_constraints` :62 (pins `{spatial: N}` dims at level 0).
- `constraints/node_capacity.py`: `_max_product_leq` :64,
  `add_node_capacity_constraints` :80 (temporal caps at level 0),
  `add_no_noc_level_constraints` :162 (single_node archs: no NoC perm slots).
- `constraints/temporal_order.py`: big-M slot helpers `_wslot` :49,
  `_in_region` :58, `_above_all_k` :67, `_above_all_t` :81, `_t_above_all_o` :94;
  one adder per mode: `add_ootk_gb` :113, `add_ootk_dram` :173, `add_otok_dram` :220,
  `add_otok_gb` :272, `add_xxxt_dram` :329, `add_xxxt_gb` :369, `add_oooo_dram` :419,
  `add_oooo_gb` :457, `add_ooot_gb` :491, `add_ooot_dram` :534, `add_oook_gb` :575,
  `add_oook_dram` :619. All take `(m, x, prob, gb_start_level, dram_start, perm_levels)`.
- `objectives/combined.py`: `build_objective(...)` :15:
  `10*comp_hat - 0.1*util_hat + 1.0*traffic_hat`, minimized.
- `objectives/compute.py`: `build_compute_objective` :24 (sum of ln(factor) over
  temporal placements).
- `objectives/utilization.py`: `build_utilization_terms` :41,
  `_build_noc_utilization` :76, `_build_node_util_reward` :109 (docstring no
  longer refers to the removed Z matrix),
  `_build_data_size` :147 (coefficients `0.8+0.04*i`),
  `add_utilization_capacity_constraints` :177, `_bytes_by_var` :197,
  `_loop_upper_for_global_buffer` :205.
- `objectives/traffic/spatial.py` `compute_spatial_traffic` :38;
  `temporal.py` `compute_temporal_traffic` :55; `total.py` `build_traffic_cost` :32
  (`0.99*data_size + 0.99*spatial + temporal`, zero_vars dropped).
- `analysis/dram_permutation.py`: `SUPER_DIM` :23, `classify_permutation(loops)` :31
  (M/N/K/T string), `classify_schedule_file(path)` :43. Used only by `scripts/tmp/analyze_*`.

### 2.6 `scripts/`

- `env.sh` (5 lines, new in `d2a9de8`): sourced as `. "$root/scripts/env.sh"`
  after the caller sets `root`; defaults `NEURO_CACHE_DATA=$root/data` (:3) and
  `CONDA_ENV=cosa_snn` (:4), exports both (:5). Sourced by
  `tests/test_stream_flag.sh:10`, `scripts/tmp/run_combo.sh:12`,
  `scripts/tmp/run_loas_sweep_combo.sh:10` (and, per the `d2a9de8` commit
  message, `profiling/0820_phaseD_spad_vs_cache/run_sweep.slurm`).
- `solve_schedules.py`: `ROOT` from `__file__` (:23-24); `parse_args` :47,
  `_iter_valid_layers` :60, `main` :70 (rows
  OK/SKIPPED/INFEASIBLE/ERROR -> `summary.csv` :109). Arch YAML fixed by name
  :34-40 (single-node files, now `ROOT`-absolute); no override flag.
- `generate_weight_traces.py`: `ROOT` from `__file__` (:46-47);
  `DEFAULT_TRACE_ROOT` :57; `_resolve_samples` :74 (explicit range, else
  `tracegen.sample_indices`); mode 1 `run_one_combo` :126 with `_STATE` :89,
  `_init_worker` :92, `_process_chunk` :104, `_chunks` :119 (skip existing
  samples :141 unless `--force`); mode 2 `run_all_layers` :251 with
  `_layers_for` :186, `_all_layer_targets` :192, `_regenerate_layer` :200
  (`SAMPLE_CHUNK_SIZE=10` :64, no `--combo-tag`), `_regenerate_one_layer_task` :226,
  `_run_pass` :232 (two passes, `FIRST_PASS_SAMPLES=10` :67; `--workers 0` =
  `len(os.sched_getaffinity(0))` :263); mode 3 `run_stream` :299, `emit_stream` :278;
  `parse_args` :351 (sentinel test `n_samples != 100` :390). All three modes call
  `tracegen.check_schedule_matches_trace` before `load_schedule` (:150, :212, :315).
- `subset_input_traces.py`: `ROOT` from `__file__` (:41-42), imports
  `util.data_root`; `subset_one(src_dir, dest_dir, n, seed)` :50:
  `np.random.default_rng(seed).choice`, sorted (:61), same indices for every
  layer, rewrites `B` and adds `meta["subset"]` (:83); `main` :97.
- `solve_inst16_subset.py`: `ROOT` from `__file__` (:18-19); `ARCHS` :22,
  `LAYERS` :26 (4 `_T4_all` layers), `main` :34 (arch
  `configs/arch/<arch>_inst16.yaml` :48).
- `scripts/tmp/` (tracked, not in the brief): multinode sweep generator/solver/
  analyzers, `probe_gurobi_concurrency.py`, `run_combo.sh`,
  `run_loas_sweep_combo.sh` (the latter shows how the 0803 inputs were made:
  `--schedule-cache outputs/schedules/multinode_sweep/<combo> --out-dir
  $NEURO_CACHE_DATA/neuro_cache_outputs/weight_traces --combo-tag <combo>`,
  `scripts/tmp/run_loas_sweep_combo.sh:15-21`). All now resolve the repo root
  from `__file__`/`$0` and read data paths through `data_root()`/`env.sh`.
  Not documented further.

### 2.7 `configs/`

Unchanged in phase 2 (`git diff --stat 8fa0916..HEAD -- configs/` is empty).

- `arch/`: `<arch>.yaml` x5 (single node, `instances: 1`, `single_node: true`,
  no NoC entries; num_pes loas 16, ptb 128, ...), `<arch>_multinode.yaml` x5
  (128 nodes, NoC 1 MiB per tensor), `{loas,ptb,spinalflow}_inst16.yaml` (16
  nodes, no NodeLevel `local_buffer`), `snn_arch.yaml` (generic example),
  `multinode_sweep/` 400 files = 5 archs x instances {16,64,256,1024} x node
  {2,4,8,16,32} KB x NoC {512,1024,2048,4096} KB, with NodeLevel and NoC
  entries split 30:1:1 (e.g. node 16 KB -> weight 15360, psum 512, vmem 512).
  All `DRAM_LATENCY: 0.25`.
- `dataflow/<arch>.yaml` x5: `node_dim_capacity` per dim (e.g. loas KH/KW/CIN/T
  `full`, COUT `{spatial: 4}` at `configs/dataflow/loas.yaml:9`).
- `cache/cache_config{,_tiny}.yaml`: old cache configs (32 KB FA, 32 B line,
  `inner_dim cin`); no live reader (their only reader, cachesim, was removed on 2026-10-26).
- `mapspace/mapspace.yaml`: `spatial_dims` = all 7; default for the CLI only.
- `workloads/sample_snn_layer.yaml`: 3x3, CIN 64, COUT 128, 56x56, T 4; CLI default.

### 2.8 `input_trace/`

`input_trace/loas/` (14 MB, 33 tracked files although `.gitignore` excludes
`input_trace/`): `vgg16_T4_n5/` (12 layers `layer_01_features_3` ..
`layer_12_features_40`, Cin 64..512, 32x32 down to 2x2) and `resnet19_T4_n5/`
(19 layers incl. 3 `*_shortcut_0`), each with `meta.json` (T=4, B=5,
dataset cifar10, dtype uint8, `subset.sample_indices` e.g. vgg16
`[2697, 3078, 5110, 6367, 8502]`, seed 0, made by `scripts/subset_input_traces.py`).
Only LoAS-captured traces exist; every arch model reads these same spikes.
The full `_all` captures are expected under
`$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas/` (`src/util.py:18-23`);
that directory does not exist on this disk.

### 2.9 `profiling/` stage code

#### 2.9.1 `profiling/common.py` (57 lines, new in `6835b9c`)

Imported (after `sys.path.insert(0, str(ROOT / "profiling"))`) by 20 driver
files in 9 stage directories: 0823 `run_stage1.py`, `run_armS_stage12.py`,
`run_khkw_sweep.py`, `run_l2_capacity_probe.py`, `run_layout_control.py`,
`input_trace_audit/audit_density.py`; 0831_all_layer_streams `run_compare.py`,
`solve_all_layers.py`; `0831_l2_prefetch/run_sweep.py`; 0831_reuse_distance
`analyze31.py`, `analyze_reuse.py`, `run_assoc31.py`, `run_belady.py`,
`run_reuse_hist.py`, `solve_31.py`; `0902_l1_evictions/run.py`;
`0903_l1_8k/run_sweep.py`; `0907_{assoc,index_policy,linesize}/run_sweep.py`.

- `ROOT` :9 (repo root from `__file__`).
- `BASE` :13-18: the khkw_split 64 B base point (see 1.7).
- `KHKW_KEYS` :22-25: BASE's keys in the order of `run_khkw_sweep.py`'s grid
  points; used where a stage copies that sweep's best point
  (`khkw_64b.json[0]`) so grid files keep their old key order.
- `base_config(keys=None, drop=(), **extra)` :28: BASE restricted to `keys`
  (all when None), minus `drop`, with `extra` overriding and appended. Order
  matters only for the written grid files; wcache reads keys by name (:29-32).
- `WORKLOADS` :38 = `[("V", "vgg16_T4_n5"), ("R", "resnet19_T4_n5")]`.
- `tags()` :42: `(tag, trace_dir, layer)` for every valid layer of both `_n5`
  workloads; imports `archmodels.trace.valid_layer_names` lazily (:44), so
  `ROOT/src` must be on `sys.path` first. Replaces the per-stage `tags()` /
  `combos()` copies; callers unpack the 3-tuple (e.g.
  `profiling/0907_linesize/run_sweep.py:185`).
- `next_cin_for` was removed 2026-10-26: COUT now comes from meta.json
  `layer_params` (`audit_density.py:39` reads it directly).

#### 2.9.2 Sweep drivers

Shared pattern of the 0831-0907 sweep drivers, documented on
`profiling/0907_linesize/run_sweep.py`:
`BIN` :61 (`wcache_sweep` release build), `STREAMS` :62 (0831 streams),
`NOCSIM` :63 (`all_layers_vs_nocsim.csv`), `BASE` :67 (via `base_config`
with `policy="rrip", rrip_bits=5`), grids :87-96, `one(args)` :107 (one
`wcache_sweep` call per mapper, checks row count, labels `_tag _sample _layer _arm`),
`aggregate(rows, avail)` :130 (mean over 5 samples, spread, speedup vs the
reference arm, joins nocsim makespan), `write_csv` :167, `main` :174 (threads,
default 16 workers :175, `git rev-parse --short HEAD`, writes `*_rows.csv`,
`*_by_layer.csv`). Tags come from `common.tags()`.
Diffs: `0903_l1_8k/run_sweep.py` (`one` :38, `geomean` :56,
`aggregate` :61, `write_csv` :117, `main` :124; adds `*_aggregate.csv`);
`0907_assoc/run_sweep.py` (`assocs_for` :63, `arm_tag` :66, `one` :87,
`aggregate` :105, `write_csv` :140, `main` :147); `0907_index_policy/run_sweep.py`
(`POLICIES` :42, `arm_size` :55, `arm_policy` :56, `one` :64, `geomean` :82,
`aggregate` :87, `write_csv` :145, `main` :152); `0831_l2_prefetch/run_sweep.py`
(`one` :45, `main` :63; no aggregation, see `analyze.py`).

#### 2.9.3 Per file (functions with lines; one phrase each where the name is not enough)

- `0728_status_replay/build_artifact.py`: `read_rows` :15, `validate` :35, `main` :58.
- `0803_l1_l2_cache/run_sweep.py` (removed 2026-10-26 with cachesim; described as of `39efd64`): `DEFAULT_TRACE_ROOT` :24 (`data_root()`),
  `discover_units` :60 (requires exactly 124 units, 5 samples each),
  `print_preview` :86, `_rate` :103, `run_unit` :107 (asserts L2 accesses ==
  L1 misses), `merge_results` :176, `main` :219.
  `build_artifact.py`: `TRACE_ROOT` :22 (`data_root()`), `read_rows` :30,
  `read_schedule_rows` :80, `read_trace_example` :110, `aggregate` :141, `main` :164.
- `0820_phaseD_spad_vs_cache/run_sweep.py`: `sweep_binary` :43 (release then
  fixture build), `git_commit` :53, `load_grid` :75 (exactly one of
  `units`/`fixtures`, `axes`/`configs`), `cross` :87 (dict-valued axis values
  move knobs together), `expand_configs` :104, `layout_of` :115 (defaults
  cin 1, cout 16, wb 1), `layout_groups` :122, `layout_tag` :129,
  `expand_traces` :140 (`CONFIRM_*` placeholders make a unit refuse to run),
  `build_tasks` :160, `producer_argv` :176, `emit_fixture_stream` :197 (stubs
  `archmodels.trace` to avoid NumPy), `run_unit` :234 (producer now gets
  `cwd=ROOT`, :252), `merge_results` :280 (header taken from unit files),
  `print_preview` :319, `main` :339.
  `tests/`: `demo_smoke.sh` (row invariants: total >= tick base, stall parts
  sum, prefetch outcomes sum), `duplicate_check.sh` (prefetch-distance
  budget), `replay_check.sh` (dump then replay equals stdin run),
  `test_resume.sh` (atomic per-unit resume), `test_slurm_shape.sh` (greps the
  `.slurm` for Delta settings).
- `0823_stagewise_verify/stage1_mip_solver/run_stage1.py`: `TRACE_ROOT` :44
  (`data_root()`), `LAYERS` :49, `sha` :67, `split_30_1_1` :71, `write_arch` :77,
  `kb` :87, `stage_inputs` :91 (MANIFEST `workloads` entries carry `cout`), `strategy_digest` :150,
  `run_num_pes` :163, `run_all_modes` :192, `run_noc_sizes` :227, `main` :266.
- `.../stage2_weight_trace/run_stage2.py`: `COMBO_TAG` :35, `COMBOS` :44,
  `sha` :53, `stage_inputs` :57 (copies schedules and rewrites `trace_dir`
  `_all` -> `_n5`), `run_generator` :121, `input_trace_stats` :153,
  `weight_trace_stats` :179, `main` :227 (pass A files with `--combo-tag
  noc2MiB_node32kb`, pass B `--stream --dump-trace`).
  `verify_reconstruction.py`: `pixel_row_counts` :43, `generated` :67,
  `main` :89 (NumPy re-derivation of LoAS row counts; docstring cite
  `LoASGen.h:64-108` now correct).
  `wcts_excerpt.py`: `main(path, max_tiles=2, max_cores=2, max_bursts=6)` :13;
  now a v2-only reader: rejects `format_version != 2` (:19-22) and
  `burst_dim != 3` (:23-24); field 3 is labelled `cout` (:10).
- `.../stage3_nocsim/run_stage3.py`: `COMBO_TAG` :32, `COMBOS` :39,
  `N_NODES = 16` :46, `sha` :49, `layer_yaml` :53, `run_one` :63
  (`compute_per_node = count_cycles // 16`, :93), `main` :99 (writes
  `outputs/tc/<tag>_s<5>.csv`, :101, :132).
  `run_armS_stage12.py`: `COMBO_TAG` :41, `COMBOS` :44, `TRACE_OUT` :53
  (`outputs/weight_traces_single_node`), `sha` :56, `stage1` :60, `stage2` :90,
  `main` :129.
- `.../stage4_wcache/`: `oracle_gate.py` `main` :34 (`--oracle-only --arm
  spad_oracle`, compares with stage 3 `compute_per_node`); `run_w5.py` `main` :38
  (C3 fully-associative pairs must match across layouts); `run_khkw_sweep.py`
  `BASE` :37 (`base_config(KHKW_KEYS, drop=...)`), `grid_for` :42, `one` :55,
  `main` :76; `run_l2_capacity_probe.py` `one` :36, `main` :54;
  `run_layout_control.py` `one` :34, `main` :50; `analyze_khkw_sweep.py`
  `main` :26; `build_artifact.py` (module-level script, `D` now from
  `__file__`, :5) `num` :27, `bar` :30, `table` :37, `_pick` :235, `_cliff` :264,
  `_cap_gain` :272, `bf` :424. `inputs/gen_streams.sh`: 20 `--stream
  --dump-trace` runs with `${PYTHON:-python3}` (:14), then `cmp` against
  stage 2 dumps.
- `.../input_trace_audit/audit_density.py`: module-level script, `R` :13
  (`data_root()`), `p` :18.
- `0831_all_layer_streams/solve_all_layers.py`: `TRACE_ROOT` :52, `load_meta` :69,
  `solve_one` :73, `write_n5_copy` :79, `run_check` :94, `run_all` :112.
  `gen_streams.py`: `PYTHON = sys.executable` :41, `CHECK_TAGS` :53, `tasks` :56,
  `generate` :71, `run_check` :87, `main` :103.
  `gen_weight_traces.py`: `PYTHON = sys.executable` :36, `COMBO_TAG` :39,
  `sample_path` :52, `tasks` :56, `generate` :65, `run_check` :81, `main` :103.
  `run_compare.py`: `TRACES` :53, `N_NODES = 16` :56, `BEST` :62, `layer_yaml` :65,
  `run_wcache_one` :78, `phase_wcache` :94, `run_nocsim_one` :128,
  `phase_nocsim` :160, `phase_join` :186, `main` :251.
- `0831_l2_prefetch/analyze.py`: `mean` :12, `main` :14 (gate: `off` arm must
  equal 0831 `wcache_rows.csv`). `build_artifact.py`: `cell` :73, `bar` :85, `table` :91.
- `0831_reuse_distance/`: `solve_31.py` `main` :18; `run_assoc31.py` `layers` :24,
  `engine` :31, `main` :43; `analyze31.py` `l2_seq` :19, `stack_hist` :28, `main` :40;
  `run_reuse_hist.py` `check_best_matches_friday` :51, `preview` :61, `one` :86,
  `main` :131; `run_belady.py` `ARMS` :40, `check_best` :50, `engine` :56,
  `l2_digest` :74, `one` :89 (iterates oracle until the L2 log stops changing),
  `stage3` :115, `preview` :122, `main` :143; `analyze_reuse.py` `engine` :47,
  `load` :62, `merged` :69, `curve` :77, `pct` :84, `main` :88; `plot_reuse.py`
  `load` :39, `sx` :48, `sy` :53, `panel` :61, `main` :130; `build_profile31.py`
  `hit_rows` :51, `rd_rows` :65, `rc_rows` :79; `build_assoc31_artifact.py`
  `tbl` :40, `net_row` :53, `d` :295, `c` :296 (module-level script). C++:
  `reuse_tool.cpp` `main` :58 (`reuse_tool <access.log> <out.csv> [--dump N]`,
  magic `WCALOG01` :34, 8-byte records, one stack per L1 core + one for L2);
  `reuse_distance.h` `StackDistance` :47 (Fenwick tree, exact LRU stack
  distance, cold = -1), `ReuseHistogram` :143; `test_reuse_distance.cpp`
  `main` :237 (naive oracle vs tree). No build file in the directory.
- `0902_l1_evictions/run.py`: `CONFIG` :41, `_cv` :44, `summarise` :55, `one` :170, `main` :195.
- `0903_hot_cin/run.py`: `read_stream` :34 (own WCTS decoder, 28-byte bursts;
  v2 and COUT only, :40-45), `gini` :75, `skew_stats` :83, `spearman` :103,
  `analyse` :110, `fmt` :144, `demo` :163, `main(argv)` :177, `tile_matrix` :218,
  `topk_capture` :224, `analyse_tiles` :235, `fmt_tiles` :307, `reference_order` :332,
  `line_ids` :339, `reuse_gaps` :347, `window_union` :358, `analyse_reuse` :371,
  `fmt_reuse` :404, `analyse_reuse_times` :426, `fmt_reuse_times` :478,
  `analyse_topn` :502, `fmt_topn` :548, `analyse_hot` :575, `fmt_hot` :625.
  `L2_LINES=8192`, `L1_LINES=256` :27-28.
- `0907_assoc/make_page.py`: `load` :32, `block` :57, `dots` :67, `build` :93,
  `main` :263; imports `CSS, fmt` from `0907_index_policy/make_pages.py` (:19).
- `0907_index_policy/make_pages.py`: `load` :25, `accumulate` :32, `page_data` :72,
  `fmt` :231, `dot_chart` :235, `bar_chart` :266, `build` :286, `main` :444.
- `0907_linesize/make_page.py`: `load` :26, `dots` :50, `build` :77, `main` :253.

#### 2.9.4 `profiling/0823_stagewise_verify` outputs that left git

Described from `git status --ignored`, `git ls-files`, and `du` only (the
stage's `UNTRACKED_OUTPUTS.md`, added in `9012d22`, was not read).

- `stage3_nocsim/outputs/tc/`: 20 transaction CSVs `{V8,V9,R9,R16}_s0000{0..4}.csv`,
  24 MB on disk; produced by `run_stage3.py` (:101, :132). Ignored (`!!`).
- `stage3_nocsim/outputs/weight_traces_single_node/`: 20 `sample_*.json.gz`
  under `loas/single_node/{vgg16,resnet19}_T4_n5/<layer>/`, 273 MB on disk;
  produced by `run_armS_stage12.py` (`TRACE_OUT` :53). Ignored (`!!`).
- Still tracked in `stage3_nocsim/outputs/`: `logs/*.log`, `stage3_results.json`,
  `RESULTS.md`.
- `input_trace_audit/__pycache__/` is untracked and not ignored (the only
  `??` entry under the stage); the other stage `__pycache__/` dirs are ignored.

### 2.10 `tests/`

- `test_combine_cycles_table.py`: nocsim `combine()` charges each step the
  trace's `mac_cycles` (multi-node and single-node); skips without 0823 stage-2 traces.
- `test_emission_order.py`: arch binary output is sample-outer, tile-inner
  (reads a file from argv or `EMISSION_TRACE`).
- `test_eventsim_deps.py`: eventsim delays successors by dependency finish time
  (needs `src/nocsim/eventsim/eventsim`).
- `test_flits_per_packet.py` (new in `6835b9c`): the built eventsim and
  `nocsim.core.transaction.FLITS_PER_PACKET` agree; skips without the binary
  (see `docs/atlas/nocsim.md`).
- `test_sim_weight_trace.py`: `nocsim.sim --weight-trace` CLI path and its error checks.
- `test_step_cycles.py`: `tracegen.load_step_cycles` and `StepCycles.check_against`.
- `test_stream_dump.py`: `emit_stream` dump is byte-identical / valid when truncated (fixture only).
- `test_stream_writer.py` (14 tests): WCTS writer byte layout (version 2,
  :49) and rejection rules, round trip of a `src/wcache/examples` fixture
  (`test_round_trip_a_real_fixture` :219), a Python reader `decode_stream` :156, and five new v2 tests:
  `test_each_burst_axis_round_trips` (one burst per axis 0..3 round-trips the
  full anchor), `test_write_tile_frame_refuses_an_empty_run_on_the_burst_axis`,
  `test_stream_weight_trace_refuses_a_non_cout_burst_dim`,
  `test_write_stream_header_refuses_burst_dim_outside_0_to_3`,
  `test_write_tile_frame_requires_burst_dim`.
- `test_weight_resend.py`: weight tile resent only on reload (`StepInfo`), uses
  0823 tracked schedules/layers.
- `stdout_roundtrip.sh`: an arch binary writes the same bytes to `-` and to a file.
- `test_stream_flag.sh`: end-to-end `--stream` via `conda run -n "$CONDA_ENV"`
  (from `scripts/env.sh`, :10, :13) on `vgg16_T4_all` (absent from the default
  trace root).
- The run-line docstrings now say `conda run -n ${CONDA_ENV:-cosa_snn}` (e.g.
  `tests/test_step_cycles.py:19`).

### 2.11 `dump/` and `debug/` (only where they touch the pipeline)

- `dump/python_reference/`: the Python reference models
  (`archmodels/<arch>/{reconstruct,cycles,address,model}.py`, `cachesim/`,
  `tracegen_reconstruct.py`). Present at both commits; at HEAD the src
  docstrings point here. `tracegen_reconstruct.py:25,68` calls
  `tracegen.tick_entries_from_flat`.
- `dump/scripts/`: five scripts still put cwd-relative `src` on `sys.path`
  (3.4); four now read `data_root()` (`dump/scripts/burst_dispatcher.py:58`,
  `generate_weight_traces_tile_parallel.py:35`,
  `locality_analysis/kernel_window_locality.py:40`,
  `locality_analysis/kernel_window_locality_cross.py:39`).
- `debug/`: numbered checks; they resolve `REPO_ROOT` from `__file__` (e.g.
  `debug/03_verify_hit_rate.py:31`); `debug/09_verify_tick_entries_from_flat.py:33`
  calls `tick_entries_from_flat`.

---------------------------------------------------------------------------

## 3. Findings for cleanup (code-evidenced, at `39efd64`)

Resolved by phase 2 and dropped from this list: `build_Z` (removed); the
base wcache config retyped in 15+ drivers (now `profiling/common.py:13`);
the inline "next layer's CIN" in the profiling stages (then
`common.next_cin_for`; since 2026-10-26 COUT comes from meta.json `layer_params`); per-stage `tags()`/`combos()` copies in seven drivers;
every `/u/yyu9`, `/work/hdd/bebv`, `/projects/bebv` path in `.py/.sh`; cwd
dependence of `scripts/*.py` and the 0820 producer; the conda env name
disagreement; wrong docstrings for trace dtype, `BW_VMEM`, `S[1]`,
`constraints_spatial.py`, 0907_assoc point count, 0831_l2_prefetch arm count,
run_belady arm count, 0907_index_policy arm count; stale references to
`sweep_archmodel_layers.py`, `generate_weight_traces_canonical100.py`,
`reconstruct_samples_for_schedule`, `archmodels.gustavsnn.model`,
`configs/workloads/generated/`, `sweep_weights.py`/`run_full_sweep.py`,
`<arch>/{reconstruct,cycles,address}.py`, `wcache/stream_format.h`,
`tests/sweep_cli.sh` in the 0820 driver, and the old `LoASGen.h` line range in
`verify_reconstruction.py`; the 311 MB of
tracked 0823 stage-3 outputs.

### 3.1 Dead or unused code

- `tracegen.tick_entries_from_flat` `src/tracegen.py:222`: no caller in the
  pipeline; kept because `debug/09_verify_tick_entries_from_flat.py:33` and
  `dump/python_reference/tracegen_reconstruct.py:68` call it.
- `util.REGIONS`, `util.KINDS` `src/util.py:11-12`: unused.
- Mapspace is parsed and initialized but never passed to a constraint or
  objective; this is now stated in a comment (`src/mip_solver/solve.py:77-83`)
  rather than removed. Only its path is echoed (:183); `solve_best_schedule`
  omits it (:303). `configs/mapspace/mapspace.yaml` therefore changes nothing.
- `ArchComputeModel` Protocol `src/archmodels/__init__.py:68` and its
  `format_input_batch`/`weight_ticks` contract describe the Python models in
  `dump/python_reference/`; `DenseStaticComputeModel` (`src/archmodels/dense.py:32`)
  does not implement `format_input_batch`. nocsim still types against it
  (`src/nocsim/combine.py:74`).
- `lif_cycles` is always `None` in generated traces (`src/tracegen.py:282`).
- `configs/cache/*.yaml`: no code reads them (their only reader, cachesim,
  was removed on 2026-10-26).
- `mip_solver.analysis` is used only by `scripts/tmp/`.
- `stream_weight_trace` has a `burst_dim` parameter (`src/tracegen.py:643`)
  whose only legal value is its default 3 (:660).

### 3.2 Duplicated logic

- No longer duplicated: COUT, kernel and stride come only from meta.json
  `layer_params`, read by `layer_params` (`src/archmodels/trace.py:84`), which
  `valid_layer_names` (:126) and `build_workload_from_trace` (:132, COUT at :159)
  use. `profiling/common.py:54` and `scripts/solve_schedules.py:66` call
  `valid_layer_names`; `scripts/solve_inst16_subset.py` reaches
  `build_workload_from_trace` through `tracegen.solve_and_cache_schedule`
  (`src/tracegen.py:101`).
- Five stage-1 solve loops with the same structure: `scripts/solve_schedules.py:75`,
  `scripts/solve_inst16_subset.py:34`, `profiling/0831_reuse_distance/solve_31.py:18`,
  `profiling/0831_all_layer_streams/solve_all_layers.py:112`,
  `profiling/0823_stagewise_verify/stage1_mip_solver/run_stage1.py:166`.
- Mode score defined twice with the same weights: `src/mip_solver/solve.py:271-278`
  and `src/mip_solver/enumerator.py:104` (defaults :34-36); weights also in
  `src/mip_solver/cli.py:94-102` and `src/mip_solver/objectives/combined.py:25-27`.
- Tag derivation not moved to `common.tags()`: `profiling/0831_all_layer_streams/gen_streams.py:56`,
  `gen_weight_traces.py:56`, `profiling/0831_reuse_distance/run_assoc31.py:24`
  (`layers()`). `write_csv`, `geomean`, `aggregate`, `sha` (15 definitions)
  and the `git rev-parse --short HEAD` call (11 copies) are still per stage.
- nocsim stdout parsing duplicated: `profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:63`
  and `profiling/0831_all_layer_streams/run_compare.py:128`, with `N_NODES = 16`
  in both (:46, :56).
- Five arch `main.cpp` and five `native_bridge.py` differ only in names and the
  tile record.
- Two Python WCTS decoders besides the C++ one, each with the same v2 gate
  pasted in: `profiling/0823_stagewise_verify/stage2_weight_trace/wcts_excerpt.py:13`
  (gate :19-24) and `profiling/0903_hot_cin/run.py:34` (gate :40-45); a third
  lives in `tests/test_stream_writer.py:156`.

### 3.3 Hardcoded absolute paths and hosts

- Delta specifics in code: `srun -A bebv-delta-gpu -p gpuA100x4-interactive`
  (`profiling/0823_stagewise_verify/stage4_wcache/build_artifact.py:732`),
  `-p gpuA40x4` (`profiling/0831_l2_prefetch/build_artifact.py:309`), and the
  `.slurm` shape test `profiling/0820_phaseD_spad_vs_cache/tests/test_slurm_shape.sh:5-10`
  (account `bebv-delta-gpu`, partition `gpuA40x4`, 16 CPUs, 128 GB, 2 h).
- Gurobi token-server license path in a docstring:
  `/sw/external/containers_other/gurobi/gurobi.lic`
  (`profiling/0831_all_layer_streams/solve_all_layers.py:21`).
- `source ~/miniconda3/etc/profile.d/conda.sh` assumes a home-directory conda:
  `scripts/tmp/run_combo.sh:14`, `scripts/tmp/run_loas_sweep_combo.sh:12`.
- Schedule JSONs store the config paths they were solved with
  (`src/mip_solver/solve.py:180-184`); with `ROOT`-based callers these are now
  absolute paths of the machine that solved.

### 3.4 Server and environment assumptions

- Still cwd-relative: `python -m mip_solver` defaults (`src/mip_solver/cli.py:20-24`);
  five `dump/scripts` files with `sys.path.insert(0, "src")`
  (`dump/scripts/generate_weight_traces_tile_parallel.py:29`,
  `dump/scripts/sweep_archmodel_layers.py:22`,
  `dump/scripts/visualize_dram_permutation.py:21`,
  `dump/scripts/locality_analysis/kernel_window_locality.py:35`,
  `dump/scripts/locality_analysis/kernel_window_locality_cross.py:34`), which
  also use relative `outputs/...` (e.g. `kernel_window_locality.py:41`); their
  new `from util import data_root` works only from the repo root.
- `data_root()` falls back to `<repo>/data` without logging it
  (`src/util.py:24-25`); a run with `NEURO_CACHE_DATA` unset fails later with
  a missing-file error under `data/neuro_cache_trace/`, which does not exist here.
- Conda: one variable `CONDA_ENV` (default `cosa_snn`, `scripts/env.sh:4`).
  0820 tests note "this machine has no conda" and use `$PYTHON`
  (`profiling/0820_phaseD_spad_vs_cache/tests/demo_smoke.sh:6`).
  `profiling/0831_all_layer_streams/gen_streams.py:13-15` says `conda run`
  corrupts binary stdout, but `tests/test_stream_flag.sh:13-17` still
  redirects `conda run` stdout.
- Gurobi: required for every solve; only `OutputFlag`/`TimeLimit`/`MIPGap`
  are set (`src/mip_solver/solve.py:85-90`), never `Threads`/`Seed`, so
  parallel solving oversubscribes cores; :172-178 documents a long-lived-worker
  bug worked around by `dispose`.
- Core counts: default 16 workers in `0831_l2_prefetch/run_sweep.py:64`,
  `0903_l1_8k/run_sweep.py:125`, `0907_*` (e.g. `0907_linesize/run_sweep.py:175`),
  8 in `0902_l1_evictions/run.py:196`; `scripts/generate_weight_traces.py:257`
  uses Linux-only `os.sched_getaffinity`.
- 16 nodes hardcoded: `N_NODES = 16` in `run_stage3.py:46` and
  `run_compare.py:56` (used to divide `count_cycles`).

### 3.5 Scattered config literals

(Audit of "one canonical source": values defined in more than one place.)

- `NEURO_CACHE_DATA` default defined twice: `src/util.py:24-25` and
  `scripts/env.sh:3` (the comment at `scripts/env.sh:2` asks to keep them the same).
- `CONDA_ENV` default `cosa_snn` in `scripts/env.sh:4` and retyped as
  `${CONDA_ENV:-cosa_snn}` in about 25 usage docstrings (e.g.
  `scripts/subset_input_traces.py:27`).
- The data sub-path `neuro_cache_trace/input_trace/loas` is retyped after
  every `data_root()` call (`scripts/subset_input_traces.py:45`,
  `run_stage1.py:46`, `audit_density.py:13`, `solve_all_layers.py:52`,
  `scripts/tmp/probe_gurobi_concurrency.py:20`,
  `scripts/tmp/solve_multinode_schedules.py:23`,
  `scripts/tmp/sweep_multinode_arch_sweep.py:79`); `data_root()` returns only
  the root. Minimal collapse: a `trace_root()` helper beside it in `src/util.py`.
- Arch-to-YAML map hardcoded (`scripts/solve_schedules.py:34-40`), inst16 path
  built by string (`scripts/solve_inst16_subset.py:48`,
  `profiling/0831_reuse_distance/solve_31.py:19`).
- Tag list `["V8", "V9", "R9", "R16"]` retyped in 13 files (e.g.
  `profiling/0823_stagewise_verify/stage4_wcache/run_khkw_sweep.py:31`,
  `profiling/0831_reuse_distance/run_belady.py:33`,
  `profiling/0831_all_layer_streams/gen_streams.py:53`); layer lists in
  `scripts/solve_inst16_subset.py:26`, `run_stage1.py:51`, `run_stage2.py:44`,
  `run_stage3.py:39`, `run_armS_stage12.py:44`,
  `stage4_wcache/inputs/gen_streams.sh:20-24`, and the 0820 grids.
  `common.WORKLOADS` (:38) covers only the 31-layer form.
- Combo tag `noc2MiB_node32kb` retyped in `run_stage2.py:35`,
  `run_stage3.py:32`, `0831_all_layer_streams/gen_weight_traces.py:39`,
  `run_compare.py:53`.
- `wcache_sweep`/`wcache_run` release-build paths are retyped per driver
  (e.g. `profiling/0907_linesize/run_sweep.py:61`).
- Scoring weights 0.1/1.0/10.0 in four files (3.2).

### 3.6 Inconsistent conventions and wrong comments

- Dataflow comments vs values: `configs/dataflow/prosperity.yaml:2` "128 output
  columns" but `COUT: {spatial: 8}` (:7); `configs/dataflow/spinalflow.yaml:3`
  "128-PE array" with `{spatial: 8}` (:8); `src/archmodels/loas/__init__.py:12`
  "COUT node-level spatial capacity 16" while `configs/dataflow/loas.yaml:9`
  has `{spatial: 4}` (left open on purpose by `39efd64`).
- Default trace-dir order differs: `scripts/solve_schedules.py:33` vs
  `scripts/generate_weight_traces.py:58`.
- The `0907_index_policy` stage name says "index" but it sweeps replacement
  policy (`profiling/0907_index_policy/run_sweep.py:42`).
- `--n-samples` conflict check uses the default as sentinel
  (`scripts/generate_weight_traces.py:378`), so `--n-samples 100 --sample-count 5` passes.
- Mode 2 (`--all-layers`) ignores `--combo-tag` (`_regenerate_layer`
  `scripts/generate_weight_traces.py:195-198`).
- Drivers still pass `--header` (e.g. `profiling/0907_linesize/run_sweep.py:115`),
  which is now the `wcache_run` default (`src/wcache/native/apps/wcache_run.cpp:46`);
  harmless, but no longer meaningful.

### 3.7 Tracked outputs and build products

- No `__pycache__`/`.pyc` tracked; native binaries (`<arch>gen`, `eventsim`,
  `wcache_run/sweep`) are untracked builds present on this disk.
- `profiling/0823_stagewise_verify` now tracks 196 files, about 1.9 MB. The 40
  bulk stage-3 outputs (20 `tc/*.csv`, 20 single-node `sample_*.json.gz`) were
  untracked in `9012d22` without a history rewrite, so the 311 MB remain in
  git history; on this disk they are ignored copies (2.9.4).
  `profiling/0823_stagewise_verify/input_trace_audit/__pycache__/` is untracked
  but not ignored.
- Also tracked: `dump/` (28 MB), `survey-output/` (150 files), a PDF at repo
  root, `input_trace/loas` (14 MB, though `.gitignore` lists `input_trace/`),
  0728 per-layer CSVs, 0820 result CSVs, HTML artifacts.
- `profiling/0831_all_layer_streams/streams/` is 16 GB untracked (ignored) and
  holds WCTS v1 files that no HEAD reader accepts.

### 3.8 Stale references (to removed or renamed things)

- `profiling/0823_stagewise_verify/stage2_weight_trace/wcts_excerpt.py:4-5`
  cites `write_stream_header:524, write_tile_frame:566, write_stream_trailer:603`;
  at HEAD they are `src/tracegen.py:521`, `:563`, `:600` (rewritten in
  `725474f`, still off by 3).
- `assemble_layer_traces` docstring (`src/tracegen.py:259-262`) says archs
  other than LoAS reach the tick-grouped shape via `tick_entries_from_flat`;
  all five binaries write tick-grouped output themselves (`write_tick_grouped`,
  e.g. `src/archmodels/ptb/main.cpp:140`).
- `profiling/0820_phaseD_spad_vs_cache/tests/test_resume.sh:6` and
  `demo_smoke.sh:9` cite `tests/sweep_cli.sh`; the file is
  `src/wcache/native/tests/sweep_cli.sh`.
- `src/archmodels/trace.py:36` example `input_trace/loas/vgg16_T4_B1` does not exist.
- `profiling/0903_l1_8k/run_sweep.py:4` refers to stage `0903_l1_pf_fix`, which
  is not in `profiling/`.
- Missing producers: `profiling/0823_stagewise_verify/stage4_wcache/outputs/w5{b..g}_*.csv`
  have no generating script in the stage; the 0728 CSVs have no in-stage producer.

---------------------------------------------------------------------------

## 4. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

What a fresh machine needs:

- Python >= 3.9 (`tuple[...]` annotation without `from __future__` in
  `src/parsers/arch.py:283`); `__pycache__` files here are cpython-312.
  Packages from imports: `numpy`, `pyyaml`, `gurobipy` (comment mentions
  13.0.2 in `profiling/0831_all_layer_streams/solve_all_layers.py:59`),
  `matplotlib` (only `scripts/tmp/analyze_multinode_schedules.py`),
  `pytest` (`tests/test_flits_per_packet.py`). `requirements.txt` exists but
  was not read (extension rule).
- A Gurobi license (`GRB_LICENSE_FILE`; Delta token server path in
  `solve_all_layers.py:21`) for any solve. Not needed to reuse cached schedules.
- g++ with C++17 and `make` for: 5 arch generators (`src/archmodels/<arch>/Makefile`),
  `src/nocsim/eventsim`, `src/wcache/native`
  (`MODE=release lib apps` for `build/release/`, which every 0823+ driver hardcodes).
  `reuse_tool` has no build file.
- `NEURO_CACHE_DATA` pointing at a directory with
  `neuro_cache_trace/input_trace/loas/<capture>/` (and, for 0803,
  `neuro_cache_outputs/weight_traces/`), or that layout under `<repo>/data`
  (`src/util.py:18-25`); `CONDA_ENV` if the env is not `cosa_snn`.
  `PYTHONPATH=src` only for `python -m nocsim.sim` / `python -m mip_solver`
  run by hand.

Inputs missing from the repo:

- Full captures `vgg16_T4_all`, `resnet19_T4_all` (10,000 samples, 25.8 GB per
  the `scripts/subset_input_traces.py` docstring) referenced by
  `scripts/solve_inst16_subset.py:26`, all 0820 grids, `run_stage1.py:51`,
  0803 paths, `solve_all_layers.py:52`, `audit_density.py:13`,
  `tests/test_stream_flag.sh:14`. Only `_n5` (5 samples) is stored.
- Default `--n-samples 100` draws indices from `range(10000)`
  (`src/tracegen.py:691`), which is out of range for the stored B=5 arrays; use
  `--sample-start/--sample-count` with indices 0-4. Saved `sample_idx` is then
  the array index, not the CIFAR-10 index in `meta.json["subset"]`.
- No `outputs/` tree: no cached schedules for `outputs/schedules/{loas,..}`,
  `inst16`, `multinode`, `multinode_sweep/<combo>`, nor
  `outputs/schedules/multinode_sweep/classification.csv` (0803 build).
  Tracked schedules exist only for 4 loas layers under 0823 (16-core and single-node).
- WCTS streams: every stored stream predates v2 and must be regenerated
  (top note). `profiling/0831_all_layer_streams/streams/` (155 files, v1) feeds
  `0831_l2_prefetch`, `0902_l1_evictions`, `0903_l1_8k`, `0907_*`;
  `profiling/0823_stagewise_verify/stage4_wcache/inputs/streams` (absent here)
  feeds stage 4, `0831_reuse_distance` and `0903_hot_cin`, and is rebuilt by
  `stage4_wcache/inputs/gen_streams.sh`, whose final `cmp` also needs the
  absent stage-2 dumps.
- Untracked derived data later stages read: `profiling/0831_all_layer_streams/{schedules,streams,weight_traces,outputs}`,
  `.../stage2_weight_trace/outputs/weight_traces` and `inputs/input_trace` (absent;
  tests `test_step_cycles.py`, `test_combine_cycles_table.py` skip without them),
  and the 0823 stage-3 `outputs/tc` and `outputs/weight_traces_single_node`
  (untracked since `9012d22`; present on this disk only). Regenerating `tc/`
  with `run_stage3.py` needs the stage-2 weight traces first; the single-node
  traces come from `run_armS_stage12.py` (Gurobi for its stage 1).
- Only LoAS-captured spike traces exist; PTB/SpinalFlow/Prosperity/GustavSNN
  models replay the same spikes. The example workload dir `vgg16_T4_B1`
  (`src/archmodels/trace.py:36`) is absent.

Hardcoded paths that remain: listed in 3.3 (Delta `srun`/Slurm settings, a
license path in a docstring, `~/miniconda3`). Data paths now go through
`NEURO_CACHE_DATA`.

---------------------------------------------------------------------------

## 5. Open questions the code alone cannot answer

1. Which code produced the 0728 CSVs and the 0823 `w5b`..`w5g` CSVs?
2. Resolved 2026-10-26: shortcut layers are 1x1 stride 2, and each stage's
   `layerS_0_conv1` is stride 2 (Hin halves before `conv2`); "next layer's CIN" gave
   `layer_02`, `layer_09`, `layer_16` half their COUT. meta.json `layer_params` now
   holds the true cout/kernel/stride, `build_workload_from_trace` reads COUT from it
   (`src/archmodels/trace.py:154`), and `valid_layer_names` leaves out the 6 layers
   the 3x3 stride-1 replay cannot model (`src/archmodels/trace.py:112-114`).
3. What do `run_sweep.slurm` (0820; the 0803 one was removed 2026-10-26), `requirements.txt` and
   `profiling/0823_stagewise_verify/UNTRACKED_OUTPUTS.md` contain (not read)?
4. How is `profiling/0831_reuse_distance/reuse_tool` built?
5. Is the mapspace YAML meant to constrain the MIP, or should it be removed
   now that `solve.py:77-83` calls it a no-op?
6. Are Gurobi solutions deterministic across machines/versions without `Seed`/`Threads`
   (the `--check` in `solve_all_layers.py` tests only 4 layers)?
7. Does `tests/test_stream_flag.sh` suffer the `conda run` stdout corruption
   that `gen_streams.py` describes?
8. Should saved traces carry the CIFAR-10 index from `meta["subset"]` instead of the 0-4 array index?
9. Is `configs/arch/ptb.yaml` (marked "RECONSTRUCTED 2026-07-20") equal to the
   one that produced any cached PTB schedule?
10. Which of the 13 stages are still meant to be reproduced, versus kept as history?
11. Should the 155 stored v1 streams be regenerated (hours of generator time)
    or converted in place (for COUT streams only the version field differs,
    per the `725474f` message)?
12. Is a non-COUT burst axis meant to be produced from layer traces some day?
    The writer accepts `burst_dim` 0..3 (`src/tracegen.py:530`), but
    `stream_weight_trace` refuses anything but 3 (:660).
