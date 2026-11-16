# Stokes full500 operation

The resident controller is `full500.py`. It uses the reviewed Stage-A worker and
NG45 Stage-B collector with an explicit sample index, never a different model.
Base source is commit `a352ced35b918fcb2e27f454d9d983c639f38739`; the T99 orchestration
patch and tests are recorded separately. The native archx library is the retained
Stokes build (SHA256 `92fbfaa145ebd2c4f09d708427dd7ecc1630d113083ca2a90a443f30e7b0386e`),
not the incompatible Delta binary included in the source archive.

All runtime paths below are under `~/snn_edp_stokes_20261114/full500/` on Stokes:

| Path | Purpose |
|---|---|
| `driver.sh`, tmux session `full500` | Detached login-node submission/accounting controller; no simulation on login |
| `driver_status.json` | PID, heartbeat, sample phases, array IDs, retry accounting, locally claimed blocks and row hashes |
| `boundary.json` | Manager-controlled inclusive `max_sample`, initially 499; read before new sample launches |
| `release_after_sample000.json` | Absent until boss release; `{"approved":true}` permits samples 001 onward |
| `staging/` | Per-benchmark SHA lists and verification logs; `ALL_READY` gates submission |
| `fixture_gate.json` | Successful five-architecture/three-arm fixture gate |
| `work/sample_XXX/` | Per-sample config, Stage-A cases and count checkpoints |
| `scratch/sample_XXX/` | Transient WCTS and native temporary files |
| `priced/sample_XXX/` | Batch-job Stage-B outputs before durable collection |
| `rows/sample_XXX/` | Durable CSVs, coverage, table snapshot, count inventories, accounting and commit receipt |
| `logs/` | Slurm logs; retained for diagnosis |

Sample arrays use the demo's 16 GiB/25 min, 64 GiB/45 min and 120 GiB/60 min
initial tiers. An OOM or timeout receives one next-tier retry where available.
The association's 250-job running cap applies. There are at most four active
samples, below the authorized maximum of 15, to bound count checkpoints near
12 GiB; large in-flight WCTS traces can create additional transient peaks.
The input dataset and accumulating durable products are separate from this
checkpoint budget. Stage B runs as an 8 GiB, two-CPU batch job, one sample at a
time, using NG45 table SHA
`2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3`.

A sample is retired only after all 559 cases succeed, pricing preserves the
count inventory, 1,677 unique rows pass sample/table/EDP checks, CSVs and accounting
are fsynced, and a commit receipt records their hashes. Those hashes are checked
again before removing only that sample's `work`, `scratch` and `priced` trees.
A crash after commit resumes retirement from the verified receipt. Any terminal
failure preserves checkpoints and blocks the controller; partial coverage is not
published as a completed sample. An unresolved sbatch intent requires accounting
reconciliation before restart, preventing blind duplicate submission.

The first completed sample sets `held_after_sample000`. It cannot launch sample
001 without the release file. The manager owns the shared Delta
`full500_ledger.json`; the controller reports local ascending block claims and
completion hashes without editing that file. Before assigning descending blocks
to AWS, the manager lowers the Stokes boundary and checks already submitted
samples in `driver_status.json`. A boundary does not cancel already running work.

The driver has no SSH or Delta dependency. Tunnel loss does not stop submitted
jobs, pricing, commit/retirement, or the local loop. Transfers and operator probes
use the existing authenticated SSH control socket with fallback connections
disabled; socket loss requires boss reauthentication, not repeated login attempts.
