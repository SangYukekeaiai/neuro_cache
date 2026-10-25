# Code atlas: the pipeline (input trace -> schedule -> weight trace -> wcache / nocsim -> results)

Repo `neuro_cache-wcache`, branch `wcache-rebuild-phase-a`, commit `8fa0916`.
Built only from code (`.py .cpp .h .sh Makefile .yaml .json`) and directory
listings. No `.md/.txt/.slurm`, notes, logs, or result files were opened, so
anything a README states and the code does not is absent here. Paths are
relative to the repo root. `file:N` means line N of that file at this commit.

Scope: `src/tracegen.py`, `src/util.py`, `src/parsers/`, `src/archmodels/`,
`src/mip_solver/`, `scripts/*.py`, `tests/`, `configs/`, `input_trace/`,
`profiling/` (13 stages). `src/wcache`, `src/nocsim`, `src/cachesim` internals
are covered elsewhere (see `docs/atlas/nocsim.md`); here only how the pipeline
calls them.

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
either to the cache simulator `wcache` (as a binary WCTS stream) or to the NoC
simulator `nocsim` (as a gzip JSON file). Each `profiling/<date>_<topic>/`
directory is one experiment: a driver that runs (c)+(d) over a grid and joins
the CSV rows into tables and HTML pages.

### 1.2 Entry points

| Entry point | What it does | Flags (default) |
|---|---|---|
| `scripts/solve_schedules.py` `main` :75 | Stage 1: solve every valid layer x arch once, write schedule JSONs + `summary.csv` | `--trace-root` (`input_trace/loas`), `--trace-dirs` (`vgg16_T4_n5 resnet19_T4_n5`), `--archs` (all 5), `--cache-dir` (`outputs/schedules`), `--force` |
| `scripts/solve_inst16_subset.py` `main` :34 | Stage 1 for the 16-core study: 3 archs x 4 fixed layers against `configs/arch/<arch>_inst16.yaml` | `--trace-root` (required), `--cache-dir` (`outputs/schedules/inst16`), `--force` |
| `scripts/generate_weight_traces.py` `main` :404 | Stage 2: load a cached schedule, reconstruct samples through the native bridge; three modes | `--arch` (required; one of 5), `--trace-dir`, `--layer`, `--trace-dirs` (`resnet19_T4_n5 vgg16_T4_n5`, only `--all-layers`), `--trace-root` (`input_trace/loas`), `--schedule-cache` (`outputs/schedules`), `--out-dir` (`outputs/weight_traces`), `--combo-tag` (`""`), `--sample-start` (0), `--sample-count` (none), `--n-samples` (100), `--seed` (0), `--workers` (1), `--force`, `--all-layers`, `--stream`, `--dump-trace PATH`, `--dump-trace-tiles N` |
| `scripts/subset_input_traces.py` `main` :98 | Cut an N-sample subset out of the full 10,000-sample captures | `--src` (a `/u/yyu9/.snapshot/...` path), `--dest` (`input_trace/loas`), `--captures` (`vgg16_T4_all resnet19_T4_all`), `--n` (5), `--seed` (0) |
| `python -m mip_solver` (`src/mip_solver/__main__.py` -> `cli.main` :27) | Stand-alone solver CLI, `solve` / `enumerate` subcommands | `--layer` (`configs/workloads/sample_snn_layer.yaml`), `--arch` (`configs/arch/spinalflow.yaml`), `--dataflow` (`configs/dataflow/spinalflow.yaml`), `--mapspace` (`configs/mapspace/mapspace.yaml`), `--out` (`outputs/schedule.json` / `outputs/enumeration.json`), `--time-limit`, `--mip-gap`, `--solver-log`, enumerate only: `--w-u 0.1 --w-tr 1.0 --w-dl 10.0` |
| `profiling/*/run_sweep.py`, `run.py`, `run_*.py` | One experiment each; see 1.6 | mostly positional `[workers]` |
| Native: `src/archmodels/<arch>/<arch>gen` | `<bin> <trace.bin> <task.bin> <out.bin or ->` | built by each arch's `Makefile` |
| Downstream (not in scope): `src/wcache/native/build/{release,fixture}/wcache_run`, `wcache_sweep`; `python -m nocsim.sim`; `src/cachesim/cache_sweep_hierarchical` | invoked by profiling drivers | see 1.4 |

### 1.3 End-to-end data flow

```
input_trace/loas/<wl>/meta.json + layer_NN_*.npy  (uint8 [T,B,Cin,Hin,Win])
   | archmodels.trace.build_workload_from_trace  (KH=KW=3, PAD=1, COUT=next layer's CIN)
   v
{"problem": {KH,KW,CIN,COUT,HO,WO,T,shape}}  -> temp YAML -> parsers.SNNProb
   | mip_solver.solve.solve_best_schedule  (13 TrafficModes, Gurobi, keep lowest score)   [Gurobi needed]
   v
ScheduleArtifact JSON  <cache>/<arch>/<trace_dir>/<layer>.json
   | tracegen.load_schedule -> nocsim.schedule.decode.schedule_from_strategy -> iter_node_tiles
   v
list[NodeTileSpec]  (dram_i, noc_i, core_id, node_bound{dim}, tile_offset{dim})
   | archmodels/<arch>/native_bridge: task.bin + trace.bin -> <arch>gen -> out.bin
   | tracegen.assemble_layer_traces (group by (dram_i,noc_i), merge cores per tick, mac=max over cores)
   v
LayerWeightTrace (one per sample)
   |-- save_weight_trace -> sample_NNNNN.json.gz ----> python -m nocsim.sim --weight-trace ... --simulate
   |                                            \---> src/cachesim (0803 only)
   '-- stream_weight_trace -> WCTS v1 bytes (stdout or --dump-trace file) ----> wcache_run / wcache_sweep
                                                                              |
                                               one CSV row per config  <------'
   profiling driver: per-unit CSV -> merged CSV -> *_by_layer.csv -> make_page*.py / build_artifact.py -> HTML
```

Formats crossing each boundary:

1. **Input trace.** `meta.json` maps layer name -> `[T, B, Cin, Hin, Win]`
   (stored subset: T=4, B=5); `.npy` is that array, `dtype` "uint8" in
   `meta.json`. `load_layer_trace` checks shape equality (`src/archmodels/trace.py:38`).
2. **Workload dict.** `build_workload_from_trace` (`src/archmodels/trace.py:104`):
   KH=KW=3, stride 1, PAD=1 so HO=Hin, WO=Win; COUT = next layer's CIN, last
   layer reuses its own CIN.
3. **Schedule JSON** (`tracegen.ScheduleArtifact`, `src/tracegen.py:52`):
   `{arch, trace_dir, layer_name, workload:{problem:{...}}, result:{status,
   has_solution, objective, strategy:{NodeLevel{temporal_tile,spatial_split},
   NoCLevel{temporal_permutation,spatial_splitting}, DRAM{temporal_permutation}},
   metrics:{util, spatial_cost, temporal_traffic, delay, capacity}, configs:{arch,
   dataflow, mapspace (absolute paths)}}, dram_num_steps, mode}`. The strategy
   block comes from `util.build_strategy` (`src/util.py:13`).
4. **Native bridge wire format** (all int32, native endian;
   `src/archmodels/loas/main.cpp:6-20`, `src/archmodels/loas/native_bridge.py:26`):
   `task.bin` = `T,B,Cin,Hin,Win`, `num_tiles`, `num_samples`, then 11 int32 per
   tile (12 for GustavSNN, `src/archmodels/gustavsnn/native_bridge.py:34`), then
   sample indices; `trace.bin` = uint8 row-major `[T,B,Cin,Hin,Win]` of only the
   requested samples; `out.bin` = per sample (outer) per tile (inner):
   `tile_idx, sample_idx, mac_cycles, num_ticks`, then per tick
   `tick, n_addr`, then `n_addr` x `(kh,kw,cin,cout_start,cout_end)`
   (`src/archmodels/tick_output.h:35`).
5. **Weight-trace JSON.gz** (`tracegen.LayerWeightTrace` :213 via `asdict`):
   `{arch, trace_dir, layer_name, sample_idx, workload_dims (the inner
   "problem" dict, includes "shape"), dram_num_steps, noc_num_steps, tiles:[{dram_i,
   noc_i, mac_cycles, lif_cycles (always null), ticks:[{tick, cores:[{core_id,
   weight_addresses:[[kh,kw,cin,cout_start,cout_end],...]}]}]}]}`. Path:
   `<out-dir>/<arch>/[<combo-tag>/]<trace_dir>/<layer>/sample_<5 digits>.json.gz`
   (`scripts/generate_weight_traces.py:111-114`).
6. **WCTS v1 stream** (`src/tracegen.py:483-667`): 56-byte fixed header
   (magic `WCTRACE1`, version 1, header_bytes, n_tiles, n_cores, weight_bytes=1,
   burst_dim=3 (COUT), burst_stride=1, burst_span=max run length in the layer,
   n_addr_fields=5, n_spatial, n_dims=7, identity_bytes), then 5 field codes,
   `(dim_id, factor)` spatial pairs, `(dim_id, extent)` for all 7 dims, identity
   `arch\0trace_dir\0layer\0sample_idx\0`. Per tile frame `<iiqQ` = tile_index,
   cores-in-frame, mac_cycles (i64), payload bytes; per core `<ii` core_id,
   n_bursts; per burst `<q5i` local_tick, kh, kw, cin, run_start, run_end (28 B).
   Trailer `<iQ` = -1, total bursts. Dim wire codes 0=KH..6=T (`:515`), equal to
   `parsers.layer.DIM_*`.
7. **Simulator outputs.** `wcache_run`/`wcache_sweep` print CSV (header with
   `--header`) to stdout or `--out`; drivers read columns such as
   `total_cycles, tick_base_total, l1_hit_rate, l2_hit_rate, dram_bytes,
   dram_accesses, stall_*, pf_*, line_size_bytes, l1_num_sets`.
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

Invocations of downstream code made by in-scope code:

- `tracegen` imports `nocsim.schedule.decode.schedule_from_strategy` and
  `nocsim.schedule.tiles.iter_node_tiles` (`src/tracegen.py:41-42`).
- nocsim: `python -m nocsim.sim --schedule S.json --layer L.yaml --arch A.yaml
  --weight-trace sample_NNNNN.json.gz --out tc.csv --simulate` with
  `PYTHONPATH=src` (`profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:63-72`,
  `profiling/0831_all_layer_streams/run_compare.py:144`). `L.yaml` is the
  schedule's own `workload` block dumped to YAML.
- wcache: `wcache_run --config C.json --trace X.wcts [--arm cache|spad_oracle]
  [--tier T] [--run-id R] [--git-commit G] --header [--out -] [--access-log F]
  [--line-trace F --line-trace-level l1] [--cache-state F --cache-state-core 0]
  [--l2-oracle F] [--oracle-only]`; `wcache_sweep --config-grid G.json --trace
  X.wcts|- [--out F] --arm --tier --run-id --git-commit --header`. One
  `wcache_sweep` call accepts only configs that agree on the address mapper
  (`cin_block`, `cout_block`, `weight_bytes`, `layout`), so drivers split grids
  per mapper (`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:115-131`,
  `profiling/0907_linesize/run_sweep.py:87-95`).
- cachesim (0803 only): `cachesim.native_bridge.native_hierarchical_sweep(path, DIMS)`
  (`profiling/0803_l1_l2_cache/run_sweep.py:123`), binary
  `src/cachesim/cache_sweep_hierarchical`.

### 1.5 One run, step by step (the stream path used by 0820 and every later stage)

1. `generate_weight_traces.py --stream --arch loas --trace-dir D --layer L
   --sample-start s --sample-count 1 --schedule-cache C` -> `parse_args` :339
   rejects `--workers>1`, `--all-layers`, missing `--trace-dir/--layer`.
2. `run_stream` :293: `_resolve_samples` :74 gives `[s]`; loads
   `C/loas/D/L.json`.
3. `tracegen.load_schedule` (`src/tracegen.py:134`): JSON -> `ScheduleArtifact`;
   the workload is dumped to a temp YAML (`_dump_workload_path` :64,
   `delete=False`), parsed as `SNNProb`; `schedule_from_strategy` decodes the
   strategy; `iter_node_tiles` yields one `NodeTileSpec` per (dram step, NoC
   step, core).
4. `n_cores` = product of `schedule.spatial_factors` (`scripts/generate_weight_traces.py:316-320`),
   so idle cores still count.
5. `load_layer_trace(..., mmap=True)` maps the `.npy`.
6. `tracegen.reconstruct_samples` :296 imports `ARCH_NATIVE_BRIDGES[arch]` and
   calls `reconstruct_samples_native`: slice `trace[:, samples]` to contiguous
   uint8 (`src/archmodels/loas/native_bridge.py:102`), write `trace.bin` and
   `task.bin` in a temp dir, run `loasgen trace.bin task.bin out.bin`, parse
   (`_unpack_output` :45, asserts every byte consumed), then
   `assemble_layer_traces` (`src/tracegen.py:241`).
7. `emit_stream` (`scripts/generate_weight_traces.py:272`) ->
   `stream_weight_trace` (`src/tracegen.py:633`): converts tick-major to
   core-major frames (`_wcts_tile_frames` :596), writes header, frames, trailer
   to stdout; with `--dump-trace`, a second pass writes the same bytes (or the
   first N tiles plus a valid trailer) to a file.
8. The consumer (`wcache_sweep --trace -`) reads stdin and writes one CSV row
   per config. The 0820 driver wires the pipe (`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:251-253`),
   checks row count equals config count, then `os.replace`s the per-unit CSV
   into place (:264-269).
9. The driver merges unit CSVs (:279). Later stages instead aggregate rows per
   (layer, arm) as means over 5 samples, join against nocsim
   `all_layers_vs_nocsim.csv`, and render HTML.

### 1.6 Canonical commands (all from the repo root; scripts use cwd-relative `src`)

```
# build (once per machine)
make -C src/archmodels/loas            # also ptb, spinalflow, prosperity, gustavsnn
make -C src/wcache/native MODE=release lib apps      # per comment at 0820 run_sweep.py:34
make -C src/nocsim/eventsim ; make -C src/cachesim

# Stage 1 (Gurobi)
PYTHONPATH=src python scripts/solve_schedules.py --archs loas
PYTHONPATH=src python profiling/0831_reuse_distance/solve_31.py   # loas, inst16, all 31 _n5 layers

# Stage 2, file form (sample indices must be < 5 for the stored subset)
python scripts/generate_weight_traces.py --arch loas --trace-dir vgg16_T4_n5 \
    --layer layer_01_features_3 --sample-start 0 --sample-count 5

# Stage 2, stream form, into wcache
python scripts/generate_weight_traces.py --stream --arch loas --trace-dir vgg16_T4_n5 \
    --layer layer_08_features_27 --sample-start 0 --sample-count 1 \
    --schedule-cache profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules \
  | src/wcache/native/build/release/wcache_sweep --config-grid grid.json --trace - --out rows.csv --arm cache --tier t

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
  `run_assoc31.py` / `analyze31.py` (they generate streams on the fly),
  `profiling/0823_stagewise_verify/stage3_nocsim/run_armS_stage12.py`.
- **Not runnable as written**: anything naming `*_T4_all` or `/work`/`/u/yyu9`
  (0803, 0820 campaign grids, 0823 stage1, 0831_all_layer_streams/solve_all_layers.py,
  `scripts/solve_inst16_subset.py`, `tests/test_stream_flag.sh`), and every
  stage after 0831 until `profiling/0831_all_layer_streams/{streams,outputs}`
  or `profiling/0823_stagewise_verify/stage4_wcache/inputs/streams` are
  regenerated (neither is tracked; the second is absent on this disk).

### 1.7 The 13 profiling stages

All drivers resolve `ROOT` from `__file__`, insert `ROOT/src` into `sys.path`,
and write under the stage's own `outputs/` unless noted. "5 samples" means
array indices 0-4 of the `_n5` subset. Tags: `V<n>`/`R<n>` = vgg16/resnet19
layer number n.

| Stage | Driver(s) | Inputs | Simulator invoked | Swept parameters | Outputs |
|---|---|---|---|---|---|
| `0728_status_replay` | `build_artifact.py` `main` :58 | tracked `loas_cout_only.csv`, `loas_cin_cout_2d.csv` | none in this dir; CSV producer not in the stage | validation expects 31 layers x 4 sizes x 3 structures x 3 line sizes per layout, 2 layouts, n=5 (:36-53) | `artifact/data.js` (tracked) |
| `0803_l1_l2_cache` | `run_sweep.py` `main` :218 (`--run`, `--workers`, `--unit-index`, `--merge-only`), `build_artifact.py` :160; `run_sweep.slurm` (not read) | `sample_0000{0..4}.json.gz` under `/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces/loas/<arch_config>/<wl>_T4_all/<layer>/` (:23); `outputs/schedules/multinode_sweep/classification.csv` (build) | `cachesim.native_bridge.native_hierarchical_sweep` | 4 arch configs (inst16/inst1024 x noc512kb/noc4096kb, node32kb) x 31 layers x 5 samples = 124 units; per sample 24 configs = {FA, 32-way, 4-way} x L1 {16,32} KB x L2 {128,256,512,1024} KB (:34-46) | `results/*.csv`, `per_core/*.csv.gz`, `hierarchical_cache_results.csv` (14,880 rows; absent), `artifact/` (tracked) |
| `0820_phaseD_spad_vs_cache` | `run_sweep.py` `main` :338 (`--grid`, `--run`, `--tier`, `--workers`, `--unit-index`, `--merge-only`, `--dry-run-units`, `--trace-root`, `--results-dir`, `--out`); `tests/*.sh` | `grids/*.json`; units name `*_T4_all` trace dirs and `schedule_cache` (e.g. `outputs/schedules/inst16`); fixtures from `src/wcache/examples/` | `generate_weight_traces.py --stream` piped into `wcache_sweep --trace -` | `tier0`/`tier3_full`: 180 = L1 {2,4,8,16,32} KB x cin_block {1,2,4} x L2 {256K,512K,1M} x prefetch {none, next_burst 2/4/8}; `cache16`: 36 (L1 8 KB; cin_block x L2 x prefetch), 3 archs x 4 layers x 5 samples; `cache16_l1_16k` 12; `cache16_lat` 12 (l2_latency 5, miss 50); `tier2_ridge` 15; `tier4_latency` 5; `tier1_spad` 1 (arm `spad_wcache`); `demo` 4; `duplicate_check` 4 | `results/<tier>/<unit>.csv`, merged `--out` (default `spad_vs_cache.csv`); tracked `cache16*_results.csv` |
| `0823_stagewise_verify` | stage1 `run_stage1.py`; stage2 `run_stage2.py`, `verify_reconstruction.py`, `wcts_excerpt.py`; stage3 `run_stage3.py`, `run_armS_stage12.py`; stage4 `inputs/gen_streams.sh`, `oracle_gate.py`, `run_w5.py`, `run_khkw_sweep.py`, `run_l2_capacity_probe.py`, `run_layout_control.py`, `analyze_khkw_sweep.py`, `build_artifact.py`; `input_trace_audit/audit_density.py` | 4 layers (vgg16 layer_08/09, resnet19 layer_09/16); stage1 reads `_all` `meta.json` on `/work` and `configs/arch/multinode_sweep/loas_inst16_node32kb_noc4096kb.yaml`; stage2+ read `input_trace/loas/*_n5` | Gurobi (stage1); generator + `loasgen` (stage2); `nocsim.sim --simulate` (stage3); `wcache_run`, `wcache_sweep` (stage4) | stage1: num_pes {4,16,64,256}; all 13 TrafficModes; NoC totals {8 KiB..4 MiB} split 30:1:1. stage4: configs C2-C6 x layouts {block_pack, split_cin}; khkw_split line {16,32,64} B x l2_banks {1,2,4,8} x prefetch distance {0,1,2,4} (48 x 20 = 960 rows); L2 {512K..16M}; 3 layouts at the best point | per-stage `inputs/` + `outputs/`; 312 MB tracked incl. 20 single-node `sample_*.json.gz` |
| `0831_all_layer_streams` | `solve_all_layers.py [--check]`, `gen_streams.py [--check] [--workers]`, `gen_weight_traces.py`, `run_compare.py --workers` | arch/dataflow from 0823 stage1 inputs (`noc2MiB_pe16`); `_all` meta on `/work` (solve); `input_trace/loas/*_n5` | Gurobi; generator via `/u/yyu9/miniconda3/bin/python`; `wcache_sweep` (one config `BEST`); `nocsim.sim --simulate` | none: 31 layers x 5 samples at one config | `schedules_all/`, `schedules/`, `streams/` (16 GB, untracked), `weight_traces/`, `outputs/{wcache_rows.csv, nocsim_rows.json, all_layers_vs_nocsim.csv}` (absent) |
| `0831_l2_prefetch` | `run_sweep.py [workers=16]`, `analyze.py`, `build_artifact.py <out.html>` | 0831 `streams/`, 0831 `outputs/` | `wcache_sweep` (tier `l2pf`) | `l2_prefetch_policy` none vs `neighbour` on cin, up / down / both (4 configs) | `outputs/l2pf_rows.csv`, `l2pf_by_layer.csv`, HTML |
| `0831_reuse_distance` | `solve_31.py`, `run_assoc31.py`, `analyze31.py`, `run_reuse_hist.py`, `run_belady.py`, `analyze_reuse.py`, `plot_reuse.py`, `build_profile31.py`, `build_assoc31_artifact.py`; C++ `reuse_tool.cpp`, `reuse_distance.h`, `test_reuse_distance.cpp` | `configs/arch/loas_inst16.yaml`; `input_trace/loas/*_n5`; `outputs/schedules/inst16`; 0823 stage4 streams + `_khkw_grid/khkw_64b.json` | Gurobi (solve_31); generator; `wcache_run` with `--access-log`, `--cache-state`, `--l2-oracle`; `reuse_tool` | `l2_assoc` 16 vs 32 over 31 layers; Belady: 6 arms (LRU/Belady x 16-way, 64-way, FA); reuse histograms at the khkw best config | `outputs/*.csv`, `spectra.svg`; tracked `artifact.html`, `assoc31.html` |
| `0902_l1_evictions` | `run.py` | 0831 `streams/`, sample 0 only | `wcache_run --out - --line-trace F --line-trace-level l1` | none (0831 baseline config) | `outputs/l1_evict.csv` |
| `0903_hot_cin` | `run.py [--demo / --tiles / --reuse / --reuse-times / --topn / --hot]` | 0823 stage4 `inputs/streams/{V8,V9,R9,R16}_s*.wcts` | none: decodes WCTS in NumPy | analysis mode only | `outputs/hot_cin*.json` |
| `0903_l1_8k` | `run_sweep.py [workers=16]` | 0831 `streams/`, `all_layers_vs_nocsim.csv` | `wcache_sweep` (tier `l1cap`) | `l1_size_bytes` {16384, 8192} | `outputs/l1cap_{rows,by_layer,aggregate}.csv` |
| `0907_assoc` | `run_sweep.py [workers]`, `make_page.py` | as 0903_l1_8k | `wcache_sweep` (tier `assoc`) | `l1_assoc` {32, 16, fully assoc} x `policy` {lru, rrip} x L1 {16K, 8K} = 12 points | `outputs/assoc_{rows,by_layer}.csv`, `page_assoc.html` |
| `0907_index_policy` | `run_sweep.py [workers]`, `make_pages.py` | as above | `wcache_sweep` (tier `policy`) | `policy` {lru, rrip, lfu} x L1 {16K, 8K} = 6 | `outputs/policy_{rows,by_layer,aggregate}.csv`, `page_16k.html`, `page_8k.html` |
| `0907_linesize` | `run_sweep.py [workers]`, `make_page.py` | as above | `wcache_sweep`, 3 passes per stream (tier `linesize`) | `cin_block` {16,8,4} (64/32/16 B lines) with `l1_assoc` {32,64,128} so sets stay fixed, x L1 {16K, 8K}; policy rrip, `rrip_bits` 5 | `outputs/line_{rows,by_layer}.csv`, `page_linesize.html` |

Common base config after 0823 (copied in each driver): `layout khkw_split,
cin_block 16, cout_block 4, weight_bytes 1, l1 16 KB 8-way, l2 512 KB 16-way,
l2_mshrs 32, l2_banks 1, l1_latency 0, l2_latency 2, l2_miss_latency 24,
prefetch none` (e.g. `profiling/0831_all_layer_streams/run_compare.py:62-68`,
`profiling/0903_l1_8k/run_sweep.py` `BASE`).

---------------------------------------------------------------------------

## 2. Bottom-up

### 2.1 `src/tracegen.py` (701 lines): solve / reconstruct / persist / stream

- `ScheduleArtifact` :52 dataclass. `mode` defaults to `"base"` so old caches load.
- `_dump_workload_path(workload)` :64 writes a temp YAML with `delete=False`
  and never removes it; `_prob_from_workload` :70 wraps it in `SNNProb`.
- `solve_and_cache_schedule(arch_name, arch_yaml, dataflow_yaml, trace_dir_name, layer_name, meta, next_cin, cache_dir)` :74
  -> builds workload, calls `mip_solver.solve.solve_best_schedule` (imported
  lazily :103 so the rest of the module needs no `gurobipy`), decodes to get
  `dram_num_steps`, writes `cache_dir/<arch>/<trace_dir>/<layer>.json` (:127).
  Always re-solves; raises `ValueError` if all modes infeasible.
- `load_schedule(path)` :134 -> `(artifact, prob, tiles)`; tiles rebuilt with
  `iter_node_tiles`, not stored.
- `CoreEntry` :151, `TickEntry` :162, `TileWeightTrace` :199, `LayerWeightTrace` :213:
  the nested trace shape. Absent cores are omitted, not padded.
- `merge_cores_by_tick(core_results)` :171: cross-core merge, ticks ascending.
- `tick_entries_from_flat(weight_addresses, tick_ids)` :224: old flat-format
  adapter; no caller left (all bridges emit tick-grouped data).
- `assemble_layer_traces(tiles, sample_indices, unpacked, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :241:
  keys on each record's own indices; `noc_num_steps = max(noc_i)+1`;
  `mac_cycles = max` over cores (:282); `lif_cycles=None` always (:284).
- `reconstruct_samples(arch_name, trace, tiles, sample_indices, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :296:
  the single dispatcher to `ARCH_NATIVE_BRIDGES`.
- `save_weight_trace(trace, path)` :330: gzip JSON written to a temp file then
  `os.replace` (no partial files).
- `StepCycles` :359 + `check_against(artifact, schedule)` :388: read-back of
  per-(dram_i, noc_i) `ComputeCycles` with six identity checks; compares
  `artifact.workload["problem"]` to `workload_dims`.
- `load_step_cycles(path)` :436: accepts `.json` or `.json.gz`; rejects duplicate
  tiles or tile count != `dram_num_steps*noc_num_steps`. Used by nocsim.
- WCTS constants :508-519; `write_stream_header(...)` :522 (checks
  prod(spatial_factors)==n_cores and all 7 dims present), `write_tile_frame` :561
  (core ids ascending, ticks strictly ascending, no empty cores),
  `write_stream_trailer` :591, `_wcts_tile_frames` :596 (rejects empty runs,
  core ids outside `[0,n_cores)`, measures `burst_span`),
  `stream_weight_trace(trace, fh, *, n_cores, spatial_factors, burst_dim=3, burst_stride=1, weight_bytes=1, max_tiles=None)` :633.
- `sample_indices(n=100, seed=0, n_total=10000)` :674: canonical 100 =
  `random.Random(0).sample(range(10000),100)`, n>100 adds more at `seed`;
  n<100 raises. Indices refer to the full 10,000-sample capture.

### 2.2 `src/util.py`

- `build_strategy(levels)` :13: fuses solver factor placements into the
  `NodeLevel / NoCLevel / DRAM` strategy dict; NoC/DRAM temporal blocks are
  displayed outer-to-inner (reversed). Helpers `_region_levels` :52,
  `_strategy_block` :56, `_tile_block` :68, `_loops` :75, `_fuse_kind` :82
  (fuses adjacent same-dim), `_fuse_same_dim_kind` :92 (fuses all same-dim),
  `_append_or_fuse` :112, `_new_segment` :123, `_format_order` :135. `REGIONS`,
  `KINDS` :9-10 are unused.

### 2.3 `src/parsers/`

- `__init__.py`: re-exports the five parsers.
- `layer.py`: `DIM_KH..DIM_T = 0..6` :35-41; `SNN_REDUCTION_DIMS` = {KH,KW,CIN} :47;
  `_get_prime_factors` :50 (1 -> [1]); `parse_snn_layer` :67; `SNNProb` :85
  (`prob_bound`, `prob_factors`, name/index maps; unknown keys only warned);
  `config_str` :159, `is_reduction_dim` :163, `print` :167.
- `arch.py`: `MEM_NODE/NOC/OFFCHIP` :63-65; `parse_snn_arch` :68; `SNNArch` :86:
  levels must be exactly `[NodeLevel, NoCLevel, OffChip]`; `node_dim_capacity`
  here is an error (belongs in dataflow); `S[i]=instances[i]//instances[i+1]`
  (:199); `single_node` flag (:172); properties `has_local_buffer` :186,
  `has_noc_buffer` :191; private parsers :210-335; `config_str` :341 (file stem).
- `bitwidths.py`: defaults :32-35 (BW_WEIGHT 8, BW_PSUM 32, BW_VMEM 32,
  DRAM_LATENCY 0.25 cycles per 32-byte packet, fractional on purpose);
  `parse_snn_bitwidths` :38; `SNNBitwidths` :55.
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
  `compute_cycles` :82, `weight_addresses` :86, `weight_ticks` :96) - left from
  the removed Python models; only `DenseStaticComputeModel` implements it.
- `dense.py`: `_dim_totals` :24; `DenseStaticComputeModel(schedule, prob)` :32:
  same MAC/LIF count for every tile from the loop factors (`_pe_cycles` :52,
  `_lif_cycles` :67 counts only dims with `_A[j][VAR_VMEM]`). Used by nocsim when
  no weight trace is given.
- `trace.py`: `KH=KW=3` :27, `PAD=1` :29; `load_layer_trace(trace_dir, layer_name, mmap=False)` :38;
  `valid_layer_names(meta)` :83 (HO,WO>=1; never filters with PAD=1);
  `build_workload_from_trace(meta, layer_name, next_cin=None)` :104.
- `<arch>/__init__.py` (5 files): docstrings only (paper, fixed deployment).
- `<arch>/native_bridge.py` (5 near-identical files; loas lines given):
  `_BINARY` :23; `_pack_task(trace_shape, tiles, sample_indices)` :26;
  `_unpack_output(data, num_tiles, sample_indices)` :45;
  `reconstruct_samples_native(trace, tiles, sample_indices, arch_name, trace_dir_name, layer_name, workload_dims, dram_num_steps)` :72.
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
  (`src/archmodels/loas/main.cpp:134-143`). The 5 files differ only in names
  and the tile-record fields.
- `loas/LoASGen.h` `reconstruct_sample` :63: one tile = one (ho, wo) pixel;
  walk (kh, kw, cin), emit an address when that input site spikes at any t in
  `[t_off, t_off+t_n)`; tick = emission index; `mac_cycles` = number emitted.
- `ptb/PTBGen.h`: `TW_SIZE=8, PE_ROWS_MAX=16, PE_COLS_MAX=8` :40-42;
  `compute_cycle_count(ln, cout_n, total_t)` :76 systolic fill/drain;
  `reconstruct_sample` :86: Pass 1 silence removal (addresses), Pass 2 merge of
  non-overlapping neighbours gives `ln`; `mac_cycles = max(access, compute)`.
- `spinalflow/SpinalFlowGen.h` `reconstruct_sample` :55: one address per spike
  event, t outermost; tick = event index.
- `prosperity/ProsperityGen.h`: `popcount64` :79; `reconstruct_sample` :89: rows
  sorted by popcount, prefix row by subset test, address per set bit of the XOR
  pattern; emitted in processing order.
- `gustavsnn/GustavGen.h`: `PE_COUNT_MAX=8` :34; `reconstruct_tile` :81 (per-HO-row
  submatrices), `addresses_and_ticks` :131 (waves of 8 submatrices; tick =
  wave_start + line index, so several addresses share a tick),
  `reconstruct_sample` :170.

### 2.5 `src/mip_solver/` (3.3k lines)

- `__init__.py`: re-exports constants only (no `gurobipy`). `__main__.py`: `cli.main()`.
- `constants.py`: `SNN_GB_START_LEVEL=1` :58; `VAR_WEIGHT/PSUM/VMEM` 0/1/2;
  `TRAFFIC_MULT=[1,2,2]`; `_A` :83 (dim -> var size relation); `_B` all ones;
  `build_Z(B, num_mems)` :106 (no caller outside `__init__`).
- `schedule.py`: `create_schedule_vars(m, prob, arch, gb_start_level=1)` :49:
  binary `x[(i,j,n,k)]` (k 0=spatial 1=temporal) over `total_levels = 1+2P`
  (P = total prime-factor count, :73-76); integer `y[(v,i)]` over NoC+DRAM slots.
- `modes.py`: `TrafficMode` :53 (13 values: base, psum_{dram,gb}_otok,
  vmem_{dram,gb}_xxxt, dram_{oooo,ooot,oook}, both_dram_ootk, gb_{oooo,ooot,oook,ootk});
  `_ModeSpec` :73; `_MODE_SPECS` :79 maps each to a constraint adder +
  `zero_vars` / `gb_only_vars`.
- `solve.py`: `solve_schedule(layer_path, arch_path, dataflow_path, mapspace_path=None, time_limit=None, mip_gap=None, output_flag=False, traffic_mode=BASE, return_metrics=False)` :54:
  builds parsers, vars, constraints, objective; `model.dispose()` in `finally` (:175);
  records absolute config paths (:177-181). `_collect_result` :185,
  `_extract_strategy` :219, `_region` :246, `_status_name` :254, `_safe_attr` :258,
  `_mode_score` :272 with weights `0.1, 1.0, 10.0` (:269),
  `solve_best_schedule(layer, arch, dataflow)` :279 (loops all 13 modes, no
  mapspace, no time limit).
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
  `_build_noc_utilization` :76, `_build_node_util_reward` :109,
  `_build_data_size` :147 (coefficients `0.8+0.04*i`),
  `add_utilization_capacity_constraints` :177, `_bytes_by_var` :197,
  `_loop_upper_for_global_buffer` :205.
- `objectives/traffic/spatial.py` `compute_spatial_traffic` :37;
  `temporal.py` `compute_temporal_traffic` :55; `total.py` `build_traffic_cost` :32
  (`0.99*data_size + 0.99*spatial + temporal`, zero_vars dropped).
- `analysis/dram_permutation.py`: `SUPER_DIM` :23, `classify_permutation(loops)` :31
  (M/N/K/T string), `classify_schedule_file(path)` :43. Used only by `scripts/tmp/analyze_*`.

### 2.6 `scripts/`

- `solve_schedules.py`: `parse_args` :47, `_iter_valid_layers` :60 (next_cin
  inline :71), `main` :75 (rows OK/SKIPPED/INFEASIBLE/ERROR -> `summary.csv` :114).
  Arch YAML fixed by name :34-44 (single-node files); no override flag.
- `generate_weight_traces.py`: `_resolve_samples` :74 (explicit range, else
  `tracegen.sample_indices`); mode 1 `run_one_combo` :126 with `_STATE` :89,
  `_init_worker` :92, `_process_chunk` :104, `_chunks` :119 (skip existing
  samples :141 unless `--force`); mode 2 `run_all_layers` :251 with
  `_layers_for` :181, `_all_layer_targets` :187, `_regenerate_layer` :195
  (`SAMPLE_CHUNK_SIZE=10` :64, no `--combo-tag`), `_regenerate_one_layer_task` :220,
  `_run_pass` :226 (two passes, `FIRST_PASS_SAMPLES=10` :67; `--workers 0` =
  `len(os.sched_getaffinity(0))` :257); mode 3 `run_stream` :293, `emit_stream` :272;
  `parse_args` :339 (sentinel test `n_samples != 100` :378).
- `subset_input_traces.py`: `subset_one(src_dir, dest_dir, n, seed)` :51:
  `np.random.default_rng(seed).choice`, sorted (:61), same indices for every
  layer, rewrites `B` and adds `meta["subset"]`; `main` :98.
- `solve_inst16_subset.py`: `ARCHS` :22, `LAYERS` :26 (4 `_T4_all` layers),
  `main` :34 (arch `configs/arch/<arch>_inst16.yaml` :48, next_cin inline :64).
- `scripts/tmp/` (tracked, not in the brief): multinode sweep generator/solver/
  analyzers, `probe_gurobi_concurrency.py`, `run_combo.sh`,
  `run_loas_sweep_combo.sh` (the latter shows how the 0803 inputs were made:
  `--schedule-cache outputs/schedules/multinode_sweep/<combo> --out-dir /work/... --combo-tag <combo>`).
  Not documented further.

### 2.7 `configs/`

- `arch/`: `<arch>.yaml` x5 (single node, `instances: 1`, `single_node: true`,
  no NoC entries; num_pes loas 16, ptb 128, ...), `<arch>_multinode.yaml` x5
  (128 nodes, NoC 1 MiB per tensor), `{loas,ptb,spinalflow}_inst16.yaml` (16
  nodes, no NodeLevel `local_buffer`), `snn_arch.yaml` (generic example),
  `multinode_sweep/` 400 files = 5 archs x instances {16,64,256,1024} x node
  {2,4,8,16,32} KB x NoC {512,1024,2048,4096} KB, with NodeLevel and NoC
  entries split 30:1:1 (e.g. node 16 KB -> weight 15360, psum 512, vmem 512).
  All `DRAM_LATENCY: 0.25`.
- `dataflow/<arch>.yaml` x5: `node_dim_capacity` per dim (e.g. loas KH/KW/CIN/T
  `full`, COUT `{spatial: 4}`).
- `cache/cache_config{,_tiny}.yaml`: old cachesim configs (32 KB FA, 32 B line,
  `inner_dim cin`); not read by any in-scope code.
- `mapspace/mapspace.yaml`: `spatial_dims` = all 7; default for the CLI only.
- `workloads/sample_snn_layer.yaml`: 3x3, CIN 64, COUT 128, 56x56, T 4; CLI default.

### 2.8 `input_trace/`

`input_trace/loas/` (13.6 MB, tracked although `.gitignore` excludes
`input_trace/`): `vgg16_T4_n5/` (12 layers `layer_01_features_3` ..
`layer_12_features_40`, Cin 64..512, 32x32 down to 2x2) and `resnet19_T4_n5/`
(19 layers incl. 3 `*_shortcut_0`), each with `meta.json` (T=4, B=5,
dataset cifar10, dtype uint8, `subset.sample_indices` e.g. vgg16
`[2697, 3078, 5110, 6367, 8502]`, seed 0, made by `scripts/subset_input_traces.py`).
Only LoAS-captured traces exist; every arch model reads these same spikes.

### 2.9 `profiling/` stage code

Shared pattern of the 0831-0907 sweep drivers, documented on
`profiling/0907_linesize/run_sweep.py`:
`BIN` :60 (`wcache_sweep` release build), `STREAMS` :61 (0831 streams),
`NOCSIM` :62 (`all_layers_vs_nocsim.csv`), `BASE` :66, grids :87-96,
`tags()` :107 (`V<n>`/`R<n>` from `_n5` meta), `one(args)` :116 (one
`wcache_sweep` call per mapper, checks row count, labels `_tag _sample _layer _arm`),
`aggregate(rows, avail)` :139 (mean over 5 samples, spread, speedup vs the
reference arm, joins nocsim makespan), `write_csv` :176, `main` :183 (threads,
`git rev-parse --short HEAD`, writes `*_rows.csv`, `*_by_layer.csv`).
Diffs: `0903_l1_8k/run_sweep.py` (`tags` :42, `one` :51, `geomean` :69,
`aggregate` :74, `write_csv` :130, `main` :137; adds `*_aggregate.csv`);
`0907_assoc/run_sweep.py` (`assocs_for` :65, `arm_tag` :68, `tags` :89, `one` :98,
`aggregate` :116, `write_csv` :151, `main` :158); `0907_index_policy/run_sweep.py`
(`arm_size` :59, `arm_policy` :60, `tags` :68, `one` :77, `geomean` :95,
`aggregate` :100, `write_csv` :158, `main` :165); `0831_l2_prefetch/run_sweep.py`
(`tags` :48, `one` :57, `main` :75; no aggregation, see `analyze.py`).

Per file (functions with lines; one phrase each where the name is not enough):

- `0728_status_replay/build_artifact.py`: `read_rows` :15, `validate` :35, `main` :58.
- `0803_l1_l2_cache/run_sweep.py`: `discover_units` :59 (requires exactly 124
  units, 5 samples each), `print_preview` :85, `_rate` :102, `run_unit` :106
  (asserts L2 accesses == L1 misses), `merge_results` :175, `main` :218.
  `build_artifact.py`: `read_rows` :26, `read_schedule_rows` :76,
  `read_trace_example` :106, `aggregate` :137, `main` :160.
- `0820_phaseD_spad_vs_cache/run_sweep.py`: `sweep_binary` :43 (release then
  fixture build), `git_commit` :53, `load_grid` :75 (exactly one of
  `units`/`fixtures`, `axes`/`configs`), `cross` :87 (dict-valued axis values
  move knobs together), `expand_configs` :104, `layout_of` :115 (defaults
  cin 1, cout 16, wb 1), `layout_groups` :122, `layout_tag` :129,
  `expand_traces` :140 (`CONFIRM_*` placeholders make a unit refuse to run),
  `build_tasks` :160, `producer_argv` :176, `emit_fixture_stream` :197 (stubs
  `archmodels.trace` to avoid NumPy), `run_unit` :233, `merge_results` :279
  (header taken from unit files), `print_preview` :318, `main` :338.
  `tests/`: `demo_smoke.sh` (row invariants: total >= tick base, stall parts
  sum, prefetch outcomes sum), `duplicate_check.sh` (prefetch-distance
  budget), `replay_check.sh` (dump then replay equals stdin run),
  `test_resume.sh` (atomic per-unit resume), `test_slurm_shape.sh` (greps the
  `.slurm` for Delta settings).
- `0823_stagewise_verify/stage1_mip_solver/run_stage1.py`: `sha` :66,
  `split_30_1_1` :70, `write_arch` :76, `kb` :86, `stage_inputs` :90,
  `next_cin_for` :152, `strategy_digest` :158, `run_num_pes` :171,
  `run_all_modes` :200, `run_noc_sizes` :235, `main` :274.
- `.../stage2_weight_trace/run_stage2.py`: `sha` :53, `stage_inputs` :57
  (copies schedules and rewrites `trace_dir` `_all` -> `_n5`),
  `run_generator` :121, `input_trace_stats` :153, `weight_trace_stats` :179,
  `main` :227 (pass A files with `--combo-tag noc2MiB_node32kb`, pass B
  `--stream --dump-trace`). `verify_reconstruction.py`: `pixel_row_counts` :43,
  `generated` :67, `main` :89 (NumPy re-derivation of LoAS row counts).
  `wcts_excerpt.py`: `main(path, max_tiles=2, max_cores=2, max_bursts=6)` :13.
- `.../stage3_nocsim/run_stage3.py`: `sha` :49, `layer_yaml` :53, `run_one` :63
  (`compute_per_node = count_cycles // 16`), `main` :99.
  `run_armS_stage12.py`: `sha` :54, `next_cin_for` :58, `stage1` :64, `stage2` :94, `main` :133.
- `.../stage4_wcache/`: `oracle_gate.py` `main` :34 (`--oracle-only --arm
  spad_oracle`, compares with stage 3 `compute_per_node`); `run_w5.py` `main` :38
  (C3 fully-associative pairs must match across layouts); `run_khkw_sweep.py`
  `grid_for` :52, `one` :65, `main` :86; `run_l2_capacity_probe.py` `one` :36,
  `main` :54; `run_layout_control.py` `one` :35, `main` :51;
  `analyze_khkw_sweep.py` `main` :26; `build_artifact.py` (module-level script)
  `num` :27, `bar` :30, `table` :37, `_pick` :235, `_cliff` :264, `_cap_gain` :272,
  `bf` :424. `inputs/gen_streams.sh`: 20 `--stream --dump-trace` runs, then
  `cmp` against stage 2 dumps.
- `.../input_trace_audit/audit_density.py`: module-level script, `p` :14.
- `0831_all_layer_streams/solve_all_layers.py`: `load_meta` :66, `next_cin_for` :70,
  `solve_one` :76, `write_n5_copy` :82, `run_check` :97, `run_all` :115.
  `gen_streams.py`: `tasks` :56, `generate` :71, `run_check` :87, `main` :103.
  `gen_weight_traces.py`: `sample_path` :52, `tasks` :56, `generate` :65,
  `run_check` :81, `main` :103. `run_compare.py`: `combos` :71, `layer_yaml` :81,
  `run_wcache_one` :94, `phase_wcache` :110, `run_nocsim_one` :144,
  `phase_nocsim` :176, `phase_join` :202, `main` :267.
- `0831_l2_prefetch/analyze.py`: `mean` :12, `main` :14 (gate: `off` arm must
  equal 0831 `wcache_rows.csv`). `build_artifact.py`: `cell` :73, `bar` :85, `table` :91.
- `0831_reuse_distance/`: `solve_31.py` `main` :16; `run_assoc31.py` `layers` :27,
  `engine` :34, `main` :46; `analyze31.py` `l2_seq` :20, `stack_hist` :29, `main` :41;
  `run_reuse_hist.py` `check_best_matches_friday` :56, `preview` :66, `one` :91,
  `main` :136; `run_belady.py` `check_best` :55, `engine` :61, `l2_digest` :79,
  `one` :94 (iterates oracle until the L2 log stops changing), `stage3` :120,
  `preview` :127, `main` :148; `analyze_reuse.py` `engine` :52, `load` :67,
  `merged` :74, `curve` :82, `pct` :89, `main` :93; `plot_reuse.py` `load` :39,
  `sx` :48, `sy` :53, `panel` :61, `main` :130; `build_profile31.py` `hit_rows` :51,
  `rd_rows` :65, `rc_rows` :79; `build_assoc31_artifact.py` `tbl` :40, `net_row` :53,
  `d` :295, `c` :296 (module-level script). C++: `reuse_tool.cpp` `main` :58
  (`reuse_tool <access.log> <out.csv> [--dump N]`, magic `WCALOG01`, 8-byte
  records, one stack per L1 core + one for L2); `reuse_distance.h`
  `StackDistance` :47 (Fenwick tree, exact LRU stack distance, cold = -1),
  `ReuseHistogram` :143; `test_reuse_distance.cpp` `main` :237 (naive oracle vs
  tree). No build file in the directory.
- `0902_l1_evictions/run.py`: `tags` :48, `_cv` :57, `summarise` :68, `one` :183, `main` :208.
- `0903_hot_cin/run.py`: `read_stream` :34 (own WCTS decoder, 28-byte bursts),
  `gini` :69, `skew_stats` :77, `spearman` :97, `analyse` :104, `fmt` :138,
  `demo` :157, `main(argv)` :171, `tile_matrix` :212, `topk_capture` :218,
  `analyse_tiles` :229, `fmt_tiles` :301, `reference_order` :326, `line_ids` :333,
  `reuse_gaps` :341, `window_union` :352, `analyse_reuse` :365, `fmt_reuse` :398,
  `analyse_reuse_times` :420, `fmt_reuse_times` :472, `analyse_topn` :496,
  `fmt_topn` :542, `analyse_hot` :569, `fmt_hot` :619. `L2_LINES=8192`, `L1_LINES=256` :27-28.
- `0907_assoc/make_page.py`: `load` :32, `block` :57, `dots` :67, `build` :93,
  `main` :263; imports `CSS, fmt` from `0907_index_policy/make_pages.py`.
- `0907_index_policy/make_pages.py`: `load` :25, `accumulate` :32, `page_data` :72,
  `fmt` :231, `dot_chart` :235, `bar_chart` :266, `build` :286, `main` :444.
- `0907_linesize/make_page.py`: `load` :26, `dots` :50, `build` :77, `main` :253.

### 2.10 `tests/`

- `test_combine_cycles_table.py`: nocsim `combine()` charges each step the
  trace's `mac_cycles` (multi-node and single-node); skips without 0823 stage-2 traces.
- `test_emission_order.py`: arch binary output is sample-outer, tile-inner
  (reads a file from argv or `EMISSION_TRACE`).
- `test_eventsim_deps.py`: eventsim delays successors by dependency finish time
  (needs `src/nocsim/eventsim/eventsim`).
- `test_sim_weight_trace.py`: `nocsim.sim --weight-trace` CLI path and its error checks.
- `test_step_cycles.py`: `tracegen.load_step_cycles` and `StepCycles.check_against`.
- `test_stream_dump.py`: `emit_stream` dump is byte-identical / valid when truncated (fixture only).
- `test_stream_writer.py`: WCTS writer byte layout and rejection rules, round
  trip of a `src/wcache/examples` fixture.
- `test_weight_resend.py`: weight tile resent only on reload (`StepInfo`), uses
  0823 tracked schedules/layers.
- `stdout_roundtrip.sh`: an arch binary writes the same bytes to `-` and to a file.
- `test_stream_flag.sh`: end-to-end `--stream` via `conda run -n cosa_snn` on
  `vgg16_T4_all` (absent).

---------------------------------------------------------------------------

## 3. Findings for cleanup (code-evidenced)

### 3.1 Dead or unused code

- `tracegen.tick_entries_from_flat` `src/tracegen.py:224`: no caller.
- `mip_solver.constants.build_Z` `src/mip_solver/constants.py:106`: exported, never called.
- `util.REGIONS`, `util.KINDS` `src/util.py:9-10`: unused.
- Mapspace is parsed and initialized but never passed to a constraint or
  objective (`src/mip_solver/solve.py:77-80`, only echoed at :180);
  `solve_best_schedule` omits it entirely (:301). `configs/mapspace/mapspace.yaml`
  therefore changes nothing.
- `ArchComputeModel` Protocol `src/archmodels/__init__.py:68` and its
  `format_input_batch`/`weight_ticks` contract describe Python models moved
  to `dump/`; `DenseStaticComputeModel` (`src/archmodels/dense.py:32`) does not
  implement `format_input_batch`.
- `lif_cycles` is always `None` in generated traces (`src/tracegen.py:284`).
- `configs/cache/*.yaml`: no in-scope reader.
- `mip_solver.analysis` is used only by `scripts/tmp/`.

### 3.2 Duplicated logic

- "COUT = next layer's CIN" inline in 8 places: `scripts/solve_schedules.py:71`,
  `scripts/solve_inst16_subset.py:64`, `profiling/0823_stagewise_verify/stage1_mip_solver/run_stage1.py:113`
  and `:152`, `.../stage3_nocsim/run_armS_stage12.py:58`,
  `.../input_trace_audit/audit_density.py:37`,
  `profiling/0831_all_layer_streams/solve_all_layers.py:70`,
  `profiling/0831_reuse_distance/solve_31.py:28`. Belongs in `archmodels.trace`.
- Five stage-1 solve loops with the same structure: `scripts/solve_schedules.py:75`,
  `scripts/solve_inst16_subset.py:34`, `profiling/0831_reuse_distance/solve_31.py:16`,
  `profiling/0831_all_layer_streams/solve_all_layers.py:115`, `run_stage1.py:171`.
- Mode score defined twice with the same weights: `src/mip_solver/solve.py:269-276`
  and `src/mip_solver/enumerator.py:104`; weights also in `cli.py:94-102`
  and `objectives/combined.py:25-27`.
- `tags()`/`combos()`/`layers()` (tag from `_n5` meta) copied in
  `0831_l2_prefetch/run_sweep.py:48`, `0902_l1_evictions/run.py:48`,
  `0903_l1_8k/run_sweep.py:42`, `0907_assoc/run_sweep.py:89`,
  `0907_index_policy/run_sweep.py:68`, `0907_linesize/run_sweep.py:107`,
  `0831_all_layer_streams/run_compare.py:71`, `0831_reuse_distance/run_assoc31.py:27`.
  `write_csv`, `geomean`, `aggregate`, `sha`, and the `git rev-parse` call
  (11 copies) are likewise per-stage copies.
- The base wcache config dict is retyped in at least 15 drivers (grep
  `"l2_miss_latency": 24`); no shared config file.
- nocsim stdout parsing duplicated: `0823_stagewise_verify/stage3_nocsim/run_stage3.py:63`
  and `0831_all_layer_streams/run_compare.py:144`.
- Five arch `main.cpp` and five `native_bridge.py` differ only in names and the
  tile record (`diff` of loas vs ptb main.cpp is names only).
- Two WCTS decoders besides the C++ one: `0823_stagewise_verify/stage2_weight_trace/wcts_excerpt.py:13`,
  `0903_hot_cin/run.py:34`.

### 3.3 Hardcoded absolute paths and hosts

- `/u/yyu9/...`: `scripts/subset_input_traces.py:43-46`, `:114`;
  `profiling/0823_stagewise_verify/stage4_wcache/build_artifact.py:5`;
  `.../stage4_wcache/inputs/gen_streams.sh:14` (`/u/yyu9/miniconda3/bin/python`);
  `profiling/0831_all_layer_streams/gen_streams.py:41`, `gen_weight_traces.py:36`;
  `scripts/tmp/run_combo.sh:11`, `run_loas_sweep_combo.sh:9`,
  `probe_gurobi_concurrency.py:18-19`, `solve_multinode_schedules.py:22`,
  `sweep_multinode_arch_sweep.py:78`.
- `/work/hdd/bebv/yyu9/...` (NCSA Delta project storage): `profiling/0803_l1_l2_cache/run_sweep.py:23`,
  `build_artifact.py:18`; `profiling/0823_stagewise_verify/stage1_mip_solver/run_stage1.py:43`;
  `.../input_trace_audit/audit_density.py:9`; `profiling/0831_all_layer_streams/solve_all_layers.py:49`;
  `scripts/solve_inst16_subset.py:9` (usage); `scripts/tmp/run_loas_sweep_combo.sh:17`.
- Delta specifics in code: `srun -A bebv-delta-gpu -p gpuA100x4-interactive`
  (`.../stage4_wcache/build_artifact.py:732`), `-p gpuA40x4`
  (`profiling/0831_l2_prefetch/build_artifact.py:309`), and the `.slurm` shape test
  `profiling/0820_phaseD_spad_vs_cache/tests/test_slurm_shape.sh:5-10`
  (account `bebv-delta-gpu`, partition `gpuA40x4`, 16 CPUs, 128 GB, 2 h).
- Gurobi license paths in a docstring: `/u/yyu9/gurobi.lic`,
  `/sw/external/containers_other/gurobi/gurobi.lic`
  (`profiling/0831_all_layer_streams/solve_all_layers.py:16-21`).
- Schedule JSONs store absolute config paths (`src/mip_solver/solve.py:177-181`).

### 3.4 Server and environment assumptions

- cwd must be the repo root: `sys.path.insert(0, "src")` is relative in
  `scripts/generate_weight_traces.py:46`, `scripts/solve_schedules.py:23`,
  `scripts/solve_inst16_subset.py:19`; defaults `input_trace/loas`,
  `outputs/...` are relative. The 0820 driver starts the generator without
  `cwd` (`profiling/0820_phaseD_spad_vs_cache/run_sweep.py:251`), so it only
  works when launched from the root.
- Conda env names disagree: `base` in most usage strings, `cosa_snn` in
  `tests/test_stream_flag.sh:11,20`; 0820 tests note "this machine has no conda"
  and use `$PYTHON`. `profiling/0831_all_layer_streams/gen_streams.py:13-15` says `conda run` corrupts binary
  stdout, but `test_stream_flag.sh:11` redirects `conda run` stdout.
- Gurobi: required for every solve, never given `Threads`/`Seed`
  (`src/mip_solver/solve.py:82-87`), so parallel solving oversubscribes cores;
  `solve.py:169-175` documents a long-lived-worker bug worked around by dispose.
- Core counts: default 16 workers in `0831_l2_prefetch/run_sweep.py`,
  `0903_l1_8k`, `0907_*` (`workers = ... else 16`, e.g. `0907_linesize/run_sweep.py:184`);
  `generate_weight_traces.py:257` uses Linux-only `os.sched_getaffinity`.
- 16 nodes hardcoded: `N_NODES = 16` in `run_stage3.py` and `run_compare.py`
  (used to divide `count_cycles`).

### 3.5 Scattered config literals

- Arch-to-YAML map hardcoded (`scripts/solve_schedules.py:34-44`), inst16 path
  built by string (`scripts/solve_inst16_subset.py:48`, `solve_31.py`).
- Layer lists retyped: `scripts/solve_inst16_subset.py:26`, `run_stage1.py:48`,
  `run_stage2.py` `COMBOS`, `run_stage3.py` `COMBOS`, `run_armS_stage12.py` `COMBOS`,
  `gen_streams.sh:20-24`, `0820` grids, tags `["V8","V9","R9","R16"]` in 6+ files.
- Combo tag `noc2MiB_node32kb` retyped in `run_stage2.py`, `run_stage3.py`,
  `0831_all_layer_streams/gen_weight_traces.py`, `run_compare.py`.
- Scoring weights 0.1/1.0/10.0 in four files (3.2).

### 3.6 Inconsistent conventions and wrong comments

- dtype: `src/archmodels/trace.py:6,53` say "binary float32"; `meta.json`
  says uint8 and all bridges cast to uint8 (`src/archmodels/loas/native_bridge.py:102`).
- `src/parsers/bitwidths.py:61` docstring "BW_VMEM Default 16" vs `_DEFAULT_BW_VMEM = 32` at :34.
- Dataflow comments vs values: `configs/dataflow/prosperity.yaml` "128 output
  columns" but `COUT: {spatial: 8}`; `spinalflow.yaml` "128-PE array" with
  `{spatial: 8}`; `src/archmodels/loas/__init__.py` "COUT node-level spatial
  capacity 16" while `configs/dataflow/loas.yaml` has `{spatial: 4}`.
- `src/mip_solver/objectives/traffic/spatial.py:5-6`: "S[1] = 1024" and file
  name `constraints_spatial.py` (now `constraints/spatial.py`).
- Default trace-dir order differs: `solve_schedules.py:33` vs `generate_weight_traces.py:58`.
- `profiling/0907_assoc/run_sweep.py` docstring says `{32,16}` / "eight points",
  but `assocs_for` :65 adds fully associative -> 12 points.
- `profiling/0831_l2_prefetch/run_sweep.py` docstring "three arms", `GRID` has 4.
- `profiling/0831_reuse_distance/run_belady.py` docstring "five arms", `ARMS` :45 has 6.
- `profiling/0907_index_policy/make_pages.py` docstring "six of the twelve arms";
  its `run_sweep.py` has 6 arms. The stage name says "index" but sweeps replacement policy.
- `--n-samples` conflict check uses the default as sentinel
  (`scripts/generate_weight_traces.py:378`), so `--n-samples 100 --sample-count 5` passes.
- Mode 2 (`--all-layers`) ignores `--combo-tag` (`_regenerate_layer` :195-198).

### 3.7 Tracked outputs and build products

- No `__pycache__`/`.pyc` tracked; native binaries (`<arch>gen`, `eventsim`,
  `wcache_run/sweep`) are untracked builds present on this disk.
- `profiling/0823_stagewise_verify` tracks 312 MB, mostly 20 single-node
  `sample_*.json.gz` (10-27 MB each) under `stage3_nocsim/outputs/weight_traces_single_node/`.
- Also tracked: `dump/` (~27 MB), `survey-output/`, a 5.5 MB PDF at repo
  root, `input_trace/loas` (13.6 MB, though `.gitignore` lists `input_trace/`),
  0728 per-layer CSVs, 0820 result CSVs, HTML artifacts.
- `profiling/0831_all_layer_streams/streams/` is 16 GB untracked on disk;
  `__pycache__/` dirs exist (ignored).

### 3.8 Stale references (to removed or renamed things)

- `scripts/sweep_archmodel_layers.py` (`src/tracegen.py:3`),
  `scripts/generate_weight_traces_canonical100.py` (`src/tracegen.py:310`,
  `src/archmodels/gustavsnn/native_bridge.py:96`), `configs/sampling/sample_indices.json`
  (`src/tracegen.py:671,677`), `tracegen.reconstruct_samples_for_schedule`
  (all 5 bridges, e.g. `src/archmodels/loas/native_bridge.py:82`),
  `archmodels.gustavsnn.model` (`src/archmodels/gustavsnn/native_bridge.py:108`),
  `reconstruct.py/cycles.py/address.py` in every `src/archmodels/<arch>/__init__.py`
  and `<Arch>Gen.h` header, `configs/workloads/generated/` (`src/archmodels/trace.py`
  module docstring), `sweep_weights.py`/`run_full_sweep.py` (`src/mip_solver/solve.py:266,285`,
  `src/tracegen.py:85`), `model/fixed_schedule.py` (`constraints/node_capacity.py` docstring): none exist.
- `tests/sweep_cli.sh` cited in `profiling/0820_phaseD_spad_vs_cache/run_sweep.py:198,226`;
  the file is `src/wcache/native/tests/sweep_cli.sh`.
- `wcache/stream_format.h` (`src/tracegen.py:490`): actual path `src/wcache/native/include/wcache/stream_format.h`.
- Line citations that no longer match: `wcts_excerpt.py` docstring cites
  `write_stream_header:397, write_tile_frame:436, write_stream_trailer:466`
  (now :522, :561, :591); `verify_reconstruction.py` cites `LoASGen.h:66-119`
  (file has 107 lines; function at :63-107).
- Missing producers: `0823_stagewise_verify/stage4_wcache/outputs/w5{b..g}_*.csv`
  have no generating script in the stage; `0903_l1_8k/run_sweep.py:4` refers to
  stage `0903_l1_pf_fix`, which is not in `profiling/`; 0728 CSVs have no in-stage producer.

---------------------------------------------------------------------------

## 4. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

What a fresh machine needs:

- Python >= 3.9 (`tuple[...]` annotation without `from __future__` in
  `src/parsers/arch.py:283`); `__pycache__` files here are cpython-312.
  Packages from imports: `numpy`, `pyyaml`, `gurobipy` (docstring mentions
  13.0.2 in `solve_all_layers.py`), `matplotlib` (only `scripts/tmp/analyze_multinode_schedules.py`).
  `requirements.txt` exists but was not read (extension rule).
- A Gurobi license (`GRB_LICENSE_FILE`; Delta token server path in
  `solve_all_layers.py:21`) for any solve. Not needed to reuse cached schedules.
- g++ with C++17 and `make` for: 5 arch generators (`src/archmodels/<arch>/Makefile`),
  `src/nocsim/eventsim`, `src/cachesim` (3 binaries), `src/wcache/native`
  (`MODE=release lib apps` for `build/release/`, which every 0823+ driver hardcodes).
  `reuse_tool` has no build file.
- Run from the repo root (3.4); `PYTHONPATH=src` for `python -m nocsim.sim`.

Inputs missing from the repo:

- Full captures `vgg16_T4_all`, `resnet19_T4_all` (10,000 samples, 25.8 GB per
  `subset_input_traces.py` docstring) referenced by `solve_inst16_subset.py:26`,
  all 0820 grids, `run_stage1.py:48`, `0803` paths, `solve_all_layers.py:49`,
  `audit_density.py:9`, `test_stream_flag.sh`. Only `_n5` (5 samples) is stored.
- Default `--n-samples 100` draws indices from `range(10000)`
  (`src/tracegen.py:674`), which is out of range for the stored B=5 arrays; use
  `--sample-start/--sample-count` with indices 0-4. Saved `sample_idx` is then
  the array index, not the CIFAR-10 index in `meta.json["subset"]`.
- No `outputs/` tree: no cached schedules for `outputs/schedules/{loas,..}`,
  `inst16`, `multinode`, `multinode_sweep/<combo>`, nor
  `outputs/schedules/multinode_sweep/classification.csv` (0803 build).
  Tracked schedules exist only for 4 loas layers under 0823 (16-core and single-node).
- Untracked derived data later stages read: `profiling/0831_all_layer_streams/{schedules,streams,weight_traces,outputs}`,
  `profiling/0823_stagewise_verify/stage4_wcache/inputs/streams` (absent),
  `.../stage2_weight_trace/outputs/weight_traces` and `inputs/input_trace` (absent;
  tests `test_step_cycles.py`, `test_combine_cycles_table.py` skip without them).
- Only LoAS-captured spike traces exist; PTB/SpinalFlow/Prosperity/GustavSNN
  models replay the same spikes. Workloads referenced but absent:
  `configs/workloads/generated/{vgg16,resnet19}/T4`, `vgg16_T4_B1` (example in
  `src/archmodels/trace.py:39` docstring).

Scripts that hardcode paths: listed in 3.3; the minimum to fix for Delta is a
single `TRACE_ROOT`/`OUTPUT_ROOT`/`PYTHON` setting replacing those constants.

---------------------------------------------------------------------------

## 5. Open questions the code alone cannot answer

1. Which code produced the 0728 CSVs and the 0823 `w5b`..`w5g` CSVs?
2. ResNet `*_shortcut_0` layers are given KH=KW=3, PAD=1 (`src/archmodels/trace.py:27-29`);
   are they really 3x3 in the captured model, and is "next layer's CIN" the
   right COUT around shortcut layers (e.g. `layer_02 conv2` -> `layer_03 shortcut`)?
3. What do `run_sweep.slurm` (0803, 0820) and `requirements.txt` contain (not read)?
4. How is `profiling/0831_reuse_distance/reuse_tool` built?
5. Is the mapspace YAML meant to constrain the MIP, or is it legacy?
6. Are Gurobi solutions deterministic across machines/versions without `Seed`/`Threads`
   (the `--check` in `solve_all_layers.py` tests only 4 layers)?
7. Does `tests/test_stream_flag.sh` suffer the `conda run` stdout corruption
   that `gen_streams.py` describes?
8. Should saved traces carry the CIFAR-10 index from `meta["subset"]` instead of the 0-4 array index?
9. Is `configs/arch/ptb.yaml` (marked "RECONSTRUCTED 2026-07-20") equal to the
   one that produced any cached PTB schedule?
10. Which of the 13 stages are still meant to be reproduced, versus kept as history?
