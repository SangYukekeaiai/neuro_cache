"""Vmem load, T-chain LIF update, and vmem store transactions.

Three functions called in order at each (dram_i, noc_i) step, but only when
is_last_K is True (K-reduction must be complete before vmem can be updated).
That guard lives in combine.py; these functions are unaware of it.

  load_vmem  — GB → T_min PE for each vmem group    [skipped if is_first_T]
  t_chain    — serial unicasts T=0 → T=1 → … → T_max
  store_vmem — T_max PE → GB for each vmem group     [skipped if is_last_T]

Contrast with psum
------------------
  psum load → K_max (tail): K_max accumulates the chain result on top of the
                             carry-over, so the carry-over arrives at the end.
  vmem load → T_min (head): T_min starts the LIF update sequence; it must
                             be initialised with the carry-over membrane
                             potential before passing to T=1, T=2, …

Data sizing
-----------
data_size["vmem"] is the total element count of the GB vmem tile across all
vmem addr groups.  Each group receives an equal share:

    size_bits = (data_size["vmem"] // num_groups) × bw_vmem

Hop accounting
--------------
load_vmem  src = gb_port  → counted in unicast_hops.
t_chain    src = PE node  → excluded (node-to-node).
store_vmem src = PE node  → excluded (node-to-GB, not GB-to-node).
"""

from __future__ import annotations

from typing import Dict, List

from ..core.generator import TC_Generator
from ..schedule.buf_spatial import BufSpatial


def load_vmem(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_vmem:      int,
    is_first_T:   bool,
    deps:         List[int],
    label_prefix: str,
    src_port:     int | None = None,
) -> Dict[tuple, int]:
    """Unicast the carry-over vmem from GB to each T-chain head PE (T_min).

    T_min (T=0 spatial PE) is the starting node of the LIF update chain.
    It needs the membrane potential from the previous temporal-T step as its
    initial state before computing its own LIF and forwarding to T=1.

    Skipped when is_first_T is True: no vmem has been written to GB yet,
    so the membrane potential is implicitly zero — nothing to reload.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides t_min_pes per vmem addr group).
        data_size:    GB tile element counts keyed by var name.
        bw_vmem:      Bits per vmem element.
        is_first_T:   True when the combined (DRAM+GB) T index equals 0.
        deps:         TC ids that must complete before these loads can start.
        label_prefix: Step identifier, e.g. ``"vmem_0_2"`` (dram_i=0, noc_i=2).
        src_port:     Override the send origin. None (default) uses
                      gen.noc.gb_port. Single-node mode passes
                      gen.noc.dram_port to elide the Global Buffer hop.

    Returns:
        {vmem_addr → tc_id} for each group, or {} if skipped.
    """
    if is_first_T:
        return {}

    src = gen.noc.gb_port if src_port is None else src_port

    t_min = bs.t_min_pes()                              # {addr → t_min_pe_id}
    num_groups = len(t_min)
    size_bits = (data_size["vmem"] // num_groups) * bw_vmem

    tc_ids: Dict[tuple, int] = {}
    for addr, pe in sorted(t_min.items()):
        label = f"{label_prefix}__load_{pe}"
        tc_id = gen.unicast(
            "vmem", size_bits, bw_vmem,
            src, pe, deps, label,
        )
        tc_ids[addr] = tc_id
    return tc_ids


def t_chain(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_vmem:      int,
    deps:         List[int],
    label_prefix: str,
) -> Dict[tuple, List[int]]:
    """Serial vmem LIF-update chain: T=0 → T=1 → … → T_max per group.

    Each link carries the updated membrane potential from one PE to the next.
    The chain is serial within a group: link i+1 depends on link i.
    The first link of every group depends on ``deps`` (the LIF COUNT tc_ids),
    ensuring T=0 has completed its LIF update before forwarding its vmem.

    Different vmem addr groups are independent and run concurrently.
    Groups with a single PE return an empty list (no link needed).
    Node-to-node unicasts are excluded from hop counters.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides t_chain_groups, K_max row only).
        data_size:    GB tile element counts.
        bw_vmem:      Bits per vmem element.
        deps:         LIF COUNT tc_ids for this step (all K_max-row PEs).
        label_prefix: Step identifier string.

    Returns:
        {vmem_addr → [tc_id_link_0, tc_id_link_1, …]}.
        [] for groups with a single PE.
    """
    groups = bs.t_chain_groups()                        # {addr → [pe_t0, …, pe_tmax]}
    num_groups = len(groups)
    size_bits = (data_size["vmem"] // num_groups) * bw_vmem

    tc_ids: Dict[tuple, List[int]] = {}
    for addr, chain in sorted(groups.items()):
        link_ids: List[int] = []
        for i in range(len(chain) - 1):
            src = chain[i]
            dst = chain[i + 1]
            link_dep = deps if i == 0 else [link_ids[-1]]
            label = f"{label_prefix}__tchain_{src}_{dst}"
            tc_id = gen.unicast(
                "vmem", size_bits, bw_vmem,
                src, dst, link_dep, label,
            )
            link_ids.append(tc_id)
        tc_ids[addr] = link_ids
    return tc_ids


def store_vmem(
    gen:          TC_Generator,
    bs:           BufSpatial,
    data_size:    Dict[str, int],
    bw_vmem:      int,
    is_last_T:    bool,
    deps:         List[int],
    label_prefix: str,
    dest_port:    int | None = None,
) -> Dict[tuple, int]:
    """Unicast the updated vmem from each T-chain tail PE (T_max) back to GB.

    After the T-chain completes, T_max holds the final membrane potential for
    all spatial T tiles at this temporal-T step.  It stores this back to GB
    so the next temporal-T step can reload it (via load_vmem at T_min).

    Skipped when is_last_T is True: the full T-reduction is done and the
    result is the final output; no further temporal-T step will reload it.

    Args:
        gen:          TC_Generator.
        bs:           BufSpatial (provides t_max_pes per vmem addr group).
        data_size:    GB tile element counts.
        bw_vmem:      Bits per vmem element.
        is_last_T:    True when the combined (DRAM+GB) T index equals T_max.
        deps:         TC ids of the t_chain tail link(s) for this step.
        label_prefix: Step identifier string.
        dest_port:    Override the store destination. None (default) uses
                      gen.noc.gb_port. Single-node mode passes
                      gen.noc.dram_port to elide the Global Buffer hop.

    Returns:
        {vmem_addr → tc_id} for each group, or {} if skipped.
    """
    if is_last_T:
        return {}

    dest = gen.noc.gb_port if dest_port is None else dest_port

    t_max = bs.t_max_pes()
    num_groups = len(t_max)
    size_bits = (data_size["vmem"] // num_groups) * bw_vmem

    tc_ids: Dict[tuple, int] = {}
    for addr, pe in sorted(t_max.items()):
        label = f"{label_prefix}__store_{pe}"
        tc_id = gen.unicast(
            "vmem", size_bits, bw_vmem,
            pe, dest, deps, label,
        )
        tc_ids[addr] = tc_id
    return tc_ids
