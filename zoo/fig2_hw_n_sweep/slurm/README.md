# Slurm array harness

Run these commands from the repository root with the campaign environment:

```bash
PY=/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python
export PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm
```

Build a deterministic manifest from the active `gen_inputs.py`, which defines
the four networks `resnet19`, `vgg16`, `sdt`, and `vgg8dvs`. `--num-shards`
is an upper bound on the array length and `--cases-per-shard` bounds each task;
the harness trims excess requested shards, rejects more than 250 required shards,
and rejects a batch group split across tasks. `--batch-samples` keeps all 100
samples for each `(layer, N)` together. `shard_cases.py` prints the case count,
the shard count, and the exact `sbatch` line, including the array range; run
that printed line rather than a hardcoded array range.

```bash
$PY zoo/fig2_hw_n_sweep/slurm/shard_cases.py \
  --output-dir zoo/fig2_hw_n_sweep/outputs/slurm/cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/runs \
  --batch-samples --num-shards 250 --cases-per-shard 100 --cpus 4
SHARDS=<shards printed above>
sbatch --partition=normal --cpus-per-task=4 --array=0-$((SHARDS-1))%$SHARDS \
  zoo/fig2_hw_n_sweep/slurm/run_array.sbatch \
  --case-dir zoo/fig2_hw_n_sweep/outputs/slurm/cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/runs \
  --batch-samples
$PY zoo/fig2_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/cases/manifest.json \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/runs \
  --output-dir zoo/fig2_hw_n_sweep/outputs
```

## Network subsets and carried results

`--networks` restricts the manifest to one or more networks, given
space-separated or comma-separated within one value; `--network` takes a single
name and cannot be combined with `--networks`, and an unknown name is a usage
error. `--hardware-size`, `--layer`, and `--limit` narrow the selection further,
and filters that select no cases are rejected.

Merging a subset manifest into campaign outputs that already hold another
network needs `--carry-existing`. The three networks added to the ResNet19
campaign hold 35 included layers between them, which at `--cases-per-shard 100`
gives 17,500 cases in 175 shards, one `(layer, N)` group of 100 samples per
shard:

```bash
$PY zoo/fig2_hw_n_sweep/slurm/shard_cases.py \
  --networks vgg16 sdt vgg8dvs \
  --output-dir zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-runs \
  --batch-samples --num-shards 250 --cases-per-shard 100 --cpus 4
# then the printed sbatch line
$PY zoo/fig2_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-cases/manifest.json \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-runs \
  --output-dir zoo/fig2_hw_n_sweep/outputs \
  --carry-existing
```

`--carry-existing` reads `results.csv` and `summary.csv` from `--output-dir`,
requires both to exist, validates the carried rows as exactly the full
`resnet19` case set (its included layers × the five hardware sizes × the
100
selected samples) with no duplicates, missing, or extra cases, recomputes the
carried summary from the carried result rows and requires an exact match, and
exits if any carried case also appears in the shard manifest. The carried rows
are written ahead of the newly merged rows, which keep manifest order, and the
union is validated once more before the merged CSVs are written. ResNet19 is
carried, never re-run: its 6,500 layer runs plus the 17,500 new ones give the
24,000 layer runs and 2,000 network/sample totals of the merged campaign.

Without `--carry-existing`, `merge_results.py` refuses a merge that would drop
data: if `outputs/results.csv` holds a network that the shard manifest does not,
it exits naming those networks and pointing at `--carry-existing`. A manifest
covering all four networks needs no flag.

Each task writes `shard_XXXX/results_XXXX.csv`, its commands, Slurm log, and
per-case native logs below its own shard directory; the per-case stem carries
the network name, so cases of different networks never collide. The batch
generator writes one weight-trace log per `(layer, N)` and `run.py` runs nocsim
once per sample. The merge checks exact once-only coverage against the manifest
and reuses `run.py`'s summary logic. The generated `--output/--error` paths are
under the shard root, not the repository root.

To list incomplete cases and create a replacement manifest/array:

```bash
$PY zoo/fig2_hw_n_sweep/slurm/rerun_missing.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/cases/manifest.json \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/runs \
  --output-dir zoo/fig2_hw_n_sweep/outputs/slurm/rerun-cases \
  --new-shard-root zoo/fig2_hw_n_sweep/outputs/slurm/rerun-runs
```

For a small validation manifest, use `--batch-samples --limit 2
--num-shards 1 --cases-per-shard 100` (or filter to one network, hardware size,
or `(layer, N)` group); run the emitted array, merge it into a separate
`--output-dir`, and compare its `results.csv` with plain
`run.py --case-file <manifest> --no-summary`.
