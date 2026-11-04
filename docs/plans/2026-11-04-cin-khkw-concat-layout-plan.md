# Plan: `cin_khkw_concat`, a concatenated CIN-(KH·KW) indexing policy

Date: 2026-11-04. Session: redesign-cache-index (peon team: boss %0, archie %1 reviewer,
impl %2 codex, scribe %3 writer). Status: **T50 (static utilization analysis) dispatched
2026-11-04; T51+ implementation awaits user approval informed by T50's numbers.**

## 1. Background and verified current behavior

The cache simulator's address mapping lives in `src/lays/cachesim/native/`. Set and tag
are not bit fields: each layout flattens the weight coordinate `(kh, kw, cin, cout)` into
a dense mixed-radix **line id**, then `index/set_index.h` applies

```
set = line % num_sets        tag = line / num_sets
```

Baseline config (`examples/cache/base.json`): `cin_block 16 x cout_block 4 x 1 B = 64 B`
lines; L1 16 KB / 8-way / 64 B gives **32 sets**; L2 512 KB / 16-way gives **512 sets**;
`layout = khkw_split`.

`KhkwSplitMapper` (`src/layout/khkw_split.cpp`) nests digits, outermost first:

```
[pos_hi | cout_blk | cin_blk | pos_lo]      pos = kh*KW + kw,  pos_lo radix = min(8, KH*KW)
```

So for a 3x3 kernel the L1 index = 3 bits of kernel position + low cin blocks, and the
tag = high cin + cout + pos_hi, matching the user's description of the current design.

**One correction to the premise.** For KH = KW = 1 (spiking-GEMM) the 3 position bits are
*not* wasted: `n_pos_lo = min(8, 1) = 1`, both position digits collapse, and the line id
degenerates to `cout_blk * n_cin_blocks + cin_blk`, so cin already owns the low index bits
on GEMM layers (khkw_split.h documents this case). The real questions the new policy
answers are (a) where cout sits, and (b) whether the ragged 9-position kernel digit
wastes index entropy on conv layers (no pos_hi aliasing, no 3-bit cap).

## 2. The new policy

New sibling mapper, per the codebase's rule B10 (a differently nested layout is a new
`AddressMapper` subclass, never a flag): **`CinKhkwConcatMapper`**,
`layout = "cin_khkw_concat"`.

Concatenated dimension, CIN major / kernel-position minor, dense by construction:

```
d = cin_blk * (KH*KW) + pos          d in [0, D),  D = n_cin_blocks * KH*KW
```

Nesting, outermost first, **two digits, no split**:

```
[cout_blk | d]                        line = cout_blk * D + d
```

### Why no explicit split (the limited-cin problem)

A first draft split d as `[d_hi | cout | d_lo]` with `d_lo` radix = L1 set count. The
user spotted the failure: a core's cout is pinned per tile, so per-core index entropy
comes only from cin x pos, and when `D < num_sets` a pure-d index must starve. Example:
a 128-input GEMM layer has 128/16 = 8 cin blocks, so `d in [0, 8)` pins the L1 index to
8 of 32 sets, leaving 75 % of L1 unreachable on a real layer. Even 384 inputs (24 blocks)
strands 8 sets.

The no-split nesting fixes this through the modulo placement itself, exactly as
`khkw_split` already treats full cin: `set = (cout*D + d) % num_sets`. When `D < 32`,
the cout digit shifts the dense band `[0, D)` by `D mod 32` in steps of
`gcd(D, 32) <= D`, so the union over a core's own cout blocks covers **all 32 sets**:
no hole, no `W_*_UNREACHABLE` warning, no config knob. Regimes:

- **D >= sets** (large GEMM, any conv): index comes from d alone, which is the intended
  policy. On 3x3 this is the genuine novelty over `khkw_split`: the ragged 9-position
  kernel is absorbed densely into d.
- **D < sets** (limited cin): cout tops up the index via the modulo. Power-of-two D
  tiles perfectly; non-power-of-two covers because the stride gcd never exceeds D.
- **L2 (512 sets)**: same mechanism; cout supplies the upper index bits.

Residual limit, physical and policy-independent: a core whose cout-slice x cin x pos has
fewer distinct lines than sets cannot fill them under any mapping.

### Fallback kept in reserve

If the comparison shows `[cout | d]` losing at L2 against split_cin's measured
`[hi | cout | lo]` arrangement (see the table in `include/cachesim/layout/split_cin.h`),
the variant `d_lo = min(L1 set count, D)`, the same min-guard trick as `kPosLoRadix`,
restores that shape without the reachability hole. Implement only the no-split version
first; the sweep decides whether the variant earns an enumerator.

### Degeneracies (expected equivalences, useful as test oracles)

- KH = KW = 1: `cin_khkw_concat` matches `khkw_split`'s degenerate `[cout | cin]`
  flatten exactly: identical line ids, identical placement.
- The flatten is a bijection onto `[0, n_cout_blocks * D)`; `num_lines` is exact (no
  ragged radix product to bound, unlike khkw_split).

## 3. Implementation (T50 dispatched 2026-11-04; T51+ only after user approval)

| id | owner | task | done means |
|----|-------|------|-----------|
| T50 | impl (codex) | **Static set-utilization analysis** (user request, pre-approval): for every loas vgg16/resnet19 layer shape, % of L1/L2 sets reached under `khkw_split` and under the proposed `cin_khkw_concat` (global, per-core with 16 contiguous cout slices, lines-per-set imbalance, capacity bound); stdlib-only `zoo/set_utilization/compute.py` regenerating `zoo/set_utilization/RESULTS.md` | **reviewed pass 2026-11-04.** Finding: only resnet19 shortcut layer_03 below full per-core L1 reach (25%, capacity-bound: 8 lines/core vs 32 sets, policy-independent); other 30 layers reach every L1 set under both policies |
| T51 | impl (codex) | **Corpus extension** (user request): T50 analysis over every out_real capture dir (A02 Spikformer, A04 SDT, A07 SpikingLM 72 GEMMs, A08 Prosperity-VGG16, B09 LoAS vgg16+resnet19), with per-benchmark labels and a GEMM-vs-conv breakdown | compute.py regenerates RESULTS.md over the full corpus (dispatched 2026-11-04) |
| T52 | impl (codex) | **Ways x line-size coverage sweep** (user request), khkw_split only: line 16B (4cin x 4cout) / 32B (8cin x 4cout) / 64B (16cin x 4cout), L1 16KB / L2 512KB, ways 1..64 powers of two; per line size the way counts whose sets are fully utilized (min per-core reach 100%), capacity-bound layers counted separately | ways_sweep.py regenerates WAYS_COVERAGE_{16B,32B,64B}.md (dispatched 2026-11-04) |
| T53 | impl (codex) | `CinKhkwConcatMapper`: `include/cachesim/layout/cin_khkw_concat.h`, `src/layout/cin_khkw_concat.cpp`, `LayoutKind` enumerator, config spelling (`config.cpp`, `enum_names.h`), `factory.cpp` case, Makefile entry, native unit tests `tests/layout/test_cin_khkw_concat.cpp` mirroring `test_khkw_split.cpp` (bijectivity, line_of/locate/neighbour/expand, the 1x1 khkw_split-equivalence oracle, D < sets coverage) | `make test` green incl. new tests |
| T54 | impl, only after T53 **reviewed pass** | Comparison: `khkw_split` vs `cin_khkw_concat` vs `split_cin` on tracked 3x3 controls V8/V9/R9/R16 via `scripts/pipeline.py` / `python -m lays.cachesim sweep` on the base.json geometry; GEMM-shaped (1x1) arm per the trace-availability ruling below; results.csv + summary | one table: L1/L2 hit rates + cycles per layer x layout |
| T55 | scribe, only after T54 reviewed pass | Technique write-up in `innovation_summary/` | describes code that exists and measured numbers |
| n/a | archie | reviews each done row | verdict on board |
| n/a | boss | `git stash create` snapshot before dispatch; publish the final comparison artifact (table + rationale) and summary to the user | n/a |

## 4. Risks and notes

- **The replay pipeline cannot drive 1x1 layers at all**: `weight_trace_gen/trace.py`'s
  `exclusion_reason` rejects any layer whose kernel is not 3x3 stride-1, so the resnet19
  shortcut layers have no trace path today. The dynamic (hit-rate) comparison on
  spiking-GEMM therefore needs either external GEMM traces, or extending the replay to
  1x1 (new scope), or settling for the static T50 analysis on those shapes. T52's GEMM
  arm waits on the user's ruling.
- Non-shortcut schedules missing from `examples/schedules/` would be Gurobi-solved by
  the pipeline (license present at `~/gurobi.lic`; adds runtime).
- The wcache worktree is on `wcache-rebuild-phase-a` and carries T8's uncommitted edits
  (board note); T50 adds new files plus small edits to factory/config/Makefile, and a
  snapshot is taken before dispatch regardless.
- Spikformer/SDT/SpikingLM GEMM traces are not in this repo; if the user wants them as
  the GEMM arm instead of the resnet19 shortcuts, that is a scope change to T51.

## 5. Open questions for the user

1. Approve the **no-split** `[cout_blk | d]` design (recommended); the fixed-3-bit and
   `d_lo = L1 sets` variants are recorded above as rejected/fallback.
2. The GEMM arm of the dynamic comparison: external GEMM traces, extend the replay to
   1x1 kernels, or static-analysis-only for 1x1 shapes (see risk note on the replay's
   3x3-only restriction)?
3. `split_cin` included as the third comparison arm (recommended, cheap).
