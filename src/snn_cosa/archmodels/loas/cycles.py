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