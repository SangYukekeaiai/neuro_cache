# Weight-trace generation scripts

Run from the **project root** with the `base` conda env active
(`source ~/miniconda3/etc/profile.d/conda.sh && conda activate base`),
`PYTHONPATH=src`. Stage 1 additionally needs `GRB_LICENSE_FILE` set to a
working Gurobi license.

Two-stage pipeline, see `dump/docs/superpowers/specs/2026-07-18-weight-trace-generation-design.md`
for the full design:

```
Stage 1 (Gurobi, low concurrency)     Stage 2 (no Gurobi, embarrassingly parallel)
snn_scheduler solve-trace       -->  weight_trace_gen gen
outputs/schedules/<arch>/<trace_dir>/<layer>.json
                                       outputs/weight_traces/<arch>/<trace_dir>/<layer>/sample_NNNNN.json.gz
                                       (per-step cycles for nocsim; addresses go out via --stream)
```

## Stage 1: `python -m snn_scheduler solve-trace`

Solves every `(trace_dir, layer)` schedule of one arch once via full 13-mode
traffic enumeration (`snn_scheduler.enumerator`/`TrafficMode`), keeps the
winning mode, and persists it plus a `summary.csv`. The arch YAML defaults to
`configs/arch/loas_inst16_node32kb.yaml` for loas and `configs/arch/<arch>.yaml`
otherwise (`--arch-yaml`); the node mapspace to `configs/node_mapspace/<arch>.yaml`
(`--node-mapspace`). `--layers` limits it to the named layers.

```bash
python -m snn_scheduler solve-trace --arch loas \
  --trace-root /u/yyu9/neuro_cache_trace/input_trace/loas \
  --trace-dirs vgg16_T4_all resnet19_T4_all \
  --cache-dir outputs/schedules
```

`--force` re-solves and overwrites even if a cached schedule exists. It exits 1
when any layer is infeasible or fails.

The temporary multi-node equivalents are
`scripts/tmp/solve_multinode_schedules.py` and
`scripts/tmp/analyze_multinode_schedules.py`. They write schedules under
`outputs/schedules/multinode/` and the value-free GB/DRAM analysis under
`outputs/figures/multinode_schedule_splitting.*`.

`plan_trace_shards.py` (the Slurm-array job-list generator) and
`slurm/run_full_sweep_array.slurm` are archived to `dump/`: the array-job
sweep they supported is retired, and `dump/plan_trace_shards.py` is kept
only for reference, not meant to run against the current pipeline.

## Stage 2: `python -m weight_trace_gen gen`

Loads a Stage-1-cached schedule (no re-solving) and reconstructs samples
against it through the arch's native C++ bridge (dispatched via
`weight_trace_gen.weight_trace.reconstruct_samples`), one `.json.gz` per sample holding its
per-step cycle counts (`nocsim.step_cycles.save_step_cycles`, src/nocsim/step_cycles.py:27; no
weight addresses, which `--stream` emits as WCTS instead). Skip-existing
is on by default (`--force` to override). Two modes:

One explicit `(arch, trace_dir, layer)` combo, parallelized by chunking
samples across `--workers`:

```bash
python -m weight_trace_gen gen \
  --arch loas --trace-dir vgg16_T4_all --layer layer_01_features_3 \
  --out-dir /work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces \
  --n-samples 10000 --workers 16
```

`--all-layers`: every valid layer across `--trace-dirs` (default both)
for one arch, parallelized by task (one `(trace_dir, layer)` per worker)
in two passes -- broad coverage first, then depth:

```bash
python -m weight_trace_gen gen --arch loas --all-layers --n-samples 100 --workers 16
```

`--n-samples 100` (the default) is the fixed, reproducible canonical
subset (`weight_trace_gen.weight_trace.sample_indices`, seed 0) -- computed live from the
seed, not read from a stored file. Pass `--sample-start`/`--sample-count`
instead for an arbitrary range (single-combo mode only).

`generate_weight_traces_tile_parallel.py`, which used to chunk by tile
instead of by sample for GustavSNN's ~8000 node-tiles/sample, is
archived at `dump/scripts/`: reconstruction now runs in C++, so the
Python per-tile-loop cost it worked around no longer applies.

`visualize_dram_permutation.py` and `sweep_archmodel_layers.py` are
likewise archived at `dump/scripts/` (DRAM-permutation heatmap and
ad hoc per-layer NoC-sim checks, respectively) -- see each file's own
docstring if reviving one.
