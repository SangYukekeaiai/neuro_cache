"""SNN-CoSA NoC simulator — entry point and public API.

Two calling modes
-----------------
1. **Programmatic** (called by the MIP solver):
   ``run(x, prob, bitwidths, out_file)`` — takes live Gurobi variables.

2. **Standalone CLI** (called from the command line):
   ``python -m snn_cosa.nocsim.sim --schedule <json> --layer <yaml>
       --arch <yaml> --out <csv>``
   Reconstructs the schedule from the solver JSON output (no Gurobi
   license needed at replay time) and writes a single ``tc.csv``.

CSV format
----------
Each transaction is written as two lines::

    # <human-readable annotation>
    tc_id,actor_id,op,size,src,dest,dep

Columns
~~~~~~~
* ``tc_id``    — unique integer, 0-based
* ``actor_id`` — originating PE or port id
* ``op``       — 0 UNICAST · 1 MULTICAST · 2 COUNT
* ``size``     — packets (unicast/multicast) or cycles (count)
* ``src``      — space-separated source node ids
* ``dest``     — space-separated destination node ids (empty for COUNT)
* ``dep``      — space-separated prerequisite tc_ids (empty if none)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from typing import Dict, Optional, Tuple

from snn_cosa.parsers.layer import (
    SNNProb,
    DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT,
)
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.archmodels import ArchComputeModel

from .schedule.decode import decode, schedule_from_strategy
from .schedule.buf_spatial import BufSpatial
from .schedule.steps import StepInfo
from .combine import combine
from .core.noc import NoC


# ---------------------------------------------------------------------------
# Programmatic API  (used by the MIP solver pipeline)
# ---------------------------------------------------------------------------

def run(
    x:         Dict,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    out_file:  pathlib.Path,
    y:         Optional[Dict] = None,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """Generate the TC list for one solved MIP result and write it to CSV.

    Args:
        x:         Solved Gurobi binary variables ``{(i, j, n, k): Var}``
                   where ``.X`` holds the solved value (0.0 or 1.0).
        prob:      Parsed SNN layer (prime-factor lists, dimension names).
        bitwidths: Per-variable bit widths (bw_weight, bw_psum, bw_vmem,
                   dram_latency).
        out_file:  Destination CSV path.
        y:         Solved Gurobi y-variables (accepted for API symmetry; not
                   used by the NoC simulator).
        arch:      Parsed arch config. Pass whenever arch.single_node may be
                   True, so combine() can route DRAM<->node transfers
                   directly instead of through a nonexistent Global Buffer.
                   None (default) behaves exactly as before this parameter
                   existed.
        compute_model: Optional per-architecture cycle model, passed straight
                   through to combine(). None (default) behaves exactly as
                   before this parameter existed.

    Returns:
        ``(unicast_hops, multicast_hops, dram_cost)`` — each a dict keyed by
        ``"weight"``/``"psum"``/``"vmem"``, always containing all three keys.
        unicast_hops/multicast_hops total on-chip GB-sourced NoC traffic;
        dram_cost totals DRAM-touching traffic (either direction) weighted
        by dram_latency.
    """
    schedule = decode(x, prob)
    bs       = BufSpatial(schedule, prob)
    si       = StepInfo(schedule, prob)
    gen      = combine(schedule, bs, si, prob, bitwidths, arch=arch, compute_model=compute_model)
    gen.to_file(out_file)
    return (gen.unicast_hops, gen.multicast_hops, gen.dram_cost)


def run_from_json(
    schedule_path: pathlib.Path,
    prob:          SNNProb,
    bitwidths:     SNNBitwidths,
    out_file:      pathlib.Path,
    arch:          Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """Generate the TC list from a solver JSON output file and write it to CSV.

    This variant requires no Gurobi installation at replay time; the schedule
    is reconstructed from the ``strategy`` block in the JSON.

    Args:
        schedule_path: Path to the solver JSON file (output of ``snn_cosa solve``).
        prob:          Parsed SNN layer.
        bitwidths:     Per-variable bit widths.
        out_file:      Destination CSV path.
        arch:          Parsed arch config -- see ``run()``.
        compute_model: Optional per-architecture cycle model -- see ``run()``.

    Returns:
        ``(unicast_hops, multicast_hops, dram_cost)`` — see ``run()``.

    Raises:
        ValueError: If the JSON does not contain a feasible solution.
    """
    with open(schedule_path) as fh:
        result = json.load(fh)

    if not result.get("has_solution"):
        raise ValueError(f"No feasible solution found in {schedule_path}")

    schedule = schedule_from_strategy(result["strategy"], prob)
    bs       = BufSpatial(schedule, prob)
    si       = StepInfo(schedule, prob)
    gen      = combine(schedule, bs, si, prob, bitwidths, arch=arch, compute_model=compute_model)
    gen.to_file(out_file)
    return (gen.unicast_hops, gen.multicast_hops, gen.dram_cost)


# ---------------------------------------------------------------------------
# eventsim — compiled discrete-event latency backend (optional)
# ---------------------------------------------------------------------------

_DEFAULT_EVENTSIM_BINARY = pathlib.Path(__file__).parent / "eventsim" / "eventsim"


def run_eventsim(
    csv_path:     pathlib.Path,
    X:            int,
    Y:            int,
    dram_port:    int,
    dram_latency: int,
    binary:       Optional[pathlib.Path] = None,
) -> Dict[str, int]:
    """Invoke the compiled eventsim backend and return its JSON summary.

    eventsim is a separate discrete-event NoC latency simulator (see
    PLAN_eventsim_latency.md) — it reads the same tc.csv this module writes
    and computes a contention-aware total latency, independent of the
    static unicast_hops/multicast_hops/dram_cost metrics from run()/
    run_from_json().

    Args:
        csv_path:     Path to a tc.csv written by run()/run_from_json().
        X, Y:         NoC mesh dimensions (gen.noc.X / gen.noc.Y).
        dram_port:    DRAM port id (gen.noc.dram_port).
        dram_latency: Per-packet DRAM latency multiplier
                      (bitwidths.dram_latency).
        binary:       Path to the compiled eventsim binary. Defaults to
                      the ``eventsim/eventsim`` binary next to this file.

    Returns:
        ``{"total_cycles": int, "unicast_cycles": int, "multicast_cycles":
        int, "count_cycles": int, "dram_cycles": int}``.

    Raises:
        FileNotFoundError: If the eventsim binary hasn't been built.
        subprocess.CalledProcessError: If eventsim exits non-zero.
    """
    binary = binary or _DEFAULT_EVENTSIM_BINARY
    if not binary.exists():
        raise FileNotFoundError(
            f"eventsim binary not found at {binary} -- build it first: "
            f"cd {binary.parent} && make"
        )

    proc = subprocess.run(
        [
            str(binary), str(csv_path),
            "--X", str(X),
            "--Y", str(Y),
            "--dram-port", str(dram_port),
            "--dram-latency", str(dram_latency),
        ],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEFAULT_OUT = "outputs/tc.csv"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m snn_cosa.nocsim.sim",
        description=(
            "SNN-CoSA NoC simulator: replay a solved schedule and write "
            "the full transaction list to a CSV file."
        ),
    )
    parser.add_argument(
        "--schedule",
        required=True,
        metavar="JSON",
        help="path to the solver JSON output (from `snn_cosa solve`)",
    )
    parser.add_argument(
        "--layer",
        required=True,
        metavar="YAML",
        help="SNN layer YAML (must match the one used when solving)",
    )
    parser.add_argument(
        "--arch",
        required=True,
        metavar="YAML",
        help="architecture YAML (supplies bit-width information)",
    )
    parser.add_argument(
        "--out",
        default=_DEFAULT_OUT,
        metavar="CSV",
        help=f"output CSV path (default: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help=(
            "after writing the CSV, run the compiled eventsim backend "
            "(must be built: cd nocsim/eventsim && make) and print "
            "total_cycles"
        ),
    )
    return parser


def main(argv=None) -> int:
    """CLI entry point for the standalone NoC simulator."""
    parser = _build_parser()
    args   = parser.parse_args(argv)

    out_path = pathlib.Path(args.out)

    try:
        prob      = SNNProb(args.layer)
        arch      = SNNArch(args.arch)
        bitwidths = SNNBitwidths(args.arch)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error loading inputs: {exc}", file=sys.stderr)
        return 2

    schedule_path = pathlib.Path(args.schedule)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        unicast_hops, multicast_hops, dram_cost = run_from_json(
            schedule_path, prob, bitwidths, out_path, arch=arch
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"simulation failed: {exc}", file=sys.stderr)
        return 2

    # Read back the TC count from the written file (line pairs: comment + data)
    lines    = [ln for ln in out_path.read_text().splitlines() if ln and not ln.startswith("#")]
    tc_count = len(lines)

    print(f"transactions  : {tc_count}")
    for var in ("weight", "psum", "vmem"):
        print(
            f"{var:>6}  unicast_hops={unicast_hops[var]:<8} "
            f"multicast_hops={multicast_hops[var]:<8} "
            f"dram_cost={dram_cost[var]:<8}"
        )
    print(f"output        : {out_path}")

    if args.simulate:
        # eventsim needs the mesh dimensions and DRAM port id, neither of
        # which run_from_json() exposes. Cheap to recompute (an integer
        # formula, not a re-run of combine()) rather than changing its
        # already-established return shape.
        with open(schedule_path) as fh:
            result = json.load(fh)
        schedule = schedule_from_strategy(result["strategy"], prob)
        sf = schedule.spatial_factors
        X  = sf[DIM_T] * sf[DIM_WO] * sf[DIM_HO]
        Y  = sf[DIM_CIN] * sf[DIM_KW] * sf[DIM_KH] * sf[DIM_COUT]
        dram_port = NoC(X, Y).dram_port

        try:
            sim_result = run_eventsim(out_path, X, Y, dram_port, bitwidths.dram_latency)
        except FileNotFoundError as exc:
            print(f"eventsim not available: {exc}", file=sys.stderr)
            return 2
        except subprocess.CalledProcessError as exc:
            print(f"eventsim failed: {exc.stderr}", file=sys.stderr)
            return 2

        print()
        print(f"total_cycles  : {sim_result['total_cycles']}")
        print(f"unicast_cycles: {sim_result['unicast_cycles']}")
        print(f"multicast_cycles: {sim_result['multicast_cycles']}")
        print(f"count_cycles  : {sim_result['count_cycles']}")
        print(f"dram_cycles   : {sim_result['dram_cycles']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
