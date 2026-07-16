"""Prosperity cycle count: driven by ProSparsity row-prefix compression --
one cycle per residual ('pattern') spike, after each row reuses its
chosen Prefix row's already-computed partial sum (Wei, Guo, Cheng, Li,
Yang, Li & Chen, "Prosperity: Accelerating Spiking Neural Networks via
Product Sparsity", HPCA 2025).

Mirrors SpinalFlow's/LoAS's/GustavSNN's archmodels/<arch>/cycles.py
structure:

    total_cycle_count = max(access_cycle_count, compute_cycle_count)

though for Prosperity (like SpinalFlow/LoAS/GustavSNN) access_cycle_count
and compute_cycle_count always evaluate to the SAME quantity -- the
paper's own Processor design (Section V-E, Fig. 5(d)) issues exactly one
weight-fetch-and-accumulate cycle per residual spike bit: Step 10 (load
weight, one row of the K x N weight sub-matrix, decoded by bit-scan-
forward on the ProSparsity pattern) and Step 11 (accumulate into the
partial sum, across all N=128 output columns in parallel via the 128-PE
array) happen together, one residual bit per cycle, with no separate
access-vs-compute bottleneck to distinguish.

    cycle_count = sum over all rows in this tile of sum(row.pattern)

This is the pilot's explicit steady-state abstraction: the paper's own
ProSparsity *processing* phase (Detector/Pruner/Dispatcher identifying
each row's Prefix, m+4 cycles per tile, Section VI-A) is entirely hidden
by the *computation* phase of the PREVIOUS tile via the paper's own
inter-phase pipeline (Section VI-B: "the ProSparsity processing phase of
a tile is perfectly overlapped by the computation phase of the previous
tile... except for the first tile phase, which has a minor impact") --
this deployment counts only the steady-state computation-phase cycles,
the same "abstract away fixed pipeline fill/drain overhead" treatment
PTB/GustavSNN already apply to their own systolic/wave latencies.

COUT contributes ZERO incremental cycle cost, same treatment as
SpinalFlow/LoAS/GustavSNN -- Section V-A states this explicitly ("the
number of n has no impact on ProSparsity"): the 128-wide PE array
accumulates across the tile's whole assigned COUT range in the same
single cycle that consumes one residual spike bit, regardless of how
wide that COUT range is.
"""

from __future__ import annotations

from .. import NodeTileSpec
from .reconstruct import ProsperityReconstructed


def _total_pattern_spikes(reconstructed: ProsperityReconstructed) -> int:
    return sum(sum(row.pattern) for row in reconstructed.rows)


def access_cycle_count(reconstructed: ProsperityReconstructed) -> int:
    return _total_pattern_spikes(reconstructed)


def compute_cycle_count(reconstructed: ProsperityReconstructed, tile: NodeTileSpec) -> int:
    return _total_pattern_spikes(reconstructed)


def event_to_cycle(reconstructed: ProsperityReconstructed, tile: NodeTileSpec) -> int:
    return max(access_cycle_count(reconstructed), compute_cycle_count(reconstructed, tile))
