#!/usr/bin/env python3
"""Parse NodeLevel mapping constraints from a dataflow YAML."""

from __future__ import annotations

import pathlib
from typing import Dict, Optional

import yaml

from parsers.arch import SNNArch


_VALID_DIM_NAMES = ["KH", "KW", "CIN", "COUT", "HO", "WO", "T"]
FULL = "full"


def parse_snn_dataflow(dataflow_path: pathlib.Path) -> "SNNDataflow":
    return SNNDataflow(dataflow_path)


class SNNDataflow:
    """Complete per-dimension NodeLevel mapping specification.

    A dimension value is a positive temporal cap, ``full`` for complete
    temporal residency, or ``{"spatial": N}`` for PE-parallel fanout.
    Dimensions omitted from the mapping are barred from NodeLevel.
    """

    def __init__(self, dataflow_path: pathlib.Path) -> None:
        self.path = pathlib.Path(dataflow_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"SNNDataflow: dataflow config not found: {self.path}"
            )

        with open(self.path, "r") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict) or "dataflow" not in raw:
            raise ValueError(
                f"SNNDataflow: YAML at {self.path} must have a top-level "
                f"'dataflow' key"
            )
        dataflow = raw["dataflow"]
        if not isinstance(dataflow, dict):
            raise ValueError(
                f"SNNDataflow: dataflow must be a mapping in {self.path}"
            )

        capacity = dataflow.get("node_dim_capacity")
        if not isinstance(capacity, dict):
            raise ValueError(
                f"SNNDataflow: dataflow.node_dim_capacity must be a mapping "
                f"in {self.path}"
            )

        self.node_dim_capacity: Dict[str, object] = {}
        spatial_split: Dict[str, int] = {}
        for dim_name, value in capacity.items():
            if dim_name not in _VALID_DIM_NAMES:
                raise ValueError(
                    f"SNNDataflow: unknown dimension '{dim_name}' "
                    f"(valid: {_VALID_DIM_NAMES}) in {self.path}"
                )
            if value is None:
                raise ValueError(
                    f"SNNDataflow: node_dim_capacity.{dim_name} must use "
                    f"'full', not null, in {self.path}"
                )
            if value == FULL:
                self.node_dim_capacity[dim_name] = FULL
                continue
            if isinstance(value, dict):
                if set(value) != {"spatial"}:
                    raise ValueError(
                        f"SNNDataflow: node_dim_capacity.{dim_name} mapping "
                        f"must contain only 'spatial' in {self.path}"
                    )
                factor = value["spatial"]
                if (
                    not isinstance(factor, int)
                    or isinstance(factor, bool)
                    or factor <= 0
                ):
                    raise ValueError(
                        f"SNNDataflow: node_dim_capacity.{dim_name}.spatial "
                        f"must be a positive integer in {self.path}"
                    )
                self.node_dim_capacity[dim_name] = {"spatial": factor}
                spatial_split[dim_name] = factor
                continue
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(
                    f"SNNDataflow: node_dim_capacity.{dim_name} must be a "
                    f"positive integer, 'full', or {{spatial: N}} in "
                    f"{self.path}"
                )
            self.node_dim_capacity[dim_name] = value

        self.node_pe_spatial_split: Optional[Dict[str, int]] = (
            spatial_split or None
        )

    def validate_for_arch(self, arch: SNNArch) -> None:
        """Validate the requested NodeLevel fanout against one architecture."""
        if self.node_pe_spatial_split is None:
            return
        product = 1
        for factor in self.node_pe_spatial_split.values():
            product *= factor
        if product > arch.node_pe_num_pes:
            raise ValueError(
                f"SNNDataflow: NodeLevel spatial product={product} exceeds "
                f"arch num_pes={arch.node_pe_num_pes} for {self.path} with "
                f"{arch.path}"
            )


__all__ = ["FULL", "SNNDataflow", "parse_snn_dataflow"]
