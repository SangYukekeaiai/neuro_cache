# AWS step-by-step: account, payment, and fleet setup for the Fig. 12 full run

Companion to [aws_full_run_plan.md](aws_full_run_plan.md). Every step has its console link. Region used throughout: **us-east-2 (Ohio)** - swap `us-east-2` in URLs if you choose another. Steps 1-6 are one-time account work (~30 min + quota wait); steps 7-12 are run-day.

**Reading conventions, learned the hard way (2026-11-16):**

- `<anything-in-angle-brackets>` is a placeholder: replace the **whole token,
  brackets included**, with your value. Pasting it literally makes the shell
  parse `<bucket>` as a file redirection (`zsh: no such file or directory: bucket`).
- Before touching EC2 pages, check the **region selector in the console's
  top-right corner** says Ohio (us-east-2). Instance types, key pairs,
  security groups and AMIs are all per-region; "it's not in the list" is
  almost always the wrong region.
- "Skip X" in a console flow means "leave the page's checkboxes empty and
  press Next", not a button named Skip.

## 1. Create the AWS account (skip if the lab has one)

1. Go to https://signin.aws.amazon.com/signup?request_type=register
2. Email + account name -> verify email code -> set root password.
3. Contact info: choose "Personal" unless the lab provides a business tax profile.
4. **Payment**: enter a credit/debit card (it is charged after usage, monthly or when thresholds hit). A temporary $1 verification hold appears and drops off.
5. Identity verification by SMS/voice code.
6. Support plan: choose **Basic (free)**.
7. Sign in to the console: https://console.aws.amazon.com/

Docs: https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-creating.html

## 2. Secure the account and create a working user (10 min)

1. Turn on MFA for root: https://console.aws.amazon.com/iam/home#/security_credentials -> "Assign MFA device" (any authenticator app).
2. Create an admin IAM user for daily work (don't use root): https://console.aws.amazon.com/iam/home#/users -> Create user -> name `fig12-admin` -> check "Provide user access to the AWS Management Console" -> attach policy `AdministratorAccess` -> create, save the sign-in URL/password.
3. Create an access key for CLI use: open the user -> Security credentials -> "Create access key" -> use case: CLI -> save `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (shown once).

Docs: https://docs.aws.amazon.com/IAM/latest/UserGuide/getting-started.html

## 3. Billing guardrails (5 min)

0. **If Billing pages show "Access denied" for the IAM user**: sign in as
   **root** once -> https://console.aws.amazon.com/billing/home#/account ->
   "IAM user and role access to billing information" -> Edit -> Activate IAM
   Access -> Update. `AdministratorAccess` alone is not enough without this
   account-level switch.
1. Budget alert: https://console.aws.amazon.com/billing/home#/budgets -> Create budget -> Cost budget -> amount **$500** -> alert at 50/80/100% to your email. (The console may route you to "Billing and Cost Management -> Budgets", hosted under us-east-1 - budgets are global, that is normal. The "Use a template -> Monthly cost budget" shortcut with amount 500 is equivalent.)
2. Billing preferences: https://console.aws.amazon.com/billing/home#/preferences -> enable "Receive Free Tier usage alerts" and PDF invoices by email.
3. (If you have education/research credits) redeem: https://console.aws.amazon.com/billing/home#/credits

Docs: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-create.html

## 4. Request the vCPU quotas (DO THIS FIRST - approval can take minutes to a day)

1. Spot quota: https://us-east-2.console.aws.amazon.com/servicequotas/home/services/ec2/quotas -> search "**All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests**" -> Request increase at account level -> **1024** vCPUs -> short justification: "academic computer-architecture simulation campaign, memory-optimized spot fleet (4-6x r7a.48xlarge) for ~1 day".
2. On-demand fallback quota: same page, "**Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances**" -> **256** vCPUs.
3. Watch status under https://us-east-2.console.aws.amazon.com/servicequotas/home/requests

Docs: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-resource-limits.html

## 5. Key pair and security group (5 min)

1. Key pair: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#KeyPairs: -> Create key pair -> name `fig12-key`, type ED25519, format .pem -> the download is your private key; `chmod 600 fig12-key.pem`.
2. Security group: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#SecurityGroups: -> Create -> name `fig12-ssh` -> inbound rule: SSH, TCP 22, source "My IP" (add Delta's IP 141.142.0.0/16 too if you'll SSH from Delta) -> plus one rule: All traffic, source = this security group's own ID (lets head and workers talk freely).

## 6. S3 bucket and instance role (10 min)

1. Bucket: https://s3.console.aws.amazon.com/s3/bucket/create?region=us-east-2 -> name e.g. `<yourid>-neurocache-fig12` (globally unique), region us-east-2, defaults otherwise.
2. Instance role: https://console.aws.amazon.com/iam/home#/roles -> Create role -> Trusted entity: AWS service / EC2 -> skip managed policies -> name `fig12-runner` -> create. Open it -> Add permissions -> Create inline policy -> JSON:

```json
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:ListBucket"],"Resource":"arn:aws:s3:::<bucket>"},
 {"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::<bucket>/*"}]}
```

3. Upload the traces from Delta (one-time, ~30-60 min for 33 GB). On dt-login02:

```bash
pip install --user awscli        # installs to ~/.local/bin (already on PATH on Delta)
aws configure   # paste the access key from step 2.3; region us-east-2; output json
aws s3 sync /work/nvme/bebv/yyu9/input_trace_delta/ s3://<bucket>/input_trace_delta/ --no-progress
```

`aws configure` is interactive; where no interactive stdin exists (an agent
pane, a script), set the same four values one line each - **value on the same
line as the command**, real keys, not these samples:

```bash
aws configure set aws_access_key_id AKIA................
aws configure set aws_secret_access_key ........................................
aws configure set region us-east-2
aws configure set output json
aws sts get-caller-identity      # must print your account/user ARN before syncing
```

The secret access key is shown exactly once at creation; if it was not saved,
create a fresh key pair (IAM -> Users -> fig12-admin -> Security credentials ->
Create access key) rather than hunting for the old one. Verify the sync
afterwards: `aws s3 ls s3://<bucket>/input_trace_delta/ --recursive
--summarize` - the object count must equal `find <src> -type f | wc -l`
(2026-11-16 campaign reference: 166 objects, ~33 GiB, a few minutes from a
Delta login node).

4. GitHub deploy key so instances can clone the private repo: repo -> https://github.com/SangYukekeaiai/neuro_cache/settings/keys -> Add deploy key (read-only) -> paste a fresh public key generated for the head node.

## 7. Launch the head node (5 min)

https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#LaunchInstances:

The "Launch an instance" page is one long form of collapsible panels. Top to
bottom, touching only what is named here and leaving everything else at its
default:

1. **Name and tags**: Name = `fig12-head`.
2. **Application and OS Images (AMI)**: in the Quick Start row of OS logos,
   click **Ubuntu**. In the AMI dropdown below it pick **Ubuntu Server
   24.04 LTS (HVM), SSD volume type** - 22.04 has rotated out of the quick
   list and 24.04 works identically for this setup. Immediately under the
   dropdown, the **Architecture** selector must read **64-bit (x86)**, never
   Arm: m7a/r7a are x86 machines and an Arm AMI will not boot on them. (To
   match the old doc exactly instead: "Browse more AMIs" -> search
   `ubuntu-jammy-22.04-amd64-server` -> newest result owned by Canonical,
   `099720109477` - but there is no need.)
3. **Instance type**: the panel below the AMI, pre-filled with a free-tier
   `t2.micro`/`t3.micro`. Click the dropdown; a **search box** opens at its
   top; type `m7a.xlarge` and click the match (shows "4 vCPU, 16 GiB
   Memory"). If it is not offered, the region selector (top-right of the
   console) is not on us-east-2.
4. **Key pair (login)**: dropdown -> `fig12-key` (created in step 5).
5. **Network settings**: click **Edit** is NOT needed - just switch
   "Firewall (security groups)" to **Select existing security group** and
   pick `fig12-ssh`. Leave VPC/subnet at default; confirm "Auto-assign
   public IP" shows Enable (the default VPC does).
6. **Configure storage**: change the root volume to **200** GiB, type
   **gp3**.
7. **Advanced details** (collapsed - expand it): scroll to **IAM instance
   profile** -> select `fig12-runner`. This is what lets the node reach the
   S3 bucket without any keys on disk; forgetting it is the most common
   miss on this page. Nothing else in Advanced changes.
8. Right-hand **Summary** panel: number of instances 1 -> **Launch
   instance** -> "Success" banner -> click the instance id (i-...).

First connection:

- Instances table -> select `fig12-head` -> Details tab -> copy **Public
  IPv4 address** (there from launch; reachable once Status checks pass,
  ~2 min).
- From the machine holding the key:
  `chmod 600 fig12-key.pem && ssh -i fig12-key.pem ubuntu@<public-ip>`
  (user is `ubuntu` on Ubuntu AMIs, not ec2-user). A timeout here means the
  SSH rule in `fig12-ssh` does not cover the network you are on - re-check
  step 5's "My IP"/Delta source entries.
- Sanity-check the role from inside the node:
  `aws s3 ls s3://<bucket>/ ` should list the bucket with no configure step -
  credentials arrive via the instance profile.
- Now do step 6.4's deploy key ON this node: `ssh-keygen -t ed25519 -C
  fig12-head-deploy -f ~/.ssh/github_deploy -N ""`, paste
  `~/.ssh/github_deploy.pub` into the repo's Deploy keys (read-only), add a
  `Host github.com / IdentityFile ~/.ssh/github_deploy / IdentitiesOnly yes`
  block to `~/.ssh/config`, verify with `ssh -T git@github.com`.

## 8. Launch the 4 spot workers (10 min)

Simplest path - launch template + fleet:

1. Template: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#CreateTemplate: -> name `fig12-worker` -> then the same panels as step 7 with three differences: type **r7a.48xlarge**, storage **300** GB gp3, and under Advanced details tick **Purchasing option "Spot"** with request type "one-time", interruption behavior "terminate". AMI (Ubuntu 24.04 x86), key `fig12-key`, SG `fig12-ssh` and IAM profile `fig12-runner` are identical to the head's.
2. From the template: Actions -> Launch instance from template -> count **4**. (For auto-replacement on reclaim, instead create an Auto Scaling Group from the template, desired=4, "capacity-optimized" spot allocation: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#AutoScalingGroups: )
3. Current spot price check: https://us-east-2.console.aws.amazon.com/ec2sp/v2/home?region=us-east-2#/spot (r7a.48xlarge typically $4-6/h in us-east-2).

## 9. Software on every node (head first, then workers; ~20 min, scriptable)

Follow [aws_full_run_plan.md](aws_full_run_plan.md) section 4 verbatim: apt packages, micromamba env, repo clone via deploy key, `pip install -e ./zoo/archx`, native cachesim/nocsim builds, `aws s3 sync` of the traces (role credentials are automatic on-instance), then the **5-fixture validation gate** - no node runs campaign work until it passes at < 1e-9.

## 10. Agents (head node)

Plan section 7 verbatim: install Claude Code (https://docs.claude.com/en/docs/claude-code/overview), `claude login` (or `export ANTHROPIC_API_KEY=...` from https://console.anthropic.com/settings/keys), copy `peon-code` from Delta, start the tmux layout, paste the kickoff prompt. The manager runs the campaign from there and holds at your two checkpoints.

## 11. Monitor cost and progress during the run

- Live spend: https://console.aws.amazon.com/costmanagement/home#/cost-explorer (updates ~hourly; spot shows next day in detail, fleet-hours x price is your live proxy).
- Fleet health: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#Instances:
- Progress: the manager's 30-minute reports; raw status rows under `s3://<bucket>/results_full500/status/`.

## 12. Teardown (IMPORTANT - do not skip)

1. Terminate workers (or set ASG desired=0): instances page -> select -> Instance state -> Terminate.
2. After pulling results to Delta, terminate the head too.
3. Delete unattached EBS volumes: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#Volumes:
4. Keep the S3 bucket (storage ~$0.8/month for 33 GB + results); delete when the paper is done.
5. Verify a day later in Cost Explorer that spend has flatlined.

## Cost summary expected

| Item | Est. |
|---|---|
| 4x r7a.48xlarge spot x ~13 h | $210-310 |
| Head m7a.xlarge x ~16 h | ~$4 |
| EBS (5x 300 GB gp3, 2 days) | ~$8 |
| S3 (33 GB + results, 1 month) | ~$2 |
| Data transfer out (results to Delta, ~5 GB) | ~$0.5 |
| **Total** | **~$230-330** |
