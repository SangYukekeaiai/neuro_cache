# Portable Fig12 campaign runner

A no-Slurm runner for 749 feasible pairs × 500 actual samples × three arms.

## Overview

Sample 0 across all selected pairs produces `demo/results.csv` and an
8-page `demo/draft.pdf` before sample 1 starts. Each later sample also has a
barrier. Results are durable per case; transient traces use separate scratch.
Failures, OOMs, over-budget cases and mini subsets never imply full coverage.
See [ARCHITECTURE.md](ARCHITECTURE.md) for mechanics and
[STAGING.md](STAGING.md) for the rented-host checklist.

## Requirements

Linux, Python 3.12, NumPy, PyYAML, Matplotlib, a C++17 compiler and GNU make.
No GPU/Slurm. Full captures are about 33 GB; memory-heavy samples measured
63 GiB and may require 140–200 GiB. Use local NVMe scratch and durable output
storage. The full 374,500-case run is expensive; no rental/cloud launch has
been performed. The known Prosperity zero-MAC rejection is not fixed here.

## Installation

Follow STAGING.md, including native rebuilds **only on the rented host**.
All shared Delta sources/binaries and the live T84 wave remain untouched.

## Quick start

The checked Delta mini is one SpinalFlow classifier, actual samples 0 and 1,
one 3 GiB worker within an owned 4 GiB scope:

```bash
bash zoo/fig12_edp/run_ec2/mini.sh > zoo/fig12_edp/run_ec2/mini.log 2>&1
```

It writes only `run_ec2/mini_output/` and its configured `/tmp` scratch. It
is explicitly a **1/749 subset**, never a campaign-completeness test. Existing
matching results resume without native recomputation. Changed scientific
inputs are rejected with a nonzero exit and require a new output root.

## Reproducing results

From the repo root:

```bash
PYTHONDONTWRITEBYTECODE=1 conda run -n fig12-archx python -B -m pytest -q -p no:cacheprovider \
  --basetemp=zoo/fig12_edp/run_ec2/test_tmp zoo/fig12_edp/run_ec2/test_runner.py
PYTHONDONTWRITEBYTECODE=1 conda run -n fig12-archx python -B zoo/fig12_edp/run_ec2/verify_mini.py
```

`mini_validation.json` records sample identity, numerical comparison with the
known VGG16 sample-0 result, and resume checks. For a fresh mini, run
`verify_mini.py --before-resume`, rerun `mini.sh`, then run the verifier without
that flag. `demo/results.csv` maps to `demo/draft.pdf` via `plot.py --checkpoint
<output>/demo` (on Delta use `conda run -n gurobi python -B`). Each sample has
n=1; no variance or significance claims. Whole-model EDP is `(sum E)*(sum T)`;
`sum_layer_EDP_nJ_s` is a separate sum. Missing model totals are blank; null
characterization is labelled as incomplete lower-bound energy.

After staging and validation, this is the **rented-host-only** background
launch for the 240-GiB example, from its repo root:

```bash
mkdir -p zoo/fig12_edp/run_ec2/logs
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
PYTHONDONTWRITEBYTECODE=1 \
setsid -w systemd-run --user --scope -q --unit="fig12-rented-$(date +%s)" \
  -p OOMPolicy=continue -p MemoryMax=244G -p MemorySwapMax=0 -p TasksMax=64 \
  conda run --no-capture-output -n fig12-archx python -B zoo/fig12_edp/run_ec2/run.py \
  --config zoo/fig12_edp/run_ec2/rented.json \
  > zoo/fig12_edp/run_ec2/logs/campaign.log 2>&1 < /dev/null &
```

Budget/scope limits must fit the measured host. If a rented host lacks a
systemd user manager, use `setsid` with the same runner and an externally
configured equivalent cgroup; memory reservations remain enforced by the
runner, but they do not replace a kernel aggregate limit. Do not run this
240-GiB example on Delta.

Monitor `<output>/status.json`, `<output>/events.jsonl`, the log and sample
`coverage.json`. A `finished` phase means all selected attempts finished;
coverage identifies successful, missing, failed and OOM cases. For stopping,
use SIGTERM only on the running driver's recorded `driver_pgid`; the driver
cancels its own worker sessions. Never use a prepared/finished stale PID or
process-name/PID walks. Reissue the same command to resume.

## Configuration

`rented.example.json` lists repo-relative or absolute capture, manifest,
architecture YAML, native binaries, table, cache/snapshot, scratch and output
paths; sample range uses an exclusive `sample_stop`. `case_limit=0` and empty
`case_keys` mean all 749 pairs. All thread pools are forced to one by the
runner before numerical imports. Worker count, memory tiers, serial threshold,
aggregate budget, driver allowance, timeout, scratch reserve and plotting
interpreter are explicit. A nonzero start requires verified earlier sample
checkpoints, including the sample-0 CSV and figure. Binaries and source changes
invalidate resume. Operational resource settings can change without changing
scientific fingerprints; explicit terminal failures remain terminal.

## Citation

Unpublished research harness; no citation is assigned.

## License

Use under the parent repository's terms; this task grants no additional
redistribution rights.


## Parked findings — required before enabling this runner

This path is parked; the following work is gated on remote-runner/T86 resumption.
No launch should use the current selection or deleted validation fixtures.

- `config.select()` still selects all 749 feasible pairs. Apply the canonical
  `../docs/workload_layer_scope.md` filter before simulation and sharding so only
  559 kept pairs are launched. The standalone zoo model deliberately does not
  enforce campaign layer names; the caller must prevent excluded work itself.
- Regenerate the deleted `mini_output` and `t86_mini` fixtures and their complete
  shard/merge/unlock artifacts, or explicitly park the dependent tests. Stored
  fingerprints naming the removed `aggregate.py` must be regenerated for the
  current model; never relax fingerprint checks to accept them.
- Fix the existing sample-barrier bug: `run.py` passes an integer case count to
  `config.key()` (which expects a case mapping), causing a TypeError. The remote
  suite remains red on this bug and the absent fixtures; it is not launch-ready.

Cache configs are independently byte-pinned by literal SHA256 values in
`../energy_driver.py`; both this runner and the local campaign enforce them.
`provenance/preserved_receipts.json` under the fig12 directory is a historical
archive index, not a set of live files or a resume allowlist.
