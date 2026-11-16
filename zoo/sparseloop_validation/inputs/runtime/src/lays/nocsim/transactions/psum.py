"""Psum load, K-chain reduction, and psum store transactions.

Three functions called in order at each (dram_i, noc_i) step:

  load_psum  — GB → K_max PE for each psum group     [skipped if is_first_K]
  k_chain    — serial unicasts K=0 → K=1 → … → K_max
  store_psum — K_max PE → GB for each psum group     [skipped if is_last_K]

Data sizing
-----------
data_size["psum"] is the total element count of the GB psum tile across all
psum addr groups.  Each group receives an equal share:

    size_bits = (data_size["psum"] // num_groups) × bw_psum

Hop accounting
--------------
load_psum  src = gb_port  → counted in unicast_hops.
k_chain    src = PE node  → excluded (node-to-node).
store_psum src = PE node  → excluded (node-to-GB, not GB-to-node).
"""

from __future__ import annotations

from typing import Dict, List

from ..core.generator import TC_Generator
from ..schedule.buf_spatial import BufSpatial


def load_psum(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_psum:      int,
    is_first_K:   bool,
    deps:         List[int],
    label_prefix: str,
    src_port:     int | None = None,
) -> Dict[tuple, int]:
    """Unicast the stored partial psum from GB to each K-chain tail PE.

    K_max is the natural accumulation point of the K-chain: it receives the
    running sum from K_{max-1} and must add it to whatever was already
    stored in GB from a prior temporal-K step.  So GB sends the carry-over
    value directly to K_max before the chain fires.

    Skipped when is_first_K is True: no psum has been written to GB yet, so
    there is nothing to reload.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides k_max_pes per psum addr group).
        data_size:    GB tile element counts keyed by var name.
        bw_psum:      Bits per psum element.
        is_first_K:   True when the combined (DRAM+GB) K index equals 0.
        deps:         TC ids that must complete before these loads can start.
        label_prefix: Step identifier, e.g. ``"psum_0_2"`` (dram_i=0, noc_i=2).
        src_port:     Override the send origin. None (default) uses
                      gen.noc.gb_port. Single-node mode passes
                      gen.noc.dram_port to elide the Global Buffer hop.

    Returns:
        {psum_addr → tc_id} for each group, or {} if skipped.
    """
    if is_first_K:
        return {}

    src = gen.noc.gb_port if src_port is None else src_port

    k_max = bs.k_max_pes()                              # {addr → k_max_pe_id}
    num_groups = len(k_max)
    size_bits = (data_size["psum"] // num_groups) * bw_psum

    tc_ids: Dict[tuple, int] = {}
    for addr, pe in sorted(k_max.items()):
        label = f"{label_prefix}__load_{pe}"
        tc_id = gen.unicast(
            "psum", size_bits, bw_psum,
            src, pe, deps, label,
        )
        tc_ids[addr] = tc_id
    return tc_ids


def k_chain(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_psum:      int,
    deps:         List[int],
    label_prefix: str,
) -> Dict[tuple, List[int]]:
    """Serial psum reduction chain: K=0 → K=1 → … → K_max per group.

    Each link is a unicast from one PE to the next higher-K PE in the same
    column.  The chain is serial within a group: link i+1 depends on link i.
    The first link of every group depends on ``deps`` (the MAC COUNT tc_ids),
    ensuring that K=0 has computed its partial sum before it sends.

    Different addr groups are independent and run concurrently.

    Groups with only one PE (no spatial K unrolling) produce an empty list.
    Node-to-node unicasts are excluded from hop counters.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides k_chain_groups).
        data_size:    GB tile element counts.
        bw_psum:      Bits per psum element.
        deps:         MAC COUNT tc_ids for this step (all PEs).
        label_prefix: Step identifier string.

    Returns:
        {psum_addr → [tc_id_link_0, tc_id_link_1, …]}.
        An empty list [] means the group has a single PE (no chain needed).
    """
    groups = bs.k_chain_groups()                        # {addr → [pe0, …, pe_kmax]}
    num_groups = len(groups)
    size_bits = (data_size["psum"] // num_groups) * bw_psum

    tc_ids: Dict[tuple, List[int]] = {}
    for addr, chain in sorted(groups.items()):
        link_ids: List[int] = []
        for i in range(len(chain) - 1):
            src = chain[i]
            dst = chain[i + 1]
            # Serial within a group: first link waits for MACs; each later
            # link waits only for the previous link (data arrives serially).
            link_dep = deps if i == 0 else [link_ids[-1]]
            label = f"{label_prefix}__kchain_{src}_{dst}"
            tc_id = gen.unicast(
                "psum", size_bits, bw_psum,
                src, dst, link_dep, label,
            )
            link_ids.append(tc_id)
        tc_ids[addr] = link_ids
    return tc_ids


def store_psum(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_psum:      int,
    is_last_K:    bool,
    deps:         List[int],
    label_prefix: str,
    dest_port:    int | None = None,
) -> Dict[tuple, int]:
    """Unicast the accumulated psum from each K-chain tail PE back to GB.

    After the K-chain completes, K_max holds the running partial sum for all
    spatial K tiles at this temporal-K step.  It stores this back to GB so
    that the next temporal-K step can reload it (via load_psum).

    Skipped when is_last_K is True: the K-reduction is fully complete and the
    result is immediately consumed by the LIF / T-chain; there is no need to
    write it back to GB.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides k_max_pes per psum addr group).
        data_size:    GB tile element counts.
        bw_psum:      Bits per psum element.
        is_last_K:    True when the combined (DRAM+GB) K index equals K_max.
        deps:         TC ids of the k_chain tail link(s) for this step.
        label_prefix: Step identifier string.
        dest_port:    Override the store destination. None (default) uses
                      gen.noc.gb_port. Single-node mode passes
                      gen.noc.dram_port to elide the Global Buffer hop.

    Returns:
        {psum_addr → tc_id} for each group, or {} if skipped.
    """
    if is_last_K:
        return {}

    dest = gen.noc.gb_port if dest_port is None else dest_port

    k_max = bs.k_max_pes()
    num_groups = len(k_max)
    size_bits = (data_size["psum"] // num_groups) * bw_psum

    tc_ids: Dict[tuple, int] = {}
    for addr, pe in sorted(k_max.items()):
        label = f"{label_prefix}__store_{pe}"
        tc_id = gen.unicast(
            "psum", size_bits, bw_psum,
            pe, dest, deps, label,
        )
        tc_ids[addr] = tc_id
    return tc_ids
