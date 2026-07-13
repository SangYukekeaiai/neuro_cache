# Arch-specific cycle count — SpinalFlow pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this run:** the user asked to implement one task at
> a time and review/comment on each before the next — treat every task as
> its own checkpoint; do not proceed past a task without explicit
> go-ahead. Per project convention (confirmed: only commit when the user
> explicitly asks), tasks end with "present the diff for review", not an
> automatic `git commit`.

**Goal:** Replace `combine.py`'s static, trace-agnostic MAC/LIF cycle
formula with a pluggable `ArchComputeModel`, and build the first real
(non-default) implementation of it for SpinalFlow, verified end-to-end
against a real captured LoAS spike trace used purely as sample data.

**Architecture:** `src/snn_cosa/archmodels/` is a new package: a Protocol
(`ArchComputeModel`) plus a `NodeTileSpec` describing which slice of a real
trace one node-level tile covers. `dense.py` is the default implementation
(today's formula, refactored, zero behavior change, called exactly once
per `combine()` run — unchanged from today). `spinalflow/` is the first
real, trace-driven implementation, built and verified standalone against
`input_trace/loas/` — a local copy of the real LoAS-captured trace.

**Tech Stack:** Python 3, numpy, existing `snn_cosa` MIP/NoC-sim stack
(Gurobi only needed to regenerate a schedule JSON, not for this plan's new
code). No pytest in this repo — verification follows the project's existing
convention (`COMMANDS.md`, `PLAN_single_node.md`): run a script or CLI
command, check exact printed/computed output.

## Global Constraints

- Zero regression: every existing CLI path (`snn_cosa solve`,
  `snn_cosa.nocsim.sim`) must produce byte-identical output to before this
  plan, whenever `compute_model` is not explicitly passed.
- No new third-party dependencies (numpy/PyYAML/gurobipy already cover
  everything needed).
- `snn_cosa` must not import from `neuro_cache` — the pilot's SpinalFlow
  code is a fresh, standalone port, not a cross-repo dependency (per the
  2026-07-12 design doc, "everything inside snn_cosa").
- Out of scope for this plan (explicitly deferred, needs its own design
  pass before starting): wiring `SpinalFlowComputeModel` into `combine()`'s
  live per-tile `dram_i`/`noc_i` loop. That requires deriving each tile's
  `NodeTileSpec.tile_offset` from the solved schedule (which output pixel,
  which DRAM sub-range) — a distinct, riskier piece of design. This plan
  only proves the SpinalFlow plugin is correct standalone, against
  hand-specified tiles and real trace data.

---

## Task 1: Local trace copy + locality placeholder

**Files:**
- Create: `input_trace/loas/` (copied from
  `/home/yy/projects/neuro_cache/input_trace/loas/`)
- Create: `src/snn_cosa/locality/__init__.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy` (and
  siblings) — consumed by Task 5's verification.

- [x] **Step 1: Copy the trace data**

```bash
mkdir -p input_trace
cp -r /home/yy/projects/neuro_cache/input_trace/loas input_trace/loas
```

- [x] **Step 2: Verify the copy is complete**

Run: `find input_trace/loas -name "*.npy" | wc -l && du -sh input_trace/loas`
Expected: same file count and size as the source
(`find /home/yy/projects/neuro_cache/input_trace/loas -name "*.npy" | wc -l`
→ compare counts; `du -sh` → `11M`).

- [x] **Step 3: Gitignore the trace data**

Add to `.gitignore` (it already ignores `outputs/`; add a matching line):
```
input_trace/
```

- [x] **Step 4: Create the locality placeholder package**

`src/snn_cosa/locality/__init__.py`:
```python
"""Placeholder for the neuromorphic-cache locality/reuse analyzer.

Reserved for TITL (Time-Inner Temporal Locality), MITL (M-Inner Temporal
Locality), and NISL (N-Inner Spatial Locality) classification of weight
access patterns, per the 2026-07-12 "Neuromorphic Cache Design" draft.
No implementation yet -- intentionally empty until the archmodels/ pilot
(this plan) proves out the real-trace-driven weight-address stream this
package will eventually consume.
"""
```

- [x] **Step 5: Present for review**

Run: `git status && git diff --stat`
Show the user: new `input_trace/loas/` (untracked, gitignored — won't show
in `git status` after Step 3), new `src/snn_cosa/locality/__init__.py`,
modified `.gitignore`. Stop here for review/comment.

---

## Task 2: `archmodels` package skeleton

**Files:**
- Create: `src/snn_cosa/archmodels/__init__.py`

**Interfaces:**
- Produces: `NodeTileSpec`, `ComputeCycles`, `ArchComputeModel` — consumed
  by Task 3 (`dense.py`) and Task 5-7 (`spinalflow/`).

- [x] **Step 1: Write the package**

`src/snn_cosa/archmodels/__init__.py`:
```python
"""ArchComputeModel: pluggable, trace-driven per-node cycle counts.

Replaces combine.py's static dense-tile formula with an architecture-
specific model that derives MAC/LIF cycle counts (and, for a real trace-
driven model, the weight addresses touched) from an actual spike trace.

NodeTileSpec identifies which slice of a real trace one node-level tile
covers, using the same dimension indices as snn_cosa.parsers.layer
(DIM_KH, DIM_KW, DIM_CIN, DIM_COUT, DIM_HO, DIM_WO, DIM_T):

  node_bound[dim]  -- how many values of `dim` this tile spans
  tile_offset[dim] -- the starting index into the real trace for `dim`

The default model (archmodels.dense.DenseStaticComputeModel) ignores the
real trace and both NodeTileSpec fields entirely, returning the same
static value for every tile -- see its docstring. A real model (e.g.
archmodels.spinalflow) uses them to slice the trace and reconstruct that
tile's actual spike sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class NodeTileSpec:
    dram_i: int
    node_bound: Dict[int, int]
    tile_offset: Dict[int, int]
    is_last_K: bool


@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: int


class ArchComputeModel(Protocol):
    """Per-architecture plugin, called once per node-level tile."""

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        """Slice/reconstruct this tile's real-trace-derived representation."""
        ...

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        """Derive this tile's (mac_cycles, lif_cycles) from format_input's output."""
        ...
```

- [x] **Step 2: Verify it imports cleanly**

Run: `cd /home/yy/projects/snn_cosa && PYTHONPATH=src python3 -c "from snn_cosa.archmodels import NodeTileSpec, ComputeCycles, ArchComputeModel; print('ok')"`
Expected: `ok`

- [x] **Step 3: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/`
Stop here for review/comment.

---

## Task 3: `dense.py` — default model, standalone equivalence check

**Files:**
- Create: `src/snn_cosa/archmodels/dense.py`

**Interfaces:**
- Consumes: `ArchComputeModel`, `ComputeCycles`, `NodeTileSpec` from Task 2.
- Consumes: `snn_cosa.nocsim.schedule.decode.Schedule`,
  `snn_cosa.parsers.layer.SNNProb`, `snn_cosa.model.constants._A`,
  `snn_cosa.model.constants.VAR_VMEM` (all pre-existing).
- Produces: `DenseStaticComputeModel(schedule, prob)` — consumed by Task 4.

- [x] **Step 1: Write `dense.py`**

`src/snn_cosa/archmodels/dense.py`:
```python
"""Default ArchComputeModel: today's analytical dense-tile formula.

This is combine.py's original _pe_cycles/_lif_cycles, refactored behind
the ArchComputeModel Protocol with zero behavior change. It ignores the
real trace and the NodeTileSpec entirely -- every node-level tile gets the
same cycle count, computed once from the schedule's loop-factor structure,
matching combine()'s existing single upfront call (mac_cyc/lif_cyc are
computed once per run today, not per tile, because this formula is static).
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import Any, Dict, List

from snn_cosa.model.constants import _A, VAR_VMEM
from snn_cosa.nocsim.schedule.decode import Schedule
from snn_cosa.parsers.layer import SNNProb

from . import ArchComputeModel, ComputeCycles, NodeTileSpec


def _dim_totals(loops) -> Dict[int, int]:
    """Return {dim: product-of-all-factors} for every dim that appears in loops."""
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


class DenseStaticComputeModel(ArchComputeModel):
    def __init__(self, schedule: Schedule, prob: SNNProb) -> None:
        self._schedule = schedule
        self._prob = prob

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        return None

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(
            mac_cycles=self._pe_cycles(),
            lif_cycles=self._lif_cycles(),
        )

    def _pe_cycles(self) -> int:
        noc_t = _dim_totals(self._schedule.noc_temporal_loops)
        dram_t = _dim_totals(self._schedule.dram_temporal_loops)
        cycles = 1
        for j, factors in enumerate(self._prob.prob_factors):
            total_j = reduce(operator.mul, factors, 1)
            above_j = (
                self._schedule.spatial_factors[j]
                * noc_t.get(j, 1)
                * dram_t.get(j, 1)
            )
            node_j = total_j // above_j
            cycles *= max(node_j, 1)
        return cycles

    def _lif_cycles(self) -> int:
        noc_t = _dim_totals(self._schedule.noc_temporal_loops)
        dram_t = _dim_totals(self._schedule.dram_temporal_loops)
        cycles = 1
        for j, factors in enumerate(self._prob.prob_factors):
            if _A[j][VAR_VMEM] == 0:
                continue
            total_j = reduce(operator.mul, factors, 1)
            above_j = (
                self._schedule.spatial_factors[j]
                * noc_t.get(j, 1)
                * dram_t.get(j, 1)
            )
            node_j = total_j // above_j
            cycles *= max(node_j, 1)
        return cycles
```

- [x] **Step 2: Write the equivalence check script**

`/tmp/verify_dense_equivalence.py` (scratch, not committed):
```python
import pathlib
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels.dense import DenseStaticComputeModel
from snn_cosa.nocsim.combine import _pe_cycles, _lif_cycles
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.parsers.layer import SNNProb
import json

prob = SNNProb("configs/workloads/sample_snn_layer.yaml")
result = json.loads(pathlib.Path("outputs/sample_schedule.json").read_text())
schedule = schedule_from_strategy(result["strategy"], prob)

old_mac, old_lif = _pe_cycles(schedule, prob), _lif_cycles(schedule, prob)
model = DenseStaticComputeModel(schedule, prob)
new = model.compute_cycles(model.format_input(None, None), None)

assert new.mac_cycles == old_mac, (new.mac_cycles, old_mac)
assert new.lif_cycles == old_lif, (new.lif_cycles, old_lif)
print(f"OK: mac_cycles={new.mac_cycles} lif_cycles={new.lif_cycles} (matches old formula)")
```

- [x] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_dense_equivalence.py`
Expected: `OK: mac_cycles=<N> lif_cycles=<M> (matches old formula)` (exits 0,
no `AssertionError`). If `outputs/sample_schedule.json` doesn't exist,
regenerate it first:
```bash
PYTHONPATH=src python3 -m snn_cosa solve \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/snn_arch.yaml \
  --mapspace configs/mapspace/mapspace.yaml \
  --out outputs/sample_schedule.json
```

- [x] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/`
Stop here for review/comment.

---

## Task 4: Wire `DenseStaticComputeModel` into `combine.py` (regression-checked)

**Files:**
- Modify: `src/snn_cosa/nocsim/combine.py`

**Interfaces:**
- Consumes: `DenseStaticComputeModel` from Task 3, `ArchComputeModel` from
  Task 2.
- Produces: `combine(..., compute_model: Optional[ArchComputeModel] = None)`
  — consumed by a later plan wiring real per-tile models in.

- [x] **Step 1: Capture the pre-change baseline**

```bash
export PYTHONPATH=src
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/single_node_schedule.json \
  --layer configs/workloads/sim_demo.yaml \
  --arch configs/arch/snn_arch_single_node.yaml \
  --out /tmp/baseline_tc.csv --simulate
```
(If `outputs/single_node_schedule.json` doesn't exist yet, generate it
first: `python3 -m snn_cosa solve --layer configs/workloads/sim_demo.yaml
--arch configs/arch/snn_arch_single_node.yaml --mapspace
configs/mapspace/mapspace.yaml --out outputs/single_node_schedule.json`.)
Record the printed `transactions`, `dram_cost` per variable, and
`total_cycles`/`count_cycles`/`dram_cycles` — this is the "before" number
set.

- [x] **Step 2: Modify `combine.py`**

Add the import (near the top, with the other `from .schedule...` imports):
```python
from snn_cosa.archmodels import ArchComputeModel
from snn_cosa.archmodels.dense import DenseStaticComputeModel
```

Delete the two free functions `_pe_cycles` (lines 102-119) and
`_lif_cycles` (lines 122-138) — their logic now lives in
`DenseStaticComputeModel`.

Change the `combine()` signature (currently at line 158-165):
```python
def combine(
    schedule:  Schedule,
    bs:        BufSpatial,
    si:        StepInfo,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
) -> TC_Generator:
```
(add one line to the docstring's Args section: `compute_model: Optional
per-architecture cycle model. None (default) uses
DenseStaticComputeModel, exactly reproducing today's static formula.`)

Change the cycle-count section (currently lines 200-202,
`mac_cyc = _pe_cycles(schedule, prob)` / `lif_cyc = _lif_cycles(schedule, prob)`):
```python
    # ── 2. Pre-compute cycle counts ───────────────────────────────────────
    model = compute_model or DenseStaticComputeModel(schedule, prob)
    cycles = model.compute_cycles(model.format_input(None, None), None)
    mac_cyc, lif_cyc = cycles.mac_cycles, cycles.lif_cycles
```

- [x] **Step 3: Wire `compute_model` through `sim.py`'s programmatic API**

In `src/snn_cosa/nocsim/sim.py`, add the import:
```python
from snn_cosa.archmodels import ArchComputeModel
```
Add `compute_model: Optional[ArchComputeModel] = None` as the last
parameter to both `run()` (currently ending `arch: Optional[SNNArch] =
None,`) and `run_from_json()` (same), and pass it straight through to
`combine(schedule, bs, si, prob, bitwidths, arch=arch,
compute_model=compute_model)` in both. The CLI (`main()`) is unaffected —
it never passes `compute_model`, so it keeps using the default.

- [x] **Step 4: Re-run the exact Step-1 command and diff**

```bash
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/single_node_schedule.json \
  --layer configs/workloads/sim_demo.yaml \
  --arch configs/arch/snn_arch_single_node.yaml \
  --out /tmp/after_tc.csv --simulate
diff /tmp/baseline_tc.csv /tmp/after_tc.csv
```
Expected: `diff` produces no output (files identical), and every printed
number (`transactions`, `dram_cost` per variable, `total_cycles`,
`count_cycles`, `dram_cycles`) matches Step 1 exactly.

- [x] **Step 5: Present for review**

Run: `git diff src/snn_cosa/nocsim/combine.py src/snn_cosa/nocsim/sim.py`
Show the full diff plus the Step 4 `diff` output (empty). Stop here for
review/comment.

---

## Task 5: SpinalFlow `reconstruct_tile_sequence` — verified against real LoAS trace

**Files:**
- Create: `src/snn_cosa/archmodels/spinalflow/__init__.py`
- Create: `src/snn_cosa/archmodels/spinalflow/reconstruct.py`

**Interfaces:**
- Consumes: `NodeTileSpec` from Task 2; `snn_cosa.parsers.layer.{DIM_KH,
  DIM_KW, DIM_CIN, DIM_COUT, DIM_HO, DIM_WO, DIM_T}` (pre-existing).
- Produces: `reconstruct_tile_sequence(trace, tile) -> List[Tuple[int,int,int,int]]`
  (each tuple is `(t, cin, kh, kw)`) — consumed by Task 6 and Task 7.

- [x] **Step 1: Write `spinalflow/__init__.py`**

```python
"""SpinalFlow ArchComputeModel plugin -- Phase 1 pilot.

Reconstructs SpinalFlow's per-tile spike "spine" from a real trace
(reconstruct.py), then derives MAC cycle count (cycles.py) and the ordered
weight-address stream (address.py) from it. Standalone-verified against a
real captured LoAS trace (input_trace/loas/) used purely as sample spike
data -- LoAS's own accelerator dataflow is not modeled here.
"""
```

- [x] **Step 2: Write `reconstruct.py`**

```python
"""Builds SpinalFlow's per-tile spike sequence from a real spike trace.

SpinalFlow packs a tile's receptive field into a "spine": every neuron
that actually spiked in this tile's (t, kh, kw, cin) window, in
chronological order (t outermost). Unlike a dense 0/1 vector, only real
spike events are kept -- this is the input to event_to_cycle (cycle count
= spine length) and event_to_address (one weight burst per spine event).

Assumes batch=0 and stride=1/no-padding convolution (hin = ho + kh,
win = wo + kw), matching the reference SpinalFlow tile-computation
(neuro_cache/sim/compute/spinalflow_compute.py's _receptive_field).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T

from .. import NodeTileSpec


def reconstruct_tile_sequence(
    trace: np.ndarray, tile: NodeTileSpec
) -> List[Tuple[int, int, int, int]]:
    """Return this tile's spike events as (t, cin, kh, kw), t-chronological.

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

    events: List[Tuple[int, int, int, int]] = []
    for t in range(t_off, t_off + t_n):
        for kh in range(kh_n):
            for kw in range(kw_n):
                hin = ho + kh
                win = wo + kw
                for cin in range(cin_off, cin_off + cin_n):
                    if trace[t, batch, cin, hin, win]:
                        events.append((t, cin, kh, kw))
    return events
```

- [x] **Step 3: Write the verification script**

`/tmp/verify_spinalflow_reconstruct.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.spinalflow.reconstruct import reconstruct_tile_sequence
from snn_cosa.parsers.layer import DIM_CIN, DIM_HO, DIM_KH, DIM_KW, DIM_T

trace = np.load("input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy")
assert trace.shape == (4, 1, 64, 32, 32), trace.shape

tile = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_CIN: 64, DIM_T: 4},
    tile_offset={DIM_HO: 0, DIM_WO: 0},
    is_last_K=True,
)
events = reconstruct_tile_sequence(trace, tile)

# Independently-computed expected spike count over the same window.
window = trace[0:4, 0, 0:64, 0:3, 0:3]
expected_count = int(window.sum())

assert len(events) == expected_count, (len(events), expected_count)

ts = [e[0] for e in events]
assert ts == sorted(ts), "events must be chronologically sorted by t"

for t, cin, kh, kw in events:
    assert trace[t, 0, cin, kh, kw] == 1, "every returned event must be a real spike"

print(f"OK: {len(events)} spike events reconstructed, matches independent count "
      f"({expected_count}), chronologically sorted, all verified as real spikes")
```

- [x] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_spinalflow_reconstruct.py`
Expected: `OK: <N> spike events reconstructed, matches independent count
(<N>), chronologically sorted, all verified as real spikes` (`N` will be
some positive integer under ~17% of `4*64*3*3=2304`, matching the trace's
overall ~17.3% spike rate — i.e. roughly 300-450).

- [x] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/spinalflow/`
Stop here for review/comment.

---

## Task 6: SpinalFlow `event_to_cycle`

**Files:**
- Create: `src/snn_cosa/archmodels/spinalflow/cycles.py`

**Interfaces:**
- Consumes: the `List[Tuple[int,int,int,int]]` event list from Task 5.
- Produces: `event_to_cycle(events, tile) -> int` — consumed by Task 7's
  sibling module and (later, out of scope here) a `SpinalFlowComputeModel`
  that implements the full `ArchComputeModel` Protocol.

- [x] **Step 1: Write `cycles.py`**

```python
"""SpinalFlow MAC cycle count: one spike event = one cycle.

SpinalFlow's PE array processes exactly one spine entry per cycle -- the
reconstruction in reconstruct.py already flattened time and dropped
non-spikes, so cycle count is simply the reconstructed event count.
"""

from __future__ import annotations

from typing import List, Tuple

from .. import NodeTileSpec


def event_to_cycle(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> int:
    return len(events)
```

- [x] **Step 2: Verify**

Run:
```bash
cd /home/yy/projects/snn_cosa && PYTHONPATH=src python3 -c "
from snn_cosa.archmodels.spinalflow.cycles import event_to_cycle
events = [(0,1,0,0), (0,2,0,1), (1,5,1,0)]
assert event_to_cycle(events, None) == 3
print('ok')
"
```
Expected: `ok`

- [x] **Step 3: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/spinalflow/cycles.py`
Stop here for review/comment.

---

## Task 7: SpinalFlow `event_to_address`

**Files:**
- Create: `src/snn_cosa/archmodels/spinalflow/address.py`

**Interfaces:**
- Consumes: the event list from Task 5, `NodeTileSpec` from Task 2,
  `snn_cosa.parsers.layer.DIM_COUT`.
- Produces: `event_to_address(events, tile) -> List[Tuple[int,int,int,int,int]]`
  (each tuple `(kh, kw, cin, cout_start, cout_end)`) — this is the ordered
  weight-address stream the (future, out of scope) locality analyzer will
  consume.

- [x] **Step 1: Write `address.py`**

```python
"""SpinalFlow weight address per spike event.

A spike at receptive-field position (kh, kw) and input channel cin
requires exactly one weight burst: the fixed (kh, kw, cin) reduction
index, contiguous across this tile's full output-channel range
(SpinalFlow's 128-wide PE array reads all output channels for a given
input in one burst). One address per event, same order as the input
event list (already t-chronological from reconstruct.py).
"""

from __future__ import annotations

from typing import List, Tuple

from snn_cosa.parsers.layer import DIM_COUT

from .. import NodeTileSpec


def event_to_address(
    events: List[Tuple[int, int, int, int]], tile: NodeTileSpec
) -> List[Tuple[int, int, int, int, int]]:
    cout_off = tile.tile_offset.get(DIM_COUT, 0)
    cout_n = tile.node_bound[DIM_COUT]
    return [
        (kh, kw, cin, cout_off, cout_off + cout_n)
        for (_t, cin, kh, kw) in events
    ]
```

- [x] **Step 2: Verify**

Run:
```bash
cd /home/yy/projects/snn_cosa && PYTHONPATH=src python3 -c "
from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.spinalflow.address import event_to_address
from snn_cosa.parsers.layer import DIM_COUT

tile = NodeTileSpec(dram_i=0, node_bound={DIM_COUT: 128}, tile_offset={DIM_COUT: 0}, is_last_K=True)
events = [(0,1,0,0), (0,2,0,1), (1,5,1,0)]
addrs = event_to_address(events, tile)
assert addrs == [(0,0,1,0,128), (0,1,2,0,128), (1,0,5,0,128)], addrs
print('ok')
"
```
Expected: `ok`

- [x] **Step 3: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/spinalflow/address.py`
Stop here — this completes the plan. Full `SpinalFlowComputeModel`
(implementing `ArchComputeModel` end-to-end, wired into `combine()`'s live
per-tile loop via a `NodeTileSpec` derived from the solved schedule) is
the next plan, deferred per the Global Constraints section above.

---

## Self-review notes

- **Spec coverage:** all in-scope items from the 2026-07-12 design doc are
  covered (input_trace copy, locality placeholder, archmodels skeleton,
  dense fallback wired with regression check, SpinalFlow
  reconstruct/cycles/address). `capture/` and live `combine()` per-tile
  wiring are explicitly out of scope per that same doc / this plan's
  Global Constraints.
- **No placeholders:** every step has complete, runnable code and an exact
  verification command with expected output.
- **Type consistency:** `NodeTileSpec`, `ComputeCycles`, `ArchComputeModel`
  (Task 2) are used identically in Tasks 3, 5, 6, 7. Event tuples are
  consistently `(t, cin, kh, kw)` from Task 5 through Tasks 6-7. Address
  tuples are consistently `(kh, kw, cin, cout_start, cout_end)`.
