# EXPLAIN: units U1-U6 and W1-W5, all complete

**Erasable.** The record is `PROGRESS.md`. Plans are
`log/2026-08-31-reuse-distance-plan.md` and `log/2026-08-31-belady-l2-plan.md`.
Result: https://claude.ai/code/artifact/38f8e8d6-02fb-486a-af96-b9b9b03d3983

## Reproduce

    make -C ../../src/wcache/native MODE=release lib apps
    make -C ../../src/wcache/native test          # 21 suites

    W="-std=c++17 -O2 -Wall -Wextra -Wpedantic -Wsign-conversion -Wconversion -Wshadow"
    g++ $W test_reuse_distance.cpp -o test_reuse_distance && ./test_reuse_distance
    g++ $W reuse_tool.cpp -o reuse_tool
    python3 run_reuse_hist.py 4     # 24 runs, ~12 s,  V1 V4
    python3 analyze_reuse.py        # V2 V3 and the conflict finding, ~70 s
    python3 plot_reuse.py           # outputs/spectra.svg, embedded in the artifact
    python3 run_belady.py           # 120 runs, ~6 min, B1 B2 B3

## Engine changes

Three, all additive and all inert by default:

- `include/wcache/access_log.h` plus two hook lines in `engine.cpp` (U2)
- `include/wcache/next_use.h`, `BeladyPolicy` in `stamp_policy.h/.cpp`, and the
  optional `note_next_use` verb on `ReplacementPolicy` (W1, W2)
- `l2_policy` in config, `--l2-oracle` on `wcache_run`, the occurrence counter
  in `CacheLevel` (W3)

Checked inert: B4 shows an oracle attached to an LRU L2 leaves all 93 columns
identical bar `sim_wall_seconds`.

## The three results

1. **The L2 was never short of capacity.** Largest reuse distance in the corpus
   is 3,071 lines; the 512 KB L2 held 8,192. At fixed capacity, 16-way to 64-way
   takes the hit rate 0.00% to 52.63% and cuts 12.7-14.5% of cycles, matching a
   4 MB L2 exactly at one eighth the size.

2. **The conflict has two components, and neither is the policy.** Belady's MIN
   gets 26.32% at 16-way, exactly half the ceiling, so the sets really are
   over-subscribed. LRU gets 0.00%, so it is also pathological. At 64-way Belady
   and LRU are identical to the cycle.

3. **A lock-step barrier makes hit rate the wrong objective.** Belady's 20,480
   extra hits on V8 cut channel stall 26% and core stall 18%, and the run is
   SLOWER: the barrier absorbs 418,786 cycles of it as slack. Ways work because
   they lift the critical core too.

## What I would look at next

`PROGRESS.md`'s open questions, of which the live one is re-cutting the L2 set
index. Everything needed to test it is already in the access log.
