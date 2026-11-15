# Layer-8 dummy-price dry run

Five architectures × three arms, sample0 of `B09/loas_vgg16_T4_n500/layer_08_core_features_27`. This is a kept3x3 convolution (512 input/output channels,4x4 outputs,T4). Each case runs trace generation, analytic counts, both native cache simulations, native NoC simulation, archx count compilation/execution and Stage-B pricing. Cache configurations remain byte-pinned.

All53 pending prices are filled in `archx/zoo/snn_edp/characterization/energy_table_dummy.json`:14 explicitly retired-characterization magnitudes,34 archived composition estimates and5 explicitly uncharacterized substitutes (TCAM search/write, router and both full controllers). All default logic prices are null pending own-RTL500MHz synthesis; no retired class or active source CSV remains. Numerical totals are finite, but every row remains `incomplete=True` and carries **DUMMY placeholder pending ASAP7 synthesis**. These totals are neither final energy estimates nor lower bounds. `dummy_basis` records each substitute's magnitude/provenance; it does not certify500MHz ASAP7 timing or power.

Hardware describes two256x16 flop-based subset-match banks (`entry AND query == entry`), a four-entry64-bit ADDRESS queue inside L1 next_access (no data buffer; three state registers/core separate), and the pinned8192x64-bit L2 metadata SRAM. The event set remains unchanged; queue enqueue/dequeue is included in the controller dummy magnitude per existing `pf_issued` step, not simulated as an extra timing resource.

[OUTPUT_PATHS.md](OUTPUT_PATHS.md) and [output_paths.json](output_paths.json) list every case folder, analytic-count file, Stage-A directory, event-count categories file, Stage-B result and receipt using full paths. Each categories file contains per-operation `{count,category}` and core/memory/total rollups. Archx category event invocation counts are1: the rollups instead sum native `aggregate_event_count` queries rooted at the category event for every operation. The sums mix heterogeneous operation types and are not cycles, bytes, energy or a cross-architecture workload normalization.

The five serial cases together used199.27CPU-s; maximum peakRSS3.80GiB. Scope limits: oneCPU,14GiB,32tasks; worker address-space limit12GiB; thread pools1. No GPU allocation or synthesis license was used. All transient traces were deleted only after durable results.

From `/u/yyu9/projects/neuro_cache_wcache`, regenerate validation/CSV and figures:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 conda run -n fig12-archx python -B zoo/fig12_edp/demo/layer8_dummy/validate.py
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 conda run -n gurobi python -B zoo/fig12_edp/demo/layer8_dummy/plot.py
```

To execute one saved case with the same pipeline (matching completed results resume):

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 ARCHX_DISABLE_PERFORMANCE_CACHE=1 \
setsid -w systemd-run --user --scope -q -p OOMPolicy=continue -p MemoryMax=14G -p TasksMax=32 -p CPUQuota=100% \
nice -n 10 conda run --no-capture-output -n fig12-archx python -B zoo/fig12_edp/demo/run.py \
  --case-json zoo/fig12_edp/demo/layer8_dummy/loas.json --output zoo/fig12_edp/demo/all_bench --memory-gib 12 \
  --energy-table /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json
```

The table SHA is in output_paths.json and every row. Receipts explicitly pin this dummy table: the generic default-table campaign validator must not be used to relabel them as default-table results.

Model tests run in the archx checkout; runner tests run separately in neuro_cache_wcache to avoid their different `zoo` namespaces colliding during collection. Final logs: `model_tests.log` (16 passed) and `runner_tests.log` (9 passed).

The EDP figure uses absolute mJ·ms on a log axis, all15 bars, sample count1 and no error bars. Gill Sans is unavailable; the existing Cantarell humanist sans is used. PDF and300dpi PNG are under `../../figures/layer8_dummy_edp.*`; caption and figure provenance are saved beside them.
