# wt500 Slurm trace-generation harness

This harness runs the campaign's frozen schedule manifest in restartable array
shards. It has no DeltaAI or Stokes path baked in: pass repository, Python,
trace-root, and schedule-cache roots on every generated `sbatch` command.

`shard_cases.py` reads the manifest written by
`zoo/wt500_fig3cfg/gen_inputs.py`. It accepts a `combos`/`schedules` list with
`arch`, `trace_dir`, `layer`, and `has_solution` fields, or equivalent nested
schedule/capture records. Infeasible or explicitly excluded records are
omitted. The resulting harness manifest freezes samples `0..499`, keeps all
samples of one `(arch, trace_dir, layer)` together, and orders architectures as
`loas, ptb, spinalflow, prosperity, gustavsnn`.

The frozen records retain `trace_relative_dir` (for example
`A02/spikformer_4_384_cifar100_T4_n500`). The runner uses its parent as the
trace root for the native generator while keeping the basename as the schedule
cache key, matching the layout produced by `gen_inputs.py`.

From the repository root on a Stokes compute allocation:

```bash
export REPO=/path/to/neuro_cache
export PYTHON=/path/to/python
export TRACE_ROOT=/path/to/input_trace_delta
export SCHEDULE_CACHE=/path/to/schedules

"$PYTHON" zoo/wt500_fig3cfg/slurm/shard_cases.py \
  --campaign-manifest zoo/wt500_fig3cfg/outputs/manifest.json \
  --output-dir zoo/wt500_fig3cfg/outputs/slurm/cases \
  --shard-root zoo/wt500_fig3cfg/outputs/slurm/runs \
  --num-shards 250 --cpus 4 \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"
```

The script prints the exact array submission line. On Stokes, submit from a
tmux session with `setsid` if the launch shell may disconnect; this workflow
uses `setsid` only and does not assume a systemd user bus:

For the S3 weighted layout, pass its CSV instead of an even-split size:

```bash
"$PYTHON" zoo/wt500_fig3cfg/slurm/shard_cases.py \
  --campaign-manifest zoo/wt500_fig3cfg/outputs/manifest.json \
  --shards-file zoo/wt500_fig3cfg/stokes/shards/shards.csv \
  --output-dir zoo/wt500_fig3cfg/outputs/slurm/cases \
  --shard-root zoo/wt500_fig3cfg/outputs/slurm/runs \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"
```

This writes one `cases_XXXX.json` per CSV row and sizes the printed array to
that row count. Weighted manifests omit `cases_per_shard` because their shard
sizes are intentionally uneven; choose an explicit `--cases-per-shard` when
building a rerun manifest.

```bash
setsid sbatch --partition=normal --cpus-per-task=4 --array=0-N%N \
  zoo/wt500_fig3cfg/slurm/run_array.sbatch \
  --case-dir zoo/wt500_fig3cfg/outputs/slurm/cases \
  --shard-root zoo/wt500_fig3cfg/outputs/slurm/runs \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"
```

Each task invokes `python -m lays.weight_trace_gen gen` once per combo with
`--sample-start 0 --sample-count 500`; the generator writes
`step_cycles/<arch>/<trace_dir>/<layer>/sample_NNNNN.json.gz`. Then each sample
is streamed with `--sample-count 1`; stdout is written as
`wcts/<arch>/<trace_dir>/<layer>/sample_NNNNN.wcts.gz`. A shard writes its
result CSV only for cases for which both files exist.

If an array round is incomplete, emit a replacement manifest. The printed
submission command carries the same roots; no path is inferred from the
DeltaAI layout:

```bash
"$PYTHON" zoo/wt500_fig3cfg/slurm/rerun_missing.py \
  --manifest zoo/wt500_fig3cfg/outputs/slurm/cases/manifest.json \
  --shard-root zoo/wt500_fig3cfg/outputs/slurm/runs \
  --output-dir zoo/wt500_fig3cfg/outputs/slurm/rerun-cases \
  --new-shard-root zoo/wt500_fig3cfg/outputs/slurm/rerun-runs \
  --trace-root "$TRACE_ROOT" --schedule-cache "$SCHEDULE_CACHE" \
  --repo "$REPO" --python "$PYTHON"
```

After the initial and rerun rounds, assemble complete canonical shards. The
assembler combines rows by case, so a rerun containing only missing samples
can repair an original 500-sample shard. It hardlinks the two compressed
artifacts into the canonical tree (the source and assembled roots must share
the Stokes filesystem), avoiding a second full WCTS copy:

```bash
"$PYTHON" zoo/wt500_fig3cfg/slurm/assemble_shards.py \
  --manifest zoo/wt500_fig3cfg/outputs/slurm/cases/manifest.json \
  --source zoo/wt500_fig3cfg/outputs/slurm/cases/manifest.json \
          zoo/wt500_fig3cfg/outputs/slurm/runs \
  --source zoo/wt500_fig3cfg/outputs/slurm/rerun-cases/manifest.json \
          zoo/wt500_fig3cfg/outputs/slurm/rerun-runs \
  --output-root zoo/wt500_fig3cfg/outputs/slurm/assembled-runs

"$PYTHON" zoo/wt500_fig3cfg/slurm/merge_results.py \
  --manifest zoo/wt500_fig3cfg/outputs/slurm/cases/manifest.json \
  --shard-root zoo/wt500_fig3cfg/outputs/slurm/assembled-runs \
  --output-dir zoo/wt500_fig3cfg/outputs/slurm/merged
```

`merge_results.py` checks every shard's result rows, both output trees, and the
campaign-wide set for exact once-only coverage. It writes `results.csv` and a
machine-readable `coverage.json` only after all `500 * combos` cases have both
compressed artifacts.
