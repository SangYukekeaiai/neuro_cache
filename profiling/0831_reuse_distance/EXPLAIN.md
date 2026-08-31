# EXPLAIN: U1 through U6, all complete

**Erasable.** The record is `PROGRESS.md`; the plan is
`log/2026-08-31-reuse-distance-plan.md`; the result is the artifact at
https://claude.ai/code/artifact/38f8e8d6-02fb-486a-af96-b9b9b03d3983

## Reproduce

    # engine, once
    make -C ../../src/wcache/native MODE=release lib apps

    # this folder
    g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow \
        test_reuse_distance.cpp -o test_reuse_distance && ./test_reuse_distance
    g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow \
        reuse_tool.cpp -o reuse_tool
    python3 run_reuse_hist.py 4      # 24 runs, ~12 s, V1 and V4
    python3 analyze_reuse.py         # V2, V3, the finding, ~70 s

`reuse_tool` and `test_reuse_distance` are build products and are not checked in.

## What each unit is

- **U1** `reuse_distance.h`: `StackDistance` (Fenwick over the timestamp axis) and
  `ReuseHistogram`. No engine dependency at all, which is what let it be proved
  against a naive back-scan oracle before anything fed it. 850 checks.
- **U2** `../../src/wcache/native/include/wcache/access_log.h`: the engine's only
  change. A dumper, 8 bytes per demand reference, written at the same two sites
  that increment `l1_accesses` and `l2_accesses`.
- **U3** `reuse_tool.cpp`: log in, histogram CSV out. Seventeen stacks per run.
- **U4** `run_reuse_hist.py`: the 20 best-config runs plus 4 for V4.
- **U5** `analyze_reuse.py`: the curve, V2, V3, and the associativity experiment.
- **U6** `artifact.html`.

## Outputs

    outputs/reuse_hist.csv        3,106 rows, level/core/distance/count per (layer,sample)
    outputs/reuse_runs.csv        the 93-column results row per run
    outputs/v4_independence.csv   the L1-histogram config-independence check
    outputs/hit_rate_curve.csv    predicted hit rate vs capacity, both levels, 4 layers
    outputs/analysis.json         everything the artifact quotes

## The one thing to read if you read nothing else

The L2 was never short of capacity. Largest reuse distance in the corpus: 3,071
lines. Lines the 512 KB L2 already held: 8,192. Holding capacity fixed and going
16-way to 64-way takes the hit rate from 0.00% to 52.63% and cuts 12.7 to 14.5%
off total cycles, matching the 4 MB L2 exactly at one eighth the capacity.

The L1 says the same thing from the other side: its 8-way array beats
fully-associative LRU by up to 5.36 points, because the `khkw_split` index
spreads a reuse window across the L1's 32 sets. The same index concentrates one
across the L2's 512 sets. Correct where it was tuned, unexamined one level down.

Three open items are listed at the bottom of `PROGRESS.md`. Nothing is committed.
