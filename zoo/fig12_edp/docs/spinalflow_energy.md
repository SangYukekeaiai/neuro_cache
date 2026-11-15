# SpinalFlow node energy plan (Fig 12, 7 nm)

Status: accepted 2026-11-12; dispatched as T60/T61. **Scope note (user,
2026-11-12): the cache design's energy implementation is an independent,
deferred step: nothing cache-side is implemented now; this plan covers the
scratchpad/node side only.** Parent plan:
`docs/plans/2026-11-11-fig12-edp-plan.md`. Sources: SpinalFlow paper
(Narayanan et al., ISCA 2020); lays model
`src/lays/weight_trace_gen/spinalflow/SpinalFlowGen.h`;
`zoo/wt500_fig3cfg/walkthroughs/spinalflow.md`;
`docs/weight_trace_gen_archs.md` §8; campaign `zoo/wt500_fig3cfg/arch.yaml`
(16 nodes x 4 PEs, L1 weight 32 KB, BW_WEIGHT 8, BW_VMEM 32, BW_PSUM 16,
L1 vmem/psum 1 KB).

## 1. Check of the user's understanding

1. **COUT 128 -> 4 so PEs 128 -> 4: correct.** SpinalFlow maps one output
   neuron (COUT channel) per PE; our node mapspace pins COUT {spatial: 4}
   and everything else temporal (KH, KW, CIN, T resident). One caveat: the
   solver picks the node COUT factor as the largest divisor of COUT <= 4
   (`src/lays/scheduler/constraints/node_level.py`), so layers whose COUT is
   not a multiple of 4 run with 2 or 1 active lanes uniformly: ops scale by
   `cout_n`, not a blanket 4.
2. **"Rest stays the same": structurally yes, geometrically no.** Datapath
   and dataflow are the paper's; every buffer size comes from the campaign
   arch.yaml (L1 weight 32 KB, vmem/psum 1 KB), not from the paper. That is
   deliberate (equal on-chip capacity across designs). Per-access energies
   are computed at OUR sizes.
3. **"Accumulation + LIF ops = MAC cycle count": right per lane, with two
   corrections.**
   - The model processes one spike event per cycle with all lanes in
     lockstep (`SpinalFlowGen.h:74-83`), so per-lane accumulates = per-node
     mac_cycles, and SpinalFlow's "LIF" is a threshold compare + conditional
     reset on every accumulate, so compares = accumulates. Total ops =
     spikes x cout_n per node, summed over nodes.
   - **step_cycles cannot supply this count.** `assemble_layer_traces`
     stores mac_cycles as the MAX over the 16 nodes per step
     (`src/lays/weight_trace_gen/weight_trace.py:174`): right for latency,
     wrong for energy (energy needs the SUM of work over nodes).
     `lif_cycles` is always None for trace-driven archs.
4. **The lays model contains no compute hardware at all** (no accumulate,
   no compare, no Vmem access, no sorter, no output spikes): it is a weight
   address generator plus a cycle counter. All compute counts are therefore
   DERIVED: and for SpinalFlow they are exactly derivable from the capture
   tensors, with no simulation.

## 2. Analytic count model (per capture, layer, sample)

Define, from the layer's input spike tensor over T timesteps:

```
S_win = sum over (output pixel, t) of nonzero spikes in its KHxKW x CIN
        receptive window
      = sum over spikes of (number of output pixels whose window contains
        that spike)                        # ones-kernel convolution
A     = S_win * COUT_total                 # total accumulates, all nodes
R     = A / cout_n                         # weight-read bursts (records)
O     = d_out * HO * WO * COUT * T         # output spike writes, scaled by
                                           # the output sparsity rate d_out
                                           # = density of the NEXT layer's
                                           # input capture (same spike
                                           # stream modulo pooling; final
                                           # layer: own input density as
                                           # proxy; footnote). User
                                           # decision 2026-11-12, replaces
                                           # the dense bound
L     = HO * WO * COUT * T                 # leak ops (added 2026-11-12:
                                           # benchmark scan says LIF, so one
                                           # shift-leak per neuron-timestep;
                                           # shift is wiring, cost is one
                                           # register RMW, lif_unit.md)
```

Notes: the model re-fetches the same (kh,kw,cin) at every timestep it fires
(no time collapsing), which the sum over T in S_win reproduces. Padded
positions are skipped. Cross-check available against
`docs/weight_trace_gen_archs.md` §8 spike-count checks and a handful of
replayed WCTS samples.

## 3. Node components and per-event energies (7 nm)

| # | Component | Geometry (campaign) | Energy source | Count |
|---|-----------|--------------------|---------------|-------|
| 1 | Accumulator adder, per lane | 32-bit add (8-bit weight into BW_VMEM=32 potential) | ASAP7 CSV; synthesize via auto_syn_pnr if absent | A |
| 2 | Threshold comparator, per lane | 32-bit compare | ASAP7 / auto_syn_pnr | A |
| 3 | Membrane-potential register, per lane | 32-bit register (potential stays in-lane: tile holds one output pixel, full window, all T resident; schedule never spills potentials to vmem) | ASAP7 register CSV | register RMW per accumulate: A |
| 4 | L1 weight scratchpad (spad design) | 32 KB, burst cout_n x 1 B | cacti_fn sram, tech 7 | R bursts |
| 5 | Input spine FIFOs (sorted spike lists, consumed head-first; heads feed the row-7 min-tree) | ~1 KB total, sequential access | cacti_fn sram, tech 7 (tech-mapping rule 2026-11-12: KB-scale on-chip storage is sram under cacti_fn; the earlier TSMC fifo CSV was neither ASAP7 logic nor cacti_fn and is reverted; FIFO pointer logic is negligible ASAP7 registers) | R reads + R writes |
| 6 | Output spine FIFO (appends already time-sorted, no output sorter) | ~1 KB, sequential | cacti_fn sram, tech 7 (same rule) | O writes (next layer's reads counted on its own input side) |
| 7 | Sorted-spike merge (min-tree of comparators) | 4-way min-tree (user decision 2026-11-12) | ASAP7 comparators | R compares |
| 8 | psum/vmem NoC/GB movement | NONE. The schedule JSONs' temporal_traffic/spatial_cost are solver score proxies, not access counts; nocsim decodes all four psum/vmem "free" flags True for all 749 schedules (incl. the two sdt_2_512 x2 layers) and emits zero psum/vmem GB/DRAM transactions (prosperity_base.md §2). Potentials are register-resident (row 3); results leave as output spikes (row 6) | - | 0 |
| 9 | Control/sequencer | negligible | excluded, footnote | - |

Rows 1-3 are the compute energy: the potential is register-resident (paper-
faithful; the SpinalFlow mapspace keeps T untiled, so the schedule never
spills potentials to vmem and tc.csv vmem traffic is ~0). Rows 4-6 are
node-local memory events. Row 7 is included per the user's decision.

## 4. Inner-node compute energy formula

```
E_compute(layer, sample) =
    A * (e_add32 + e_cmp32 + e_reg32_rmw)   # lanes, register-resident Vmem
  + L * e_reg32_rmw                    # timestep-boundary shift-leak
                                       #   (LIF resolved 2026-11-12)
  + R * e_l1w_rd(burst)                # spad design only; cache design
                                       #   takes weight-side energy from
                                       #   cachesim counters instead
  + R * (e_fifo_w + e_fifo_r + e_merge)  # input spine FIFO push+pop + min-tree
  + O * e_fifo_w                         # output spine FIFO push
E_leak = P_leak(node) * 16 nodes * T_layer / f
```

psum/vmem add no NoC/GB terms (row 8): tc.csv carries
weight-tensor movement only.

T_layer (delay) stays what the performance sims say: nocsim total_cycles
(spad) / cachesim total_cycles (cache). Compute terms 1-3 and 5-7 are
identical for both designs.

## 5. archx workflow (SpinalFlow slice of T60)

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/spinalflow.architecture.yaml`: modules per the
   table above at `technology: 7` (cacti_fn for SRAMs; ASAP7 for all
   compute logic; any missing compute row synthesized with
   https://github.com/UnaryLab/auto_syn_pnr and added as a CSV row).
   RTL source (2026-11-12): https://github.com/UnaryLab/verilog_modules
   (cloned at /u/yyu9/projects/verilog_modules) provides parameterized
   adder.v and register.v: synthesize at BITWIDTH 32 under ASAP7 to
   replace the current tnn_adder/tnn_reg CSV rows, and retire the
   technology-45 comparator placeholders behind cmp32/min_tree4 by
   writing those two RTL blocks in the same repo style (note:
   verilog_modules/less_equal is a TNN temporal operator, NOT a
   magnitude comparator; cmp32 needs its own trivial module).
2. One archx run with a stub event/workload to populate the graph, then
   query per-access dynamic energy, leakage, area per module
   (`query_module_metric`), writing rows `spinalflow.<module>.<op>` into
   `../archx/zoo/snn_edp/energy_table.json`.
3. Counts script `zoo/fig12_edp/counts/spinalflow_counts.py`: computes
   S_win, A, R, O per (capture, layer, sample) directly from the captures
   at `/work/nvme/bebv/yyu9/input_trace_delta/` (ones-kernel window sum over
   T). Runs on Delta; no Stokes contact; threads capped (login-node PID cap),
   bulk runs via Delta Slurm.
4. Validation: (a) replay a few WCTS samples and check record counts match R
   and spike sums match S_win; (b) compare per-op energy against the
   SpinalFlow paper's published numbers (sanity, not calibration).

## 6. Model settings

1. Merge/sorter: INCLUDE, 4-way min-tree (user).
2. Output-spike count O: d_out * HO*WO*COUT*T with d_out = the next layer's
   input-capture density (same spike stream modulo pooling; final layer
   uses its own input density as proxy; footnote). Applied to SpinalFlow
   O, PTB O, LoAS W_o, GustavSNN W_o.
3. Adder/comparator/register width: 32-bit (BW_VMEM = 32), pending user
   override to a narrower paper-style accumulator.
