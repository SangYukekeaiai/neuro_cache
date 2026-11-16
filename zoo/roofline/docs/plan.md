# Roofline plan (RQ3 todo, 08_evaluation.tex:99) - AWAITING BOSS REVIEW, nothing implemented

Target: the `\todo{add roofline model to show where each desgin stays}` in
RQ3 (Scratchpad versus Cache). One figure that places every RQ3 design on a
log-log roofline so the latency/energy wins of fig:eval-spad-cache get a
mechanistic explanation: which designs are DRAM-bandwidth-bound and how far
the cache moves them toward (or onto) the compute roof.

Claim the figure proves: at equal capacity and core count, the scratchpad
designs sit under the bandwidth roof (weight over-fetch lowers their
operational intensity), while the neuromorphic cache raises intensity by
fetching only spike-selected weights, moving the design right and up toward
the compute roof. SpikeX-style tag-gated spad lands between them.

All writes under `zoo/roofline/`, decoupled from every other zoo figure
(own configs, own snapshot of anything borrowed, same law as eval_scaling).

## Axes and roofs (counter-exact definitions)

- Attained performance P = SOP / T_total [synaptic ops per cycle], where
  SOP = spike-gated MACs actually executed (the LoAS skip rule), per
  sample, summed over layers; T_total = nocsim/cachesim makespan cycles.
- Operational intensity OI = SOP / B_dram [SOP per byte], with B_dram =
  the NEW dram_bytes payload counter (4b068a9), summed over layers.
  Payload bytes, pre-packet-quantization, consistent with eval_scaling's
  units decision; caption states it.
- Compute roof = N_nodes x num_pes x 1 MAC/cycle (16 x 4 = 64 SOP/cycle
  at the RQ3 operating point).
- Bandwidth roof = P <= BW x OI with BW = 128 B/cycle (64 GB/s at 500 MHz,
  the arch.yaml DRAM_LATENCY=0.25 convention).
- Per-sample points; mean over the 10 samples with 95% CI whiskers on both
  axes (samples move SOP and B_dram together, so whiskers are small).

SOP source: analytic spike-gated MAC counts from the capture convolutions
(fig12_edp/counts machinery computes fetched records already; SOP is the
same pass summing gated MACs instead of fetched lines). No simulation.

## Design points (RQ3 set, one marker each)

| Point | Perf/cycles source | Bytes source |
|---|---|---|
| multi-node spad (ours, scheduler-optimized) | nocsim (eval_scaling chain) | dram_bytes |
| neuro-cache, each prefetch config x replacement policy (RQ3 grid) | cachesim cache arm | its dram byte counter (verify same units) |
| optional ceiling: Belady cache (RQ4 upper bound) | cachesim, replacement=belady | same |

CORRECTION (boss, 2026-11-16): the earlier "spad + SpikeX tag-gating"
row was wrong - cachesim's spad_wcache arm is only a row LABEL for which
trace feeds a spad run (cli_args.h:54), not a tag-gating model. No SpikeX
implementation exists. Options (boss call, new Q6):
  a. drop the point - the claim stands on spad vs cache vs Belady;
  b. analytic-OI-only marker: bytes = unique spike-touched weight rows
     per tile residency (counts pass can emit this), P from a stated
     optimistic model, hollow marker + caption caveat;
  c. implement tag-gating in nocsim - real impl work for one marker,
     not recommended.

Workload: loas_vgg16, samples 000-009, 13 layers, aggregated
whole-model (sum SOP, sum bytes, sum cycles - never mean of ratios).
One roofline panel; a faint per-layer point cloud behind the aggregate
markers if it reads clearly, else aggregate only.

## Execution chain

1. S0: configs snapshot - RQ3 operating point (OPEN: boss must fix
   capacity + core count, same TODO as fig:eval-spad-cache), design grid
   list, SOP-counter provenance.
2. S1: SOP counts per (layer, sample) - counts pass on Delta login,
   minutes, no sim.
3. S2: cycles + dram_bytes per design point - REUSE: the eval_scaling
   re-run already yields the multi-node spad point at x1; cachesim arms
   run on Stokes for the cache/SpikeX grid (sim_shard machinery).
4. S3: join + aggregate -> roofline.csv (point, OI, P, CIs).
5. S4: plot.py - log-log, two roofs, labeled points, distance-to-roof
   annotations for the headline designs.
6. Gates: boss fixes the operating point and approves a mock before any
   Stokes submission; Archie reviews every impl commit (team protocol);
   figure sign-off before paper integration.

## Open questions for boss

- Q1: operating point - propose 16 nodes x 4 PEs, total weight storage
  1 MB (the eval_scaling x1 point), so the roofline reuses the
  eval_scaling multi_x1 runs unchanged. Confirm or set another.
- Q2: SOP definition - spike-gated MACs (effective work, standard for
  sparse accelerators) vs dense MACs (would move every design left by the
  same factor and not change ordering). Propose spike-gated.
- Q3: which cache configs get markers - full prefetch x replacement grid
  (cluttered) or best-per-prefetch-class (3-4 markers)? Propose the
  latter, grid in an appendix CSV.
- Q4: include the Belady ceiling point? Cheap if RQ4 runs anyway.
- Q5: figure placement - inside fig:eval-spad-cache as a panel, or its
  own single-column figure? Propose own figure after fig:eval-spad-cache.
