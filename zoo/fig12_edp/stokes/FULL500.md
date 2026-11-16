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
| `batch.sbatch`, sourced from `full500_batch.sbatch` | Python case fan-out inside each allocated Slurm task |
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

Cases retain the demo's 16 GiB/25 min, 64 GiB/45 min and 120 GiB/60 min tiers.
An OOM or timeout receives one next-tier retry where available. Each case keeps
its own supervisor, address-space limit, attempt status and durable receipts.
The batch launcher uses Python subprocesses from the existing scientific
environment; no additional parallel-execution package is needed.

| Case tier | Cases/job | CPUs/job | Memory/job | Time/job |
|---|---:|---:|---:|---:|
| Default | 8 | 8 | 140 GiB | 25 min |
| Heavy | 2 | 2 | 140 GiB | 45 min |
| Largest | 1 | 1 | 120 GiB | 60 min |

The controller counts expanded array elements in `squeue`, including this user's
other jobs, and admits no more than 250 pending/running jobs. Compute admission
leaves one slot for pricing. Ready pricing jobs have admission priority and may
overlap each other and later samples' compute. Up to 15 samples are in flight;
there is no per-sample compute barrier after sample 000 is released.

If the oldest pending campaign task has waited 10/20/30 minutes, newly submitted
default batches shrink to 4/2/1 cases (70/35/16 GiB). Heavy batches shrink to one
case after 10 minutes. Submitted tasks are left intact: fallback never cancels
running work or submits a second copy of a case. Each submission records its
case-to-array-element mapping, resource request and manifest hash. Reconciliation
uses the individual case receipts, so a failed batch peer cannot cause a
completed case to be retried.

Sample work and scratch are measured, not inferred from a fixed per-sample size:
sample 000 reached 19 GiB work plus 12 GiB live scratch. The input dataset,
preserved recovery evidence and accumulating durable products are additional.
New sample admissions additionally require 70 GiB and 70,000 inodes for every
admitted-but-unfinished sample, including the proposed new one, plus a standing
30 GiB and 20,000-inode reserve. `lfs quota` supplies the user's remaining byte
and inode headroom; the smaller positive soft/hard limit applies. An unavailable
or unparseable quota reading holds new admissions only. Submitted jobs, pending
cases in admitted samples, pricing and retirement continue. This conservative
reservation counts remaining quota in addition to already-used space; effective
depth can be below 15 and changes as samples grow or retire.

`driver_status.json.quota_admission` reports headroom, effective depth and the
admission hold. Samples 001–015 are grandfathered admissions from before guard
deployment. Recovery evidence remains separate and retained. The filesystem-free
check remains independent of this user-quota admission check. Stage B uses
8 GiB and two CPUs per sample, with NG45 table SHA
`2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3`.

With `boundary.json.automatic_release.enabled`, each verified retirement advances
`max_sample` by one, up to the separate manager-owned `ownership_max_sample`.
The controller rechecks the committed product's hashes and coverage and requires
all three transient trees to be absent. A retirement credit is consumed exactly
once; consumption and the ceiling change share one atomic boundary-file write.
Quota holds retain unused credits for a later loop. The same per-sample and
standing reservations apply to unfinished samples already within the dispatch
ceiling, including quarantined samples; grandfathered samples beyond that ceiling
do not reserve a dispatch slot until released. Release also requires the projected
inode use, including one sample and the standing reserve, to remain at or below
850,000. Missing quota information holds releases without stopping existing work.
The ownership limit must be lowered before assigning further descending blocks
to Delta or another site. `driver_status.json.automatic_release` records release
or hold reasons; the boundary file retains the consumed credits and release log.

A sample is retired only after all 559 cases succeed, pricing preserves the
count inventory, 1,677 unique rows pass sample/table/EDP checks, CSVs and accounting
are fsynced, and a commit receipt records their hashes. Those hashes are checked
again before removing only that sample's `work`, `scratch` and `priced` trees.
A crash after commit resumes retirement from the verified receipt. Terminal
120 GiB OOMs and 60-minute timeouts for C01 gesture `layer_03_core_block4_0_0`
are quarantined with their evidence and completed peer cases retained, without
an additional retry. Other terminal failures preserve checkpoints and block the
controller; partial coverage is not
published as a completed sample. An unresolved sbatch intent requires accounting
reconciliation before restart, preventing blind duplicate submission.

The first completed sample sets `held_after_sample000`. It cannot launch sample
001 without the release file. The manager owns the shared Delta
`full500_ledger.json`; the controller reports local ascending block claims and
completion hashes without editing that file. Before assigning descending blocks
to another site, the manager lowers the Stokes ownership limit and checks already submitted
samples in `driver_status.json`. A boundary does not cancel already running work;
pending case submissions also recheck it. Lower the boundary only after
reconciling already admitted samples.
Sample processing and dispatch use numeric sample order, including after a
restart from the sorted JSON status file.

The driver has no SSH or Delta dependency. Tunnel loss does not stop submitted
jobs, pricing, commit/retirement, or the local loop. Transfers and operator probes
use the existing authenticated SSH control socket with fallback connections
disabled; socket loss requires boss reauthentication, not repeated login attempts.
