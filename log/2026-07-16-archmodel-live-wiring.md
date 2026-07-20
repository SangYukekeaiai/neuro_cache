# Live combine() wiring for the 5 arch models — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note:** per the SpinalFlow/PTB/LoAS/GustavSNN/Prosperity pilots'
> established convention, treat every task as its own checkpoint — present
> the diff for review at the end of each task rather than auto-committing
> (commit only when the user explicitly asks). If executed via
> subagent-driven-development instead, that skill's commit-per-task ledger
> mechanism applies instead — confirm with the user which mode before
> starting.

## Spec (rephrased)

Full design: `docs/superpowers/specs/2026-07-16-archmodel-live-wiring-locality-design.md`.

All 5 completed arch models (SpinalFlow, PTB, LoAS, GustavSNN, Prosperity)
have standalone, verified `reconstruct_tile_sequence`/`event_to_cycle`/
`event_to_address` trios, but none are wired into `combine()`'s live loop
— `combine.py` still calls a compute model exactly **once per run**,
upfront, using `tile=None`. This plan:

1. Adds `iter_node_tiles()`, deriving a real per-`dram_i` `NodeTileSpec`
   from a solved `Schedule` (new — no such helper exists today).
2. Extends `ArchComputeModel` with `weight_addresses()` (needed by the
   separate locality-analyzer plan, not by `combine.py` itself).
3. Adds one `<Arch>ComputeModel` class per architecture (thin Protocol
   wrappers over already-verified functions — no new per-arch algorithm
   work).
4. Restructures `combine.py` to call the model **once per `dram_i`**
   (not once per run) when `arch.single_node` is set, threading a real
   spike trace through `run()`/`run_from_json()`.
5. Verifies all of the above against **28 real captured trace layers**
   (12 from `vgg16_T4_B1/` minus 3 structurally-too-small ones, 19 from
   `resnet19_T4_B1/`), each driven through a **freshly-built** workload
   YAML derived directly from `meta.json` (the pre-existing
   `configs/workloads/generated/` YAMLs do NOT match these trace shapes —
   see spec's Design §4 for why).

**Goal:** every `dram_i` tile's `mac_cycles`/weight addresses come from
the real captured spike data, for all 5 architectures, with zero
regression on every non-single_node or no-real-model call path.

**Architecture:** one new tile-derivation helper
(`nocsim/schedule/tiles.py`), one Protocol extension + 5 thin wrapper
classes (`archmodels/<arch>/model.py`), one new trace/workload-generation
module (`archmodels/trace.py`), and a surgical `combine.py`/`sim.py`
change that only takes the new code path when `arch.single_node` is set.

**Tech Stack:** Python 3, numpy, PyYAML, Gurobi (via the existing
`solve_schedule()`), existing `snn_cosa` stack. No pytest in this repo —
verification runs scripts and checks exact printed/saved output, per
existing convention.

## Global Constraints

- **Zero regression, always.** Every code path that existed before this
  plan (non-`single_node` combine() calls; `single_node` calls with
  `compute_model=None`) must produce byte-identical output to before.
- **KH=KW=3, stride-1, no padding** is the blanket convolution-shape
  assumption already stated in every arch's `reconstruct_tile_sequence`
  docstring — this plan makes it explicit at the workload-YAML level too
  (`build_workload_from_trace`), applied uniformly, including to
  ResNet's 1x1-in-reality "shortcut" layers (no kernel-size ground truth
  exists in `meta.json` to special-case them).
- **3 of the 12 vgg16 layers are excluded** (`layer_10/11/12_features_*`,
  `Hin=Win=2`, too small for a 3x3 no-pad receptive field) — 28 layers
  swept, not 31.
- **`NodeTileSpec.node_bound[dim]` must NOT divide out `spatial_factors`**
  — it describes real-trace residency width (what `reconstruct_tile_
  sequence` slices, what `address.py`'s burst spans), not a cycle-count
  divisor. Only `dram_temporal`'s total belongs in the divisor. See the
  spec's Design §1 for the full derivation (this differs from
  `archmodels.dense.DenseStaticComputeModel`'s own `node_j`, which
  divides out `spatial_factors` too — that's correct for ITS purpose,
  wrong for this one).
- No new third-party dependencies.
- Out of scope: Phi (nothing built yet), any new trace capture, the
  locality analyzer itself (separate plan, depends on this one), any
  general joint-dimension spatial-cap MIP mechanism.

---

## Task 1: `iter_node_tiles()` — per-`dram_i` tile derivation

**Files:**
- Create: `src/snn_cosa/nocsim/schedule/tiles.py`

**Interfaces:**
- Consumes: `Schedule`/`LoopItem` from `nocsim/schedule/decode.py`
  (pre-existing); `StepInfo`/`_decode_dim` from `nocsim/schedule/steps.py`
  (pre-existing — `_decode_dim` is private, reused directly rather than
  re-derived, see code comment); `SNNProb` from `parsers/layer.py`
  (pre-existing); `NodeTileSpec` from `archmodels/__init__.py`
  (pre-existing).
- Produces: `iter_node_tiles(schedule, prob) -> Iterator[NodeTileSpec]` —
  consumed by Task 5's `combine.py` change and by the separate locality-
  analyzer plan.

- [ ] **Step 1: Write `tiles.py`**

```python
"""Derives one real NodeTileSpec per dram_i from a solved Schedule.

For a single_node arch, NoCLevel is empty/irrelevant and every node visit
is fully resident at NodeLevel EXCEPT whatever the MIP pushed to DRAM --
so node_bound[dim] (the width this dim occupies at every node visit,
INCLUDING both spatial fanout and any leftover NodeLevel-temporal
multiplier) is simply the dimension's total divided by whatever fraction
of it was pushed to DRAM-temporal:

    node_bound[dim] = total[dim] // dram_temporal_total[dim]

This differs from archmodels.dense.DenseStaticComputeModel's node_j,
which ADDITIONALLY divides out spatial_factors[dim] and any NoC-temporal
factor -- appropriate there because spatial fanout across PEs doesn't
cost extra MAC cycles, but wrong here: NodeTileSpec.node_bound must
describe the tile's actual real-trace RESIDENCY width -- what
reconstruct_tile_sequence slices out of the trace, and what address.py's
burst spans (e.g. SpinalFlow's burst covers the tile's "whole assigned
output-channel range" -- the full spatial width, not 1 per PE). Tracing
through PTB's `active_rows = min(tile.node_bound[DIM_COUT], PE_ROWS_MAX)`
and every arch's existing "COUT costs zero/clamped cycles regardless of
magnitude" convention confirms this: node_bound[dim] must include the
full spatial fanout, dividing out ONLY whatever the MIP actually pushed
to DRAM for that dim.

tile_offset[dim] only varies across dims that appear in
schedule.dram_temporal_loops -- the only thing that changes from one node
visit to the next for a single_node arch (NodeLevel/NoCLevel factors are
the same resident block on every visit).
"""

from __future__ import annotations

import operator
from functools import reduce
from typing import Dict, Iterator, List

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.parsers.layer import SNNProb

from .decode import Schedule
from .steps import StepInfo, _decode_dim  # _decode_dim is private to steps.py --
# reused directly rather than re-deriving its mixed-radix decoding a second
# time (matches this codebase's tolerance for a tiny private cross-module
# import over duplicating nontrivial logic; see combine.py's/dense.py's own
# duplicated _dim_totals one-liner for the opposite, "duplicate the trivial
# stuff" convention this module also follows below).


def _dim_totals(loops) -> Dict[int, int]:
    """Return {dim: product-of-all-factors} for every dim that appears in loops.

    Local copy matching combine.py's/dense.py's own copies of this
    one-liner -- this codebase's existing convention for tiny per-module
    helpers rather than a shared cross-module import.
    """
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


def iter_node_tiles(schedule: Schedule, prob: SNNProb) -> Iterator[NodeTileSpec]:
    """Yield one NodeTileSpec per dram_i, in solved-schedule order.

    Args:
        schedule: decoded Schedule (from decode() or schedule_from_strategy()).
        prob:     parsed SNN layer (prob.prob_factors gives each dim's total
                  as a prime-factor list).

    Yields:
        NodeTileSpec(dram_i, node_bound, tile_offset, is_last_K), one per
        dram_i in [0, schedule.dram_num_steps).
    """
    si = StepInfo(schedule, prob)
    dram_t = _dim_totals(schedule.dram_temporal_loops)

    node_bound: Dict[int, int] = {}
    for j, factors in enumerate(prob.prob_factors):
        total_j = reduce(operator.mul, factors, 1)
        node_bound[j] = max(total_j // dram_t.get(j, 1), 1)

    dram_dims: List[int] = []
    for item in schedule.dram_temporal_loops:
        if item.dim not in dram_dims:
            dram_dims.append(item.dim)

    for dram_i in range(schedule.dram_num_steps):
        tile_offset = {
            j: _decode_dim(dram_i, schedule.dram_temporal_loops, j) * node_bound[j]
            for j in dram_dims
        }
        _, is_last_K = si.dram_k_position(dram_i)
        yield NodeTileSpec(
            dram_i=dram_i,
            node_bound=dict(node_bound),
            tile_offset=tile_offset,
            is_last_K=is_last_K,
        )
```

- [ ] **Step 2: Write the verification script**

`/tmp/verify_iter_node_tiles.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import pathlib
import tempfile

import yaml

from snn_cosa.nocsim.schedule.decode import LoopItem, Schedule
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.layer import SNNProb, DIM_HO, DIM_WO, DIM_COUT, DIM_CIN, DIM_KH, DIM_KW, DIM_T

# --- Build a tiny hand-crafted problem: KH=2,KW=1,CIN=1,COUT=4,HO=2,WO=2,T=4
problem = {"problem": {"KH": 2, "KW": 1, "CIN": 1, "COUT": 4, "HO": 2, "WO": 2, "T": 4}}
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.safe_dump(problem, f)
    prob_path = f.name
prob = SNNProb(pathlib.Path(prob_path))

# --- Case A: COUT spatially pinned to the full 4 (no leftover); HO/WO barred
# to DRAM (SpinalFlow/PTB/LoAS-style) -- KH/KW/CIN/T fully resident.
schedule_a = Schedule(
    spatial_factors={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 1, DIM_COUT: 4, DIM_HO: 1, DIM_WO: 1, DIM_T: 1},
    noc_temporal_loops=[],
    dram_temporal_loops=[
        LoopItem(dim=DIM_HO, dim_name="HO", factor=2, level=8),
        LoopItem(dim=DIM_WO, dim_name="WO", factor=2, level=9),
    ],
    data_size={},
    gb_start=1, dram_start=8, perm_levels=7,
)
tiles_a = list(iter_node_tiles(schedule_a, prob))
assert len(tiles_a) == schedule_a.dram_num_steps == 4, len(tiles_a)
for t in tiles_a:
    assert t.node_bound == {
        DIM_KH: 2, DIM_KW: 1, DIM_CIN: 1, DIM_COUT: 4, DIM_HO: 1, DIM_WO: 1, DIM_T: 4,
    }, t.node_bound  # HO/WO fully barred -> node_bound=1 each; COUT fully spatial -> node_bound=4 (full width, NOT 1)
offsets_a = sorted((t.tile_offset[DIM_HO], t.tile_offset[DIM_WO]) for t in tiles_a)
assert offsets_a == [(0, 0), (0, 1), (1, 0), (1, 1)], offsets_a  # HO inner (level 8 < WO's level 9)
print(f"Case A OK: 4 tiles, node_bound COUT=4 (full spatial width, not divided), "
      f"HO/WO offsets={offsets_a}")

# --- Case B: COUT's leftover pushed to DRAM (total=4, spatial cap pinned to 2)
# -- node_bound[COUT] must shrink to 2 (only the truly-resident slice), and
# tile_offset[COUT] must step by 2 across the 2 dram steps for that dim.
schedule_b = Schedule(
    spatial_factors={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 1, DIM_COUT: 2, DIM_HO: 1, DIM_WO: 1, DIM_T: 1},
    noc_temporal_loops=[],
    dram_temporal_loops=[
        LoopItem(dim=DIM_COUT, dim_name="COUT", factor=2, level=8),
    ],
    data_size={},
    gb_start=1, dram_start=8, perm_levels=7,
)
tiles_b = list(iter_node_tiles(schedule_b, prob))
assert len(tiles_b) == 2, len(tiles_b)
assert [t.node_bound[DIM_COUT] for t in tiles_b] == [2, 2]  # resident width shrinks to the spatial cap
assert [t.tile_offset[DIM_COUT] for t in tiles_b] == [0, 2]  # steps by the FULL resident width (2), not 1
print(f"Case B OK: COUT leftover pushed to DRAM -> node_bound[COUT]=2 (resident "
      f"slice, not 4), tile_offset steps [0, 2] (by the resident width, not 1)")

# --- Case C: is_last_K wiring -- KH is the only reduction dim varying at
# DRAM level (KW/CIN fixed at 1 -- trivially "last" always); confirm
# is_last_K flips True only at the final KH index.
schedule_c = Schedule(
    spatial_factors={DIM_KH: 1, DIM_KW: 1, DIM_CIN: 1, DIM_COUT: 4, DIM_HO: 1, DIM_WO: 1, DIM_T: 1},
    noc_temporal_loops=[],
    dram_temporal_loops=[LoopItem(dim=DIM_KH, dim_name="KH", factor=2, level=8)],
    data_size={},
    gb_start=1, dram_start=8, perm_levels=7,
)
tiles_c = list(iter_node_tiles(schedule_c, prob))
assert [t.is_last_K for t in tiles_c] == [False, True], [t.is_last_K for t in tiles_c]
print(f"Case C OK: is_last_K=[False, True] across the 2 KH dram steps")
```

- [ ] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_iter_node_tiles.py`
Expected:
```
Case A OK: 4 tiles, node_bound COUT=4 (full spatial width, not divided), HO/WO offsets=[(0, 0), (0, 1), (1, 0), (1, 1)]
Case B OK: COUT leftover pushed to DRAM -> node_bound[COUT]=2 (resident slice, not 4), tile_offset steps [0, 2] (by the resident width, not 1)
Case C OK: is_last_K=[False, True] across the 2 KH dram steps
```

- [ ] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/nocsim/schedule/tiles.py`
Stop here for review/comment.

---

## Task 2: `ArchComputeModel` Protocol gains `weight_addresses`

**Files:**
- Modify: `src/snn_cosa/archmodels/__init__.py`
- Modify: `src/snn_cosa/archmodels/dense.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ArchComputeModel.weight_addresses(packed, tile) -> List[Any]`
  — consumed by Task 4's 5 wrapper classes and by the separate locality-
  analyzer plan. `DenseStaticComputeModel.weight_addresses` returns `[]`
  always (no real address notion for the static formula).

- [ ] **Step 1: Add `weight_addresses` to the Protocol**

In `src/snn_cosa/archmodels/__init__.py`, change:
```python
from typing import Any, Dict, Optional, Protocol
```
to:
```python
from typing import Any, Dict, List, Optional, Protocol
```
and change:
```python
class ArchComputeModel(Protocol):
    """Per-architecture plugin, called once per node-level tile."""

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        """Slice/reconstruct this tile's real-trace-derived representation."""
        ...

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        """Derive this tile's (mac_cycles, lif_cycles) from format_input's output."""
        ...
```
to:
```python
class ArchComputeModel(Protocol):
    """Per-architecture plugin, called once per node-level tile."""

    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any:
        """Slice/reconstruct this tile's real-trace-derived representation."""
        ...

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        """Derive this tile's (mac_cycles, lif_cycles) from format_input's output."""
        ...

    def weight_addresses(self, packed: Any, tile: NodeTileSpec) -> List[Any]:
        """Ordered weight addresses this tile touches (this arch's own
        address.py::event_to_address, wrapped). Not consumed by combine.py's
        transaction generator (which still uses byte-size accounting) --
        exists so the locality analyzer has one per-arch entry point for
        both timing and addressing, instead of reaching around the
        Protocol into each arch's raw address.py function.
        """
        ...
```

- [ ] **Step 2: Add the no-op implementation to `DenseStaticComputeModel`**

In `src/snn_cosa/archmodels/dense.py`, change:
```python
from typing import Any, Dict
```
to:
```python
from typing import Any, Dict, List
```
and add, right after `compute_cycles`:
```python
    def weight_addresses(self, packed: Any, tile: NodeTileSpec) -> List[Any]:
        return []
```

- [ ] **Step 3: Write the verification script**

`/tmp/verify_weight_addresses_protocol.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels.dense import DenseStaticComputeModel
from snn_cosa.parsers.layer import SNNProb
from snn_cosa.nocsim.schedule.decode import Schedule

# Minimal fixture -- only checking weight_addresses' return shape, not the
# rest of DenseStaticComputeModel's (unrelated, already-verified) formula.
import pathlib, tempfile, yaml
problem = {"problem": {"KH": 1, "KW": 1, "CIN": 1, "COUT": 1, "HO": 1, "WO": 1, "T": 1}}
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.safe_dump(problem, f)
    prob_path = f.name
prob = SNNProb(pathlib.Path(prob_path))
schedule = Schedule(
    spatial_factors={j: 1 for j in range(7)}, noc_temporal_loops=[], dram_temporal_loops=[],
    data_size={}, gb_start=1, dram_start=8, perm_levels=7,
)
model = DenseStaticComputeModel(schedule, prob)
assert model.weight_addresses(None, None) == []
print("OK: DenseStaticComputeModel.weight_addresses(None, None) == []")
```

- [ ] **Step 4: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_weight_addresses_protocol.py`
Expected: `OK: DenseStaticComputeModel.weight_addresses(None, None) == []`

- [ ] **Step 5: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/__init__.py src/snn_cosa/archmodels/dense.py`
Stop here for review/comment.

---

## Task 3: `archmodels/trace.py` — trace loading + per-layer workload generation

**Files:**
- Create: `src/snn_cosa/archmodels/trace.py`

**Interfaces:**
- Consumes: nothing new (numpy, PyYAML, stdlib json/pathlib).
- Produces: `load_layer_trace(trace_dir, layer_name) -> np.ndarray`,
  `build_workload_from_trace(meta, layer_name, next_cin=None) -> Dict` —
  consumed by Task 6's sweep script.

- [ ] **Step 1: Write `trace.py`**

```python
"""Loads real captured spike traces and builds matching workload problem
dicts directly from their metadata.

input_trace/loas/<workload>/ holds one meta.json (layer name -> real
input-tensor shape [T, B, Cin, Hin, Win]) plus one <layer_name>.npy per
captured layer, binary float32. No such loader existed before this -- the
5 arch pilots' own verification scripts each called np.load ad hoc.

The pre-existing configs/workloads/generated/{vgg16,resnet19}/T4/*.yaml
workloads do NOT match these captured layers' real shapes (checked
directly: vgg16's generated YAMLs are ImageNet-scale 224x224/CIN-from-3,
while the captured trace is CIFAR-scale 32x32/CIN-from-64, matching the
source paper's own "VGG 9" figure caption, not full VGG16; resnet19's
generated YAMLs use a different channel-width base than the trace too).
build_workload_from_trace() replaces resolving against that directory --
it derives a fresh, trace-matching workload directly from meta.json.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional

import numpy as np

KH = KW = 3  # blanket assumption, matching every archmodel's own
             # reconstruct_tile_sequence docstring: stride-1, no padding.


def load_layer_trace(trace_dir: pathlib.Path, layer_name: str) -> np.ndarray:
    """Load one captured layer's trace, e.g. trace_dir=input_trace/loas/vgg16_T4_B1.

    Args:
        trace_dir: directory containing meta.json + <layer_name>.npy.
        layer_name: e.g. "layer_01_features_3" (a meta.json "layers" key).

    Returns:
        Binary float32 array, shape [T, B, Cin, Hin, Win] (per meta.json).

    Raises:
        FileNotFoundError: if meta.json or the .npy file is missing.
        ValueError: if the loaded array's shape doesn't match meta.json.
    """
    trace_dir = pathlib.Path(trace_dir)
    meta_path = trace_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"load_layer_trace: no meta.json at {meta_path}")
    with open(meta_path) as fh:
        meta = json.load(fh)
    if layer_name not in meta["layers"]:
        raise ValueError(
            f"load_layer_trace: '{layer_name}' not in {meta_path}'s layers "
            f"(available: {sorted(meta['layers'])})"
        )
    npy_path = trace_dir / f"{layer_name}.npy"
    if not npy_path.exists():
        raise FileNotFoundError(f"load_layer_trace: no .npy at {npy_path}")
    trace = np.load(npy_path)
    expected_shape = tuple(meta["layers"][layer_name])
    if trace.shape != expected_shape:
        raise ValueError(
            f"load_layer_trace: {npy_path} has shape {trace.shape}, "
            f"meta.json declares {expected_shape}"
        )
    return trace


def valid_layer_names(meta: Dict[str, Any]) -> List[str]:
    """Return meta['layers'] keys whose Hin/Win support a KHxKW=3x3 no-pad
    receptive field (HO=Hin-2>=1, WO=Win-2>=1), in meta.json's own order.

    Excludes any layer too spatially small for this project's blanket
    convolution-shape assumption (e.g. vgg16_T4_B1's last 3 layers,
    Hin=Win=2) -- a real incompatibility, not a bug to work around.
    """
    names = []
    for name, (_t, _b, _cin, hin, win) in meta["layers"].items():
        if hin - (KH - 1) >= 1 and win - (KW - 1) >= 1:
            names.append(name)
    return names


def build_workload_from_trace(
    meta: Dict[str, Any], layer_name: str, next_cin: Optional[int] = None
) -> Dict[str, Any]:
    """Build a {"problem": {...}} dict for one captured layer, derived
    directly from meta.json -- KH=KW=3, stride-1, no padding.

    Args:
        meta:      the parsed meta.json dict.
        layer_name: e.g. "layer_01_features_3".
        next_cin:  the NEXT captured layer's CIN (this layer's real COUT,
                   since meta.json's "layers" dict is network-sequential --
                   layer i's output channels = layer i+1's input channels).
                   None (the last captured layer in a model) falls back to
                   reusing this layer's own CIN as COUT.

    Returns:
        {"problem": {"KH":3, "KW":3, "CIN":.., "COUT":.., "HO":.., "WO":..,
        "T":.., "shape": "snn-layer"}}, ready to write to a YAML file and
        pass to SNNProb.

    Raises:
        ValueError: if this layer's Hin/Win are too small for KH=KW=3
                    (use valid_layer_names() to filter these out first).
    """
    t, _b, cin, hin, win = meta["layers"][layer_name]
    ho, wo = hin - (KH - 1), win - (KW - 1)
    if ho < 1 or wo < 1:
        raise ValueError(
            f"build_workload_from_trace: '{layer_name}' has Hin={hin}/Win={win}, "
            f"too small for a {KH}x{KW} no-pad receptive field (HO={ho}, WO={wo})"
        )
    cout = next_cin if next_cin is not None else cin
    return {
        "problem": {
            "KH": KH, "KW": KW, "CIN": cin, "COUT": cout,
            "HO": ho, "WO": wo, "T": t, "shape": "snn-layer",
        }
    }
```

- [ ] **Step 2: Write the verification script**

`/tmp/verify_trace.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

import json
import pathlib

from snn_cosa.archmodels.trace import (
    build_workload_from_trace,
    load_layer_trace,
    valid_layer_names,
)

trace_dir = pathlib.Path("input_trace/loas/vgg16_T4_B1")
with open(trace_dir / "meta.json") as fh:
    meta = json.load(fh)

# --- valid_layer_names excludes exactly the 3 too-small vgg16 layers ------
names = valid_layer_names(meta)
assert len(names) == 9, (len(names), names)
excluded = set(meta["layers"]) - set(names)
assert excluded == {
    "layer_10_features_34", "layer_11_features_37", "layer_12_features_40",
}, excluded
print(f"OK: valid_layer_names excludes exactly {sorted(excluded)}")

# --- build_workload_from_trace matches the hand-derived table from the
# spec's investigation (layer_01: Hin=32,Cin=64 -> HO=30,CIN=64,
# COUT=64 inferred from layer_02's Cin=64) ---------------------------------
layer_names = list(meta["layers"])
i = layer_names.index("layer_01_features_3")
next_cin = meta["layers"][layer_names[i + 1]][2]
wl = build_workload_from_trace(meta, "layer_01_features_3", next_cin=next_cin)
assert wl == {
    "problem": {"KH": 3, "KW": 3, "CIN": 64, "COUT": 64, "HO": 30, "WO": 30, "T": 4, "shape": "snn-layer"}
}, wl
print(f"OK: layer_01_features_3 -> {wl['problem']}")

# --- last layer in the model falls back to COUT=own CIN -------------------
wl_last = build_workload_from_trace(meta, "layer_09_features_30")  # last VALID layer
assert wl_last["problem"]["COUT"] == wl_last["problem"]["CIN"] == 512, wl_last
print(f"OK: layer_09_features_30 (last valid vgg16 layer) falls back to COUT=CIN=512")

# --- too-small layer raises ------------------------------------------------
try:
    build_workload_from_trace(meta, "layer_10_features_34")
    raise AssertionError("expected ValueError")
except ValueError as exc:
    print(f"OK: layer_10_features_34 raises ValueError ({exc})")

# --- load_layer_trace round-trips against the real .npy -------------------
trace = load_layer_trace(trace_dir, "layer_01_features_3")
assert trace.shape == (4, 1, 64, 32, 32), trace.shape
print(f"OK: load_layer_trace loaded real shape {trace.shape}")
```

- [ ] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_trace.py`
Expected:
```
OK: valid_layer_names excludes exactly ['layer_10_features_34', 'layer_11_features_37', 'layer_12_features_40']
OK: layer_01_features_3 -> {'KH': 3, 'KW': 3, 'CIN': 64, 'COUT': 64, 'HO': 30, 'WO': 30, 'T': 4, 'shape': 'snn-layer'}
OK: layer_09_features_30 (last valid vgg16 layer) falls back to COUT=CIN=512
OK: layer_10_features_34 raises ValueError (build_workload_from_trace: 'layer_10_features_34' has Hin=2/Win=2, too small for a 3x3 no-pad receptive field (HO=0, WO=0))
OK: load_layer_trace loaded real shape (4, 1, 64, 32, 32)
```

- [ ] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/trace.py`
Stop here for review/comment.

---

## Task 4: Five `<Arch>ComputeModel` classes

**Files:**
- Create: `src/snn_cosa/archmodels/spinalflow/model.py`
- Create: `src/snn_cosa/archmodels/ptb/model.py`
- Create: `src/snn_cosa/archmodels/loas/model.py`
- Create: `src/snn_cosa/archmodels/gustavsnn/model.py`
- Create: `src/snn_cosa/archmodels/prosperity/model.py`

**Interfaces:**
- Consumes: each arch's own `reconstruct_tile_sequence`/`event_to_cycle`/
  `event_to_address` (all pre-existing, unmodified); `ArchComputeModel`/
  `ComputeCycles`/`NodeTileSpec` from `archmodels/__init__.py` (Task 2's
  `weight_addresses` addition).
- Produces: `SpinalFlowComputeModel`, `PTBComputeModel`, `LoASComputeModel`,
  `GustavSNNComputeModel`, `ProsperityComputeModel` — each implementing
  `ArchComputeModel` fully (`format_input`/`compute_cycles`/
  `weight_addresses`). Consumed by Task 6's sweep script.

- [ ] **Step 1: Write `spinalflow/model.py`**

```python
"""SpinalFlowComputeModel: ArchComputeModel Protocol wrapper.

Wires SpinalFlow's already-verified reconstruct_tile_sequence/
event_to_cycle/event_to_address trio (reconstruct.py/cycles.py/
address.py) behind the ArchComputeModel Protocol so it can be passed to
combine()/run()/run_from_json() as a real per-tile cycle-count model. No
new per-arch algorithm here -- pure plumbing over what the SpinalFlow
pilot already verified standalone.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import reconstruct_tile_sequence


class SpinalFlowComputeModel(ArchComputeModel):
    def format_input(
        self, trace: np.ndarray, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int]]:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)
```

- [ ] **Step 2: Write `ptb/model.py`**

```python
"""PTBComputeModel: ArchComputeModel Protocol wrapper.

Wires PTB's already-verified reconstruct_tile_sequence/event_to_cycle/
event_to_address trio behind the ArchComputeModel Protocol. No new
per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import PTBReconstructed, reconstruct_tile_sequence


class PTBComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> PTBReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)
```

- [ ] **Step 3: Write `loas/model.py`**

```python
"""LoASComputeModel: ArchComputeModel Protocol wrapper.

Wires LoAS's already-verified reconstruct_tile_sequence/event_to_cycle/
event_to_address trio behind the ArchComputeModel Protocol. No new
per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import LoASReconstructed, reconstruct_tile_sequence


class LoASComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> LoASReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)
```

- [ ] **Step 4: Write `gustavsnn/model.py`**

```python
"""GustavSNNComputeModel: ArchComputeModel Protocol wrapper.

Wires GustavSNN's already-verified reconstruct_tile_sequence/
event_to_cycle/event_to_address trio behind the ArchComputeModel
Protocol. No new per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import GustavReconstructed, reconstruct_tile_sequence


class GustavSNNComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> GustavReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)
```

- [ ] **Step 5: Write `prosperity/model.py`**

```python
"""ProsperityComputeModel: ArchComputeModel Protocol wrapper.

Wires Prosperity's already-verified reconstruct_tile_sequence/
event_to_cycle/event_to_address trio behind the ArchComputeModel
Protocol. No new per-arch algorithm here.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import numpy as np

from .. import ArchComputeModel, ComputeCycles, NodeTileSpec
from .address import event_to_address
from .cycles import event_to_cycle
from .reconstruct import ProsperityReconstructed, reconstruct_tile_sequence


class ProsperityComputeModel(ArchComputeModel):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> ProsperityReconstructed:
        return reconstruct_tile_sequence(trace, tile)

    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles:
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)

    def weight_addresses(
        self, packed: Any, tile: NodeTileSpec
    ) -> List[Tuple[int, int, int, int, int]]:
        return event_to_address(packed, tile)
```

- [ ] **Step 6: Write the verification script**

`/tmp/verify_compute_models.py` (scratch, not committed) — reuses each
arch's own real captured-trace tile from its existing pilot verification,
confirming the wrapper class produces IDENTICAL output to calling the
raw functions directly:
```python
import sys

sys.path.insert(0, "src")

import numpy as np

from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.spinalflow.reconstruct import reconstruct_tile_sequence as sf_reconstruct
from snn_cosa.archmodels.spinalflow.cycles import event_to_cycle as sf_cycle
from snn_cosa.archmodels.spinalflow.address import event_to_address as sf_address
from snn_cosa.archmodels.ptb.model import PTBComputeModel
from snn_cosa.archmodels.ptb.reconstruct import reconstruct_tile_sequence as ptb_reconstruct
from snn_cosa.archmodels.ptb.cycles import event_to_cycle as ptb_cycle
from snn_cosa.archmodels.ptb.address import event_to_address as ptb_address
from snn_cosa.archmodels.loas.model import LoASComputeModel
from snn_cosa.archmodels.loas.reconstruct import reconstruct_tile_sequence as loas_reconstruct
from snn_cosa.archmodels.loas.cycles import event_to_cycle as loas_cycle
from snn_cosa.archmodels.loas.address import event_to_address as loas_address
from snn_cosa.archmodels.gustavsnn.model import GustavSNNComputeModel
from snn_cosa.archmodels.gustavsnn.reconstruct import reconstruct_tile_sequence as gs_reconstruct
from snn_cosa.archmodels.gustavsnn.cycles import event_to_cycle as gs_cycle
from snn_cosa.archmodels.gustavsnn.address import event_to_address as gs_address
from snn_cosa.archmodels.prosperity.model import ProsperityComputeModel
from snn_cosa.archmodels.prosperity.reconstruct import reconstruct_tile_sequence as pr_reconstruct
from snn_cosa.archmodels.prosperity.cycles import event_to_cycle as pr_cycle
from snn_cosa.archmodels.prosperity.address import event_to_address as pr_address
from snn_cosa.parsers.layer import DIM_CIN, DIM_COUT, DIM_HO, DIM_KH, DIM_KW, DIM_T, DIM_WO

trace = np.load("input_trace/loas/vgg16_T4_B1/layer_01_features_3.npy")
assert trace.shape == (4, 1, 64, 32, 32)

# SpinalFlow / PTB / LoAS: HO/WO barred (one output pixel), KH/KW capped at 4,
# CIN/T fully resident.
tile_barred = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_CIN: 64, DIM_T: 4, DIM_COUT: 128},
    tile_offset={DIM_HO: 5, DIM_WO: 7, DIM_CIN: 0, DIM_T: 0, DIM_COUT: 0},
    is_last_K=True,
)

sf_model = SpinalFlowComputeModel()
sf_packed = sf_model.format_input(trace, tile_barred)
assert sf_packed == sf_reconstruct(trace, tile_barred)
assert sf_model.compute_cycles(sf_packed, tile_barred).mac_cycles == sf_cycle(sf_packed, tile_barred)
assert sf_model.compute_cycles(sf_packed, tile_barred).lif_cycles is None
assert sf_model.weight_addresses(sf_packed, tile_barred) == sf_address(sf_packed, tile_barred)
print(f"SpinalFlowComputeModel OK: {len(sf_packed)} events, "
      f"mac_cycles={sf_model.compute_cycles(sf_packed, tile_barred).mac_cycles}")

ptb_model = PTBComputeModel()
ptb_packed = ptb_model.format_input(trace, tile_barred)
assert ptb_packed == ptb_reconstruct(trace, tile_barred)
assert ptb_model.compute_cycles(ptb_packed, tile_barred).mac_cycles == ptb_cycle(ptb_packed, tile_barred)
assert ptb_model.weight_addresses(ptb_packed, tile_barred) == ptb_address(ptb_packed, tile_barred)
print(f"PTBComputeModel OK: {len(ptb_packed.lines_pass1)} pass1 lines, "
      f"mac_cycles={ptb_model.compute_cycles(ptb_packed, tile_barred).mac_cycles}")

# LoAS requires KH/KW/CIN/T fully resident -- reuse the same tile (already is).
loas_model = LoASComputeModel()
loas_packed = loas_model.format_input(trace, tile_barred)
assert loas_packed == loas_reconstruct(trace, tile_barred)
assert loas_model.compute_cycles(loas_packed, tile_barred).mac_cycles == loas_cycle(loas_packed, tile_barred)
assert loas_model.weight_addresses(loas_packed, tile_barred) == loas_address(loas_packed, tile_barred)
print(f"LoASComputeModel OK: bitmask popcount={sum(loas_packed.bitmask)}, "
      f"mac_cycles={loas_model.compute_cycles(loas_packed, tile_barred).mac_cycles}")

# GustavSNN: HO/WO node-resident (one tick), T barred (single absolute tick).
tile_gustav = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_CIN: 64, DIM_HO: 8, DIM_WO: 8, DIM_COUT: 8},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0, DIM_COUT: 0},
    is_last_K=True,
)
gs_model = GustavSNNComputeModel()
gs_packed = gs_model.format_input(trace, tile_gustav)
assert gs_packed == gs_reconstruct(trace, tile_gustav)
assert gs_model.compute_cycles(gs_packed, tile_gustav).mac_cycles == gs_cycle(gs_packed, tile_gustav)
assert gs_model.weight_addresses(gs_packed, tile_gustav) == gs_address(gs_packed, tile_gustav)
print(f"GustavSNNComputeModel OK: {len(gs_packed.submatrices)} submatrices, "
      f"mac_cycles={gs_model.compute_cycles(gs_packed, tile_gustav).mac_cycles}")

# Prosperity: HO/WO node-resident (one tick, one CIN channel).
tile_prosperity = NodeTileSpec(
    dram_i=0,
    node_bound={DIM_KH: 3, DIM_KW: 3, DIM_HO: 16, DIM_WO: 16, DIM_COUT: 128},
    tile_offset={DIM_HO: 0, DIM_WO: 0, DIM_CIN: 0, DIM_T: 0, DIM_COUT: 0},
    is_last_K=True,
)
pr_model = ProsperityComputeModel()
pr_packed = pr_model.format_input(trace, tile_prosperity)
assert pr_packed == pr_reconstruct(trace, tile_prosperity)
assert pr_model.compute_cycles(pr_packed, tile_prosperity).mac_cycles == pr_cycle(pr_packed, tile_prosperity)
assert pr_model.weight_addresses(pr_packed, tile_prosperity) == pr_address(pr_packed, tile_prosperity)
print(f"ProsperityComputeModel OK: {len(pr_packed.rows)} rows, "
      f"mac_cycles={pr_model.compute_cycles(pr_packed, tile_prosperity).mac_cycles}")
```

- [ ] **Step 5: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_compute_models.py`
Expected (exact event/line/cycle counts depend on the real trace's actual
spike content at this tile — report whatever the assertions confirm,
don't assume a specific number):
```
SpinalFlowComputeModel OK: <N> events, mac_cycles=<N>
PTBComputeModel OK: <N> pass1 lines, mac_cycles=<N>
LoASComputeModel OK: bitmask popcount=<N>, mac_cycles=<N>
GustavSNNComputeModel OK: 8 submatrices, mac_cycles=<N>
ProsperityComputeModel OK: 256 rows, mac_cycles=<N>
```

- [ ] **Step 6: Present for review**

Run: `git diff --stat src/snn_cosa/archmodels/*/model.py`
Stop here for review/comment.

---

## Task 5: `combine.py`/`sim.py` live wiring

**Files:**
- Modify: `src/snn_cosa/nocsim/combine.py`
- Modify: `src/snn_cosa/nocsim/sim.py`

**Interfaces:**
- Consumes: `iter_node_tiles` from Task 1; `ArchComputeModel` (unchanged
  call surface, `format_input`/`compute_cycles`) from Task 2/4.
- Produces: `combine(..., trace=None)` — new optional parameter;
  `run(..., trace=None)`/`run_from_json(..., trace=None)` — new optional
  parameter, passed straight through. All pre-existing call sites
  (`trace` omitted) are completely unaffected.

- [ ] **Step 1: Modify `combine.py`'s imports and signature**

In `src/snn_cosa/nocsim/combine.py`, change:
```python
from typing import Deque, Dict, List, Optional
```
to:
```python
from typing import Any, Deque, Dict, List, Optional
```
Add, after the existing `from snn_cosa.archmodels.dense import DenseStaticComputeModel` line:
```python
from snn_cosa.archmodels import NodeTileSpec
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
```
Change the `combine()` signature from:
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
to:
```python
def combine(
    schedule:  Schedule,
    bs:        BufSpatial,
    si:        StepInfo,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
    trace:     Optional[Any] = None,
) -> TC_Generator:
```
Add to the docstring's `Args:` section, after the `compute_model:` entry:
```
        trace:     Optional real spike trace (e.g. a numpy array, shape
                   [T, B, Cin, Hin, Win]), passed straight through to
                   compute_model.format_input() -- meaningless when
                   compute_model is None (DenseStaticComputeModel ignores
                   it) or when arch.single_node is not set (only
                   single_node schedules get a per-dram_i live model
                   call -- see below).
```

- [ ] **Step 2: Replace the one-shot cycle-count call with a per-`dram_i` live path**

Replace:
```python
    # ── 2. Pre-compute cycle counts ───────────────────────────────────────
    model = compute_model or DenseStaticComputeModel(schedule, prob)
    cycles = model.compute_cycles(model.format_input(None, None), None)
    mac_cyc = cycles.mac_cycles
    lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0
```
with:
```python
    # ── 2. Cycle-count model ─────────────────────────────────────────────
    # single_node: per-tile call -- each dram_i gets its own NodeTileSpec
    # (from iter_node_tiles) and its own model.format_input/compute_cycles
    # call, so a real trace-driven model's cycle count can vary tile to
    # tile. DenseStaticComputeModel ignores tile/trace entirely, so this
    # path costs it nothing but a few redundant (identical) calls.
    # Non-single_node: exactly today's original one-shot call, unchanged.
    model = compute_model or DenseStaticComputeModel(schedule, prob)
    live_tiles: Optional[List[NodeTileSpec]] = (
        list(iter_node_tiles(schedule, prob)) if single_node else None
    )
    if live_tiles is None:
        cycles = model.compute_cycles(model.format_input(trace, None), None)
        mac_cyc = cycles.mac_cycles
        lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0
```

- [ ] **Step 3: Recompute `mac_cyc`/`lif_cyc` inside the `dram_i` loop when live**

Immediately after:
```python
        (is_first_K_dram, is_last_K_dram) = si.dram_k_position(dram_i)
        (is_first_T_dram, is_last_T_dram) = si.dram_t_position(dram_i)
```
add:
```python
        if live_tiles is not None:
            tile = live_tiles[dram_i]
            cycles = model.compute_cycles(model.format_input(trace, tile), tile)
            mac_cyc = cycles.mac_cycles
            lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0
```

- [ ] **Step 4: Thread `trace` through `sim.py`**

In `src/snn_cosa/nocsim/sim.py`, add `import numpy as np` near the top
(after the existing stdlib imports), then change `run()`'s signature from:
```python
def run(
    x:         Dict,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    out_file:  pathlib.Path,
    y:         Optional[Dict] = None,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
```
to:
```python
def run(
    x:         Dict,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    out_file:  pathlib.Path,
    y:         Optional[Dict] = None,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
    trace:     Optional[np.ndarray] = None,
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
```
and its body's `combine()` call from:
```python
    gen      = combine(schedule, bs, si, prob, bitwidths, arch=arch, compute_model=compute_model)
```
to:
```python
    gen      = combine(schedule, bs, si, prob, bitwidths, arch=arch, compute_model=compute_model, trace=trace)
```
Repeat the identical signature/body change for `run_from_json()`.

- [ ] **Step 5: Zero-regression verification (non-single_node path)**

`/tmp/verify_combine_zero_regression.py` (scratch, not committed) — run
the pre-existing `sim_demo` config exactly as before this change and
diff the output CSV byte-for-byte against a copy taken before editing:
```bash
cd /home/yy/projects/snn_cosa
export PYTHONPATH=src
cp outputs/sim_demo_schedule.json /tmp/pre_change_schedule.json 2>/dev/null || true
python3 -m snn_cosa.nocsim.sim \
  --schedule outputs/sim_demo_schedule.json \
  --layer configs/workloads/sample_snn_layer.yaml \
  --arch configs/arch/snn_arch.yaml \
  --out /tmp/tc_after.csv
```
(If `outputs/sim_demo_schedule.json` doesn't exist locally, first
regenerate it: `python3 -m snn_cosa solve --layer configs/workloads/
sample_snn_layer.yaml --arch configs/arch/snn_arch.yaml --out outputs/
sim_demo_schedule.json`, then re-run the `nocsim.sim` command above
TWICE — once on a git stash of this task's changes, once after — and
diff the two `tc_after.csv` outputs.)

Expected: `diff` between the pre-change and post-change CSV shows **zero
differences** (this exercises `arch.single_node=False`, so `live_tiles`
stays `None` and the code path is byte-identical to before).

- [ ] **Step 6: Zero-regression verification (single_node + no real model path)**

```bash
python3 -m snn_cosa solve \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/spinalflow.yaml \
  --out /tmp/spinalflow_schedule.json
python3 -m snn_cosa.nocsim.sim \
  --schedule /tmp/spinalflow_schedule.json \
  --layer configs/workloads/generated/vgg16/T4/conv2_1.yaml \
  --arch configs/arch/spinalflow.yaml \
  --out /tmp/tc_spinalflow_dense.csv
```
(No `compute_model` passed — this uses `DenseStaticComputeModel` under
`single_node=True`, now going through the NEW per-`dram_i` live-tiles
path.) Run this command TWICE — once against a git stash of this task's
changes (the OLD one-shot-call code), once after — and diff the two
`tc_spinalflow_dense.csv` outputs.

Expected: **zero differences** (confirms the per-`dram_i` path, even
though it now calls `DenseStaticComputeModel` N times instead of once,
produces identical `mac_cyc`/`lif_cyc` every time, since that model
ignores `tile` entirely — a structural guarantee, not a coincidence, but
worth confirming against real output).

- [ ] **Step 7: Real-arch smoke test (live wiring actually varies per tile)**

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
import pathlib
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.trace import load_layer_trace
from snn_cosa.nocsim.sim import run_from_json
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.parsers.layer import SNNProb

trace = load_layer_trace(pathlib.Path('input_trace/loas/vgg16_T4_B1'), 'layer_01_features_3')
prob = SNNProb('configs/workloads/generated/vgg16/T4/conv2_1.yaml')
arch = SNNArch('configs/arch/spinalflow.yaml')
bitwidths = SNNBitwidths('configs/arch/spinalflow.yaml')
run_from_json(
    pathlib.Path('/tmp/spinalflow_schedule.json'), prob, bitwidths,
    pathlib.Path('/tmp/tc_spinalflow_live.csv'),
    arch=arch, compute_model=SpinalFlowComputeModel(), trace=trace,
)
print('run_from_json with a real trace exited clean')
"
```
Expected: exits 0, prints the confirmation line, and
`/tmp/tc_spinalflow_live.csv` differs from `/tmp/tc_spinalflow_dense.csv`
(the real trace-driven `mac_cyc` values are NOT the same as the static
formula's — inspect a few `COUNT` op rows in both CSVs by hand and
confirm the `size` column differs at some `dram_i` step).

- [ ] **Step 8: Present for review**

Run: `git diff -- src/snn_cosa/nocsim/combine.py src/snn_cosa/nocsim/sim.py`
Stop here for review/comment.

---

## Task 6: Full sweep — all 5 archs × 28 real layers

**Files:**
- Create: `scripts/sweep_archmodel_layers.py`

**Interfaces:**
- Consumes: `build_workload_from_trace`/`valid_layer_names`/
  `load_layer_trace` (Task 3), the 5 `<Arch>ComputeModel` classes
  (Task 4), `run_from_json` (Task 5), `solve_schedule` (pre-existing,
  `src/snn_cosa/solver.py`).
- Produces: `outputs/archmodel_sweep/<arch>_summary.csv`, one row per
  (layer) — `layer,workload_dims,status,dram_num_steps,total_mac_cycles,
  cycles_vary,total_weight_addresses,tc_count,error`.

- [ ] **Step 1: Write the sweep script**

```python
#!/usr/bin/env python3
"""Sweep all 5 wired arch models against all 28 valid captured trace
layers, solving + live-wiring + running each, and saving one summary CSV
per arch to outputs/archmodel_sweep/ for review.

28 = 9 valid vgg16_T4_B1 layers (3 of the 12 excluded, Hin=Win=2 too
small for a 3x3 no-pad receptive field) + all 19 resnet19_T4_B1 layers.
"""

from __future__ import annotations

import csv
import json
import pathlib
import sys
import tempfile
import traceback

sys.path.insert(0, "src")

import yaml

from snn_cosa.archmodels.gustavsnn.model import GustavSNNComputeModel
from snn_cosa.archmodels.loas.model import LoASComputeModel
from snn_cosa.archmodels.prosperity.model import ProsperityComputeModel
from snn_cosa.archmodels.ptb.model import PTBComputeModel
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.trace import build_workload_from_trace, load_layer_trace, valid_layer_names
from snn_cosa.nocsim.sim import run_from_json
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.parsers.layer import SNNProb
from snn_cosa.solver import solve_schedule

ARCHS = {
    "spinalflow": ("configs/arch/spinalflow.yaml", SpinalFlowComputeModel),
    "ptb": ("configs/arch/ptb.yaml", PTBComputeModel),
    "loas": ("configs/arch/loas.yaml", LoASComputeModel),
    "gustavsnn": ("configs/arch/gustavsnn.yaml", GustavSNNComputeModel),
    "prosperity": ("configs/arch/prosperity.yaml", ProsperityComputeModel),
}
TRACE_DIRS = ["input_trace/loas/vgg16_T4_B1", "input_trace/loas/resnet19_T4_B1"]
OUT_DIR = pathlib.Path("outputs/archmodel_sweep")


def _sweep_layers():
    """Yield (trace_dir, layer_name, meta) for every valid layer, across
    both captured models, in meta.json order."""
    for trace_dir in TRACE_DIRS:
        trace_dir = pathlib.Path(trace_dir)
        with open(trace_dir / "meta.json") as fh:
            meta = json.load(fh)
        names = list(meta["layers"])
        valid = set(valid_layer_names(meta))
        for i, name in enumerate(names):
            if name not in valid:
                continue
            next_cin = meta["layers"][names[i + 1]][2] if i + 1 < len(names) else None
            yield trace_dir, name, meta, next_cin


def _run_one(arch_name: str, arch_yaml: str, model_cls, trace_dir, layer_name, meta, next_cin):
    row = {"layer": f"{trace_dir.name}/{layer_name}", "status": "ERROR"}
    try:
        workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
        row["workload_dims"] = str(workload["problem"])

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(workload, f)
            layer_path = f.name

        prob = SNNProb(pathlib.Path(layer_path))
        arch = SNNArch(pathlib.Path(arch_yaml))
        bitwidths = SNNBitwidths(pathlib.Path(arch_yaml))

        result = solve_schedule(layer_path, arch_yaml)
        if not result.get("has_solution"):
            row["status"] = "INFEASIBLE"
            return row
        schedule = schedule_from_strategy(result["strategy"], prob)
        row["dram_num_steps"] = schedule.dram_num_steps

        trace = load_layer_trace(trace_dir, layer_name)
        model = model_cls()
        tiles = list(iter_node_tiles(schedule, prob))
        per_tile_cycles = []
        total_addresses = 0
        for tile in tiles:
            packed = model.format_input(trace, tile)
            cycles = model.compute_cycles(packed, tile)
            per_tile_cycles.append(cycles.mac_cycles)
            total_addresses += len(model.weight_addresses(packed, tile))

        row["total_mac_cycles"] = sum(per_tile_cycles)
        row["cycles_vary"] = len(set(per_tile_cycles)) > 1
        row["total_weight_addresses"] = total_addresses

        out_csv = OUT_DIR / f"{arch_name}_{trace_dir.name}_{layer_name}_tc.csv"
        strategy_path = pathlib.Path(tempfile.mktemp(suffix=".json"))
        with open(strategy_path, "w") as fh:
            json.dump(result, fh)
        run_from_json(
            strategy_path, prob, bitwidths, out_csv,
            arch=arch, compute_model=model, trace=trace,
        )
        lines = [ln for ln in out_csv.read_text().splitlines() if ln and not ln.startswith("#")]
        row["tc_count"] = len(lines)
        row["status"] = "OK"
    except Exception as exc:  # noqa: BLE001 -- sweep script: record, don't crash the whole sweep
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["status"] = "ERROR"
        traceback.print_exc()
    return row


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = list(_sweep_layers())
    print(f"Sweeping {len(layers)} valid layers x {len(ARCHS)} archs = {len(layers) * len(ARCHS)} runs")

    for arch_name, (arch_yaml, model_cls) in ARCHS.items():
        rows = []
        for trace_dir, layer_name, meta, next_cin in layers:
            print(f"  {arch_name} / {trace_dir.name}/{layer_name} ...")
            rows.append(_run_one(arch_name, arch_yaml, model_cls, trace_dir, layer_name, meta, next_cin))

        summary_path = OUT_DIR / f"{arch_name}_summary.csv"
        fieldnames = [
            "layer", "workload_dims", "status", "dram_num_steps",
            "total_mac_cycles", "cycles_vary", "total_weight_addresses",
            "tc_count", "error",
        ]
        with open(summary_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        n_ok = sum(1 for r in rows if r["status"] == "OK")
        print(f"{arch_name}: {n_ok}/{len(rows)} OK -> {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the sweep**

```bash
cd /home/yy/projects/snn_cosa
export PYTHONPATH=src
python3 scripts/sweep_archmodel_layers.py
```
Expected: prints `Sweeping 28 valid layers x 5 archs = 140 runs`, then a
progress line per (arch, layer), then a final `<arch>: <n_ok>/28 OK ->
outputs/archmodel_sweep/<arch>_summary.csv` line per arch. `n_ok` is not
predictable in advance (some layers may be `INFEASIBLE` for a given
arch's capacity constraints, e.g. LoAS's full-row-residency requirement
against a very wide CIN) — report the actual counts, don't assume 28/28.

- [ ] **Step 3: Inspect and present the 5 summary CSVs for review**

```bash
for f in outputs/archmodel_sweep/*_summary.csv; do
  echo "=== $f ==="
  column -s, -t "$f" | head -30
done
```
Present the full output of this command (all 5 tables) to the user —
per the plan's verification convention, this is the actual reviewable
artifact, not a prose summary of it. Specifically confirm:
- `cycles_vary` is `True` for at least some rows per arch (proof the
  live per-tile wiring is actually firing differently per tile, not
  returning one constant — the entire point of this plan).
- Any `ERROR`/`INFEASIBLE` rows' `error`/`status` values, so the user can
  judge whether they're expected (e.g. a genuine capacity mismatch) or a
  real bug.

- [ ] **Step 4: Present for review**

Run: `git status --short scripts/sweep_archmodel_layers.py`
Stop here — this completes the plan. The separate locality-analyzer plan
depends on this sweep's per-layer solved schedules + `weight_addresses`
output.

---

## Self-review notes

- **Spec coverage:** `iter_node_tiles` (Design §1, Task 1) — including
  the corrected `node_bound` formula (NOT dividing out `spatial_factors`,
  per Global Constraints) and its `is_last_K` reuse of `StepInfo`.
  `weight_addresses` Protocol extension (Design §2, Task 2). Five
  `<Arch>ComputeModel` classes (Design §3, Task 4) — each verified to
  produce byte-identical output to calling the raw functions directly.
  `combine.py`/`sim.py` per-`dram_i` wiring + `trace` threading (Design
  §4, Task 5) — zero-regression on both the non-`single_node` path and
  the `single_node`+no-real-model path, plus a real-arch smoke test
  proving the live values actually differ from the static ones. The
  28-layer (not 31) sweep with freshly-built per-layer workloads (Design
  §4's fix, Task 3 + Task 6) — including the 3-layer vgg16 exclusion and
  the COUT-inference-from-next-layer's-CIN rule, both concretely verified
  against the real `meta.json` data in Task 3.
- **No placeholders:** every step has complete, runnable code; Task 6's
  sweep step reports "don't assume a specific number" only for genuinely
  data-dependent outcomes (real spike counts, MIP feasibility), consistent
  with how the existing GustavSNN/Prosperity pilots handle solver-output
  inspection.
- **Type consistency:** `NodeTileSpec`/`ComputeCycles`/`ArchComputeModel`
  match `archmodels/__init__.py`'s definitions after Task 2's extension;
  all 5 `model.py` wrappers (Task 4) call their own arch's already-defined
  `reconstruct_tile_sequence`/`event_to_cycle`/`event_to_address` with no
  signature drift. `iter_node_tiles` (Task 1) produces exactly the
  `NodeTileSpec` shape every arch's `reconstruct_tile_sequence` already
  expects (`node_bound`/`tile_offset` dicts keyed by the same `DIM_*`
  constants). `combine.py`'s new `trace` parameter threads through
  `sim.py`'s `run()`/`run_from_json()` unchanged in type
  (`Optional[np.ndarray]`) end to end.