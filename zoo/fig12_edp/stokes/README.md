This runner produces price-independent Stage-A event-count checkpoints for
sample 0 of all 559 kept feasible cases, with `spad`, `cacheA`, and `cacheB`
arms. It generates a WCTS trace, collects NumPy counts, runs both cache
configurations and NoC simulation, and calls `snn_edp.run.count(case, output)`.
Stage 1 configures, reads, and fingerprints no energy table. Stage 2 is a
separate authorized pricing-and-collection step, followed by plotting, after
all Stage-1 jobs and retries have drained. Terminal failures may remain;
valid completed checkpoints are still priced and missing groups stay explicit.

`stage1.sbatch` runs a non-login Bash shell and uses the absolute conda executable
`/apps/anaconda/anaconda-2024.10/bin/conda`. Its staged root is
`$HOME/snn_edp_stokes_20261114`, its environment is `env/`, and its worker config
is `stage1/config.json` beneath that root. Submission supplies array indices,
memory, and wall time. `SLURM_ARRAY_TASK_ID` is the zero-based index in the full
selection list; `T97_ATTEMPT` defaults to `0`. The script sets all thread pools
to one and uses `--propagate=NONE` to avoid inheriting login resource limits.

The worker CLI is:

```text
python -B zoo/fig12_edp/stokes/stage1_worker.py --config CONFIG --case-index INDEX --attempt 0
```

Config JSON accepts these paths; relative paths resolve against `repo`, which
otherwise defaults to the repository containing the worker:

| Keys | Meaning |
| --- | --- |
| `capture_root` | Read-only sample-0 captures and metadata. |
| `schedule_manifest`, `schedule_cache` | Schedule manifest and generator cache root. Selected artifact hashes must agree. |
| `selection` | JSON containing the ordered `cases` list. |
| `arch_yaml` | Map from each architecture name to its YAML path; checked against the schedule hash. |
| `cachesim`, `eventsim` | Built native executables. |
| `cache_a`, `cache_b` | Production cache configuration files. |
| `output_root`, `scratch_root` | Separate durable and transient trees, outside read-only inputs. |

Each selection entry supplies `key` (`arch/trace_relative_dir/layer`) and
`record_memory_proxy_gib`. `tier: "historical_oom"` selects the historical
SpinalFlow OOM tier. Full selection requires exactly the 559 kept feasible
cases; `"mini": true` permits an explicitly partial selection.

| Initial selection | Memory | Slurm wall cap |
| --- | --- | --- |
| Proxy at most 16 GiB | 16 GiB | 25 minutes |
| Proxy above 16 GiB | 64 GiB | 45 minutes |
| Historical SpinalFlow OOM | 120 GiB | 60 minutes |

The supervisor reserves 30 seconds for shutdown and status writes. OOM,
`killed_or_oom`, or timeout can request one next-tier retry: 16→64 or 64→120 GiB.
Exit 75 and `attempt_0.json.retry` describe that request; submission must allocate
the indicated resources and pass `--attempt 1`. There is no automatic retry
above 120 GiB; further action awaits authorization. Scheduler-level termination
without a final status requires external accounting reconciliation.

Each case lives at `output_root/<key>/sample_00000/`:

- `case/`: identity, generation provenance, NumPy counts, exact record CSV,
  cache CSVs, and `noc/` measurements.
- `counts/`: native graphs, event counts, category counts, and `manifest.json`.
- `inputs.json`, `steps/`, `complete.json`: input fingerprints and durable receipts.
- `attempt_N.json`, `attempt_N.log`: resource limits, outcome, and diagnostics.

The deterministic trace is
`scratch_root/<key>/sample_00000/sample_00000.wcts`; native `TMPDIR` is its sibling
`tmp/`. The trace is deleted only after the count artifacts and completion
receipt are synced. Failed attempts retain their trace and completed stages.
Resume verifies input/source/native/config hashes and checkpoint artifacts;
changed inputs fail closed. Matching complete cases return `resumed` without
recomputation. An inadequate inherited address-space hard limit produces
`resource_unavailable` before worker launch.

After confirming drain and reconciling terminal job statuses, run Stage 2 and
then plotting in the allocated batch environment (non-login shell, thread
pools set to one, `--propagate=NONE`):

```bash
STAGE="$HOME/snn_edp_stokes_20261114"
REPO="$STAGE/neuro_cache_wcache"
CONDA=/apps/anaconda/anaconda-2024.10/bin/conda
cd "$REPO"
export LD_LIBRARY_PATH="$STAGE/env/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONDONTWRITEBYTECODE=1
export MPLCONFIGDIR="$STAGE/stage2_mplconfig"
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  zoo/fig12_edp/stokes/stage2.py \
  --stage1-root "$STAGE/stage1" \
  --table "$REPO/zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json" \
  --output "$STAGE/stage2" --workers 2 --confirmed-drained
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  zoo/fig12_edp/stokes/plot.py \
  --input "$STAGE/stage2/whole_model.csv" --out "$STAGE/stage2/figures"
```

Stage 2 reads `stage1/config.json` for the schedule manifest, selection, and
checkpoint output root. It runs at most two separate `snn_edp.run price`
processes and does not read simulator inputs or call counting. Each pricing
output is stored under `stage2/cases/<key>/sample_00000/<tableSHA>/`. The dummy
table is copied byte-for-byte and its SHA256 is recorded in rows and coverage.

Collection writes `results.csv`, `whole_model.csv`, and `coverage.json`.
Coverage records terminal failures, the six infeasible schedules,
`started_unix`, `finished_unix`, and elapsed `wall_seconds`. Batch logs receive
flushed progress every 25 priced cases and at the last case. `report_complete`
is false if any feasible case fails. `counts_before.json`, `counts_after.json`,
and `immutability.json` record hashes of every saved count file, including
partial checkpoints; changed counts, tables, or selection inputs block collection.

All published rows are marked DUMMY and energy-incomplete. Fully covered
model groups use `complete_dummy_prices`; groups with missing layers have null
model metrics, never partial bars. Model EDP is `(sum energy) * (sum latency)`;
`sum_layer_EDP_nJ_s` is the separate sum of layer EDPs. Partial sums remain in
explicitly named CSV columns only.

Plotting writes `figures/whole_model.pdf` (eight benchmark pages, each with
latency, energy, and EDP panels), per-page PNGs, `model_edp_overview.pdf/.png`,
`sum_layer_edp.pdf/.png`, and `plot_manifest.json`. Captions and the manifest
state **DUMMY PRICES — ENERGY / EDP PLACEHOLDERS**: all groups remain
energy-incomplete and placeholder values are not lower bounds. Coverage labels
show completed/nominal layers; hatching marks unavailable totals. Sample 0 has
n=1 when any layer completes, otherwise n=0, with no error bars. Caption text,
source hashes, and the reproduction command are saved in `plot_manifest.json`.

For the NanGate45 interim price basis, use a separate output root and explicit
pricing profile. These commands read the existing Stage-A checkpoints; no
simulator or event-count model runs:

```bash
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B zoo/fig12_edp/stokes/stage2.py \
  --stage1-root "$STAGE/stage1" \
  --table "$REPO/zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json" \
  --output "$STAGE/stage2_ng45" --workers 2 --confirmed-drained --pricing-profile nangate45
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B zoo/fig12_edp/stokes/plot.py \
  --input "$STAGE/stage2_ng45/whole_model_ng45.csv" \
  --out "$STAGE/stage2_ng45/figures" --nangate45-only
```

The profile writes `results_ng45.csv` and `whole_model_ng45.csv`, plus count-file
hash inventories before and after pricing. The two overview figures carry the
mixed-technology caveat and table SHA. Latency remains count-derived and
unchanged. [Pricing sources and substitutions](../../archx/zoo/snn_edp/characterization/NANGATE45.md)
document the interim assumptions. All pricing profiles preserve missing-group
hatches and prohibit partial whole-model bars.
