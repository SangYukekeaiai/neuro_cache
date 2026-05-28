#!/usr/bin/env python3
"""Step 4 – Parse SNN mapping-space dimensions and permutations.

The SNNMapspace is constructed from a YAML config and then bound to a
(SNNProb, SNNArch) pair via ``init()``.  After ``init()`` the object exposes:

  factor_space          – for each of the 7 prob dimensions, a list of integer
                          bounds equal to the total number of valid level-
                          assignment choices (temporal levels + spatial levels)
                          for each prime factor of that dimension.
  valid_spatial_levels  – list of (mem_level_idx, max_spatial_factor) pairs
                          derived from arch.S for levels where S > 1.
  valid_spatial_factors – per-level maximum spatial factor (length = mem_levels).
  total_factor_choices  – mem_levels + len(valid_spatial_levels).

Expected mapspace YAML format::

    mapspace:
      spatial_dims: [COUT, HO, WO, T]   # dims eligible for spatial splitting

All seven dimensions may appear in spatial_dims. The solver applies
different traffic rules depending on whether the spatially-split dimension
is a reduction dim (KH/KW/CIN → psum-reduction communication) or a free
dim (COUT/HO/WO/T → unicast/multicast).
"""

import copy
import logging
import pathlib
from typing import Dict, List, Optional, Tuple

import yaml

from snn_cosa.parsers.layer import SNNProb, _DIM_NAMES
from snn_cosa.parsers.arch import SNNArch

logger = logging.getLogger(__name__)

# org indices (matches CoSA convention)
ORG_SPATIAL   = 0
ORG_TEMPORAL  = 1

# config indices inside the mapspace 4-D array
CFG_PERM   = 0
CFG_FACTOR = 1


def parse_snn_mapspace(mapspace_path: pathlib.Path) -> "SNNMapspace":
    """Parse SNN mapspace config from *mapspace_path*.

    Call ``init(prob, arch)`` on the returned object before use.

    Raises:
        FileNotFoundError: If *mapspace_path* does not exist.
        ValueError: If the YAML lacks a top-level ``mapspace`` key, or if an
                    unknown dimension name appears in ``spatial_dims``.
    """
    return SNNMapspace(mapspace_path)


class SNNMapspace:
    """SNN mapping space: factor and permutation search space.

    Lifecycle::

        ms = SNNMapspace(mapspace_path)
        ms.init(prob, arch)
        # now ms.factor_space, ms.get_default_perm(), etc. are usable

    Attributes (available after ``init``):
        prob (SNNProb):                  Bound layer problem.
        arch (SNNArch):                  Bound hardware arch.
        spatial_dim_indices (List[int]): Indices of dims eligible for spatial split.
        valid_spatial_levels (List[Tuple[int,int]]):
                                         (mem_level_idx, max_factor) pairs where
                                         arch.S[mem_level_idx] > 1.
        valid_spatial_factors (List[int]): Per-level maximum spatial factor
                                           (length = arch.mem_levels).
        total_factor_choices (int):      mem_levels + len(valid_spatial_levels).
        factor_space (List[List[int]]):  For each prob dim, a list of bounds
                                         (one per prime factor of that dim);
                                         each bound == total_factor_choices,
                                         or 1 when the prime factor itself is 1.
        unscheduled_prob_factors (List[List[int]]): Copy of prob.prob_factors
                                         with any pre-assigned spatial factors
                                         removed (populated during init).
        path (pathlib.Path):             Resolved path to the mapspace YAML.
    """

    def __init__(self, mapspace_path: pathlib.Path) -> None:
        self.path = pathlib.Path(mapspace_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"SNNMapspace: config not found: {self.path}"
            )

        with open(self.path, "r") as f:
            raw = yaml.safe_load(f)

        if "mapspace" not in raw:
            raise ValueError(
                f"SNNMapspace: YAML at {self.path} must have a top-level 'mapspace' key"
            )
        ms = raw["mapspace"]

        # Parse eligible spatial dimensions by name
        spatial_names: List[str] = ms.get("spatial_dims", [])
        valid_names = set(_DIM_NAMES)
        for name in spatial_names:
            if name not in valid_names:
                raise ValueError(
                    f"SNNMapspace: unknown dimension '{name}' in spatial_dims "
                    f"(valid: {_DIM_NAMES}) in {self.path}"
                )
        self._spatial_dim_names: List[str] = spatial_names

        # These are populated by init()
        self.prob: Optional[SNNProb] = None
        self.arch: Optional[SNNArch] = None
        self.spatial_dim_indices: List[int] = []
        self.valid_spatial_levels: List[Tuple[int, int]] = []
        self.valid_spatial_factors: List[int] = []
        self.total_factor_choices: int = 0
        self.factor_space: List[List[int]] = []
        self.unscheduled_prob_factors: List[List[int]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(self, prob: SNNProb, arch: SNNArch) -> None:
        """Bind to *prob* and *arch* and build the factor / permutation spaces.

        Args:
            prob: Parsed SNN layer dimensions (SNNProb).
            arch: Parsed SNN memory hierarchy (SNNArch).
        """
        self.prob = prob
        self.arch = arch

        # Resolve spatial dim names -> indices
        name_to_idx: Dict[str, int] = prob.prob_name_idx_dict
        self.spatial_dim_indices = [name_to_idx[n] for n in self._spatial_dim_names]

        # Derive valid spatial levels: levels where arch.S > 1
        self.valid_spatial_levels = [
            (lvl_idx, arch.S[lvl_idx])
            for lvl_idx in range(arch.mem_levels)
            if arch.S[lvl_idx] > 1
        ]

        # Per-level spatial factor cap (length = mem_levels, default 1)
        self.valid_spatial_factors = [1] * arch.mem_levels
        for lvl_idx, max_factor in self.valid_spatial_levels:
            self.valid_spatial_factors[lvl_idx] = max_factor

        # Total choices for each prime factor:
        #   temporal levels (mem_levels) + spatial levels (len(valid_spatial_levels))
        self.total_factor_choices = arch.mem_levels + len(self.valid_spatial_levels)

        # Build factor_space: for each prob dim, one bound per prime factor
        self.unscheduled_prob_factors = copy.deepcopy(prob.prob_factors)
        self.factor_space = []
        for prob_factors_j in self.unscheduled_prob_factors:
            if len(prob_factors_j) == 1 and prob_factors_j[0] == 1:
                bounds = [1]  # trivial dim: only one choice (assign anywhere -> no-op)
            else:
                bounds = [self.total_factor_choices] * len(prob_factors_j)
            self.factor_space.append(bounds)

        logger.debug(
            "SNNMapspace.init: spatial_dims=%s  valid_spatial_levels=%s  "
            "total_factor_choices=%d  factor_space_shape=%s",
            self._spatial_dim_names,
            self.valid_spatial_levels,
            self.total_factor_choices,
            [len(b) for b in self.factor_space],
        )

    def get_default_perm(self) -> List[List[int]]:
        """Return the default inner-to-outer permutation at every memory level.

        The default ordering is [0, 1, 2, 3, 4, 5, 6] (KH innermost, T outermost)
        at every level.

        Returns:
            List of length ``arch.mem_levels``, each element being a list of
            length ``prob.prob_levels`` with dimension indices 0..6.
        """
        self._check_init()
        return [
            list(range(self.prob.prob_levels))
            for _ in range(self.arch.mem_levels)
        ]

    def get_default_factor(self) -> List[List[int]]:
        """Return the default factor config: every prime factor assigned to OffChip.

        Returns:
            Nested list matching the shape of ``factor_space``, with every
            entry set to ``arch.mem_levels - 1`` (index of OffChip).
        """
        self._check_init()
        outermost = self.arch.mem_levels - 1
        return [
            [outermost] * len(bounds)
            for bounds in self.factor_space
        ]

    def is_spatial_dim(self, dim_idx: int) -> bool:
        """Return True if *dim_idx* is eligible for spatial splitting."""
        return dim_idx in self.spatial_dim_indices

    def print(self) -> None:
        self._check_init()
        print(f"SNNMapspace  path={self.path}")
        print(f"  spatial_dims : {self._spatial_dim_names}")
        print(f"  valid_spatial_levels : {self.valid_spatial_levels}")
        print(f"  total_factor_choices : {self.total_factor_choices}")
        for j, (bounds, name) in enumerate(
            zip(self.factor_space, self.prob.prob_idx_name_dict.values())
        ):
            print(f"  factor_space[{j}] {name:5s}: {bounds}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_init(self) -> None:
        if self.prob is None or self.arch is None:
            raise RuntimeError(
                "SNNMapspace.init(prob, arch) must be called before use"
            )
