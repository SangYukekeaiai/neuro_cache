# TITL/MITL/NISL locality analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note:** per the arch-model pilots' established convention,
> treat every task as its own checkpoint — present the diff for review at
> the end of each task rather than auto-committing. If executed via
> subagent-driven-development instead, that skill's commit-per-task
> ledger mechanism applies instead — confirm with the user which mode
> before starting.
>
> **Hard prerequisite:** this plan depends on
> `docs/superpowers/plans/2026-07-16-archmodel-live-wiring.md` being
> done — it consumes real per-tile weight addresses from a solved
> schedule via the 5 `<Arch>ComputeModel` classes and `iter_node_tiles()`
> that plan builds. Do not start this plan before that one is merged.

## Spec (rephrased)

Full design: `docs/superpowers/specs/2026-07-16-archmodel-live-wiring-locality-design.md`.

`src/snn_cosa/locality/` is currently an empty placeholder package. This
plan builds:

1. **Stack-distance / reuse-distance analysis** (`stack_distance.py`) —
   for an ordered weight-address stream, the number of DISTINCT addresses
   referenced between two accesses to the same address (classic LRU
   stack distance, Mattson et al.), plus the derived reuse-distance
   histogram and a footprint-vs-window-size curve.
2. **TITL/MITL/NISL classification** (`classify.py`) — inspects a solved
   `Schedule`'s actual weight-loading permutation order and returns each
   locality type's degree (Strong/Medium/Weak/N/A), per Table I of the
   "Neuromorphic Cache Design" draft — reverse-derived directly from the
   table's own 7 rows (the paper's prose is imprecise; see the spec's
   Design §5 and this plan's Task 2 docstring for the derivation).
3. **A runner** (`run_analysis.py`) that, for one (arch, real trace
   layer), builds the concatenated real address stream from a solved
   schedule (reusing the live-wiring plan's `iter_node_tiles`/
   `<Arch>ComputeModel`), runs both analyses, and saves a JSON summary +
   two matplotlib figures.
4. **A full sweep** across all 5 archs × the same 28 valid real layers
   the live-wiring plan's own sweep used, producing one classification
   CSV and 140 per-layer output directories for explicit review.

**Goal:** empirically characterize the real weight-address reuse
behavior of all 5 wired architectures, and classify each one's actual
solved schedule against the paper's own locality taxonomy.

**Architecture:** two small, independently-testable analysis modules
(`stack_distance.py`, `classify.py`) with no dependency on any specific
architecture, plus one runner that glues them to the live-wiring plan's
real per-tile address stream.

**Tech Stack:** Python 3, numpy (already a dependency), matplotlib
(already installed in this environment, verified — not currently listed
in any dependency manifest since this repo has none; first real consumer
of it). No pytest — verification runs scripts and inspects saved
JSON/CSV/figure output, per existing convention.

## Global Constraints

- Every verification step below **saves its concrete output to disk**
  for explicit user review — this is a standing requirement for this
  project's arch-model/locality work (see the `feedback_verification_
  output_review` memory captured 2026-07-16), not just a nice-to-have.
- Reuse distance is computed in units of **distinct weight lines**
  (stack distance), not raw access count — this is what makes "against
  the unique weight line counts" directly answerable (a reuse distance
  of `d` means a cache holding `d` distinct lines would have captured
  that reuse).
- `stack_distances`/`footprint_curve` must stay correct at the address
  counts these traces actually produce (tens to low thousands per solved
  schedule, per the live-wiring plan's Task 6 sweep) — no need for
  OS-trace-scale approximate reuse-distance algorithms.
- `classify_schedule` must exactly reproduce Table I's 7 canonical rows
  when given their exact permutation orders (verified directly in Task
  2) — this is the analyzer's own self-consistency check before it's
  trusted on real solved schedules.
- No changes to `archmodels/`, `nocsim/`, or any file from the
  live-wiring plan — this plan only reads their outputs.

---

## Task 1: Stack distance, reuse-distance histogram, footprint curve

**Files:**
- Create: `src/snn_cosa/locality/stack_distance.py`

**Interfaces:**
- Consumes: nothing arch-specific — a plain `List[Any]` of hashable
  addresses (e.g. the `(kh,kw,cin,cout_off,cout_end)` tuples every arch's
  `event_to_address`/`weight_addresses` already produces).
- Produces: `stack_distances(addresses) -> List[Optional[int]]`,
  `reuse_distance_histogram(distances) -> Dict[int, int]`,
  `footprint_curve(addresses, max_window=64) -> Dict[int, float]` —
  consumed by Task 3's `run_analysis.py`.

- [ ] **Step 1: Write `stack_distance.py`**

```python
"""Stack-distance (reuse-distance) and footprint analysis over an ordered
weight-address stream.

Stack distance (Mattson et al., 1970): for an access to address `a` that
was last referenced at an earlier position `j`, the stack distance is the
number of DISTINCT addresses referenced strictly between `j` and the
current position -- i.e. how many distinct weight lines an LRU cache
would need to hold to have captured that reuse. A first-time access has
no finite stack distance (None -- a cold miss regardless of cache size).

Computed via a Fenwick (binary indexed) tree over "is this timestep
currently the most-recent occurrence of some address" -- O(n log n) total
for a stream of n accesses. This project's real per-schedule address
streams are small (tens to low thousands of entries, see the live-wiring
plan's sweep), so this reference-model implementation favors clarity over
the streaming/approximate reuse-distance algorithms built for OS-trace-
scale (billions of accesses) analysis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _Fenwick:
    """1-indexed internally; supports point update and range sum over
    0-indexed positions [0, n-1]."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.tree = [0] * (n + 1)

    def update(self, pos: int, delta: int) -> None:
        i = pos + 1
        while i <= self.n:
            self.tree[i] += delta
            i += i & (-i)

    def _prefix_sum(self, pos: int) -> int:
        """Sum over 0-indexed [0, pos] inclusive."""
        if pos < 0:
            return 0
        i = pos + 1
        s = 0
        while i > 0:
            s += self.tree[i]
            i -= i & (-i)
        return s

    def range_sum(self, lo: int, hi: int) -> int:
        """Sum over 0-indexed [lo, hi] inclusive; 0 if lo > hi."""
        if lo > hi:
            return 0
        return self._prefix_sum(hi) - self._prefix_sum(lo - 1)


def stack_distances(addresses: List[Any]) -> List[Optional[int]]:
    """Return one stack distance per access, `None` for first occurrences.

    Args:
        addresses: ordered, hashable weight addresses (e.g. the
                   (kh,kw,cin,cout_off,cout_end) tuples every arch's
                   event_to_address/weight_addresses produces).

    Returns:
        List of the same length as `addresses`; entry i is the stack
        distance of addresses[i] (None if this is that address's first
        occurrence in the stream).
    """
    n = len(addresses)
    fen = _Fenwick(n)
    last_seen: Dict[Any, int] = {}
    distances: List[Optional[int]] = []

    for i, addr in enumerate(addresses):
        if addr in last_seen:
            j = last_seen[addr]
            distances.append(fen.range_sum(j + 1, i - 1))
            fen.update(j, -1)
        else:
            distances.append(None)
        fen.update(i, 1)
        last_seen[addr] = i

    return distances


def reuse_distance_histogram(distances: List[Optional[int]]) -> Dict[int, int]:
    """Bucket finite stack distances into a {distance: count} histogram.

    First-occurrence (None) entries are excluded -- they have no finite
    reuse distance to bucket.
    """
    hist: Dict[int, int] = {}
    for d in distances:
        if d is not None:
            hist[d] = hist.get(d, 0) + 1
    return hist


def footprint_curve(addresses: List[Any], max_window: int = 64) -> Dict[int, float]:
    """{window_size: avg_distinct_addresses_touched}, for window sizes
    1..min(max_window, len(addresses)).

    For each window size w, slides a length-w window across the whole
    stream and averages the number of distinct addresses inside it --
    the working-set-vs-capacity curve: "how many unique weight lines does
    an on-chip cache of this capacity need to hold this tile's reuse."

    O(n * max_window) -- max_window defaults to a modest 64 to keep this
    reference implementation's runtime bounded regardless of stream
    length; pass a larger value explicitly if a wider curve is needed for
    a specific (small) stream.
    """
    n = len(addresses)
    if n == 0:
        return {}
    max_window = min(max_window, n)

    curve: Dict[int, float] = {}
    for w in range(1, max_window + 1):
        window_counts: Dict[Any, int] = {}
        distinct = 0
        total = 0
        samples = 0
        for i in range(n):
            addr = addresses[i]
            window_counts[addr] = window_counts.get(addr, 0) + 1
            if window_counts[addr] == 1:
                distinct += 1
            if i >= w:
                old = addresses[i - w]
                window_counts[old] -= 1
                if window_counts[old] == 0:
                    distinct -= 1
            if i >= w - 1:
                total += distinct
                samples += 1
        curve[w] = total / samples if samples else 0.0

    return curve
```

- [ ] **Step 2: Write the verification script**

`/tmp/verify_stack_distance.py` (scratch, not committed):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.locality.stack_distance import (
    footprint_curve,
    reuse_distance_histogram,
    stack_distances,
)

# --- Hand-worked example: A,B,A,C,A -----------------------------------------
# A@0: first occurrence -> None
# B@1: first occurrence -> None
# A@2: last seen @0, distinct addresses strictly between (positions 1) = {B} -> 1
# C@3: first occurrence -> None
# A@4: last seen @2, distinct addresses strictly between (position 3) = {C} -> 1
stream = ["A", "B", "A", "C", "A"]
dists = stack_distances(stream)
assert dists == [None, None, 1, None, 1], dists
print(f"OK: stack_distances({stream}) == {dists}")

hist = reuse_distance_histogram(dists)
assert hist == {1: 2}, hist
print(f"OK: reuse_distance_histogram == {hist}")

# --- A longer example with a distance-2 reuse: A,B,C,A ----------------------
# A@3: last seen @0, distinct strictly between (positions 1,2) = {B,C} -> 2
stream2 = ["A", "B", "C", "A"]
dists2 = stack_distances(stream2)
assert dists2 == [None, None, None, 2], dists2
print(f"OK: stack_distances({stream2}) == {dists2}")

# --- footprint_curve: all-distinct stream of length 5 -> every window w has
# exactly w distinct addresses (footprint(w) == w when nothing repeats) -----
all_distinct = ["A", "B", "C", "D", "E"]
fp = footprint_curve(all_distinct, max_window=5)
assert fp == {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0}, fp
print(f"OK: footprint_curve(all-distinct, max_window=5) == {fp}")

# --- footprint_curve: constant repeated address -> footprint(w) == 1 always
constant = ["X"] * 10
fp_const = footprint_curve(constant, max_window=4)
assert fp_const == {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}, fp_const
print(f"OK: footprint_curve(constant, max_window=4) == {fp_const}")

# --- empty stream -> footprint_curve returns {} -----------------------------
assert footprint_curve([]) == {}
assert stack_distances([]) == []
print("OK: empty-stream edge cases")
```

- [ ] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_stack_distance.py`
Expected:
```
OK: stack_distances(['A', 'B', 'A', 'C', 'A']) == [None, None, 1, None, 1]
OK: reuse_distance_histogram == {1: 2}
OK: stack_distances(['A', 'B', 'C', 'A']) == [None, None, None, 2]
OK: footprint_curve(all-distinct, max_window=5) == {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0}
OK: footprint_curve(constant, max_window=4) == {1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0}
OK: empty-stream edge cases
```

- [ ] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/locality/stack_distance.py`
Stop here for review/comment.

---

## Task 2: TITL/MITL/NISL schedule classification

**Files:**
- Create: `src/snn_cosa/locality/classify.py`

**Interfaces:**
- Consumes: `Schedule`/`LoopItem` from
  `nocsim/schedule/decode.py` (pre-existing); `DIM_COUT, DIM_HO, DIM_T,
  DIM_WO` from `parsers/layer.py` (pre-existing).
- Produces: `classify_schedule(schedule) -> Dict[str, object]` —
  consumed by Task 3's `run_analysis.py`.

- [ ] **Step 1: Write `classify.py`**

```python
"""Classifies a solved single_node Schedule's weight-loading permutation
against the "Neuromorphic Cache Design" draft's Table I locality types
(Time-Inner Temporal Locality, M-Inner Temporal Locality, N-Inner Spatial
Locality).

Rule derivation note: the paper's own prose description of MITL/NISL is
imprecise ("NISL degrades as M moves inner->outer", "MITL degrades as N
moves outer->inner") -- this implementation instead matches Table I's own
7 rows exactly, reverse-derived directly from the table (see
docs/superpowers/specs/2026-07-16-archmodel-live-wiring-locality-design.md's
Design section for the full row-by-row derivation):

    TITL <- T's position in the permutation (read outer->inner):
            innermost=Strong, middle=Medium, outermost=Weak, absent="N/A"
    NISL <- N's (=COUT) position, the SAME rule as TITL
    MITL <- N's position too, but INVERTED: innermost=Weak, middle=Medium,
            outermost=Strong

M's own position does not independently drive any of the three degrees
in Table I's data -- with only 3 permutation slots, T's and N's positions
already determine M's by elimination, so the table's 7 rows alone cannot
distinguish an M-driven rule from "whichever slot T and N didn't take".
"""

from __future__ import annotations

from typing import Dict, List, Optional

from snn_cosa.nocsim.schedule.decode import Schedule
from snn_cosa.parsers.layer import DIM_COUT, DIM_HO, DIM_T, DIM_WO

# Table I's 7 canonical rows: (order outer->inner, attributed paper/arch).
# M = HO+WO collapsed into one slot; T = DIM_T; N = DIM_COUT.
TABLE1_ROWS: List[Dict[str, object]] = [
    {"order": ["N", "M", "T"], "TITL": "Strong", "MITL": "Strong", "NISL": "Weak", "arch": "GustavSNN [7]"},
    {"order": ["M", "N", "T"], "TITL": "Strong", "MITL": "Medium", "NISL": "Medium", "arch": "SpinalFlow [10]"},
    {"order": ["N", "T", "M"], "TITL": "Medium", "MITL": "Strong", "NISL": "Weak", "arch": None},
    {"order": ["T", "N", "M"], "TITL": "Weak", "MITL": "Medium", "NISL": "Medium", "arch": "Phi/Prosperity [11,12]"},
    {"order": ["M", "T", "N"], "TITL": "Medium", "MITL": "Weak", "NISL": "Strong", "arch": "PTB [6]"},
    {"order": ["T", "M", "N"], "TITL": "Weak", "MITL": "Weak", "NISL": "Strong", "arch": None},
    {"order": ["M", "N"], "TITL": "N/A", "MITL": "Weak", "NISL": "Strong", "arch": "LoAS [5]"},
]


def _dim_tag(dim: int) -> Optional[str]:
    if dim == DIM_T:
        return "T"
    if dim == DIM_COUT:
        return "N"
    if dim in (DIM_HO, DIM_WO):
        return "M"
    return None  # reduction dim (KH/KW/CIN) -- not part of the M/N/T abstraction


def outer_to_inner_order(schedule: Schedule) -> List[str]:
    """This schedule's dram_temporal_loops dims, outer->inner, tagged
    "T"/"N"/"M" -- HO and WO both tag "M" and collapse into one slot if
    adjacent. Reduction dims (KH/KW/CIN) are dropped entirely.

    Raises:
        ValueError: if HO and WO both appear but are non-adjacent (can't
                    collapse into one "M" slot -- non-canonical schedule).
    """
    loops = sorted(schedule.dram_temporal_loops, key=lambda item: -item.level)  # outer -> inner
    seq: List[str] = []
    for item in loops:
        tag = _dim_tag(item.dim)
        if tag is None:
            continue
        if seq and seq[-1] == tag:
            continue  # HO+WO adjacent, both "M" -- collapse
        seq.append(tag)

    if seq.count("M") > 1:
        raise ValueError(f"HO/WO are non-adjacent in this schedule's permutation: {seq}")
    return seq


def _degree(order: List[str], tag: str) -> str:
    if tag not in order:
        return "N/A"
    idx = order.index(tag)
    if idx == len(order) - 1:
        return "Strong"   # innermost
    if idx == 0:
        return "Weak"     # outermost
    return "Medium"


def _invert(degree: str) -> str:
    return {"Strong": "Weak", "Weak": "Strong", "Medium": "Medium", "N/A": "N/A"}[degree]


def classify_schedule(schedule: Schedule) -> Dict[str, object]:
    """Classify a solved single_node Schedule's TITL/MITL/NISL degrees.

    Returns:
        {"order": List[str] or None, "TITL": str, "MITL": str,
         "NISL": str, "table1_row": List[str] or None,
         "table1_arch": str or None, "error": str (only if non-canonical)}
    """
    try:
        order = outer_to_inner_order(schedule)
    except ValueError as exc:
        return {
            "order": None, "TITL": "non-canonical", "MITL": "non-canonical",
            "NISL": "non-canonical", "table1_row": None, "table1_arch": None,
            "error": str(exc),
        }

    nisl = _degree(order, "N")
    result = {
        "order": order,
        "TITL": _degree(order, "T"),
        "MITL": _invert(nisl),
        "NISL": nisl,
        "table1_row": None,
        "table1_arch": None,
    }
    for row in TABLE1_ROWS:
        if row["order"] == order:
            result["table1_row"] = row["order"]
            result["table1_arch"] = row["arch"]
            break
    return result
```

- [ ] **Step 2: Write the verification script**

`/tmp/verify_classify.py` (scratch, not committed) — confirms every one
of Table I's 7 rows reproduces exactly, using hand-built `Schedule`
fixtures with only `dram_temporal_loops` populated (the only field
`classify_schedule` reads):
```python
import sys

sys.path.insert(0, "src")

from snn_cosa.locality.classify import TABLE1_ROWS, classify_schedule
from snn_cosa.nocsim.schedule.decode import LoopItem, Schedule
from snn_cosa.parsers.layer import DIM_COUT, DIM_HO, DIM_KH, DIM_T, DIM_WO

def _schedule_for(tags):
    """Build a Schedule whose dram_temporal_loops read outer->inner as
    `tags` (e.g. ["N","M","T"]), using DIM_COUT for N, DIM_HO+DIM_WO (two
    adjacent items) for M, DIM_T for T. Levels count DOWN from outer to
    inner so higher level = more outer, matching decode.py's convention."""
    dim_for = {"N": [DIM_COUT], "M": [DIM_HO, DIM_WO], "T": [DIM_T]}
    items = []
    level = 100  # outer-most gets the highest level number
    for tag in tags:
        for dim in dim_for[tag]:
            items.append(LoopItem(dim=dim, dim_name=str(dim), factor=2, level=level))
            level -= 1
    return Schedule(
        spatial_factors={j: 1 for j in range(7)}, noc_temporal_loops=[],
        dram_temporal_loops=items, data_size={}, gb_start=1, dram_start=8, perm_levels=7,
    )

for row in TABLE1_ROWS:
    schedule = _schedule_for(row["order"])
    result = classify_schedule(schedule)
    assert result["order"] == row["order"], (result["order"], row["order"])
    assert result["TITL"] == row["TITL"], (row["order"], "TITL", result["TITL"], row["TITL"])
    assert result["MITL"] == row["MITL"], (row["order"], "MITL", result["MITL"], row["MITL"])
    assert result["NISL"] == row["NISL"], (row["order"], "NISL", result["NISL"], row["NISL"])
    assert result["table1_arch"] == row["arch"], (result["table1_arch"], row["arch"])
    print(f"OK: order={row['order']} -> TITL={result['TITL']}, MITL={result['MITL']}, "
          f"NISL={result['NISL']}, arch={result['table1_arch']}")

# --- Non-adjacent HO/WO -> non-canonical, doesn't crash ---------------------
bad_items = [
    LoopItem(dim=DIM_HO, dim_name="HO", factor=2, level=10),
    LoopItem(dim=DIM_T, dim_name="T", factor=2, level=9),
    LoopItem(dim=DIM_WO, dim_name="WO", factor=2, level=8),
]
bad_schedule = Schedule(
    spatial_factors={j: 1 for j in range(7)}, noc_temporal_loops=[],
    dram_temporal_loops=bad_items, data_size={}, gb_start=1, dram_start=8, perm_levels=7,
)
bad_result = classify_schedule(bad_schedule)
assert bad_result["TITL"] == "non-canonical", bad_result
assert "error" in bad_result
print(f"OK: non-adjacent HO/WO -> {bad_result['TITL']} ({bad_result['error']})")
```

- [ ] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_classify.py`
Expected (7 rows + 1 edge case, in `TABLE1_ROWS`'s order):
```
OK: order=['N', 'M', 'T'] -> TITL=Strong, MITL=Strong, NISL=Weak, arch=GustavSNN [7]
OK: order=['M', 'N', 'T'] -> TITL=Strong, MITL=Medium, NISL=Medium, arch=SpinalFlow [10]
OK: order=['N', 'T', 'M'] -> TITL=Medium, MITL=Strong, NISL=Weak, arch=None
OK: order=['T', 'N', 'M'] -> TITL=Weak, MITL=Medium, NISL=Medium, arch=Phi/Prosperity [11,12]
OK: order=['M', 'T', 'N'] -> TITL=Medium, MITL=Weak, NISL=Strong, arch=PTB [6]
OK: order=['T', 'M', 'N'] -> TITL=Weak, MITL=Weak, NISL=Strong, arch=None
OK: order=['M', 'N'] -> TITL=N/A, MITL=Weak, NISL=Strong, arch=LoAS [5]
OK: non-adjacent HO/WO -> non-canonical (HO/WO are non-adjacent in this schedule's permutation: ['M', 'T', 'M'])
```

- [ ] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/locality/classify.py`
Stop here for review/comment.

---

## Task 3: Runner — real address stream + figures for one (arch, layer)

**Files:**
- Create: `src/snn_cosa/locality/run_analysis.py`

**Interfaces:**
- Consumes: `stack_distances`/`reuse_distance_histogram`/
  `footprint_curve` (Task 1); `classify_schedule` (Task 2);
  `iter_node_tiles` (live-wiring plan, `nocsim/schedule/tiles.py`); the 5
  `<Arch>ComputeModel` classes + `build_workload_from_trace`/
  `valid_layer_names`/`load_layer_trace` (live-wiring plan,
  `archmodels/trace.py`); `solve_schedule` (pre-existing,
  `src/snn_cosa/solver.py`).
- Produces: `analyze_layer(arch_name, arch_yaml, model_cls, trace_dir,
  layer_name, meta, next_cin, out_dir) -> Dict` — writes
  `<out_dir>/summary.json`, `<out_dir>/reuse_distance_histogram.png`,
  `<out_dir>/footprint_curve.png`. Consumed by Task 4's sweep.

- [ ] **Step 1: Write `run_analysis.py`**

```python
#!/usr/bin/env python3
"""Runs the locality analyzer against one real (arch, captured trace
layer): solves that layer's workload for the given arch, walks the
solved schedule's real per-tile weight-address stream (via
iter_node_tiles + the arch's ComputeModel), and saves the reuse-distance
histogram, footprint curve, and TITL/MITL/NISL classification.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any, Dict, Optional, Type

import matplotlib

matplotlib.use("Agg")  # headless -- this runner only ever saves PNGs
import matplotlib.pyplot as plt
import yaml

from snn_cosa.archmodels import ArchComputeModel
from snn_cosa.archmodels.trace import build_workload_from_trace, load_layer_trace
from snn_cosa.locality.classify import classify_schedule
from snn_cosa.locality.stack_distance import (
    footprint_curve,
    reuse_distance_histogram,
    stack_distances,
)
from snn_cosa.nocsim.schedule.decode import schedule_from_strategy
from snn_cosa.nocsim.schedule.tiles import iter_node_tiles
from snn_cosa.parsers.layer import SNNProb
from snn_cosa.solver import solve_schedule


def _build_address_stream(
    arch_yaml: str, model_cls: Type[ArchComputeModel],
    trace_dir: pathlib.Path, layer_name: str, meta: Dict[str, Any],
    next_cin: Optional[int],
):
    """Solve this layer's workload for this arch and return
    (schedule, concatenated address stream in dram_i order) or None if
    infeasible."""
    workload = build_workload_from_trace(meta, layer_name, next_cin=next_cin)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(workload, f)
        layer_path = f.name

    prob = SNNProb(pathlib.Path(layer_path))
    result = solve_schedule(layer_path, arch_yaml)
    if not result.get("has_solution"):
        return None

    schedule = schedule_from_strategy(result["strategy"], prob)
    trace = load_layer_trace(trace_dir, layer_name)
    model = model_cls()

    addresses = []
    for tile in iter_node_tiles(schedule, prob):
        packed = model.format_input(trace, tile)
        addresses.extend(model.weight_addresses(packed, tile))

    return schedule, addresses


def analyze_layer(
    arch_name: str, arch_yaml: str, model_cls: Type[ArchComputeModel],
    trace_dir: pathlib.Path, layer_name: str, meta: Dict[str, Any],
    next_cin: Optional[int], out_dir: pathlib.Path,
) -> Dict[str, Any]:
    """Run the full locality analysis for one (arch, layer) and save its
    output (summary.json, reuse_distance_histogram.png,
    footprint_curve.png) under out_dir. Returns the summary dict too."""
    out_dir.mkdir(parents=True, exist_ok=True)
    built = _build_address_stream(arch_yaml, model_cls, trace_dir, layer_name, meta, next_cin)

    if built is None:
        summary = {"arch": arch_name, "layer": layer_name, "status": "INFEASIBLE"}
        with open(out_dir / "summary.json", "w") as fh:
            json.dump(summary, fh, indent=2)
        return summary

    schedule, addresses = built
    distances = stack_distances(addresses)
    hist = reuse_distance_histogram(distances)
    fp_curve = footprint_curve(addresses)
    classification = classify_schedule(schedule)

    finite = [d for d in distances if d is not None]
    summary = {
        "arch": arch_name,
        "layer": layer_name,
        "status": "OK",
        "num_addresses": len(addresses),
        "num_unique_addresses": len(set(addresses)),
        "num_cold_misses": len(distances) - len(finite),
        "mean_reuse_distance": (sum(finite) / len(finite)) if finite else None,
        "max_reuse_distance": max(finite) if finite else None,
        "classification": classification,
    }
    with open(out_dir / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)

    if hist:
        fig, ax = plt.subplots()
        xs = sorted(hist)
        ax.bar(xs, [hist[x] for x in xs])
        ax.set_xlabel("reuse distance (distinct weight lines)")
        ax.set_ylabel("count")
        ax.set_title(f"{arch_name} / {layer_name}: reuse-distance histogram")
        fig.savefig(out_dir / "reuse_distance_histogram.png")
        plt.close(fig)

    if fp_curve:
        fig, ax = plt.subplots()
        xs = sorted(fp_curve)
        ax.plot(xs, [fp_curve[x] for x in xs])
        ax.set_xlabel("window size (accesses)")
        ax.set_ylabel("avg distinct weight lines")
        ax.set_title(f"{arch_name} / {layer_name}: footprint curve")
        fig.savefig(out_dir / "footprint_curve.png")
        plt.close(fig)

    return summary
```

- [ ] **Step 2: Write the verification script**

`/tmp/verify_run_analysis.py` (scratch, not committed) — one real (arch,
layer) end to end:
```python
import sys

sys.path.insert(0, "src")

import json
import pathlib

from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.locality.run_analysis import analyze_layer

trace_dir = pathlib.Path("input_trace/loas/vgg16_T4_B1")
with open(trace_dir / "meta.json") as fh:
    meta = json.load(fh)

out_dir = pathlib.Path("/tmp/locality_verify/spinalflow_layer_01")
summary = analyze_layer(
    "spinalflow", "configs/arch/spinalflow.yaml", SpinalFlowComputeModel,
    trace_dir, "layer_01_features_3", meta, next_cin=64, out_dir=out_dir,
)
print(json.dumps(summary, indent=2))

assert summary["status"] == "OK"
assert summary["num_addresses"] > 0
assert (out_dir / "summary.json").exists()
assert (out_dir / "reuse_distance_histogram.png").exists()
assert (out_dir / "footprint_curve.png").exists()
print(f"OK: all 3 output files exist under {out_dir}")
```

- [ ] **Step 3: Run it**

Run: `cd /home/yy/projects/snn_cosa && python3 /tmp/verify_run_analysis.py`
Expected: prints the summary JSON (exact `num_addresses`/
`mean_reuse_distance`/`classification` values depend on the real trace's
actual spike content and the MIP's actual solved permutation — report
what's printed, don't assume specific numbers), then
`OK: all 3 output files exist under /tmp/locality_verify/spinalflow_layer_01`.
Open `reuse_distance_histogram.png`/`footprint_curve.png` and visually
confirm they're non-empty, sensible plots (not blank/corrupt).

- [ ] **Step 4: Present for review**

Run: `git diff --stat src/snn_cosa/locality/run_analysis.py`
Stop here for review/comment.

---

## Task 4: Full sweep — all 5 archs × 28 real layers

**Files:**
- Create: `scripts/sweep_locality_analysis.py`

**Interfaces:**
- Consumes: `analyze_layer` (Task 3), the same `ARCHS`/layer-sweep
  structure as the live-wiring plan's `scripts/sweep_archmodel_layers.py`
  (duplicated here in miniature, not imported — this plan's scripts stay
  independently runnable without depending on that script's internals).
- Produces: `outputs/locality/classify_summary.csv` (one row per
  (arch, layer)), `outputs/locality/<arch>_<trace_dir>_<layer>/` (140
  directories, each with `summary.json` + 2 PNGs),
  `outputs/locality/cross_layer_summary.csv` (one row per arch:
  mean/median/min/max reuse distance across its 28 layers).

- [ ] **Step 1: Write the sweep script**

```python
#!/usr/bin/env python3
"""Sweep the locality analyzer across all 5 wired arch models x all 28
valid captured trace layers, saving a classification summary CSV, a
cross-layer aggregate CSV, and 140 per-layer output directories
(summary.json + 2 PNGs each) under outputs/locality/ for review.
"""

from __future__ import annotations

import csv
import json
import pathlib
import statistics
import sys

sys.path.insert(0, "src")

from snn_cosa.archmodels.gustavsnn.model import GustavSNNComputeModel
from snn_cosa.archmodels.loas.model import LoASComputeModel
from snn_cosa.archmodels.prosperity.model import ProsperityComputeModel
from snn_cosa.archmodels.ptb.model import PTBComputeModel
from snn_cosa.archmodels.spinalflow.model import SpinalFlowComputeModel
from snn_cosa.archmodels.trace import valid_layer_names
from snn_cosa.locality.run_analysis import analyze_layer

ARCHS = {
    "spinalflow": ("configs/arch/spinalflow.yaml", SpinalFlowComputeModel, "row2"),
    "ptb": ("configs/arch/ptb.yaml", PTBComputeModel, "row5"),
    "loas": ("configs/arch/loas.yaml", LoASComputeModel, "row7"),
    "gustavsnn": ("configs/arch/gustavsnn.yaml", GustavSNNComputeModel, "row1"),
    "prosperity": ("configs/arch/prosperity.yaml", ProsperityComputeModel, None),
}
TRACE_DIRS = ["input_trace/loas/vgg16_T4_B1", "input_trace/loas/resnet19_T4_B1"]
OUT_DIR = pathlib.Path("outputs/locality")


def _sweep_layers():
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


_TABLE1_ROW_LABEL = {"row1": "N-M-T", "row2": "M-N-T", "row5": "M-T-N", "row7": "M-N (T parallel)"}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = list(_sweep_layers())
    print(f"Sweeping {len(layers)} valid layers x {len(ARCHS)} archs = {len(layers) * len(ARCHS)} runs")

    classify_rows = []
    cross_layer_rows = []

    for arch_name, (arch_yaml, model_cls, expected_row) in ARCHS.items():
        reuse_means = []
        for trace_dir, layer_name, meta, next_cin in layers:
            out_dir = OUT_DIR / f"{arch_name}_{trace_dir.name}_{layer_name}"
            print(f"  {arch_name} / {trace_dir.name}/{layer_name} ...")
            summary = analyze_layer(
                arch_name, arch_yaml, model_cls, trace_dir, layer_name,
                meta, next_cin, out_dir,
            )
            cls = summary.get("classification", {})
            got_row_label = _TABLE1_ROW_LABEL.get(expected_row)
            matches_expected = (
                expected_row is not None
                and cls.get("table1_row") is not None
                and "-".join(cls["order"]) == got_row_label
            )
            classify_rows.append({
                "arch": arch_name,
                "layer": f"{trace_dir.name}/{layer_name}",
                "status": summary["status"],
                "order": "-".join(cls.get("order") or []) if cls.get("order") else "",
                "TITL": cls.get("TITL", ""),
                "MITL": cls.get("MITL", ""),
                "NISL": cls.get("NISL", ""),
                "table1_arch": cls.get("table1_arch", ""),
                "expected_table1_row": expected_row or "",
                "matches_expected": matches_expected,
            })
            if summary["status"] == "OK" and summary.get("mean_reuse_distance") is not None:
                reuse_means.append(summary["mean_reuse_distance"])

        if reuse_means:
            cross_layer_rows.append({
                "arch": arch_name,
                "n_layers_ok": len(reuse_means),
                "mean_of_means": statistics.mean(reuse_means),
                "median_of_means": statistics.median(reuse_means),
                "min": min(reuse_means),
                "max": max(reuse_means),
            })

    classify_path = OUT_DIR / "classify_summary.csv"
    with open(classify_path, "w", newline="") as fh:
        fieldnames = ["arch", "layer", "status", "order", "TITL", "MITL", "NISL",
                      "table1_arch", "expected_table1_row", "matches_expected"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(classify_rows)
    print(f"-> {classify_path} ({len(classify_rows)} rows)")

    cross_path = OUT_DIR / "cross_layer_summary.csv"
    with open(cross_path, "w", newline="") as fh:
        fieldnames = ["arch", "n_layers_ok", "mean_of_means", "median_of_means", "min", "max"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cross_layer_rows)
    print(f"-> {cross_path} ({len(cross_layer_rows)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the sweep**

```bash
cd /home/yy/projects/snn_cosa
export PYTHONPATH=src
python3 scripts/sweep_locality_analysis.py
```
Expected: prints `Sweeping 28 valid layers x 5 archs = 140 runs`, then a
progress line per (arch, layer), then the two output-path lines. Runtime
will be substantial (140 real MIP solves) — this is expected, matching
the live-wiring plan's own Task 6 sweep cost.

- [ ] **Step 3: Present the classification and cross-layer summaries for review**

```bash
echo "=== classify_summary.csv ===" && column -s, -t outputs/locality/classify_summary.csv | head -40
echo "=== cross_layer_summary.csv ===" && column -s, -t outputs/locality/cross_layer_summary.csv
```
Present the full output to the user. Specifically confirm:
- Each arch's `TITL`/`MITL`/`NISL`/`order` is **stable across all its
  valid layers** (loop ordering comes from the MIP's schedule choice, not
  the trace content — a layer where an arch's verdict flips from its
  others is worth flagging, not silently accepted).
- `matches_expected` for spinalflow/ptb/loas/gustavsnn (Prosperity has no
  fixed expected row, see `ARCHS`'s `None`) — report `True`/`False`
  counts per arch; a `False` here means either the analyzer has a bug or
  the MIP's real traffic-minimizing objective doesn't happen to pick the
  same permutation the paper's cache-locality-motivated schedule would
  (both are legitimate findings worth surfacing, not silently resolving).

- [ ] **Step 4: Spot-check 2-3 figure pairs by eye**

```bash
ls outputs/locality/*/reuse_distance_histogram.png | shuf -n 3
```
Open the 3 sampled files (and their matching `footprint_curve.png`
siblings) and visually confirm: the reuse-distance histogram has mass
concentrated at low distances (matching the source paper's own Fig. 1b
evidence of strong temporal spike correlation — a neuron that spikes is
likely to spike again soon, meaning weight reuse tends to happen at
short distances), and the footprint curve is monotonically
non-decreasing (a wider window can only ever touch the same or more
distinct lines, never fewer).

- [ ] **Step 5: Present for review**

Run: `git status --short scripts/sweep_locality_analysis.py`
Stop here — this completes the plan.

---

## Self-review notes

- **Spec coverage:** stack distance / reuse-distance histogram /
  footprint curve (Design §5, Task 1) — verified against hand-worked
  examples including the distance-2 case and both footprint edge cases
  (all-distinct, constant). TITL/MITL/NISL classification (Design §5,
  Task 2) — verified to reproduce all 7 of Table I's canonical rows
  exactly, plus the non-adjacent-HO/WO non-canonical edge case. Real
  address-stream construction from a solved schedule (Task 3) reuses the
  live-wiring plan's `iter_node_tiles`/`ArchComputeModel` exactly as that
  plan built them — no new tile-derivation logic duplicated here. The
  28-layer x 5-arch sweep with stored classification CSV, cross-layer
  aggregate, and 140 saved figure pairs (Task 4) — matches the spec's
  explicit "every verification step stores its output for review"
  requirement.
- **No placeholders:** every step has complete, runnable code; Task 4's
  sweep step reports "don't assume specific numbers" only for genuinely
  data-dependent outcomes (real spike content, MIP's actual permutation
  choice), same convention as the live-wiring plan.
- **Type consistency:** `stack_distances`/`reuse_distance_histogram`/
  `footprint_curve` (Task 1) operate on a plain `List[Any]` of hashable
  addresses — exactly what `ArchComputeModel.weight_addresses` (from the
  live-wiring plan) already returns, no adapter needed. `classify_
  schedule` (Task 2) takes the same `Schedule` type `iter_node_tiles`
  already consumes. `run_analysis.py` (Task 3) imports both without
  modification and is the only file that touches the live-wiring plan's
  types at all.