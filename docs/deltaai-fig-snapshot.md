# Figure campaign snapshot for DeltaAI (2026-11-16)

All `zoo/fig*` campaign folders are copied to the Lustre `/work` filesystem,
which Delta and DeltaAI both mount (same path on both systems, the
convention `zoo/fig12_edp/deltaai/README.md` already uses):

```
/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/
  fig1_energy_profiling/   (includes outputs/, 3.0G - excluded from git)
  fig2_hw_n_sweep/
  fig3_design_space/
  fig5_reuse_distance/
  fig12_edp/               (includes stokes/full500_rows_fetch_20261116/rows,
                            1.7G - excluded from git)
```

- This is a one-time snapshot by `rsync -a`, not a live mirror; the
  repository on branch `wcache-rebuild-phase-a` stays the source of truth
  for everything except the two oversized data dirs noted above, which
  exist only in this snapshot and on their origin machines.
- Input spike traces are separate and already shared:
  `/work/nvme/bebv/yyu9/input_trace_delta/`.
- ASAP7 1 GHz synthesis outputs (all 26 basic modules, Genus syn-only,
  for archx harvest + pricing) are at
  `/work/hdd/bebv/yyu9/asap7_syn_1ghz_20261116/` with their own README.
- eval_scaling and roofline campaign folders are small and fully in git;
  clone the repo on DeltaAI to get them (eval_scaling outputs/ live on
  Stokes: `~/neuro_cache_wcache/zoo/eval_scaling/outputs/`). As of
  2026-11-16 they are also copied into this snapshot (`eval_scaling/`,
  `roofline/`), including the mock figures and the RQ2 rewrite draft.
