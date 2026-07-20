# Arch-specific cycle count — GustavSNN pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this run:** per the SpinalFlow/PTB/LoAS pilots'
> established convention, treat every task as its own checkpoint — present
> the diff for review at the end of each task rather than auto-committing
> (commit only when the user explicitly asks, per repo convention). If
> executed via subagent-driven-development instead (LoAS's precedent),
> that skill's commit-per-task ledger mechanism applies instead — confirm
> with the user which mode before starting.

## Spec (rephrased)

This targets GustavSNN, from Hwang, Lee, Koo & Kung, *"GustavSNN:
Unleashing the Power of Gustavson's Algorithm on SNN Acceleration with
Column-Parallel Tick-Batch Dataflow"* (HPCA 2026), as the fifth of the
6-architecture cycle-count plan (SpinalFlow was the pilot, PTB the third,
LoAS the fourth — see `docs/superpowers/plans/2026-07-12-archmodel-
spinalflow-pilot.md`, `2026-07-14-archmodel-ptb-pilot.md`, and
`2026-07-14-archmodel-loas-pilot.md`; Prosperity and Phi remain
unstarted after this).

GustavSNN's mapping onto this project's DIM system, confirmed against the
paper's own notation (Section II-B/IV, Algorithm 1, Table II):

| Paper symbol | This project |
|---|---|
| `M` (weight-matrix A rows) | `COUT` |
| `D` (reduction dim) | `K` = KH·KW·CIN |
| `N` (spike-matrix B columns) | `HO·WO` |
| `P` (column-partition width) | `WO`, capped at 8 per node visit (this deployment, matching the paper's own best config, Fig. 16/Table II) |
| `K` submatrices (`=N/P`) | `HO`, spatially split 8-wide — one resident HO row = one submatrix = one PE |

This deployment departs from the paper in explicit, user-specified ways
(confirmed interactively, not paper-fidelity bugs):

- **T (timestep) is barred from NodeLevel entirely — one node visit
  covers exactly one tick.** Unlike LoAS (fully temporal-parallel, T
  contributes zero cycles) or PTB (T windowed), GustavSNN's Algorithm 1
  loop order is `for t: for d: for n` and Section V-B's column-major
  time-second scheduling re-derives which D-rows are silent **fresh at
  every tick**, firing LIF, before advancing to the next tick (Fig. 12).
  This deployment therefore treats T the same way SpinalFlow/PTB/LoAS
  treat HO/WO: barred from NodeLevel, looped at the DRAM permutation
  level by the MIP. `reconstruct_tile_sequence` never loops over T at
  all — `tile.tile_offset[DIM_T]` is the one absolute tick this call
  covers.
- **HO/WO ARE node-level resident, unlike SpinalFlow/PTB/LoAS, which bar
  them — but asymmetrically, not both spatial.** GustavSNN's CPTB
  dataflow needs multiple output pixels resident and column-partitioned
  across PEs *simultaneously* within one node visit — that's the entire
  point of the P-wide submatrix partitioning (Section IV-C). This is the
  first architecture in this project's 6-arch plan where HO/WO carry any
  NodeLevel residency. Mapping the paper's flattened 1-D `N` (with its
  `K` submatrices of width `P`) onto this project's two separate HO/WO
  DIM axes needs each axis to play a genuinely different hardware role,
  confirmed against this project's own MIP validation (V1: the *product*
  of every `{spatial: N}`-tagged dimension across the whole arch must fit
  `pe.num_pes` — marking BOTH HO and WO `{spatial: 8}` would require
  `COUT(8) x HO(8) x WO(8) = 512 <= num_pes`, when the paper's real
  hardware has only 64 PEs total, 8 tiles x 8 PEs/tile). The correct
  split, matching how a real conv layer's output actually traverses row-
  major: **HO is the genuinely spatial dim** (`{spatial: 8}` — 8
  resident HO rows, 8 physically parallel PEs/tile, one row = one
  submatrix = one PE, matching `K` submatrices), and **WO is a plain
  capped (temporal) residency of 8** (this visit's P=8-wide column
  window within each HO-row's submatrix — the paper's `P`). `num_pes =
  COUT(8) x HO(8) = 64`, matching Table II/Fig. 17 exactly; WO's cap
  isn't spatial-tagged, so it's excluded from the V1 product check
  entirely.
- **The exact split values (COUT/HO spatial fanout of 8, WO cap of 8) are
  a hardcoded, workload-derived choice, not a general mechanism.** There
  is no existing MIP machinery for treating a *joint* budget spanning two
  separate dimensions generically for any workload shape — this
  deployment picks a real workload whose actual `(HO, WO)` shape supports
  this specific split (`configs/workloads/generated/vgg16/T4/conv2_1.yaml`,
  `HO=WO=112`, both divisible by/cappable-to 8) rather than building a
  general "any workload's HO/WO shape" mechanism (bigger scope than any
  prior pilot — see Global Constraints).
- **Row-level (not element-level) cycle abstraction.** A submatrix's cost
  is its count of non-zero `(kh,kw,cin)` "lines" (NRV rows, Section
  IV-D/Fig. 7) — the paper's own actual merger-tree PE (Fig. 9) emits
  *one non-zero column index per cycle*, meaning a "non-zero row" with
  several non-zero columns really costs several cycles in the real
  hardware. This pilot uses the coarser row-count abstraction, matching
  the user's own explicit formula ("count non-zero lines, take max") and
  mirroring LoAS's/PTB's own precedent of abstracting away fine-grained
  pipeline/systolic timing for a first pilot.
- **No cross-PE weight-fetch deduplication.** The paper's Section V-A
  shares one local weight buffer across all PEs in a tile (a weight row
  fetched once, reused by every PE whose submatrix needs the same
  `(kh,kw,cin)` this tick). This deployment does not model that sharing:
  each submatrix's non-zero rows independently trigger their own weight
  fetch, so up to `PE_COUNT_MAX=8` distinct weight-line fetches can be
  issued per cycle-position, even when two submatrices want the identical
  address — an explicit, user-specified simplification ("up to 8 weight
  lines to be fetched... per cycle").
- **`access_cycle_count == compute_cycle_count`** (both driven by
  max-across-parallel-PEs), same "no dominance" shape as SpinalFlow/LoAS,
  though for a different underlying reason here: PE-level parallelism
  (`parallel-for k` in Algorithm 1) bottlenecks both the weight-fetch and
  execution sides on whichever PE has the most non-zero rows this tick,
  not a single flat pipeline.
- **COUT contributes zero incremental cycle cost**, same treatment as
  SpinalFlow/LoAS — all `COUT:{spatial:8}` tiles (M'=8, Table II) share
  the identical per-tick NRV structure, since it depends only on spike
  data, never on which output channel. `COUT: {spatial: 8}` matches the
  paper's own evaluated Table II/Fig. 17 config (8 tiles) exactly.

**Goal:** Build GustavSNN's `reconstruct_tile_sequence` / `event_to_cycle`
/ `event_to_address` trio (matching the SpinalFlow/PTB/LoAS pilots'
architecture-owned 3-stage pattern), plus `configs/arch/gustavsnn.yaml`
and a real MIP-solved single-node schedule proving the config is
solver-feasible (per [[feedback_archmodel_deliverable_scope]] — the YAML
+ solve step is part of "build the archmodel," not an optional
follow-up).

**Architecture:** `src/snn_cosa/archmodels/gustavsnn/{__init__.py,
reconstruct.py, cycles.py, address.py}`, standalone and unwired (same
scope as the SpinalFlow/PTB/LoAS pilots — live wiring into `combine()`'s
per-tile loop is a separate, later design pass for every architecture in
this plan). `reconstruct.py` builds, for one tick, one submatrix per
resident HO row (each spanning that row's full resident WO width, this
visit's P), each independently NRV-compressed (non-zero `(kh,kw,cin)`
rows only).

**Tech Stack:** Python 3, numpy, existing `snn_cosa` stack. No pytest in
this repo — verification runs a script and checks exact printed output,
per existing convention.

## Global Constraints

- Zero regression: this plan touches no shared code (`archmodels/__init__.py`'s
  `ComputeCycles.lif_cycles: Optional[int] = None` convention and
  `combine.py`'s handling of it already exist from the PTB pilot —
  GustavSNN reuses them as-is, no further changes needed there).
- No new third-party dependencies.
- `reconstruct_tile_sequence`, `event_to_cycle`, `event_to_address` are
  GustavSNN-owned, not shared with SpinalFlow, PTB, LoAS, or any other
  architecture — do not refactor those to share code with GustavSNN's.
- Out of scope for this plan (needs its own design pass): wiring a full
  `GustavSNNComputeModel` implementing the `ArchComputeModel` Protocol
  into `combine()`'s live per-tile loop. This plan only proves the
  GustavSNN plugin correct standalone, against hand-specified tiles, a
  real captured trace, and a real MIP-solved schedule.
- Out of scope for this plan: a general joint-dimension spatial-cap
  mechanism in `node_capacity.py`/`node_level.py` that would let the MIP
  freely split a target product (like `N=64`) across two separate DIM
  axes (HO, WO) for *any* workload shape. This pilot hardcodes the split
  for one real, evenly-divisible workload instead (see Spec above) — a
  future design pass should revisit if a workload whose HO/WO don't
  divide by 8 needs to be scheduled.
- The row-level (not element-level) cycle abstraction and the lack of
  cross-PE weight-fetch deduplication are both explicit, user-confirmed
  simplifications (see Spec above) — not bugs to "fix" during
  implementation or review.
- COUT does not appear in the compute/access cycle formulas at all (see
  Cycle formulas above) — it's a fully-parallel hardware resource (8
  tiles, Table II), not a multiplier or additive latency term.

---

## Task 1: GustavSNN input interface — `reconstruct_tile_sequence` with per-tick, per-submatrix NRV compression

**Files:**
- Create: `src/snn_cosa/archmodels/gustavsnn/__init__.py`
- Create: `src/snn_cosa/archmodels/gustavsnn/reconstruct.py`

**Interfaces:**
- Consumes: `NodeTileSpec` from `src/snn_cosa/archmodels/__init__.py`;
  `snn_cosa.parsers.layer.{DIM_KH, DIM_KW, DIM_CIN, DIM_HO, DIM_WO,
  DIM_T}` (pre-existing).
- Produces: `GustavLine`, `GustavSubmatrix`, `GustavReconstructed` (with
  `submatrices: List[GustavSubmatrix]`),
  `reconstruct_tile_sequence(trace, tile) -> GustavReconstructed` —
  consumed by Task 2's `cycles.py` (reads each submatrix's `.lines`
  count) and `address.py` (reads `.lines` for the weight-address
  stream).

- [ ] **Step 1: Write `gustavsnn/__init__.py`**

```python
"""GustavSNN (Column-Parallel Tick-Batch Gustavson-product SNN
accelerator) ArchComputeModel plugin -- pilot.

Reconstructs GustavSNN's per-tile, per-tick NRV-compressed column-
partition submatrix sequence from a real trace (reconstruct.py), then
derives the pipeline cycle count (cycles.py) and the ordered weight-
address stream / weight_access_count (address.py) from it. Standalone-
verified against a real captured LoAS trace (input_trace/loas/) used
purely as sample spike data, and against hand-built examples reproducing
the paper's own NRV row-skip mechanism (Fig. 7) at multiple ticks.

This deployment fixes: column-partition width P=8, 8 tiles x 8 PEs/tile
(64 PEs total), matching the paper's own Table II/Fig. 17 evaluated
config, per Hwang, Lee, Koo & Kung, "GustavSNN: Unleashing the Power of
Gustavson's Algorithm on SNN Acceleration with Column-Parallel Tick-Batch
Dataflow" (HPCA 2026), Sections IV-V. Unlike SpinalFlow/PTB/LoAS, T is
barred from NodeLevel (one node visit = one tick) and HO/WO ARE NodeLevel
resident (spatially split) -- see reconstruct.py's module docstring and
configs/arch/gustavsnn.yaml for the full rationale.
"""
```

- [ ] **Step 2: Write `reconstruct.py`**

```python
"""Builds GustavSNN's per-tile, per-tick NRV (non-zero row vector)
compressed submatrix sequence from a real spike trace.

GustavSNN's column-parallel tick-batch (CPTB) dataflow (Hwang, Lee, Koo &
Kung, HPCA 2026) partitions a tile's HO*WO output-pixel range ("N", the
paper's flattened spike-matrix column count) into P-wide column
submatrices (Section IV-C, Algorithm 1's `Bk = [B0|B1|...|BK-1]`), one
submatrix per PE (up to PE_COUNT_MAX=8 PEs per tile in cycles.py, Table
II). This project keeps HO and WO as two separate DIM axes rather than
one flattened N, so this deployment maps the paper's 1-D column-partition
onto them asymmetrically, matching how a real conv layer's output
actually traverses row-major and matching this project's own MIP
validation (see configs/arch/gustavsnn.yaml's module comment for the full
V1 rationale): **one resident HO row = one submatrix = one PE** (the
paper's `K` submatrices, HO genuinely spatially parallel), and **each
submatrix spans that row's full resident WO width** (the paper's `P`,
this deployment capped at 8 -- see configs/arch/gustavsnn.yaml's `WO: 8`).

Within a submatrix, NRV format (Section IV-D, Fig. 7) drops any
(kh,kw,cin) reduction-index "row" that is entirely zero across that
submatrix's WO-wide columns -- but critically, this is evaluated FRESH AT
EVERY TICK (Algorithm 1's `for t: for d:` loop order; Section V-B's
column-major time-second scheduling sweeps the full D range for one
tick, fires LIF, THEN advances to the next tick, Fig. 12), not once
across the whole T range like LoAS's silent-neuron compression.

This deployment therefore bars T from NodeLevel residency entirely (see
configs/arch/gustavsnn.yaml) -- one node visit here covers exactly ONE
tick, mirroring how HO/WO are barred (DRAM-looped) in
SpinalFlow/PTB/LoAS. tile.tile_offset[DIM_T] gives that one absolute
tick; there is no T loop inside this module at all, and node_bound has no
DIM_T entry to read.

Unlike SpinalFlow/PTB/LoAS (which bar HO/WO from NodeLevel -- one node
visit = one output pixel), GustavSNN's CPTB dataflow needs multiple
output pixels resident and column-partitioned at once, so HO/WO ARE
node-level resident here. tile.node_bound[DIM_HO] gives this visit's
resident HO-row count (one GustavSubmatrix per row); tile.node_bound[DIM_WO]
gives each row's resident WO width (that submatrix's `positions`) -- both
read directly from the tile rather than hardcoded, so this function stays
correct even if a real solve grants more/less residency than the YAML's
nominal 8/8 (e.g. extra temporal residency beyond the spatial cap -- see
cycles.py's wave handling for what happens when node_bound[DIM_HO] > 8).

Assumes batch=0 and stride=1/no-padding convolution (hin=ho+kh,
win=wo+kw), matching
src/snn_cosa/archmodels/{spinalflow,ptb,loas}/reconstruct.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class GustavLine:
    """One non-zero (kh, kw, cin) reduction-index row within one
    submatrix, at this tile's one tick.

    Carries no bit-vector (unlike PTB's/LoAS's per-line T-length bits) --
    GustavSNN's NRV re-derives silence fresh per tick (see module
    docstring), so there is nothing to pack across time here; a line's
    mere presence in a GustavSubmatrix.lines means "non-zero this tick,
    this submatrix."
    """

    kh: int
    kw: int
    cin: int


@dataclass
class GustavSubmatrix:
    """One HO row's WO-wide column-partition submatrix (one PE's assigned
    slice of the tile's HO*WO output-pixel range), at this tile's one
    tick.

    positions: the (ho, wo) output pixels covered by this submatrix --
    a single fixed ho paired with every wo in this tile's resident WO
    range (this visit's P-wide window).
    lines: the non-zero (kh, kw, cin) rows for this submatrix, i.e. every
    reduction index with at least one spike among `positions` at this
    tick -- NRV's row-skip result (Fig. 7).
    """

    piece_idx: int
    positions: List[Tuple[int, int]]
    lines: List[GustavLine]


@dataclass
class GustavReconstructed:
    submatrices: List[GustavSubmatrix]


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> GustavReconstructed:
    """Return this tile's (one tick's) NRV-compressed submatrix sequence,
    one submatrix per resident HO row.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the tile -- tile_offset[DIM_HO] plus
               node_bound[DIM_HO] select this tile's resident HO rows
               (one GustavSubmatrix per row); tile_offset[DIM_WO] plus
               node_bound[DIM_WO] select each row's resident WO width
               (this visit's P-wide column window); node_bound[DIM_KH]/
               [DIM_KW]/[DIM_CIN] the full reduction row (must be
               entirely resident -- see module docstring);
               tile_offset[DIM_T] the single absolute tick this node
               visit covers.
    """
    batch = 0
    t = tile.tile_offset[DIM_T]
    ho_off = tile.tile_offset[DIM_HO]
    wo_off = tile.tile_offset[DIM_WO]
    ho_n = tile.node_bound[DIM_HO]
    wo_n = tile.node_bound[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    cin_n = tile.node_bound[DIM_CIN]
    cin_off = tile.tile_offset.get(DIM_CIN, 0)

    submatrices: List[GustavSubmatrix] = []
    for piece_idx, ho in enumerate(range(ho_off, ho_off + ho_n)):
        positions = [(ho, wo) for wo in range(wo_off, wo_off + wo_n)]
        lines: List[GustavLine] = []
        for kh in range(kh_n):
            for kw in range(kw_n):
                for cin in range(cin_off, cin_off + cin_n):
                    active = any(
                        trace[t, batch, cin, ho + kh, wo + kw]
                        for _, wo in positions
                    )
                    if active:
                        lines.append(GustavLine(kh, kw, cin))
        submatrices.append(GustavSubmatrix(piece_idx, positions, lines))

    return GustavReconstructed(submatrices=submatrices)
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_gustavsnn_reconstruct.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.gustavsnn.reconstruct import reconstruct_tile_sequence
from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

# --- Part A: per-tick re-derivation (KH=KW=1, CIN=4, one 8-wide row of WO) --
# t=0: cin0 fires at wo={1,4,7}; cin3 fires at wo={0,2,3}; cin1,cin2 silent.
# t=1: cin1 fires at wo={0,3}; cin3 fires at wo={3}; cin0,cin2 silent.
# This is the plan's own worked example: cin0 flips active->silent and cin1
# flips silent->active between ticks, proving NRV silence is re-derived
# fresh per tick, not cached/OR'd across T.
trace = np.zeros((2, 1, 4, 1, 8), dtype=np.uint8)  # [T=2, B=1, Cin=4, Hin=1, Win=8]
trace[0, 0, 0, 0, 1] = 1
trace[0, 0, 0, 0, 4] = 1
trace[0, 0, 0, 0, 7] = 1
trace[0, 0, 3, 0, 0] = 1
trace[0, 0, 3, 0, 2] = 1
trace[0, 0, 3, 0, 3] = 1
trace[1, 0, 1, 0, 0] = 1
trace[1, 0, 1, 0, 3] = 1
trace[1, 0, 3, 0, 3] = 1

node_bound = {DIM_KH: 1, DIM_KW: 1, DIM_CIN: 4, DIM_HO: 1, DIM_WO: 8}

tile_t0 = NodeTileSpec(
    dram_i=0, node_bound=node_bound,
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0}, is_last_K=True,
)
r0 = reconstruct_tile_sequence(trace, tile_t0)
assert len(r0.submatrices) == 1, r0.submatrices          # HO=1 -> 1 submatrix (this one row)
assert [l.cin for l in r0.submatrices[0].lines] == [0, 3]  # cin0, cin3 active at t0

tile_t1 = NodeTileSpec(
    dram_i=0, node_bound=node_bound,
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 1}, is_last_K=True,
)
r1 = reconstruct_tile_sequence(trace, tile_t1)
assert len(r1.submatrices) == 1, r1.submatrices
assert [l.cin for l in r1.submatrices[0].lines] == [1, 3]  # cin1, cin3 active at t1 -- cin0/cin1 flipped
print(f"Part A OK: t=0 active cin={[l.cin for l in r0.submatrices[0].lines]}, "
      f"t=1 active cin={[l.cin for l in r1.submatrices[0].lines]} (cin0/cin1 flip between ticks, "
      f"proving fresh per-tick NRV re-derivation, not T-collapsed)")

# --- Part B: multi-piece chunking (HO=2 -> 2 submatrices, one per row) -----
# Each submatrix = one ho row's full (here 8-wide) WO window. cin0 fires in
# BOTH rows (independently); cin1 fires only in row 1 -- proving each row's
# NRV is computed independently, and the same cin can be active in one
# submatrix but not another.
trace_b = np.zeros((1, 1, 2, 2, 8), dtype=np.uint8)  # [T=1, B=1, Cin=2, Hin=2, Win=8]
trace_b[0, 0, 0, 0, 0] = 1  # cin0, ho=0,wo=0 -> submatrix 0
trace_b[0, 0, 0, 1, 1] = 1  # cin0, ho=1,wo=1 -> submatrix 1
trace_b[0, 0, 1, 1, 7] = 1  # cin1, ho=1,wo=7 -> submatrix 1 only

tile_b = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 2, DIM_HO: 2, DIM_WO: 8},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0},
    is_last_K=True,
)
rb = reconstruct_tile_sequence(trace_b, tile_b)
assert len(rb.submatrices) == 2, rb.submatrices
assert rb.submatrices[0].positions == [(0, wo) for wo in range(0, 8)]
assert rb.submatrices[1].positions == [(1, wo) for wo in range(0, 8)]
assert [l.cin for l in rb.submatrices[0].lines] == [0]        # only cin0 (via ho=0,wo=0)
assert [l.cin for l in rb.submatrices[1].lines] == [0, 1]      # cin0 (ho=1,wo=1) and cin1 (ho=1,wo=7)
print(f"Part B OK: 2 submatrices from HO=2,WO=8 (one per row) -- row0 active cin="
      f"{[l.cin for l in rb.submatrices[0].lines]}, row1 active cin="
      f"{[l.cin for l in rb.submatrices[1].lines]}")

# --- Part C: real LoAS trace, one 8x8 HO/WO block, one tick -----------------
real_trace = np.load("input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy")
assert real_trace.shape == (4, 1, 64, 32, 32), real_trace.shape

real_tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_CIN: 64, DIM_HO: 8, DIM_WO: 8},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0},
    is_last_K=True,
)
r2 = reconstruct_tile_sequence(real_trace, real_tile)
assert len(r2.submatrices) == 8, len(r2.submatrices)  # HO=8 -> 8 submatrices, one per row, each WO=8 wide

total_active = 0
for sm in r2.submatrices:
    expected_lines = []
    for kh in range(3):
        for kw in range(3):
            for cin in range(64):
                active = any(
                    real_trace[0, 0, cin, ho + kh, wo + kw]
                    for ho, wo in sm.positions
                )
                if active:
                    expected_lines.append((kh, kw, cin))
    got_lines = [(l.kh, l.kw, l.cin) for l in sm.lines]
    assert got_lines == expected_lines, (sm.piece_idx, got_lines, expected_lines)
    total_active += len(sm.lines)

print(f"Part C OK: 8 submatrices from an 8x8 HO/WO block at t=0, all independently "
      f"cross-checked against a from-scratch recomputation; total non-zero rows "
      f"across all 8 pieces = {total_active}")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_gustavsnn_reconstruct.py`
Expected:
```
Part A OK: t=0 active cin=[0, 3], t=1 active cin=[1, 3] (cin0/cin1 flip between ticks, proving fresh per-tick NRV re-derivation, not T-collapsed)
Part B OK: 2 submatrices from HO=2,WO=8 (one per row) -- row0 active cin=[0], row1 active cin=[0, 1]
Part C OK: 8 submatrices from an 8x8 HO/WO block at t=0, all independently cross-checked against a from-scratch recomputation; total non-zero rows across all 8 pieces = <N>
```
(`<N>` is whatever the real trace produces — the important assertion is
that `got_lines == expected_lines` for every one of the 8 submatrices,
not a specific hardcoded total.)

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/gustavsnn/`
Stop here for review/comment.

---

## Task 2: GustavSNN archmodel — `event_to_cycle` and `event_to_address`

**Files:**
- Create: `src/snn_cosa/archmodels/gustavsnn/cycles.py`
- Create: `src/snn_cosa/archmodels/gustavsnn/address.py`

**Interfaces:**
- Consumes: `GustavReconstructed`/`GustavSubmatrix` from Task 1's
  `reconstruct.py` (`cycles.py` reads each submatrix's `len(.lines)`;
  `address.py` reads each submatrix's `.lines` directly); `NodeTileSpec`
  from `archmodels/__init__.py`; `snn_cosa.parsers.layer.DIM_COUT`
  (pre-existing).
- Produces: `access_cycle_count(reconstructed) -> int`,
  `compute_cycle_count(reconstructed, tile) -> int`,
  `event_to_cycle(reconstructed, tile) -> int` (= `max` of the two,
  always equal here — no dominance case, see cycles.py),
  `event_to_address(reconstructed, tile) -> List[Tuple[int,int,int,int,int]]`,
  `weight_access_count(reconstructed) -> int`, `PE_COUNT_MAX` (=8) —
  consumed by a future `GustavSNNComputeModel` (out of scope here, per
  Global Constraints). `compute_cycle_count`/`event_to_cycle` accept
  `tile` only for signature parity with PTB/SpinalFlow/LoAS's shared
  convention — COUT (the only thing `tile` could contribute) is
  established to cost zero cycles, so `tile` plays no role in the
  formula.

- [ ] **Step 1: Write `cycles.py`**

```python
"""GustavSNN cycle count: driven by NRV row-sparsity within each HO-row
submatrix, maxed across the (up to PE_COUNT_MAX) PEs running in parallel
this tick -- one tick per node visit (T barred from NodeLevel, see
reconstruct.py's module docstring).

Mirrors PTB's/SpinalFlow's/LoAS's archmodels/<arch>/cycles.py structure:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

though for GustavSNN (like SpinalFlow/LoAS) access_cycle_count and
compute_cycle_count always evaluate to the SAME quantity -- no dominance
case, for a different reason than SpinalFlow/LoAS's flat single-pipeline
equality: here it's because the K' PEs in a tile run in parallel
(Algorithm 1's `parallel-for k`), so a tile's cycle cost this tick is
driven by whichever PE has the most non-zero D-rows to process, and both
the weight-fetch side and the execution side are bottlenecked by that
same slowest PE (see address.py's per-submatrix weight-fetch discussion
-- no cross-PE weight-fetch deduplication is modeled, an explicit
departure from the paper's Section V-A weight-sharing claim).

This deployment departs from the GustavSNN paper (Hwang, Lee, Koo & Kung,
HPCA 2026) in explicit, user-specified ways:

  1. Row-level (not element-level) abstraction: a submatrix's cost is its
     count of non-zero (kh,kw,cin) "lines" (NRV rows, Section IV-D/Fig.
     7), NOT the finer per-nonzero-(d,n)-element cost the paper's actual
     merger-tree PE microarchitecture implies (Fig. 9: the execution
     stage's merger tree emits ONE non-zero column index per cycle, so a
     "non-zero row" with multiple non-zero columns really costs multiple
     cycles in the real hardware). This mirrors LoAS's/PTB's own
     precedent of abstracting away fine-grained pipeline/systolic timing
     for a first pilot.
  2. No cross-PE weight-fetch deduplication (departs from Section V-A's
     shared weight-row-tiled buffer) -- see address.py.
  3. COUT contributes ZERO incremental cycle cost, same treatment as
     SpinalFlow/LoAS -- all 8 tiles (M'=8, one per COUT chunk) share the
     identical per-tick NRV structure (it depends only on the spike data,
     never on which output channel), so COUT never enters this formula at
     all, not even as a "parallel resource" argument.

Within one node visit (one tick), the tile's (up to PE_COUNT_MAX=8)
HO-row submatrices run in parallel PEs. If more than PE_COUNT_MAX rows
are resident in one visit (e.g. the MIP grants HO extra temporal
residency beyond its {spatial: 8} cap, so node_bound[DIM_HO] > 8), they
run in sequential WAVES of up to PE_COUNT_MAX PEs each -- this
generalization is this deployment's own (not paper-derived, mirrors
PTB's capped/residual active_cols handling for an analogous "more work
than fits in one parallel pass" case):

    cycle_count = sum over waves of ( max over that wave's submatrices
                                       of len(submatrix.lines) )

access_cycle_count -- one weight-fetch cycle per non-zero row within the
bottleneck submatrix of each wave (see address.py).
compute_cycle_count -- one accumulate cycle per non-zero row within the
bottleneck submatrix of each wave (same formula/value as access, by
construction -- see point 1 above for why these aren't split further).

This is a single end-to-end cycle count covering both integration (MAC)
and membrane-potential/spike-generation (LIF) work -- interleaved per PE
with no separable component (see archmodels/__init__.py's
ComputeCycles.lif_cycles=None convention, same as PTB/SpinalFlow/LoAS).
"""

from __future__ import annotations

from .. import NodeTileSpec
from .reconstruct import GustavReconstructed

PE_COUNT_MAX = 8  # K': PEs per tile (Table II's 8-PE/tile evaluated config)


def _wave_cycle_count(reconstructed: GustavReconstructed) -> int:
    submatrices = reconstructed.submatrices
    total = 0
    for start in range(0, len(submatrices), PE_COUNT_MAX):
        wave = submatrices[start : start + PE_COUNT_MAX]
        total += max((len(sm.lines) for sm in wave), default=0)
    return total


def access_cycle_count(reconstructed: GustavReconstructed) -> int:
    return _wave_cycle_count(reconstructed)


def compute_cycle_count(reconstructed: GustavReconstructed, tile: NodeTileSpec) -> int:
    return _wave_cycle_count(reconstructed)


def event_to_cycle(reconstructed: GustavReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
```

- [ ] **Step 2: Write `address.py`**

```python
"""GustavSNN weight address per non-zero (submatrix, row) pair.

Each submatrix's own non-zero (kh,kw,cin) rows independently trigger a
weight-line fetch, `[m, kh,kw,cin] -> weight[k=(kh,kw,cin),
cout_start:cout_start+8]` -- one burst per non-zero row PER SUBMATRIX,
covering the tile's whole assigned COUT range (8-wide in this
deployment). Because the (up to PE_COUNT_MAX=8) submatrices in a tile run
in parallel PEs, up to PE_COUNT_MAX distinct weight-line fetches can be
issued in the same cycle-position -- one per PE that still has a non-zero
row to process there.

This is an EXPLICIT departure from the paper's Section V-A, which shares
one local weight buffer across all PEs in a tile (a weight row fetched
ONCE, reused by every PE whose submatrix also needs that same (kh,kw,cin)
this tick) -- this deployment does not model that sharing/deduplication:
each submatrix's fetches are counted independently, even when two
submatrices happen to need the identical (kh,kw,cin) weight row in the
same tick. weight_access_count is therefore the sum of every submatrix's
own non-zero-row count, not the count of distinct (kh,kw,cin) values
across the tile.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import GustavReconstructed


def event_to_address(
    reconstructed: GustavReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for sm in reconstructed.submatrices
        for line in sm.lines
    ]


def weight_access_count(reconstructed: GustavReconstructed) -> int:
    return sum(len(sm.lines) for sm in reconstructed.submatrices)
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_gustavsnn_cycles_address.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.gustavsnn.address import event_to_address, weight_access_count
from snn_cosa.archmodels.gustavsnn.cycles import (
    PE_COUNT_MAX,
    access_cycle_count,
    compute_cycle_count,
    event_to_cycle,
)
from snn_cosa.archmodels.gustavsnn.reconstruct import GustavLine, GustavReconstructed, GustavSubmatrix
from snn_cosa.parsers.layer import DIM_COUT

# --- Part A: single wave (3 submatrices, line counts 2/3/1) -----------------
sm0 = GustavSubmatrix(0, [(0, 0), (0, 1)], [GustavLine(0, 0, 0), GustavLine(0, 0, 1)])
sm1 = GustavSubmatrix(1, [(0, 2), (0, 3)], [GustavLine(0, 0, 0), GustavLine(0, 0, 2), GustavLine(0, 0, 5)])
sm2 = GustavSubmatrix(2, [(0, 4), (0, 5)], [GustavLine(0, 0, 3)])
r = GustavReconstructed(submatrices=[sm0, sm1, sm2])
tile = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 8}, tile_offset={DIM_COUT: 0}, is_last_K=True)

a = access_cycle_count(r)
c = compute_cycle_count(r, tile)
assert a == 3 and c == 3, (a, c)             # bottleneck submatrix (sm1) has 3 lines
assert event_to_cycle(r, tile) == 3
addrs = event_to_address(r, tile)
assert len(addrs) == 2 + 3 + 1 == 6           # NOT deduped -- every line from every submatrix
assert weight_access_count(r) == 6
print(f"Part A OK: access={a}, compute={c}, total={event_to_cycle(r, tile)} "
      f"(== max(2,3,1)=3, the bottleneck submatrix), weight_access_count={weight_access_count(r)} "
      f"(== 2+3+1=6, no dedup)")

# --- Part B: multi-wave (10 submatrices -> wave0=[0:8], wave1=[8:10]) ------
many = [GustavSubmatrix(i, [], [GustavLine(0, 0, j) for j in range(n)])
        for i, n in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])]
r_many = GustavReconstructed(submatrices=many)
assert len(many) == 10 > PE_COUNT_MAX
a_many = access_cycle_count(r_many)
# wave0 = pieces with line counts [1,2,3,4,5,6,7,8] -> max=8
# wave1 = pieces with line counts [9,10]            -> max=10
assert a_many == 8 + 10 == 18, a_many
print(f"Part B OK: 10 submatrices (line counts 1..10) split into 2 waves of "
      f"<= {PE_COUNT_MAX} PEs -- access_cycle_count={a_many} (== max(1..8)=8 + max(9,10)=10 = 18)")

# --- Part C: COUT-invariance -- same submatrices, much wider COUT block ----
tile_wide = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 64}, tile_offset={DIM_COUT: 0}, is_last_K=True)
a_wide = access_cycle_count(r)
c_wide = compute_cycle_count(r, tile_wide)
assert a_wide == a == 3 and c_wide == c == 3   # unchanged -- COUT never enters the formula
addrs_wide = event_to_address(r, tile_wide)
assert all(addr[4] - addr[3] == 64 for addr in addrs_wide)  # only the address range widens
print(f"Part C OK: COUT=64 gives the same cycle count ({c_wide}) as COUT=8 -- "
      f"only the address range widens (every burst now spans 64 cout entries)")

# --- Part D: fully-silent tile edge case -- every submatrix has 0 lines ----
r_empty = GustavReconstructed(submatrices=[GustavSubmatrix(i, [], []) for i in range(4)])
tile_empty = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 8}, tile_offset={DIM_COUT: 0}, is_last_K=True)
assert access_cycle_count(r_empty) == 0
assert compute_cycle_count(r_empty, tile_empty) == 0
assert event_to_cycle(r_empty, tile_empty) == 0
assert event_to_address(r_empty, tile_empty) == []
assert weight_access_count(r_empty) == 0
print("Part D OK: fully-silent tile -> 0 cycles, 0 weight accesses")

# --- Part E: real-trace-scale sanity check (8 submatrices, mirroring Task 1's
# 8x8 HO/WO block) --------------------------------------------------------
real_line_counts = [7, 12, 3, 20, 15, 1, 9, 6]  # stand-in for a real 8-piece tick's counts
real_subs = [
    GustavSubmatrix(i, [], [GustavLine(0, 0, k) for k in range(n)])
    for i, n in enumerate(real_line_counts)
]
r_real = GustavReconstructed(submatrices=real_subs)
tile_real = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 8}, tile_offset={DIM_COUT: 0}, is_last_K=True)
a_real = access_cycle_count(r_real)
assert a_real == max(real_line_counts) == 20
assert weight_access_count(r_real) == sum(real_line_counts) == 73
print(f"Part E OK (real-trace scale): access=compute={a_real} (== max{real_line_counts}), "
      f"weight_access_count={weight_access_count(r_real)} (== sum{real_line_counts})")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_gustavsnn_cycles_address.py`
Expected:
```
Part A OK: access=3, compute=3, total=3 (== max(2,3,1)=3, the bottleneck submatrix), weight_access_count=6 (== 2+3+1=6, no dedup)
Part B OK: 10 submatrices (line counts 1..10) split into 2 waves of <= 8 PEs -- access_cycle_count=18 (== max(1..8)=8 + max(9,10)=10 = 18)
Part C OK: COUT=64 gives the same cycle count (3) as COUT=8 -- only the address range widens (every burst now spans 64 cout entries)
Part D OK: fully-silent tile -> 0 cycles, 0 weight accesses
Part E OK (real-trace scale): access=compute=20 (== max[7, 12, 3, 20, 15, 1, 9, 6]), weight_access_count=73 (== sum[7, 12, 3, 20, 15, 1, 9, 6])
```

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/gustavsnn/`
Stop here for review/comment.

---

## Task 3: GustavSNN arch YAML + real MIP-solved single-node schedule

Per [[feedback_archmodel_deliverable_scope]]: Tasks 1-2 only exercise the
Python plugin against hand-built/real-trace fixtures. This task builds
the actual hardware-capacity *input interface* the MIP solver consumes —
`configs/arch/gustavsnn.yaml` — and runs a real `snn_cosa solve` against
it to produce a genuine GustavSNN single-node schedule, proving the
config is solver-feasible and encodes the right node-level residency
(including this pilot's first-ever HO/WO NodeLevel spatial residency).

**Files:**
- Create: `configs/arch/gustavsnn.yaml`
- Create: `outputs/gustavsnn_single_node_schedule.json` (solver output,
  gitignored)

**Interfaces:**
- Consumes: `snn_cosa.parsers.arch.SNNArch` (`node_dim_capacity`,
  `single_node`, `{spatial: N}` form — all pre-existing, no changes
  needed to the solver for this task).
- Produces: a schedule JSON consumable by `snn_cosa.nocsim.sim` (same
  contract as `outputs/single_node_schedule.json` /
  `outputs/ptb_single_node_schedule.json` / `outputs/loas_single_node_schedule.json`).

- [ ] **Step 1: Write `configs/arch/gustavsnn.yaml`**

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM:   16
    BW_VMEM:   32
    DRAM_LATENCY: 17

  # single_node: GustavSNN's PE array (Fig. 11) is fed directly from its
  # Weight/Spike global buffers -- no inter-node NoC, so no physical
  # Global Buffer level at this scope (mirrors spinalflow.yaml/ptb.yaml/
  # loas.yaml's reasoning).
  #
  # node_dim_capacity: this deployment's node-level dimension set.
  #
  # KH/KW/CIN forced fully resident (null, not capped like SpinalFlow/
  # PTB's KH/KW=4): this deployment requires the ENTIRE reduction row
  # (every k=(kh,kw,cin)) visible at once, per submatrix, to build that
  # submatrix's NRV row-skip result (Fig. 7) -- there is no partial-row
  # compression.
  #
  # T absent -- BARRED from NodeLevel entirely, the opposite of LoAS's
  # T:null. GustavSNN's column-major time-second scheduling (Section V-B,
  # Fig. 12) processes ticks strictly sequentially, re-deriving NRV
  # silence fresh at every tick -- one node visit covers exactly one
  # tick, and the MIP loops T at the DRAM permutation level, the same
  # mechanism SpinalFlow/PTB/LoAS use for their barred HO/WO.
  #
  # COUT uses {spatial: 8} -- one tile per output channel, matching the
  # paper's own evaluated config (Table II/Fig. 17: 8 tiles), validated
  # against pe.num_pes (V1).
  #
  # HO uses {spatial: 8} -- 8 resident HO rows, 8 genuinely parallel PEs
  # per tile (Table II's "8 PEs/tile"), one row = one submatrix = one PE
  # (the paper's K column-partition submatrices). WO uses a plain int cap
  # of 8 (NOT spatial) -- each row's resident WO width, the paper's P.
  # This split is asymmetric ON PURPOSE: marking BOTH HO and WO
  # {spatial: 8} would make this project's own V1 check require
  # COUT(8) x HO(8) x WO(8) = 512 <= num_pes, when the paper's real
  # hardware has only 64 PEs total (8 tiles x 8 PEs/tile, Fig. 17) --
  # V1 sums the product of every {spatial: N}-tagged dimension across the
  # WHOLE arch, not per-dimension independently (see
  # src/snn_cosa/parsers/arch.py's _validate_spatial_split). Only HO is
  # spatial-tagged here, so num_pes = COUT(8) x HO(8) = 64 checks out
  # exactly, and WO's cap is excluded from that product entirely. This is
  # the FIRST architecture in this project's 6-arch plan where HO/WO
  # carry any NodeLevel residency at all (SpinalFlow/PTB/LoAS bar both).
  # The exact 8/8 values are hardcoded to match
  # configs/workloads/generated/vgg16/T4/conv2_1.yaml's real HO=WO=112
  # shape (HO divides 8 exactly; WO's max achievable factor product <=8
  # is also 8) -- there is no general joint-dimension solver mechanism
  # yet for an arbitrary workload's HO/WO shape (see
  # docs/superpowers/plans/2026-07-15-archmodel-gustavsnn-pilot.md's
  # Global Constraints); a workload with a different HO/WO shape would
  # need a different split or a future generalization.
  single_node: true
  node_dim_capacity:
    KH:   null
    KW:   null
    CIN:  null
    COUT: {spatial: 8}
    HO:   {spatial: 8}
    WO:   8

  storage:             # innermost first
    - name: NodeLevel
      instances: 1
      pe:
        num_pes: 64     # 8 tiles (COUT) x 8 PEs/tile (HO-row submatrices), Table II / Fig. 17's "64 PE"
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
already used to verify LoAS's config (see `2026-07-14-archmodel-loas-
pilot.md`'s Task 3). Reused deliberately for continuity, and because it
happens to exercise every interesting path here at once:
- `COUT=128` divides the `{spatial: 8}` cap exactly (V2) and `128 > 8`
  forces additional COUT residency beyond the spatial fanout — same
  "spatial cap plus leftover" pattern PTB's Task 6 sweep and LoAS's Task
  3 already found for COUT.
- `HO=112` divides the `{spatial: 8}` cap exactly (V2) — the first real
  test of this pilot's HO spatial split actually being solver-feasible.
- `WO=112 = 2^4 x 7`: the max achievable product of its prime factors
  that doesn't exceed the cap of 8 is exactly 8 (three of its four 2's),
  so the plain-int-cap path (`model/constraints/node_capacity.py`) pins
  `WO`'s NodeLevel-resident factor to exactly 8, deterministically (no
  V2 divisibility requirement applies to a capped, non-spatial dim).
- `KH=3, KW=3, CIN=64` are all forced fully resident (`null`), so they
  always fit regardless of size.
- `T=4` is entirely barred from NodeLevel, so all 4 factors must appear
  at the DRAM permutation level — the first real test of T being routed
  to DRAM instead of HO/WO.

- [ ] **Step 3: Run the solver**

```bash
export PYTHONPATH=src
python3 -m snn_cosa solve \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/gustavsnn.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/gustavsnn_single_node_schedule.json
```
Expected: `status: OPTIMAL`, `objective: <float>`,
`output: outputs/gustavsnn_single_node_schedule.json`.

Then inspect the strategy:
```bash
python3 -c "
import json
d = json.load(open('outputs/gustavsnn_single_node_schedule.json'))
print(json.dumps(d['strategy'], indent=2))
"
```
Expected, and confirm by reading the actual printed JSON (don't assume —
report what the solver actually picked where this plan notes freedom):
- `NodeLevel.temporal_tile.factors` contains `KH=3, KW=3, CIN=64` (all
  fully resident, matching their `null` caps) and `WO=8` (deterministically
  pinned by the plain int cap — no MIP freedom in this value, per
  `node_capacity.py`'s docstring); no `T` entry at all (T is entirely
  barred from NodeLevel).
- `NodeLevel.spatial_split.factors` contains exactly `COUT=8, HO=8`.
- Whatever `NodeLevel.temporal_tile.factors` shows for COUT/HO beyond
  their pinned spatial value (e.g. an additional temporal `COUT` factor
  of `16` = `128/8`, and/or an additional temporal `HO` factor from its
  `112/8=14` leftover) is the MIP's free choice (same "spatial cap plus
  optional extra temporal residency" freedom COUT already showed in the
  LoAS/PTB runs) — record exactly what's there, don't assume it matches
  any particular value.
- `NoCLevel` both permutation/split are empty (`single_node` bars it).
- `DRAM.temporal_permutation.loops` contains `T` (barred from NodeLevel
  entirely) with factor `4`, the deterministic WO leftover factor of `14`
  (`112/8`, forced to DRAM by the capped-dim constraint — see
  `node_capacity.py`'s docstring on capped dims having no placement
  freedom for their leftover), plus whatever COUT/HO leftover the MIP
  didn't place at NodeLevel.

- [ ] **Step 4: Run the solved schedule through the NoC simulator**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/gustavsnn_single_node_schedule.json \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/gustavsnn.yaml \
  --out /tmp/gustavsnn_tc.csv --simulate
```
Expected: exits 0 and prints `transactions`, `dram_cost`, `total_cycles`,
etc. (Cycle numbers here come from the default `DenseStaticComputeModel`,
NOT `archmodels/gustavsnn/cycles.py` — wiring GustavSNN's real per-tile
model into this live loop is still out of scope, per the Global
Constraints. This step only proves the config produces a schedule the
simulator can run, not that the printed cycle count reflects GustavSNN's
real hardware behavior.)

- [ ] **Step 5: Present for review**

Run: `git status --short configs/arch/gustavsnn.yaml` (expect untracked
— gitignored like `spinalflow.yaml`/`ptb.yaml`/`loas.yaml`; the repo's
`.gitignore` blanket-ignores `*.yaml`/`*.json` and only 3 config files
are actually committed: `configs/arch/snn_arch.yaml`,
`configs/mapspace/mapspace.yaml`, `configs/workloads/sample_snn_layer.yaml`).
If the user wants `gustavsnn.yaml` committed, it needs `git add -f`.
Stop here — this completes the plan. A full `GustavSNNComputeModel`
implementing `ArchComputeModel` end-to-end (wired into `combine()`'s live
per-tile loop, consuming this real solved schedule's tile boundaries) is
a later plan, deferred per the Global Constraints section above. A
general joint HO/WO spatial-cap solver mechanism (for workloads whose
HO/WO don't divide evenly by 8) is likewise deferred.

---

## Self-review notes

- **Spec coverage:** the paper<->project symbol mapping (M/COUT, D/K,
  N/HO*WO with P mapped to WO and K-submatrices mapped to HO) — covered
  in the Spec table and validated against a real workload in Task 3,
  including the V1-driven reasoning for why the split is asymmetric
  (HO spatial, WO capped) rather than both spatial. Per-tick NRV
  re-derivation (T barred from NodeLevel, one node visit = one tick) —
  covered in `reconstruct.py`'s module docstring and Task 1's Part A (the
  cin0/cin1 flip-between-ticks test), and in
  `configs/arch/gustavsnn.yaml`'s T-absent entry. HO/WO NodeLevel
  residency (novel vs. the other 3 archs) — covered in `reconstruct.py`'s
  one-submatrix-per-HO-row logic (Task 1's Part B multi-row test) and
  `configs/arch/gustavsnn.yaml` + Task 3's real solve. NRV row-skip per
  submatrix (Fig. 7) — covered in Task 1's `GustavSubmatrix.lines` and
  Part C's from-scratch cross-check against the real trace.
  `access_cycle_count == compute_cycle_count` (max-across-PEs,
  wave-generalized) — covered in Task 2's Parts A/B (single-wave and
  multi-wave cases) and documented as this deployment's own
  generalization (not paper-derived) in `cycles.py`. No cross-PE
  weight-fetch dedup (departs from Section V-A) — covered in `address.py`
  and Task 2's Part A (`weight_access_count == 6`, the un-deduped sum,
  not the distinct-address count). COUT-invariance — covered in Task 2's
  Part C. Hardware-capacity input interface (`configs/arch/gustavsnn.yaml`)
  and a real MIP-solved single-node schedule — covered in Task 3, using a
  workload whose COUT/HO both exceed their spatial caps (exercising the
  "leftover factor" MIP-freedom path) and whose WO/T exercise the two
  deterministic paths (capped-dim leftover forced to DRAM; T barred
  entirely) for the first time in this project.
- **No placeholders:** every step has complete, runnable code and an
  exact verification command with expected output (Task 3's solver-output
  inspection intentionally asks the executor to report the MIP's actual
  free-variable choices rather than asserting a specific number that
  can't be predicted without actually running Gurobi — consistent with
  how LoAS's/PTB's own COUT-leftover behavior was only confirmed after
  their real solves ran, not predicted in advance).
- **Type consistency:** `GustavLine`/`GustavSubmatrix`/`GustavReconstructed`
  (Task 1) are consumed by `cycles.py` (reads only `len(sm.lines)` per
  submatrix) and `address.py` (reads only `sm.lines` per submatrix) in
  Task 2 — no field is read that Task 1 doesn't produce.
  `PE_COUNT_MAX` is defined once, in `cycles.py`, and not duplicated;
  `reconstruct.py` derives each submatrix's width directly from
  `tile.node_bound[DIM_WO]` rather than a hardcoded constant, so it stays
  correct even where the YAML's nominal 8 doesn't apply. `NodeTileSpec`,
  `ComputeCycles` match `archmodels/__init__.py`'s existing definitions
  (unchanged by this plan).
