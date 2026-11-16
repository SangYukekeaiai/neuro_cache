# eval_scaling (paper Fig 11): campaign state, 2026-11-16

Record of the campaign's state as of 2026-11-16, logged on boss's request.
Scope: what has been decided, what has run, and where the artifacts are.
Plan of record: `zoo/eval_scaling/docs/execution_plan.md` (commit `cf0e232`).

## Decisions in force

- **Two series only**: single-node vs multi-node. The multi-node *cache*
  series of `plan.md` v2 is dropped.
- **Sweep**: single node, node mapspace COUT 64, `lb` 1-16 MB, against
  16 nodes at COUT 4 with the same total weight storage, counted as
  `16 x lb + GB` (so 16 x 32 KB + 512 KB = 1024 KB matches single x1, and
  the match holds at every multiplier).
- **Workload**: `loas_vgg16`, samples 000-009, 13 valid layers.
- **Utilization**: `U = sum_l C_l / (N * sum_l T_l)`.
- **Traffic**: analytic CoSA weight traffic from the solved schedule is
  primary; nocsim-counted DRAM words are kept as a cross-check diagnostic
  only.
- **Venue**: Stokes; all inputs and outputs under `zoo/eval_scaling/`.

## Stage state

| stage | state | evidence |
|---|---|---|
| S0 configs | done | `zoo/eval_scaling/configs/`, 13 files |
| S1 schedule solves | done, 130/130 `OPTIMAL`, ~15 min on Delta | commit `53f3c1f`; `outputs/cases.txt` 130 rows = 13 layers x {single,multi} x {x1,x2,x4,x8,x16}; per-case schedules under `outputs/s1/<config>/` |
| S3/S4 trace-gen + sim | dispatched: 130-task Slurm array submitted to Stokes; queue was idle and no prior validation jobs were found to kill | boss report |
| S5/S6 aggregate + figure | not started; ETA for the figure is tonight | boss report |

Review: archie is reviewing the kit in parallel, with findings requested
before S5/S6.

## Open discrepancy to settle before the caption is written

`execution_plan.md` states **12 kept layers** and **120 solves**
("Case counts: schedules 2 sides x 5 capacities x 12 layers"), while the
committed kit is built on **13 layers and 130 solves** (`outputs/cases.txt`,
13 distinct layer names, 13 rows per config; commit `53f3c1f`'s message
likewise says 130). The artifacts are self-consistent at 13; only the plan
text disagrees. Which number is right is not settled here - whoever owns
the 13th layer's inclusion should reconcile the plan text with the kit,
because the case count and the layer set both reach the figure caption.

## Stokes working-tree note (reported by boss, not verified here)

To unblock a `git pull` on Stokes, 9 untracked wt500 Stokes files were
moved to `~/untracked_backup_20261116/`, and local deletions were stashed
as `stash@{0}`. Nothing was deleted. Recovering either set is a `git stash
pop` and a move back from that directory.
