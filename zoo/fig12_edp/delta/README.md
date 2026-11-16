# Delta descending campaign

Delta owns manager-confirmed descending sample blocks; Stokes runs ascending.
The manager maintains `../stokes/full500_ledger.json`. The first Delta block is
490–499. Each production task runs its fixture gate and then its sample without
an operator checkpoint.

Submit from the repository root:

```sh
sbatch zoo/fig12_edp/delta/production.sbatch
```

The manager's ledger assigns samples060–339 and blocks430–439,450–459,
470–479 and490–499 to Delta. The original ten-task array and the310-task
extension are independent, each throttled to two tasks: four concurrently.
`remaining_samples.txt` supplies the extension's exact task-to-sample mapping.
Each requests32 cores, two GPUs,140GiB and six hours on `gpuA40x4`, account
`bebv-delta-gpu`, using either `gpuA40x4` or `gpuA40x4-preempt`. This workload uses CPUs. `run_node.py` reserves each active
case's full16/64/120GiB tier within128GiB, leaving12GiB for orchestration.
Memory limits concurrency below32 cases for this workload.

`node.sh` builds the native programs on Delta and exercises production B's
NextLine policy. The five-architecture/three-arm fixture gate compares386 terms
against the retained historical reference, with the documented retirement and
prefetch-exclusion adjustments. Relative error must be below1e-9; expected zeros
must be exact. The gate records the imported vendored backend and native hashes
before any case generation starts.

Paths:

| Artifact | Location |
|---|---|
| Protected captures, read-only | `/work/nvme/bebv/yyu9/input_trace_delta/` |
| Workspace | `/work/hdd/bebv/yyu9/fig12_full500_delta/` |
| Manager-confirmed sample ownership | workspace `claims.json` |
| Per-case configuration/checkpoints | workspace `work/sample_XXX/` |
| Transient generated traces | workspace `scratch/sample_XXX/` |
| NG45 priced intermediates | workspace `priced/sample_XXX/` |
| Fixture evidence | workspace `fixture_gate.json`, `gate/` |
| Per-sample state | workspace `sample_XXX_status.json` |
| Durable rows/accounting | repository `zoo/fig12_edp/delta/full500/rows/sample_XXX/` |
| Slurm logs | repository `zoo/fig12_edp/delta/full500/logs/` |

The workspace `rows` symlink points to the repository's durable row directory.
The existing Stokes worker supplies case receipts and the single next-tier
retry; the same stage2 and commit functions price NG45, verify all559 cases,
commit1677 rows plus accounting, and only then retire work/scratch/priced trees.
No simulator inputs are written, and native binaries are never synced from
another host. All thread caps and `ARCHX_DISABLE_PERFORMANCE_CACHE=1` apply.

Terminal120GiB OOMs or60-minute timeouts for C01 gesture
`layer_03_core_block4_0_0` are quarantined with evidence retained and no additional
retry. A sample containing such a case remains incomplete and is not priced or
retired. Other terminal failures stop for diagnosis. A scheduler interruption
retains evidence. A proven Slurm preemption/requeue or timed-out allocation
reopens interrupted work at the same tier. `recovery.py` archives its attempt
receipt and logs, and the worker revalidates fingerprints and completed steps.
Unrelated failures do not enter this recovery path.

The per-sample lock prevents two jobs from owning the same sample. Native build
receipts pin source hashes, binary hashes and the host ISA; later tasks reuse
only an exact match. Every task executes the fixture gate before campaign work.
