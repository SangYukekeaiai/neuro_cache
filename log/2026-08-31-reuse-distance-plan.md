# 2026-08-31: L1 and L2 reuse-distance distributions at the khkw_split best config

Authority for the reuse-distance measurement. Implementation lives in
`profiling/0831_reuse_distance/`; the live board is that folder's `PROGRESS.md`.

## 1. The quantity

LRU **stack distance**, in units of distinct lines. For a reference to line `X`
at time `t` whose previous reference was at `p`, the distance is the number of
DISTINCT lines referenced in `(p, t)`. A first reference is **cold** and is
counted in its own bucket rather than folded into any finite distance.

This is the house definition, carried over from
`log/2026-07-16-locality-analyzer.md:66`, "in units of distinct weight lines".

Its value is that one pass gives the hit rate at every capacity at once: a
reference hits in a fully-associative LRU cache of `N` lines exactly when its
distance is `< N`, and a cold reference never hits.

## 2. What is config-dependent, and what is not

**The per-core L1 access sequence is fixed by the layout alone.** I13 pins
service order to trace order and the core holds one burst in flight, so L1 size,
associativity and latency cannot reorder what a core asks for. At the best
config prefetching is off, so nothing else probes the L1. The L1 histogram is
therefore a property of `(trace, layout, cin_block, cout_block, weight_bytes)`.

**The L2 sequence is config-dependent.** It is whatever the L1 fails to absorb,
and the interleaving of sixteen cores into one shared L2 is set by timing. That
is why the measurement is pinned to the best config.

Both halves are checked: V4 below.

## 3. The best config (Friday's artifact, `outputs/_khkw_grid/khkw_64b.json[0]`)

    layout khkw_split, cin_block 16, cout_block 4, weight_bytes 1   (64 B lines)
    L1 16 KB 8-way, L2 512 KB 16-way, l2_mshrs 32, l2_banks 1
    l1_latency 0, l2_latency 2, l2_miss_latency 24
    prefetch none, distance 0

Layers V8, V9, R9, R16 at five samples each, streams already on disk at
`profiling/0823_stagewise_verify/stage4_wcache/inputs/streams/`.

## 4. Sizing, measured 2026-08-31

| layer | L1 refs | L2 refs | L1:L2 | distinct lines |
|---|---|---|---|---|
| V8 | 2,597,632 | 77,824 | 33.4:1 | 36,864 |
| V9 | 4,995,072 | 77,824 | 64.2:1 | 36,864 |
| R9 | 1,382,144 | 4,608 | 299.9:1 | 4,588 |
| R16 | 1,969,728 | 38,912 | 50.6:1 | 18,350 |

Across four layers and five samples: 54.7M L1 references, 996K L2 references.
Exact stack distance is affordable at this scale, so the plan uses no sampling
and no approximation.

`l2_accesses == dram_accesses` on all four layers, so the L2 hit rate is a true
zero and every L2 distance lands above the 8,192 lines that 512 KB holds. The
histogram's job at the L2 is to say how far above, and therefore what capacity
would capture them.

## 5. The algorithm

Fenwick-tree exact stack distance (Bennett and Kruskal). One 0/1 marker per
distinct line, sitting at that line's most recent reference; the distance is the
count of markers in `(p, t)`; a Fenwick tree over the timestamp axis makes that
count `O(log n)` instead of `O(gap)`.

    for each reference to line X at time t:
        if X unseen:          record COLD
        else:                 d = prefix(t-1) - prefix(p);  remove marker at p
        place marker at t;    last[X] = t

About 19 slot touches per reference at the largest stack, against roughly 2,300
for a backward walk. The naive back-scan is kept as the test oracle, never as
the production path.

## 6. Where the code lives

The engine gains only a **thin access-log dumper**. Every line of the
reuse-distance logic lives in `profiling/0831_reuse_distance/`, which is what
makes U1 testable with no engine coupling at all.

    profiling/0831_reuse_distance/reuse_distance.h        StackDistance, ReuseHistogram
    profiling/0831_reuse_distance/test_reuse_distance.cpp naive oracle + self-checks
    profiling/0831_reuse_distance/reuse_tool.cpp          reads an access log, writes the histogram
    profiling/0831_reuse_distance/run_reuse_hist.py       the 20 runs at the best config
    profiling/0831_reuse_distance/analyze_reuse.py        CDF, hit-rate curve, validation
    src/wcache/native/include/wcache/access_log.h         the dumper (engine side)

## 7. Units

Each stops for review, per the standing pipeline.

| Unit | Increment |
|---|---|
| U1 | `StackDistance` and `ReuseHistogram`, with the naive oracle and self-checks |
| U2 | `AccessLog` dumper, hooked in `CacheLevel::triage()`, `--access-log` on `wcache_run` |
| U3 | `reuse_tool`, reading an access log and writing the histogram CSV |
| U4 | `run_reuse_hist.py` over the 20 streams at the best config |
| U5 | `analyze_reuse.py`: CDF, predicted hit-rate curve, validation overlay |
| U6 | The published artifact |

## 8. Verification

- **V1** The histogram's total equals `l1_accesses` and `l2_accesses` in the
  results row, exactly. Two independently built numbers.
- **V2** Predicted fully-associative hit rate at 256 lines against the measured
  `l1_hit_rate` of 0.970040. These will differ, because the real L1 is 8-way.
  The gap is the associativity penalty, and reporting it is a result.
- **V3, the strongest, because the answer is already on the record.** Friday's
  artifact found the L2 cliff by sweeping `l2_size_bytes` to 16 MB: 0% below
  4 MB for V8 and V9, 52.63% at and above; 2 MB for R16; R9 flat at 0%. The
  histogram must reproduce that knee, at those sizes, from one run per layer.
  The ceiling is arithmetically forced: V8 has 36,864 distinct lines over 77,824
  references, so cold is 47.37% and the ceiling is 52.63%, which is the figure
  the artifact measured.
- **V4** The L1 histogram at `l1_size_bytes` 16384 and 262144 must be identical,
  proving section 2's claim.

## 9. Out of scope

Sampled or approximate reuse distance, per-tile stacks (the user chose whole
layer on 2026-08-31), reuse distance under prefetching (off at the best config),
and binning inside the instrument. Distances are kept exact and binned at
analysis time, so the raw file stays re-analyzable.
