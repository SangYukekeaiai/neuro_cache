# eval_scaling campaign state - SUPERSEDED

**This file described a campaign that no longer exists.** It is kept, rather
than deleted, for one unverified item about the Stokes working tree that is
recorded nowhere else (below). The Slurm array it was kept for is **cancelled
by user decision of 2026-11-16**.

**The current design is `plan.md`**, with the chain in `execution_plan.md`.

## What changed

The user redefined the figure: five architectures, the LoAS VGG16 workload,
the whole layer set, a memory-capacity sweep at 1x/2x/4x, **three series**
(single-node spad, multi-node spad, multi-node cache), and **performance and
DRAM traffic** as the two metrics. The previous campaign was LoAS-only,
two-series, swept x1-x16, and reported utilization.

The workload was specified as CIFAR-100 and then settled on the existing
CIFAR-10 `B09/loas_vgg16_T4_n500` capture, because no CIFAR-100 LoAS VGG16
checkpoint exists in the tree and the scaling claim does not depend on the
label count (`plan.md` section 1, Q1). **This file's two-series decision is
overridden**: the cache series is back in (`plan.md` Q4, 7.7).

`zoo/eval_scaling/outputs/` and `zoo/eval_scaling/configs/` were deleted from
the working tree on user command - the 130 S1 schedule solves, `cases.txt`,
the manifests, and the 13 S0 config files. 284 tracked deletions,
uncommitted, recoverable from git history. **Nothing under either directory
is an asset of the current plan**, which regenerates everything it consumes
from S0.

The harness scripts are untouched and are still the framework components the
new plan names: `make_configs.py`, `gen_inputs.py`, `run_case.py`,
`run_array.sbatch`, `aggregate.py`, `plot.py`, `test_hardening.py`,
`wt_gen_inputs_snapshot.py`.

## The array: cancelled

The 130-task Slurm array dispatched for the previous campaign is **cancelled
on user decision** (`plan.md` Q9). There is no Stokes access from Delta, so
the user runs `scancel` there. **Nothing in the current plan reads its rows**,
including as a cross-check - the earlier suggestion that its single-node rows
could confirm the schedule-invariance finding for free is withdrawn with it,
and `plan.md` section 3 is re-derived in S1b instead.

## Still live, and actionable

- **Stokes working-tree note, reported but never verified here.** To unblock
  a `git pull` on Stokes, 9 untracked wt500 Stokes files were moved to
  `~/untracked_backup_20261116/` and local deletions were stashed as
  `stash@{0}`. Nothing was deleted. Recovering either set is a `git stash pop`
  and a move back from that directory.

## Resolved, so it is not carried forward

The 12-versus-13 layer discrepancy this file left open is settled in
`plan.md` step I2: **12 is the count of 3x3 convolutions and 13 includes the
1x1 GEMM classifier head**, per
`zoo/wt500_fig3cfg/layer_dim_coverage.md:194` (1 GEMM + 12 conv). The two
numbers were never a disagreement about which layers exist.
