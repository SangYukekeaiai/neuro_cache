# LoAS node energy plan (Fig 12, 7 nm)

Status: for user review. Parent plan: `docs/plans/2026-11-11-fig12-edp-plan.md`.
Sources: LoAS paper (MICRO 2024, fully temporal-parallel dual-sparse SNN
accelerator); lays model `src/lays/weight_trace_gen/loas/LoASGen.h`;
`zoo/wt500_fig3cfg/walkthroughs/loas.md`; `docs/weight_trace_gen_archs.md`;
CAVEATS.md L1-L10; campaign `zoo/wt500_fig3cfg/arch.yaml` (BW_WEIGHT 8,
BW_PSUM 16, BW_VMEM 32). Scope: scratchpad/node side only; the cache design
is a deferred independent step (user, 2026-11-12).

## 1. Node picture (user's understanding checked)

1. **COUT = 4 TPPEs per node: confirmed.** "One TPPE handles each spatial
   output channel" (examples/node_mapspace/loas.yaml:3); the published
   single-node config has 16 TPPEs, the campaign mapspace pins COUT
   {spatial: 4} -> 4 TPPEs (2 when COUT=10, divisor rule as usual). KH, KW,
   CIN and T are all fully resident per node. (Stale docstring saying
   "COUT capacity 16" at src/lays/weight_trace_gen/loas/__init__.py:12;
   both mapspace YAMLs say 4.)
2. **FTP dataflow**: each TPPE processes ALL T timesteps of a line in
   parallel: one weight broadcast per surviving line; the line's T-bit
   spike word gates adds of that weight into T parallel 16-bit psum lanes.
   After the accumulate phase, a LIF unit scans the T psum lanes
   sequentially (cumulative potential, threshold, reset, output spike bit).
3. **Repo model is fetch-only**: mac_cycles = survivor count exactly
   (LoASGen.h:83-93), no pipeline terms, no LIF anywhere. The record
   stream is record-identical to PTB's (same Pass-1 any-fire skip), so all
   LoAS compute/LIF energy is analytic, from the same capture convolutions.
4. **Dense weights**: the repo explicitly departs from the paper's dual
   sparsity (dense 8-bit weights, no bitmask/pointer metadata,
   loas/__init__.py:14-18). The energy model follows: no compressed-weight
   or intersection-unit energy, footnoted in the paper.
5. **Schedules verified (2026-11-12, all 221 LoAS schedule JSONs)**:
   temporal_traffic psum = vmem = 0 everywhere; one distribute/collect per
   tile, counted from tc.csv (same as PTB/SpinalFlow).
6. **Latency caveat (energy-neutral)**: mac_cycles excludes the LIF phase,
   so LoAS delay from the sims assumes LIF is hidden under fetch. Energy
   counts it explicitly; the delay stays the sims' number, footnoted.

## 2. Analytic count model (per capture, layer, sample)

Identical convolution core as PTB (`ptb_counts` shares it):

```
S_or, S_sum        as in ptb_energy.md §2
B  = sum_pixels S_or x (COUT_total / cout_n)   # weight bursts = records
A  = sum_pixels S_sum x COUT_total             # gated accumulates
L  = HO x WO x COUT x T                        # LIF scan steps
W_o = d_out x HO x WO x COUT                           # output spike words (T-bit)
```

Validation: per-node record count must equal sum_pixels S_or (streams are
record-identical to PTB; cross-checks in docs/weight_trace_gen_archs.md §8).

## 3. Node components and per-event energies (7 nm)

| # | Component | Geometry (campaign) | Energy source | Count |
|---|-----------|--------------------|---------------|-------|
| 1 | TPPE gated accumulate lanes | 8-bit weight into 16-bit psum lane registers (BW_PSUM); adds gated by spike bits, idle lanes gated off | ASAP7 / auto_syn_pnr | A x (e_add16 + e_reg16_rmw) |
| 2 | L1 weight scratchpad read (spad design) | 32 KB, burst cout_n x 1 B | cacti_fn sram, tech 7 | B bursts |
| 3 | Weight-staging FIFO | between L1 and TPPEs, shallow (<= 8 entries) | ASAP7 auto_syn_pnr of verilog_modules/fifo.v (BITWIDTH 16, DEPTH 8); replaces TSMC fifo CSV per tech-mapping rule 2026-11-12 | B pushes + B pops |
| 4 | Spike-word FIFO | T-bit word per surviving line, shallow | ASAP7 fifo.v (BITWIDTH 32, DEPTH 8), same rule | B pushes + B pops |
| 5 | LIF unit, per TPPE | sequential scan over T; full digital decomposition in docs/lif_unit.md (leak/integrate/threshold/reset/state), synthesized as one auto_syn_pnr RTL block | ASAP7 / auto_syn_pnr (lif_unit) | L x (e_reg16_rd + e_lif_step) |
| 6 | Output spike-word FIFO | one T-bit word per (pixel, cout), shallow | ASAP7 fifo.v (BITWIDTH 32, DEPTH 8), same rule | W_o pushes |
| 7 | psum/vmem NoC/GB movement | NONE (correction 2026-11-12: solver temporal_traffic/spatial_cost are score proxies; nocsim emits zero psum/vmem transactions for all 749 schedules, prosperity_base.md §2). Potentials are TPPE lane registers (row 1) + LIF state (row 5) | - | 0 |
| 8 | Dual-sparsity structures (weight bitmasks, intersection unit) | NOT modeled: campaign weights are dense, matching the repo's explicit departure | excluded, footnote | - |
| 9 | Control/sequencer | negligible | excluded, footnote | - |

No sorter/min-tree (LoAS is unsorted) and no Pass-2 merge (no systolic
pipeline): structurally the simplest of the three archs so far.

## 4. Inner-node compute energy formula

```
E_compute(layer, sample) =
    A  * (e_add16 + e_reg16_rmw)                      # FTP accumulate
  + (A/cout_n) * e_bsf32 + B * (e_pscan32 + 32*e_and) # FTP scan (3.1)
  + B  * e_l1w_rd(burst)                              # spad design only
  + 2B * (e_fifo_w + e_fifo_r)                        # weight + spike-word FIFOs
  + L  * (e_reg16_rd + e_lif_step)   # LIF scan; e_lif_step = the ONE
                                     #   shared lif_unit block
                                     #   (lif_unit.md), not a primitive
                                     #   expansion
  + W_o * e_fifo_w                                    # output spike words
E_leak = P_leak(node_physical) * 16 nodes * T_layer / f
```

## 5. archx workflow (LoAS slice)

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/loas.architecture.yaml` at technology 7: reuses
   the 16-bit adder/register entries from PTB, the 32-bit
   adder/comparator/register entries from SpinalFlow, and the shared
   ASAP7-synthesized fifo block (verilog_modules/fifo.v); nothing
   arch-new to synthesize beyond the shared lif_unit.
2. Harvest -> energy_table.json keys loas.*.
3. `loas_counts.py`: thin wrapper over the shared convolution core
   (S_or/S_sum identical to PTB); adds L and W_o.
4. Validation: record-count equality against replayed WCTS samples (same
   check as PTB).

## 3.1 TPPE FTP front-end decomposed into primitives (user, 2026-11-12)

The user is right that the fully-temporal-parallel PE carries scan logic
beyond the gated adders. Per surviving line (record, count B), the TPPE
consumes a T-bit spike word with:

| Block | Primitive inventory | Per-event composition |
|---|---|---|
| Priority encoder `bsf32` | 32-bit leading-one scan + clear mask (bsf16 doubled: one extra mux/OR level) | e_bsf32 per set-bit step; bounded by B x mean popcount = A/cout_n steps total, so charge A/cout_n x e_bsf32 |
| Prefix-sum `psum_scan32` | 5-level parallel-prefix popcount over 32 bits, ~80 FA-equivalents (positions for compacted psum update) | e_pscan32 x B (once per word) |
| Word AND-join | 32 AND gates (spike word & weight-valid mask); degenerate with dense weights but physically present | 32 x e_and x B |

Synthesis: one composite `tppe_scan` block (bsf32 + psum_scan32 + AND
row) in verilog_modules style, added to the ASAP7 worklist; primitives
above give the placeholder sum until synthesized. Effort note: doc +
worklist + placeholder rows only, no new sims or counts (all counts are
B and A already in §2): LOW, done here.

Formula addition to §4: `+ (A/cout_n) * e_bsf32 + B * (e_pscan32 + 32*e_and)`.

## 6. Decisions (resolved 2026-11-12, user)

1. RESOLVED: 32 physical psum lanes per TPPE (T=32 coverage; T=4 layers
   idle 28 lanes, charged as leakage).
2. RESOLVED (user 2026-11-12): psum lanes 16-bit, running potential
   32-bit (BW_PSUM/BW_VMEM).
3. RESOLVED (user 2026-11-12): dual sparsity excluded, footnote (campaign
   weights dense end-to-end).
4. FTP scan logic added as §3.1 (priority encoder + prefix-sum + AND
   join); accepted with the dispatch 2026-11-12.
