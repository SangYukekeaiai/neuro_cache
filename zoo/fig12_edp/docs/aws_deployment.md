# AWS deployment guide: full 500-sample campaign (fastest under $1,500)

Status: for user review 2026-11-12. Goal: full run starts tonight, results
by tomorrow night. Compute needed: ~350-650 node-hours (4-worker/150 GB
units) = generation 300-500 + sims/join (demo run will tighten the sim
share tonight).

## 1. What to buy (fastest inside the budget)

**3x x2idn.32xlarge, on-demand, one region/AZ (us-east-1)**:
each 128 vCPU / 2048 GiB RAM / 2x 1.9 TB local NVMe / ~$13.34 per hr.
- 6 TiB total memory = ~150 concurrent mid-tier workers (37 GB each):
  mid shards done in ~8-14 h; box 3 starts on the heavy tail (140-200 GiB
  serial samples) at hour 0; sims + in-flight join trail each shard.
- Expected wall: **12-20 h**. Cost: 3 x 13.34 x 20 h = $800, worst case
  ~30 h = $1,200. Under budget with margin; spot would be ~70% cheaper
  but can interrupt, wrong trade for this deadline.
- Each box: Ubuntu 24.04 AMI, 300 GB gp3 root volume (~$1/day), your SSH
  keypair, security group allowing inbound port 22 from your IP only.
- Fallback if the 2-TiB quota stalls: r6id.32xlarge (1 TiB, $9.68/hr),
  double the box count.

## 2. How to buy, step by step

1. **Account + quota (DO THIS FIRST, it is the long pole)**: AWS console
   -> Service Quotas -> EC2 -> "Running On-Demand Standard (A, C, D, H,
   I, M, R, T, Z) instances" -> request >= 384 vCPUs (3 boxes x 128).
   New accounts default far lower; approval is hours to days: file
   tonight, note "short-term scientific computing burst" in the request.
2. Console -> EC2 -> Launch instance (x3, or one launch template):
   name epe-run-{1,2,3}; AMI Ubuntu Server 24.04 LTS x86_64;
   type x2idn.32xlarge; your keypair (create + download .pem if none);
   network: default VPC, auto-assign public IP, security group SSH from
   My IP; storage 300 GiB gp3.
3. Note each public IP. Billing starts at launch: do not launch until
   the quota is granted and you are ready to stage.

## 3. How to use it

```
# laptop ~/.ssh/config
Host epe1
  HostName <public-ip-1>
  User ubuntu
  IdentityFile ~/.ssh/<key>.pem
```
VS Code Remote-SSH: install the extension, "Connect to Host" -> epe1:
works out of the box on Ubuntu 24.04 (vscode-server auto-installs).

Per box, in order (T71 run_ec2/ scripts wrap steps 2-5):
1. `sudo apt update && sudo apt install -y build-essential tmux git
   python3-venv rsync` ; format + mount the NVMe:
   `sudo mkfs.ext4 /dev/nvme1n1 && sudo mount /dev/nvme1n1 /scratch`
   (TMPDIR=/scratch; RAID0 the two drives only if one fills).
2. Clone the repo (branch wcache-rebuild-phase-a), untar s2_schedules per
   zoo/wt500_fig3cfg/release/README.md.
3. Stage captures FROM DELTA (outbound, no Duo):
   `rsync -a --progress /work/nvme/bebv/yyu9/input_trace_delta/ \
    ubuntu@<ip>:/scratch/input_trace/` (~33 GB, run once, then box-to-box
   copy for the other two).
4. Build natives locally (`make -B` in src/lays/weight_trace_gen/*/ and
   src/lays/cachesim/native/): NEVER reuse binaries from another machine
   (glibc rule from PAUSE-2026-11-11.md).
5. venv + numpy/PyYAML; `shard_cases.py --shards-file` regenerates cases.
6. Launch: `run_ec2/runner.sh` (T71): memory-tiered worker pool, NVMe
   TMPDIR, per-sample resume, in-flight energy join (energy_table.json +
   per-case counts), durable result rows. Box 1+2 mid shards, box 3 heavy
   tail then overflow. Monitor in tmux; rows sync back to Delta by rsync.

## 4. Claude Code + codex on the box, and the task handoff

1. Claude Code: native installer (`curl -fsSL https://claude.ai/install.sh
   | bash` or the current command from code.claude.com); headless auth:
   run `claude` once, it prints an OAuth URL: open it in your laptop
   browser, paste the code back. (Alternative: `claude setup-token` on
   your laptop, export CLAUDE_CODE_OAUTH_TOKEN on the box.)
2. codex: `npm i -g @openai/codex` (or the official install.sh); headless
   auth: `codex login --device-auth` shows a code+URL for your laptop
   browser. (Fallback: copy ~/.codex/auth.json from Delta: works, but
   keep ONE live session per auth to avoid the SQLite-over-NFS style
   lock mess we hit before: local disk here makes it safe.)
3. Team: copy peon-code (`rsync -a /u/yyu9/peon-code/ epe1:~/peon-code/`),
   start the tmux session with boss (claude) + impl (codex) panes; the
   task board starts FRESH on the box (one row: "run the campaign per
   run_ec2/README") - do NOT share Delta's board over two machines.
4. Handoff content (one message to the box's boss pane): repo commit
   hash, the run_ec2 README, the demo-run results location on Delta for
   cross-checking, and the standing guards (never read temporal_traffic
   as counts; placeholder rows join as 0 + incomplete flag; skip-on-OOM
   for the gustavsnn worst sample).
   Delta side keeps: review backlog, synthesis worklist, paper figures.

## 5. How to stop (and not keep paying)

- **Pause** (keeps EBS, loses NVMe content!): console -> instance ->
  Stop. Billing for compute stops; the 300 GB gp3 costs ~$24/mo until
  terminated. NVMe /scratch is WIPED on stop: sync results to Delta
  first (results are small CSVs; traces are deleted by design).
- **Finish**: rsync results to Delta -> verify row counts -> Terminate
  all three instances (console or `aws ec2 terminate-instances`) ->
  EC2 -> Volumes: confirm no orphaned volumes; Elastic IPs: none
  allocated (we used auto-assign, which detaches on terminate).
- Set a billing alarm NOW: console -> Billing -> Budgets -> $1,500 with
  email alerts at 50/80/100%.

## 6. Timeline to your deadline

- Tonight: quota request + demo wave launches on Delta (independent).
- Tomorrow morning: quota granted -> launch 3 boxes -> stage + build
  (~1-2 h, scripted) -> campaign starts before noon.
- Tomorrow night: 12-20 h wall puts completion at late evening; results
  CSVs rsync to Delta as shards finish, so the figure can build from
  partial data at any point. If the quota is NOT granted by tomorrow
  morning, the fallback is Stokes resume (free, ~35-65 h: misses the
  deadline) or fewer/smaller boxes within whatever quota exists.
