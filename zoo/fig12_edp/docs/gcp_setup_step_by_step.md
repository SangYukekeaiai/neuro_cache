# GCP fast-start: get fleet capacity running TODAY for the Fig. 12 full run

Companion to [aws_setup_step_by_step.md](aws_setup_step_by_step.md) and [distributed_run_plan.md](distributed_run_plan.md). GCP is used because its quota bumps are usually auto-approved in minutes, unlike the pending AWS Support case. Region throughout: **us-east1 (South Carolina)**, GCP's largest capacity pool with the lowest prices. If a step's link lands on the wrong project, check the project selector in the top bar first.

The campaign side needs ZERO changes: a GCP worker is just another machine that claims descending blocks from the ledger, exactly like the planned AWS fleet. Per-case fingerprints make accidental overlap with Stokes harmless.

## 0. The fast path (your first hour, in order)

1. Sign in / create account (step 1) and **upgrade billing to paid** (step 2). Without the upgrade, quotas stay at trial level and increase requests are refused.
2. **Immediately** file the quota bump (step 4). It usually auto-approves in minutes; file it first so it processes while you do everything else.
3. While waiting: create the bucket and start the 33 GB trace upload from Delta (step 6, the long pole, ~30-60 min).
4. Launch the first worker inside whatever default quota already exists (step 7). Do not wait for the bump.
5. Software + fixture gate (steps 8-9), then tell the manager: the descending block claim is recorded and the node starts at sample 499.

## 1. Account and project (5 min)

1. Go to https://console.cloud.google.com/ and sign in with a Google account. A personal Gmail is safest; a university Workspace account may have project creation disabled by its admin.
2. First visit shows a country + terms-of-service agreement. Accept it.
3. If a free-trial banner offers $300 credits, accept (credits apply to the bill either way).
4. Create a project: https://console.cloud.google.com/projectcreate , name `neurocache-fig12`, location "No organization", Create. (Or reuse the auto-created "My First Project"; the name is cosmetic.)
5. Make sure the top-bar project selector shows this project for everything below.

## 2. Upgrade billing to paid (2 min, REQUIRED)

1. https://console.cloud.google.com/billing , open your billing account (created automatically with the trial).
2. Click the **Upgrade** button (blue banner at the top of the console, or Billing overview page, labeled "Upgrade" or "Activate full account"). Confirm.
3. What changes: trial hard caps are removed and quota increase requests become possible. Your card is charged only for usage, and any remaining trial credits are consumed first.
4. Budget alert: https://console.cloud.google.com/billing/budgets , Create budget, scope = this project, Amount = $500, alerts at 50/80/100% to your email.

## 3. Enable the Compute Engine API (2 min)

Open https://console.cloud.google.com/compute . The first visit shows "Compute Engine API: Enable". Click Enable and wait ~1 min. (CLI: `gcloud services enable compute.googleapis.com`.)

## 4. Quota bump (file FIRST; usually minutes to approve)

1. Go to https://console.cloud.google.com/iam-admin/quotas (IAM & Admin -> Quotas & system limits).
2. In the Filter box type `Preemptible CPUs` and press Enter. Find the row with Service = "Compute Engine API", Dimensions = `region: us-east1`.
3. Tick the row's checkbox, click **Edit quotas** (top of the page). A side panel opens: set New value = **512**, Next, fill name/email if asked, justification:
   > Academic computer-architecture simulation campaign (memory-bound Monte-Carlo sweep for an ASPLOS paper figure), N2D high-memory spot instances in us-east1 for 1-2 days.
   Submit.
4. Repeat for these quotas, same region `us-east1`:
   | Quota (filter text) | New value | Why |
   |---|---|---|
   | `Preemptible CPUs` | 512 | spot worker cores (the cheap capacity) |
   | `CPUs` | 128 | on-demand fallback; also the cap for some SKU paths |
   | `N2D CPUs` (if it exists as its own row) | 512 | the machine family below |
   | `Persistent Disk SSD (GB)` (only if its default < 2000) | 5000 | 300 GB boot disk per worker |
5. Track status: https://console.cloud.google.com/iam-admin/quotas;tab=increase_requests . Approval mails arrive per quota; partial approvals are normal. If 512 routes to manual review, immediately file a smaller ask (128), which nearly always auto-approves, and re-request higher later.

## 5. SSH key (3 min; skip if you will only use the browser SSH button)

The in-console **SSH button needs no key setup** and is the fastest way in. For terminal SSH from your laptop or Delta:

1. Use an existing `~/.ssh/id_ed25519.pub` or make one: `ssh-keygen -t ed25519`.
2. https://console.cloud.google.com/compute/metadata?tab=sshkeys , Add SSH key, paste the pub key. The key's trailing comment (`user@host`) becomes the login username on every VM in the project.
3. The default VPC's `default-allow-ssh` firewall rule already permits port 22 from anywhere, so no firewall work is needed.

## 6. Bucket + trace upload (start early; ~45 min, the long pole)

1. Create bucket: https://console.cloud.google.com/storage/create-bucket , name `<yourid>-neurocache-fig12` (globally unique, lowercase), Region = `us-east1`, Standard storage, Uniform access control, Create.
2. No service-account setup is needed: VMs will run as the project's default compute service account, which can read/write this bucket within the same project.
3. Upload traces from Delta (dt-login02). One-time `gcloud` CLI install + login:

```bash
cd ~ && curl -sSL https://sdk.cloud.google.com > /tmp/gcl.sh && bash /tmp/gcl.sh --disable-prompts --install-dir=$HOME/gcloud-sdk
export PATH=$HOME/gcloud-sdk/google-cloud-sdk/bin:$PATH   # add to ~/.bashrc too
gcloud auth login --no-launch-browser   # prints a URL; open it in your LOCAL browser, paste the code back
gcloud config set project neurocache-fig12
gcloud storage cp -r /work/nvme/bebv/yyu9/input_trace_delta gs://<bucket>/input_trace_delta
```

   The source dataset stays read-only; `cp` never modifies it. ~33 GB takes 30-60 min from Delta. Verify afterwards:

```bash
gcloud storage du -s gs://<bucket>/input_trace_delta   # expect ~33 GiB
```

4. Repo deploy key so VMs can clone the private repo: on your machine `ssh-keygen -t ed25519 -f fig12_deploy -N ""`, then https://github.com/SangYukekeaiai/neuro_cache/settings/keys , Add deploy key, title `gcp-fig12`, paste `fig12_deploy.pub`, leave write access OFF. Keep `fig12_deploy` (the private half) to paste onto nodes in step 8.

## 7. Launch the first worker (5 min; inside default quota, before the bump lands)

Console path: https://console.cloud.google.com/compute/instancesAdd

- **Name**: `fig12-gcp-1`.
- **Region/zone**: `us-east1`, zone Any (or `us-east1-b`; if spot capacity is missing at launch, retry with `-c` or `-d`).
- **Machine configuration**: General purpose, series **N2D**, type **n2d-highmem-32** (32 vCPU, 256 GB). 256 GB covers every memory tier including the four 120G-solo SpinalFlow cases. If your not-yet-bumped quota refuses 32 vCPUs, start with `n2d-highmem-16` (128 GB, skips 120G-solo cases) or even `n2d-highmem-8`, and launch bigger nodes after approval.
- **Availability policies** (under Advanced options -> Management, or the "VM provisioning model" dropdown): **Spot**. On VM termination: **Stop**. Spot n2d-highmem-32 in us-east1 is roughly $0.4-0.7/h vs ~$1.9/h on-demand (live price shown in the right-hand cost panel).
- **Boot disk**: Change -> Ubuntu -> **Ubuntu 22.04 LTS x86/64**, Balanced persistent disk, **300 GB**.
- **Identity and API access**: default compute service account, Access scopes = **Allow full access to all Cloud APIs** (simplest; this grants the bucket read/write).
- Create. The instance row shows its External IP.

Connect: click **SSH** in the instance row (browser terminal, zero setup), or `ssh <keycomment-user>@<external-ip>` if you did step 5.

CLI equivalent for later repeats (Cloud Shell or anywhere gcloud is logged in):

```bash
gcloud compute instances create fig12-gcp-2 \
  --zone=us-east1-b --machine-type=n2d-highmem-32 \
  --provisioning-model=SPOT --instance-termination-action=STOP \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=300GB --boot-disk-type=pd-balanced \
  --scopes=cloud-platform
```

## 8. Software on every node (~20 min, copy-paste blocks)

Same recipe as [aws_full_run_plan.md](aws_full_run_plan.md) section 4, with GCS in place of S3. Run as the login user:

```bash
# base packages
sudo apt-get update && sudo apt-get install -y build-essential cmake git tmux

# micromamba + python env
cd ~ && curl -L micromamba.snakepit.net/api/micromamba/linux-64/latest | tar -xj bin/micromamba
./bin/micromamba create -n fig12 python=3.12 numpy pandas matplotlib -y

# repo via deploy key (paste the private half from step 6.4 into ~/.ssh/fig12_deploy, chmod 600)
GIT_SSH_COMMAND="ssh -i ~/.ssh/fig12_deploy -o IdentitiesOnly=yes" \
  git clone git@github.com:SangYukekeaiai/neuro_cache.git -b wcache-rebuild-phase-a ~/neuro_cache_wcache
cd ~/neuro_cache_wcache
~/bin/micromamba run -n fig12 pip install -e ./zoo/archx

# native simulators: ALWAYS build on the node, never copy binaries (GLIBC incident)
cmake -S src/lays/cachesim/native -B build/cachesim && make -C build/cachesim -j8
cmake -S src/lays/nocsim/native  -B build/nocsim  && make -C build/nocsim  -j8
# install into the path the model expects:
mkdir -p zoo/fig12_edp/demo/native_build && cp build/cachesim/cachesim_run build/nocsim/nocsim_run zoo/fig12_edp/demo/native_build/

# traces from the bucket (gcloud is pre-installed on GCP Ubuntu images)
mkdir -p ~/data && gcloud storage cp -r gs://<bucket>/input_trace_delta ~/data/input_trace_delta
```

Environment for every campaign task (the worker script sets these, listed for manual runs):
`ARCHX_DISABLE_PERFORMANCE_CACHE=1`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, node-local `TMPDIR`.

## 9. Validation gate (MANDATORY before any campaign work)

Same bar as Stokes and the AWS plan: the 5-fixture x 3-arm validation against `reference_t84_results.csv`, max relative error < 1e-9, and `archx.__file__` resolving inside the clone. The runner is in the repo exactly as used on Stokes (see `stokes_demo_run.md`); a node that fails the gate runs nothing. Keep the gate log; the manager records its digest with the block claim.

## 10. Join the campaign

Report to the manager (Delta session) that the gate passed. The manager then:

1. Records the descending block claim in `zoo/fig12_edp/stokes/full500_ledger.json` (first AWS/GCP block: **490-499**, then 480-489, downward).
2. Confirms the config/table SHAs the node must match: configs `a08ec1f8`/`4d89ff61`, NG45 table `2d8e4ea0`, repo commit fc30d64 or later.

The node then runs its block descending from sample 499: per (case, sample) trace gen -> counts -> three arms -> durable commit -> delete trace, with per-sample Stage-2 NG45 pricing and checkpoint deletion after commit (the same lifecycle as Stokes). Durable rows sync to `gs://<bucket>/results_full500/rows/sample_XXX/` after each sample.

## 11. Spot interruptions

A preempted VM shows as "Stopped" in the instance list. Nothing is lost: checkpoints and fingerprints live on its persistent disk, so just select it -> Start, and the worker resumes, re-running only in-flight cases. For a fleet, create an instance template + managed instance group (https://console.cloud.google.com/compute/instanceGroups) with target size N and GCP restarts/replaces preempted nodes automatically.

## 12. Monitor cost and progress

- Spend: https://console.cloud.google.com/billing/reports (near-real-time, filter by project). Sanity: N workers x ~$0.5/h.
- Fleet: https://console.cloud.google.com/compute/instances
- Progress: per-sample row files appearing under `gs://<bucket>/results_full500/rows/` and the manager's ledger updates.

## 13. Teardown (do not skip)

1. Delete all instances: instances page -> select all -> Delete. Confirm "also delete boot disk" is checked (default for boot disks created with the VM).
2. Check for orphan disks: https://console.cloud.google.com/compute/disks (should be empty after deletes).
3. Pull final results to Delta: `gcloud storage cp -r gs://<bucket>/results_full500 <delta-path>` then keep the bucket (~$0.7/month) until the paper is done; delete it after.
4. Next day, confirm in Billing reports that spend flatlined.

## Cost expectation

| Scenario | Est. |
|---|---|
| 1x n2d-highmem-32 spot (~25 samples/day) | ~$10-17/day |
| 16x n2d-highmem-32 spot (512 vCPU), remainder in about a day | ~$150-270 total |
| Same capacity on-demand (if the preemptible quota lags) | ~3x those numbers |
| Bucket + egress of results (~5 GB) | ~$2 |
