# Arch-specific cycle count — LoAS pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this run:** per the SpinalFlow/PTB pilots' established
> convention, treat every task as its own checkpoint — present the diff for
> review at the end of each task rather than auto-committing (commit only
> when the user explicitly asks, per repo convention).

## Spec (rephrased)

This targets LoAS (Low-latency inference Accelerator for dual-Sparse SNNs)
from Yin, Kim, Wu & Panda, *"LoAS: Fully Temporal-Parallel Dataflow for
Dual-Sparse Spiking Neural Networks"* (MICRO 2024), as the fourth of the
6-architecture cycle-count plan (SpinalFlow was the pilot, PTB the third;
see `docs/superpowers/plans/2026-07-12-archmodel-spinalflow-pilot.md` and
`docs/superpowers/plans/2026-07-14-archmodel-ptb-pilot.md`).

This deployment departs from the paper in explicit, user-specified ways:

- **T** (timesteps) is entirely resident at the node in one visit — no
  temporal tiling of T, matching LoAS's fully-temporal-parallel (FTP)
  dataflow, where Algorithm 1's `parallel-for t in T` spatially unrolls
  every timestep across P-LIF units and per-timestep correction
  accumulators (Sections III-IV) rather than looping over them.
- **N = COUT** is fixed at 16 for this deployment, matching the paper's
  own evaluated config of 16 TPPEs (Section V, Table III/IV) — one TPPE
  per output channel, all COUT channels computed/fetched in parallel.
  Like T, COUT is therefore a spatially-parallel hardware resource that
  contributes ZERO incremental cycle cost (see Cycle formulas below), not
  a multiplier.
- **K = KH·KW·CIN** must be *entirely* resident at the node at once — not
  capped the way SpinalFlow/PTB cap KH/KW at 4. A full reduction row (one
  output pixel, every k) must be visible together to build one complete
  fiber/bitmask, matching the paper's row-wise compression unit (Fig. 8).
- **Weight matrix B is stored dense** — no column-wise bitmask compression
  on B (the paper's Section IV-A applies bitmask compression to both A and
  B; here only A gets it). Every non-silent input line's data is matched
  against the tile's full assigned COUT-wide weight range, one burst per
  non-silent line (see Cycle formulas' weight-address example below).
- **Input compression** follows the paper's Fig. 8 scheme exactly, as a
  two-part format: (1) a ROW-LEVEL bitmask, one bit per candidate k =
  (kh,kw,cin) position (length KH·KW·CIN), marking which k's are
  non-silent, plus a pointer to the start of the packed non-zero data;
  (2) for each non-silent k only, its own packed length-T spike
  bit-vector recording when it fires (e.g. "1001" for a 4-timestep
  neuron: fires at t0 and t3, silent at t1/t2) — silent k's contribute
  nothing to this packed data at all. There is **no** second merge pass
  — unlike PTB's stSAP, LoAS's own compression is single-pass.
- **Cycle formulas** (this deployment's specification, not derived from
  the paper's own cycle model in Section IV-B/C). Since TPPEs are
  one-per-output-channel and run in parallel (COUT above), and T is also
  fully hardware-parallel, neither contributes to cycle count — the ONLY
  driver is how many candidate k = (kh,kw,cin) positions in this row are
  non-silent, i.e. the row-level bitmask's popcount:
  - `access_cycle_count = compute_cycle_count = sum(row bitmask)` — one
    cycle per non-silent k (e.g. a row bitmask of `10000000101101` has 5
    set bits, so that row's cycle count is 5, independent of COUT). No
    dominance case — access and compute always evaluate to the same
    quantity here, mirroring SpinalFlow's own cycles.py.
  - `event_to_cycle = max(access_cycle_count, compute_cycle_count)`,
    mirroring the `max(...)` structure already established for
    SpinalFlow and PTB (trivially equal to that same quantity here).
  - **Weight address**, per non-silent k = (kh,kw,cin): the input's own
    address drives which weight row gets fetched — e.g. for a row with
    non-silent k's at positions 0 and K, `[m, 0] -> weight[k=0,
    cout_start : cout_start+16]` and `[m, K] -> weight[k=K, cout_start :
    cout_start+16]`, one burst per non-silent k covering the tile's whole
    assigned COUT range (16-wide in this deployment) as "one line" of
    weight data. `weight_access_count = access_cycle_count` (the same
    quantity, by construction).

**Goal:** Build LoAS's `reconstruct_tile_sequence` / `event_to_cycle` /
`event_to_address` trio (matching the SpinalFlow/PTB pilots' architecture-
owned 3-stage pattern), plus `configs/arch/loas.yaml` and a real
MIP-solved single-node schedule proving the config is solver-feasible
(per [[feedback_archmodel_deliverable_scope]] — the YAML + solve step is
part of "build the archmodel," not an optional follow-up).

**Architecture:** `src/snn_cosa/archmodels/loas/{__init__.py,
reconstruct.py, cycles.py, address.py}`, standalone and unwired (same
scope as the SpinalFlow/PTB pilots — live wiring into `combine()`'s
per-tile loop is a separate, later design pass for every architecture in
this plan). `reconstruct.py` performs the single-pass silent-neuron
compression and returns the paper's own two-part fiber format — a
row-level bitmask + pointer over the full K candidate set, plus the
packed non-silent lines themselves; no second (merge) pass exists for
LoAS (unlike PTB).

**Tech Stack:** Python 3, numpy, existing `snn_cosa` stack. No pytest in
this repo — verification runs a script and checks exact printed output,
per existing convention.

## Global Constraints

- Zero regression: this plan touches no shared code (`archmodels/__init__.py`'s
  `ComputeCycles.lif_cycles: Optional[int] = None` convention and
  `combine.py`'s handling of it already exist from the PTB pilot — LoAS
  reuses them as-is, no further changes needed there).
- No new third-party dependencies.
- `reconstruct_tile_sequence`, `event_to_cycle`, `event_to_address` are
  LoAS-owned, not shared with SpinalFlow, PTB, or any other architecture —
  do not refactor those to share code with LoAS's.
- Out of scope for this plan (needs its own design pass): wiring a full
  `LoASComputeModel` implementing the `ArchComputeModel` Protocol into
  `combine()`'s live per-tile loop. This plan only proves the LoAS plugin
  correct standalone, against hand-specified tiles, a real captured trace,
  and a real MIP-solved schedule.
- COUT does not appear in the compute/access cycle formulas at all (see
  Cycle formulas above) — it's a fully-parallel hardware resource
  (16 TPPEs, one per output channel), not a multiplier or additive
  latency term. The [[feedback_symmetric_hw_dims]] lesson about matching
  named constants/clamps for two parallel hardware axes doesn't apply
  here: there is only one true driver of cycle count (the row bitmask's
  popcount), not two axes needing symmetric treatment.

---

## Task 1: LoAS input interface — `reconstruct_tile_sequence` with silent-neuron compression

**Files:**
- Create: `src/snn_cosa/archmodels/loas/__init__.py`
- Create: `src/snn_cosa/archmodels/loas/reconstruct.py`

**Interfaces:**
- Consumes: `NodeTileSpec` from `src/snn_cosa/archmodels/__init__.py`;
  `snn_cosa.parsers.layer.{DIM_KH, DIM_KW, DIM_CIN, DIM_HO, DIM_WO, DIM_T}`
  (pre-existing).
- Produces: `LoASLine`, `LoASReconstructed` (with `bitmask: Tuple[int,...]`,
  `ptr: int`, `lines: List[LoASLine]`),
  `reconstruct_tile_sequence(trace, tile) -> LoASReconstructed` — consumed
  by Task 2's `cycles.py` (reads `.bitmask`, for the cycle-count formulas)
  and `address.py` (reads `.lines`, for the weight-address stream); `.ptr`
  is structural fidelity to the paper's Fig. 8 fiber format, not consumed
  by either.

- [ ] **Step 1: Write `loas/__init__.py`**

```python
"""LoAS (Low-latency inference Accelerator for dual-Sparse SNNs)
ArchComputeModel plugin -- pilot.

Reconstructs LoAS's per-row silent-neuron-compressed input line sequence
from a real trace (reconstruct.py), then derives the pipeline cycle count
(cycles.py) and the ordered weight-address stream / weight_access_count
(address.py) from it. Standalone-verified against a real captured LoAS
trace (input_trace/loas/) and against hand-built examples reproducing the
paper's own Fig. 8 compression walkthrough.

This deployment fixes: COUT node-level spatial capacity 16, matching the
paper's own 16-TPPE evaluated config, full
NodeLevel residency for KH/KW/CIN/T (see configs/arch/loas.yaml), and
DENSE weight storage (no column-wise bitmask compression on B) -- all
explicit departures from Yin, Kim, Wu & Panda, "LoAS: Fully
Temporal-Parallel Dataflow for Dual-Sparse Spiking Neural Networks"
(MICRO 2024), Sections III-IV.
"""
```

- [ ] **Step 2: Write `reconstruct.py`**

```python
"""Builds LoAS's per-row compressed fiber (bitmask + pointer + packed
non-silent data) from a real spike trace.

LoAS compresses one output pixel's full reduction row (fixed m; k = every
(kh, kw, cin) reduction index, in [KH, KW, CIN] nested order) in the
paper's own two-part Fig. 8 format (Yin et al., MICRO 2024, Section IV-A):

  1. A ROW-LEVEL BITMASK, one bit per candidate k position (length
     KH*KW*CIN): 1 marks a "non-silent neuron" (fires at least once
     across the whole T range), 0 marks a "silent" one. Followed by a
     POINTER to the start of the packed non-zero data.
  2. The PACKED NON-ZERO DATA: for each non-silent k only, its own
     length-T spike bit-vector (e.g. "1001" for a 4-timestep neuron that
     spikes at t0 and t3, silent at t1/t2) -- silent k's are dropped
     entirely, contributing nothing here ("no silent neuron inside").

There is no further compression pass (unlike PTB's stSAP, which
additionally merges adjacent non-overlapping lines; LoAS has no such
merge step in this deployment).

ptr is always 0 in this standalone reconstruction: each call processes
exactly one row/fiber in isolation (one NodeTileSpec tile = one output
pixel's row), so its own pointer trivially points to the start of its own
packed segment. ptr would only become a meaningful non-zero offset once
multiple rows' compressed data share a single memory arena -- out of
scope for this per-tile pilot (see Global Constraints).

This deployment requires KH, KW, and CIN to be entirely resident at
NodeLevel (configs/arch/loas.yaml's `KH: null`/`KW: null`/`CIN: null`) --
the full reduction row must be visible at once to build one complete
fiber, matching the paper's row-wise compression unit.

Assumes batch=0 and stride=1/no-padding convolution (hin = ho + kh,
win = wo + kw), matching
src/snn_cosa/archmodels/{spinalflow,ptb}/reconstruct.py.

cin_off/t_off (tile.tile_offset.get(DIM_CIN/DIM_T, 0)) are NOT about
supporting a nonzero offset in this deployment -- configs/arch/loas.yaml
forces CIN and T fully resident (null), so a real solved schedule never
splits either dimension across multiple node visits, and their entries
are simply ABSENT from tile_offset (there's only ever one visit, so no
offset needs tracking). `.get(dim, 0)` exists to avoid a KeyError on that
absence, not to handle a real nonzero value -- same convention as
SpinalFlow's reconstruct.py, which has the identical CIN/T:null setup.
Contrast with tile_offset[DIM_HO]/[DIM_WO] just below, accessed with
plain `[...]`: HO/WO are barred from NodeLevel entirely (always vary
across node visits), so their tile_offset entry is mandatory and a
missing key there is a genuine bug worth crashing on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class LoASLine:
    """One non-silent (kh, kw, cin) reduction index's packed spike data.

    bits[i] is 1 if this neuron fired at the i-th timestep of this tile's
    T range (absolute timestep tile_offset[DIM_T] + i), else 0 -- e.g.
    bits=(1,0,1,0) is the paper's "1010" packed value. Only non-silent
    lines (any(bits) is True) are ever constructed; LoASReconstructed's
    row-level bitmask records exactly which (kh, kw, cin) positions these
    correspond to.
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class LoASReconstructed:
    """This row's compressed fiber: row-level bitmask + pointer, plus the
    non-silent lines' packed data -- the paper's two-part Fig. 8 format
    (see module docstring).
    """

    bitmask: Tuple[int, ...]  # length KH*KW*CIN, [KH,KW,CIN] order; 1 = non-silent, 0 = silent
    ptr: int                  # start offset of the packed non-zero data; always 0 here (see module docstring)
    lines: List[LoASLine]     # non-silent lines only, same relative order as bitmask's set bits


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> LoASReconstructed:
    """Return this tile's (one row's) compressed fiber: bitmask + ptr + lines.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel (this row), node_bound
               [DIM_KH]/[DIM_KW]/[DIM_CIN] the full reduction row (must
               be entirely resident -- see module docstring), node_bound
               [DIM_T]/tile_offset[DIM_T] (default 0) the timestep range.
    """
    batch = 0
    ho = tile.tile_offset[DIM_HO]
    wo = tile.tile_offset[DIM_WO]
    kh_n = tile.node_bound[DIM_KH]
    kw_n = tile.node_bound[DIM_KW]
    cin_n = tile.node_bound[DIM_CIN]
    cin_off = tile.tile_offset.get(DIM_CIN, 0)
    t_n = tile.node_bound[DIM_T]
    t_off = tile.tile_offset.get(DIM_T, 0)

    bitmask: List[int] = []
    lines: List[LoASLine] = []
    for kh in range(kh_n):
        for kw in range(kw_n):
            hin = ho + kh
            win = wo + kw
            for cin in range(cin_off, cin_off + cin_n):
                bits = tuple(
                    int(trace[t, batch, cin, hin, win])
                    for t in range(t_off, t_off + t_n)
                )
                non_silent = any(bits)
                bitmask.append(1 if non_silent else 0)
                if non_silent:
                    lines.append(LoASLine(kh, kw, cin, bits))

    return LoASReconstructed(bitmask=tuple(bitmask), ptr=0, lines=lines)
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_loas_reconstruct.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.loas.reconstruct import reconstruct_tile_sequence
from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

# --- Part A: hand-built example matching the paper's own Fig. 8 walkthrough ---
# k=0 (a0,0) fires at t0,t2 -> bits (1,0,1,0). k=3 (a0,3) fires at t1,t2,t3
# -> bits (0,1,1,1). k=1, k=2 stay all-zero (silent), dropped entirely.
trace = np.zeros((4, 1, 4, 1, 1), dtype=np.uint8)  # [T=4, B=1, Cin=4, Hin=1, Win=1]
trace[0, 0, 0, 0, 0] = 1
trace[2, 0, 0, 0, 0] = 1
trace[1, 0, 3, 0, 0] = 1
trace[2, 0, 3, 0, 0] = 1
trace[3, 0, 3, 0, 0] = 1

tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 4, DIM_T: 4},
    tile_offset={DIM_HO: 0, DIM_WO: 0},
    is_last_K=True,
)
r = reconstruct_tile_sequence(trace, tile)

assert r.bitmask == (1, 0, 0, 1), r.bitmask              # matches the paper's own "1001" row bitmask
assert r.ptr == 0
assert len(r.lines) == 2, r.lines                        # k=1,k=2 (silent) dropped
assert [l.cin for l in r.lines] == [0, 3]
assert r.lines[0].bits == (1, 0, 1, 0)                   # matches the paper's "1010" for a0,0
assert r.lines[1].bits == (0, 1, 1, 1)                   # matches the paper's "0111" for a0,3
print(f"Part A OK: bitmask={''.join(str(b) for b in r.bitmask)} (matches the paper's Fig. 8 "
      f"'1001'), ptr={r.ptr}, {len(r.lines)} non-silent lines packed as "
      f"{[''.join(str(b) for b in l.bits) for l in r.lines]}")

# --- Part B: all-silent row edge case (no non-silent lines at all) -----------
trace_silent = np.zeros((4, 1, 3, 1, 1), dtype=np.uint8)
tile_silent = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 3, DIM_T: 4},
    tile_offset={DIM_HO: 0, DIM_WO: 0},
    is_last_K=True,
)
r_silent = reconstruct_tile_sequence(trace_silent, tile_silent)
assert r_silent.bitmask == (0, 0, 0)
assert r_silent.ptr == 0
assert len(r_silent.lines) == 0
print("Part B OK: fully-silent row -> bitmask=000, 0 non-silent lines")

# --- Part C: real LoAS trace, sanity-check line/spatial-sparsity counts -----
real_trace = np.load("input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy")
assert real_trace.shape == (4, 1, 64, 32, 32), real_trace.shape

real_tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_CIN: 64, DIM_T: 4},
    tile_offset={DIM_HO: 0, DIM_WO: 0},
    is_last_K=True,
)
r2 = reconstruct_tile_sequence(real_trace, real_tile)

total_lines = 3 * 3 * 64  # KH * KW * CIN
window = real_trace[0:4, 0, 0:64, 0:3, 0:3]
expected_nonsilent = int((window.sum(axis=0) > 0).sum())  # lines with >=1 spike anywhere in T

assert len(r2.bitmask) == total_lines
assert sum(r2.bitmask) == len(r2.lines) == expected_nonsilent, (sum(r2.bitmask), len(r2.lines), expected_nonsilent)
assert r2.ptr == 0
print(f"Part C OK: bitmask length={len(r2.bitmask)} (KH*KW*CIN), sum(bitmask)={sum(r2.bitmask)} "
      f"== len(lines)={len(r2.lines)} (matches independent non-silent count {expected_nonsilent})")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_loas_reconstruct.py`
Expected:
```
Part A OK: bitmask=1001 (matches the paper's Fig. 8 '1001'), ptr=0, 2 non-silent lines packed as ['1010', '0111']
Part B OK: fully-silent row -> bitmask=000, 0 non-silent lines
Part C OK: bitmask length=576 (KH*KW*CIN), sum(bitmask)=130 == len(lines)=130 (matches independent non-silent count 130)
```

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/loas/`
Stop here for review/comment.

---

## Task 2: LoAS archmodel — `event_to_cycle` and `event_to_address`

**Files:**
- Create: `src/snn_cosa/archmodels/loas/cycles.py`
- Create: `src/snn_cosa/archmodels/loas/address.py`

**Interfaces:**
- Consumes: `LoASReconstructed` from Task 1's `reconstruct.py`
  (`cycles.py` reads only `.bitmask`; `address.py` reads only `.lines`;
  neither needs `.ptr`); `NodeTileSpec` from `archmodels/__init__.py`;
  `snn_cosa.parsers.layer.DIM_COUT` (pre-existing).
- Produces: `access_cycle_count(reconstructed) -> int`,
  `compute_cycle_count(reconstructed, tile) -> int`,
  `event_to_cycle(reconstructed, tile) -> int` (= `max` of the two,
  always equal here — no dominance case, see cycles.py),
  `event_to_address(reconstructed, tile) -> List[Tuple[int,int,int,int,int]]`,
  `weight_access_count(reconstructed) -> int` — consumed by a future
  `LoASComputeModel` (out of scope here, per Global Constraints).
  `compute_cycle_count`/`event_to_cycle` accept `tile` only for signature
  parity with PTB/SpinalFlow's shared convention — COUT (the only thing
  `tile` could contribute) is established to cost zero cycles, so `tile`
  plays no role in the formula.

- [ ] **Step 1: Write `cycles.py`**

```python
"""LoAS cycle count: driven purely by the row-level bitmask's sparsity --
COUT contributes zero incremental cost.

Mirrors PTB's/SpinalFlow's archmodels/<arch>/cycles.py structure:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

though for LoAS (like SpinalFlow) access_cycle_count and
compute_cycle_count always evaluate to the SAME quantity -- there is no
dominance case here, same as SpinalFlow's own cycles.py.

This deployment departs from the LoAS paper (Yin et al., MICRO 2024) in
explicit, user-specified ways:

  1. COUT is spatially parallel hardware in this deployment (16 TPPEs,
     one per output channel, matching the paper's own evaluated config --
     see configs/arch/loas.yaml's COUT: {spatial: 16}). All COUT output
     neurons for a given non-silent input are computed/fetched in the
     SAME cycle, so COUT contributes ZERO incremental cycle cost -- same
     treatment as T (point 2), not a multiplier.
  2. The T dimension is likewise fully hardware-parallel (Algorithm 1's
     `parallel-for t in T`, spatially unrolled across P-LIF units and
     per-timestep correction accumulators -- Sections III-IV) and is
     forced fully resident at NodeLevel (see configs/arch/loas.yaml's
     `T: null`). T also contributes ZERO incremental cycle cost.
  3. Weight matrix B is stored DENSE, not bitmask-compressed (Section
     IV-A's column-wise fiber compression is not modeled here) -- see
     address.py.

With both T and COUT parallelized away, the only thing driving cycle
count is how many candidate k = (kh,kw,cin) positions in this row are
non-silent -- exactly the row-level bitmask's popcount
(reconstruct.py's LoASReconstructed.bitmask). E.g. a row bitmask of
"10000000101101" has 5 set bits, so that row's cycle count is 5,
regardless of COUT:

    access_cycle_count = compute_cycle_count = sum(reconstructed.bitmask)

access_cycle_count -- one weight-fetch cycle per non-silent k: each fetch
streams that k's full assigned COUT-wide weight row in one cycle (see
address.py) -- exactly address.py's weight_access_count.

compute_cycle_count -- one inner-join-matched accumulate cycle per
non-silent k: the TPPE array processes all COUT outputs for that k
simultaneously (one TPPE per output channel), and all T timesteps are
already parallel within each TPPE (point 2 above).

This is a single end-to-end cycle count covering both integration
(pseudo-accumulator AC) and membrane-potential/spike-generation (P-LIF)
work -- both happen per non-silent k with no separable component (see
archmodels/__init__.py's ComputeCycles.lif_cycles=None convention, same
as PTB and SpinalFlow).

This module reads reconstructed.bitmask only -- .lines/.ptr aren't
needed by these formulas. `tile` is accepted by compute_cycle_count/
event_to_cycle purely for signature parity with PTB/SpinalFlow's shared
convention (SpinalFlow's own compute_cycle_count similarly ignores its
tile argument) -- it plays no role in the formula, since COUT (the only
thing tile.node_bound could contribute here) costs zero cycles.
"""

from __future__ import annotations

from .. import NodeTileSpec
from .reconstruct import LoASReconstructed


def access_cycle_count(reconstructed: LoASReconstructed) -> int:
    return sum(reconstructed.bitmask)


def compute_cycle_count(reconstructed: LoASReconstructed, tile: NodeTileSpec) -> int:
    return sum(reconstructed.bitmask)


def event_to_cycle(reconstructed: LoASReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
```

- [ ] **Step 2: Write `address.py`**

```python
"""LoAS weight address per non-silent input neuron.

The weight access pattern is driven by the INPUT's own address: for a
row with non-silent k's at, say, positions 0 and K, `[m, 0]` maps to
`weight[k=0, cout_start : cout_start+16]` and `[m, K]` maps to
`weight[k=K, cout_start : cout_start+16]` -- one weight burst per
non-silent (kh, kw, cin) reduction index, each covering the tile's whole
assigned output-channel range as a single contiguous "line" of weight
data (16-wide in this deployment). Because weight B is dense (no
column-wise bitmask compression, see cycles.py's docstring), this burst
always covers the *entire* assigned COUT range regardless of individual
weight values -- there is no further per-output skip.

Like cycles.py, this module doesn't read reconstructed.bitmask/.ptr --
only .lines (the actual non-silent (kh, kw, cin) positions) matters for
addressing.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import LoASReconstructed


def event_to_address(
    reconstructed: LoASReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for line in reconstructed.lines
    ]


def weight_access_count(reconstructed: LoASReconstructed) -> int:
    return len(reconstructed.lines)
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_loas_cycles_address.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.loas.address import event_to_address, weight_access_count
from snn_cosa.archmodels.loas.cycles import access_cycle_count, compute_cycle_count, event_to_cycle
from snn_cosa.archmodels.loas.reconstruct import LoASLine, LoASReconstructed
from snn_cosa.parsers.layer import DIM_COUT

# --- Part A: the paper's own Fig. 8 example, COUT=5 -------------------------
# 2 non-silent lines (cin=0, cin=3) -> bitmask (1,0,0,1), 2 set bits.
lines = [
    LoASLine(0, 0, 0, (1, 0, 1, 0)),
    LoASLine(0, 0, 3, (0, 1, 1, 1)),
]
r = LoASReconstructed(bitmask=(1, 0, 0, 1), ptr=0, lines=lines)
tile = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 5}, tile_offset={DIM_COUT: 0}, is_last_K=True)

a = access_cycle_count(r)
c = compute_cycle_count(r, tile)
assert a == 2
assert c == 2
assert event_to_cycle(r, tile) == 2
print(f"Part A OK: access={a}, compute={c}, total={event_to_cycle(r, tile)} (== bitmask popcount 2)")

addrs = event_to_address(r, tile)
assert addrs == [(0, 0, 0, 0, 5), (0, 0, 3, 0, 5)]
assert weight_access_count(r) == 2 == a
print(f"Part A' OK: addresses={addrs}, weight_access_count={weight_access_count(r)} (== access_cycle_count)")

# --- Part B: COUT-invariance -- same row, much wider COUT block ------------
tile_wide = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 64}, tile_offset={DIM_COUT: 0}, is_last_K=True)
a_wide = access_cycle_count(r)
c_wide = compute_cycle_count(r, tile_wide)
assert a_wide == a == 2       # unchanged -- COUT never enters the formula
assert c_wide == c == 2
addrs_wide = event_to_address(r, tile_wide)
assert addrs_wide == [(0, 0, 0, 0, 64), (0, 0, 3, 0, 64)]   # only the address range widens
print(f"Part B OK: COUT=64 gives the same cycle count ({c_wide}) as COUT=5 -- only the address "
      f"range widens: {addrs_wide}")

# --- Part C: fully-silent row edge case -- 0 non-silent lines --------------
r_empty = LoASReconstructed(bitmask=(0, 0, 0), ptr=0, lines=[])
tile_empty = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 8}, tile_offset={DIM_COUT: 0}, is_last_K=True)
assert access_cycle_count(r_empty) == 0
assert compute_cycle_count(r_empty, tile_empty) == 0
assert event_to_cycle(r_empty, tile_empty) == 0
assert event_to_address(r_empty, tile_empty) == []
assert weight_access_count(r_empty) == 0
print("Part C OK: fully-silent row -> 0 cycles, 0 weight accesses")

# --- Part D: real-trace-scale sanity check ----------------------------------
lines_real = [LoASLine(0, 0, cin, (1, 0, 0, 0)) for cin in range(130)]  # 130, matching Task 1 Part C
bitmask_real = tuple([1] * 130 + [0] * (576 - 130))  # 576 candidates (KH*KW*CIN), matching Task 1 Part C
r_real = LoASReconstructed(bitmask=bitmask_real, ptr=0, lines=lines_real)
tile_real = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 16}, tile_offset={DIM_COUT: 0}, is_last_K=True)
a_real = access_cycle_count(r_real)
c_real = compute_cycle_count(r_real, tile_real)
assert a_real == 130
assert c_real == 130
assert event_to_cycle(r_real, tile_real) == 130
assert weight_access_count(r_real) == 130
print(f"Part D OK (real-trace scale): access={a_real}, compute={c_real}, "
      f"total={event_to_cycle(r_real, tile_real)}, weight_access_count={weight_access_count(r_real)}")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_loas_cycles_address.py`
Expected:
```
Part A OK: access=2, compute=2, total=2 (== bitmask popcount 2)
Part A' OK: addresses=[(0, 0, 0, 0, 5), (0, 0, 3, 0, 5)], weight_access_count=2 (== access_cycle_count)
Part B OK: COUT=64 gives the same cycle count (2) as COUT=5 -- only the address range widens: [(0, 0, 0, 0, 64), (0, 0, 3, 0, 64)]
Part C OK: fully-silent row -> 0 cycles, 0 weight accesses
Part D OK (real-trace scale): access=130, compute=130, total=130, weight_access_count=130
```

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/loas/`
Stop here for review/comment.

---

## Task 3: LoAS arch YAML + real MIP-solved single-node schedule

Per [[feedback_archmodel_deliverable_scope]]: Tasks 1-2 only exercise the
Python plugin against hand-built/real-trace fixtures. This task builds the
actual hardware-capacity *input interface* the MIP solver consumes --
`configs/arch/loas.yaml` -- and runs a real `snn_cosa solve` against it to
produce a genuine LoAS single-node schedule, proving the config is
solver-feasible and encodes the right node-level residency.

**Files:**
- Create: `configs/arch/loas.yaml`
- Create: `outputs/loas_single_node_schedule.json` (solver output, gitignored)

**Interfaces:**
- Consumes: `snn_cosa.parsers.arch.SNNArch` (`node_dim_capacity`,
  `single_node`, `{spatial: N}` form -- all pre-existing).
- Produces: a schedule JSON consumable by `snn_cosa.nocsim.sim` (same
  contract as `outputs/single_node_schedule.json` / `outputs/ptb_single_node_schedule.json`).

- [ ] **Step 1: Write `configs/arch/loas.yaml`**

```yaml
arch:
  bitwidths:
    BW_WEIGHT: 8
    BW_PSUM:   16
    BW_VMEM:   32
    DRAM_LATENCY: 17

  # single_node: LoAS's TPPE array (Fig. 7) is fed directly from its
  # global cache / bitmask buffers -- no inter-node NoC, so no physical
  # Global Buffer level at this scope (mirrors spinalflow.yaml/ptb.yaml's
  # reasoning).
  #
  # node_dim_capacity: this deployment's node-level dimension set.
  #
  # KH/KW/CIN forced fully resident (null, not capped like SpinalFlow/
  # PTB's KH/KW=4): this deployment requires the ENTIRE reduction row
  # (every k = (kh,kw,cin)) to be visible at once to build one complete
  # silent-neuron-compressed fiber/bitmask (Fig. 8) -- there is no
  # partial-row compression.
  #
  # T forced fully resident (null): LoAS's FTP dataflow spatially unrolls
  # every timestep in hardware (Algorithm 1's parallel-for t), so a node
  # visit always covers the whole T range -- T is never split across
  # multiple node visits in this deployment.
  #
  # COUT uses {spatial: 16} -- one TPPE per output channel, matching the
  # paper's own evaluated config (Section V: 16 TPPEs), validated against
  # pe.num_pes (V1).
  #
  # HO/WO absent for the same reason as SpinalFlow/PTB -- they select
  # which output pixel is computed and never vary within one node-level
  # tile, so they live at the DRAM permutation level (MIP-decided).
  single_node: true
  node_dim_capacity:
    KH:   null
    KW:   null
    CIN:  null
    T:    null
    COUT: {spatial: 16}

  storage:             # innermost first
    - name: NodeLevel
      instances: 1
      pe:
        num_pes: 16     # 16 TPPEs (one per output channel), matching the paper's evaluated config
    - name: NoCLevel
      # entries omitted: no physical Global Buffer exists (single_node:
      # true), so there's nothing real to size -- absent means no capacity
      # check for this level (has_noc_buffer=False).
      instances: 1
    - name: OffChip
      instances: 1
```

- [ ] **Step 2: Pick a workload that actually exercises node capacity**

`configs/workloads/generated/vgg16/T4/conv2_1.yaml`
(`KH=3, KW=3, CIN=64, COUT=128, HO=112, WO=112, T=4`): COUT=128 divides
the 16 spatial cap exactly (V2), and 128 > 16 forces an *additional*
NodeLevel temporal COUT factor of 8 -- so this run exercises the
"COUT beyond the spatial cap becomes a temporal NodeLevel factor" path
(same pattern PTB's Task 6 sweep found), rather than a trivially
fully-resident COUT=16 case. KH/KW/CIN/T are all forced fully resident
(`null`), so they always fit regardless of size -- no divisibility
constraint applies to them.

- [ ] **Step 3: Run the solver**

```bash
export PYTHONPATH=src
python3 -m snn_cosa solve \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/loas.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/loas_single_node_schedule.json
```
Expected: `status: OPTIMAL`, `objective: <float>`,
`output: outputs/loas_single_node_schedule.json`.

Then inspect the strategy:
```bash
python3 -c "
import json
d = json.load(open('outputs/loas_single_node_schedule.json'))
print(json.dumps(d['strategy'], indent=2))
"
```
Expected: `NodeLevel.temporal_tile.factors` contains `KH=3, KW=3, CIN=64,
T=4` (all fully resident, matching their `null` caps) plus a temporal
`COUT` factor of `8` (the `128 / 16` that doesn't fit in the spatial
cap); `NodeLevel.spatial_split.factors` contains exactly `COUT=16`;
`NoCLevel` both permutation/split are empty (`single_node` bars it);
`DRAM.temporal_permutation.loops` contains `HO`, `WO` (barred from
NodeLevel entirely) with no leftover KH/KW/CIN/T factor (all fully
consumed at NodeLevel).

- [ ] **Step 4: Run the solved schedule through the NoC simulator**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/loas_single_node_schedule.json \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/loas.yaml \
  --out /tmp/loas_tc.csv --simulate
```
Expected: exits 0 and prints `transactions`, `dram_cost`, `total_cycles`,
etc. (Cycle numbers here come from the default `DenseStaticComputeModel`,
NOT `archmodels/loas/cycles.py` -- wiring LoAS's real per-tile model into
this live loop is still out of scope, per the Global Constraints. This
step only proves the config produces a schedule the simulator can run,
not that the printed cycle count reflects LoAS's real hardware behavior.)

- [ ] **Step 5: Present for review**

Run: `git status --short configs/arch/loas.yaml` (expect untracked --
gitignored like `spinalflow.yaml`/`ptb.yaml`; the repo's `.gitignore`
blanket-ignores `*.yaml`/`*.json` and only 3 config files are actually
committed: `configs/arch/snn_arch.yaml`, `configs/mapspace/mapspace.yaml`,
`configs/workloads/sample_snn_layer.yaml`). If the user wants
`loas.yaml` committed, it needs `git add -f`.
Stop here — this completes the plan. A full `LoASComputeModel` implementing
`ArchComputeModel` end-to-end (wired into `combine()`'s live per-tile loop,
consuming this real solved schedule's tile boundaries) is a later plan,
deferred per the Global Constraints section above.

---

## Self-review notes

- **Spec coverage:** node-level dimension mapping (T fully resident, COUT
  spatial=16 and fully parallel, K=KH·KW·CIN fully resident) — covered in
  Task 3's YAML and cycles.py's docstring (why COUT costs zero cycles).
  Dense-weight, input-address-driven access pattern (no B-side bitmask
  compression, one burst per non-silent (kh,kw,cin) spanning the tile's
  whole assigned COUT range) — covered in `address.py`, matching the
  worked `[m,0] -> weight[k=0, cout_start:cout_start+16]` example
  verbatim. Two-part input compression matching Fig. 8 exactly (row-level
  bitmask + pointer over the full K candidate set, plus packed non-silent
  per-k spike data, no merge pass) — covered in Task 1 via
  `LoASReconstructed.{bitmask, ptr, lines}`, verified against a
  hand-reproduction of the paper's own worked example (bitmask "1001",
  packed values "1010"/"0111"). `access_cycle_count = compute_cycle_count
  = sum(row bitmask)`, independent of COUT — covered in Task 2, verified
  with the paper's own Fig. 8 numbers, a COUT-invariance check (same row,
  COUT=5 vs COUT=64, identical cycle count), a fully-silent edge case (0
  cycles), and a real-trace-scale case (130). Hardware-capacity input
  interface (`configs/arch/loas.yaml`) and a real MIP-solved single-node
  schedule — covered in Task 3, using a workload whose COUT exceeds the
  spatial cap to exercise the temporal-COUT-factor path rather than a
  trivially-fully-resident case.
- **No placeholders:** every step has complete, runnable code and an exact
  verification command with expected output.
- **Type consistency:** `LoASLine`/`LoASReconstructed` (Task 1, with
  `bitmask`/`ptr`/`lines` fields) are consumed by `cycles.py` (reads only
  `.bitmask`) and `address.py` (reads only `.lines`) in Task 2. Task 2's
  verification script constructs `LoASReconstructed` with all three
  required fields (no defaults on the dataclass) throughout, and keeps
  `access_cycle_count(reconstructed)`/`weight_access_count(reconstructed)`
  equal by construction in every part (Parts A, B, C, D all assert this).
  `NodeTileSpec`, `ComputeCycles` match `archmodels/__init__.py`'s
  existing definitions (unchanged by this plan — the `Optional[int]`
  widening for `lif_cycles` already landed in the PTB pilot).
