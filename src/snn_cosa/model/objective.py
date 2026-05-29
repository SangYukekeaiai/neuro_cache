#!/usr/bin/env python3
"""Compatibility wrapper for objective builders.

New objective implementations live under :mod:`snn_cosa.model.objectives`.
"""

from snn_cosa.model.objectives import build_compute_objective, build_objective

__all__ = ["build_compute_objective", "build_objective"]
