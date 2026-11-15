# AWS step-by-step: account, payment, and fleet setup for the Fig. 12 full run

Companion to [aws_full_run_plan.md](aws_full_run_plan.md). Every step has its console link. Region used throughout: **us-east-2 (Ohio)** - swap `us-east-2` in URLs if you choose another. Steps 1-6 are one-time account work (~30 min + quota wait); steps 7-12 are run-day.

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

1. Budget alert: https://console.aws.amazon.com/billing/home#/budgets -> Create budget -> Cost budget -> amount **$500** -> alert at 50/80/100% to your email.
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
pip install --user awscli
aws configure   # paste the access key from step 2.3; region us-east-2; output json
aws s3 sync /work/nvme/bebv/yyu9/input_trace_delta/ s3://<bucket>/input_trace_delta/ --no-progress
```

4. GitHub deploy key so instances can clone the private repo: repo -> https://github.com/SangYukekeaiai/neuro_cache/settings/keys -> Add deploy key (read-only) -> paste a fresh public key generated for the head node.

## 7. Launch the head node (5 min)

https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#LaunchInstances:

- Name `fig12-head`; AMI: Ubuntu Server 22.04 LTS (64-bit x86); type **m7a.xlarge**; key `fig12-key`; security group `fig12-ssh`; storage 200 GB gp3; Advanced -> IAM instance profile `fig12-runner`.
- Launch -> note its public IP -> `ssh -i fig12-key.pem ubuntu@<ip>`.

## 8. Launch the 4 spot workers (10 min)

Simplest path - launch template + fleet:

1. Template: https://us-east-2.console.aws.amazon.com/ec2/home?region=us-east-2#CreateTemplate: -> name `fig12-worker` -> same AMI/key/SG/role -> type **r7a.48xlarge** -> storage 300 GB gp3 -> Advanced: Purchasing option "Spot", request type "one-time", interruption behavior "terminate".
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
