"""Classify a solved schedule's DRAM-level loop permutation into a
canonical M/N/K/T super-dimension string.

Per-loop dims fuse into super-dimensions (the MIP's chosen tile *sizes*
are dropped entirely -- only the *order* of super-dimensions matters):
  M := {HO, WO}
  N := {COUT}
  K := {KH, KW, CIN}
  T := {T}

Consecutive DRAM-permutation entries that fuse into the SAME super-dim
(including across an interleaving of e.g. HO,WO,HO -- all M) collapse
into one token, so `HO=2 -> WO=4 -> HO=2` becomes a single `M` token, not
`M -> M -> M`. This mirrors mip_solver/cli.py's `_fmt_perm`, which does
the same adjacent-fusion at the level of individual dims (not
super-dims); this module fuses one level up.
"""

from __future__ import annotations

from typing import Any, Dict, List

SUPER_DIM = {
    "HO": "M", "WO": "M",
    "COUT": "N",
    "KH": "K", "KW": "K", "CIN": "K",
    "T": "T",
}


def classify_permutation(loops: List[Dict[str, Any]]) -> str:
    """loops: DRAM.temporal_permutation.loops (list of {"dim": ..., "size": ...}).
    Returns a canonical class string, e.g. "M->K->N->T", or "" if loops is empty
    (every dim fully resident at NodeLevel, nothing left at DRAM)."""
    tokens: List[str] = []
    for loop in loops:
        super_dim = SUPER_DIM[loop["dim"]]
        if not tokens or tokens[-1] != super_dim:
            tokens.append(super_dim)
    return "->".join(tokens)


def classify_schedule_file(path) -> str:
    import json

    with open(path) as fh:
        data = json.load(fh)
    loops = data["result"]["strategy"]["DRAM"]["temporal_permutation"]["loops"]
    return classify_permutation(loops)
