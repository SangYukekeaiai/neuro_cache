# Survey: Cache-vs-Scratchpad and Locality/Reuse Profiling for DNN/SNN Accelerators
Date: 2026-07-18 | Papers in DB: 79

## Themes (families kept visible: ARCH = computer-architecture, SYS/CMP = systems/compiler, ML-HW = ML-accelerator, SNN = spiking)

### Theme A — Reuse-distance / stack-distance profiling methodology (SYS/CMP, the profiling core)
The measurement machinery the user needs. Origins in [Mattson et al., 1970](https://doi.org/10.1147/sj.92.0078)
(stack/LRU distance, one-pass all-cache-sizes miss curve) and made scalable by
[Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159) (approximate reuse-distance,
near-linear). Follow-ons: per-instruction miss-rate prediction (2004), locality
approximation using time (2007), whole-program locality (Zhong et al., 2009), and the
multicore variants (multicore-aware RD 2010; "Is reuse distance applicable on CMPs?" 2010).
Applied to a real parallel HW cache in [Nugteren et al., 2014 (GPU cache model)](https://doi.org/10.1109/hpca.2014.6835955)
and multi-level extension "Fast/Accurate Multi-level Caches via Hierarchical RD" (2017).

### Theme B — Analytical reuse models tied to the loop-nest / tiling (ML-HW + SYS)
Reuse quantified from the schedule, not a trace: MAESTRO/[Understanding Reuse (2019)](https://doi.org/10.1145/3352460.3358252),
[Timeloop, 2019](https://doi.org/10.1109/ispass.2019.00042), [Interstellar, 2020](https://doi.org/10.1145/3373376.3378514),
[Marvel, 2021](https://doi.org/10.1145/3485137), [ZigZag, 2021](https://doi.org/10.1109/tc.2021.3059962),
[CoSA, 2021](https://doi.org/10.1109/isca52012.2021.00050) (the user's own scheduler family),
[Accelergy, 2019](https://doi.org/10.1109/iccad45719.2019.8942149), DOSA (2023), TeAAL (2023),
FactorFlow (2025). Classic compiler roots: [Wolf & Lam, 1991](https://www.semanticscholar.org/paper/f4dff66ba8f2338d118f379f2eff1410feb57ce6),
[analytical cache model for affine programs, 2017](https://doi.org/10.1145/3158120), loop-tiling papers.

### Theme C — Scratchpad vs. hardware-managed cache (ARCH/embedded)
The decision the user faces: [Banakar et al., 2003](https://doi.org/10.1109/codes.2002.1003604)
(scratchpad = less area/energy, deterministic, but needs SW management), cache-aware
scratchpad allocation (2004), memory coloring (2005), and DNN-context scratchpad management
[Pin or Fuse?, 2023](https://doi.org/10.1145/3579990.3580017), TelaMalloc (2022),
[Buffets, 2019](https://doi.org/10.1145/3297858.3304025) (the decoupled explicit-buffer idiom).

### Theme D — Reuse-aware replacement / prefetch policy (ARCH)
How locality data justifies a policy: [Belady, 1966](https://doi.org/10.1147/sj.52.0078) (MIN/optimal),
[Hawkeye / Back-to-the-Future, 2016](https://doi.org/10.1109/isca.2016.17) (learn Belady),
[Dynamic Reuse Distances, 2012](https://www.semanticscholar.org/paper/bb0ecaa562f8af82a895fa70409e5982e6d22907),
reuse-distance-prediction replacement (2007), Leeway dead-block prediction (2017).

### Theme E — SNN accelerator memory hierarchies (SNN)
The target domain: SNN ping-pong sparse accelerator (2023), 2048-neuron SNN accelerator with
pruning (2019), Spiker FPGA SNN (2022), FPGA spiking-attention (2025), plus neuromorphic
surveys (2022) and infrastructure (SpikingJelly 2023, BrainCog 2023).

## Venue / family distribution
- ML-accelerator / dataflow: ~24   - Systems/compiler/reuse-distance: ~20
- Computer-architecture core (ISCA/MICRO/HPCA/ASPLOS): ~12   - SNN/neuromorphic: ~9
- FPGA/embedded + surveys: ~14   - Preprints (arXiv, unpublished): ~4

## Year distribution
1966-1999: 4 (roots); 2000-2009: 10; 2010-2014: 10; 2015-2019: 20; 2020-2025: 35.
Key groups: Ding/Zhong (reuse distance), Krishna/Kwon (MAESTRO), Parashar/Emer (Timeloop/Buffets),
Lin/Jain (Belady learning), Genc/Shao (CoSA/Gemmini), Corporaal/ZigZag.

## Initial observations
1. The profiling methodology the user needs is mature but lives in the CPU/GPU/compiler world
   (Themes A/D); the accelerator world (Theme B) mostly uses *analytical* reuse from the loop nest
   instead of *trace-driven* reuse distance. Bridging the two is the opportunity.
2. Almost every accelerator here uses an explicit scratchpad; hardware caches at the PE/node level
   are rare and deliberately avoided (Banakar rationale) — so the user's cache idea is contrarian and
   must be justified with locality data.
3. Within-tile vs across-tile reuse (the user's two regimes) maps cleanly onto MAESTRO's
   temporal/spatial reuse directions and onto short- vs long- reuse-distance modes in a RD histogram.