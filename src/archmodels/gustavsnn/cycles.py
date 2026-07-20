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
    submatrices = sorted(reconstructed.submatrices, key=lambda sm: sm.piece_idx)
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
