"""TC_Generator — stateful transaction list builder for the SNN-CoSA NoC simulator.

Owns:
  - the running tc_id counter
  - the ordered list of all TCs produced so far
  - the write_deps dict  (label → list of tc_ids that produced that label)
  - unicast_hops / multicast_hops / dram_cost counters, each a per-variable
    dict keyed by "weight" / "psum" / "vmem"

unicast_hops / multicast_hops track on-chip GB-sourced NoC traffic (hop
distance + flit count); dram_cost tracks DRAM-touching traffic (either
direction) weighted by dram_latency, since DRAM access is not modeled by
mesh hop distance. The two are independent — see NOC_SIM_DESIGN.md.

Label convention
----------------
Every TC is given a human-readable label (passed as ``label``).  Labels
follow a two-part scheme separated by ``__``:

    <base_name>__<kind>_<pe_ids>

    e.g.  "weight_0_2__send_5"          unicast weight to PE 5 at step (0,2)
          "psum_0_2__kchain_4_8"        K-chain link from PE 4 to PE 8
          "mac_0_2__count_5"            MAC COUNT at PE 5, step (0,2)

get_deps uses the ``__`` separator to distinguish:
  - exact-match lookups  (label already contains ``__``)
  - prefix-match lookups (label is the base_name only; optionally filtered
                          by pe_id extracted from the suffix)
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict, List

from .noc import NoC
from .transaction import TC, TCEncoder, UNICAST, MULTICAST, COUNT, PACKET_SIZE, FLITS_PER_PACKET


_TRAFFIC_VARS = ("weight", "psum", "vmem")


class TC_Generator:
    """Builds and stores the complete TC list for one simulation run.

    Args:
        noc:          A fully initialised NoC object (topology + port IDs).
        dram_latency: Per-packet DRAM access latency multiplier applied to
                      dram_cost. Default 17 (CoSA parity).
    """

    def __init__(self, noc: NoC, dram_latency: int = 17) -> None:
        self.noc          = noc
        self.dram_latency = dram_latency
        self.tc_id = 0
        self.tcs:        List[TC]             = []
        self.write_deps: Dict[str, List[int]] = {}

        # Per-variable cost counters, keyed by "weight" / "psum" / "vmem".
        # Pre-seeded (not defaultdict) so all three keys are always present,
        # even for a variable with zero traffic of that type.
        #
        # unicast_hops / multicast_hops — on-chip GB-sourced NoC traffic only.
        # dram_cost — DRAM-touching traffic (either direction), weighted by
        #             dram_latency; independent of the hop counters since
        #             DRAM access isn't modeled by mesh hop distance.
        self.unicast_hops:   Dict[str, int] = {v: 0 for v in _TRAFFIC_VARS}
        self.multicast_hops: Dict[str, int] = {v: 0 for v in _TRAFFIC_VARS}
        self.dram_cost:      Dict[str, int] = {v: 0 for v in _TRAFFIC_VARS}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _num_packets(self, size_bits: int) -> int:
        """Ceiling divide size_bits by PACKET_SIZE."""
        return (size_bits - 1) // PACKET_SIZE + 1

    def _append(self, tc: TC, label: str) -> int:
        """Append tc to the list, register label → [tc_id], return tc_id."""
        self.tcs.append(tc)
        self.write_deps[label] = [self.tc_id]
        self.tc_id += 1
        return self.tc_id - 1

    # ------------------------------------------------------------------
    # Primitive transaction constructors
    # ------------------------------------------------------------------

    def unicast(
        self,
        var_name:  str,
        size_bits: int,
        datawidth: int,
        src:       int,
        dest:      int,
        deps:      List[int],
        label:     str,
    ) -> int:
        """Send size_bits of var_name from src to one dest.

        Accumulates unicast_hops[var_name] when src == gb_port (on-chip).
        Accumulates dram_cost[var_name] when either end is dram_port,
        regardless of direction (load and store follow the same mechanism).

        Returns the tc_id assigned to this transaction.
        """
        num_packets = self._num_packets(size_bits)
        entries     = size_bits // datawidth if datawidth > 0 else 0
        annotation  = f"{label}: unicast {src}→{dest}  {size_bits}b  {num_packets}pkts  dep={deps}"

        tc = TC(self.tc_id, src, UNICAST, deps, var_name, entries, datawidth, annotation)
        tc.create_unicast(dest, num_packets)

        if src == self.noc.gb_port and dest != self.noc.dram_port:
            hops = self.noc.manhattan(src, dest)
            self.unicast_hops[var_name] += hops + num_packets * FLITS_PER_PACKET

        if src == self.noc.dram_port or dest == self.noc.dram_port:
            self.dram_cost[var_name] += num_packets * self.dram_latency

        return self._append(tc, label)

    def multicast(
        self,
        var_name:  str,
        size_bits: int,
        datawidth: int,
        src:       int,
        dests:     List[int],
        deps:      List[int],
        label:     str,
    ) -> int:
        """Send size_bits of var_name from src to all dests.

        Accumulates multicast_hops[var_name] (farthest-node rule) when
        src == gb_port. Multicast is never DRAM-sourced in this simulator
        (transactions/dram.py only ever calls unicast()), so there is no
        dram_cost branch here — only unicast() feeds dram_cost.

        Returns the tc_id assigned to this transaction.
        """
        num_packets = self._num_packets(size_bits)
        entries     = size_bits // datawidth if datawidth > 0 else 0
        annotation  = f"{label}: multicast {src}→{dests}  {size_bits}b  {num_packets}pkts  dep={deps}"

        tc = TC(self.tc_id, src, MULTICAST, deps, var_name, entries, datawidth, annotation)
        tc.create_multicast(dests, num_packets)

        if src == self.noc.gb_port:
            # farthest-node rule: latency set by the most distant receiver
            hops = max(self.noc.manhattan(src, d) for d in dests)
            self.multicast_hops[var_name] += hops + num_packets * FLITS_PER_PACKET

        return self._append(tc, label)

    def count(
        self,
        cycles:  int,
        node_id: int,
        deps:    List[int],
        label:   str,
    ) -> int:
        """Schedule node_id to compute for `cycles` cycles.

        COUNT transactions do not move data; they model PE computation time.
        No hop accumulation — COUNT is never GB-sourced.

        Returns the tc_id assigned to this transaction.
        """
        annotation = f"{label}: COUNT {node_id} for {cycles} cycles  dep={deps}"
        tc = TC(self.tc_id, node_id, COUNT, deps, "", 0, 0, annotation)
        tc.create_count(cycles)
        return self._append(tc, label)

    # ------------------------------------------------------------------
    # Dependency resolution
    # ------------------------------------------------------------------

    def _get_reqs(self, base: str, pe_id: int, out: List[str]) -> None:
        """Collect write_deps keys that match base, filtered by pe_id.

        Two matching modes:
          - base contains ``__``  →  exact key match (one specific TC)
          - base has no ``__``    →  prefix match on the part before ``__``
              - pe_id == -1       →  accept all keys with this prefix
              - pe_id != -1       →  only accept keys whose suffix encodes pe_id
                                     (suffix = last ``_``-delimited field,
                                      PE IDs joined by ``-`` for multicast groups)
        """
        if "__" in base:
            # exact match
            if base in self.write_deps:
                out.append(base)
        else:
            for key in self.write_deps:
                if key.split("__")[0] != base:
                    continue
                if pe_id == -1:
                    out.append(key)
                else:
                    # suffix is the last "_"-separated token; IDs joined by "-"
                    id_field = key.split("_")[-1]
                    ids = [int(x) for x in id_field.split("-")]
                    if pe_id in ids:
                        out.append(key)

    def get_deps(
        self,
        dep_labels: List[str],
        pe_id: int = -1,
    ) -> List[int]:
        """Resolve a list of label references to concrete tc_ids.

        Args:
            dep_labels: List of label strings (exact or prefix).
            pe_id:      If != -1, restrict prefix matches to labels whose
                        suffix encodes this PE id.  Use -1 to match all.

        Returns:
            Flat list of tc_ids that the caller should list as deps.
        """
        matched_keys: List[str] = []
        for lbl in dep_labels:
            self._get_reqs(lbl, pe_id, matched_keys)

        tc_ids: List[int] = []
        for key in matched_keys:
            tc_ids.extend(self.write_deps[key])
        return tc_ids

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def to_file(self, out_file: pathlib.Path) -> None:
        """Write all TCs to a CSV or JSON file.

        The file format is inferred from the suffix:
          .csv  →  one ``# annotation`` line + one data row per TC
          .json →  JSON array of TC dicts
        """
        out_file = pathlib.Path(out_file)
        if out_file.suffix == ".csv":
            text = "\n".join(tc.format_csv() for tc in self.tcs)
            out_file.write_text(text)
        elif out_file.suffix == ".json":
            out_file.write_text(
                json.dumps(self.tcs, indent=2, cls=TCEncoder)
            )
        else:
            raise ValueError(f"Unsupported output format: {out_file.suffix}")
