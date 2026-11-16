# Stokes small-experiments plan: remaining paper figure placeholders

Status: for user review 2026-11-12. Source: grep of
2027_ASPLOS_neuro_cache/src/*.tex for \figplaceholder + the intro
placeholder box. The big Fig 12 (eval_spad_cache) runs on AWS/Delta per
the fig12 plan; everything below is small enough for Stokes (its queue is
free and idle since the pause) and none of it needs the 500-sample grid.
Stokes ground rules: resume via ~/stokes_master.sh bridge (user types the
password), repo at ~/neuro_cache_wcache on branch wcache-rebuild-phase-a,
OPENBLAS/OMP_NUM_THREADS=1 on login (RLIMIT_NPROC=100), real --mem on
jobs, TMPDIR=/dev/shm.

## The placeholders and their experiments

### P1. fig:spinalflow_saturation (04_motivation.tex:35)
"SpinalFlow performance vs workload size, node-level N = 128/256/512."
- Run: single-node gen+nocsim sweep, spinalflow only, 3 node sizes x the
  8 benchmarks' representative layers, ~5 samples. The fig3 single-node
  sweep machinery (zoo/fig3_design_space/, fig3_single_node_n_sweep)
  already does exactly this shape: re-point configs at N in {128, 256,
  512}.
- Cost: < 10 node-hours. Output: cycles vs workload-size curves.

### P2. fig:reuse-distance (04_motivation.tex:329)
"Reuse distance distribution of weight requests."
- Run: generate weight traces for ~2 benchmarks x all layers x 1 sample
  per arch (or spinalflow + loas only, if the figure is motivational),
  then a one-pass reuse-distance histogram over each address stream
  (stack-distance algorithm, streaming, O(unique lines) memory).
- New code: one small script (reuse_dist.py) consuming wcts address
  streams; no sim changes.
- Cost: ~5-15 node-hours (dominated by gen; traces deleted after the
  histogram pass, same wave pattern as everything else).

### P3. fig:eval_unused_weights (08_evaluation.tex:49)
"Unused-weight ratio per layer and architecture."
- Pure counts: fetched-weight set vs total weight footprint per layer.
  The analytic counts scripts (fig12_edp/counts/) already compute
  fetched records; unused ratio = 1 - |touched lines| / |weight lines|.
  Touched-line sets come from the same capture convolutions (which
  (kh,kw,cin) positions ever fire) - NO simulation at all.
- Where: could run on Delta login in minutes; listed here because the
  captures are mirrored on Stokes - run wherever is idle.
- Cost: < 1 node-hour.

### P4. fig:eval_scaling (08_evaluation.tex:89)
"Utilization and off-chip traffic: single-node scratchpad sweep vs
multi-node."
- Run: nocsim on the existing 749 schedules for the multi-node points
  (already scheduled; cycles + dram split come free with the demo run)
  PLUS a single-node spad-size sweep (reuse P1 machinery, sweep L1 size
  instead of N). Mostly reuses P1 outputs + demo-run outputs; the only
  new Stokes work is the single-node spad sweep: ~10 node-hours.

### P5. Intro energy-profiling box (02_introduction.tex:31, RQ1)
"Energy breakdown per architecture."
- NOT a Stokes experiment: it joins the same energy_table.json +
  demo-run counts already in flight on Delta (parent plan: the table
  feeds fig:energy-profiling). Listed so nothing double-runs it; falls
  out of the demo results + one plotting script.

## Sequencing and ownership

| order | row | what | where | est |
|---|---|---|---|---|
| 1 | T80 | P3 unused-weight counts + CSV (no sim) | Delta login / Stokes | <1 h |
| 2 | T81 | P1 saturation sweep (N=128/256/512) | Stokes Slurm | ~10 h queue-bound |
| 3 | T82 | P2 reuse-distance script + histogram wave | Stokes Slurm | ~5-15 h |
| 4 | T83 | P4 single-node spad-size sweep (reuses T81 kit) | Stokes Slurm | ~10 h |
| 5 | - | P5 + plotting for P1-P4 | Delta (after demo run) | small |

All four Stokes rows are independent of the AWS campaign and of each
other except T83-after-T81 (shared sweep kit). They can start as soon as
you re-establish the Stokes bridge and confirm this plan; none touches
the paused campaign's outputs or the wave tooling.

## User efforts

1. Re-establish the Delta->Stokes bridge (~/stokes_master.sh, password).
2. Confirm P1's exact x-axis ("workload size": layer size spectrum per
   benchmark, or batch/timestep scaling - the caption is ambiguous; plan
   assumes layer size spectrum).
3. Confirm P2 scope (all 5 archs or the 2-arch motivational version).
4. Review this plan + the AWS guide (zoo/fig12_edp/docs/aws_deployment.md).
