# 0907 index-policy run log

Machine: 32 cores, 62 GB RAM, 635 GB free. Branch wcache-rebuild-phase-a @ fb1ad0e.

- 2026-09-08: Step 0 done (this file).
- Step 1 DONE. solve_all_layers.py --check MATCH on all 4 reference layers after
  excluding `result.configs` (absolute input paths) from the diff. Full solve:
  31 layers, all OPTIMAL, 23.0 s.
- Step 2 RUNNING. gen_streams.py --workers 24, PYTHON swapped to sys.executable,
  --check made a skip when the stage-4 reference streams are absent (they are).
  155 streams expected.
- Step 2 incident: 24 workers exhausted the 62 GB of RAM on the larger resnet
  layers (R8, R10); the OOM killer took 6 children, each surfacing as
  CalledProcessError(-9). Run stopped at 100/155. The 100 streams whose success
  line in the log matches their on-disk size were kept; 4 partial files
  (R11 s0, s1, s2, s4) were deleted, since the script skips any file that exists
  and would otherwise have accepted a truncated stream. Restarted at 6 workers.
- Step 3 PENDING. run_sweep.py already patched to tolerate the missing nocsim CSV.
- Step 4 PENDING: arm/layer coverage and the lru l1_hit_rate ~0.9888 check.
