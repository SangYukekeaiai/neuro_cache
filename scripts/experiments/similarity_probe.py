#!/usr/bin/env python3
"""
Similarity probe: 2^5 permutations of CNN depth × T × GB size × weight split × node count.

Axes (2 options each → 32 total combinations):
  cnn     shallow = resnet19/conv1      |  deep = vgg16/conv5_3
  T       short   = 4                   |  long  = 128
  gb      small   = 64 KB               |  big   = 4096 KB
  split   w24_p4_v4 (75% weight)        |  w30_p1_v1 (94% weight)
  nodes   small   = 16                  |  large = 1024

Fixed arch: L1=16 KB, PE=64.

Fingerprint rules:
  - Spatial splitting: only the *set* of split dims matters (order ignored).
  - Temporal permutation: if all dims at a level are from {COUT, HO, WO},
    permutations are equivalent (but actual orders are still printed).

Run from the project root:
    python scripts/experiments/similarity_probe.py

Outputs land in:  outputs/similarity_probe/
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class _Tee:
    """Write to multiple streams simultaneously (stdout + log file)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data: str) -> None:
        for s in self._streams:
            s.write(data)

    def flush(self) -> None:
        for s in self._streams:
            s.flush()

import yaml

# ── project path setup ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from snn_cosa.cli import _print_enumeration_summary  # noqa: E402
from snn_cosa.enumerator import enumerate_modes  # noqa: E402

# ── axes ──────────────────────────────────────────────────────────────────────
AXES: Dict[str, List[Tuple[str, Any]]] = {
    "cnn":   [("shallow", "resnet19/conv1"),   ("deep",  "vgg16/conv5_3")],
    "T":     [("short",   4),                  ("long",  128)],
    "gb":    [("small",   "64kb"),             ("big",   "4096kb")],
    "split": [("small_w", "w24_p4_v4"),        ("big_w", "w30_p1_v1")],
    "nodes": [("small",   16),                 ("large", 1024)],
}

# ── fixed arch dims ───────────────────────────────────────────────────────────
FIXED_L1 = "16kb"
FIXED_PE = 64

# Output dimensions that are interchangeable everywhere in the fingerprint.
_OUT_DIMS = frozenset({"COUT", "HO", "WO"})


def _norm_dim(d: str) -> str:
    """Replace any output dim with a canonical placeholder."""
    return "_OD_" if d in _OUT_DIMS else d

# ── paths ─────────────────────────────────────────────────────────────────────
WORKLOAD_ROOT = PROJECT_ROOT / "configs" / "workloads"
ARCH_SWEEP    = PROJECT_ROOT / "configs" / "arch" / "sweep"
MAPSPACE      = PROJECT_ROOT / "configs" / "mapspace" / "mapspace.yaml"
OUT_ROOT      = PROJECT_ROOT / "outputs" / "similarity_probe"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_workload(network: str, layer: str, t: int, tmp_dir: Path) -> Path:
    """Copy base layer dims, overwrite T, write a temp YAML."""
    src = WORKLOAD_ROOT / network / f"{layer}.yaml"
    with open(src) as f:
        raw = yaml.safe_load(f)
    prob = {k: v for k, v in raw["problem"].items() if k not in ("T", "shape")}
    prob["T"] = t
    prob["shape"] = "snn-layer"
    out = tmp_dir / f"{network}_{layer}_T{t}.yaml"
    with open(out, "w") as f:
        yaml.safe_dump({"problem": prob}, f, sort_keys=False)
    return out


def _arch_path(nodes: int, gb: str, split: str) -> Path:
    return (
        ARCH_SWEEP
        / f"nodes_{nodes}"
        / f"gb_{gb}"
        / f"l1_{FIXED_L1}"
        / f"pe_{FIXED_PE}"
        / f"split_{split}.yaml"
    )


def _collapse_od_runs(dims: tuple) -> tuple:
    """Collapse consecutive _OD_ entries into a single _OD_ (run-length collapse)."""
    result: list = []
    for d in dims:
        if d == "_OD_" and result and result[-1] == "_OD_":
            continue
        result.append(d)
    return tuple(result)


def _collapse_od_runs_full(pairs: tuple) -> tuple:
    """Collapse consecutive (_OD_, size) pairs: merge sizes by product."""
    result: list = []
    for d, sz in pairs:
        if d == "_OD_" and result and result[-1][0] == "_OD_":
            result[-1] = ("_OD_", result[-1][1] * sz)
        else:
            result.append((d, sz))
    return tuple(result)


def _fingerprint_dims(schedule: Dict[str, Any]) -> Optional[Tuple]:
    """Dimension-name-only fingerprint (ignores tile sizes).

    COUT, HO, WO are interchangeable output dims — each is normalised to '_OD_'.
    Consecutive _OD_ runs in DRAM temporal are collapsed to one (count irrelevant).
    Spatial splitting is order-insensitive (sorted tuple).
    """
    if not schedule.get("has_solution"):
        return None
    s = schedule["strategy"]
    dram_dims  = _collapse_od_runs(
        tuple(_norm_dim(lp["dim"]) for lp in s["DRAM"]["temporal_permutation"]["loops"])
    )
    gb_sp_dims = tuple(sorted(_norm_dim(lp["dim"]) for lp in s["NoCLevel"]["spatial_splitting"]["loops"]))
    gb_tp_dims = tuple(_norm_dim(lp["dim"]) for lp in s["NoCLevel"]["temporal_permutation"]["loops"])
    node_dims  = tuple(sorted(_norm_dim(f["dim"]) for f in s["NodeLevel"]["temporal_tile"]["factors"]))
    pe_sp_dims = tuple(sorted(_norm_dim(f["dim"]) for f in s["NodeLevel"]["spatial_split"]["factors"]))
    return (dram_dims, gb_sp_dims, gb_tp_dims, node_dims, pe_sp_dims)


def _fingerprint_full(schedule: Dict[str, Any]) -> Optional[Tuple]:
    """Full fingerprint including tile sizes.

    Same normalisation as _fingerprint_dims.  Consecutive _OD_ loops in DRAM
    are merged (sizes multiplied).  Spatial split is a sorted tuple of
    (_OD_-normalised-dim, size) pairs so multiplicity is preserved.
    """
    if not schedule.get("has_solution"):
        return None
    s = schedule["strategy"]
    dram  = _collapse_od_runs_full(
        tuple((_norm_dim(lp["dim"]), lp["size"]) for lp in s["DRAM"]["temporal_permutation"]["loops"])
    )
    gb_sp = tuple(sorted((_norm_dim(lp["dim"]), lp["size"]) for lp in s["NoCLevel"]["spatial_splitting"]["loops"]))
    gb_tp = tuple((_norm_dim(lp["dim"]), lp["size"]) for lp in s["NoCLevel"]["temporal_permutation"]["loops"])
    node  = tuple(sorted((_norm_dim(f["dim"]), f["size"]) for f in s["NodeLevel"]["temporal_tile"]["factors"]))
    pe_sp = tuple(sorted((_norm_dim(f["dim"]), f["size"]) for f in s["NodeLevel"]["spatial_split"]["factors"]))
    return (dram, gb_sp, gb_tp, node, pe_sp)


def _fmt_perm(loops) -> str:
    return " → ".join(f"{lp['dim']}×{lp['size']}" for lp in loops) or "none"


def _fmt_unordered(factors) -> str:
    return "  ".join(f"{f['dim']}×{f['size']}" for f in sorted(factors, key=lambda f: f["dim"])) or "none"


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    log_path = OUT_ROOT / "similarity_probe.txt"
    log_file = open(log_path, "w", buffering=1)
    _real_stdout = sys.stdout
    sys.stdout = _Tee(_real_stdout, log_file)

    try:
        return _run()
    finally:
        sys.stdout = _real_stdout
        log_file.close()


def _run() -> int:
    axis_keys  = list(AXES.keys())
    axis_opts  = list(AXES.values())
    all_combos = list(itertools.product(*axis_opts))

    print(f"Running {len(all_combos)} combinations  (fixed: L1={FIXED_L1}, PE={FIXED_PE})")
    print(f"Output → {OUT_ROOT}\n")

    records: List[Dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        for combo in all_combos:
            labels = {k: lbl for k, (lbl, _) in zip(axis_keys, combo)}
            values = {k: val for k, (_, val) in zip(axis_keys, combo)}

            network, layer_stem = values["cnn"].split("/")
            t      = values["T"]
            gb     = values["gb"]
            split  = values["split"]
            nodes  = values["nodes"]

            combo_id = (
                f"cnn={labels['cnn']}"
                f"__T={labels['T']}"
                f"__gb={labels['gb']}"
                f"__split={labels['split']}"
                f"__nodes={labels['nodes']}"
            )

            print(f"{'─'*64}")
            print(f"  {combo_id}")

            arch = _arch_path(nodes, gb, split)
            if not arch.exists():
                print(f"  [SKIP] arch missing: {arch}")
                records.append({"combo_id": combo_id, "status": "missing_arch"})
                continue

            workload = _make_workload(network, layer_stem, t, tmp_dir)

            try:
                enum_result = enumerate_modes(
                    layer_path=workload,
                    arch_path=arch,
                    mapspace_path=MAPSPACE,
                    mip_gap=0.001,
                )
            except Exception as exc:
                print(f"  [ERROR] {exc}")
                records.append({"combo_id": combo_id, "status": "error", "error": str(exc)})
                continue

            has_sol    = enum_result["best_mode"] is not None
            best_score = enum_result["best_comparison_score"]
            # Build a sched-shaped dict so fingerprint helpers work unchanged.
            sched = {
                "has_solution": has_sol,
                "status":       "OPTIMAL" if has_sol else "INFEASIBLE",
                "objective":    best_score,
                "strategy":     enum_result["best_strategy"] or {},
            }

            out_dir = OUT_ROOT / combo_id
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "schedule.json", "w") as f:
                json.dump(enum_result, f, indent=2)

            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf):
                _print_enumeration_summary(enum_result, out_dir / "schedule.json")
            (out_dir / "schedule.txt").write_text(_buf.getvalue())

            fp_dims = _fingerprint_dims(sched)
            fp_full = _fingerprint_full(sched)
            obj = best_score

            obj_str = f"{obj:.4f}" if obj is not None else "—"
            print(f"  status={sched['status']}  best_mode={enum_result['best_mode']}  score={obj_str}")

            if has_sol:
                s = sched["strategy"]
                print(f"  DRAM perm : {_fmt_perm(s['DRAM']['temporal_permutation']['loops'])}")
                print(f"  GB spatial: {_fmt_perm(s['NoCLevel']['spatial_splitting']['loops'])}")
                print(f"  GB temp   : {_fmt_perm(s['NoCLevel']['temporal_permutation']['loops'])}")
                print(f"  Node tile : {_fmt_unordered(s['NodeLevel']['temporal_tile']['factors'])}")
                pe_sp_factors = s['NodeLevel']['spatial_split']['factors']
                if pe_sp_factors:
                    print(f"  PE spatial: {_fmt_unordered(pe_sp_factors)}")

            records.append({
                "combo_id":   combo_id,
                "labels":     labels,
                "values":     {k: str(v) for k, v in values.items()},
                "status":     sched["status"],
                "objective":  obj,
                "fp_dims":    fp_dims,
                "fp_full":    fp_full,
            })

    # ── write raw records ─────────────────────────────────────────────────────
    with open(OUT_ROOT / "records.json", "w") as f:
        json.dump(records, f, indent=2, default=str)

    # ── similarity summary ────────────────────────────────────────────────────
    summary = _build_summary(records)
    summary_path = OUT_ROOT / "summary.txt"
    with open(summary_path, "w") as f:
        f.write(summary)
    print(f"\n{'='*64}")
    print(summary)
    print(f"summary → {summary_path}")
    print(f"log    → {OUT_ROOT / 'similarity_probe.txt'}")

    return 0


def _build_summary(records: List[Dict]) -> str:
    lines = []
    lines.append("SIMILARITY SUMMARY")
    lines.append("=" * 64)

    # ── group by dim-name fingerprint (structure only, ignore sizes) ──────────
    lines.append("\n[A] Groups by STRUCTURE (dim-order, ignoring tile sizes)")
    lines.append("    _OD_ = any of {COUT, HO, WO}  (interchangeable output dims)")
    lines.append("    Spatial splitting is order-insensitive (shown as sorted set).\n")
    groups_dims: Dict[Any, List[str]] = defaultdict(list)
    for r in records:
        key = str(r.get("fp_dims")) if r.get("fp_dims") else f"NO_SOLUTION:{r['status']}"
        groups_dims[key].append(r["combo_id"])

    for gid, (key, combo_ids) in enumerate(
        sorted(groups_dims.items(), key=lambda x: -len(x[1])), 1
    ):
        lines.append(f"  Group {gid}  ({len(combo_ids)} combos):")
        for cid in combo_ids:
            lines.append(f"    {cid}")
        if not key.startswith("NO_SOLUTION"):
            try:
                fp = eval(key)
                dram_dims, gb_sp_dims, gb_tp_dims, node_dims, pe_sp_dims = fp
                lines.append(f"    → DRAM perm : {' → '.join(dram_dims) or 'none'}")
                lines.append(f"    → GB spatial: {{{', '.join(gb_sp_dims)}}}  (sorted, order irrelevant)")
                lines.append(f"    → GB temp   : {' → '.join(gb_tp_dims) or 'none'}")
                lines.append(f"    → Node dims : {' '.join(sorted(node_dims)) or 'none'}")
                if pe_sp_dims:
                    lines.append(f"    → PE spatial: {{{', '.join(pe_sp_dims)}}}  (sorted, order irrelevant)")
            except Exception:
                lines.append(f"    → {key[:100]}")
        lines.append("")

    # ── group by full fingerprint (structure + sizes) ─────────────────────────
    lines.append("[B] Groups by FULL fingerprint (structure + exact tile sizes)")
    lines.append("    Combos sharing a group produce byte-identical schedules.\n")
    groups_full: Dict[Any, List[str]] = defaultdict(list)
    for r in records:
        key = str(r.get("fp_full")) if r.get("fp_full") else f"NO_SOLUTION:{r['status']}"
        groups_full[key].append(r["combo_id"])

    for gid, (key, combo_ids) in enumerate(
        sorted(groups_full.items(), key=lambda x: -len(x[1])), 1
    ):
        lines.append(f"  Group {gid}  ({len(combo_ids)} combos):")
        for cid in combo_ids:
            lines.append(f"    {cid}")
        lines.append("")

    # ── axis sensitivity ──────────────────────────────────────────────────────
    lines.append("[C] Axis sensitivity (how many distinct structures each axis introduces)")
    axis_keys = ["cnn", "T", "gb", "split", "nodes"]
    for axis in axis_keys:
        by_val: Dict[str, set] = defaultdict(set)
        for r in records:
            if not r.get("labels"):
                continue
            val = r["labels"].get(axis, "?")
            fp  = str(r.get("fp_dims", "NO_SOLUTION"))
            by_val[val].add(fp)
        parts = "  |  ".join(f"{v}: {len(fps)} unique" for v, fps in sorted(by_val.items()))
        lines.append(f"  {axis:8s}: {parts}")

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
