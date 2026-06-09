# Phase 1 — Frontier: DNN NoC Simulator Local Buffer Sizes

**Topic:** On-chip local buffer sizes (input, weight, output/partial-sum) in DNN accelerator simulators
and physical chips, 2014–2025.

**Why this matters:** Every DNN NoC simulator (SCALE-Sim, Timeloop, MAESTRO, ZigZag, Gemmini, CoSA)
must specify the per-PE scratchpad breakdown and the global shared buffer. The sizes directly
determine how much data reuse is possible before hitting DRAM, and they dominate area and energy
budgets. Knowing the community-wide range informs realistic simulation setups.

## Trending Directions (2022–2025)

1. **Multi-level scratchpad hierarchies** — post-Eyeriss designs add L0/L1/L2 tiers
   (e.g., Ascend 910: L0A 32KB + L0B 32KB + L0C 256KB + L1 1MB + L2 32MB per AI core).
2. **Simulation-oriented "reference" architectures** — Timeloop/Accelergy, ZigZag, and CoSA
   ship canonical Eyeriss-like or weight-stationary reference configs; these configs
   are becoming the community's shared benchmark geometry.
3. **Smaller per-PE buffers, larger global buffers** — recent chips trading deeper hierarchies
   for larger globally-shared SRAM (Gemmini: 256KB shared scratchpad vs. 64B per PE).
4. **Compiler-driven buffer assignment** — ZigZag/Interstellar treat buffer sizes as design
   variables optimized by the mapper rather than fixed hardware constants.
5. **Chiplet NoC integrations** — Simba (MICRO 2019) and successors expose multi-chip scratchpad
   hierarchies with packet-switched NoC between chiplets.

## Key Papers Found (Phase 1 — ≥10 required)

1. Eyeriss (Chen et al., JSSC 2017) — canonical reference
2. Eyeriss v2 (Chen et al., JETCAS 2019)
3. DianNao (Chen et al., ASPLOS 2014)
4. DaDianNao (Chen et al., MICRO 2014)
5. ShiDianNao (Du et al., ISCA 2015)
6. TPU v1 (Jouppi et al., ISCA 2017)
7. EIE (Han et al., ISCA 2016)
8. SCNN (Parashar et al., ISCA 2017)
9. TETRIS (Gao et al., ASPLOS 2017)
10. MAERI (Kwon et al., ASPLOS 2018)
11. Timeloop (Parashar et al., ISPASS 2019)
12. SCALE-Sim (Samajdar et al., arXiv 2019)
13. MAESTRO (Kwon et al., IEEE Micro 2020)
14. Simba (Shao et al., MICRO 2019)
15. Gemmini (Genc et al., DAC 2021)
16. CoSA (Huang et al., ISCA 2021)
17. ZigZag (Mei et al., IEEE TC 2021)
18. Ascend 910 (Liao et al., HPCA 2021)
19. SIGMA (Hegde et al., HPCA 2020)
20. Interstellar (Yang et al., ASPLOS 2020)
