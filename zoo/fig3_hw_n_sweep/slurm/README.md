# Slurm array harness

Run these commands from the repository root with the campaign environment:

```bash
PY=/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python
export PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm
```

Build a deterministic manifest from the active `gen_inputs.py`. `--num-shards`
is an upper bound on the array length and `--cases-per-shard` bounds each task;
the harness trims excess requested shards, rejects more than 250 required shards,
and rejects a batch group split across tasks. `--batch-samples` keeps all 100
samples for each `(layer, N)` together.

```bash
$PY zoo/fig3_hw_n_sweep/slurm/shard_cases.py \
  --output-dir zoo/fig3_hw_n_sweep/outputs/slurm/cases \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/runs \
  --batch-samples --num-shards 250 --cases-per-shard 100 --cpus 4
sbatch --partition=normal --cpus-per-task=4 --array=0-64%65 \
  zoo/fig3_hw_n_sweep/slurm/run_array.sbatch \
  --case-dir zoo/fig3_hw_n_sweep/outputs/slurm/cases \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/runs \
  --batch-samples
$PY zoo/fig3_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig3_hw_n_sweep/outputs/slurm/cases/manifest.json \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/runs \
  --output-dir zoo/fig3_hw_n_sweep/outputs
```

Each task writes `shard_XXXX/results_XXXX.csv`, its commands, Slurm log, and
per-case native logs below its own shard directory. The batch generator writes
one weight-trace log per `(layer, N)` and `run.py` runs nocsim once per sample.
The merge checks exact once-only coverage against the manifest and reuses
`run.py`'s summary logic. The generated `--output/--error` paths are under the
shard root, not the repository root.

To list incomplete cases and create a replacement manifest/array:

```bash
$PY zoo/fig3_hw_n_sweep/slurm/rerun_missing.py \
  --manifest zoo/fig3_hw_n_sweep/outputs/slurm/cases/manifest.json \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/runs \
  --output-dir zoo/fig3_hw_n_sweep/outputs/slurm/rerun-cases \
  --new-shard-root zoo/fig3_hw_n_sweep/outputs/slurm/rerun-runs
```

For a small validation manifest, use `--batch-samples --limit 2
--num-shards 1 --cases-per-shard 100` (or filter to one `(layer, N)` group);
run the emitted array, merge it, and compare its `results.csv` with plain
`run.py --case-file <manifest> --no-summary`.
