"""NoC topology for the SNN-CoSA post-MIP simulator.

Models a 2-D mesh of X columns × Y rows.  PE IDs and external port IDs
share one flat coordinate space:

    x = pe_id % X          (column, left → right)
    y = pe_id // X          (row,    top  → bottom)

Real PEs occupy IDs 0 … X*Y-1 (rows 0 … Y-1).
External ports (GB, DRAM) are placed past the grid and addressed by the
same formula, purely as a bookkeeping convenience for this module's own
hop-count heuristics — it is not a claim about physical router placement.

Default port positions
-----------------------
    GB   : bottom-left  →  pe_id = X*Y
    DRAM : pe_id = num_ports - (X + Y)

The DRAM default is not a free choice: CoSA's C++ NoC backend
(``testbench.cpp``) special-cases exactly one port as the DRAM/DDR timing
model, using the constant ``DRAMPort = kNumNoCMeshPorts - (X + Y)``
(overridable there via the ``DRAM_PORT`` env var). ``num_ports`` here
mirrors that backend's ``kNumNoCMeshPorts = num_lports + num_rports``
(lports = the X*Y PE grid; rports = the mesh's boundary router ports —
see CoSA's ``gen_tc_io.py::NoC``). Matching this formula means a CSV
generated here lines up with that backend's default without needing to
pass a matching ``DRAM_PORT`` env var at simulation time. GB has no such
special-case on the backend side — any valid, non-colliding port id works
for it — so its default is left as a plain "first id past the PE grid"
placement.

Both defaults can be overridden via constructor arguments.
"""

from __future__ import annotations
from typing import List, Set, Tuple

Link = Tuple[Tuple[int, int], Tuple[int, int]]   # ((x0,y0),(x1,y1))


class NoC:
    """2-D mesh NoC topology.

    Args:
        X:         Number of columns  (= M_s × T_s under Way-2).
        Y:         Number of rows     (= N_s × K_s under Way-2).
        gb_port:   PE-ID of the Global Buffer port.
                   Default: bottom-left  →  X * Y.
        dram_port: PE-ID of the DRAM port.
                   Default: matches CoSA C++ backend's DRAMPort  →
                   num_ports - (X + Y).

    Raises:
        ValueError: if gb_port/dram_port collide with each other, with a
            real PE id, or fall outside [X*Y, num_ports) — the range CoSA's
            C++ backend accepts as a valid, non-PE port id.
    """

    def __init__(
        self,
        X: int,
        Y: int,
        gb_port:   int | None = None,
        dram_port: int | None = None,
    ) -> None:
        self.X = X
        self.Y = Y
        self.num_pes = X * Y

        # Mirrors CoSA C++ backend's kNumNoCMeshPorts = lports + rports,
        # where rports are the mesh's boundary router ports (RouterSpec.h).
        # Needed only to derive the correct default dram_port below.
        num_lports = X * Y
        num_rports = 4 * X * Y - Y * (X - 1) * 2 - X * (Y - 1) * 2
        self.num_ports = num_lports + num_rports

        # External port IDs — placed past the PE grid
        self.gb_port   = gb_port   if gb_port   is not None else X * Y
        self.dram_port = (
            dram_port if dram_port is not None
            else self.num_ports - (X + Y)
        )

        for name, port in (("gb_port", self.gb_port), ("dram_port", self.dram_port)):
            if not (self.num_pes <= port < self.num_ports):
                raise ValueError(
                    f"{name}={port} must be in [{self.num_pes}, {self.num_ports}) "
                    f"— outside this range collides with a real PE id or exceeds "
                    f"the CoSA backend's kNumNoCMeshPorts"
                )
        if self.gb_port == self.dram_port:
            raise ValueError(
                f"gb_port and dram_port must differ (both are {self.gb_port})"
            )

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def get_xy(self, pe_id: int) -> Tuple[int, int]:
        """Map any port/PE id to (x, y) in the extended coordinate space.

        Works uniformly for real PEs and external ports (GB, DRAM).
        """
        return (pe_id % self.X, pe_id // self.X)

    # ------------------------------------------------------------------
    # Hop counting  (XY routing)
    # ------------------------------------------------------------------

    def _hops_single(self, src: int, dest: int) -> List[Link]:
        """Return the ordered list of directed links on the XY route src→dest.

        XY routing: traverse all X distance first (horizontal), then all
        Y distance (vertical).  Each link is a pair of (x,y) waypoints.
        """
        sx, sy = self.get_xy(src)
        dx, dy = self.get_xy(dest)

        links: List[Link] = []

        # Phase 1 — horizontal: move along y = sy until x == dx
        x_step = 1 if dx > sx else -1
        for x in range(sx, dx, x_step):
            links.append(((x, sy), (x + x_step, sy)))

        # Phase 2 — vertical: move along x = dx until y == dy
        y_step = 1 if dy > sy else -1
        for y in range(sy, dy, y_step):
            links.append(((dx, y), (dx, y + y_step)))

        return links

    def count_hops(self, src: int, dests: List[int]) -> int:
        """Count unique links used to reach all dests from src.

        Deduplicates shared path segments so that a multicast that fans
        out along a common trunk only counts that trunk once.

        For a single dest this equals the Manhattan distance (XY routing
        never reuses a link on a single path).
        """
        link_set: Set[Link] = set()
        for dest in dests:
            link_set.update(self._hops_single(src, dest))
        return len(link_set)

    def manhattan(self, src: int, dest: int) -> int:
        """Manhattan distance between two ports (= hop count for one dest)."""
        sx, sy = self.get_xy(src)
        dx, dy = self.get_xy(dest)
        return abs(dx - sx) + abs(dy - sy)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def all_pe_ids(self) -> List[int]:
        """Return the list of real PE IDs [0, X*Y)."""
        return list(range(self.num_pes))

    def __repr__(self) -> str:
        return (
            f"NoC(X={self.X}, Y={self.Y}, "
            f"gb_port={self.gb_port}, dram_port={self.dram_port})"
        )
