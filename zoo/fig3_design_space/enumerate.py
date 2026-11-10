#!/usr/bin/env python3
"""Brute-force the full multi-node scheduling design space for paper Figure 3.

One counted schedule = (per-dimension NodeLevel role, per-dimension NoC
fanout).  Validity is closed-form arithmetic, mirroring what the MIP
enforces, so no Gurobi solve is needed:

  * NodeLevel role per dimension (src/lays/scheduler/constraints/):
    a dimension is either PE-spatial (node_level.py, pinned over level 0)
    or temporally LB-resident (node_capacity.py, which forces k=0 to zero
    for every non-spatial-split dim) -- never both.  Factor 1 means the
    dimension is absent from NodeLevel entirely.
  * Spatial budgets: the six non-T dimensions share the 8-PE budget; T is
    an additional axis capped at 4 (the arch's num_pes: 32 = 8 x 4 is the
    solver's single combined budget, see ../../../examples/arch and the
    figure plan).
  * NoC fanout per dimension is drawn from that dimension's leftover
    factors; the product is capped by arch.S[1] = instances 16
    (constraints/spatial.py).
  * Byte capacities mirror objectives/utilization.py
    add_utilization_capacity_constraints:
      LB (MEM_NODE, levels i < gb_start = level 0 only): node factors.
      GLB (MEM_NOC, levels i < dram_start): node x NoC-fanout factors.
    Footprints use the A matrix of scheduler/constants.py:
      weight = KH.KW.CIN.COUT x 1 B, psum = COUT.HO.WO.T x 2 B,
      vmem = COUT.HO.WO x 4 B.
  * latency = total work / (PE_spatial x T_spatial x NoC_fanout), i.e. the
    product of every temporally-assigned factor (metrics.py _eval_delay).

Outputs outputs/schedules.csv (one row per valid schedule) and
outputs/summary.json.  Run `python3 enumerate.py --self-check` for the
assertion-based check of the model.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
from typing import Dict, List, Tuple

import yaml

HERE = pathlib.Path(__file__).resolve().parent
DIMS = ["KH", "KW", "CIN", "COUT", "HO", "WO", "T"]
T_IDX = DIMS.index("T")

# A matrix (scheduler/constants.py): which dims scale which tensor footprint.
WEIGHT_DIMS = [DIMS.index(d) for d in ("KH", "KW", "CIN", "COUT")]
PSUM_DIMS = [DIMS.index(d) for d in ("COUT", "HO", "WO", "T")]
VMEM_DIMS = [DIMS.index(d) for d in ("COUT", "HO", "WO")]

PE_SPATIAL_CAP = 8          # non-T spatial product per node
T_SPATIAL_CAP = 4           # additional T-lane axis, does not spend PEs
NOC_FANOUT_CAP = 16         # arch.S[1] = NodeLevel instances / NoCLevel instances

ROLE_NONE, ROLE_SPATIAL, ROLE_RESIDENT = "-", "S", "R"


def divisors(n: int) -> List[int]:
    return [d for d in range(1, n + 1) if n % d == 0]


def load_bounds(layer_path: pathlib.Path) -> List[int]:
    prob = yaml.safe_load(layer_path.read_text())["problem"]
    return [int(prob[d]) for d in DIMS]


def load_caps(arch_path: pathlib.Path) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """Return (LB byte caps, GLB byte caps, bytes-per-element) from the arch."""
    arch = yaml.safe_load(arch_path.read_text())["arch"]
    bw = arch["bitwidths"]
    per_elem = {
        "weight": bw["BW_WEIGHT"] // 8,
        "psum": bw["BW_PSUM"] // 8,
        "vmem": bw["BW_VMEM"] // 8,
    }
    levels = {lvl["name"]: lvl for lvl in arch["storage"]}
    lb = dict(levels["NodeLevel"]["local_buffer"]["entries"])
    glb = dict(levels["NoCLevel"]["entries"])
    return lb, glb, per_elem


def node_options(bound: int, is_t: bool) -> List[Tuple[int, str]]:
    """(factor, role) choices for one dimension at NodeLevel.

    Factor 1 is a single option: spatial-1 and resident-1 are the same
    schedule (the dimension is simply not at NodeLevel).
    """
    cap = T_SPATIAL_CAP if is_t else PE_SPATIAL_CAP
    opts = [(1, ROLE_NONE)]
    for f in divisors(bound):
        if f == 1:
            continue
        if f <= cap:
            opts.append((f, ROLE_SPATIAL))
        opts.append((f, ROLE_RESIDENT))
    return opts


def enumerate_node_assignments(bounds, lb_caps, per_elem):
    """Yield (factors, roles, pe_spatial, t_spatial, lb_bytes) per valid node role set."""
    opts = [node_options(bounds[j], j == T_IDX) for j in range(len(DIMS))]
    w_cap, p_cap, v_cap = lb_caps["weight"], lb_caps["psum"], lb_caps["vmem"]
    bw, bp, bv = per_elem["weight"], per_elem["psum"], per_elem["vmem"]
    factors = [1] * len(DIMS)
    roles = [ROLE_NONE] * len(DIMS)

    def rec(j, pe_sp, t_sp, w, p, v):
        if j == len(DIMS):
            yield (tuple(factors), tuple(roles), pe_sp, t_sp,
                   (w * bw, p * bp, v * bv))
            return
        for f, role in opts[j]:
            if role == ROLE_SPATIAL:
                if j == T_IDX:
                    n_pe, n_t = pe_sp, t_sp * f
                    if n_t > T_SPATIAL_CAP:
                        continue
                else:
                    n_pe, n_t = pe_sp * f, t_sp
                    if n_pe > PE_SPATIAL_CAP:
                        continue
            else:
                n_pe, n_t = pe_sp, t_sp
            # Both spatial and resident factors occupy the node footprint:
            # utilization.py sums k = 0 and k = 1 at levels i < gb_start.
            nw = w * f if j in WEIGHT_DIMS else w
            np_ = p * f if j in PSUM_DIMS else p
            nv = v * f if j in VMEM_DIMS else v
            if nw * bw > w_cap or np_ * bp > p_cap or nv * bv > v_cap:
                continue
            factors[j], roles[j] = f, role
            yield from rec(j + 1, n_pe, n_t, nw, np_, nv)
        factors[j], roles[j] = 1, ROLE_NONE

    yield from rec(0, 1, 1, 1, 1, 1)


def enumerate_fanouts(bounds, node_factors, lb_bytes, glb_caps):
    """Yield (fan_factors, fanout_product, glb_bytes) for one node assignment."""
    leftovers = [bounds[j] // node_factors[j] for j in range(len(DIMS))]
    opts = [[f for f in divisors(leftovers[j]) if f <= NOC_FANOUT_CAP]
            for j in range(len(DIMS))]
    w_cap, p_cap, v_cap = glb_caps["weight"], glb_caps["psum"], glb_caps["vmem"]
    fan = [1] * len(DIMS)

    def rec(j, prod, w, p, v):
        if j == len(DIMS):
            yield (tuple(fan), prod, (w, p, v))
            return
        for f in opts[j]:
            if prod * f > NOC_FANOUT_CAP:
                continue
            nw = w * f if j in WEIGHT_DIMS else w
            np_ = p * f if j in PSUM_DIMS else p
            nv = v * f if j in VMEM_DIMS else v
            if nw > w_cap or np_ > p_cap or nv > v_cap:
                continue
            fan[j] = f
            yield from rec(j + 1, prod * f, nw, np_, nv)
        fan[j] = 1

    yield from rec(0, 1, *lb_bytes)


def run(layer_path, arch_path, csv_path, json_path, write_csv=True):
    bounds = load_bounds(layer_path)
    lb_caps, glb_caps, per_elem = load_caps(arch_path)
    total_work = math.prod(bounds)

    header = (
        [f"node_{d}" for d in DIMS] + [f"role_{d}" for d in DIMS]
        + ["pe_spatial", "t_spatial"]
        + [f"fan_{d}" for d in DIMS]
        + ["noc_fanout", "lb_weight_B", "lb_psum_B", "lb_vmem_B",
           "glb_weight_B", "glb_psum_B", "glb_vmem_B", "latency"]
    )
    hist: Dict[int, int] = {}
    n_assign = 0
    n_sched = 0

    fh = open(csv_path, "w", newline="") if write_csv else None
    writer = csv.writer(fh) if fh else None
    if writer:
        writer.writerow(header)
    try:
        for factors, roles, pe_sp, t_sp, lb_bytes in enumerate_node_assignments(
            bounds, lb_caps, per_elem
        ):
            n_assign += 1
            for fan, fanout, glb_bytes in enumerate_fanouts(
                bounds, factors, lb_bytes, glb_caps
            ):
                latency = total_work // (pe_sp * t_sp * fanout)
                hist[latency] = hist.get(latency, 0) + 1
                n_sched += 1
                if writer:
                    writer.writerow(
                        list(factors) + list(roles) + [pe_sp, t_sp]
                        + list(fan) + [fanout] + list(lb_bytes) + list(glb_bytes)
                        + [latency]
                    )
    finally:
        if fh:
            fh.close()

    latencies = sorted(hist)
    summary = {
        "layer": str(layer_path),
        "arch": str(arch_path),
        "bounds": dict(zip(DIMS, bounds)),
        "total_work": total_work,
        "lb_byte_caps": lb_caps,
        "glb_byte_caps": glb_caps,
        "bytes_per_element": per_elem,
        "budgets": {
            "pe_spatial_cap": PE_SPATIAL_CAP,
            "t_spatial_cap": T_SPATIAL_CAP,
            "noc_fanout_cap": NOC_FANOUT_CAP,
        },
        "n_node_assignments": n_assign,
        "n_schedules": n_sched,
        "n_distinct_latencies": len(latencies),
        "best_latency": latencies[0],
        "worst_latency": latencies[-1],
        "spread": latencies[-1] // latencies[0],
        "latency_counts": {str(k): hist[k] for k in latencies},
        "csv": str(csv_path) if write_csv else None,
    }
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def self_check():
    """Smallest check that fails if the enumeration model breaks."""
    # Divisor roles: factor 1 appears once, every other divisor twice (minus
    # spatial options above the cap).
    assert node_options(4, False) == [
        (1, ROLE_NONE), (2, ROLE_SPATIAL), (2, ROLE_RESIDENT),
        (4, ROLE_SPATIAL), (4, ROLE_RESIDENT),
    ]
    # T spatial is capped at 4, so an 8-divisor dim gets no spatial-8 on T.
    assert (8, ROLE_SPATIAL) not in node_options(8, True)
    assert (8, ROLE_SPATIAL) in node_options(8, False)

    # Tiny end-to-end model: 2x2 problem, generous caps -> hand-countable.
    bounds = [1, 1, 2, 2, 1, 1, 1]
    lb = {"weight": 1 << 20, "psum": 1 << 20, "vmem": 1 << 20}
    glb = {"weight": 1 << 20, "psum": 1 << 20, "vmem": 1 << 20}
    per_elem = {"weight": 1, "psum": 2, "vmem": 4}
    assigns = list(enumerate_node_assignments(bounds, lb, per_elem))
    assert len(assigns) == 9, len(assigns)   # 3 options each for CIN and COUT
    # Latency always divides the total work exactly.
    total = math.prod(bounds)
    for factors, roles, pe_sp, t_sp, lb_bytes in assigns:
        for fan, fanout, _ in enumerate_fanouts(bounds, factors, lb_bytes, glb):
            assert total % (pe_sp * t_sp * fanout) == 0
            for j, f in enumerate(fan):
                assert (bounds[j] // factors[j]) % f == 0
    # A resident factor costs no parallelism; a spatial one does.
    res = next(a for a in assigns if a[1][2] == ROLE_RESIDENT and a[0][2] == 2)
    spa = next(a for a in assigns if a[1][2] == ROLE_SPATIAL and a[0][2] == 2)
    assert res[2] == 1 and spa[2] == 2
    print("self-check: ok")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layer", default=str(HERE / "layer.yaml"))
    ap.add_argument("--arch", default=str(HERE / "arch.yaml"))
    ap.add_argument("--out-dir", default=str(HERE / "outputs"))
    ap.add_argument("--no-csv", action="store_true",
                    help="count only; skip writing schedules.csv")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        self_check()
        return 0

    out = pathlib.Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = run(
        pathlib.Path(args.layer), pathlib.Path(args.arch),
        out / "schedules.csv", out / "summary.json",
        write_csv=not args.no_csv,
    )
    print(f"node assignments (LB-valid) : {summary['n_node_assignments']:,}")
    print(f"valid schedules             : {summary['n_schedules']:,}")
    print(f"distinct latencies          : {summary['n_distinct_latencies']}")
    print(f"best / worst latency        : {summary['best_latency']:,} / "
          f"{summary['worst_latency']:,}  ({summary['spread']}x spread)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
