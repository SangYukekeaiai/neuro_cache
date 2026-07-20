# Arch-specific cycle count from real input traces — SpinalFlow pilot

## Context

`snn_cosa`'s NoC transaction simulator (`src/snn_cosa/nocsim/combine.py`)
currently derives per-node MAC/LIF cycle counts from a purely analytical,
dense-tile-size formula (`_pe_cycles`/`_lif_cycles`, product of node-level
loop factors — no notion of real spike sparsity). This is Part 2 of a
larger effort (Part 1 — replacing the hand-fixed single-node schedule with
a real MIP `node_dim_capacity` constraint — is done; see
`PLAN_single_node.md`).

Goal: replace that static formula with a data-dependent cycle count derived
from a real SNN spike trace, per architecture (SpinalFlow first, then
PTB and others). This spec covers the SpinalFlow pilot only.

## Non-goals (explicitly deferred)

- Trace **capture** (`neuro_cache/capture/`) — out of scope. We consume an
  already-captured LoAS trace as sample data; we do not build a capture
  pipeline in `snn_cosa`.
- The locality/cache analyzer (TITL/MITL/NISL classification, from the
  attached ASPLOS draft's §III-C) — a placeholder package only, no logic.
- Any architecture other than SpinalFlow (PTB, LoAS's own compute model,
  Prosperity, Phi, GustavSNN) — the plugin interface is designed to
  generalize to them later, but only SpinalFlow is implemented now.
- Persisting an ordered weight-address log (`weight_trace.py` from an
  earlier draft of this design) — dropped; nothing consumes it yet.

## Design

**Per-arch plugin protocol** (`src/snn_cosa/archmodels/__init__.py`):
```python
@dataclass(frozen=True)
class NodeTileSpec:
    dram_i: int
    node_bound: Dict[int, int]    # dim -> node-level bound
    tile_offset: Dict[int, int]   # dim -> starting index into the real trace
    is_last_K: bool

class ArchComputeModel(Protocol):
    def format_input(self, trace: np.ndarray, tile: NodeTileSpec) -> ArchPackedInput: ...
    def compute_cycles(self, packed: ArchPackedInput, tile: NodeTileSpec) -> ComputeCycles: ...

@dataclass
class ComputeCycles:
    mac_cycles: int
    lif_cycles: int
```

`combine.py`'s `_pe_cycles`/`_lif_cycles` become the default
`ArchComputeModel` (`archmodels/dense.py`, today's formula unchanged,
selected automatically when no real arch model is passed —
`compute_model: Optional[ArchComputeModel] = None`, zero regression on the
existing path).

**SpinalFlow plugin** (`src/snn_cosa/archmodels/spinalflow/`):
- `reconstruct.py` — `reconstruct_tile_sequence`: for a tile's receptive
  field, scan `(t, cin, kh, kw)`, collect every `(t, neuron_id)` where the
  real trace has a spike, chronologically sort by `t` → the "spine".
  Ported/adapted from `neuro_cache/sim/permutation/spinalflow_permutation.py`
  + `spinalflow_compute.py`.
- `cycles.py` — `event_to_cycle`: 1 spine event = 1 cycle (trivial, since
  reconstruction already flattened time).
- `address.py` — `event_to_address`: fixed `(kh,kw,cin)` per event →
  contiguous weight burst across `cout[0:128]`.

**Sample data**: `neuro_cache/input_trace/loas/` copied verbatim into
`snn_cosa/input_trace/loas/` (11MB, `vgg16_T4_B1/` + `resnet19_T4_B1/`,
each layer a `[T,B,Cin,Hin,Win]` binary `.npy` + `meta.json`). Used purely
as sample spike data to drive SpinalFlow's reconstruction — LoAS's own
accelerator dataflow is not modeled here.

## File-level changes

```
snn_cosa/
├── input_trace/loas/                   NEW — copied from neuro_cache/input_trace/loas
└── src/snn_cosa/
    ├── archmodels/                     NEW
    │   ├── __init__.py                     Protocol + NodeTileSpec + dataclasses
    │   ├── dense.py                        fallback, today's formula refactored behind Protocol
    │   └── spinalflow/
    │       ├── reconstruct.py
    │       ├── cycles.py
    │       └── address.py
    ├── nocsim/
    │   ├── combine.py                  MODIFIED — optional compute_model param
    │   └── sim.py                      MODIFIED — compute_model passthrough
    └── locality/                       NEW — empty placeholder package
```
Untouched: `schedule/`, `transactions/`, `core/`, `parsers/arch.py`,
`model/constraints/node_capacity.py`.

## Verification plan

Same bar as Part 1 (`PLAN_single_node.md`): re-run the existing
`snn_arch_single_node.yaml` end-to-end path with `compute_model=None` and
confirm byte-identical output to before this change (regression check).
Then run it with the SpinalFlow model + a real LoAS-trace layer and confirm
`mac_cycles` reflects real spike count (fewer cycles than the dense
formula, proportional to the layer's actual spike rate), and that
reconstructed spine length matches the trace's true spike count in that
tile's receptive field.
