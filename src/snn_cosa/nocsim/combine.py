"""combine.py — main nested loop orchestrating all NoC and DRAM transactions.

Called once per solved MIP result to generate the complete TC list.  Returns
the populated TC_Generator for output and hop-count extraction.

Loop structure
--------------
for dram_i in range(dram_num_steps):
    [DRAM → GB loads: weight, psum (skip if first-K or dram-free),
                      vmem  (skip if not last-K, first-T, or dram-free)]
    for noc_i in range(noc_num_steps):
        1. load_weight  (skip if weight unchanged at this step)
        2. load_psum    (skip if is_first_K  OR  is_psum_gb_free)
        3. mac_count    (all PEs, parallel)
        4. k_chain
        5. store_psum   (skip if is_last_K   OR  is_psum_gb_free)
        if is_last_K:
            6. load_vmem  (skip if is_first_T  OR  is_vmem_gb_free)
            7. lif_count  (all PEs, parallel)
            8. t_chain
            9. store_vmem (skip if is_last_T   OR  is_vmem_gb_free)
    [GB → DRAM stores: psum (skip if last-K  or dram-free),
                       vmem (skip if not last-K, last-T, or dram-free)]

Double-buffer dependency pattern
---------------------------------
Every GB load has two independent deps: (B) buffer slot freed, (D) data committed.
Both must appear — neither subsumes the other.

  load_weight at noc_i   ← load_weight[noc_i-1]             (S: sequential GB sends)
                          ← mac_count[noc_i-2]               (B: node buf freed 2 steps ago)
  load_psum   at noc_i   ← store_psum[noc_i-2]              (B: GB buf freed 2 steps ago)
                          ← store_psum[noc_i-T_noc_steps]   (D: same-T partial sum committed)
  mac_count   at noc_i   ← mac_count[noc_i-2]               (B: node double-buffer)
  load_vmem   at vmem_step  ← store_vmem[vmem_step-2]       (B: GB buf freed 2 vmem-steps ago)
                             ← store_vmem[vmem_step-1]       (D: prev-T vmem committed)
  lif_count   at vmem_step  ← lif_count[vmem_step-2]        (B: node double-buffer)
                             ← t_chain[vmem_step-1]          (D: vmem carry-over from prev T)

"vmem_step" counts only is_last_K firings within a dram_i block, not raw noc_i.
vs_hist and lif_hist are sparse (populated only at is_last_K noc_i values), so the
raw noc_i-2 offset would miss the prior entry whenever K is a NoC temporal dimension
(consecutive is_last_K steps are K_noc × N_inner noc_i apart, not 2).
A rolling deque of size 2 (vmem_store_ring / lif_ring) is used instead.

The remaining history dicts (ps_hist, mac_hist, w_hist) are keyed by noc_i and reset
at the start of each dram_i; they remain dense because psum/weight/mac ops fire at
every noc_i step.

GB-free flags
--------------
is_psum_gb_free / is_vmem_gb_free are structural flags set once from the
loop ordering.  When True, the PE holds the intermediate result in its local
buffer for the entire K (or T) temporal range without any GB round-trip.
This is applied by overriding is_first_K / is_last_K / is_first_T / is_last_T
passed to the transaction builders:

  load_psum(is_first_K = is_first_K OR is_psum_gb_free)   → always skip load
  store_psum(is_last_K = is_last_K  OR is_psum_gb_free)   → always skip store
  load_vmem / store_vmem: same pattern with is_vmem_gb_free
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

from snn_cosa.parsers.layer import (
    SNNProb,
    DIM_T, DIM_WO, DIM_HO, DIM_CIN, DIM_KW, DIM_KH, DIM_COUT,
)
from snn_cosa.parsers.arch import SNNArch
from snn_cosa.parsers.bitwidths import SNNBitwidths
from snn_cosa.archmodels import ArchComputeModel
from snn_cosa.archmodels.dense import DenseStaticComputeModel

from .core.noc import NoC
from .core.generator import TC_Generator
from .schedule.decode import Schedule
from .schedule.buf_spatial import BufSpatial
from .schedule.steps import StepInfo
from .transactions.weight import load_weight
from .transactions.psum import load_psum, k_chain, store_psum
from .transactions.vmem import load_vmem, t_chain, store_vmem
from .transactions.compute import mac_count, lif_count
from .transactions.dram import load_from_dram, store_to_dram


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _dim_totals(loops) -> Dict[int, int]:
    """Return {dim: product-of-all-factors} for every dim that appears in loops."""
    totals: Dict[int, int] = {}
    for loop in loops:
        totals[loop.dim] = totals.get(loop.dim, 1) * loop.factor
    return totals


def _vals(d: dict) -> List[int]:
    """Flatten a result-dict's values into a plain list of tc_ids."""
    return list(d.values())


def _chain_tails(chain_dict: Dict[tuple, List[int]]) -> List[int]:
    """Return the last link tc_id from each chain group that has any links.

    Groups with a single PE return an empty list — those are excluded.
    """
    return [links[-1] for links in chain_dict.values() if links]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def combine(
    schedule:  Schedule,
    bs:        BufSpatial,
    si:        StepInfo,
    prob:      SNNProb,
    bitwidths: SNNBitwidths,
    arch:      Optional[SNNArch] = None,
    compute_model: Optional[ArchComputeModel] = None,
) -> TC_Generator:
    """Generate all TCs for one simulation run and return the TC_Generator.

    Args:
        schedule:  Decoded loop structure (spatial_factors, temporal loops,
                   data_size, step counts).
        bs:        BufSpatial holding PE addresses and chain-group helpers.
        si:        StepInfo with position flags, traffic-free flags, and the
                   weight_changes() method.
        prob:      Parsed SNN layer (dimension prime factors, num dims).
        bitwidths: Per-variable bit widths (bw_weight, bw_psum, bw_vmem).
        arch:      Parsed arch config. When arch.single_node is True, every
                   GB-mediated DRAM<->node transfer collapses into one
                   direct DRAM<->node transfer (see PLAN_single_node.md) --
                   the separate DRAM<->GB leg is skipped entirely and
                   load_weight/load_psum/load_vmem/store_psum/store_vmem
                   send/receive straight from/to gen.noc.dram_port. None
                   (default) behaves exactly as before this parameter
                   existed -- every existing call site is unaffected.
        compute_model: Optional per-architecture cycle model. None (default)
                   uses DenseStaticComputeModel, exactly reproducing today's
                   static formula.

    Returns:
        TC_Generator with all TCs appended and unicast/multicast hop counters
        updated.  Call gen.to_file() to write the CSV and gen.unicast_hops /
        gen.multicast_hops / gen.dram_cost (each a per-variable dict keyed
        by "weight"/"psum"/"vmem") to read the totals.
    """
    single_node = arch is not None and arch.single_node
    # ── 1. Construct NoC and TC_Generator ────────────────────────────────
    # Way-2 layout: X axis = T × WO × HO (inner → outer);
    #               Y axis = CIN × KW × KH × COUT (inner → outer).
    sf  = schedule.spatial_factors
    X   = sf[DIM_T] * sf[DIM_WO] * sf[DIM_HO]
    Y   = sf[DIM_CIN] * sf[DIM_KW] * sf[DIM_KH] * sf[DIM_COUT]
    gen = TC_Generator(NoC(X, Y), dram_latency=bitwidths.dram_latency)

    # ── 2. Pre-compute cycle counts ───────────────────────────────────────
    model = compute_model or DenseStaticComputeModel(schedule, prob)
    cycles = model.compute_cycles(model.format_input(None, None), None)
    mac_cyc = cycles.mac_cycles
    lif_cyc = cycles.lif_cycles if cycles.lif_cycles is not None else 0

    # ── 3. Shorthands ────────────────────────────────────────────────────
    ds    = schedule.data_size
    bww   = bitwidths.bw_weight
    bwp   = bitwidths.bw_psum
    bwv   = bitwidths.bw_vmem
    nodes = list(range(bs.num_pes))

    # Structural GB-free flags: True → skip ALL GB traffic for that variable
    skip_psum_gb = si.is_psum_gb_free
    skip_vmem_gb = si.is_vmem_gb_free

    # Number of distinct T values at the NoC temporal level.  Used for the
    # psum same-T data dep: for T-inner-K, consecutive stores of the same T
    # index are exactly T_noc_steps noc_i apart.
    T_noc_steps = _dim_totals(schedule.noc_temporal_loops).get(DIM_T, 1)

    # ── 4. Cross-dram_i dependency tracking ──────────────────────────────
    # DRAM store tc_ids from dram_i-1 gate the corresponding DRAM loads of
    # dram_i, ensuring the two steps are properly ordered.
    prev_dram_psum_store: Optional[int] = None
    prev_dram_vmem_store: Optional[int] = None

    # ── 5. Outer DRAM loop ────────────────────────────────────────────────
    for dram_i in range(schedule.dram_num_steps):
        dlbl = f"dram_{dram_i}"

        (is_first_K_dram, is_last_K_dram) = si.dram_k_position(dram_i)
        (is_first_T_dram, is_last_T_dram) = si.dram_t_position(dram_i)

        # ── 5a. DRAM → GB loads ───────────────────────────────────────────
        # Single-node mode: no Global Buffer exists, so this leg is skipped
        # unconditionally -- load_weight/load_psum/load_vmem send straight
        # from DRAM instead (src_port=gen.noc.dram_port below).
        #
        # Weight: always transfers; no prior DRAM store to sequence against.
        dram_w_id = load_from_dram(
            gen, "weight", ds, bww,
            skip=single_node,
            deps=[],
            label_prefix=dlbl,
        )

        # Psum: skip if this is the first K iteration (nothing in DRAM yet)
        #       or if psum is completely free of DRAM traffic.
        dram_p_id = load_from_dram(
            gen, "psum", ds, bwp,
            skip=(single_node or is_first_K_dram or si.is_psum_dram_free),
            deps=([prev_dram_psum_store] if prev_dram_psum_store is not None else []),
            label_prefix=dlbl,
        )

        # Vmem: only meaningful when K-reduction is complete at DRAM level.
        #       Skip when K is not yet at its last DRAM index (no LIF output
        #       has been produced), or when T is at its first (no prior vmem),
        #       or when vmem traffic is entirely free of DRAM round-trips.
        dram_v_id = load_from_dram(
            gen, "vmem", ds, bwv,
            skip=(single_node or not is_last_K_dram or is_first_T_dram or si.is_vmem_dram_free),
            deps=([prev_dram_vmem_store] if prev_dram_vmem_store is not None else []),
            label_prefix=dlbl,
        )

        # ── 5b. Double-buffer histories (reset per dram_i) ────────────────
        # Dense histories (keyed by noc_i): psum/weight/mac fire every step.
        w_hist:   Dict[int, dict] = {}   # weight loads
        mac_hist: Dict[int, dict] = {}   # MAC COUNT results
        ps_hist:  Dict[int, dict] = {}   # psum stores
        # Sparse histories (keyed by noc_i, only at is_last_K steps):
        lif_hist: Dict[int, dict] = {}   # LIF COUNT results (for DRAM store fallback)
        vs_hist:  Dict[int, dict] = {}   # vmem stores       (for DRAM store fallback)
        # Ring buffers of size 2 for vmem/LIF double-buffer deps.
        # These count vmem-steps (is_last_K firings), not raw noc_i, so the
        # [-2] entry is always "2 vmem-steps ago" regardless of K's noc stride.
        vmem_store_ring: Deque[dict] = deque(maxlen=2)
        lif_ring:        Deque[dict] = deque(maxlen=2)

        # Updated at every noc_i; used after the inner loop for DRAM store deps.
        last_kchain_tails: List[int] = []
        last_tchain_tails: List[int] = []

        # Tracks the t_chain tails from the previous is_last_K vmem step.
        # Added to lif_deps so that LIF(T=t+1) always waits for t_chain(T=t):
        #   - when is_vmem_gb_free=True (T-inner-K): no store/load path exists,
        #     so this is the ONLY vmem ordering dep across consecutive T steps.
        #   - when is_vmem_gb_free=False: redundant but harmless.
        prev_tchain_tails: List[int] = []

        # ── 5c. Inner NoCLevel loop ───────────────────────────────────────
        for noc_i in range(schedule.noc_num_steps):
            nlbl = f"{dram_i}_{noc_i}"

            (is_first_K, is_last_K) = si.k_position(dram_i, noc_i)
            (is_first_T, is_last_T) = si.t_position(dram_i, noc_i)

            # ── Step 1: Weight load  (GB → all nodes) ─────────────────────
            # Two deps:
            #   a) previous weight load (noc_i-1): sequential GB sends avoid
            #      simultaneous accesses to the same GB weight bank.
            #   b) MAC COUNT two steps back (noc_i-2): node double-buffer —
            #      the PE finishes consuming its prior weight tile, freeing
            #      its local buffer to accept the incoming weight.
            # At noc_i=0 we add the DRAM weight load in place of dep (a).
            # Single-node: dram_w_id is always None (the DRAM->GB leg is
            # skipped entirely, see 5a above) and there is no shared GB
            # weight bank to serialize sends on, so dep (a) does not apply;
            # load_weight sends straight from DRAM via src_port below.
            w_deps: List[int] = []
            if noc_i == 0:
                if dram_w_id is not None:
                    w_deps.append(dram_w_id)
            else:
                # Sequential: wait for the previous weight send to finish
                w_deps.extend(_vals(w_hist.get(noc_i - 1, {})))
            if noc_i >= 2:
                # Node double-buffer: PE freed its old weight buffer 2 steps ago
                w_deps.extend(_vals(mac_hist.get(noc_i - 2, {})))

            w_tcs = load_weight(
                gen, bs, ds, bww,
                weight_changes=si.weight_changes(noc_i),
                deps=w_deps,
                label_prefix=f"weight_{nlbl}",
                src_port=(gen.noc.dram_port if single_node else None),
            )
            w_hist[noc_i] = w_tcs

            # ── Step 2: Psum load  (GB → K_max PE per group) ─────────────
            # Skipped if no prior psum to reload (is_first_K) or if the PE
            # holds its psum locally across all K steps (is_psum_gb_free).
            # Three deps:
            #   a) psum store two steps back (noc_i-2): GB double-buffer.
            #   b) psum store T_noc_steps back: same-T data ordering — for
            #      T-inner-K, the partial sum for T index t was last stored at
            #      noc_i - T_noc_steps and must be committed before reloading.
            #   c) DRAM psum load: DRAM tile must have landed in GB first.
            #   d) single-node only: the previous dram_i's store_psum wrote
            #      directly to DRAM (no separate store_to_dram leg exists
            #      to depend on instead -- see 5d below); this is the
            #      read-after-write ordering dram_p_id would otherwise
            #      provide, and dram_p_id is always None here (5a skips it
            #      unconditionally in single-node mode).
            pl_deps: List[int] = []
            if noc_i >= 2:
                pl_deps.extend(_vals(ps_hist.get(noc_i - 2, {})))           # (a) buf
            if noc_i >= T_noc_steps:
                pl_deps.extend(_vals(ps_hist.get(noc_i - T_noc_steps, {}))) # (b) data
            if dram_p_id is not None:
                pl_deps.append(dram_p_id)                                    # (c) DRAM
            if single_node and prev_dram_psum_store is not None:
                pl_deps.append(prev_dram_psum_store)                         # (d) single-node RAW

            pl_tcs = load_psum(
                gen, bs, ds, bwp,
                is_first_K=(is_first_K or skip_psum_gb),
                deps=pl_deps,
                label_prefix=f"psum_{nlbl}",
                src_port=(gen.noc.dram_port if single_node else None),
            )

            # ── Step 3: MAC COUNT  (all PEs, parallel) ────────────────────
            # Deps: weight loads, psum loads (if any), and the node
            # double-buffer: PE must have finished its prior MAC work (noc_i-2)
            # before it can start a new one into the same node buffer bank.
            mac_deps: List[int] = _vals(w_tcs) + _vals(pl_tcs)
            if noc_i >= 2:
                mac_deps.extend(_vals(mac_hist.get(noc_i - 2, {})))

            mac_tcs = mac_count(
                gen, nodes, mac_cyc, mac_deps,
                label_prefix=f"mac_{nlbl}",
            )
            mac_hist[noc_i] = mac_tcs

            # ── Step 4: K-chain  (K=0 → K=1 → … → K_max per group) ──────
            # Serial within a group; all groups run in parallel.
            # Dep: MAC COUNT (all PEs must finish before the chain starts so
            # that K=0 has its partial sum ready to forward).
            kchain_tcs = k_chain(
                gen, bs, ds, bwp,
                deps=_vals(mac_tcs),
                label_prefix=f"psum_{nlbl}",
            )
            kchain_tails = _chain_tails(kchain_tcs)
            # If all groups are single-PE (no chain links), the MAC result
            # at each PE IS the K_max output — use MAC ids as the effective tail.
            if not kchain_tails:
                kchain_tails = _vals(mac_tcs)
            last_kchain_tails = kchain_tails

            # ── Step 5: Psum store  (K_max PE → GB per group) ────────────
            # Skipped if this is the last K step (result consumed by LIF next)
            # or if psum is held in the PE across all K steps.
            ps_tcs = store_psum(
                gen, bs, ds, bwp,
                is_last_K=(is_last_K or skip_psum_gb),
                deps=kchain_tails,
                label_prefix=f"psum_{nlbl}",
                dest_port=(gen.noc.dram_port if single_node else None),
            )
            ps_hist[noc_i] = ps_tcs

            # Steps 6-9 only fire when the K-reduction is complete
            if not is_last_K:
                continue

            # ── Step 6: Vmem load  (GB → T_min PE per group) ─────────────
            # Skipped if no prior vmem in GB (is_first_T) or if vmem is
            # held in the PE across all T steps (is_vmem_gb_free).
            # Three deps:
            #   a) vmem_store_ring[-2]: GB double-buffer (slot freed 2 vmem-steps ago).
            #   b) vmem_store_ring[-1]: prev-T data ordering — T_max's store at T=t-1
            #      must commit to GB before T_min can reload it at T=t.
            #   c) DRAM dep: DRAM vmem tile must have landed in GB first.
            #   d) single-node only: the previous dram_i's store_vmem wrote
            #      directly to DRAM -- same reasoning as psum dep (d) above.
            # vmem_store_ring counts vmem-steps, not raw noc_i.
            vl_deps: List[int] = []
            if len(vmem_store_ring) >= 2:
                vl_deps.extend(_vals(vmem_store_ring[-2]))  # (a) buf
            if len(vmem_store_ring) >= 1:
                vl_deps.extend(_vals(vmem_store_ring[-1]))  # (b) data
            if dram_v_id is not None:
                vl_deps.append(dram_v_id)                   # (c) DRAM
            if single_node and prev_dram_vmem_store is not None:
                vl_deps.append(prev_dram_vmem_store)         # (d) single-node RAW

            vl_tcs = load_vmem(
                gen, bs, ds, bwv,
                is_first_T=(is_first_T or skip_vmem_gb),
                deps=vl_deps,
                label_prefix=f"vmem_{nlbl}",
                src_port=(gen.noc.dram_port if single_node else None),
            )

            # ── Step 7: LIF COUNT  (all PEs, parallel) ───────────────────
            # Deps: k-chain tails (accumulated psum must be ready), vmem
            # loads (carry-over membrane potential must have arrived),
            # prev_tchain_tails (T carry-over ordering dep), and the node
            # double-buffer for the LIF phase.
            # lif_ring[-2] is "2 vmem-steps ago" (same local bank reuse),
            # not noc_i-2: lif_hist is sparse (only is_last_K steps), so the
            # raw offset would miss the prior entry when K is a NoC temporal dim.
            # prev_tchain_tails: when is_vmem_gb_free=True (T-inner-K), no
            # store/load path exists for vmem, so this is the ONLY dep that
            # orders LIF(T=t+1) after t_chain(T=t).
            lif_deps: List[int] = list(kchain_tails) + _vals(vl_tcs) + prev_tchain_tails
            if len(lif_ring) >= 2:
                lif_deps.extend(_vals(lif_ring[-2]))

            lif_tcs = lif_count(
                gen, nodes, lif_cyc, lif_deps,
                label_prefix=f"lif_{nlbl}",
            )
            lif_hist[noc_i] = lif_tcs
            lif_ring.append(lif_tcs)

            # ── Step 8: T-chain  (T=0 → T=1 → … → T_max per group) ──────
            # Serial within each K_max-row vmem group; all groups parallel.
            tchain_tcs = t_chain(
                gen, bs, ds, bwv,
                deps=_vals(lif_tcs),
                label_prefix=f"vmem_{nlbl}",
            )
            tchain_tails = _chain_tails(tchain_tcs)
            if not tchain_tails:
                tchain_tails = _vals(lif_tcs)
            last_tchain_tails = tchain_tails
            prev_tchain_tails = tchain_tails   # gates next vmem-step's LIF

            # ── Step 9: Vmem store  (T_max PE → GB per group) ────────────
            # Skipped if this is the last T step (final membrane state —
            # no further T step will reload it) or if vmem is local to PE.
            vs_tcs = store_vmem(
                gen, bs, ds, bwv,
                is_last_T=(is_last_T or skip_vmem_gb),
                deps=tchain_tails,
                label_prefix=f"vmem_{nlbl}",
                dest_port=(gen.noc.dram_port if single_node else None),
            )
            vs_hist[noc_i] = vs_tcs
            vmem_store_ring.append(vs_tcs)

        # ── 5d. GB → DRAM stores (after inner loop) ──────────────────────
        # Single-node: store_psum/store_vmem above already wrote directly
        # to DRAM (dest_port=gen.noc.dram_port) whenever they fired, so
        # this separate GB->DRAM leg is skipped unconditionally; the tc_id
        # to order the *next* dram_i's load against comes from ps_hist/
        # vs_hist instead of this (skipped) store_to_dram call.
        last_noc = schedule.noc_num_steps - 1

        # Psum store deps: prefer the last NoC-step psum store (which carries
        # the latest partial sum); fall back to k-chain tails if the store
        # was skipped (is_last_K at last noc_i → psum consumed by LIF).
        ps_store_deps = _vals(ps_hist.get(last_noc, {})) or last_kchain_tails
        dram_ps = store_to_dram(
            gen, "psum", ds, bwp,
            skip=(single_node or is_last_K_dram or si.is_psum_dram_free),
            deps=ps_store_deps,
            label_prefix=dlbl,
        )
        if single_node:
            last_ps_tcs = _vals(ps_hist.get(last_noc, {}))
            prev_dram_psum_store = last_ps_tcs[0] if last_ps_tcs else None
        else:
            prev_dram_psum_store = dram_ps   # gates next dram_i's psum DRAM load

        # Vmem store deps: last vmem store from the NoC loop (if any ran),
        # or the t-chain tails from the last is_last_K step.
        vs_store_deps = _vals(vs_hist.get(last_noc, {})) or last_tchain_tails
        dram_vs = store_to_dram(
            gen, "vmem", ds, bwv,
            skip=(single_node or not is_last_K_dram or is_last_T_dram or si.is_vmem_dram_free),
            deps=vs_store_deps,
            label_prefix=dlbl,
        )
        if single_node:
            last_vs_tcs = _vals(vs_hist.get(last_noc, {}))
            prev_dram_vmem_store = last_vs_tcs[0] if last_vs_tcs else None
        else:
            prev_dram_vmem_store = dram_vs   # gates next dram_i's vmem DRAM load

    return gen
