#!/usr/bin/env python3
"""Human-readable schedule formatting utilities."""

from __future__ import annotations

from typing import Any, Dict, List


REGIONS = ("NodeLevel", "NoCLevel", "OffChip")
KINDS = ("temporal", "spatial")


def build_readable_schedule(levels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return per-region temporal/spatial orders with adjacent dims fused.

    Fusion is performed independently for temporal and spatial assignments.
    Within each region, selected factors are scanned in increasing loop-level
    order.  Consecutive entries of the same dimension are multiplied into one
    segment, preserving the first and last level where they appeared.
    """
    readable = {}
    for region in REGIONS:
        readable[region] = {}
        region_levels = [level for level in levels if level["region"] == region]
        for kind in KINDS:
            fused = _fuse_kind(region_levels, kind)
            readable[region][kind] = {
                "segments": fused,
                "order": _format_order(fused),
            }
    return readable


def _fuse_kind(levels: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    fused: List[Dict[str, Any]] = []
    for level in levels:
        factors = [f for f in level["factors"] if f["kind"] == kind]
        factors.sort(key=lambda f: (f["dim_index"], f["factor_index"]))
        for factor in factors:
            _append_or_fuse(fused, level["level"], factor)
    return fused


def _append_or_fuse(fused: List[Dict[str, Any]], level: int, factor: Dict[str, Any]) -> None:
    if fused and fused[-1]["dim"] == factor["dim"]:
        fused[-1]["factor"] *= factor["factor"]
        fused[-1]["factor_indices"].append(factor["factor_index"])
        fused[-1]["levels"].append(level)
        fused[-1]["end_level"] = level
        return

    fused.append(
        {
            "dim": factor["dim"],
            "dim_index": factor["dim_index"],
            "factor": factor["factor"],
            "factor_indices": [factor["factor_index"]],
            "start_level": level,
            "end_level": level,
            "levels": [level],
        }
    )


def _format_order(segments: List[Dict[str, Any]]) -> str:
    if not segments:
        return "none"
    return " -> ".join(f"{seg['dim']}x{seg['factor']}" for seg in segments)


__all__ = ["build_readable_schedule"]
