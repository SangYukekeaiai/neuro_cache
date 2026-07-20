"""MAC and LIF COUNT transactions.

Two functions generating parallel COUNT transactions — one per PE node.

  mac_count — multiply-accumulate: weight × input_spike → partial psum
  lif_count — leaky integrate-and-fire: accumulated psum → vmem update

Both fire one COUNT TC per node with the same dep list; all nodes compute
concurrently (independent TCs, no inter-node data flow at this stage).

lif_count is only invoked when is_last_K is True (K-reduction must be
complete before vmem can be updated).  That guard lives in combine.py.

COUNT transactions model PE computation time.  They carry no data and are
never GB-sourced, so they contribute nothing to unicast_hops or
multicast_hops.
"""

from __future__ import annotations

from typing import Dict, List

from ..core.generator import TC_Generator


def mac_count(
    gen:          TC_Generator,
    node_ids:     List[int],
    pe_cycles:    int,
    deps:         List[int],
    label_prefix: str,
) -> Dict[int, int]:
    """Schedule one MAC COUNT TC per PE node, all running in parallel.

    Each TC models ``pe_cycles`` cycles of multiply-accumulate work
    (weight × input spike → accumulate into local partial psum).

    All nodes share the same ``deps``, so they can all start as soon as
    those dependencies are satisfied.  There is no ordering between nodes.

    Args:
        gen:          TC_Generator.
        node_ids:     All spatial PE ids, typically ``list(range(num_pes))``.
        pe_cycles:    Cycles for one MAC step at a single PE node.
        deps:         TC ids that must complete first: weight load tc_ids,
                      psum load tc_ids, and the double-buffer MAC dep
                      from step noc_i-2 (all combined by combine.py).
        label_prefix: Step identifier, e.g. ``"mac_0_2"`` (dram_i=0, noc_i=2).

    Returns:
        {pe_id → tc_id} for every node in node_ids.
    """
    tc_ids: Dict[int, int] = {}
    for pe in node_ids:
        label = f"{label_prefix}__count_{pe}"
        tc_id  = gen.count(pe_cycles, pe, deps, label)
        tc_ids[pe] = tc_id
    return tc_ids


def lif_count(
    gen:          TC_Generator,
    node_ids:     List[int],
    lif_cycles:   int,
    deps:         List[int],
    label_prefix: str,
) -> Dict[int, int]:
    """Schedule one LIF COUNT TC per PE node, all running in parallel.

    Each TC models ``lif_cycles`` cycles of leaky integrate-and-fire work
    (accumulated psum drives the LIF neuron → vmem update).

    Shares the same parallel structure as mac_count.  Only invoked when
    is_last_K is True; that condition is checked by combine.py.

    Args:
        gen:          TC_Generator.
        node_ids:     All spatial PE ids, typically ``list(range(num_pes))``.
        lif_cycles:   Cycles for one LIF step at a single PE node.
        deps:         TC ids that must complete first: k_chain tail tc_ids,
                      vmem load tc_ids (if any), and the double-buffer LIF dep
                      from step noc_i-2 (all combined by combine.py).
        label_prefix: Step identifier, e.g. ``"lif_0_2"`` (dram_i=0, noc_i=2).

    Returns:
        {pe_id → tc_id} for every node in node_ids.
    """
    tc_ids: Dict[int, int] = {}
    for pe in node_ids:
        label = f"{label_prefix}__count_{pe}"
        tc_id  = gen.count(lif_cycles, pe, deps, label)
        tc_ids[pe] = tc_id
    return tc_ids
