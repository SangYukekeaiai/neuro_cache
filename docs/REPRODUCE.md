# Reproducing results

Every command runs from the repo root with the venv active. Each claim cites the code
it comes from; `docs/atlas/README.md` explains the code itself.

## Environment

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make build
```

- `pip install -e .` installs the packages under `src/` and `src/util.py`, so
  `python -m <module>` works from any directory (`pyproject.toml:10-15`).
- `make build` compiles `cachesim_run` and `cachesim_sweep`, the NoC event simulator
  `src/nocsim/eventsim/eventsim`, and the loas replay binary (`Makefile:5-8`).
  `scripts/pipeline.py` runs the same makes itself, for the benchmark it runs
  (`scripts/pipeline.py:333-337`), and `python -m cachesim sweep|run` builds the cache
  simulator when its binary is missing (`src/cachesim/cli.py:20-25`).
- Gurobi (`gurobipy` in `requirements.txt:1`) is needed only to solve a schedule. Set
  `GRB_LICENSE_FILE` to the path of your license file; never copy the file into the repo.
  `solve-trace` imports gurobipy only when it has a layer to solve
  (`src/snn_scheduler/cli.py:18-19`) and skips schedules already in `--cache-dir`
  (`src/snn_scheduler/cli.py:222-225`). The pipeline needs it only when a requested layer
  has no schedule in `configs/schedules/` (`scripts/pipeline.py:322-325`).
- `NEURO_CACHE_DATA` is the root for data kept outside git, default `data/`
  (`src/util.py:15-24`): the pipeline writes to `$NEURO_CACHE_DATA/demo/<bench>` by
  default (`scripts/pipeline.py:312-313`), and the full captures for
  `scripts/subset_input_traces.py` live under it (`scripts/subset_input_traces.py:44`).

## Input contract

One directory per benchmark and capture: `input_trace/<bench>/<trace_dir>/meta.json` plus
one `<layer>.npy` per layer (`scripts/pipeline.py:40-41`), e.g.
`input_trace/loas/resnet19_T4_n5/`.

- `meta.json` `layers`: layer name to the input shape `[T, B, Cin, Hin, Win]`, five
  positive ints (`scripts/pipeline.py:201-213`).
- `meta.json` `layer_params`: the same layer names to `{"cout", "kernel", "stride"}`,
  positive ints, required for every layer (`src/weight_trace_gen/trace.py:84-105`).
- `meta.json` `n_samples`, equal to B, and `dtype`, `"uint8"`
  (`scripts/pipeline.py:205-206`, `scripts/pipeline.py:223-229`).
- `<layer>.npy`: uint8 0/1 spikes whose shape is exactly the declared
  `[T, B, Cin, Hin, Win]` (`src/weight_trace_gen/trace.py:74-80`,
  `scripts/pipeline.py:218-222`).
- Only 3x3 stride-1 layers whose output is at least 1x1 with padding 1 can be replayed;
  every other layer is left out (`src/weight_trace_gen/trace.py:108-129`). The workload a
  schedule is solved for is KH=KW=3, CIN=Cin, COUT=`cout`, HO=Hin, WO=Win, T=T
  (`src/weight_trace_gen/trace.py:152-162`).
- A tracked schedule must have been solved for that workload, or the pipeline stops and
  names it (`src/snn_scheduler/artifact.py:115-137`, `scripts/pipeline.py:290-297`).
- Tags: layer `layer_NN_*` of `vgg16_T4_n5` is `V<NN>` and of `resnet19_T4_n5` is
  `R<NN>` (`scripts/pipeline.py:49`, `scripts/pipeline.py:105-114`).

`python scripts/pipeline.py --check-bench loas` checks all of this for one benchmark (a
name under `input_trace/` or a directory path), lists the excluded layers with the reason,
and exits 0 when it finds no problem (`scripts/pipeline.py:170-249`,
`scripts/pipeline.py:468-471`).

A subset of N samples is cut from a full capture with the same sample indices for every
layer, into `<capture minus _all>_n<N>/`, with B and `n_samples` rewritten
(`scripts/subset_input_traces.py:49-93`, `scripts/subset_input_traces.py:119`):

```
python scripts/subset_input_traces.py --src <captures dir> --dest <dir> --captures <network>_T4_all --n 5 --seed 0
```

## The four modules, each alone

Running example R9: `resnet19_T4_n5/layer_09_layer2_0_conv2`, sample 0, benchmark loas.
`OUT` is any directory; `data/demo/loas` is the pipeline's default output. First:

```
OUT=data/demo/loas; mkdir -p $OUT/streams/resnet19_T4_n5 $OUT/layers/resnet19_T4_n5 $OUT/cachesim
```

### 1. SNN scheduler: `python -m snn_scheduler solve-trace`

```
python -m snn_scheduler solve-trace --arch loas --trace-root input_trace/loas --trace-dirs resnet19_T4_n5 --layers layer_09_layer2_0_conv2 --cache-dir $OUT/schedules
```

- Inputs: `input_trace/loas/resnet19_T4_n5/meta.json` (`src/snn_scheduler/cli.py:203-206`);
  the hardware config, default `configs/arch/loas_inst16_node32kb.yaml` for loas and
  `configs/arch/<arch>.yaml` otherwise (`src/snn_scheduler/cli.py:183-189`); the node
  mapspace, default `configs/node_mapspace/<arch>.yaml` (`src/snn_scheduler/cli.py:198`);
  Gurobi.
- Outputs: `$OUT/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json` with keys
  `arch, trace_dir, layer_name, workload, result, dram_num_steps, mode`
  (`src/snn_scheduler/artifact.py:26-36`, `src/snn_scheduler/artifact.py:101-104`), and
  `$OUT/schedules/summary.csv` with `arch, trace_dir, layer, status, dram_num_steps, error`
  (`src/snn_scheduler/cli.py:242-248`).
- Without `--layers` it solves every replayable layer; each `--layers` name applies to the
  trace dirs whose `meta.json` has it, and a name in none of them exits 2
  (`src/snn_scheduler/cli.py:207-218`). Any infeasible or failed layer exits 1
  (`src/snn_scheduler/cli.py:250-255`).
- `solve` and `enumerate` solve one hand-written layer YAML instead, default
  `configs/workloads/sample_snn_layer.yaml` (`src/snn_scheduler/cli.py:22-25`).

### 2. Weight-trace generator: `python -m weight_trace_gen gen`

```
python -m weight_trace_gen gen --arch loas --trace-root input_trace/loas --trace-dir resnet19_T4_n5 --layer layer_09_layer2_0_conv2 --schedule-cache configs/schedules --sample-start 0 --sample-count 1 --out-dir $OUT/weight_traces
python -m weight_trace_gen gen --arch loas --trace-root input_trace/loas --trace-dir resnet19_T4_n5 --layer layer_09_layer2_0_conv2 --schedule-cache configs/schedules --sample-start 0 --sample-count 1 --stream > $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts
```

- Inputs: the schedule `<schedule-cache>/<arch>/<trace_dir>/<layer>.json`
  (`src/weight_trace_gen/cli.py:130`), `meta.json` and `<layer>.npy`, and the native replay
  binary built from `src/weight_trace_gen/loas/` through the bridge named in
  `src/weight_trace_gen/__init__.py:30-36`.
- Outputs: the per-step cycle counts
  `$OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz`
  (`src/weight_trace_gen/cli.py:140-142`), and with `--stream` one WCTS stream (magic
  `WCTRACE1`, `src/cachesim/stream.py:42`) on stdout for exactly one sample
  (`src/weight_trace_gen/cli.py:301-309`). `--dump-trace PATH` writes the same stream to a
  file, which is how the pipeline calls it (`scripts/pipeline.py:349-350`).

### 3. NoC simulator: `python -m nocsim`

nocsim reads the layer as YAML; the pipeline writes it from the schedule's `workload` block
(`scripts/pipeline.py:356-358`). By hand:

```
python -c 'import json, sys, yaml; yaml.safe_dump(json.load(open(sys.argv[1]))["workload"], open(sys.argv[2], "w"), sort_keys=False)' configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json $OUT/layers/resnet19_T4_n5/layer_09_layer2_0_conv2.yaml
python -m nocsim --schedule configs/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json --layer $OUT/layers/resnet19_T4_n5/layer_09_layer2_0_conv2.yaml --arch configs/arch/loas_inst16_node32kb.yaml --weight-trace $OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz --out $OUT/nocsim/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.csv --simulate
```

- Inputs: schedule JSON, layer YAML, arch YAML, one sample's step cycles
  (`src/nocsim/sim.py:266-310`), and with `--simulate` the binary
  `src/nocsim/eventsim/eventsim` (`src/nocsim/sim.py:195`).
- Outputs: the transaction CSV at `--out` (`src/nocsim/sim.py:342-346`) and, on stdout,
  `total_cycles`, `unicast_cycles`, `multicast_cycles`, `count_cycles`
  (`src/nocsim/sim.py:392-396`). The pipeline reads `total_cycles`
  (`scripts/pipeline.py:378-383`).

### 4. Cache simulator: `python -m cachesim grid | sweep | run`

```
python -m cachesim grid --out $OUT/grid
python -m cachesim sweep --config-grid $OUT/grid/khkw_0.json --trace $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts --out $OUT/cachesim/R9_s0_khkw_0.csv
```

- `grid` crosses `configs/cache/base.json` with the axes in `configs/cache/khkw_sweep.json`
  (line size x L2 banks x prefetch, 3 x 4 x 4 = 48 configs,
  `configs/cache/khkw_sweep.json:2-4`, `src/cachesim/grid.py:20-36`). It writes one file
  per `cin_block` = line bytes / (`cout_block` x `weight_bytes`), because one sweep uses
  one mapper: `khkw_0.json`, `khkw_1.json`, `khkw_2.json` for 16, 32 and 64-byte lines
  (`src/cachesim/grid.py:26`, `src/cachesim/grid.py:39-53`). `--base` and `--sweep` take
  other files (`src/cachesim/cli.py:38-46`).
- `sweep` and `run` pass every later argument to the native `cachesim_sweep` /
  `cachesim_run` (`src/cachesim/cli.py:15-33`); `python -m cachesim sweep --help` prints
  the native usage. The `--out` directory must exist.
- Output: a CSV with one row per config, including `total_cycles`, `l1_hits`, `l2_hits`,
  `dram_bytes` (`src/cachesim/native/src/stats.cpp:215-217`).

## End to end: `scripts/pipeline.py`

For one benchmark it checks the inputs, takes the schedules from `configs/schedules/` and
solves the missing ones into `<out>/schedules/` with one `solve-trace` call, builds the
native tools, generates step cycles and streams, then runs nocsim and the cache sweep per
(layer, sample) and joins them (`scripts/pipeline.py:316-401`). Steps run in parallel
across commands under `--jobs` (`scripts/pipeline.py:99-102`).

| Flag | Default | Meaning |
|---|---|---|
| `--bench` | `loas` | benchmark under `input_trace/` (`scripts/pipeline.py:453`) |
| `--layers` | `V8 V9 R9 R16` | tags, `trace_dir/layer`, or `all` for every replayable layer of `vgg16_T4_n5` and `resnet19_T4_n5` (`scripts/pipeline.py:47`, `scripts/pipeline.py:117-135`) |
| `--sample-start`, `--sample-count` | `0`, `5` | samples run per layer (`scripts/pipeline.py:457-458`) |
| `--out` | `$NEURO_CACHE_DATA/demo/<bench>` | output directory (`scripts/pipeline.py:312-313`) |
| `--grid` | the 48-config khkw grid | a JSON array of cache configs (`scripts/pipeline.py:301-309`) |
| `--jobs` | `min(8, cpu count)` | parallel commands (`scripts/pipeline.py:57`) |
| `--verify-baseline [DIR]` | `.baseline/after` | only compare `<out>/results.csv` with DIR (`scripts/pipeline.py:463-464`) |
| `--check-bench BENCH` | | only check the input contract (`scripts/pipeline.py:465-471`) |

```
make demo
python scripts/pipeline.py --layers R9 --sample-count 1 --out data/demo/R9
python scripts/pipeline.py --layers all --sample-count 1 --out data/demo/all_s1
python scripts/pipeline.py --verify-baseline --out data/demo/R9
```

- `make demo` is `python scripts/pipeline.py` with the defaults above (`Makefile:10-11`).
- `--layers all` needs Gurobi for every layer without a tracked schedule.
- `--verify-baseline` compares `wcache_total_cycles` with `DIR/wcache/khkw_sweep.csv` and
  `nocsim_total_cycles` with `DIR/nocsim/stage3_results.csv`, prints each mismatch, and
  exits 0 only when every row is in the reference and matches
  (`scripts/pipeline.py:422-448`).

Outputs under `<out>`: `results.csv`, `summary.md` (geomean speedup per config and every
command run, `scripts/pipeline.py:404-419`), and the intermediate `schedules/` (only when
it solved), `weight_traces/`, `streams/`, `layers/`, `nocsim/`, `grid/`
(`scripts/pipeline.py:273`, `scripts/pipeline.py:342-371`).

`results.csv` has one row per (layer, sample, config) (`scripts/pipeline.py:385-398`):
`trace_dir, layer, sample, config, layout, line_size_bytes, l2_size_bytes, l2_banks,
prefetch_policy, prefetch_distance, nocsim_total_cycles, wcache_total_cycles,
speedup_vs_nocsim`, where `speedup_vs_nocsim` is nocsim cycles / cache-simulator cycles
(`scripts/pipeline.py:51-52`, `scripts/pipeline.py:60-79`).

## Adding a benchmark

1. Native replay model: `src/weight_trace_gen/<bench>/` with `main.cpp`, the generator
   header, `native_bridge.py` and a `Makefile`, as for the five existing ones (loas, ptb,
   spinalflow, prosperity, gustavsnn), and an entry in `ARCH_NATIVE_BRIDGES`
   (`src/weight_trace_gen/__init__.py:30-36`), which also sets the `--arch` choices
   (`src/snn_scheduler/cli.py:103`).
2. `configs/arch/<bench>.yaml` and `configs/node_mapspace/<bench>.yaml`
   (`scripts/pipeline.py:179-183`, `src/snn_scheduler/cli.py:188-198`).
3. The nocsim arch: an entry in `NOCSIM_ARCH`; only loas has one
   (`scripts/pipeline.py:45`).
4. Traces under `input_trace/<bench>/<trace_dir>/` as in the input contract, then
   `python scripts/pipeline.py --check-bench <bench>` until it reports 0 problems.
5. Run it: `python scripts/pipeline.py --bench <bench> --layers <trace_dir>/<layer> --out <dir>`.
   Tags (`V8`, `R9`) exist only for `vgg16_T4_n5` and `resnet19_T4_n5`
   (`scripts/pipeline.py:49`). Missing schedules are solved into `<out>/schedules/`
   (`scripts/pipeline.py:270-289`); copy them to `configs/schedules/<bench>/<trace_dir>/`
   to track them (`scripts/pipeline.py:42-43`).

## Writing a sweep script

Another cache grid needs no new code: pass a JSON array of configs with `--grid`; configs
with different `cin_block` run as separate sweeps (`scripts/pipeline.py:368-371`). For
example, only the 64-byte lines of the khkw grid:

```
python scripts/pipeline.py --layers R9 --sample-count 1 --grid data/demo/R9/grid/khkw_2.json --out data/demo/R9_64B
```

Anything else (other layers, archs, or axes) is a new file under `scripts/`. Run as
`python scripts/<name>.py`, it can `import pipeline` and reuse `run_all`, `join_results`,
`load_grid` and `resolve_layers` (`scripts/pipeline.py:68-135`, `scripts/pipeline.py:301-309`),
or call the four CLIs directly. A minimal one, sweeping the L2 size on one stream:

```python
import json, pathlib, sys
from cachesim.grid import load_base
from pipeline import run_all

trace, out = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
grid = [dict(load_base(), l2_size_bytes=kb * 1024) for kb in (256, 512, 1024)]
(out / "grid.json").write_text(json.dumps(grid))
run_all([[sys.executable, "-m", "cachesim", "sweep", "--config-grid", str(out / "grid.json"),
          "--trace", str(trace), "--out", str(out / "l2_size.csv")]], [], 1)
```

`run_all` runs each command from the repo root and exits on the first failure, so pass
absolute paths (`scripts/pipeline.py:90-102`).

## Regenerating schedules

The tracked schedules are `configs/schedules/loas/<trace_dir>/<layer>.json` for V8, V9,
R9 and R16. To re-solve them (Gurobi), solve into a scratch directory with `--force`, then
copy the files into `configs/schedules/loas/<trace_dir>/`:

```
python -m snn_scheduler solve-trace --arch loas --trace-root input_trace/loas --trace-dirs vgg16_T4_n5 resnet19_T4_n5 --layers layer_08_features_27 layer_09_features_30 layer_09_layer2_0_conv2 layer_16_layer3_0_conv2 --cache-dir data/schedules --force
```

A schedule whose workload no longer matches `meta.json` is reported with the command to
re-solve it (`src/snn_scheduler/artifact.py:131-137`).
