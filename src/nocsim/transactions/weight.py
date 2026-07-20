"""Weight load transactions: GB → all nodes for one NoC temporal step.

At each NoC temporal step the Global Buffer sends the current weight sub-tile
to every spatial PE.  The destination set is determined by the weight address
groups in buf_spatial:

  - PEs sharing the same weight address see the SAME weight data
    (same KH/KW/CIN/COUT spatial index, different HO/WO/T)
    → one multicast from GB to all PEs in the group

  - PEs with unique weight addresses each need DIFFERENT data
    → one unicast per PE

Data sizing
-----------
data_size["weight"] is the total element count of the GB weight tile.  This
tile is partitioned among the `num_groups` spatial weight groups, so each group
receives:

    size_bits = (data_size["weight"] // num_groups) × bw_weight

In the typical case all weight-relevant spatial factors are exhausted within the
GB tile, and each group therefore receives exactly the temporal weight factors'
worth of elements.

Hop accounting
--------------
Both unicasts and multicasts originate at gb_port, so they contribute to
TC_Generator.unicast_hops / multicast_hops.

Return value
------------
Dict[addr_tuple → tc_id]: lets combine.py track which weight loads to
list as dependencies of the subsequent MAC COUNT step.
"""

from __future__ import annotations

from typing import Dict, List

from ..core.generator import TC_Generator
from ..schedule.buf_spatial import BufSpatial


def load_weight(
    gen:            TC_Generator,
    bs:             BufSpatial,
    data_size:      Dict[str, int],
    bw_weight:      int,
    weight_changes: bool,
    deps:           List[int],
    label_prefix:   str,
    src_port:       int | None = None,
) -> Dict[tuple, int]:
    """Generate GB → node weight transactions for one NoC temporal step.

    Skipped when weight_changes is False: the weight tile is identical to the
    previous step (only weight-invariant dims HO/WO/T advanced in the NoC
    temporal loop), so there is no need to re-send it.

    Args:
        gen:            TC_Generator (accumulates TCs and hop counters).
        bs:             BufSpatial for the current solve (provides addr groups).
        data_size:      Decoded data sizes in elements, keyed by var name.
        bw_weight:      Bits per weight element (from SNNBitwidths.bw_weight).
        weight_changes: True if any weight-indexed dim (KH/KW/CIN/COUT) has a
                        different index at this step vs the previous step.
                        Supplied by StepInfo.weight_changes(noc_i).
        deps:           TC ids that must complete before these sends can start.
        label_prefix:   Step identifier string, e.g. ``"weight_0_2"``
                        (dram_i=0, noc_i=2).  The ``__send_<pes>`` suffix is
                        appended per group.
        src_port:       Override the send origin. None (default) uses
                        gen.noc.gb_port, matching every existing call site.
                        Single-node mode passes gen.noc.dram_port to send
                        directly from DRAM, eliding the Global Buffer hop.

    Returns:
        Dict mapping each weight address tuple to the tc_id of the send TC
        that serves that address group, or {} if skipped.
        Use these tc_ids as deps for the MAC COUNT step that consumes the
        weight data.
    """
    if not weight_changes:
        return {}

    src = gen.noc.gb_port if src_port is None else src_port

    groups = BufSpatial.addr_groups(bs.weight)
    num_groups = len(groups)

    # GB tile is split evenly among groups; division is always exact because
    # data_size["weight"] = spatial_weight_groups × temporal_weight_factors,
    # and num_groups = spatial_weight_groups.
    size_bits = (data_size["weight"] // num_groups) * bw_weight

    tc_ids: Dict[tuple, int] = {}

    # Iterate in deterministic order so CSV output is reproducible
    for addr, pes in sorted(groups.items()):
        # Encode destination PE(s) in the label for get_deps lookup
        pe_tag = "-".join(str(p) for p in pes)
        label  = f"{label_prefix}__send_{pe_tag}"

        if len(pes) == 1:
            tc_id = gen.unicast(
                "weight", size_bits, bw_weight,
                src, pes[0], deps, label,
            )
        else:
            tc_id = gen.multicast(
                "weight", size_bits, bw_weight,
                src, pes, deps, label,
            )

        tc_ids[addr] = tc_id

    return tc_ids
