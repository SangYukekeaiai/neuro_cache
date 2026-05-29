#!/usr/bin/env python3
"""Step 6 – Log-scale tile-size linear expressions for SNN scheduling.

All sizes are expressed in log₂ space so that multiplicative tile products
become additive linear expressions compatible with Gurobi.

One quantity family is returned (no Gurobi constraints are added here):

  buf_util[(v, mem_idx)] log₂ of the cumulative tile for variable v up to
                         the boundary of memory level mem_idx.
                         A-weighted: only dimensions where A[j][v]==1 count.
                         mem_idx:  0 = NodeLevel   (objective/metadata only)
                                   1 = NoCLevel    (capacity-constrained)
                                   2 = OffChip     (unbounded, not constrained)

Loop-level ranges contributing to each memory boundary
-------------------------------------------------------
  NodeLevel  boundary:  levels 0 … gb_start_level − 1      (just level 0)
  NoCLevel   boundary:  levels 0 … dram_start − 1
  OffChip    boundary:  all levels                          (not added here)

Temporal log-factor expressions (l[i]) are computed in traffic/temporal.py,
not here.
"""

import logging
import numpy as np
from typing import Dict

from snn_cosa.parsers.layer import SNNProb
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.model.constants import NUM_VARS, _A

logger = logging.getLogger(__name__)

# Symbolic memory-level indices (matches _B column order)
MEM_NODE = 0   # NodeLevel  – innermost,  1024 instances
MEM_NOC  = 1   # NoCLevel   – global buf, 1 instance


def compute_log_sizes(
    x: Dict,
    prob: SNNProb,
    bitwidths: SNNBitwidths,
    gb_start_level: int,
    dram_start: int,
) -> Dict:
    """Return log₂-scale cumulative tile-size expressions (no constraints added).

    Each entry is log₂(bytes) = log₂(BW[v]/8) + log₂(element_count), so that
    the result can be compared directly to log₂(memory_capacity_in_bytes).

    Args:
        x:              X decision-variable dict from create_schedule_vars.
        prob:           Parsed SNN layer (prime-factor lists).
        bitwidths:      Per-variable bit-width config.
        gb_start_level: First NoCLevel permutation slot (loop level 0 = NodeLevel).
        dram_start:     First OffChip permutation slot.

    Returns:
        buf_util – {(v, mem_idx): LinExpr}  log₂(bits) per variable per memory.
                   buf_util[(v, MEM_NODE)] also serves as the NodeLevel traffic
                   contribution (CoSA's data_size[v], bit-width included).
    """
    pf = prob.prob_factors
    BW = [bitwidths.bw_weight, bitwidths.bw_psum, bitwidths.bw_vmem]
    buf_util: Dict = {}

    # ------------------------------------------------------------------
    # buf_util[(v, mem_idx)] – cumulative log-tile for capacity checks
    #
    #    Loop-level upper bounds (exclusive) per memory level:
    #      MEM_NODE: range(0, gb_start_level)   → level 0 only  (gb_start=1)
    #      MEM_NOC:  range(0, dram_start)        → levels 0 … dram_start-1
    #
    #    Both spatial (k=0) and temporal (k=1) assignments enlarge the tile.
    #    A[j][v] masks out dimensions that do not affect variable v's size.
    # ------------------------------------------------------------------
    _mem_upper: Dict = {
        MEM_NODE: gb_start_level,
        MEM_NOC:  dram_start,
    }

    for v in range(NUM_VARS):
        for mem_idx, upper in _mem_upper.items():
            size = np.log2(BW[v] / 8.0)   # constant byte-width offset
            for i in range(upper):
                for j, f_j in enumerate(pf):
                    for n in range(len(f_j)):
                        coef = np.log2(f_j[n]) * _A[j][v]
                        if coef == 0.0:
                            continue
                        size += coef * (x[(i, j, n, 0)] + x[(i, j, n, 1)])
            buf_util[(v, mem_idx)] = size

    logger.debug("compute_log_sizes: buf_util entries=%d", len(buf_util))
    return buf_util
