# GustavSNN node energy plan (Fig 12, 7 nm)

Parent plan: `docs/plans/2026-11-11-fig12-edp-plan.md`.
Sources: GustavSNN paper (Hwang, Lee, Koo, Kung, "GustavSNN: Unleashing the
Power of Gustavson's Algorithm on SNN Acceleration with Column-Parallel
Tick-Batch Dataflow", HPCA 2026, refs.bib:72-80); lays model
`src/lays/weight_trace_gen/gustavsnn/GustavGen.h`;
`zoo/wt500_fig3cfg/walkthroughs/gustavsnn.md`; `docs/weight_trace_gen_archs.md`
§4-5; CAVEATS.md G1-G6; campaign arch.yaml (BW 8/16/32).
Scope: scratchpad/node side only (cache design deferred).

## 1. Node picture (user's understanding checked)

1. **2 COUT x 2 HO lanes per node: confirmed.** mapspaces/gustavsnn.yaml:
   COUT {spatial: 2}, HO {spatial: 2}, WO 1, KH/KW/CIN full, T barred from
   the node. Published design: 64 PEs (8 COUT tiles x 8 HO rows, paper
   Table II / Fig. 17), shrunk to our 2x2 = 4.
2. **Gustavson (row-wise SpMM) dataflow**: per output pixel row, the node
   walks the nonzero (firing) input lines and accumulates each fetched
   weight row into the output psum row: binary spikes mean no multiplier,
   just gated row accumulation. The 2 HO lanes run in lockstep (a wave pays
   its longest lane); the 2-wide COUT slab rides inside each fetch record.
3. **One timestep per tile** (TileSpec has a single t_offset): T is a
   DRAM-level temporal loop, innermost (OOOT mode), so the membrane
   potential for the live pixel/cout group is revisited consecutively
   across t and stays resident in the node between tiles: in the per-PE
   **potential register file** ("Potential REG", paper Fig. 9; see row 4 and decision 2). The
   LIF step costs a register-file RMW; the yaml has no vmem module.
4. **Fetch rule = SpinalFlow's (once per spike), sliced by timestep**, with
   NO dedup across the 2 HO lanes (two lanes can fetch the same address on
   the same tick: real refetch, counted). Records = 2x SpinalFlow by
   construction (slab 2 vs 4), verified in the walkthrough.
5. **Paper-name tension, footnote**: the paper's "tick-batch" batches
   timesteps; the lays model processes one tick per tile (no batching).
   The energy model follows the lays model (one tick per tile), consistent
   with the campaign's traces and cycles.
6. **psum/vmem movement (applies to ALL archs)**: the
   schedule-JSON `temporal_traffic` values (2.0 / 1024.0
   on 37 gustavsnn schedules) are a SOLVER SCORE, not an access count.
   nocsim decodes all four psum/vmem "free" flags True for every one of
   the 749 schedules and therefore emits ZERO psum/vmem GB/DRAM
   transactions (verified in zoo/fig12_edp/docs/prosperity_base.md §2). So psum/vmem buffer energy is counted ANALYTICALLY
   (node-local access counts, below), not from tc.csv; there is no
   temporal psum/vmem spill energy anywhere in the campaign.

## 2. Analytic count model (per capture, layer, sample)

Same convolution core as the other archs:

```
S_pt(pixel,t) = sum over (kh,kw,cin) of spike in window at timestep t
S_win = sum over (pixels,t) of S_pt          # == SpinalFlow's S_win
R_g = S_win x (COUT_total / 2)               # fetch records (2x SpinalFlow)
A   = S_win x COUT_total                     # accumulates (universal A)
L   = HO x WO x COUT x T                     # LIF steps (one per tile visit)
W_o = d_out x HO x WO x COUT x T bits        # output spike bits; d_out =
                                             # output sparsity rate (next
                                             # layer's input-capture
                                             # density; user 2026-11-12)
```

Validation: per-sample record count must equal 2x the SpinalFlow record
count for the same capture (walkthrough gustavsnn.md:309-318); A matches
the universal accumulate total shared by all archs.

## 3. Node components and per-event energies (7 nm)

| # | Component | Geometry (campaign) | Energy source | Count |
|---|-----------|--------------------|---------------|-------|
| 1 | Row-accumulate units (2 HO lanes x 2 couts) | 8-bit weight into 16-bit psum register (BW_PSUM); psum footprint 2-8 B = registers | ASAP7 / auto_syn_pnr | A x (e_add16 + e_reg16_rmw) |
| 2 | L1 weight scratchpad read (spad design) | 32 KB, burst 2 x 1 B (cout_n = 2) | cacti_fn sram, tech 7 | R_g bursts |
| 3 | NRV spike-vector fetch (paper Fig. 9 fetch stage): Skipping Module of leading-one detectors (L-1D) + merger tree + W REG staging. MAPSPACE CHECK 2026-11-12: the paper's NR=4 merger feeds its 8-row node; our node runs 2 HO lanes (mapspace HO {spatial: 2}, GustavGen walks ho_n pieces with no sort hardware), so the matched scaling is **NR=2: a single compare-exchange stage (merger_tree2)**, not NR=4 | fetch-stage logic | ASAP7 via auto_syn_pnr: l1d + merger_tree2 (worklist updated from merger_tree4); placeholder rows (comparator-scaled) until synthesized | R_g x (e_l1d + e_mtree2) + R_g spike-vector reads (fifo) |
| 4 | LIF unit | per docs/lif_unit.md with STATE in the **per-PE potential register file** (paper Fig. 9 "Potential REG", updated at a selected column index) | ASAP7 lif_unit | L x (e_lif_step_core + e_regfile_rmw) |
| 5 | Output spike buffer | 1 bit per (pixel, cout, t), word-packed, shallow staging | ASAP7 auto_syn_pnr of verilog_modules/fifo.v (BITWIDTH 32, DEPTH 8); replaces TSMC fifo CSV per tech-mapping rule 2026-11-12 | W_o pushes (word-packed) |
| 6 | psum/vmem NoC movement | none: psum/vmem never cross GB/DRAM in nocsim (§1.6); outputs leave as spike words | - | 0 |
| 7 | Control/sequencer (wave lockstep) | negligible | excluded, footnote | - |

No sorter (unsorted), no min-tree, no Pass-2 merge, no bitmask/popcount
(those are Prosperity's).

## 4. Inner-node compute energy formula

```
E_compute(layer, sample) =
    A   * (e_add16 + e_reg16_rmw)                 # Gustavson row accumulate
  + R_g * e_l1w_rd(burst2)                        # spad design only
  + R_g * (e_l1d + e_mtree2 + e_fifo_r)           # fetch stage (Fig. 9)
  + L   * (e_lif_step_core + e_regfile_rmw)       # LIF, potential REG file
  + (W_o/32) * e_fifo_w                           # output spikes, packed
                                                  #   32-bit words (W_o is
                                                  #   in bits)
E_leak = P_leak(node_physical: 2x2 lanes + LIF + walker) * 16 * T_layer / f
```

e_lif_step_core = lif_unit.md stages 1-4 (leak/integrate/threshold/reset),
resolved 2026-11-12: shift-leak, hard reset (benchmark scan).

## 5. archx workflow (GustavSNN slice)

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/gustavsnn.architecture.yaml` at technology 7:
   reuses add16/reg16 (PTB), the shared ASAP7 fifo block, cacti_fn vmem
   1 KB and L1 32 KB entries; lif_unit shared block. Arch-new synthesis:
   l1d + merger_tree2 only (row 3).
2. Harvest -> energy_table.json keys gustavsnn.*.
3. `gustavsnn_counts.py`: thin wrapper over the shared convolution core
   (S_win identical to SpinalFlow's; R_g = S_win x COUT/2; adds L, W_o).
4. Validation: record count == 2x SpinalFlow record count per sample.

## 6. Decisions for the user

1. RESOLVED 2026-11-12 (user): the redundant fetch is real; energy counts
   both HO lanes' fetches with no dedup (faithful to the lays model).
   NR=2 merger scaling (row 3) also confirmed 2026-11-12.
2. RESOLVED by the paper (zoo/fig12_edp/ref/gustavsnn_hpca26.pdf, Fig. 9):
   LIF state is a per-PE potential register file ("Potential REG"), not
   vmem SRAM; the schedule's vmem footprint is the capacity accounting for
   it. No popcount exists; the sparsity hardware is the L-1D skipping
   module + NR=4 merger tree (now row 3).
3. RESOLVED 2026-11-12 (benchmark scan, 8/8 unanimous, lif_unit.md): LIF,
   power-of-two shift leak (lambda 0.5 or 0.25), HARD reset to 0. The
   paper's own soft-reset eval (eq. 1) is overridden by the user's
   most-common-setting rule; footnote the difference in the methodology.
