#!/usr/bin/env python3
"""Step 1 – Parse SNN layer dimensions from a problem YAML.

Dimension ordering (matches GEMM-style decomposition):
  idx 0 -> KH    (kernel height,  reduction)
  idx 1 -> KW    (kernel width,   reduction)
  idx 2 -> CIN   (input channel,  reduction)
  idx 3 -> COUT  (output channel, free)
  idx 4 -> HO    (output height,  free)
  idx 5 -> WO    (output width,   free)
  idx 6 -> T     (timestep,       free)

GEMM equivalents:
  K = KH * KW * CIN   (reduction dimensions)
  N = COUT
  M = HO * WO
  T = T

Variables modeled:
  weight[KH, KW, CIN, COUT]  -- load-only
  psum  [HO, WO, COUT, T]    -- load+store, reduced over KH, KW, CIN
  vmem  [HO, WO, COUT]       -- load+store, carried across T only
"""

import logging
import math
import pathlib
from typing import Dict, FrozenSet, List

import yaml

logger = logging.getLogger(__name__)

# Dimension indices for the seven SNN loop bounds
DIM_KH   = 0
DIM_KW   = 1
DIM_CIN  = 2
DIM_COUT = 3
DIM_HO   = 4
DIM_WO   = 5
DIM_T    = 6

# Ordered list of dimension names; index == DIM_* constant
_DIM_NAMES: List[str] = ["KH", "KW", "CIN", "COUT", "HO", "WO", "T"]

# Reduction dimensions (accumulated over when computing a psum tile)
SNN_REDUCTION_DIMS: FrozenSet[int] = frozenset([DIM_KH, DIM_KW, DIM_CIN])


def _get_prime_factors(value: int) -> List[int]:
    """Return sorted list of prime factors (with repetition) for *value*."""
    factors: List[int] = []
    while value % 2 == 0:
        factors.append(2)
        value //= 2
    for i in range(3, int(math.sqrt(value)) + 1, 2):
        while value % i == 0:
            factors.append(i)
            value //= i
    if value > 2:
        factors.append(value)
    if not factors:
        factors.append(1)
    return factors


def parse_snn_layer(prob_path: pathlib.Path) -> "SNNProb":
    """Parse SNN layer dimensions from *prob_path* and return an SNNProb.

    Args:
        prob_path: Path to a YAML file with a ``problem`` mapping that must
                   contain keys ``KH``, ``KW``, ``CIN``, ``COUT``, ``HO``,
                   ``WO``, and ``T``.

    Returns:
        SNNProb populated with validated dimensions and prime-factor lists.

    Raises:
        ValueError: If any required dimension is absent from the file.
        FileNotFoundError: If *prob_path* does not exist.
    """
    return SNNProb(prob_path)


class SNNProb:
    """SNN layer problem dimensions parsed from a YAML config.

    Expected YAML format::

        problem:
          KH: 3
          KW: 3
          CIN: 64
          COUT: 128
          HO: 56
          WO: 56
          T: 16
          shape: snn-layer

    Attributes:
        prob (Dict):            Raw ``problem`` dict from the YAML file.
        prob_bound (List[int]): Length-7 list ``[KH, KW, CIN, COUT, HO, WO, T]``.
        prob_factors (List[List[int]]): Prime factors for each dimension.
        prob_idx_name_dict (Dict[int, str]): Dimension index -> name.
        prob_name_idx_dict (Dict[str, int]): Dimension name -> index.
        reduction_dims (FrozenSet[int]): Indices of reduction dimensions.
        prob_levels (int):      Number of loop dimensions (7).
        path (pathlib.Path):    Resolved path to the source YAML.
    """

    _DIM_NAMES: List[str] = _DIM_NAMES

    def __init__(self, prob_path: pathlib.Path) -> None:
        self.prob_idx_name_dict: Dict[int, str] = {
            i: name for i, name in enumerate(self._DIM_NAMES)
        }
        self.prob_name_idx_dict: Dict[str, int] = {
            name: i for i, name in enumerate(self._DIM_NAMES)
        }

        self.prob_levels: int = len(self._DIM_NAMES)
        self.prob_bound: List[int] = [-1] * self.prob_levels
        self.prob_factors: List[List[int]] = [[] for _ in range(self.prob_levels)]
        self.reduction_dims: FrozenSet[int] = SNN_REDUCTION_DIMS

        self.path = pathlib.Path(prob_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"SNNProb: config not found: {self.path}")

        with open(self.path, "r") as f:
            raw = yaml.safe_load(f)

        if "problem" not in raw:
            raise ValueError(
                f"SNNProb: YAML at {self.path} must have a top-level 'problem' key"
            )
        self.prob: Dict = raw["problem"]

        for key, value in self.prob.items():
            if key == "shape":
                continue
            if key not in self.prob_name_idx_dict:
                logger.warning("SNNProb: unknown key '%s' in %s -- skipped", key, self.path)
                continue
            idx = self.prob_name_idx_dict[key]
            self.prob_bound[idx] = int(value)
            self.prob_factors[idx] = _get_prime_factors(int(value))

        missing = [
            self._DIM_NAMES[i]
            for i, v in enumerate(self.prob_bound)
            if v == -1
        ]
        if missing:
            raise ValueError(
                f"SNNProb: missing required dimension(s) {missing} in {self.path}"
            )

    def config_str(self) -> str:
        """Return a compact string that uniquely identifies this layer shape."""
        return "_".join(str(v) for v in self.prob_bound)

    def is_reduction_dim(self, dim_idx: int) -> bool:
        """Return True if *dim_idx* is a reduction (accumulation) dimension."""
        return dim_idx in self.reduction_dims

    def print(self) -> None:
        header = ["Dim", "Bound", "Prime factors"]
        rows = [
            (self.prob_idx_name_dict[j], self.prob_bound[j],
             " × ".join(str(f) for f in self.prob_factors[j]))
            for j in range(self.prob_levels)
        ]
        print(f"  {'Dim':<6}  {'Bound':>6}  Prime factors")
        print(f"  {'─'*6}  {'─'*6}  {'─'*20}")
        for name, bound, factors in rows:
            tag = " (reduction)" if self.prob_name_idx_dict[name] in self.reduction_dims else ""
            print(f"  {name:<6}  {bound:>6}  {factors}{tag}")