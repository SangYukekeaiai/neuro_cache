# Live combine() wiring for the 5 arch models + TITL/MITL/NISL locality analyzer

## Context

All 6 planned architectures except Phi now have standalone, verified
per-arch plugins under `src/snn_cosa/archmodels/{spinalflow,ptb,loas,
gustavsnn,prosperity}/` — each a `reconstruct_tile_sequence` /
`event_to_cycle` / `event_to_address` trio, verified against hand-built
`NodeTileSpec` fixtures and the real LoAS trace, but **none wired into
`combine()`'s live loop**. `combine.py` still calls
`DenseStaticComputeModel` (or a passed-in `compute_model`) exactly **once**
per run, upfront, before the `dram_i` loop — it was never restructured to
call a model per real node-tile. `src/snn_cosa/locality/` is an empty
placeholder package; no reuse-tracking logic exists.

This spec covers two things, in dependency order:

1. **Live wiring**: build a `<Arch>ComputeModel` class per architecture and
   restructure `combine.py` to derive a real `NodeTileSpec` and call the
   model once per `dram_i` step (not once per run), driven by a real spike
   trace threaded through `run()`/`run_from_json()`.
2. **Locality analyzer**: given the address stream that a solved schedule's
   live wiring produces, compute stack-distance (reuse-distance) and
   footprint statistics in units of distinct weight lines, and classify
   the schedule's actual loop ordering against the paper's TITL/MITL/NISL
   categories (Table I of the "Neuromorphic Cache Design" draft).

Task 2 depends on Task 1 being wired end-to-end for at least the
architectures it's run against — it consumes real per-tile addresses in
solved-schedule order, not a synthetic permutation sweep.

## Non-goals (explicitly deferred)

- **Phi** — sixth architecture, nothing implemented yet (reconstruct/
  cycles/address), out of scope here.
- **Trace capture** — still consuming the already-captured
  `input_trace/loas/vgg16_T4_B1/` sample; no new capture or additional
  layers/models fetched.
- **Sweeping the canonical Table I permutations independently of the MIP
  solver** — the analyzer classifies whatever ordering the solved schedule
  actually used; it does not re-enumerate M0/N0/T orderings itself.
- **eventsim / contention-aware latency** — untouched by this work.
- Any change to the non-single-node (GB-present) combine.py path's
  numerical output — must remain byte-identical (regression bar, same as
  every prior pilot).

## Design

### 1. Shared tile-derivation helper (new)

Extracted from `DenseStaticComputeModel`'s existing per-dim formula
(`node_j = total_j // (spatial_factors[j] * noc_temporal[j] *
dram_temporal[j])`) plus `StepInfo`'s `_decode_dim`, into a small new
module:

```python
# src/snn_cosa/nocsim/schedule/tiles.py
def iter_node_tiles(schedule: Schedule, prob: SNNProb) -> Iterator[NodeTileSpec]:
    """Yield one NodeTileSpec per dram_i, in order, for single_node schedules.

    node_bound[dim]  = total[dim] // dram_total[dim]   (same formula
                        DenseStaticComputeModel already uses per-dim)
    tile_offset[dim] = _decode_dim(dram_i, schedule.dram_temporal_loops, dim)
                       * node_bound[dim]
    is_last_K        = True iff dim KH/KW/CIN's dram-level index is at its max
                        (dram_k_position(dram_i), already in StepInfo)
    """
```

This is the one place tile-index math lives; `combine.py` and the
locality analyzer both call it instead of re-deriving offsets themselves.
Scoped to the case the 5 archs actually run in (`arch.single_node=True`,
`noc_num_steps==1`) — `tile_offset`/`node_bound` only need to vary across
`dram_i`, matching how every pilot's `reconstruct_tile_sequence` already
reads `tile.tile_offset`/`tile.node_bound`.

### 2. `ArchComputeModel` Protocol gains `weight_addresses`

```python
class ArchComputeModel(Protocol):
    def format_input(self, trace: Any, tile: NodeTileSpec) -> Any: ...
    def compute_cycles(self, packed: Any, tile: NodeTileSpec) -> ComputeCycles: ...
    def weight_addresses(self, packed: Any, tile: NodeTileSpec) -> List[Any]:
        """Ordered weight addresses this tile touches (this arch's own
        address.py::event_to_address, wrapped). Not consumed by combine.py's
        transaction generator (which still uses byte-size accounting) --
        exists so the locality analyzer has one per-arch entry point for
        both timing and addressing, instead of reaching around the
        Protocol into each arch's raw address.py function."""
        ...
```

`DenseStaticComputeModel.weight_addresses` returns `[]` (no real address
notion for the static formula) — never called by the analyzer since it
only targets real archs.

### 3. Five `<Arch>ComputeModel` classes (new, one file each)

`src/snn_cosa/archmodels/{spinalflow,ptb,loas,gustavsnn,prosperity}/model.py`,
each a thin wrapper:

```python
class SpinalFlowComputeModel(ArchComputeModel):
    def format_input(self, trace, tile):
        return reconstruct_tile_sequence(trace, tile)          # events
    def compute_cycles(self, packed, tile):
        return ComputeCycles(mac_cycles=event_to_cycle(packed, tile), lif_cycles=None)
    def weight_addresses(self, packed, tile):
        return event_to_address(packed, tile)
```

PTB/LoAS/GustavSNN/Prosperity follow the same shape, each calling its own
arch's already-built functions (PTB's `format_input` returns the
`PTBReconstructed` pass1/pass2 pair; `compute_cycles` uses its existing
`max(access_cycle_count, compute_cycle_count)`; etc. — no new per-arch
algorithm work, this is pure plumbing over what's already verified).

### 4. `combine.py`: per-`dram_i` model calls, trace threading

Today (lines ~164-168): `model.compute_cycles(...)` is called once,
before the `dram_i` loop, and `mac_cyc`/`lif_cyc` are constant for the
whole run. Change: when `arch is not None and arch.single_node`, iterate
`iter_node_tiles(schedule, prob)` and call
`model.format_input(trace, tile)` / `model.compute_cycles(packed, tile)`
**inside** the `dram_i` loop, once per iteration, feeding that iteration's
`mac_cyc`/`lif_cyc` into that iteration's `mac_count`/`lif_count` calls.
When `arch` is `None` or `arch.single_node` is `False`, behavior is
unchanged (one upfront call) — this preserves the non-arch dense path's
existing byte-identical output with zero code-path duplication, since
`DenseStaticComputeModel.compute_cycles` ignores `tile` entirely and would
return the same numbers either way; the single-node/live-arch path is the
only one that actually needs per-tile variation.

`run()`/`run_from_json()` gain an optional `trace: Optional[np.ndarray] =
None` parameter, passed straight through to `combine()`, straight through
to `model.format_input(trace, tile)`. A small loader helper
(`archmodels/trace.py::load_layer_trace(meta_path, layer_name) ->
np.ndarray`) reads `input_trace/loas/<workload>/meta.json` +
`layer_XX_*.npy`, since no such loader exists in `snn_cosa` today (the 5
pilots' verification scripts each called `np.load` ad hoc).

### 5. Locality analyzer (`src/snn_cosa/locality/`)

```python
# stack_distance.py
def stack_distances(addresses: List[Any]) -> List[Optional[int]]:
    """For each access, the number of DISTINCT addresses referenced since
    the previous access to this same address (None for an address's first
    occurrence -- a cold miss, no finite reuse distance). O(n log n) via a
    Fenwick tree over "rank at last-seen position", matching the address
    counts these traces produce (hundreds-low thousands per solved
    schedule) -- no need for OS-trace-scale approximate reuse-distance
    algorithms here.
    """

def reuse_distance_histogram(distances: List[Optional[int]]) -> Dict[int, int]:
    """Bucket finite stack distances into a {distance: count} histogram."""

def footprint_curve(addresses: List[Any], max_window: Optional[int] = None) -> Dict[int, float]:
    """{window_size: avg_distinct_addresses_touched}, derived from the same
    stack-distance data (Xiang/Ding footprint-from-reuse-distance relation)
    -- the working-set-vs-window curve, directly answers "how many unique
    weight lines does an on-chip cache of this capacity need to hold this
    tile's reuse."""

# classify.py
def classify_schedule(schedule: Schedule) -> Dict[str, str]:
    """Inspect schedule.dram_temporal_loops' outer->inner ordering of
    T / M(=HO,WO collapsed into one slot) / N(=COUT) and return
    {"TITL": ..., "MITL": ..., "NISL": ..., "table1_row": Optional[str]}.

    Rule (reverse-derived from Table I's 7 rows -- the paper's prose is
    imprecise, this is what the table's own entries actually encode):
      TITL <- T's position:  innermost=Strong, middle=Medium, outermost=Weak
               (absent entirely, e.g. LoAS's fully-parallel T -> "N/A")
      NISL <- N's position:  innermost=Strong, middle=Medium, outermost=Weak
      MITL <- N's position, INVERTED: innermost=Weak, middle=Medium,
               outermost=Strong
    M's own position does not independently drive any of the three degrees
    (with only 3 permutation slots, T's and N's positions already
    determine M's by elimination -- Table I's data cannot distinguish an
    M-driven rule from "the slot T and N didn't take").

    Also reports which of Table I's 7 canonical rows the collapsed order
    matches (if any) and that row's attributed architecture, as a
    built-in sanity check -- e.g. GustavSNN's real solved schedule should
    land on row 1 (N0-M0-T) if the analyzer is implemented correctly. If
    HO/WO aren't adjacent in the permutation (so they can't collapse into
    one M slot), reports "non-canonical" instead of forcing a verdict.
    """
```

Plus a runner, `src/snn_cosa/locality/run_analysis.py`: given an arch name,
a solved schedule JSON, and a trace, walks `iter_node_tiles` +
`<Arch>ComputeModel.format_input`/`.weight_addresses` to build the
concatenated address stream in solved-schedule order, runs the three
functions above, and saves two matplotlib figures (reuse-distance
histogram, footprint curve) plus the `classify_schedule` verdict as a
small text/JSON summary, under `outputs/locality/<arch>_<workload>/`.

## File-level changes

```
src/snn_cosa/
├── archmodels/
│   ├── __init__.py                       MODIFIED — + weight_addresses to Protocol
│   ├── dense.py                          MODIFIED — + weight_addresses returning []
│   ├── trace.py                          NEW — load_layer_trace() helper
│   ├── spinalflow/model.py               NEW — SpinalFlowComputeModel
│   ├── ptb/model.py                      NEW — PTBComputeModel
│   ├── loas/model.py                     NEW — LoASComputeModel
│   ├── gustavsnn/model.py                NEW — GustavSNNComputeModel
│   └── prosperity/model.py               NEW — ProsperityComputeModel
├── nocsim/
│   ├── schedule/tiles.py                 NEW — iter_node_tiles()
│   ├── combine.py                        MODIFIED — per-dram_i model calls (single_node only)
│   └── sim.py                            MODIFIED — trace param passthrough
└── locality/
    ├── __init__.py                       MODIFIED — drop placeholder docstring
    ├── stack_distance.py                 NEW
    ├── classify.py                       NEW
    └── run_analysis.py                   NEW
```
Untouched: `transactions/`, `core/`, `parsers/`, `model/`,
`schedule/decode.py`/`buf_spatial.py`/`steps.py` (read, not modified —
`iter_node_tiles` composes their existing outputs).

## Verification plan

**Task 1 (per arch, same bar as every prior pilot):**
1. Zero-regression: re-run `configs/arch/snn_arch_single_node.yaml` +
   `sim_demo.yaml` with `compute_model=None`/no trace — byte-identical
   CSV to before this change.
2. Each `<Arch>ComputeModel`, run against its own already-solved YAML
   (`spinalflow.yaml`/`ptb.yaml`/`loas.yaml`/`gustavsnn.yaml`/
   `prosperity.yaml`, all pre-existing from the earlier pilots) + the real
   `vgg16_T4_B1` trace layer each pilot already used — confirm per-`dram_i`
   `mac_cycles` now varies across tiles (proof the live per-tile call is
   actually firing, not just returning one constant), and that summed
   cycles/addresses match what the standalone pilot verification already
   established for that arch.
3. Full `nocsim.sim` run end-to-end with a real `ArchComputeModel` +
   trace, confirm it exits clean and produces a non-trivial `tc.csv`.

**Task 2 — every step below stores its output to disk and is presented
for explicit user review, not just self-verified and reported as "done"
(per the PTB sweep precedent, [[project_archmodel_cycle_plan]]'s Task 6):**
1. `stack_distances`/`footprint_curve` unit-verified against a hand-built
   short address sequence with known-by-hand distances — the fixture,
   the hand-computed expected distances, and the function's actual output
   saved together (e.g. `outputs/locality/unit_check.json`) for review,
   not just asserted in a scratch script's stdout.
2. `classify_schedule` run against all 5 archs' real solved schedules
   (not just 2) — each arch's collapsed permutation order, its
   TITL/MITL/NISL verdict, and its matched Table I row (or
   "non-canonical") saved to `outputs/locality/classify_summary.json` for
   review. Includes an explicit pass/fail note on whether each arch's
   verdict matches the row Table I itself attributes to that arch's paper
   (GustavSNN->row1, SpinalFlow->row2, PTB->row5, LoAS->row7; Prosperity
   has no fixed row since [11]/[12] share row4 and Prosperity's own
   solved schedule may or may not reproduce it).
3. End-to-end run for all 5 archs (not just SpinalFlow) against the real
   trace: reuse-distance histogram + footprint curve figures + the
   classification JSON, all saved under
   `outputs/locality/<arch>_vgg16_T4_B1_<layer>/`, presented together for
   review rather than described in prose.