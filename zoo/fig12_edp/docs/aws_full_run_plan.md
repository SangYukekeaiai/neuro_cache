# AWS full-run plan: Fig. 12 EDP, all benchmarks, 500 samples, one day

Goal: the complete EDP campaign - 559 kept architecture x layer cases x 500 samples x 3 arms - finished within one calendar day on AWS, with the agent team (Claude Code manager + codex impl via peon-code) operating the run remotely. Measured baseline (Stokes, 2026-11-14): one full 1-sample sweep = 15.2 core-hours, mean task 98 s, max 25.6 min; checkpoints ~3 GB per sweep.

Total compute: ~7,600 core-hours. Fleet sized for ~12 h wall; one-day end-to-end including setup.

## 1. Account, payment, quotas (do these first; quota approval has lead time)

1. AWS account with a credit/debit card on file (Billing -> Payment methods). Spot usage bills to the same card hourly in arrears. Set a Budget alert (Billing -> Budgets): $500 threshold, email alert, so a runaway fleet cannot surprise you. If the lab has AWS education/research credits, they apply automatically once redeemed (Billing -> Credits).
2. Service Quotas -> EC2: request **"All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests" >= 1024 vCPUs** in your chosen region (default is often 5-640; approval minutes to a day). Also "Running On-Demand Standard instances" >= 256 vCPUs as the fallback path.
3. Region: pick one near Delta for transfer (us-east-2 / us-east-1). Everything below is region-local.
4. Create an SSH key pair (EC2 -> Key Pairs) and a security group allowing inbound SSH (port 22) from your IPs only.
5. S3 bucket, e.g. `s3://<yourname>-neurocache-fig12/`. IAM instance role `fig12-runner` with S3 read/write on that bucket only; attach to all instances.

## 2. Fleet

| Role | Instance | Count | Why | Est. spot |
|---|---|---|---|---|
| Workers | **r7a.48xlarge** (192 vCPU, 1536 GB) | 4 (spot) | memory-optimized: all 192 cores stay busy at ~8 GB/task average; the 64 GB and 120 GB tiers pack without starving vCPUs | ~$4-6/box-h |
| Head | m7a.xlarge (4 vCPU, 16 GB) | 1 (on-demand) | orchestration, agents, collection; survives spot churn | ~$0.23/h |

Wall estimate: 7,600 core-h / 768 cores x 1.2 overhead = **~12 h compute**; +2-4 h setup/staging; +1 h stage 2/figures. Budget: **~$250-350 spot** (on-demand fallback ~$600-700). To compress to ~8 h, use 6 workers (same total cost, higher parallel burn).
AMI: Ubuntu 22.04 LTS (or Amazon Linux 2023). 200 GB gp3 root per worker; head node mounts a 2 TB gp3 volume (~$15 for the week) at `/data` for checkpoints, shared to workers via NFS (or each worker keeps local checkpoints and syncs durable rows to S3 - simpler, preferred).

Spot interruption policy: the per-case fingerprint resume makes every task idempotent. A reclaimed box loses only in-flight tasks; a replacement re-runs unfinished indices. Launch workers in a Spot Fleet / ASG with `capacity-optimized` allocation so replacements are automatic.

## 3. Inputs to deploy

| Input | Size | Source -> destination |
|---|---|---|
| Repo (code + vendored archx + model + configs + docs) | ~100 MB | `git clone git@github.com:SangYukekeaiai/neuro_cache.git -b wcache-rebuild-phase-a` (add a read-only deploy key or fine-grained PAT to the repo first) |
| Input traces, ALL 500 samples | **33 GB** (A02 1.4G, A04 1.7G, A07 20G, A08 2.8G, B09 1.3G, C01 6.0G) | Delta -> S3 once (`aws s3 sync /work/nvme/bebv/yyu9/input_trace_delta/ s3://.../input_trace_delta/`, ~30-60 min from Delta), then S3 -> each worker's local NVMe/EBS at boot (~10 min at 10 Gbps) |
| Schedule manifest | in repo (`zoo/wt500_fig3cfg/outputs/manifest.json`) | with the clone |
| Energy tables | in repo (`zoo/archx/zoo/snn_edp/characterization/`) | with the clone |

Nothing else is fetched: the vendored archx installs from the clone (`pip install -e ./zoo/archx`), per the T93 single-upload design. The Delta source dataset is never modified (read-only sync).

## 4. Environment per node (workers and head identical)

```bash
sudo apt-get update && sudo apt-get install -y build-essential cmake git tmux awscli nodejs npm
curl -L micromamba.snakepit.net/api/micromamba/linux-64/latest | tar -xj bin/micromamba
micromamba create -n fig12 python=3.12 numpy pandas matplotlib -y
git clone <repo> ~/neuro_cache_wcache && cd ~/neuro_cache_wcache
CARGO_BUILD_JOBS=1 micromamba run -n fig12 pip install -e ./zoo/archx   # prebuilt core or local build
# native simulators (cachesim MUST include the NextLine policy, commit 81ee1e5+):
cmake -S src/lays/cachesim/native -B build/cachesim && make -C build/cachesim -j8
# nocsim likewise; install binaries to zoo/fig12_edp/demo/native_build/
aws s3 sync s3://.../input_trace_delta/ /data/input_trace_delta/
```

**Gate before any campaign task** (same bar as Stokes): run the 5-fixture x 3-arm validation from the vendored model against `reference_t84_results.csv`; require max relative error < 1e-9 and `archx.__file__` inside the clone. A node that fails the gate runs nothing.

## 5. Campaign configuration (what you are checking)

- **Cases**: the 559 kept feasible pairs - 113 kept layers of 151 (38 FC layers excluded, decision B; rule and per-layer dimensions in `input_trace_and_layers.md`) x 5 architectures (spinalflow, ptb, loas, gustavsnn, prosperity), minus 6 infeasible Prosperity A08 schedules. Benchmarks: A02 spikformer, A04 SDT, A07 spikingLM, A08 vgg16-T32, B09 loas-vgg16 + loas-resnet19, C01 2x DVS.
- **Samples**: 000-499 (all captured samples).
- **Arms** (3 per case-sample):
  - `spad`: nocsim event simulation; scratchpad hierarchy (per-arch l1_weight_spad + shared GB).
  - `cacheA`: cachesim with `zoo/fig12_edp/configs/production_cache_a.json` (L1 next_access d4; L2 distance_aware d1, touch-threshold 9), SHA `a08ec1f8...` - byte-pinned by energy_driver.
  - `cacheB`: cachesim with `configs/production_cache_b.json` (**next_line d1 at BOTH levels**, T96), SHA `4d89ff61...` - byte-pinned.
- **Hardware model**: vendored `zoo/archx/zoo/snn_edp/hardware.json`, 98 operation rows (SHA `b640ca5a...`): 48 logic rows (composition-priced), 41 physical-model rows (cacti_fn SRAM/cache, cacti7 DDR4, ASAP7 wire), **9 prefetch rows excluded = zero by decision** (next_access/distance logic+state, both tag probes, both next_line adders, distance metadata). Frequency 500 MHz everywhere; EDP time base = cycles/500 MHz.
- **Pricing**: Stage-B tables - primary `energy_table_nangate45.json` (SHA `2d8e4ea0...`, 45nm interim, energy-only mixed-technology caveat); `energy_table_dummy.json` (SHA `892e6e2c...`) available for cross-checks. ASAP7 table replaces these later by reprice only - no recompute.
- **Per-task environment**: `ARCHX_DISABLE_PERFORMANCE_CACHE=1`, BLAS/OMP thread caps = 1, node-local TMPDIR, trace deleted after durable commit (provenance in generation.json).
- **Memory tiers** (per case, from the Stokes tier manifest): default 16 GB; 50 heavy cases 64 GB; 4 SpinalFlow cases 120 GB. On r7a these are just scheduler hints for the packer.

## 6. Execution pipeline

Stage 1 (counts, no table): per (case, sample): trace gen (`lays.weight_trace_gen`, stream) -> analytic counts -> nocsim + cachesim A + cachesim B -> `run.py count --case <dir> --out <dir>/archx_artifacts/<sample>/counts` -> commit durable rows -> delete trace. 279,500 tasks.

Orchestration (no Slurm on EC2): a static shard file `shards.txt` lists all (case, sample) indices; each worker runs `worker.sh N_WORKERS WORKER_ID` - a GNU-parallel loop over its shard (`idx % N == id`), ~190 concurrent slots per box, memory-aware packing by tier, writing per-task status rows. Idempotent: finished (case,sample) short-circuits on the result fingerprint. Durable rows sync to S3 every 15 min (`aws s3 sync` of results only, checkpoints stay local).

Stage 2 (price + collect + figures, head node, ~1 h): `run.py price` with the NG45 table over all checkpoints -> `results.csv`, `whole_model.csv` (now with 500-sample statistics: per-case mean/CI columns) -> latency/energy/EDP overview figures + breakdown analyses -> S3. Stage-A byte-identity check before/after pricing, as always.

Checkpoint lifecycle at this scale: after a case-sample's priced rows are committed and synced, its count checkpoint is deleted (extends the trace delete-after-commit discipline; keeps local disk ~bounded instead of 1.5 TB).

## 7. Agent team on the head node (Claude CLI + peon-code)

```bash
npm install -g @anthropic-ai/claude-code          # or the native installer
claude login                                       # or export ANTHROPIC_API_KEY=sk-ant-...
# codex CLI for impl, if used identically to the local team; otherwise run impl as a second claude instance
mkdir -p ~/.local/bin && scp delta:~/.local/bin/peon-code ~/.local/bin/ && chmod +x ~/.local/bin/peon-code
cp <repo>/.peon-code-task.md ~/.peon-code-task.md  # fresh board, or start empty with the protocol header
tmux new-session -s fig12-aws \; split-window -h \; split-window -v
# pane 0: manager (claude), pane 1: archie (claude reviewer), pane 2: impl (codex or claude)
```

Kickoff prompt for the manager pane (adjust paths):

```
You are the manager of the peon-code team for the Fig.12 EDP full run on this
EC2 fleet. Board: ~/.peon-code-task.md (one row per task; edit only your own
rows). impl is pane %2, reviewer is pane %1; message via
~/.local/bin/peon-code send <pane> - <<'EOF' ... EOF.
Repo: ~/neuro_cache_wcache (branch wcache-rebuild-phase-a). Plan of record:
zoo/fig12_edp/docs/aws_full_run_plan.md - follow it exactly.
Sequence: (1) verify env gate (5-fixture validation < 1e-9, archx.__file__
pinned) on every node and report; (2) stage-1 shard run across workers,
monitor, retry failed tasks once in the next memory tier; (3) HOLD, report
per-case completeness to the boss; (4) on boss go: stage-2 NG45 pricing,
collection, figures, S3 sync; (5) teardown checklist. Constraints: never
modify /data/input_trace_delta; ARCHX_DISABLE_PERFORMANCE_CACHE=1 and thread
caps everywhere; archive-before-delete; no simulator rerun during pricing.
Report progress every 30 minutes.
```

Operating notes: the manager drives workers over SSH (fleet-internal keys), uses the board exactly as on Delta, and holds at the same two boss checkpoints (post-validation, post-stage-1). Claude API usage for a day of supervision: a few dollars.

## 8. Run-day sequence (times from fleet launch)

| T+ | Step |
|---|---|
| -1 day | Account, card, quota request, S3 bucket, deploy key; `aws s3 sync` of the 33 GB traces from Delta |
| 0:00 | Launch head + 4 spot workers (Spot Fleet, capacity-optimized) |
| 0:15 | Env build on all nodes (parallel), native builds, trace sync from S3 |
| 1:00 | Validation gate on every node -> manager reports -> **boss checkpoint 1** |
| 1:15 | Stage-1 shards launched (279,500 tasks, ~760 concurrent) |
| ~13:00 | Drain + straggler retries -> completeness report -> **boss checkpoint 2** |
| ~13:30 | Stage-2 pricing + collection + figures on head |
| ~14:30 | Results on S3 + pulled to Delta; teardown: terminate workers, keep head 1 h for inspection, then terminate; S3 retains everything |

## 9. Deliverables

`s3://.../results_full500/`: stage-1 accounting + per-case status, `results.csv`, `whole_model.csv` (with per-case sample statistics), `model_latency_overview`, `model_energy_overview_ng45`, `model_edp_overview_ng45`, breakdown analyses, provenance (config SHAs, table SHAs, commit, fleet manifest, per-node validation records). Mirror to `zoo/fig12_edp/stokes/../aws_results_full500/` on Delta and commit the curated set.

## 10. Risks and their handling

- Spot reclaim: idempotent resume; capacity-optimized fleet auto-replaces; worst case wall grows, cost does not.
- Quota not granted in time: run at whatever vCPU quota exists (wall scales inversely) or on-demand fallback (2x cost).
- A07 heavy tail (20 GB traces, biggest memory): pre-assigned to dedicated shard lanes so it starts early, not last.
- Trace staging surprises: sizes above are measured; A07 dominates. Workers only copy the benchmarks their shard needs if disk is tight.
- The known pre-existing repo items (parked run_ec2 suite, grid golden test) are NOT used by this plan - orchestration is the shard worker, not run_ec2.
