#!/usr/bin/env python3
"""Step 5a – Structural constants for the SNN scheduling problem.

Contains three categories of constants consumed by the MIP solver:

  1. Variable indices and metadata  (VAR_*, NUM_VARS, VAR_NAMES, TRAFFIC_MULT)
  2. A matrix – dim-to-variable buffer-size relation
  3. B matrix – variable-to-memory-level relation, and derived Z matrix

A matrix convention (matches CoSA)
------------------------------------
A[j][v] = 1  iff dimension j directly contributes to the buffer SIZE of
              variable v.  "Directly" means the tile count for dim j scales
              the number of elements stored for v.  Accumulation effects on
              traffic are handled separately via the y auxiliary variable.

  dim  / var   weight  psum  vmem
  KH   (j=0)     1      0     0    weight = KH × KW × CIN × COUT
  KW   (j=1)     1      0     0
  CIN  (j=2)     1      0     0
  COUT (j=3)     1      1     1    psum = HO × WO × COUT × T
  HO   (j=4)     0      1     1    vmem = HO × WO × COUT  (T-independent)
  WO   (j=5)     0      1     1
  T    (j=6)     0      1     0    psum is indexed over T; vmem is not

B matrix convention (matches CoSA)
------------------------------------
B[v][i] = 1  iff variable v is present at memory level i.
For SNN there is no bypass: all three variables exist at all three levels.

  var    / level  NodeLevel  NoCLevel  OffChip
  weight (v=0)       1          1        1
  psum   (v=1)       1          1        1
  vmem   (v=2)       1          1        1

Z matrix (derived from B)
------------------------------------
Z[v][i][i'] = 1  iff B[v][i] == 1  AND  i' <= i.
Historically used for cumulative memory-visibility accounting: when the
permutation cursor is at position i', Z selects only the memory levels at i'
or deeper that actually store variable v.
"""

from typing import List

# ---------------------------------------------------------------------------
# 1. Variable indices and metadata
# ---------------------------------------------------------------------------

VAR_WEIGHT: int = 0
VAR_PSUM:   int = 1
VAR_VMEM:   int = 2
NUM_VARS:   int = 3

VAR_NAMES: List[str] = ["weight", "psum", "vmem"]

# Traffic multipliers:
#   weight – load only        → multiplier 1
#   psum   – load + store     → multiplier 2
#   vmem   – load + store     → multiplier 2
TRAFFIC_MULT: List[int] = [1, 2, 2]

# ---------------------------------------------------------------------------
# 2. A matrix  [NUM_DIMS × NUM_VARS]
# ---------------------------------------------------------------------------
# Rows indexed by dimension (j): KH=0, KW=1, CIN=2, COUT=3, HO=4, WO=5, T=6
# Cols indexed by variable  (v): weight=0, psum=1, vmem=2

_A: List[List[int]] = [
    [1, 0, 0],  # KH   – weight only
    [1, 0, 0],  # KW   – weight only
    [1, 0, 0],  # CIN  – weight only
    [1, 1, 1],  # COUT – weight, psum, vmem
    [0, 1, 1],  # HO   – psum, vmem
    [0, 1, 1],  # WO   – psum, vmem
    [0, 1, 0],  # T    – psum only (vmem size is independent of T)
]

# ---------------------------------------------------------------------------
# 3. B matrix  [NUM_VARS × NUM_MEM_LEVELS]  and derived Z matrix
# ---------------------------------------------------------------------------
# Rows indexed by variable  (v): weight=0, psum=1, vmem=2
# Cols indexed by mem level (i): NodeLevel=0, NoCLevel=1, OffChip=2

_B: List[List[int]] = [
    [1, 1, 1],  # weight – stored at all three levels
    [1, 1, 1],  # psum   – stored at all three levels
    [1, 1, 1],  # vmem   – stored at all three levels
]


def build_Z(B: List[List[int]], num_mems: int) -> List[List[List[int]]]:
    """Derive the cumulative Z matrix from B.

    Z[v][i][i'] = 1  iff  B[v][i] == 1  and  i' <= i.

    Interpretation: when the permutation cursor sits at level i', only memory
    levels at or deeper than i' that actually store variable v are "active"
    for buffer-utilisation accounting.

    Args:
        B:        Variable-to-memory-level matrix, shape [num_vars][num_mems].
        num_mems: Number of memory levels.

    Returns:
        Z of shape [num_vars][num_mems][num_mems].

    Example (all-ones B, num_mems=3)::

        Z[v][2][0] = 1   (level 2 stores v, cursor 0 <= 2)
        Z[v][0][2] = 0   (level 0 stores v, but cursor 2 > 0)
    """
    num_vars = len(B)
    Z: List[List[List[int]]] = []
    for v in range(num_vars):
        Z_v: List[List[int]] = []
        for i in range(num_mems):
            row = [0] * num_mems
            if B[v][i] == 1:
                for i_prime in range(i + 1):
                    row[i_prime] = 1
            Z_v.append(row)
        Z.append(Z_v)
    return Z
