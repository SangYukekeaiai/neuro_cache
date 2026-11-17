# Stokes Phase B: cache-DSE sweep and RQ4 figure

Phase A has already retained the 130 LoAS VGG16 weight traces at
`$HOME/loas10_20261116/`. Per the plan's S0 assumption, this kit consumes the
12 replayable convolution layers (layers 01--12) for samples `000`--`009`;
the plan leaves the independent basis for excluding the layer-13 1x1
classifier open. The resulting assumed grid is exactly 10 variants x 12
layers x 10 samples = 1,200 cache rows.

The retained-trace footprint was measured after Phase A. The table gives the
size of each layer at sample 000 and the sum over samples 000--009 (decimal
bytes):

| layer | sample_000 bytes | samples_000-009 bytes |
|---|---:|---:|
| layer_01_core_features_3 | 44,262,843 | 467,101,326 |
| layer_02_core_features_7 | 26,303,995 | 241,410,510 |
| layer_03_core_features_10 | 89,012,348 | 894,177,880 |
| layer_04_core_features_14 | 30,300,668 | 276,936,664 |
| layer_05_core_features_17 | 68,760,572 | 687,050,200 |
| layer_06_core_features_20 | 74,100,732 | 723,866,840 |
| layer_07_core_features_24 | 30,824,188 | 275,910,616 |
| layer_08_core_features_27 | 68,750,076 | 680,386,520 |
| layer_09_core_features_30 | 136,681,212 | 1,378,478,040 |
| layer_10_core_features_34 | 14,814,204 | 134,795,224 |
| layer_11_core_features_37 | 19,559,420 | 184,756,184 |
| layer_12_core_features_40 | 19,760,124 | 193,687,512 |
| layer_13_core_classifier | 29,995 | 296,730 |
| **total** | **623,160,377** | **6,138,854,246** |

The 12-layer cache-DSE subset occupies 6,138,557,516 bytes across ten
samples; the classifier is retained for trace completeness but is not in the
1,200-row grid. If the filesystem fills during an array, the affected task
fails while its `.part` file is left incomplete; free space or quota, remove
only that failed `.part`, and resubmit the same array. Completed CSV/receipt
pairs remain resumable and are not regenerated.

The ten configs are the plan's one-knob points: V0 cacheA, L2 256 KiB, L2 1
MiB, L1 8 KiB, L1 32 KiB, pure LRU, pure LFU, L2-only Belady, L1 next-line,
and L1+L2 next-line. `make_sweep_manifest.py` writes complete flat JSON
configs under `configs/` and validates every WCTS trailer, receipt digest and
schedule digest before writing the manifest.

If Phase A ever needs to be rerun, submit it from its manifest's output root
so Slurm's relative stdout/stderr paths stay beside the retained traces:

```bash
STAGE="${STAGE:-$HOME/snn_edp_stokes_20261114}"
REPO="${REPO:-$STAGE/neuro_cache_wcache}"
KIT="${KIT:-$REPO/zoo/cache_dse/stokes_kit}"
PHASE_A_OUT="$STAGE/cache_dse_stokes_phase_a"
mkdir -p "$PHASE_A_OUT"
cd "$PHASE_A_OUT"
sbatch --array=0-129%250 "$KIT/phase_a.sbatch"
cd "$REPO"
```

## Exact Stokes commands

Run these commands on Stokes from the staged checkout. The gate must pass
before either array is submitted.

```bash
STAGE="$HOME/snn_edp_stokes_20261114"
REPO="$STAGE/neuro_cache_wcache"
KIT="$REPO/zoo/cache_dse/stokes_kit"
TRACE_ROOT="$HOME/loas10_20261116"
OUT="$TRACE_ROOT/cache_dse"
CONDA=/apps/anaconda/anaconda-2024.10/bin/conda
export STAGE REPO KIT TRACE_ROOT OUT CONDA
cd "$REPO"

"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  "$KIT/make_sweep_manifest.py" --repo "$REPO" \
  --trace-root "$TRACE_ROOT" --output-root "$OUT" \
  --manifest "$OUT/manifest.json"
export MANIFEST="$OUT/manifest.json"

# Gate 1: V0 stable/counter-column identity against the committed cacheA row.
# Gate 2: one L2-only Belady run over the V0 access-log pass, with a V0/V4
# L2-demand access-log fixpoint check.
# Gate 3: one FN-CACTI geometry pilot.
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  "$KIT/run_gates.py" --manifest "$MANIFEST" --cacti-delegated

# First pass: one V0 access log per retained trace, 120 one-thread tasks.
mkdir -p "$OUT"
cd "$OUT"
PREPASS_JOB=$(sbatch --parsable --array=0-119%250 "$KIT/phase_b_prepass.sbatch")

# Second pass: 1,200 one-thread cache rows, including the 120 V4 rows.
# Stokes MaxArraySize is 1001, so split the legal task-index ranges and use
# CASE_OFFSET for the second chunk. Both chunks wait for the full prepass.
SWEEP_JOB_A=$(sbatch --parsable --dependency=afterok:"$PREPASS_JOB" \
  --array=0-999%250 "$KIT/phase_b.sbatch")
SWEEP_JOB_B=$(CASE_OFFSET=1000 sbatch --parsable --dependency=afterok:"$PREPASS_JOB" \
  --array=0-199%250 "$KIT/phase_b.sbatch")
echo "prepass=$PREPASS_JOB sweep_a=$SWEEP_JOB_A sweep_b=$SWEEP_JOB_B"
cd "$REPO"
```

Each Slurm task requests one CPU and 8 GiB on `normal` under account `dwu2`;
the `%250` throttle is the MaxJobs cap. Stokes also has MaxArraySize=1001,
which is why the 1,200-case sweep is submitted as legal 0--999 and
0--199+1000 chunks above. All common numerical thread pools are set to one,
and the runner uses `/dev/shm` for temporary files. The arrays write one CSV
and one JSON receipt per case under `$OUT/raw/`; the Belady access-log
prepass writes `$OUT/oracles/`.

After the sweep completes, run the four changed-geometry FN-CACTI harvest,
then aggregate and plot:

```bash
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  "$KIT/cacti_reharvest.py" --manifest "$MANIFEST"
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  "$KIT/aggregate.py" --manifest "$MANIFEST"
"$CONDA" run --no-capture-output -p "$STAGE/env" python -B \
  "$KIT/plot.py" --summary "$OUT/summary.csv" \
  --png "$OUT/cache_dse.png" --pdf "$OUT/cache_dse.pdf"
```

The aggregate writes `$OUT/cache_dse.csv` with the 1,200 layer/sample rows
and ten whole-model rows, plus `$OUT/summary.csv` for the figure. For each
sample it sums all 12 layer energies and all 12 layer times first, forms
`model_EDP = sum(E) * sum(t)`, and only then forms the V0-normalized ratios.
The bars use the mean of the ten sample ratios and 95% CI whiskers.
V4 is labeled `Belady (demand-only)`: its oracle bounds demand replacement
only. Prefetched fills have no demand-oracle entry (`kNever`) and are evicted
first, so V4 is a probe of demand-retention value rather than a performance
bound; the measured performance and EDP ratios are retained as-is.

The EDP model is the committed NG45-interim cache + DDR4 operation table,
with FN-CACTI values substituted for the four changed cache geometries;
prefetch-control prices remain the committed zero exclusions. This scope is
recorded in every aggregate row and in the figure subtitle. A cache row with
nonzero `max_wait_depth` is fatal in the runner, prepass, gate and aggregate.
The aggregate carries `incomplete` and `incomplete_reasons` from the selected
energy table (including the NG45 interim status) into every layer and summary
row. The gate receipt records each pilot's wall time and peak RSS in KiB.

## Outputs and recovery

```text
$OUT/manifest.json
$OUT/gates/gates.json
$OUT/oracles/sample_XXX/<layer>.access.bin
$OUT/raw/V*/sample_XXX/<layer>.csv + .json + .log
$OUT/cacti/harvest.json
$OUT/cache_dse.csv
$OUT/summary.csv
$OUT/cache_dse.png / .pdf
```

The runner is resumable only after verifying the CSV, receipt, trace, config,
and (for V4) oracle SHA256s. A failed task leaves a `.part` output and log;
re-submit the same array after fixing the cause. Do not run the aggregate
until all 1,200 receipts exist and the full four-geometry CACTI harvest has
completed.
