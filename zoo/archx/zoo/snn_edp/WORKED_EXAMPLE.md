# Worked example: SpinalFlow VGG16, sample 0

This kept convolution is `B09/loas_vgg16_T4_n500/layer_01_core_features_3`.
The example uses a hash-pinned, minimal simulator-input fixture. No raw capture, native
simulator, trace generator or schedule solver is opened or executed.

## Inputs

| File | Role |
|---|---|
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/fixtures/spinalflow/case.json` | architecture and case identity |
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/fixtures/spinalflow/counts.json` | analytic quantities, dimensions and measured next-layer density |
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/fixtures/spinalflow/noc/result.json` | spad cycles, weight and chain hops, delivery/DRAM activity |
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/fixtures/spinalflow/cache_a.csv` | cacheA counters and cycles |
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/fixtures/spinalflow/cache_b.csv` | cacheB counters and cycles |

Prosperity additionally consumes the matching case’s `record_count.csv`, with
capture/layer/sample identity checked before using its exact native record total.

## Drivers and Stage A intermediates

- Entry point: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/run.py` (`count`).
- Model description: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/designs/snn/description.py`.
- Callbacks: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/performance.py`.
- Hardware/expressions: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/hardware.json` and `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/model.py`.
- Case-only request: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/request.json`.
- Compiled architecture: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/architecture/config_0.architecture.yaml`.
- Compiled workload (only `case_dir`): `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/workload/spad/config_0.workload.yaml`.
- Compiled events: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/event/event.yaml`.
- Compiled metrics: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/metric/metric.yaml`.
- Batch index: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/runs.txt`.
- Counted spad graph: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/runs/spad/arch_0/config_0/checkpoint.json`.
- Count export: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/counts.json`.
- Input/model/backend manifest: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/manifest.json`.

`archx -compile`, `archx -extract`, then `archx -x` produce these files.
The cacheA/cacheB configurations have separate checkpoints under
`/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/runs/cacheA/arch_0/config_0/checkpoint.json` and
`/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts/runs/cacheB/arch_0/config_0/checkpoint.json`.
No table hash or characterized prices enter these counts.

## Stage B outputs

- Metric binder: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/pricing.py`.
- Table input: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/energy_table.json`.
- Exact table snapshot: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_priced/energy_table.json`.
- Priced spad graph: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_priced/spad.graph.json` (cacheA/cacheB beside it).
- Result rows and count-manifest hash: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_priced/result.json`.
- Pricing fingerprint and output digests: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_priced/manifest.json`.

Native archx queries compute dynamic energy, leakage power, deduplicated area
and each breakdown term. The wrapper computes time and leakage duration.

| Arm | Cycles | Time (s) | Dynamic (nJ) | Leakage (nJ) | EDP (nJ s) |
|---|---:|---:|---:|---:|---:|
| spad | 292673 | 0.000585346 | 961857.177624 | 377853.290734 | 784.194163811 |
| cacheA | 288439 | 0.000576878 | 33322.2364046 | 303170.857861 | 194.115463234 |
| cacheB | 288875 | 0.00057775 | 19105.1126359 | 300958.26317 | 184.916615372 |

All three rows are incomplete lower bounds; pending characterization contributes zero.
Comparison source (with retired-price deltas from `provenance/retired_logic.json`): `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/reference_t84_results.csv`.
Validation report: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/validation.json`. All67 SpinalFlow terms match the historical reference after explicit retired-price removal;
floating-point total differences are below 2e-16 relative. Shared inputs mean
this check validates arithmetic, not independent simulator or unit-energy accuracy.

## Reprice after synthesis

For example, with a new table staged at `/tmp/asap7_energy_table.json`:

```bash
cd /u/yyu9/projects/neuro_cache_wcache/zoo/archx
ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONPATH=/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo conda run --no-capture-output -n fig12-archx python -B -m snn_edp.run price --counts /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/spinalflow/fixture_counts --table /tmp/asap7_energy_table.json --out /tmp/spinalflow_asap7_prices
```

Only the saved checkpoints and the new table are read. Existing count graphs,
fixtures, saved count checkpoints and the pinned reference remain unchanged. In a
normal pipeline invocation the API chooses content-addressed sibling paths;
`runs/spinalflow/` is the explicit reproducible validation workspace.
