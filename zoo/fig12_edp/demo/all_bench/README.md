# Sample-0 campaign

The driver starts from the production manifest and
[canonical kept-layer scope](../../docs/workload_layer_scope.md): 559 feasible
architecture/layer pairs plus six infeasible schedules, across eight benchmarks.
Each feasible case produces spad/cacheA/cacheB rows through the mandatory
[archx model](../../../archx/zoo/snn_edp/README.md). No historical case reuse or
snapshot allowlist is part of preparation. A completed receipt must match the
current table, code, configs and binaries exactly to be resumed.

## Execution

A future authorized run can be launched from the repository root:

```bash
bash zoo/fig12_edp/demo/all_bench/launch.sh
```

The launcher caps all thread pools, uses two small workers and one serial heavy
worker, and runs in its own systemd scope with memory/PID limits. Inspect
`status.json` for phase, active cases and the driver process group. For an
intentional stop, verify those fields in the running status file and signal only
its owned group with `kill -TERM -- -<driver_pgid>`.

`run.py --prepare` writes selection and input fingerprints. `--run` executes
pending work; `--retry-failed` deliberately retries failed/OOM cases. Changed
inputs fail closed. Per-case results are durable before traces are removed.
Do not use a stale status file or broad process-name matching to stop work.

## Outputs and validation

The driver creates `cases/`, `results.csv`, `whole_model.csv`, `coverage.json`
and `status.json`. `plot.py` creates per-benchmark latency/energy/EDP figures.
Groups missing a kept layer have hatched markers and no partial bars. Complete
model EDP is `(sum energy)*(sum latency)`; the sum of layer EDPs is separate.
All energy-incomplete results remain labeled lower bounds, even with full
layer coverage. Sample 0 provides no variance estimate.

```bash
conda run -n fig12-archx python -B zoo/fig12_edp/demo/all_bench/run.py --collect-only
conda run -n gurobi python -B zoo/fig12_edp/demo/all_bench/plot.py
PYTHONPATH=.:src conda run -n fig12-archx python -B -m pytest -q -p no:cacheprovider   zoo/fig12_edp/demo/all_bench/test_all_bench.py zoo/fig12_edp/demo/all_bench/test_layer_scope.py
```

These tests use synthetic receipt data and the canonical schedule manifest;
they do not depend on completed experiment outputs. The model's independent
15-row reference and five minimal simulator-input sets live under
`../../../archx/zoo/snn_edp/`. Count and pricing artifacts stay beside each sample
folder in `archx_artifacts/<sample>/`, outside receipt file sets.

`../../t88_deletion_manifest.json` points to the archival manifest and tars.
No experiment output is needed to import the driver or validate the energy model.
