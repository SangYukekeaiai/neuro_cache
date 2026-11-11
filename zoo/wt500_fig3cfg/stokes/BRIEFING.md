# Briefing: Stokes-side campaign session

You are the Claude session on the Stokes login node, running inside tmux,
responsible for the WT500 weight-trace generation campaign. Your manager
session lives on DeltaAI and cannot reach this cluster; coordination happens
through git. Read, in order:

1. `docs/plans/2026-11-11-wt500-stokes-generation-plan.md` (the framework:
   S1 storage, S4 input transfer, S5 demos and scaling, S6 checkpointing)
2. `docs/plans/2026-11-11-wt500-stokes-multinode-deployment.md` (the
   deployment design you are executing: batch sbatch array, weighted shards,
   storage wave pipeline, budget check)
3. `zoo/wt500_fig3cfg/HANDOFF.md` (campaign state and operating constraints)

## Session rules

- Run everything long-lived inside this tmux session; `setsid` long jobs.
- Generation runs as Slurm batch jobs only - never inside an interactive
  node session. The login node is for orchestration, the shipper loop and
  monitoring only; keep it light (the manager's cluster had a 1000-PID
  cgroup cap that SIGABRT'd agents; check `cat /sys/fs/cgroup/.../pids.max`
  equivalents here before spawning anything heavy).
- No credentials in files, commits or logs. Ever.
- Commits: status-board commits to the campaign branch are yours; code
  changes follow the review flow in HANDOFF.

## Boot sequence

1. `bash zoo/wt500_fig3cfg/stokes/RECON.sh | tee recon.txt` - then decide
   go/no-go per the deployment plan: if partitions are thin, the core-hour
   balance is low, or no unattended data path to DeltaAI exists (neither
   ssh-key rsync nor Globus), STOP and report that the DeltaAI-local
   alternative (deployment plan, last section) should win.
2. Commit `recon.txt` to the campaign branch and push, so the manager
   session sees it.
3. Unpack and verify the schedules - they travel in this repo:
   `zoo/wt500_fig3cfg/release/s2_schedules.tar.gz` (142 KB). Follow
   `zoo/wt500_fig3cfg/release/README.md`: untar into
   `zoo/wt500_fig3cfg/outputs/`, then run the README's verification
   snippet, which checks every schedule file against the sha256 recorded
   per row in the manifest. 749 verified rows, 0 mismatches, or stop.
4. Wait for the manager to land the weighted shard list (produced by S3 on
   DeltaAI) in `zoo/wt500_fig3cfg/stokes/shards/`; meanwhile stage the
   input captures (~33 GB, via Globus - the one thing git cannot carry)
   and build natives per S4, and run the S5 demos.
4. Status travels in `zoo/wt500_fig3cfg/stokes/STATUS.md`: one line per
   shard (id, state, records, shipped-at, verified-at), committed and
   pushed after every wave. The manager verifies arrivals on the Delta side
   and writes verification results back the same way.
