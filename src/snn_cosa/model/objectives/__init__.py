"""Objective builders for SNN CoSA scheduling."""

from snn_cosa.model.objectives.combined import build_objective
from snn_cosa.model.objectives.compute import build_compute_objective

__all__ = ["build_objective", "build_compute_objective"]
