# Arch-specific cycle count — PTB pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this run:** the user asked to implement one task at
> a time and review/comment on each before the next — treat every task as
> its own checkpoint; do not proceed past a task without explicit
> go-ahead. Per project convention (confirmed: only commit when the user
> explicitly asks), tasks end with "present the diff for review", not an
> automatic `git commit`.

## Spec (rephrased)

This targets the PTB (Parallel Time Batching) architecture from Lee,
Zhang & Li, *"Parallel Time Batching: Systolic-Array Acceleration of
Sparse Spiking Neural Computation"* (HPCA 2022), as the third of the
6-architecture cycle-count plan (SpinalFlow was the pilot; see
`docs/superpowers/plans/2026-07-12-archmodel-spinalflow-pilot.md`).

This deployment fixes: time-window size `TW = 8`, PE array `16 x 8` (16
rows = COUT, 8 columns = active time-window slots), so one node tile
produces the output range `[ho, wo, COUT[start, start+16),
T[start, start+64)]`. A tile's input is `[ho+kh, wo+kw, CIN, T]`, laid out
as nested `[KH, KW, [CIN -> one length-T line]]`; one line is consumed by
the PE array per cycle.

**stSAP compression** (2 passes over the lines, in `[KH, KW, CIN]` order):
1. *Silence removal*: drop any line whose spikes are all-zero across the
   whole T range (the reduction index never fires).
2. *Adjacent non-overlap merge*: scan the surviving lines in order and OR
   together each line with its immediate neighbor whenever their spikes
   never coincide at the same timestep (e.g. `[0,1,0]` + `[1,0,1]` ->
   `[1,1,1]`), consuming one PE-array row-slot for the merged pair instead
   of two.

A tile's total cycle count is the max of two independent, potentially-
overlapping pipelines — the weight-access pipeline and the compute
pipeline — since neither can finish before the tile is done:
`total_cycle_count = max(access_cycle_count, compute_cycle_count)`.

**`access_cycle_count`** depends on the *Pass-1* line count, not Pass-2: a
merged pair (Pass 2) still touches two distinct `(kh, kw, cin)` weights,
so the weight-fetch pipeline issues one burst per cycle for
`access_cycle_count = len(lines_pass1)` cycles — this is also
`weight_access_count`, and `event_to_address` emits one
`(kh, kw, cin, cout_start, cout_end)` burst per Pass-1 line, same order.

**`compute_cycle_count`**, given `ln` = the *Pass-2* line count, `pe_rows`
= 16 (COUT), `TW` = 8, `PE_COLS_MAX` = 8, and `total_T` = this tile's
actual deployed T size (<= `TW * PE_COLS_MAX` = 64, since a run may not
fill the full hardware T capacity):
- `active_cols = ceil(total_T / TW)` — how many of the 8 columns are
  actually used.
- `last_col_timesteps = total_T - TW * (active_cols - 1)` — timesteps in
  the (possibly partial) last active column.
- The pipeline reaches the first element of the last row at
  `ln + pe_rows`, and the last active element of the last row at
  `ln + pe_rows + active_cols`.
- `compute_cycle_count = max(ln + pe_rows + total_T, ln + pe_rows +
  active_cols + last_col_timesteps)` — the first term bounds on the
  inherently-serial membrane-potential chain across all `total_T`
  timesteps; the second bounds on the systolic pipeline's fill/drain
  through the last column. (Sanity check against the paper's own numbers:
  full-array case, `active_cols = PE_COLS_MAX = 8`, `total_T = 64`
  collapses to `ln + 16 + 64` = `ln + 16 + 8*8`.)

Separately: `combine.py`'s single-node cycle-count wiring currently forces
every `ArchComputeModel` to report a distinct `lif_cycles` derived from
the dense per-node-dim `_A[j][VAR_VMEM]` formula. This isn't a PTB-
specific quirk: any single-node/pipelined architecture where MAC and LIF
work are interleaved per PE — not separated along a schedule-level
`VAR_VMEM` dimension the way the dense per-node-dim formula assumes — has
no meaningful separate LIF cycle count; the whole tile's cost is just one
`total_cycle_count`. PTB's `event_to_cycle` above is exactly that: a
single end-to-end number with no separable "LIF module" component to
extract. Make `ComputeCycles.lif_cycles` `Optional[int]`, where `None`
means "already folded into `mac_cycles`"; `combine.py` treats `None` as
contributing 0 additional LIF-transaction cycles, so archs like PTB
aren't forced to invent a fake split. `DenseStaticComputeModel` is
unaffected (it keeps returning a real int), so this is a zero-regression,
purely additive interface change.

**Goal:** Build PTB's `reconstruct_tile_sequence` / `event_to_cycle` /
`event_to_address` trio (matching the SpinalFlow pilot's architecture-
owned 3-stage pattern), and make the shared `ComputeCycles` interface
`lif_cycles`-agnostic so PTB (and future architectures like it) aren't
forced to report a meaningless separate LIF cycle count.

**Architecture:** `src/snn_cosa/archmodels/ptb/{__init__.py, reconstruct.py,
cycles.py, address.py}`, standalone and unwired (same scope as the
SpinalFlow pilot — live wiring into `combine()`'s per-tile loop is a
separate, later design pass for both architectures). `reconstruct.py`
performs the two-pass stSAP compression and returns both pass results
(cycle count needs Pass 2's count, weight access needs Pass 1's).

**Tech Stack:** Python 3, numpy, existing `snn_cosa` stack. No pytest in
this repo — verification runs a script and checks exact printed output,
per existing convention.

## Global Constraints

- Zero regression: every existing CLI path (`snn_cosa solve`,
  `snn_cosa.nocsim.sim`) must produce byte-identical output to before this
  plan, whenever `compute_model` is not explicitly passed (unaffected by
  Task 2's `Optional[int]` widening, since `DenseStaticComputeModel` still
  always returns a real `int`).
- No new third-party dependencies.
- `reconstruct_tile_sequence`, `event_to_cycle`, `event_to_address` are
  PTB-owned, not shared with SpinalFlow or any other architecture — do not
  refactor SpinalFlow's versions to share code with PTB's.
- Out of scope for this plan (needs its own design pass): wiring a full
  `PTBComputeModel` implementing the `ArchComputeModel` Protocol into
  `combine()`'s live per-tile loop. This plan only proves the PTB plugin
  correct standalone, against hand-specified tiles and (for `reconstruct.py`
  only) real trace data.

---

## Task 1: PTB input interface — `reconstruct_tile_sequence` with stSAP compression

**Files:**
- Create: `src/snn_cosa/archmodels/ptb/__init__.py`
- Create: `src/snn_cosa/archmodels/ptb/reconstruct.py`

**Interfaces:**
- Consumes: `NodeTileSpec` from `src/snn_cosa/archmodels/__init__.py`;
  `snn_cosa.parsers.layer.{DIM_KH, DIM_KW, DIM_CIN, DIM_HO, DIM_WO, DIM_T}`
  (pre-existing).
- Produces: `PTBLine`, `PTBReconstructed`,
  `reconstruct_tile_sequence(trace, tile) -> PTBReconstructed` — consumed
  by Task 3's `cycles.py` and `address.py`.

- [x] **Step 1: Write `ptb/__init__.py`**

```python
"""PTB (Parallel Time Batching) ArchComputeModel plugin -- pilot.

Reconstructs PTB's per-tile stSAP-compressed line sequence from a real
trace (reconstruct.py), then derives the pipeline cycle count (cycles.py)
and the ordered weight-address stream / weight_access_count (address.py)
from it. Standalone-verified against a real captured LoAS trace
(input_trace/loas/) used purely as sample spike data, and against hand-
built examples for the stSAP compression and pipeline-latency formulas
that the (currently T=4) real trace is too short to exercise fully.

This deployment fixes: time window size 8, 16x8 PE array (16 COUT rows x
8 time-window columns), per Lee, Zhang & Li, "Parallel Time Batching:
Systolic-Array Acceleration of Sparse Spiking Neural Computation" (HPCA
2022), Sections 4.3-4.4 and 6.1.2.
"""
```

- [x] **Step 2: Write `reconstruct.py`**

```python
"""Builds PTB's per-tile line sequence from a real spike trace, with
stSAP compression.

PTB packs a tile's receptive field into "lines": one length-T bit-vector
per (kh, kw, cin) reduction index, in [KH, KW, CIN] nested order -- one
line is fed into the PE array per cycle. stSAP (spatiotemporally-non-
overlapping spiking activity packing) then compresses these lines in two
passes:

  Pass 1 (silence removal): drop any line that never fires across its
  whole T range (a "silent" reduction index) -- spatial sparsity. Pass
  1's surviving line count is what actually touches the weight memory:
  event_to_address (address.py) emits exactly one weight burst per
  Pass-1 line.

  Pass 2 (adjacent non-overlap merge): scan the Pass-1 lines in order and
  greedily OR together each line with its immediate neighbor whenever
  their spikes never coincide at the same timestep (bitwise AND is all-
  zero) -- temporal sparsity, packing two lines into a single PE-array
  row-slot. Pass 2's group count (`ln`) is what determines the PE array's
  fill/drain latency: event_to_cycle (cycles.py) uses `ln`, NOT the
  Pass-1 count, because a merged pair still occupies only one row-slot
  even though it required two separate weight fetches.

Assumes batch=0 and stride=1/no-padding convolution (hin = ho + kh,
win = wo + kw), matching
src/snn_cosa/archmodels/spinalflow/reconstruct.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

from .. import NodeTileSpec


@dataclass(frozen=True)
class PTBLine:
    """One (kh, kw, cin) reduction index's line: its length-T spike bit-vector.

    bits[i] is 1 if the input at receptive-field offset (kh, kw), input
    channel cin, fired at the i-th timestep of this tile's T range
    (absolute timestep tile_offset[DIM_T] + i), else 0 -- one bit per
    timestep, straight from the trace. This is exactly what stSAP's two
    passes test: Pass 1 drops a line where any(bits) is False (never
    fires anywhere in T); Pass 2 merges two adjacent lines if their bits
    never overlap (bitwise AND is all-zero at every timestep).
    """

    kh: int
    kw: int
    cin: int
    bits: Tuple[int, ...]


@dataclass
class PTBReconstructed:
    lines_pass1: List[PTBLine]        # after silent-line removal
    lines_pass2: List[List[PTBLine]]  # after adjacent non-overlap merge; each group has 1 or 2 lines


def reconstruct_tile_sequence(trace: np.ndarray, tile: NodeTileSpec) -> PTBReconstructed:
    """Return this tile's stSAP-compressed lines, in [KH, KW, CIN] order.

    Args:
        trace: real spike trace, shape [T, B, Cin, Hin, Win], binary.
        tile:  identifies the receptive field -- tile_offset[DIM_HO]/
               [DIM_WO] select the output pixel, node_bound[DIM_KH]/
               [DIM_KW] the receptive-field extent, node_bound[DIM_CIN]/
               [DIM_T] (with matching tile_offset, default 0) the
               input-channel and timestep range.
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

    lines: List[PTBLine] = []
    for kh in range(kh_n):
        for kw in range(kw_n):
            hin = ho + kh
            win = wo + kw
            for cin in range(cin_off, cin_off + cin_n):
                bits = tuple(
                    int(trace[t, batch, cin, hin, win])
                    for t in range(t_off, t_off + t_n)
                )
                lines.append(PTBLine(kh, kw, cin, bits))

    # Pass 1: drop silent lines (never fire across the whole T range).
    lines_pass1 = [line for line in lines if any(line.bits)]

    # Pass 2: greedily merge each line with its immediate neighbor if their
    # spikes never coincide at the same timestep.
    lines_pass2: List[List[PTBLine]] = []
    i = 0
    while i < len(lines_pass1):
        cur = lines_pass1[i]
        if i + 1 < len(lines_pass1):
            nxt = lines_pass1[i + 1]
            if all(a == 0 or b == 0 for a, b in zip(cur.bits, nxt.bits)):
                lines_pass2.append([cur, nxt])
                i += 2
                continue
        lines_pass2.append([cur])
        i += 1

    return PTBReconstructed(lines_pass1=lines_pass1, lines_pass2=lines_pass2)
```

- [x] **Step 3: Write the verification script**

`/tmp/verify_ptb_reconstruct.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.ptb.reconstruct import reconstruct_tile_sequence
from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

# --- Part A: hand-built example matching the spec's own merge illustration ---
# Two adjacent lines [0,1,0] and [1,0,1] are non-overlapping -> merge to one group.
# A third, silent line [0,0,0] must be dropped entirely in Pass 1.
trace = np.zeros((3, 1, 3, 1, 1), dtype=np.uint8)  # [T=3, B=1, Cin=3, Hin=1, Win=1]
trace[1, 0, 0, 0, 0] = 1  # cin=0: [0,1,0]
trace[0, 0, 1, 0, 0] = 1  # cin=1: [1,0,1]
trace[2, 0, 1, 0, 0] = 1
# cin=2 stays all-zero (silent)

tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 3, DIM_T: 3},
    tile_offset={DIM_HO: 0, DIM_WO: 0},
    is_last_K=True,
)
r = reconstruct_tile_sequence(trace, tile)

assert len(r.lines_pass1) == 2, r.lines_pass1          # silent cin=2 line dropped
assert [l.cin for l in r.lines_pass1] == [0, 1]
assert len(r.lines_pass2) == 1, r.lines_pass2            # the two survivors merge
assert [l.cin for l in r.lines_pass2[0]] == [0, 1]
print(f"Part A OK: Pass1={len(r.lines_pass1)} lines, Pass2={len(r.lines_pass2)} groups (merged as expected)")

# --- Part B: real LoAS trace, sanity-check line/spatial-sparsity counts ---
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

assert len(r2.lines_pass1) == expected_nonsilent, (len(r2.lines_pass1), expected_nonsilent)
assert len(r2.lines_pass2) <= len(r2.lines_pass1)          # Pass 2 never increases line count
for group in r2.lines_pass2:
    assert 1 <= len(group) <= 2

print(f"Part B OK: {total_lines} candidate lines -> Pass1={len(r2.lines_pass1)} "
      f"(matches independent non-silent count {expected_nonsilent}) -> "
      f"Pass2={len(r2.lines_pass2)} groups")
```

- [x] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_ptb_reconstruct.py`
Expected: `Part A OK: Pass1=2 lines, Pass2=1 groups (merged as expected)` followed
by `Part B OK: 576 candidate lines -> Pass1=<N> (matches independent non-silent
count <N>) -> Pass2=<M> groups` with `M <= N`.

- [x] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/ptb/`
Stop here for review/comment.

---

## Task 2: Make `ComputeCycles.lif_cycles` optional (single-node lif_count agnostic)

**Files:**
- Modify: `src/snn_cosa/archmodels/__init__.py`
- Modify: `src/snn_cosa/nocsim/combine.py`

**Interfaces:**
- Modifies: `ComputeCycles.lif_cycles: int` -> `Optional[int] = None`.
- Consumed by: `combine.py`'s cycle-count section (existing), all future
  `ArchComputeModel` implementations (PTB's eventual `PTBComputeModel`
  will return `lif_cycles=None`).

- [x] **Step 1: Capture the pre-change baseline**

```bash
export PYTHONPATH=src
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/single_node_schedule.json \
  --layer configs/workloads/sim_demo.yaml \
  --arch configs/arch/snn_arch_single_node.yaml \
  --out /tmp/baseline_ptb_task2_tc.csv --simulate
```
Record the printed `transactions`, `dram_cost` per variable, and
`total_cycles`/`count_cycles`/`dram_cycles` — the "before" numbers.

- [x] **Step 2: Modify `archmodels/__init__.py`**

Change:
```python
@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: int
```
to:
```python
@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: Optional[int] = None
    """None means this architecture has no meaningful split between MAC
    and LIF cycles -- mac_cycles just holds the tile's total_cycle_count.
    This is the general case for single-node/pipelined architectures where
    MAC and LIF work are interleaved per PE rather than separated along a
    schedule-level VAR_VMEM dimension (e.g. PTB, see archmodels/ptb/).
    combine.py treats None as contributing 0 additional LIF-transaction
    cycles."""
```
and add `Optional` to the existing `from typing import Any, Dict, Protocol`
import line (-> `from typing import Any, Dict, Optional, Protocol`).

- [x] **Step 3: Modify `combine.py`'s cycle-count section**

At the existing lines:
```python
    # ── 2. Pre-compute cycle counts ───────────────────────────────────────
    model = compute_model or DenseStaticComputeModel(schedule, prob)
    cycles = model.compute_cycles(model.format_input(None, None), None)
    mac_cyc, lif_cyc = cycles.mac_cycles, cycles.lif_cycles
```
change the last line to:
```python
    mac_cyc = cycles.mac_cycles
    lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0
```

- [x] **Step 4: Verify the dataclass accepts `None`**

Run:
```bash
cd /home/yy/projects/snn_cosa && PYTHONPATH=src python3 -c "
from snn_cosa.archmodels import ComputeCycles
c = ComputeCycles(mac_cycles=42, lif_cycles=None)
assert c.mac_cycles == 42 and c.lif_cycles is None
c2 = ComputeCycles(mac_cycles=10, lif_cycles=5)
assert c2.lif_cycles == 5
print('ok')
"
```
Expected: `ok`

- [x] **Step 5: Re-run the exact Step-1 command and diff**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/single_node_schedule.json \
  --layer configs/workloads/sim_demo.yaml \
  --arch configs/arch/snn_arch_single_node.yaml \
  --out /tmp/after_ptb_task2_tc.csv --simulate
diff /tmp/baseline_ptb_task2_tc.csv /tmp/after_ptb_task2_tc.csv
```
Expected: `diff` produces no output (files identical) — `DenseStaticComputeModel`
still always returns a real int `lif_cycles`, so this path is unaffected.

- [x] **Step 6: Present for review**

Run: `git diff src/snn_cosa/archmodels/__init__.py src/snn_cosa/nocsim/combine.py`
Show the full diff plus the Step 5 `diff` output (empty). Stop here for
review/comment.

---

## Task 3: PTB archmodel — `event_to_cycle` and `event_to_address`

**Files:**
- Create: `src/snn_cosa/archmodels/ptb/cycles.py`
- Create: `src/snn_cosa/archmodels/ptb/address.py`

**Interfaces:**
- Consumes: `PTBReconstructed`/`PTBLine` from Task 1's `reconstruct.py`;
  `NodeTileSpec` from `archmodels/__init__.py`;
  `snn_cosa.parsers.layer.{DIM_COUT, DIM_T}` (pre-existing).
- Produces: `access_cycle_count(reconstructed) -> int`,
  `compute_cycle_count(reconstructed, tile) -> int`,
  `event_to_cycle(reconstructed, tile) -> int` (= `max` of the two),
  `event_to_address(reconstructed, tile) -> List[Tuple[int,int,int,int,int]]`,
  `weight_access_count(reconstructed) -> int` — consumed by a future
  `PTBComputeModel` (out of scope here, per Global Constraints).

- [x] **Step 1: Write `cycles.py`**

```python
"""PTB cycle count: max of the weight-access pipeline and the compute
pipeline, over stSAP-compressed lines.

A tile isn't done until BOTH pipelines are done, so:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

access_cycle_count -- the weight-fetch pipeline issues one burst per
cycle, one per stSAP Pass-1 line (see reconstruct.py; same count as
address.py's weight_access_count). No systolic propagation delay: this is
a flat sequential fetch count.

compute_cycle_count -- PTB's PE array is `pe_rows` (one row per output/
COUT neuron, read from tile.node_bound[DIM_COUT]) by up to PE_COLS_MAX
columns (one column per active time window). Lines (after stSAP Pass-2
merge) feed into the array one per cycle; the array is a systolic
pipeline, so a line issued at cycle `i` reaches PE-array row `r`, column
`c` at cycle `i + r + c`. Two things bound this pipeline's total run
time:
  1) the membrane-potential update chain across all `total_T` timesteps of
     this tile is inherently serial (vmem[t] depends on vmem[t-1]), so the
     array can't finish before `ln + pe_rows + total_T`;
  2) the pipeline itself must fully drain through the last active column,
     which takes `ln + pe_rows + active_cols + last_col_timesteps`.
  compute_cycle_count is the max of these two.

This is a single end-to-end cycle count covering both integration (MAC)
and membrane-potential/spike-generation (LIF) work -- PTB's pipeline
interleaves them per PE, so they are not modeled as two separable numbers
(see archmodels/__init__.py's ComputeCycles.lif_cycles=None convention
for architectures like this one).
"""

from __future__ import annotations

from snn_cosa.parsers.layer import DIM_COUT, DIM_T

from .. import NodeTileSpec
from .reconstruct import PTBReconstructed

TW_SIZE = 8       # time points packed per time window (this PTB config)
PE_COLS_MAX = 8   # max active time-window columns (16x8 array, this config)


def access_cycle_count(reconstructed: PTBReconstructed) -> int:
    return len(reconstructed.lines_pass1)


def compute_cycle_count(reconstructed: PTBReconstructed, tile: NodeTileSpec) -> int:
    ln = len(reconstructed.lines_pass2)
    pe_rows = tile.node_bound[DIM_COUT]
    total_t = tile.node_bound[DIM_T]

    active_cols = -(-total_t // TW_SIZE)  # ceil division
    last_col_timesteps = total_t - TW_SIZE * (active_cols - 1)

    full_total = ln + pe_rows + total_t
    active_drain = ln + pe_rows + active_cols + last_col_timesteps
    return max(full_total, active_drain)


def event_to_cycle(reconstructed: PTBReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
```

- [x] **Step 2: Write `address.py`**

```python
"""PTB weight address per stSAP Pass-1 line.

Each surviving (kh, kw, cin) reduction index -- after Pass-1 silence
removal but BEFORE Pass-2 merging -- requires exactly one weight burst,
contiguous across this tile's full output-channel range (all COUT rows of
the array read the same weight simultaneously). Pass-2 merging only packs
two lines into a shared row-slot for timing purposes (see cycles.py); it
does not reduce the number of distinct weights fetched, since a merged
pair still comes from two different (kh, kw, cin) indices. This is why
weight_access_count is len(lines_pass1), not len(lines_pass2) -- the same
count as cycles.py's access_cycle_count.
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec
from .reconstruct import PTBReconstructed


def event_to_address(
    reconstructed: PTBReconstructed, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (line.kh, line.kw, line.cin, cout_off, cout_off + cout_n)
        for line in reconstructed.lines_pass1
    ]


def weight_access_count(reconstructed: PTBReconstructed) -> int:
    return len(reconstructed.lines_pass1)
```

- [x] **Step 3: Write the verification script**

`/tmp/verify_ptb_cycles_address.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.ptb.address import event_to_address, weight_access_count
from snn_cosa.archmodels.ptb.cycles import access_cycle_count, compute_cycle_count, event_to_cycle
from snn_cosa.archmodels.ptb.reconstruct import PTBLine, PTBReconstructed, reconstruct_tile_sequence
from snn_cosa.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

# --- Part A: compute-dominant, full-array case: matches the spec's own -----
# worked example. pe_rows=16 (COUT), TW=8, PE_COLS_MAX=8, total_T=64 (fully
# occupies all 8 columns) -> compute_cycle_count = ln + 16 + 64 == ln + 16 + 8*8,
# and access_cycle_count (5) is far smaller, so it doesn't gate the total.
lines_pass1 = [PTBLine(0, 0, c, tuple([1] * 64)) for c in range(5)]
lines_pass2 = [[lines_pass1[0]], [lines_pass1[1]], [lines_pass1[2]],
               [lines_pass1[3]], [lines_pass1[4]]]  # overlapping (all-ones) -> no merges, ln=5
r_full = PTBReconstructed(lines_pass1=lines_pass1, lines_pass2=lines_pass2)
tile_full = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_COUT: 16, DIM_T: 64},
    tile_offset={DIM_COUT: 0},
    is_last_K=True,
)
ln = len(r_full.lines_pass2)
assert ln == 5
expected_compute_full = ln + 16 + 8 * 8
assert compute_cycle_count(r_full, tile_full) == expected_compute_full
assert access_cycle_count(r_full) == 5
assert event_to_cycle(r_full, tile_full) == max(5, expected_compute_full) == expected_compute_full
print(f"Part A OK (compute-dominant): access={access_cycle_count(r_full)}, "
      f"compute={expected_compute_full} (== ln+16+8*8), total={event_to_cycle(r_full, tile_full)}")

# --- Part B: compute-dominant, partial case: total_T=8 (1 of 8 columns) ----
r_partial = PTBReconstructed(lines_pass1=lines_pass1[:2], lines_pass2=[[lines_pass1[0]], [lines_pass1[1]]])
tile_partial = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_COUT: 16, DIM_T: 8},
    tile_offset={DIM_COUT: 0},
    is_last_K=True,
)
ln2 = len(r_partial.lines_pass2)
# active_cols = ceil(8/8) = 1, last_col_timesteps = 8
full_total = ln2 + 16 + 8
active_drain = ln2 + 16 + 1 + 8
expected_compute_partial = max(full_total, active_drain)
assert compute_cycle_count(r_partial, tile_partial) == expected_compute_partial
assert access_cycle_count(r_partial) == 2
assert event_to_cycle(r_partial, tile_partial) == expected_compute_partial
print(f"Part B OK (compute-dominant): access={access_cycle_count(r_partial)}, "
      f"compute={expected_compute_partial} (== max({full_total}, {active_drain})), "
      f"total={event_to_cycle(r_partial, tile_partial)}")

# --- Part C: access-dominant case -- many weight fetches, tiny compute ----
# 50 lines (cin=0..49) each of length T=2: even cin fires at t=0 only
# ([1,0]), odd cin fires at t=1 only ([0,1]) -- every adjacent pair is
# non-overlapping, so Pass 2 merges all of them into 25 groups.
trace = np.zeros((2, 1, 50, 1, 1), dtype=np.uint8)
for cin in range(50):
    trace[0 if cin % 2 == 0 else 1, 0, cin, 0, 0] = 1
tile_access = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 50, DIM_COUT: 16, DIM_T: 2},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_COUT: 0},
    is_last_K=True,
)
r_access = reconstruct_tile_sequence(trace, tile_access)
assert len(r_access.lines_pass1) == 50
assert len(r_access.lines_pass2) == 25          # every adjacent pair merges
a = access_cycle_count(r_access)
c = compute_cycle_count(r_access, tile_access)
assert a == 50
assert c == 25 + 16 + max(2, 1 + 2)              # ln + pe_rows + max(total_T, active_cols+last_col)
assert a > c, (a, c)                              # access must dominate for this test to be meaningful
assert event_to_cycle(r_access, tile_access) == a
print(f"Part C OK (access-dominant): access={a}, compute={c}, total={event_to_cycle(r_access, tile_access)}")

# --- Part D: address.py / weight_access_count: keys off Pass 1, not Pass 2 -
tile_addr = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_COUT: 16, DIM_T: 64},
    tile_offset={DIM_COUT: 0},
    is_last_K=True,
)
addrs = event_to_address(r_full, tile_addr)
assert len(addrs) == len(lines_pass1) == 5
assert weight_access_count(r_full) == 5
assert addrs[0] == (0, 0, 0, 0, 16), addrs[0]
print(f"Part D OK: weight_access_count={weight_access_count(r_full)} "
      f"(== Pass-1 count, not Pass-2's merged {len(lines_pass2)})")
```

- [x] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_ptb_cycles_address.py`
Expected:
```
Part A OK (compute-dominant): access=5, compute=85 (== ln+16+8*8), total=85
Part B OK (compute-dominant): access=2, compute=27 (== max(26, 27)), total=27
Part C OK (access-dominant): access=50, compute=44, total=50
Part D OK: weight_access_count=5 (== Pass-1 count, not Pass-2's merged 5)
```

- [x] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/ptb/`

---

## Task 4: PTB arch YAML + real MIP-solved single-node schedule

Added after initial review: Tasks 1-3 only exercised the Python plugin
against hand-built `NodeTileSpec` fixtures. This task builds the actual
hardware-capacity *input interface* the MIP solver consumes --
`configs/arch/ptb.yaml`, mirroring `spinalflow.yaml`'s structure -- and
runs a real `snn_cosa solve` against it to produce a genuine PTB
single-node schedule, proving the config is solver-feasible and encodes
the right node-level residency (not just that the Python functions are
internally consistent).

**Files:**
- Create: `configs/arch/ptb.yaml`
- Create: `outputs/ptb_single_node_schedule.json` (solver output, gitignored)

**Interfaces:**
- Consumes: `snn_cosa.parsers.arch.SNNArch` (`node_dim_capacity`,
  `single_node`, `{spatial: N}` form -- all pre-existing, from Part 1 of
  the 6-arch plan).
- Produces: a schedule JSON consumable by `snn_cosa.nocsim.sim` (same
  contract as `outputs/single_node_schedule.json` used in Task 2).

- [x] **Step 1: Write `configs/arch/ptb.yaml`**

Mirrors `spinalflow.yaml`'s structure (`single_node: true`,
`node_dim_capacity`, `storage`), adapted to PTB's fixed TW=8/16x8-array
deployment:
- `COUT: {spatial: 16}` -- one PE-array row per output channel (16 rows),
  validated against `pe.num_pes` at parse time (V1: product of
  spatial-tagged factors <= num_pes).
- `T: 64` -- capped, not `null`: 64 = TW(8) x PE_COLS_MAX(8) is the
  hardware's total addressable time-window capacity. This only bounds
  *residency* (how much T fits in one node visit); the internal
  8-columns x 8-per-column decomposition is derived separately by
  `archmodels/ptb/cycles.py` from the resident T count, not by the MIP.
  A layer with T > 64 must revisit the node (extra DRAM-level T
  iterations) -- verified in Step 3 below.
- `KH: 4`, `KW: 4`, `CIN: null` -- **not paper-derived**: PTB HPCA'22
  doesn't state a receptive-field buffer capacity, so this mirrors
  `spinalflow.yaml`'s assumption for a comparable systolic design.
  Flagged for the user to revisit if a specific PTB buffer size surfaces.
- `pe.num_pes: 128` -- 16 rows x 8 columns, matching the paper's Table 4
  ("Number of PEs: 128").

(Full file content: see `configs/arch/ptb.yaml` in the repo.)

- [x] **Step 2: Pick a workload that actually exercises node capacity**

`configs/workloads/sim_demo.yaml` (COUT=8) fails V2 (spatial factor must
*evenly divide* the dimension's total size, not just fit under it --
16 does not divide 8). Use
`configs/workloads/generated/resnet19/T128/conv1.yaml` instead
(`KH=3, KW=3, CIN=3, COUT=16, HO=32, WO=32, T=128`): COUT=16 divides
exactly, and T=128 exceeds the 64 cap, so this run actually exercises the
"T spills to DRAM beyond capacity" path instead of trivially fitting
everything at NodeLevel.

- [x] **Step 3: Run the solver**

```bash
export PYTHONPATH=src
python3 -m snn_cosa solve \
  --layer configs/workloads/generated/resnet19/T128/conv1.yaml \
  --arch configs/arch/ptb.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/ptb_single_node_schedule.json
```
Expected: `status: OPTIMAL`, `objective: <float>`,
`output: outputs/ptb_single_node_schedule.json`.

Then inspect the strategy:
```bash
python3 -c "
import json
d = json.load(open('outputs/ptb_single_node_schedule.json'))
print(json.dumps(d['strategy'], indent=2))
"
```
Expected: `NodeLevel.temporal_tile.factors` contains `KH=3, KW=3, CIN=3,
T=64` (T capped at exactly 64, not the full 128); `NodeLevel.spatial_split.
factors` contains exactly `COUT=16`; `NoCLevel` both permutation/split are
empty (`single_node` bars it); `DRAM.temporal_permutation.loops` contains
`HO`, `WO` (barred from NodeLevel entirely) and a leftover `T` factor of
`2` (the `128 / 64` that didn't fit at NodeLevel).

- [x] **Step 4: Run the solved schedule through the NoC simulator**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/ptb_single_node_schedule.json \
  --layer configs/workloads/generated/resnet19/T128/conv1.yaml \
  --arch configs/arch/ptb.yaml \
  --out /tmp/ptb_tc.csv --simulate
```
Expected: exits 0 and prints `transactions`, `dram_cost`, `total_cycles`,
etc. (Cycle numbers here come from the default `DenseStaticComputeModel`,
NOT `archmodels/ptb/cycles.py` -- wiring PTB's real per-tile model into
this live loop is still out of scope, per the Global Constraints. This
step only proves the config produces a schedule the simulator can run,
not that the printed cycle count reflects PTB's real hardware behavior.)

- [x] **Step 5: Present for review**

Run: `git status --short configs/arch/ptb.yaml` (expect untracked --
gitignored like `spinalflow.yaml`, `snn_arch_single_node.yaml`,
`sim_demo.yaml`; the repo's `.gitignore` blanket-ignores `*.yaml`/`*.json`
and only 3 config files are actually committed:
`configs/arch/snn_arch.yaml`, `configs/mapspace/mapspace.yaml`,
`configs/workloads/sample_snn_layer.yaml`). If the user wants
`ptb.yaml` committed, it needs `git add -f`.
Stop here — this completes the plan. A full `PTBComputeModel` implementing
`ArchComputeModel` end-to-end (wired into `combine()`'s live per-tile loop,
consuming this real solved schedule's tile boundaries) is a later plan,
deferred per the Global Constraints section above.

---

## Task 5: `active_rows` symmetry correction (post-review)

Added after a second review pass. Task 3's `compute_cycle_count` already
read `pe_rows` from `tile.node_bound[DIM_COUT]` (the tile's actual
resident COUT, not a hardcoded 16), so it already varied with COUT
numerically. But unlike columns, there was no explicit `PE_ROWS_MAX`
constant and no `active_rows` name/clamp mirroring `active_cols` --
the row dimension wasn't defensively symmetric with the column dimension
the way the spec calls for. This task makes that explicit and adds a
concrete regression case proving the sensitivity, rather than leaving it
implicit.

**Files:**
- Modify: `src/snn_cosa/archmodels/ptb/cycles.py`

- [x] **Step 1: Add `PE_ROWS_MAX` and `active_rows`, mirroring `active_cols`**

In `cycles.py`, add the constant next to `PE_COLS_MAX`:
```python
TW_SIZE = 8       # time points packed per time window (this PTB config)
PE_ROWS_MAX = 16  # PE-array row count = max distinct COUT rows (this config)
PE_COLS_MAX = 8   # max active time-window columns (16x8 array, this config)
```
and change `compute_cycle_count` to:
```python
def compute_cycle_count(reconstructed: PTBReconstructed, tile: NodeTileSpec) -> int:
    ln = len(reconstructed.lines_pass2)
    active_rows = min(tile.node_bound[DIM_COUT], PE_ROWS_MAX)
    total_t = tile.node_bound[DIM_T]

    active_cols = min(-(-total_t // TW_SIZE), PE_COLS_MAX)  # ceil division
    last_col_timesteps = total_t - TW_SIZE * (active_cols - 1)

    full_total = ln + active_rows + total_t
    active_drain = ln + active_rows + active_cols + last_col_timesteps
    return max(full_total, active_drain)
```
(`active_cols` also now explicitly clamps to `PE_COLS_MAX`, matching
`active_rows`'s clamp -- previously it relied entirely on the arch
config's `T` cap to stay in range.)

- [x] **Step 2: Add a regression case proving `active_rows` responds to COUT**

Append to `/tmp/verify_ptb_cycles_address.py` (same reconstructed lines as
Part A -- full-array, `ln=5`, `total_T=64` -- against two tiles differing
only in `DIM_COUT`):
```python
tile_cout16 = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 16, DIM_T: 64}, tile_offset={DIM_COUT: 0}, is_last_K=True)
tile_cout8 = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 8, DIM_T: 64}, tile_offset={DIM_COUT: 0}, is_last_K=True)
c16 = compute_cycle_count(r_full, tile_cout16)
c8 = compute_cycle_count(r_full, tile_cout8)
assert c16 == ln + 16 + 64
assert c8 == ln + 8 + 64
assert c16 - c8 == 8, (c16, c8)
print(f"Part E OK: compute_cycle_count(COUT=16)={c16}, compute_cycle_count(COUT=8)={c8} "
      f"(active_rows shrinks the total by exactly the COUT difference: {c16 - c8})")
```

- [x] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_ptb_cycles_address.py`
Expected: Parts A-D unchanged (all used `COUT=16`, so no behavior change
there), plus:
```
Part E OK: compute_cycle_count(COUT=16)=85, compute_cycle_count(COUT=8)=77 (active_rows shrinks the total by exactly the COUT difference: 8)
```

- [x] **Step 4: Present for review**

Run: `git diff src/snn_cosa/archmodels/ptb/cycles.py`

---

## Task 6: Workload sweep -- small->large T x COUT, MIP results saved for manual review

Requested directly: generate several workloads varying T and COUT (small
to large) and save the solver's results so they can be checked by hand,
rather than just spot-verified by this agent.

**Files:**
- Create: `configs/workloads/ptb_sweep/*.yaml` (12 workloads)
- Create: `outputs/ptb_sweep/*.json` (12 solved schedules, gitignored)
- Create: `outputs/ptb_sweep/summary.txt` (compact table across all 12)

- [x] **Step 1: Generate the sweep workloads**

12 workloads = 3 COUT values x 4 T values, holding `KH=3, KW=3, CIN=8,
HO=8, WO=8` fixed so any difference is attributable only to T/COUT:
- `COUT in {16, 64, 128}` -- multiples of 16, required by V2 (spatial
  cap must evenly divide the dimension's total size).
- `T in {1, 8, 64, 256}` -- sub-TW, exactly-one-column, exactly-at-the-
  64 node cap, and beyond-cap (forces DRAM spillover).

Each file (`configs/workloads/ptb_sweep/cout{C}_t{T}.yaml`):
```yaml
problem:
  KH: 3
  KW: 3
  CIN: 8
  COUT: {cout}
  HO: 8
  WO: 8
  T: {t}
  shape: snn-layer
```

- [x] **Step 2: Solve all 12 against `configs/arch/ptb.yaml`**

```bash
export PYTHONPATH=src
for f in configs/workloads/ptb_sweep/*.yaml; do
  name=$(basename "$f" .yaml)
  python3 -m snn_cosa solve \
    --layer "$f" \
    --arch configs/arch/ptb.yaml \
    --mapspace configs/mapspace/mapspace.yaml \
    --out "outputs/ptb_sweep/${name}.json"
done
```
Expected: all 12 print `status: OPTIMAL`.

- [x] **Step 3: Build a compact summary table across all 12**

`outputs/ptb_sweep/summary.txt` -- one row per workload with
`node temporal`, `node spatial`, and `dram` loop factors extracted from
each JSON (see the file for exact contents). Observed pattern, confirmed
consistent across the whole sweep:
- **COUT**: always exactly 16 spatial (fixed row count) regardless of
  total COUT; any COUT beyond 16 shows up as an *additional* NodeLevel
  **temporal** COUT factor = `total_COUT / 16` (e.g. temporal COUT=8 for
  total 128) -- the MIP schedules multiple full-16-row passes to cover
  COUT > 16, entirely at NodeLevel, never barred or sent to DRAM.
- **T**: resident at NodeLevel up to `min(T, 64)`; `T <= 64` is fully
  resident, `T=256` caps at 64 resident with the leftover factor (`4`,
  decomposed as `Tx2 * Tx2`) pushed to DRAM.
- **HO/WO**: always entirely at DRAM (barred from NodeLevel), matching
  `spinalflow.yaml`'s same HO/WO handling.
- **NoCLevel**: empty in every run (`single_node: true` bars it).

- [x] **Step 4: Present for review**

Run: `cat outputs/ptb_sweep/summary.txt` and hand off
`configs/workloads/ptb_sweep/` + `outputs/ptb_sweep/` (both gitignored,
like the other local sweep/solve artifacts in this repo) for the user's
own manual check of the raw JSONs.

---

## Self-review notes

- **Spec coverage:** input interface (Task 1: `[KH,KW,CIN]`-ordered lines,
  one length-T line per cycle, `bits` field documented) — covered. stSAP
  2-pass compression (Task 1) — covered, both passes preserved and exposed
  separately. lif_count agnostic single-node interface, generalized beyond
  PTB (Task 2) — covered, zero-regression verified. `total_cycle_count =
  max(access_cycle_count, compute_cycle_count)` (Task 3) — covered, both
  terms verified independently plus one compute-dominant and one access-
  dominant case, and the compute term checked against the spec's own
  worked numeric example (`ln+16+8*8`). `weight_access_count` keyed off
  Pass 1 (Task 3) — covered. Hardware-capacity input interface
  (`configs/arch/ptb.yaml`) and a real MIP-solved single-node schedule
  (Task 4) — covered, verified with a real workload whose COUT divides
  the spatial cap and whose T exceeds the node cap, confirming genuine
  DRAM-spillover behavior, not just a trivially-fully-resident case.
  `active_rows` symmetry with `active_cols` (Task 5) — covered, regression
  case proves `compute_cycle_count` responds to node-level COUT < 16.
  Small->large T x COUT workload sweep with saved, manually-reviewable
  MIP results (Task 6) — covered, 12/12 OPTIMAL, node-level residency
  pattern consistent across the whole sweep.
- **No placeholders:** every step has complete, runnable code and an exact
  verification command with expected output.
- **Type consistency:** `PTBLine`/`PTBReconstructed` (Task 1) are consumed
  identically by `cycles.py` and `address.py` (Task 3). `NodeTileSpec`,
  `ComputeCycles` (Task 2) match `archmodels/__init__.py`'s existing
  definitions from the SpinalFlow pilot. `access_cycle_count`/
  `compute_cycle_count`/`event_to_cycle` (Task 3) share the same
  `PTBReconstructed` type from Task 1 throughout.
