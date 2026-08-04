# 2026-08-03 LoAS hierarchical cache replay

Five-sample smoke sweep for milestones 4–5 of
`log/2026-08-03-l1-l2-cache-policy-plan.md`.

The completed run contains 14,880 per-sample/config rows in
`hierarchical_cache_results.csv` and 124 gzip-compressed per-core result
files. Slurm job 20823836 completed successfully in 38:52.

The driver defaults to preview-only. The approved full run uses one
16-CPU Slurm allocation. The account is GPU-only, so the job requests
one otherwise-unused A40 GPU:

```bash
sbatch profiling/0803_l1_l2_cache/run_sweep.slurm
```

Completed layer units are cached atomically under `results/`; per-core L1
statistics are stored as gzip CSVs under `per_core/`. Rerunning the same
job resumes missing units. After the job finishes, validate and merge:

```bash
PYTHONPATH=src python profiling/0803_l1_l2_cache/run_sweep.py --merge-only
```

After the sweep:

```bash
python profiling/0803_l1_l2_cache/build_artifact.py
python -m http.server 8000 --directory profiling/0803_l1_l2_cache/artifact
```
