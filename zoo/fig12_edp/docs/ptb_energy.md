# PTB node energy plan (Fig 12, 7 nm)

Status: for user review. Parent plan: `docs/plans/2026-11-11-fig12-edp-plan.md`.
Sources: PTB paper; lays model `src/lays/weight_trace_gen/ptb/PTBGen.h`;
`zoo/wt500_fig3cfg/walkthroughs/ptb.md`; `docs/weight_trace_gen_archs.md` §8;
`zoo/wt500_fig3cfg/CAVEATS.md` B1-B6; campaign `zoo/wt500_fig3cfg/arch.yaml`
(BW_WEIGHT 8, BW_PSUM 16, BW_VMEM 32).

## 1. How PTB differs from SpinalFlow in this campaign

1. **Fetch once per line, not per spike.** A "line" is one (kh, kw, cin).
   Pass 1 keeps a line if it spikes at ANY t in the tile's T range; each
   survivor triggers exactly one weight burst (cout_n x 1 B)
   (PTBGen.h:89-124, :147-158). SpinalFlow refetches per (t, spike).
2. **Systolic time-batched array.** Published node: 16 rows (output
   channels) x 8 columns (8 consecutive timesteps each, TW 64). A weight
   line broadcasts through the array; each column accumulates it into its
   8 time-slot potentials where the spike bit is 1. Campaign shrink: COUT
   spatial 4 -> at most 4 rows active (2 when COUT=10, e.g. B09
   classifier); captures have T <= 32 -> at most 4 of 8 columns active
   (CAVEATS B1).
3. **Potentials are 16-bit psum** (psum footprint = 2 B x COUT_spatial x T,
   CAVEATS ptb section; BW_PSUM 16), unlike SpinalFlow's 32-bit vmem
   convention.
4. **mac_cycles is latency-only** here too: max(access, compute) with
   pipeline fill/drain terms (PTBGen.h:72-81, :160-162), and the Pass-2
   merge count `ln` enters only that formula. Energy needs none of it:
   all energy counts are analytic from the captures; `ln` is NOT needed
   for energy (it compresses cycles, not operations).
5. **Schedules verified (2026-11-12, all 98 PTB schedule JSONs):**
   temporal_traffic psum = vmem = 0 everywhere (no exception layers);
   spatial_cost ~16/layer = one distribute/collect per tile, counted from
   tc.csv, same as SpinalFlow row 8. Weight temporal_traffic is large
   (DRAM-level COUT/WO blocking refetch) and is already counted by
   cachesim/nocsim on the weight side.

## 2. Analytic count model (per capture, layer, sample)

From the input spike tensor [T, CIN, Hin, Win], padding (k-1)/2, no stride:

```
S_or(pixel)  = sum over (kh,kw,cin) of [ any_t spike in window ]
               # ones-kernel conv of the OR-over-T collapsed tensor
S_sum(pixel) = sum over (kh,kw,cin,t) of spike in window
               # same S_win as SpinalFlow (sum over T)
B = sum_pixels S_or x (COUT_total / cout_n)   # weight bursts, all nodes
    (weight bytes = sum_pixels S_or x COUT_total x 1 B)
A = sum_pixels S_sum x COUT_total             # accumulates
L = HO x WO x COUT x T                        # LIF/threshold ops
O = d_out x L                                 # output spikes; d_out = next
                                              # layer's input-capture
                                              # density (user 2026-11-12)
```

## 3. Node components and per-event energies (7 nm)

| # | Component | Geometry (campaign) | Energy source | Count |
|---|-----------|--------------------|---------------|-------|
| 1 | Array accumulate unit (add weight into time-slot potential) | 8-bit weight into 16-bit potential register (BW_PSUM) | ASAP7 / auto_syn_pnr | A x (e_add16 + e_reg16_rmw) |
| 2 | L1 weight scratchpad read (spad design) | 32 KB, burst cout_n x 1 B | cacti_fn sram, tech 7 | B bursts |
| 3 | Weight broadcast into array | wire/driver across <=4x4 active units | fold into row 2 or small ASAP7 wire term | B |
| 4 | Spike-vector buffer | T-bit vector per line, ~1 KB SRAM | cacti_fn sram | B reads |
| 5 | LIF/threshold unit | shared 32-bit lif_unit block, 16-bit input (lif_unit.md core stages; potential state lives in the column register file, read separately), per (pixel, cout, t) | ASAP7 / auto_syn_pnr (lif_unit) | L x (e_lif_step_core + e_reg_rd); O x e_outq_wr |
| 6 | Pass-2 merge (time-batch grouping) | T-bit disjointness check (AND-reduce) per adjacent survivor pair | ASAP7 | ~B compares if included (DECISION) |
| 7 | psum/vmem NoC/GB movement | NONE (correction 2026-11-12: solver temporal_traffic/spatial_cost are score proxies; nocsim emits zero psum/vmem transactions for all 749 schedules, prosperity_base.md §2). Potentials are column registers (row 1); results leave as output spikes | - | 0 |
| 8 | Weight-staging FIFO + spike-vector FIFO | between L1 and array, shallow (<= 8 entries) | ASAP7 auto_syn_pnr of verilog_modules/fifo.v (BITWIDTH 16, DEPTH 8); replaces TSMC fifo CSV per tech-mapping rule 2026-11-12 (all compute/staging logic ASAP7) | B pushes + B pops each |
| 9 | Control/sequencer | negligible | excluded, footnote | - |

## 4. Inner-node compute energy formula

```
E_compute(layer, sample) =
    A * (e_add16 + e_reg16_rmw)          # time-slot accumulation
  + B * (e_l1w_rd(burst) + e_svec_rd)    # L1 read spad-design-only;
                                         #   cache design takes weight-side
                                         #   energy from cachesim counters
  + L * (e_lif_step_core + e_reg_rd)     # LIF sweep, shared lif_unit
  + O * e_outq_wr
  + B * e_merge                          # Pass-2 disjointness check (incl.)
  + 2B * (e_fifo_w + e_fifo_r)           # weight + spike-vector FIFOs
E_leak = P_leak(node_physical) * 16 nodes * T_layer / f
```

T_layer from the performance sims, as always.

## 5. archx workflow (PTB slice of T60/T61 pattern)

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/ptb.architecture.yaml` at technology 7: modules
   per the table; reuse spinalflow's adder/comparator/register entries
   where widths match (16-bit variants are new).
2. Harvest per-access energy/leakage/area -> energy_table.json keys ptb.*.
3. Counts script `zoo/fig12_edp/counts/ptb_counts.py`: S_or via OR-collapse
   + ones-kernel conv, S_sum shared with the spinalflow counts code, B/A/L/O
   per (capture, layer, sample). No Pass-2 walk needed.
4. Validation: replay a few PTB WCTS samples: record count must equal
   sum_pixels S_or per node slab (PTB records are record-identical to LoAS,
   ptb.md:17-24); cross-check S_sum against the spinalflow fetch count for
   the same capture.

## 6. Decisions (resolved 2026-11-12, user)

1. **Physical array: 4 rows x 8 columns, window T = 32 (4 timesteps per
   column).** This resolves the repo's open "T: 64 vs 32" review flag
   (ptb.yaml comment, HANDOFF.md) toward 32. No effect on counts (A, B, L
   depend only on each capture's T <= 32); each column's potential register
   file is 4 entries instead of 8 (slightly lower leakage/area).
2. **Pass-2 merge: INCLUDED** as one T-bit disjointness check (AND-reduce)
   per surviving line (~B checks). Common to both designs, so it barely
   moves the spad-vs-cache comparison.
3. **Bit-widths follow OUR design, not the paper**: 16-bit accumulate
   (campaign BW_PSUM = 16); the LIF step is the shared 32-bit lif_unit
   block with 16-bit input (lif_unit.md).
4. FIFOs added (row 8) per user review: weight-staging and spike-vector
   FIFOs, B pushes + B pops each, ASAP7 fifo.v per the tech-mapping rule.
