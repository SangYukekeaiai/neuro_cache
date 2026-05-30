#!/usr/bin/env python3
"""Shared output-formatting utilities."""

from __future__ import annotations

from typing import Any, Dict, List


REGIONS = ("NodeLevel", "NoCLevel", "OffChip")
KINDS = ("temporal", "spatial")


def build_strategy(levels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the compact human-readable mapping strategy.

    Fusion is performed independently for temporal and spatial assignments.
    Within each region, selected factors are scanned in increasing loop-level
    order.  Consecutive entries of the same dimension are multiplied into one
    segment, preserving the first and last level where they appeared.
    """
    node_levels = _region_levels(levels, "NodeLevel")
    noc_levels = _region_levels(levels, "NoCLevel")
    dram_levels = _region_levels(levels, "OffChip")

    return {
        "NodeLevel": {
            "temporal_tile": _tile_block(
                _fuse_kind(node_levels, "temporal")
            ),
        },
        "NoCLevel": {
            "temporal_permutation": _strategy_block(
                _fuse_kind(noc_levels, "temporal")
            ),
            "spatial_splitting": _strategy_block(
                _fuse_same_dim_kind(noc_levels, "spatial")
            ),
        },
        "DRAM": {
            "temporal_permutation": _strategy_block(
                _fuse_kind(dram_levels, "temporal")
            ),
        },
    }


def _region_levels(levels: List[Dict[str, Any]], region: str) -> List[Dict[str, Any]]:
    return [level for level in levels if level["region"] == region]


def _strategy_block(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "order": _format_order(segments),
        "loops": _loops(segments),
    }


def _tile_block(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "note": "unordered factors assigned to NodeLevel; no loop permutation is modeled here",
        "factors": _loops(segments),
    }


def _loops(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"dim": seg["dim"], "size": seg["factor"]}
        for seg in segments
    ]


def _fuse_kind(levels: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    fused: List[Dict[str, Any]] = []
    for level in levels:
        factors = [f for f in level["factors"] if f["kind"] == kind]
        factors.sort(key=lambda f: (f["dim_index"], f["factor_index"]))
        for factor in factors:
            _append_or_fuse(fused, level["level"], factor)
    return fused


def _fuse_same_dim_kind(levels: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    fused: List[Dict[str, Any]] = []
    by_dim: Dict[str, Dict[str, Any]] = {}
    for level in levels:
        factors = [f for f in level["factors"] if f["kind"] == kind]
        factors.sort(key=lambda f: (f["dim_index"], f["factor_index"]))
        for factor in factors:
            segment = by_dim.get(factor["dim"])
            if segment is None:
                segment = _new_segment(level["level"], factor)
                by_dim[factor["dim"]] = segment
                fused.append(segment)
                continue
            segment["factor"] *= factor["factor"]
            segment["factor_indices"].append(factor["factor_index"])
            segment["levels"].append(level["level"])
            segment["end_level"] = level["level"]
    return fused


def _append_or_fuse(fused: List[Dict[str, Any]], level: int, factor: Dict[str, Any]) -> None:
    if fused and fused[-1]["dim"] == factor["dim"]:
        fused[-1]["factor"] *= factor["factor"]
        fused[-1]["factor_indices"].append(factor["factor_index"])
        fused[-1]["levels"].append(level)
        fused[-1]["end_level"] = level
        return

    fused.append(_new_segment(level, factor))


def _new_segment(level: int, factor: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "dim": factor["dim"],
        "dim_index": factor["dim_index"],
        "factor": factor["factor"],
        "factor_indices": [factor["factor_index"]],
        "start_level": level,
        "end_level": level,
        "levels": [level],
    }


def _format_order(segments: List[Dict[str, Any]]) -> str:
    if not segments:
        return "none"
    return " -> ".join(f"{seg['dim']}x{seg['factor']}" for seg in segments)


__all__ = ["build_strategy"]
