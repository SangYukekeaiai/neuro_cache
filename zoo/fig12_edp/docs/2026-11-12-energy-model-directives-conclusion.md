# Conclusion: energy-model directives of 2026-11-12 (temporary note)

Supervisor request, four parts, all executed. Permanent homes of each
result are listed per item; this file is a disposable summary.

## 1. Neuron model: scanned all 8 benchmarks, applied the majority

Scan of the actual model sources AND the LoAS checkpoint pickles
(bench repo + upstream/{STEP, LoAS, SpikingLM, SMA-AZO}, spikingjelly and
braincog defaults verified). Result is unanimous, 8 of 8:

- **LIF** (no benchmark uses IF)
- **Multiplicative leak** v[t] = lambda*v[t-1] + x[t]/tau, lambda = 1-1/tau:
  - tau = 2.0 -> lambda = 0.5: spikformer, sdt, spikinglm, both sma_azo
  - tau = 4/3 -> lambda = 0.25: vgg16_cifar10_loas_T32, loas_resnet19,
    loas_vgg16
- **Hard reset to 0** (v_reset = 0.0 everywhere; no soft reset)
- Thresholds 1.0 (0.5 on transformer attention neurons): constants only.

Hardware consequence: both lambdas are exact powers of two, so the leak is
a pure arithmetic shift (k in {1,2}); no multiplier, no subtractor. Hard
reset is a mux to 0. The x/tau input scale is folded into weights offline
(footnote in methodology). Applied to ALL five arch energy models; this
unblocks every arch dispatch. GustavSNN's paper used soft reset: overridden
by the majority rule, footnoted. SpinalFlow gains a leak term
(L = HO*WO*COUT*T register RMWs) it did not have.
Home: zoo/fig12_edp/docs/lif_unit.md (resolution + unit spec).

## 2. RTL repo pulled: github.com/UnaryLab/verilog_modules

Cloned at /u/yyu9/projects/verilog_modules. Parameterized, auto_syn_pnr
ready (each module has rtl_list.tcl):
- Usable as-is: adder (BITWIDTH), multiplier, register (WL),
  fifo (BITWIDTH, DEPTH), and_gate; plus butterfly/systolic/TNN blocks we
  do not need.
- Caution: less_equal is a TNN *temporal* operator, NOT a magnitude
  comparator; cmp32 still needs its own trivial module.
- Still to write (same repo style, ASAP7): cmp32, min_tree4 (SpinalFlow),
  merger_tree4 + l1d (GustavSNN), lif_unit (shared), tcam_256x16,
  popcount16, pruner, bitonic_cmp, bsf16 (Prosperity).
Home: parent plan, section "Tech-mapping rule + RTL sources".

## 3. Tech-mapping audit (compute=ASAP7, sram=cacti_fn, dram=ddr4)

Not everything was correct. Found and fixed in the plans:
- spinalflow cmp32 + min_tree4 used **technology-45** comparator rows ->
  now marked pending-ASAP7-synthesis, no tech-45 energies allowed.
- **TSMC/chiplet_cmos fifo CSV rows violated the rule** in four plans ->
  replaced everywhere: SpinalFlow 1 KB spines -> cacti_fn sram tech 7
  (KB-scale storage is memory); PTB/LoAS/GustavSNN shallow staging FIFOs
  -> ASAP7-synthesized verilog_modules/fifo.v.
- tnn_adder/tnn_reg CSV rows -> replace with ASAP7 synthesis of
  verilog_modules adder/register at the needed widths.
- Already correct: every SRAM is cacti_fn class sram technology 7; DRAM is
  cacti7 ddr4 (22 nm), as planned.
- T67 was mid-flight converting spines TO TSMC fifo: redirected, impl
  reports done, archie review in progress.

## 4. Per-arch plan updates (spinalflow workflow as the template)

All five docs updated: spinalflow (spines back to sram, leak term added,
RTL-source note), ptb (fifo row -> ASAP7 fifo.v), loas (3 fifo rows ->
ASAP7 fifo.v, workflow note), gustavsnn (output buffer -> ASAP7 fifo.v,
reset decision resolved), prosperity (add16/reg16 -> verilog_modules
synthesis, lif decision resolved). Each follows the spinalflow workflow:
architecture.yaml at tech 7 -> harvest -> energy_table.json rows ->
counts script -> validation anchor. Missing hardware = write RTL in
verilog_modules style, synthesize under ASAP7 via auto_syn_pnr.

## Remaining gates (unchanged by this round)

- User decisions: Prosperity 1-5 (slab repetition, SFU confirm, TCAM
  source, seed-load bound, A08 bar), LoAS 3, GustavSNN HO-refetch, PTB
  supervisor sign-off, production cachesim config, AWS rental scheduling.
- auto_syn_pnr synthesis runs are a user/lab-side flow; worklist is in the
  parent plan.
