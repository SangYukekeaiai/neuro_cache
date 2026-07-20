---
aliases: [GPU reuse distance cache model, parallel reuse distance, Nugteren cache model]
topics: [reuse-distance, cache-modeling, parallel-accelerator, profiling-methodology]
author: Nugteren, van den Braak, Corporaal, Bal
venue: HPCA
year: 2014
status: pass-2
bibkey: nugteren2014detailed
gist: Extends reuse-distance theory to a real parallel HW cache (GPU L1), modeling warps, associativity, MSHRs, divergence.
---

# A Detailed GPU Cache Model Based on Reuse Distance Theory (Nugteren et al., 2014)

- **problem**: Classic reuse distance assumes a single sequential reference stream; a GPU cache is shared by many concurrently interleaved threads/warps, so plain stack distance mispredicts its miss rate.
- **challenge**: Model a hardware-managed cache accessed by parallel PEs from an address trace, capturing associativity, line size, MSHRs, and warp divergence.
- **current SoTA (then)**: Cycle-accurate GPGPU-Sim (slow) or naive single-thread reuse distance (inaccurate for parallel caches).
- **novelty**: A reuse-distance model that accounts for the GPU thread hierarchy (threads -> warps -> threadblocks -> the set of concurrently active threads) so that intervening accesses from OTHER parallel execution contexts are included in each reference's reuse distance; adds associativity, cache-line granularity, miss-status-holding-registers (MSHRs), non-uniform latencies, and conditional/divergent accesses.
- **proposal**: Interleave the per-thread memory traces according to the active-thread scheduling model, compute reuse-distance histograms on the merged stream at cache-line granularity, then translate the histogram into hit/miss rate for the modeled associativity.
- **evaluation**: Validated against real GPU hardware performance counters and against GPGPU-Sim across many kernels; reports close agreement with measured cache behavior at a small fraction of simulation cost (analytical model vs cycle-accurate sim).
  - Table row: `2014 | profiling-method | GPU kernels/traces | cache hit-rate vs HW | high agreement, ~orders faster than sim | assoc/MSHR modeled | github (cnugteren)`
- **assumptions**: A representative active-thread interleaving; line-granular addressing; steady-state scheduling.
- **limitation**: Interleaving is a model, not the exact runtime order; depends on the assumed thread-scheduling; single kernel at a time.
- **impact**: Shows reuse-distance profiling generalizes from CPUs to a parallel accelerator cache - the exact bridge the user needs for a many-PE node cache.
- **risks**: If the accelerator's real PE interleaving differs from the modeled one, the histogram (and predicted miss rate) shifts.
- **related work**: Builds on [Mattson 1970](https://doi.org/10.1147/sj.92.0078)/[Ding & Zhong 2003](https://doi.org/10.1145/781158.781159); extended by "Efficient Cache Performance Modeling in GPUs" (TACO 2019).
- **my take**: This is the closest published template for snn_cosa: treat each PE's weight-address stream, interleave per the NoC schedule, compute reuse distance at cache-line granularity, model set-associativity + MSHRs. It legitimizes a trace-driven node-cache study.
- **relevance**: HIGH - method transfers directly to a node-level cache shared by 1024 PEs.
- **future work**: Multi-level parallel reuse distance; write traffic / coherence.
- **triage**: Pass-2 (PDF binary-corrupted on fetch; grounded on VU/hgpu abstracts + known method).
- **terms**: parallel reuse distance, active-thread interleaving, MSHR, associativity model, warp divergence.
- **citation**: [Nugteren et al., 2014](https://doi.org/10.1109/hpca.2014.6835955)
- **code**: reuse-distance GPU model released by the authors (cnugteren.github.io).
- **refs**: Mattson 1970; Ding & Zhong 2003.
- **obsidian links**: [[reuse-distance]], [[parallel-accelerator]]
