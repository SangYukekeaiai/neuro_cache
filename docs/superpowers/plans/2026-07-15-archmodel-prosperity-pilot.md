# Arch-specific cycle count — Prosperity pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Spec (rephrased)

This targets Prosperity, from Wei, Guo, Cheng, Li, Yang, Li & Chen,
*"Prosperity: Accelerating Spiking Neural Networks via Product Sparsity"*
(HPCA 2025), as the sixth of the 6-architecture cycle-count plan
(SpinalFlow was the pilot, PTB the third, LoAS the fourth, GustavSNN the
fifth — see `docs/superpowers/plans/2026-07-12-archmodel-spinalflow-
pilot.md`, `2026-07-14-archmodel-ptb-pilot.md`,
`2026-07-14-archmodel-loas-pilot.md`, and
`2026-07-15-archmodel-gustavsnn-pilot.md`; only Phi remains unstarted
after this).

**Product Sparsity (ProSparsity), in the paper's own terms (Section
III):** in a tiled spiking GeMM (an `m x k` binary spike matrix times a
`k x n` weight matrix), two rows of the spike matrix that share a common
1-bit sub-combination produce partially- or fully-identical inner-product
results. If row `j`'s spike set is a proper subset of row `i`'s spike set
(**Partial Match**), `i`'s inner product can reuse `j`'s already-computed
result and only needs to accumulate the *residual* bits (`i`'s bits XOR
`j`'s bits, since XOR == set difference when `j` is a subset — Section
V-C). If two rows are identical (**Exact Match**), the later one's result
is reused outright (residual = all zero). The paper restricts this to a
single Prefix per row (Section III-D's "Pruning Rules": keep only the
subset-candidate with the largest overlap, breaking ties toward the
larger row index) and orders rows by ascending popcount so every row's
chosen Prefix is guaranteed already processed (Section III-C's Prefix/
Suffix definition; Section V-B's "Temporal Detection" via a stable
sorter) — together this is Section III-D's linear-time (`O(m)`) heuristic
this pilot implements directly, matching the pilot's own worked
pseudocode verbatim.

**This pilot's worked example is exactly the paper's own canonical
illustration** (Fig. 1(d) / Fig. 2's 6-row, 4-column spike matrix):

```
Row0: 1010    Row1: 1001    Row2: 1011
Row3: 0010    Row4: 1101    Row5: 1101
```

Processing order (ascending popcount, stable): `[3, 0, 1, 2, 4, 5]`.
Row3 has no valid Prefix (nothing processed yet) → pattern unchanged
(`0010`). Row0's only subset candidate is Row3 (`{2} ⊆ {0,2}`) → pattern
`1010 ⊕ 0010 = 1000`. Row1 has no subset candidate among `{3,0}` → pattern
unchanged (`1001`). Row2's candidates are Row3 (overlap 1) and Row1
(overlap 2, `{0,3} ⊆ {0,2,3}`) → Row1 wins (larger overlap) → pattern
`1011 ⊕ 1001 = 0010`. Row4's only candidate is Row1 (`{0,3} ⊆ {0,1,3}`) →
pattern `1101 ⊕ 1001 = 0100`. Row5 is an Exact Match of Row4 (larger
index between the tied pair, Row5, becomes the Suffix per Section III-C)
→ pattern `1101 ⊕ 1101 = 0000`. Total residual spikes across all 6 rows =
`0010`+`1000`+`1001`+`0010`+`0100`+`0000` = **6**.

**Node size, paper-confirmed:** `m=256, k=16, n=128` — this is *exactly*
Table III's own evaluated tile-size config, not an independently chosen
number. Mapped onto this project's DIM system (per the pilot's own
spec): `KH=4, KW=4` (`k = KH*KW = 16`), `COUT=128` (`n`), `HO=16, WO=16`
(`m = HO*WO = 256`). Two axes are conspicuously **absent** from this
node size, both explicit, deployment-specific simplifications (not
paper-fidelity bugs):

- **CIN is fixed at exactly one channel per node visit** (barred from
  NodeLevel entirely, like GustavSNN bars T). Table III's own `k=16` has
  no CIN term — a real im2col row is generally `KH*KW*CIN` bits wide, but
  this pilot's `k=16=KH(4)*KW(4)` leaves no room for CIN>1 without
  changing the tile's bit width. A future generalization would need `k`
  to absorb CIN too (same tiling idea, wider rows); this pilot does not
  attempt it.
- **T is likewise barred, one tick per node visit.** The paper's own
  formulation unrolls and concatenates every timestep's spike matrix into
  additional M-dimension rows (Section II-A: "we can unroll and
  concatenate all spike matrices in different time steps to get a single
  binary spike matrix"), so T *could* be folded into `m` in general — but
  this pilot's node size (`m=256=HO(16)*WO(16)`) already exactly
  saturates the row budget with the given `HO`/`WO` shape alone, leaving
  no room for a T factor. This mirrors GustavSNN's own T-barred,
  one-tick-per-visit precedent.

**HO/WO ARE node-level resident (the second architecture in this plan
after GustavSNN where they carry any NodeLevel residency) — but unlike
GustavSNN's HO, NEITHER is a spatial (parallel-PE) axis.** GustavSNN
needed HO spatial because its column-partition submatrices run on
physically separate PEs simultaneously (`parallel-for k` in its
Algorithm 1). Prosperity's Processor is the opposite: Section V-E states
plainly, **"Prosperity employs a row-wise dataflow, i.e., a spike row...
is processed at a time"** — the tile's `m` rows are consumed strictly
*sequentially* by one shared 128-wide PE array (the array's width is
`n=128`, i.e. parallel only across output channels, not across rows;
Table III: "Processor 128 PEs 8-bit Add, n=128"). So `HO` and `WO` are
both plain **capped, non-spatial** `node_dim_capacity` entries (`16`
each) — genuinely symmetric treatment this time (per
[[feedback_symmetric_hw_dims]]'s refinement: verified against the paper's
own row-wise-sequential Processor design, not just visual symmetry), and
their product (`16*16=256`) automatically enforces the paper's own
`m=256` tile-size cap without needing any joint-dimension solver
mechanism (unlike GustavSNN's HO/WO split, no V1 spatial-product check
is even involved here since neither is spatial-tagged).

**`COUT` contributes ZERO incremental cycle cost** (Section V-A states
this explicitly: *"the number of n has no impact on ProSparsity"*), same
treatment as SpinalFlow/LoAS/GustavSNN — `COUT: {spatial: 128}`,
`pe.num_pes: 128`, matching Table III's "128 PEs... n=128" exactly.

**Cycle-count rule, per the pilot's own spec (confirmed against Section
V-E's Processor design):** `compute_cycle_count == access_cycle_count ==`
the total number of residual (`pattern`) spike bits across every row in
the tile, after ProSparsity compression. This is the paper's own Step 10
(decode weight address by bit-scan-forward on the pattern) + Step 11
(accumulate into the partial sum across all N=128 columns in parallel)
happening together, **one residual bit per cycle** — no separate access-
vs-compute bottleneck to distinguish, matching SpinalFlow's/LoAS's/
GustavSNN's own "no dominance case" `event_to_cycle = max(...)` shape.
This is an explicit **steady-state abstraction**: the paper's own
ProSparsity *processing* phase (Detector/Pruner/Dispatcher, `m+4` cycles
per tile, Section VI-A) is not counted at all, because Section VI-B's
own inter-phase pipeline hides it entirely behind the *previous* tile's
computation phase ("the ProSparsity processing phase of a tile is
perfectly overlapped by the computation phase of the previous tile...
except for the first tile phase, which has a minor impact") — the same
"abstract away fixed pipeline fill/drain overhead" treatment PTB and
GustavSNN already apply to their own systolic/wave latencies.

**Weight loading, per the pilot's own spec:** for each active (`1`) bit
in a row's residual pattern, load one line of `[kh, kw, COUT[start,
start+127]]` — one weight-row burst per residual spike, spanning the
tile's *entire* assigned COUT range in a single burst (Section V-A: "the
weight sub-matrix has k rows and n columns"; Section V-E Step 10 decodes
the weight address via bit-scan-forward on the pattern). This is why
`access_cycle_count == compute_cycle_count`: both are driven by the same
total residual-spike count.

**Goal:** Build Prosperity's `reconstruct_tile_sequence` / `event_to_cycle`
/ `event_to_address` trio (matching the SpinalFlow/PTB/LoAS/GustavSNN
pilots' architecture-owned 3-stage pattern), plus `configs/arch/
prosperity.yaml` and a real MIP-solved single-node schedule proving the
config is solver-feasible (per [[feedback_archmodel_deliverable_scope]]).

**Architecture:** `src/snn_cosa/archmodels/prosperity/{__init__.py,
reconstruct.py, cycles.py, address.py}`, standalone and unwired (same
scope as every prior pilot in this plan — live wiring into `combine()`'s
per-tile loop is a separate, later design pass for every architecture).
`reconstruct.py` factors the ProSparsity compression algorithm itself
(`_prosparsity_process`, pure over already-extracted row bit-vectors)
out from the trace-slicing wrapper (`reconstruct_tile_sequence`) — this
split exists specifically so the compression algorithm can be verified
directly against the paper's own canonical worked example: hand-picking
arbitrary per-row bit patterns (as the worked example does) is only
representable at this pure-data level, since any single real stride-1
trace tensor forces adjacent output rows' overlapping receptive fields
into *mutually consistent* bits, not arbitrary ones.

**Tech Stack:** Python 3, numpy, existing `snn_cosa` stack. No pytest in
this repo — verification runs a script and checks exact printed output,
per existing convention.

## Global Constraints

- Zero regression: this plan touches no shared code (`archmodels/__init__.py`'s
  `ComputeCycles.lif_cycles: Optional[int] = None` convention and
  `combine.py`'s handling of it already exist — Prosperity reuses them
  as-is, no further changes needed there).
- No new third-party dependencies.
- `reconstruct_tile_sequence`, `event_to_cycle`, `event_to_address` are
  Prosperity-owned, not shared with SpinalFlow, PTB, LoAS, GustavSNN, or
  any other architecture — do not refactor those to share code with
  Prosperity's.
- Out of scope for this plan (needs its own design pass): wiring a full
  `ProsperityComputeModel` implementing the `ArchComputeModel` Protocol
  into `combine()`'s live per-tile loop. This plan only proves the
  Prosperity plugin correct standalone, against the paper's own worked
  example, a real captured trace, and a real MIP-solved schedule.
- CIN fixed at one channel per node visit (barred from NodeLevel) is an
  explicit, user-confirmed deployment simplification for this pilot (see
  Spec above) — not a bug to "fix" during implementation or review. A
  general CIN>1 mechanism (widening `k` to `KH*KW*CIN`) is out of scope.
- The steady-state cycle-count abstraction (ignoring the paper's own
  `m+4`-cycle ProSparsity-processing-phase latency, since Section VI-B's
  inter-phase pipeline hides it behind the previous tile's computation
  phase) is likewise an explicit, paper-justified simplification, not a
  bug.
- COUT does not appear in the compute/access cycle formulas at all (see
  Cycle formulas above) — it's a fully-parallel hardware resource (128
  PEs, Table III), not a multiplier or additive latency term.

---

## Task 1: Prosperity input interface — `reconstruct_tile_sequence` with ProSparsity row-prefix compression

**Files:**
- Create: `src/snn_cosa/archmodels/prosperity/__init__.py`
- Create: `src/snn_cosa/archmodels/prosperity/reconstruct.py`

**Interfaces:**
- Consumes: `NodeTileSpec` from `src/snn_cosa/archmodels/__init__.py`;
  `snn_cosa.parsers.layer.{DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T,
  DIM_WO}` (pre-existing).
- Produces: `ProsperityRow`, `ProsperityReconstructed` (with
  `rows: List[ProsperityRow]`, already in PROCESSING order),
  `reconstruct_tile_sequence(trace, tile) -> ProsperityReconstructed`,
  and the pure-algorithm helper `_prosparsity_process(rows_bits,
  row_positions) -> List[ProsperityRow]` — consumed by Task 2's
  `cycles.py` (reads each row's `.pattern`) and `address.py` (reads
  `.pattern` for the weight-address stream).

- [ ] **Step 1: Write `prosperity/__init__.py`**

```python
"""Prosperity (Product-Sparsity SNN accelerator) ArchComputeModel plugin
-- pilot.

Reconstructs Prosperity's per-tile ProSparsity-compressed row sequence
from a real trace (reconstruct.py), then derives the pipeline cycle count
(cycles.py) and the ordered weight-address stream / weight_access_count
(address.py) from it. Standalone-verified against the pilot's own
hand-built worked example (reproducing Wei et al.'s own Fig. 1(d)/Fig. 2
canonical 6-row/4-column illustration exactly) and against a real
captured LoAS trace (input_trace/loas/) used purely as sample spike data.

This deployment fixes: tile size m=256 (HO=16, WO=16), k=16 (KH=4, KW=4,
CIN barred -- one input channel per node visit), n=128 (COUT), per Wei,
Guo, Cheng, Li, Yang, Li & Chen, "Prosperity: Accelerating Spiking Neural
Networks via Product Sparsity" (HPCA 2025), Table III's own evaluated
config -- this pilot's node size was given to match that table exactly,
not chosen independently. Unlike SpinalFlow/PTB/LoAS (HO/WO barred
entirely) and like GustavSNN, HO/WO ARE node-level resident here -- but
unlike GustavSNN's HO, neither HO nor WO is a spatial (parallel-PE) axis:
Prosperity's row-wise dataflow (Section V-E) processes the tile's rows
strictly SEQUENTIALLY through one shared 128-wide PE array (parallel only
across COUT/N), so HO and WO are both plain capped, non-spatial
node_dim_capacity entries -- see reconstruct.py's module docstring and
configs/arch/prosperity.yaml for the full rationale.
"""
```

- [ ] **Step 2: Write `reconstruct.py`**

```python
"""Builds Prosperity's per-tile ProSparsity-compressed row sequence from a
real spike trace.

Prosperity (Wei, Guo, Cheng, Li, Yang, Li & Chen, "Prosperity:
Accelerating Spiking Neural Networks via Product Sparsity", HPCA 2025)
tiles a layer's spiking GeMM into m x n x k sub-tiles (Section V-A,
Table III's evaluated config: m=256, k=16, n=128 -- exactly this
pilot's node size, per the pilot's own spec). Each of the tile's m rows
is one im2col'd receptive-field vector: k=16 bits, one per (kh, kw)
reduction index. This pilot fixes k = KH*KW = 4*4 = 16 with a SINGLE
input channel per node visit (CIN barred from NodeLevel entirely, one
channel per visit, tile.tile_offset[DIM_CIN] the absolute channel --
Table III's own k=16 has no CIN term, so this pilot does not attempt a
general CIN>1 mechanism; a future generalization would need k to absorb
CIN too, same tiling idea, more bits per row). T is likewise barred
entirely (one tick per node visit, tile.tile_offset[DIM_T] the absolute
tick) -- the paper's own spiking-GeMM formulation unrolls and
concatenates every timestep's spike matrix into extra M-dimension rows
(Section II-A), but this pilot's node size (m=256 = HO(16)*WO(16))
already exactly saturates the m=256 row budget with no room left for a
T factor, so this deployment processes one (HO,WO) block per tick,
mirroring GustavSNN's own T-barred, one-tick-per-visit precedent.

ProSparsity compression (Section III, Section III-D's heuristic
O(m) algorithm) has two parts:

  1. Temporal ordering (Section III-C, Section V-B "Temporal
     Detection"): the tile's m rows are processed in ASCENDING popcount
     order (a stable sort keeps original row order as the tiebreak among
     equal-popcount rows) -- required because a Partial-Match Prefix must
     always have fewer spikes than its Suffix, and an Exact-Match Prefix
     must have the smaller original row index (Section III-C).

  2. Prefix selection + XOR-based pattern generation (Section III-B's
     Partial Match/Exact Match relationships, pruned per Section III-D's
     "Pruning Rules" and Section V-C's "Efficient Pruning" to exactly one
     Prefix per row): among already-processed rows whose spike set is a
     SUBSET of the current row's spike set, pick the one with the largest
     overlap (most 1-bits, i.e. Section III-D's "largest common
     sub-combination"); ties broken by the largest row index (Section
     III-D: "we keep the edges from the node with largest index"). The
     row's `pattern` is then the bitwise XOR of its own bits against the
     chosen Prefix's bits (Section V-C's "ProSparsity Sparsifying": "the
     bit-wise XOR is equivalent to the operation Sq - Sp" since the
     Prefix is always a subset). A row with no valid Prefix emits its
     `pattern` unchanged (the full row) -- this is what
     `_prosparsity_process` below implements directly from the pilot's
     own worked pseudocode.

Assumes batch=0 and stride=1/no-padding convolution (hin=ho+kh,
win=wo+kw), matching
src/snn_cosa/archmodels/{spinalflow,ptb,loas,gustavsnn}/reconstruct.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class ProsperityRow:
    """One (ho, wo) output pixel's row, after ProSparsity processing.

    row_idx: this row's index in the tile's original row-major (ho, wo)
    enumeration (0..M-1) -- the "smaller/larger index" the paper's own
    Exact-Match tiebreak and Section III-D's "largest index" pruning rule
    both refer to. NOT the processing-order position (see
    ProsperityReconstructed.rows, which is already sorted into processing
    order).
    bits: this row's raw k-bit spike vector, one bit per (kh, kw) in
    nested [KH, KW] order (bit index = kh*KW_n + kw), for this tile's one
    fixed input channel and one fixed tick.
    prefix_row_idx: the row_idx of the chosen Prefix row, or None if this
    row had no valid subset candidate among already-processed rows (its
    `pattern` is then its own `bits`, unchanged).
    pattern: the residual bits actually computed for this row -- `bits`
    XOR the Prefix's `bits` (or `bits` itself if `prefix_row_idx` is
    None). This is what cycles.py/address.py both read: one weight fetch
    + one accumulate cycle per set bit in `pattern`.
    """

    row_idx: int
    ho: int
    wo: int
    bits: Tuple[int, ...]
    prefix_row_idx: Optional[int]
    pattern: Tuple[int, ...]


@dataclass
class ProsperityReconstructed:
    rows: List[ProsperityRow]  # in PROCESSING order (ascending-popcount stable sort)


def _prosparsity_process(
    rows_bits: List[Tuple[int, ...]], row_positions: List[Tuple[int, int]]
) -> List[ProsperityRow]:
    """Pure ProSparsity compression over already-extracted row bit-vectors.

    rows_bits[i]/row_positions[i] are this tile's row `i`'s bits/(ho, wo),
    in original row-major order (row_positions is only carried through for
    ProsperityRow's ho/wo fields, not used by the algorithm itself).
    Factored out from reconstruct_tile_sequence so the ProSparsity
    algorithm itself -- independent of how rows are sliced from a real
    trace -- can be verified directly against the pilot's own hand-built
    worked example (adjacent output rows' receptive fields overlap in any
    real stride-1 trace, so hand-picking arbitrary per-row bit patterns
    like the worked example's is only representable at this pure-data
    level, not through a single consistent trace tensor).
    """
    order = sorted(range(len(rows_bits)), key=lambda i: sum(rows_bits[i]))
    processed: List[int] = []
    result: List[ProsperityRow] = []
    for idx in order:
        bits = rows_bits[idx]
        candidates = [
            j
            for j in processed
            if all(rows_bits[j][b] == 0 or bits[b] == 1 for b in range(len(bits)))
        ]
        if candidates:
            prefix = max(candidates, key=lambda j: (sum(rows_bits[j]), j))
            pattern = tuple(a ^ b for a, b in zip(bits, rows_bits[prefix]))
        else:
            prefix = None
            pattern = bits
        ho, wo = row_positions[idx]
        result.append(ProsperityRow(idx, ho, wo, bits, prefix, pattern))
        processed.append(idx)
    return result


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> ProsperityReconstructed:
    """Return this tile's (one tick's, one channel's) ProSparsity-processed
    row sequence, one row per resident (ho, wo) output pixel.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the tile -- tile_offset[DIM_HO]/[DIM_WO] plus
               node_bound[DIM_HO]/[DIM_WO] select this tile's resident
               (ho, wo) rows (row-major order: ho outer, wo inner);
               node_bound[DIM_KH]/[DIM_KW] this tile's k=KH_n*KW_n bit
               width; tile_offset[DIM_T] the single absolute tick;
               tile_offset.get(DIM_CIN, 0) the single absolute input
               channel this visit covers (CIN barred from NodeLevel, see
               module docstring).
    """
    batch = 0
    cin = tile.tile_offset.get(DIM_CIN, 0)
    t = tile.tile_offset[DIM_T]
    ho_off = tile.tile_offset[DIM_HO]
    wo_off = tile.tile_offset[DIM_WO]
    ho_n = tile.node_bound[DIM_HO]
    wo_n = tile.node_bound[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]

    rows_bits: List[Tuple[int, ...]] = []
    row_positions: List[Tuple[int, int]] = []
    for ho in range(ho_off, ho_off + ho_n):
        for wo in range(wo_off, wo_off + wo_n):
            bits = tuple(
                int(trace[t, batch, cin, ho + kh, wo + kw])
                for kh in range(kh_n)
                for kw in range(kw_n)
            )
            rows_bits.append(bits)
            row_positions.append((ho, wo))

    return ProsperityReconstructed(rows=_prosparsity_process(rows_bits, row_positions))
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_prosperity_reconstruct.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.prosperity.reconstruct import (
    _prosparsity_process,
    reconstruct_tile_sequence,
)
from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

# --- Part A: the pilot's own worked example (== Wei et al.'s Fig. 1(d)/Fig. 2
# canonical 6-row illustration), tested at the pure-algorithm level (no trace
# needed -- adjacent output rows' receptive fields would otherwise conflict
# in any single real stride-1 trace; see reconstruct.py's docstring).
rows_bits = [
    (1, 0, 1, 0),  # Row0
    (1, 0, 0, 1),  # Row1
    (1, 0, 1, 1),  # Row2
    (0, 0, 1, 0),  # Row3
    (1, 1, 0, 1),  # Row4
    (1, 1, 0, 1),  # Row5
]
row_positions = [(i, 0) for i in range(6)]
processed = _prosparsity_process(rows_bits, row_positions)

order = [r.row_idx for r in processed]
assert order == [3, 0, 1, 2, 4, 5], order

expected_prefix = {3: None, 0: 3, 1: None, 2: 1, 4: 1, 5: 4}
expected_pattern = {
    3: (0, 0, 1, 0),
    0: (1, 0, 0, 0),
    1: (1, 0, 0, 1),
    2: (0, 0, 1, 0),
    4: (0, 1, 0, 0),
    5: (0, 0, 0, 0),
}
for r in processed:
    assert r.prefix_row_idx == expected_prefix[r.row_idx], (r.row_idx, r.prefix_row_idx)
    assert r.pattern == expected_pattern[r.row_idx], (r.row_idx, r.pattern)

total_spikes = sum(sum(r.pattern) for r in processed)
assert total_spikes == 6, total_spikes
print(f"Part A OK: processing order={order}, total residual spikes={total_spikes} "
      f"(matches the pilot's own worked example exactly)")

# --- Part B: reconstruct_tile_sequence's trace-slicing, cross-checked against
# an independent from-scratch recomputation over a small synthetic trace ----
trace = np.random.RandomState(0).randint(0, 2, size=(2, 1, 3, 6, 6)).astype(np.uint8)
tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 2, DIM_KW: 2, DIM_HO: 3, DIM_WO: 3},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 1, DIM_T: 1},
    is_last_K=True,
)
r = reconstruct_tile_sequence(trace, tile)
assert len(r.rows) == 9, len(r.rows)  # HO=3 * WO=3

expected_rows_bits = []
expected_positions = []
for ho in range(3):
    for wo in range(3):
        bits = tuple(
            int(trace[1, 0, 1, ho + kh, wo + kw]) for kh in range(2) for kw in range(2)
        )
        expected_rows_bits.append(bits)
        expected_positions.append((ho, wo))
expected = _prosparsity_process(expected_rows_bits, expected_positions)

got_by_idx = {row.row_idx: row for row in r.rows}
exp_by_idx = {row.row_idx: row for row in expected}
assert set(got_by_idx) == set(exp_by_idx) == set(range(9))
for idx in range(9):
    assert got_by_idx[idx].bits == exp_by_idx[idx].bits, idx
    assert got_by_idx[idx].pattern == exp_by_idx[idx].pattern, idx
    assert got_by_idx[idx].prefix_row_idx == exp_by_idx[idx].prefix_row_idx, idx
processing_order = [row.row_idx for row in r.rows]
expected_order = [row.row_idx for row in expected]
assert processing_order == expected_order, (processing_order, expected_order)
print(f"Part B OK: 9 rows (HO=3,WO=3) extracted from a synthetic trace, "
      f"cross-checked bit-for-bit and pattern-for-pattern against an "
      f"independent from-scratch recomputation; processing order={processing_order}")

# --- Part C: real LoAS trace, one 16x16 HO/WO block, one tick, one channel -
real_trace = np.load("input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy")
assert real_trace.shape == (4, 1, 64, 32, 32), real_trace.shape

real_tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 4, DIM_KW: 4, DIM_HO: 16, DIM_WO: 16},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0},
    is_last_K=True,
)
r2 = reconstruct_tile_sequence(real_trace, real_tile)
assert len(r2.rows) == 256, len(r2.rows)  # HO=16 * WO=16 == m=256, Table III

total_real_spikes = sum(sum(row.pattern) for row in r2.rows)
naive_total = sum(sum(row.bits) for row in r2.rows)  # bit-sparsity baseline, no compression
assert total_real_spikes <= naive_total, (total_real_spikes, naive_total)
print(f"Part C OK: 256 rows (HO=16,WO=16, matching Table III's m=256) from the real "
      f"trace -- ProSparsity residual spikes={total_real_spikes} vs. raw bit-sparsity "
      f"spikes={naive_total} (residual <= raw, as required: ProSparsity never adds work)")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_prosperity_reconstruct.py`
Expected:
```
Part A OK: processing order=[3, 0, 1, 2, 4, 5], total residual spikes=6 (matches the pilot's own worked example exactly)
Part B OK: 9 rows (HO=3,WO=3) extracted from a synthetic trace, cross-checked bit-for-bit and pattern-for-pattern against an independent from-scratch recomputation; processing order=<order>
Part C OK: 256 rows (HO=16,WO=16, matching Table III's m=256) from the real trace -- ProSparsity residual spikes=<N> vs. raw bit-sparsity spikes=<M> (residual <= raw, as required: ProSparsity never adds work)
```
(`<order>`, `<N>`, `<M>` depend on the random seed / real trace data — the
important assertions are the cross-checks, not specific hardcoded
numbers.)

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/prosperity/`
Stop here for review/comment.

---

## Task 2: Prosperity archmodel — `event_to_cycle` and `event_to_address`

**Files:**
- Create: `src/snn_cosa/archmodels/prosperity/cycles.py`
- Create: `src/snn_cosa/archmodels/prosperity/address.py`

**Interfaces:**
- Consumes: `ProsperityReconstructed`/`ProsperityRow` from Task 1's
  `reconstruct.py` (`cycles.py` reads each row's `.pattern`; `address.py`
  reads each row's `.pattern` directly); `NodeTileSpec` from
  `archmodels/__init__.py`; `snn_cosa.parsers.layer.{DIM_CIN, DIM_COUT,
  DIM_KW}` (pre-existing).
- Produces: `access_cycle_count(reconstructed) -> int`,
  `compute_cycle_count(reconstructed, tile) -> int`,
  `event_to_cycle(reconstructed, tile) -> int` (= `max` of the two,
  always equal here — no dominance case, see cycles.py),
  `event_to_address(reconstructed, tile) -> List[Tuple[int,int,int,int,int]]`,
  `weight_access_count(reconstructed) -> int` — consumed by a future
  `ProsperityComputeModel` (out of scope here, per Global Constraints).
  `compute_cycle_count`/`event_to_cycle` accept `tile` only for signature
  parity with SpinalFlow/PTB/LoAS/GustavSNN's shared convention — COUT
  (the only thing `tile` could contribute) is established to cost zero
  cycles, so `tile` plays no role in the formula.

- [ ] **Step 1: Write `cycles.py`**

```python
"""Prosperity cycle count: driven by ProSparsity row-prefix compression --
one cycle per residual ('pattern') spike, after each row reuses its
chosen Prefix row's already-computed partial sum (Wei, Guo, Cheng, Li,
Yang, Li & Chen, "Prosperity: Accelerating Spiking Neural Networks via
Product Sparsity", HPCA 2025).

Mirrors SpinalFlow's/LoAS's/GustavSNN's archmodels/<arch>/cycles.py
structure:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

though for Prosperity (like SpinalFlow/LoAS/GustavSNN) access_cycle_count
and compute_cycle_count always evaluate to the SAME quantity -- the
paper's own Processor design (Section V-E, Fig. 5(d)) issues exactly one
weight-fetch-and-accumulate cycle per residual spike bit: Step 10 (load
weight, one row of the K x N weight sub-matrix, decoded by bit-scan-
forward on the ProSparsity pattern) and Step 11 (accumulate into the
partial sum, across all N=128 output columns in parallel via the 128-PE
array) happen together, one residual bit per cycle, with no separate
access-vs-compute bottleneck to distinguish.

    cycle_count = sum over all rows in this tile of sum(row.pattern)

This is the pilot's explicit steady-state abstraction: the paper's own
ProSparsity *processing* phase (Detector/Pruner/Dispatcher identifying
each row's Prefix, m+4 cycles per tile, Section VI-A) is entirely hidden
by the *computation* phase of the PREVIOUS tile via the paper's own
inter-phase pipeline (Section VI-B: "the ProSparsity processing phase of
a tile is perfectly overlapped by the computation phase of the previous
tile... except for the first tile phase, which has a minor impact") --
this deployment counts only the steady-state computation-phase cycles,
the same "abstract away fixed pipeline fill/drain overhead" treatment
PTB/GustavSNN already apply to their own systolic/wave latencies.

COUT contributes ZERO incremental cycle cost, same treatment as
SpinalFlow/LoAS/GustavSNN -- Section V-A states this explicitly ("the
number of n has no impact on ProSparsity"): the 128-wide PE array
accumulates across the tile's whole assigned COUT range in the same
single cycle that consumes one residual spike bit, regardless of how
wide that COUT range is.
"""

from __future__ import annotations

from .. import NodeTileSpec
from .reconstruct import ProsperityReconstructed


def _total_pattern_spikes(reconstructed: ProsperityReconstructed) -> int:
    return sum(sum(row.pattern) for row in reconstructed.rows)


def access_cycle_count(reconstructed: ProsperityReconstructed) -> int:
    return _total_pattern_spikes(reconstructed)


def compute_cycle_count(reconstructed: ProsperityReconstructed, tile: NodeTileSpec) -> int:
    return _total_pattern_spikes(reconstructed)


def event_to_cycle(reconstructed: ProsperityReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
```

- [ ] **Step 2: Write `address.py`**

```python
"""Prosperity weight address per residual ('pattern') spike bit.

Each row's residual pattern (the query row's bits XOR its chosen Prefix
row's bits -- see reconstruct.py) still needs one weight-row fetch per
surviving 1-bit: the paper's Processor (Section V-E, Fig. 5(d) Step 10)
decodes the weight address by bit-scan-forward on the ProSparsity
pattern, fetching the K x N weight sub-matrix's row at that bit's
(kh, kw) index, spanning the FULL N=COUT range in one burst (the weight
sub-matrix has k rows and n columns, Section V-A) -- "load one line of
[KH, KW, COUT[start, start+127]]" per the pilot's own spec. This is
identical in shape to SpinalFlow's/PTB's/LoAS's/GustavSNN's own
(kh, kw, cin, cout_start, cout_end) burst tuples; cin is always this
tile's single fixed input channel (see reconstruct.py's module docstring
-- CIN is barred from NodeLevel in this pilot, one channel per node
visit), included only for shape parity with the other archmodels'
addresses, not because Prosperity's own weight indexing uses it.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_CIN, DIM_COUT, DIM_KW

from .. import NodeTileSpec
from .reconstruct import ProsperityReconstructed


def event_to_address(
    reconstructed: ProsperityReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    kw_n = tile.node_bound[DIM_KW]
    cin = tile.tile_offset.get(DIM_CIN, 0)
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]

    addrs: List[Tuple[int, int, int, int, int]] = []
    for row in reconstructed.rows:
        for bit_idx, bit in enumerate(row.pattern):
            if bit:
                kh, kw = divmod(bit_idx, kw_n)
                addrs.append((kh, kw, cin, cout_off, cout_off + cout_n))
    return addrs


def weight_access_count(reconstructed: ProsperityReconstructed) -> int:
    return sum(sum(row.pattern) for row in reconstructed.rows)
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_prosperity_cycles_address.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.prosperity.address import event_to_address, weight_access_count
from snn_cosa.archmodels.prosperity.cycles import (
    access_cycle_count,
    compute_cycle_count,
    event_to_cycle,
)
from snn_cosa.archmodels.prosperity.reconstruct import ProsperityReconstructed, _prosparsity_process
from snn_cosa.parsers.layer import DIM_CIN, DIM_COUT, DIM_KW

# --- Part A: the pilot's own worked example, now through cycles.py/address.py -
rows_bits = [
    (1, 0, 1, 0), (1, 0, 0, 1), (1, 0, 1, 1),
    (0, 0, 1, 0), (1, 1, 0, 1), (1, 1, 0, 1),
]
row_positions = [(i, 0) for i in range(6)]
processed = _prosparsity_process(rows_bits, row_positions)
r = ProsperityReconstructed(rows=processed)
tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KW: 2, DIM_COUT: 128},
    tile_offset={DIM_CIN: 0, DIM_COUT: 0},
    is_last_K=True,
)

a = access_cycle_count(r)
c = compute_cycle_count(r, tile)
assert a == 6 and c == 6, (a, c)
assert event_to_cycle(r, tile) == 6
addrs = event_to_address(r, tile)
assert len(addrs) == 6 == weight_access_count(r)
# processing order = [3,0,1,2,4,5]; row3 pattern (0,0,1,0)->bit2 (kh=1,kw=0);
# row0 pattern (1,0,0,0)->bit0 (kh=0,kw=0); row1 pattern (1,0,0,1)->bits0,3
# (kh=0,kw=0),(kh=1,kw=1); row2 pattern (0,0,1,0)->bit2 (kh=1,kw=0); row4
# pattern (0,1,0,0)->bit1 (kh=0,kw=1); row5 pattern all-zero -> no addresses.
assert addrs == [
    (1, 0, 0, 0, 128),  # row3, bit2 -> (kh=1,kw=0)
    (0, 0, 0, 0, 128),  # row0, bit0 -> (kh=0,kw=0)
    (0, 0, 0, 0, 128),  # row1, bit0
    (1, 1, 0, 0, 128),  # row1, bit3 -> (kh=1,kw=1)
    (1, 0, 0, 0, 128),  # row2, bit2
    (0, 1, 0, 0, 128),  # row4, bit1
], addrs
print(f"Part A OK: access={a}, compute={c}, total={event_to_cycle(r, tile)} "
      f"(== 6, the worked example's total residual spikes), "
      f"weight_access_count={weight_access_count(r)}, {len(addrs)} address bursts, "
      f"each spanning COUT[0,128) (n=128, Table III -- COUT never gates the count)")

# --- Part B: COUT-invariance -- same rows, much narrower COUT block ---------
tile_narrow = NodeTileSpec(
    dram_i=0, node_bound={DIM_KW: 2, DIM_COUT: 8}, tile_offset={DIM_CIN: 0, DIM_COUT: 0}, is_last_K=True,
)
a_narrow = access_cycle_count(r)
c_narrow = compute_cycle_count(r, tile_narrow)
assert a_narrow == a == 6 and c_narrow == c == 6
addrs_narrow = event_to_address(r, tile_narrow)
assert all(addr[4] - addr[3] == 8 for addr in addrs_narrow)
print(f"Part B OK: COUT=8 gives the same cycle count ({c_narrow}) as COUT=128 -- "
      f"only the address range narrows (every burst now spans 8 cout entries)")

# --- Part C: fully-silent tile edge case -------------------------------------
silent_rows_bits = [(0, 0, 0, 0)] * 4
silent_positions = [(i, 0) for i in range(4)]
r_silent = ProsperityReconstructed(rows=_prosparsity_process(silent_rows_bits, silent_positions))
tile_silent = NodeTileSpec(
    dram_i=0, node_bound={DIM_KW: 2, DIM_COUT: 128}, tile_offset={DIM_CIN: 0, DIM_COUT: 0}, is_last_K=True,
)
assert access_cycle_count(r_silent) == 0
assert compute_cycle_count(r_silent, tile_silent) == 0
assert event_to_cycle(r_silent, tile_silent) == 0
assert event_to_address(r_silent, tile_silent) == []
assert weight_access_count(r_silent) == 0
print("Part C OK: fully-silent tile -> 0 cycles, 0 weight accesses")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_prosperity_cycles_address.py`
Expected:
```
Part A OK: access=6, compute=6, total=6 (== 6, the worked example's total residual spikes), weight_access_count=6, 6 address bursts, each spanning COUT[0,128) (n=128, Table III -- COUT never gates the count)
Part B OK: COUT=8 gives the same cycle count (6) as COUT=128 -- only the address range narrows (every burst now spans 8 cout entries)
Part C OK: fully-silent tile -> 0 cycles, 0 weight accesses
```

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/prosperity/`
Stop here for review/comment.

---

## Task 3: Prosperity arch YAML + real MIP-solved single-node schedule

Per [[feedback_archmodel_deliverable_scope]]: Tasks 1-2 only exercise the
Python plugin against hand-built/real-trace fixtures. This task builds
the actual hardware-capacity *input interface* the MIP solver consumes —
`configs/arch/prosperity.yaml` — and runs a real `snn_cosa solve` against
it to produce a genuine Prosperity single-node schedule, proving the
config is solver-feasible and encodes the right node-level residency.

**Files:**
- Create: `configs/arch/prosperity.yaml`
- Create: `outputs/prosperity_single_node_schedule.json` (solver output,
  gitignored)

**Interfaces:**
- Consumes: `snn_cosa.parsers.arch.SNNArch` (`node_dim_capacity`,
  `single_node`, `{spatial: N}` form — all pre-existing, no changes
  needed to the solver for this task).
- Produces: a schedule JSON consumable by `snn_cosa.nocsim.sim` (same
  contract as `outputs/single_node_schedule.json` /
  `outputs/ptb_single_node_schedule.json` /
  `outputs/loas_single_node_schedule.json` /
  `outputs/gustavsnn_single_node_schedule.json`).

- [ ] **Step 1: Write `configs/arch/prosperity.yaml`**

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8    # paper-confirmed: "the bitwidth of weights is set to 8 bits" (Section VII-A)
    BW_PSUM:   16
    BW_VMEM:   32
    DRAM_LATENCY: 17

  # single_node: Prosperity's PPU (Detector/Pruner/Dispatcher/Processor,
  # Fig. 4) is fed directly from its Spike/Weight/Output buffers -- no
  # inter-node NoC, so no physical Global Buffer level at this scope
  # (mirrors spinalflow.yaml/ptb.yaml/loas.yaml/gustavsnn.yaml's
  # reasoning).
  #
  # node_dim_capacity: this deployment's node-level dimension set,
  # matching Table III's own tile size (m=256, k=16, n=128) exactly.
  #
  # KH/KW capped at 4 each (product = k = 16, Table III) -- NOT null/full-
  # residency like LoAS's/GustavSNN's forced-full reduction row: k=16 is
  # a genuine HARDWARE capacity limit (the TCAM's fixed entry width,
  # Section V-B), not "however big the workload's real KH*KW happens to
  # be." A layer whose real KH*KW exceeds 16 needs extra DRAM-level KH/KW
  # iterations (same capped-dim leftover mechanism PTB's/GustavSNN's own
  # KH/KW=4 and WO=8 caps already use).
  #
  # CIN absent -- BARRED from NodeLevel entirely: this pilot fixes ONE
  # input channel per node visit. Table III's own k=16=KH(4)*KW(4) has no
  # CIN term at all -- a general CIN>1 mechanism would need k to widen to
  # KH*KW*CIN, out of scope for this pilot (see reconstruct.py's module
  # docstring).
  #
  # T absent -- also BARRED entirely, one node visit = one tick. The
  # paper's own spiking-GeMM formulation folds every timestep into extra
  # M-dimension rows (Section II-A), but this pilot's node size
  # (m=256=HO(16)*WO(16)) already exactly saturates the m=256 budget with
  # the given HO/WO shape alone -- mirrors GustavSNN's own T-barred
  # precedent.
  #
  # COUT uses {spatial: 128} -- the paper's own n=128 (Table III:
  # "Processor 128 PEs 8-bit Add, n=128"), validated against pe.num_pes
  # (V1). Section V-A states explicitly "the number of n has no impact on
  # ProSparsity" -- COUT costs zero incremental cycles, same treatment as
  # SpinalFlow/LoAS/GustavSNN.
  #
  # HO/WO use plain capped ints (16 each, NOT spatial) -- together these
  # two axes flatten into the tile's m=256 rows (m = HO*WO = 16*16 =
  # 256, Table III), but NEITHER is a parallel-PE axis: Section V-E states
  # plainly that Prosperity's Processor is a ROW-WISE dataflow, "a spike
  # row... is processed AT A TIME" -- the tile's rows are consumed
  # strictly SEQUENTIALLY by one shared 128-wide PE array (parallel only
  # across N/COUT, matching the 128 PEs above), not one PE per row the
  # way GustavSNN's spatial HO axis was. This is genuinely symmetric
  # treatment for HO/WO (both plain capped, non-spatial), unlike
  # GustavSNN's asymmetric HO(spatial)/WO(capped) split -- verified
  # against the paper's own row-wise-sequential Processor design, not
  # assumed from visual symmetry (see
  # docs/superpowers/plans/2026-07-15-archmodel-prosperity-pilot.md's
  # Spec section and [[feedback_symmetric_hw_dims]]'s refinement). Their
  # product (16*16=256) automatically enforces the paper's own m=256 cap
  # without any joint-dimension V1 check, since neither is spatial-
  # tagged.
  single_node: true
  node_dim_capacity:
    KH:   4
    KW:   4
    COUT: {spatial: 128}
    HO:   16
    WO:   16

  storage:             # innermost first
    - name: NodeLevel
      instances: 1
      pe:
        num_pes: 128    # Table III: "Processor 128 PEs 8-bit Add, n=128"
    - name: NoCLevel
      # entries omitted: no physical Global Buffer exists (single_node:
      # true), so there's nothing real to size -- absent means no capacity
      # check for this level (has_noc_buffer=False).
      instances: 1
    - name: OffChip
      instances: 1
```

- [ ] **Step 2: Confirm the chosen workload actually exercises node capacity**

`configs/workloads/generated/vgg16/T4/conv2_1.yaml`
(`KH=3, KW=3, CIN=64, COUT=128, HO=112, WO=112, T=4`) — the same workload
already used to verify LoAS's and GustavSNN's configs (see
`2026-07-14-archmodel-loas-pilot.md`'s Task 3 and
`2026-07-15-archmodel-gustavsnn-pilot.md`'s Task 3). Reused deliberately
for continuity, and because it happens to exercise every interesting path
here at once:
- `COUT=128` divides the `{spatial: 128}` cap exactly, with zero leftover
  (V2 satisfied trivially — the first pilot in this plan where COUT is
  fully consumed by the spatial fanout alone).
- `HO=112` and `WO=112` both divide the plain `16` cap exactly
  (`112/16=7`, V2's exact-divisibility requirement for a capped dim) —
  each gets a deterministic NodeLevel-resident factor of `16` with a
  deterministic leftover factor of `7` forced to DRAM (no MIP freedom,
  per `node_capacity.py`'s docstring on capped dims) — the first real
  test of BOTH HO and WO using this capped-leftover-to-DRAM path
  simultaneously.
- `KH=3, KW=3` both fit within their `4` caps with no leftover (fully
  resident, since `3 <= 4`).
- `CIN=64` and `T=4` are both entirely barred from NodeLevel, so all of
  each must appear at the DRAM permutation level — the first real test of
  CIN being routed to DRAM (T barred already has GustavSNN precedent;
  CIN barred is new to this pilot).

- [ ] **Step 3: Run the solver**

```bash
export PYTHONPATH=src
python3 -m snn_cosa solve \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/prosperity.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/prosperity_single_node_schedule.json
```
Expected: `status: OPTIMAL`, `objective: <float>`,
`output: outputs/prosperity_single_node_schedule.json`.

Then inspect the strategy:
```bash
python3 -c "
import json
d = json.load(open('outputs/prosperity_single_node_schedule.json'))
print(json.dumps(d['strategy'], indent=2))
"
```
Expected, and confirm by reading the actual printed JSON (don't assume —
report what the solver actually picked where this plan notes freedom):
- `NodeLevel.temporal_tile.factors` contains `KH=3, KW=3` (fully
  resident, under their `4` caps) and `HO=16, WO=16` (deterministically
  pinned by their plain int caps — no MIP freedom in these values, per
  `node_capacity.py`'s docstring); no `CIN` or `T` entry at all (both
  entirely barred from NodeLevel).
- `NodeLevel.spatial_split.factors` contains exactly `COUT=128`.
- `NoCLevel` both permutation/split are empty (`single_node` bars it).
- `DRAM.temporal_permutation.loops` contains `CIN` (factor `64`, entirely
  barred from NodeLevel), `T` (factor `4`, entirely barred), and the
  deterministic capped leftovers `HO=7` and `WO=7` (`112/16` each,
  forced to DRAM since NodeLevel is capped and NoCLevel is barred — see
  `node_capacity.py`'s docstring on capped dims having no placement
  freedom for their leftover). No leftover `COUT` factor should appear
  anywhere (`128` divides the spatial cap with zero remainder).

- [ ] **Step 4: Run the solved schedule through the NoC simulator**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/prosperity_single_node_schedule.json \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/prosperity.yaml \
  --out /tmp/prosperity_tc.csv --simulate
```
Expected: exits 0 and prints `transactions`, `dram_cost`, `total_cycles`,
etc. (Cycle numbers here come from the default `DenseStaticComputeModel`,
NOT `archmodels/prosperity/cycles.py` — wiring Prosperity's real per-tile
model into this live loop is still out of scope, per the Global
Constraints. This step only proves the config produces a schedule the
simulator can run, not that the printed cycle count reflects Prosperity's
real hardware behavior.)

- [ ] **Step 5: Present for review**

Run: `git status --short configs/arch/prosperity.yaml` (expect untracked
— gitignored like `spinalflow.yaml`/`ptb.yaml`/`loas.yaml`/
`gustavsnn.yaml`; the repo's `.gitignore` blanket-ignores `*.yaml`/
`*.json` and only 3 config files are actually committed:
`configs/arch/snn_arch.yaml`, `configs/mapspace/mapspace.yaml`,
`configs/workloads/sample_snn_layer.yaml`). If the user wants
`prosperity.yaml` committed, it needs `git add -f`.
Stop here — this completes the plan. A full `ProsperityComputeModel`
implementing `ArchComputeModel` end-to-end (wired into `combine()`'s live
per-tile loop, consuming this real solved schedule's tile boundaries) is
a later plan, deferred per the Global Constraints section above. A
general CIN>1 mechanism (widening k to KH*KW*CIN) is likewise deferred.

---

## Self-review notes

- **Spec coverage:** the paper<->project symbol mapping (m=HO*WO,
  k=KH*KW with CIN fixed at 1, n=COUT, all matching Table III's own
  m=256/k=16/n=128 exactly) — covered in the Spec table and validated
  against a real workload in Task 3. ProSparsity's Partial
  Match/Exact Match/single-Prefix pruning/ascending-popcount-stable-sort
  algorithm — covered by `_prosparsity_process` and Task 1's Part A,
  which reproduces the paper's own Fig. 1(d)/Fig. 2 worked example bit-
  for-bit (order, prefix choice, and pattern for all 6 rows, plus the
  total-spike count of 6). Trace-slicing correctness (independent of the
  algorithm itself) — covered by Task 1's Parts B/C, cross-checked
  against from-scratch recomputation. HO/WO NodeLevel residency, and the
  paper-verified (not assumed) reasoning for why both are non-spatial
  unlike GustavSNN's HO — covered in `configs/arch/prosperity.yaml`'s
  module comment and Task 3's real solve. CIN-barred/T-barred (both
  entirely DRAM-looped) — covered in `reconstruct.py`'s module docstring
  and Task 3's real solve (the first test of CIN routed to DRAM in this
  plan). `access_cycle_count == compute_cycle_count == total residual
  spikes` (no dominance case, steady-state abstraction ignoring the
  paper's own hidden ProSparsity-processing-phase latency) — covered in
  Task 2's Parts A/B/C. Weight loading = one burst per residual spike,
  spanning the tile's whole COUT range — covered in `address.py` and
  Task 2's Part A (exact address list matching the worked example) and
  Part B (COUT-invariance). Hardware-capacity input interface
  (`configs/arch/prosperity.yaml`) and a real MIP-solved single-node
  schedule — covered in Task 3, using the same `vgg16/T4/conv2_1.yaml`
  workload LoAS/GustavSNN used, which happens to exercise every
  interesting path (COUT exact-fit spatial, HO/WO capped-leftover-to-
  DRAM, CIN/T fully-barred-to-DRAM) simultaneously.
- **No placeholders:** every step has complete, runnable code and an
  exact verification command with expected output (Task 3's solver-
  output inspection intentionally asks the executor to report the
  actual JSON rather than a number that can't be predicted without
  running Gurobi, consistent with every prior pilot in this plan).
- **Type consistency:** `ProsperityRow`/`ProsperityReconstructed`
  (Task 1) are consumed by `cycles.py` (reads only `row.pattern` per
  row) and `address.py` (reads only `row.pattern` per row) in Task 2 —
  no field is read that Task 1 doesn't produce. `_prosparsity_process`
  is defined once, in `reconstruct.py`, and reused by both
  `reconstruct_tile_sequence` (Task 1) and Task 1's/Task 2's own
  verification scripts, not duplicated. `NodeTileSpec`, `ComputeCycles`
  match `archmodels/__init__.py`'s existing definitions (unchanged by
  this plan).
