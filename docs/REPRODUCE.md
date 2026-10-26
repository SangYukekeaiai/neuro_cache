# Reproducing the demo and adding a benchmark

Everything here is what the code reads; the atlas in docs/atlas/ explains the code.

## Environment

- Python 3.12 with the pins in requirements.txt (numpy, PyYAML; gurobipy and matplotlib
  are optional). Either a venv (`python3 -m venv .venv && .venv/bin/pip install numpy PyYAML pytest`)
  or the conda env `$CONDA_ENV` (default `cosa_snn`). Shell scripts take the settings from
  `root=<repo>; . "$root/scripts/env.sh"`, which exports `NEURO_CACHE_DATA` (data kept outside
  git, default `<repo>/data`; Python reads it through `util.data_root()`) and `CONDA_ENV`.
- Gurobi (gurobipy 13.0.2 plus a license, `GRB_LICENSE_FILE` for a token server) is needed only
  to solve a schedule: scripts/solve_schedules.py, scripts/solve_inst16_subset.py,
  profiling/0831_all_layer_streams/solve_all_layers.py and `python -m mip_solver`. The demo and
  scripts/profile_all_layers.py solve only layers that have no tracked schedule; the four demo
  layers (V8, V9, R9, R16) are tracked under
  profiling/0823_stagewise_verify/stage2_weight_trace/inputs/schedules/, so they need no Gurobi.
- Builds (GNU make, C++17, no third-party libraries):
  `make -C src/wcache/native MODE=release apps` (wcache_run, wcache_sweep),
  `make -C src/wcache/native test` (316 compile cases, 22 test binaries),
  `make -C src/nocsim/eventsim` (eventsim), `make -C src/archmodels/<bench>` (the `<bench>gen`
  replay binary; the demo runs these three makes itself).

## make demo

`make demo` (or `python scripts/demo.py [--bench loas] [--layers V8 R9 ...] [--jobs N]`) checks
the inputs, builds, generates the weight traces and WCTS v2 streams of 4 layers x 5 samples, runs
`python -m nocsim.sim --simulate` and `wcache_sweep` over the 48-config 0823 khkw grid, and
writes under `$NEURO_CACHE_DATA/demo/<bench>/` (minutes; the largest single command peaks near
14 GB RSS, so --jobs stays at min(8, cpu_count) by default):

- results.csv, 960 rows, columns `trace_dir, layer, sample, config, layout, line_size_bytes,
  l2_size_bytes, l2_banks, prefetch_policy, prefetch_distance, nocsim_total_cycles,
  wcache_total_cycles, speedup_vs_nocsim` (nocsim cycles / wcache cycles).
- summary.md: geomean speedup per config and the argv of every command that ran.
- streams/, weight_traces/, nocsim/, layers/, grid/: the intermediate files.

`python scripts/demo.py --verify-baseline` compares results.csv with .baseline/after (mismatches
must be 0). `python scripts/wcache_baseline.py run` then `compare .baseline/after/wcache/khkw_sweep.csv
$NEURO_CACHE_DATA/neuro_cache_outputs/wcache_baseline/khkw_sweep.csv` checks the wcache side alone.

## Input-trace contract

`python scripts/demo.py --check-bench <bench>` (or a directory path) checks all of this and lists
what is missing; exit 0 means complete.

- Layout: `input_trace/<bench>/<trace_dir>/meta.json` plus one `<layer>.npy` per layer, e.g.
  input_trace/loas/vgg16_T4_n5/. `<bench>` is the archmodel name (loas, ptb, spinalflow,
  prosperity, gustavsnn); `<trace_dir>` is `<network>_T<T>_n<N>` for an N-sample subset and
  `<network>_T<T>_all` for a full capture.
- meta.json fields the code reads: `layers`, an ordered dict layer name -> `[T, B, Cin, Hin, Win]`;
  `layer_params`, a dict with the same layer names -> `{"cout", "kernel", "stride"}` (output
  channels, square kernel size, stride; positive ints, every layer needs all three;
  `archmodels.trace.layer_params`, and `build_workload_from_trace` takes COUT from it); `n_samples`, equal to B
  (scripts/subset_input_traces.py); `dtype`, "uint8". Provenance fields (`arch`, `timestep`,
  `batch_size`, `dataset`, `captured_at`, and `subset` with `of`, `n`, `seed`, `sample_indices`)
  are written by the capture and the subset script and not read by the pipeline.
- `<layer>.npy`: uint8 0/1 spikes, shape exactly `[T, B, Cin, Hin, Win]` as meta.json declares
  (`archmodels.trace.load_layer_trace` refuses any other shape). The arch models replay only
  3x3 stride-1 PAD=1 convolutions, so `archmodels.trace.valid_layer_names` leaves out every
  layer whose `kernel` is not 3, whose `stride` is not 1, or whose Hin or Win is below 1, and
  `exclusion_reason` says why; `--check-bench` lists each excluded layer with its reason. In
  input_trace/loas/resnet19_T4_n5 that excludes the stride-2 `layerS_0_conv1` and the 1x1
  stride-2 `layerS_0_shortcut_0` layers (6 of 19).
- Tracked schedules: `tracegen.check_schedule_matches_trace` refuses a schedule whose
  `workload.problem` differs from the one meta.json now gives (scripts/generate_weight_traces.py
  and scripts/demo.py call it); re-solve such a schedule with `scripts/solve_schedules.py --force`.
- Layer names: `layer_NN_<anything>`; the `V<n>`/`R<n>` tags of profiling/common.py take n from
  `NN`, and the V/R prefix from the trace dir names in `common.WORKLOADS`.
- Subset: `python scripts/subset_input_traces.py --src $NEURO_CACHE_DATA/neuro_cache_trace/input_trace/<bench>
  --dest input_trace/<bench> --captures <network>_T4_all ... --n 5 --seed 0` picks the same N
  sample indices for every layer of a capture, writes `<network>_T4_n5/`, and rewrites B and
  `n_samples`. A 500-sample subset is the same command with `--n 500` (5 samples of loas are
  13.6 MB, so expect about 1.4 GB; keep it under `$NEURO_CACHE_DATA`, since .gitignore tracks
  only input_trace/loas/) and schedules solved for the `_n500` trace dir name, or copies of the
  `_n5` ones with `trace_dir` rewritten (the schedule depends on the shape only).

## Adding a benchmark

1. Capture the traces into `$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/<bench>/<network>_T4_all/`
   in the layout above, then cut the subset with scripts/subset_input_traces.py.
2. Make sure the code knows `<bench>`: `archmodels.ARCH_NATIVE_BRIDGES` names its native bridge,
   src/archmodels/<bench>/ holds main.cpp, the generator header, native_bridge.py and a Makefile,
   and configs/arch/<bench>.yaml and configs/dataflow/<bench>.yaml exist (scripts/solve_schedules.py
   DEFAULT_ARCH_YAML / DEFAULT_DATAFLOW_YAML). configs/workloads/ holds only the stand-alone
   solver CLI's sample layer; layer shapes come from meta.json.
3. `python scripts/demo.py --check-bench <bench>` until it reports 0 problems.
4. Solve the schedules (Gurobi): `python scripts/solve_schedules.py --archs <bench>
   --trace-root input_trace/<bench> --trace-dirs <network>_T4_n5 --cache-dir outputs/schedules`.
   The demo does this itself when gurobipy imports and stops naming the missing files otherwise.
5. For the nocsim side, add the benchmark's nocsim arch YAML to `NOCSIM_ARCH` in scripts/demo.py
   (only loas has one, profiling/0823_stagewise_verify/stage3_nocsim/inputs/arch/).
6. `python scripts/demo.py --bench <bench> --layers <trace_dir>/<layer> ...`.

## Files to copy from Delta for the other benchmarks

The code in src/archmodels/{gustavsnn,prosperity,ptb,spinalflow} and configs/{arch,dataflow}/
is tracked; what Delta holds and this repo does not is data, expected at these relative paths:

| What | Expected path |
|---|---|
| Full captures (10,000 samples) | `$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/<bench>/<network>_T4_all/{meta.json,layer_*.npy}` |
| 5-sample subsets | `input_trace/<bench>/<network>_T4_n5/` (cut locally from the captures) |
| Solved schedules | `outputs/schedules/<bench>/<trace_dir>/<layer>.json` (plus `summary.csv`) |
| 16-core schedules | `outputs/schedules/inst16/<bench>/<trace_dir>/<layer>.json` (scripts/solve_inst16_subset.py) |
| Weight traces | `$NEURO_CACHE_DATA/neuro_cache_outputs/weight_traces/<bench>/[<combo>/]<trace_dir>/<layer>/sample_NNNNN.json.gz` |

The loas captures are the only ones any tracked schedule or profiling stage refers to; the four
other archmodels have never been run in this checkout, so their first run also needs the
schedules solved (step 4 above).

## Regenerating the 0831 all-layer streams

profiling/0831_all_layer_streams/streams/ (31 layers x 5 samples of WCTS) was written in version
1, which every reader now refuses, and its schedules/ directory is untracked. Once the full loas
captures are under `$NEURO_CACHE_DATA/neuro_cache_trace/input_trace/loas/` (the solver reads
their meta.json for the shapes; no spike data):

    python profiling/0831_all_layer_streams/solve_all_layers.py --check   # Gurobi; 4-layer gate
    python profiling/0831_all_layer_streams/solve_all_layers.py           # 31 schedules
    python profiling/0831_all_layer_streams/gen_streams.py --workers 16   # v2 streams + byte gate

gen_streams.py reads only input_trace/loas/*_n5 and the stage's schedules/, so with the
schedules in place it needs neither the captures nor Gurobi. The streams are 16 GB and the
directory is gitignored (on Delta it was a symlink into scratch), so point it at
`$NEURO_CACHE_DATA` first.

## Per-layer profiling on Delta

scripts/profile_all_layers.py runs one layer per Slurm array task (scripts/slurm/profile_all_layers.slurm)
and writes `$NEURO_CACHE_DATA/profiling/<bench>/layers/<trace_dir>/<layer>.csv`, then `--merge`
joins them. The Slurm file has not been submitted on Delta yet: it is verified only by
`--dry-run` and by one array task run locally on the 5-sample loas subset; its header lists the
fields to confirm at the first submission.
