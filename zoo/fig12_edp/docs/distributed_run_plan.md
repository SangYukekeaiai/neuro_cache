# Distributed full run: Stokes starts now, AWS joins when quota lands

Supplements [aws_full_run_plan.md](aws_full_run_plan.md). Goal: zero waiting on the AWS quota case - Stokes begins the 500-sample campaign immediately; the AWS fleet joins whenever it becomes available; both sides draw from one ledger until 500 samples are complete.

## Work unit and split rule

Unit: one **sample-sweep** = all 559 kept cases x 3 arms for one sample index (measured 15.2 core-h, ~3 GB checkpoints). 500 units total.

Split: **burn from both ends**. Stokes claims ascending blocks (000-009, 010-019, ...); AWS claims descending blocks (490-499, 480-489, ...). A side claims a block only in the ledger, runs it, prices it, marks it done. The campaign ends when claimed-done blocks cover 500 samples; the meeting point floats with actual throughput, so no pre-commitment is ever wrong.

Ledger: `zoo/fig12_edp/stokes/full500_ledger.json` in the repo (single writer: the manager, on Delta; both sides report block completion to the manager). Entries: {block, side, claimed_at, done_at, rows_sha}. Per-case fingerprints make accidental double-computation harmless (idempotent skip), so a ledger mistake costs minutes, not correctness.

## Stokes side (starts immediately)

- Rolling submission: one Slurm array per sample (559 tasks, tiered 16G/64G/120G as in the demo), up to 15 samples in flight (stays under MaxJobCount 10000 and the 250-job association cap governs actual concurrency).
- Throughput: ~250 cores sustained = ~16 sample-sweeps/day if the queue stays friendly (measured 42 min/sweep at full cap; budget 90 min average for queue sharing).
- **Disk discipline (mandatory)**: after each sample's 559 cases complete, immediately run stage-2 NG45 pricing for that sample, commit durable priced rows + accounting to `full500/rows/sample_XXX/`, verify, then DELETE that sample's count checkpoints and case scratch. Steady-state footprint stays ~10-20 GB against the ~878 GB quota. (Durable rows per sample are ~50 MB.)
- Stage-A/stage-B equivalence: unchanged repo commit (fc30d64 or later), config SHAs a08ec1f8/4d89ff61, NG45 table 2d8e4ea0, fixture gate already passed on Stokes.

## AWS side (joins on quota approval)

Exactly per aws_full_run_plan.md, with one change: workers pull descending blocks from the manager instead of a fixed shard list. On first launch the fleet claims blocks 49x downward. Same commit, same SHAs, same per-node fixture gate before any block.

## Merge and finish

- Both sides produce identical-schema per-sample row files. Final collection (anywhere, ~minutes): concatenate 500 sample row-sets -> results_full500.csv -> whole_model with per-case mean/CI across samples -> latency/energy/EDP figures.
- Completeness check: exactly 500 distinct sample indices, each with 559 cases x 3 arms; any hole re-runs as a single block.

## Timeline scenarios

| Scenario | Stokes does | AWS does | Campaign wall |
|---|---|---|---|
| Quota approved in ~4 h | ~5 samples | ~495 | **~14-16 h total** |
| Approved in ~24 h | ~16-20 | ~480 | **~30-34 h** |
| Approved in ~48 h | ~35-40 | ~460 | ~2.5 days |
| Never approved (worst) | all 500 | none | ~1.5-2 days of pure compute; realistically 2.5-3 days with queue sharing |

Cost: AWS portion scales with its share (~$0.6-0.7 per sample-sweep on spot); e.g. the 24 h scenario costs ~$300, the never-approved scenario $0.

## Operating protocol

The Delta manager (this session) owns the ledger and the boundary; impl runs the Stokes side now and the AWS side later from the head node. Boss checkpoints stay: (1) first Stokes sample completes + prices cleanly (validates the rolling delete discipline before it runs unattended), (2) completeness report before final collection. Progress reports every ~2 h or every 3 blocks, whichever first.
