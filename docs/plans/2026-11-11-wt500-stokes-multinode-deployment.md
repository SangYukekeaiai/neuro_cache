# WT500 multi-node deployment on Stokes

Addendum to `2026-11-11-wt500-stokes-generation-plan.md`. That plan's S1
(storage), S5 (demos and scaling) and S6 (checkpointing) remain the framework;
this document fixes the deployment shape those sections left open, using what
the S2 campaign and the cluster's public documentation now tell us. Nothing
here repeats the parent plan; read it first.

## What changed since the parent plan

- **Scheduling is done and off the critical path.** The 13-mode sweep
  completed on the DeltaAI login node: 755 pairs, 749 optimal schedules,
  6 prosperity infeasibles, digest in the unified manifest
  (`zoo/wt500_fig3cfg/outputs/manifest.json`). Stokes never runs Gurobi;
  it only runs the native weight-trace generators against finished
  schedule JSONs. No solver license problem exists on Stokes.
- **The single-cnode interactive attempt is abandoned.** Running the
  campaign inside one interactive node under a peon-code session did not
  finish even the scheduling stage. Two lessons carried into the design:
  generation must run as **batch Slurm jobs** (sbatch arrays), never
  inside interactive agent sessions; and agents only submit, monitor and
  verify from the login node.
- **Storage on Stokes is confirmed insufficient for the full output.**
  ARCC policy: per-user home on Lustre is capped at **500 GB and 400,000
  files**, is not backed up, and is explicitly not for long-term storage.
  One heavy layer alone computes to ~2.9 GB of uncompressed stream per
  sample (S1's anchor), so the full campaign cannot sit on Stokes at any
  point. The pipeline below therefore generates in waves and ships out
  continuously.

## Cluster facts (ARCC public docs; verify on first login)

- Scheduler: Slurm. Allocation: **80,000 core-hours per month per faculty
  member**, non-rolling; check with `myusage`. This is the shared budget
  ceiling for the whole campaign month.
- Storage: `/lustre` home, 500 GB / 400k files per user; no backups.
  The prior campaign root was `/lustre/fs1/home/ya867177` while the
  policy page describes `/lustre/fs0`; both must be checked on login.
- Unknown until first login (the docs do not publish them): partition
  names, per-partition wall-clock limits, cores and RAM per node.
  First-login recon (five commands, two minutes):
  `sinfo -o "%P %l %D %c %m"`, `myusage`, `lfs quota -h -u $USER /lustre/fs1`
  (and fs0), `df -h /lustre/*`, `which ncode cnode`.

## Open items this plan is blocked on

1. **SSH alias for Stokes** (from the user; parent plan's Q5).
2. **T53 / S3 record-count estimates** (in flight on DeltaAI): shard
   weights and the heavy-layer set come from it.
3. **S5 demos** (first Stokes stage below): wall-time rate, peak RSS and
   the compression ratio, without which node count and wave size are
   guesses.

## Deployment design

### Staging (login node, no allocation cost)

Ship to Stokes once: the 8 input captures (~33 GB), the 749 schedule
JSONs plus unified manifest (~100 MB), and the repo at the campaign
commit. Build the native generators on a compute node of the target
partition (not the login node), then run the stale-binary check from the
parent plan's caveats.

**Transport is Globus (settled 2026-11-11).** Unattended SSH into Delta
is not possible: NCSA disables SSH key pairs for general use and requires
password + NCSA Duo on every login (exceptions only via a
Gateway-allocation request to NCSA Help). So: Delta side, NCSA Delta's
ACCESS storage endpoint (`globus endpoint search "NCSA Delta"`; confirm
it exposes the `/work` destination). Stokes side, an ARCC server endpoint
if one exists, else **Globus Connect Personal** run as the user on the
login node - it makes outbound-only connections, so the VPN firewall is
irrelevant. One browser consent, then the CLI automates transfers
unattended with checksums and retries. A reverse tunnel through the
user's VPN laptop remains the fallback for control and small files only,
never for trace waves. If Globus is blocked on either side, the
DeltaAI-local alternative (last section) wins outright.

### Sharding (from S3 estimates, weighted)

- `slurm/shard_cases.py` gains the weighted mode S5 already requires:
  shards balanced by estimated records, not case count.
- Target shard duration: 2-4 h of projected work, so a lost node costs
  little and queue turnaround stays short. Cap: whatever the partition's
  wall limit turns out to be, minus 25% margin.
- Heavy layers (gustavsnn C01 L1-L4, spinalflow C01 L1-L4, plus whatever
  S3 puts in that band) get dedicated single-layer shards with their own
  time and memory limits, exactly as S5 prescribes.

### Execution (sbatch array, one shard per task)

- One Slurm **job array**, one array task per shard; each task runs one
  `gen` invocation stream on its own node (or socket, if nodes are large
  and RAM allows two shards - decide from demo RSS).
- Task template: `setsid` the generator, write to node-local or shard-
  private Lustre dir, log per shard, exit nonzero on any empty-trace
  output (the parent plan's explicit records>0 check).
- Concurrency throttle: `--array=0-N%K` where K is tuned to the
  core-hour budget and the shipping bandwidth (below), not to raw node
  availability. Start K small (4-8 nodes), raise after the first wave
  ships clean.
- No per-pair conda, no nested environment managers inside tasks - the
  S2 ERROR lesson: environment wrappers under concurrency are the
  fragile layer. Tasks run the prebuilt native binary plus a bare venv
  python directly.

### Storage wave pipeline (the 500 GB answer)

Ring-buffer discipline on the Stokes side; the durable copy lives on
DeltaAI (`/work/nvme/bebv/yyu9/`, where the inputs already live).

1. Each shard writes compressed traces to
   `$CAMPAIGN/outbox/<shard_id>/`, then drops a `DONE.sha256` manifest
   (per-file checksums) as its last act.
2. A **shipper** loop on the login node (cron or a watcher script, not
   an agent): for each completed shard dir,
   `globus transfer --sync-level checksum` to the Delta collection, poll
   the task to completion, then and only then delete the Stokes copy.
   Shard dirs are immutable after DONE, so the shipper needs no
   coordination with Slurm.
3. **Backpressure**: the sbatch task prologue checks
   `du -s $CAMPAIGN/outbox`; above a high-water mark (300 GB, 60% of
   quota) the task requeues itself with a delay instead of generating
   into a full disk. The 400k-file cap gets the same treatment using the
   outbox file count; per-shard tarring is the fallback if file count,
   not bytes, turns out to be the binding constraint (decide from demo
   output shape).
4. Wave size therefore self-regulates: generation throttles to shipping
   bandwidth, and Stokes never holds more than the high-water mark.

### Budget check (fill in after demos)

nodes-hours needed = total_records (S3) / (records-per-second-per-node
from the S5 demo) / 3600. Must fit inside the month's remaining
core-hours (`myusage`) with the heavy shards costed at their own
measured rate. If it does not fit in one month's 80k core-hours, the
wave pipeline already supports spilling the tail into the next month -
or the Q5 alternative below wins.

### Verification and checkpointing

Parent plan S6 applies unchanged. Additionally, after each wave lands on
DeltaAI: row-count reconciliation against the shard manifest, and the
records>0 check per layer. The campaign is re-entrant: a shard is done
only when its traces are checksummed on DeltaAI, so any Stokes-side loss
(node death, purge, quota eviction) re-runs that shard alone.

## The alternative that stays on the table

Parent plan Q5's other branch - generate directly on DeltaAI next to the
destination filesystem - eliminates the entire shipping pipeline and the
500 GB constraint, at the cost of competing for DeltaAI CPU allocation.
If Stokes recon shows thin partitions, long queues or a depleted
core-hour balance, that branch wins on simplicity and should be taken
instead; the sharding and verification design above transfers unchanged,
minus the shipper.

## Sequencing

1. User provides SSH alias -> recon (5 commands) -> go/no-go vs the
   DeltaAI alternative.
2. T53 (S3) lands -> weighted shard list.
3. Stage inputs + schedules + build -> S5 demos (one per combo, chunk 10)
   -> rates, RSS, compression ratio.
4. Fill in the budget check; pick K; submit the array.
5. Shipper on; waves flow; per-wave verification on DeltaAI.
