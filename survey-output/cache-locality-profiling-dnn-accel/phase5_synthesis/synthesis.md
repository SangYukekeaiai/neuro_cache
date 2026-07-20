# Synthesis: Cache-vs-Scratchpad and Locality/Reuse Profiling for DNN/SNN Accelerators

## Taxonomy (tree of approaches)

- **1. How reuse/locality is MEASURED**
  - **1a. Trace-driven reuse-distance / stack-distance** (address trace -> histogram -> miss curve)
    - Exact stack distance [(Mattson et al., 1970)](https://doi.org/10.1147/sj.92.0078)
    - Approximate, near-linear [(Ding & Zhong, 2003)](https://doi.org/10.1145/781158.781159); per-instruction miss-rate; whole-program (Zhong et al., 2009)
    - **Parallel/accelerator-aware** [(Nugteren et al., 2014)](https://doi.org/10.1109/hpca.2014.6835955); multicore RD (2010)
  - **1b. Analytical reuse from the loop-nest / tiling** (mapping -> reuse counts, no trace)
    - Reuse decomposition [(Kwon et al., 2019, MAESTRO)](https://doi.org/10.1145/3352460.3358252); per-level accounting [(Parashar et al., 2019, Timeloop)](https://doi.org/10.1109/ispass.2019.00042); [(Interstellar, 2020)](https://doi.org/10.1145/3373376.3378514); [(ZigZag, 2021)](https://doi.org/10.1109/tc.2021.3059962)
    - Closed-form cache-miss counts for affine programs [(analytical cache model, 2017)](https://doi.org/10.1145/3158120); loop-tiling roots [(Wolf & Lam, 1991)](https://www.semanticscholar.org/paper/f4dff66ba8f2338d118f379f2eff1410feb57ce6)
  - **1c. Reuse ENCODED in a scheduler** (reuse as an optimization term)
    - MILP traffic terms [(CoSA, 2021)](https://doi.org/10.1109/isca52012.2021.00050); differentiable [(DOSA, 2023)](https://doi.org/10.1145/3613424.3623797)
- **2. How on-chip memory is ORGANIZED**
  - **2a. Software-managed scratchpad** [(Banakar et al., 2002)](https://doi.org/10.1109/codes.2002.1003604); cache-aware allocation (2004); memory coloring (2005); decoupled [(Buffets, 2019)](https://doi.org/10.1145/3297858.3304025); cross-layer [(Pin or Fuse, 2023)](https://doi.org/10.1145/3579990.3580017)
  - **2b. Hardware-managed cache** (rare at PE/node level) — reuse-distance-aware policies below
  - **2c. Hybrid cache+scratchpad** — Compad (2023); reconfigurable cache/scratchpad partitioning (2017)
- **3. How a cache POLICY is chosen from locality data**
  - Optimal baseline [(Belady, 1966)](https://doi.org/10.1147/sj.52.0078); learned-Belady [(Jain & Lin, 2016)](https://doi.org/10.1109/isca.2016.17); reuse-distance-aware replacement (Dynamic Reuse Distances, 2012; RD-prediction 2007); dead-block/Leeway (2017)

## Comparative table (master)

| Method | Ref | Year | Family | Workload/Dataset | Metric | Result | Key Limitation | Code |
|--------|-----|------|--------|------------------|--------|--------|----------------|------|
| Stack distance (one-pass MRC) | [Mattson et al.](https://doi.org/10.1147/sj.92.0078) | 1970 | profiling | address traces | miss curve vs capacity | exact, all sizes 1 pass | O(N·M), single stream | libCacheSim |
| Approx reuse distance | [Ding & Zhong](https://doi.org/10.1145/781158.781159) | 2003 | profiling | SPEC/sci | RD histogram accuracy | >90%, near-linear | smooth-scaling assumption | PyMimircache |
| Parallel GPU cache RD model | [Nugteren et al.](https://doi.org/10.1109/hpca.2014.6835955) | 2014 | profiling | GPU kernels | cache hit-rate vs HW | high, ~orders faster than sim | modeled interleaving | author repo |
| MAESTRO (data-centric reuse) | [Kwon et al.](https://doi.org/10.1145/3352460.3358252) | 2019 | ML-HW | CONV layers | model error vs RTL | 3.9%, ~1000-4000x faster | affine, ≤2 dims | MAESTRO |
| Timeloop (per-level accounting) | [Parashar et al.](https://doi.org/10.1109/ispass.2019.00042) | 2019 | ML-HW | CONV/GEMM | access counts, energy | matches Eyeriss-class | assumes scratchpad | NVlabs/timeloop |
| CoSA (MILP scheduler) | [Huang et al.](https://doi.org/10.1109/isca52012.2021.00050) | 2021 | ML-HW | ResNet/DeepBench | speedup vs Timeloop | 2.5x geomean, 90x faster tts | reuse implicit, static | ucb-bar/cosa |
| Scratchpad vs cache | [Banakar et al.](https://doi.org/10.1109/codes.2002.1003604) | 2002 | ARCH | embedded | energy, area-time | -40% energy, -46% area-time | needs static allocation | — |
| Hawkeye / learned Belady | [Jain & Lin](https://doi.org/10.1109/isca.2016.17) | 2016 | ARCH | SPEC | MPKI, IPC vs LRU | -20-30% MPKI, ~15% IPC | predictor storage | CRC2 |
| Pin or Fuse (cross-layer SPM) | [Jeong et al.](https://doi.org/10.1145/3579990.3580017) | 2023 | ML-HW | CNN models | off-chip transfer, latency | -50% transfer, -15% latency | activations, static | — |

## Lineage & history

- **Origins (1966-1970):** [Belady's MIN](https://doi.org/10.1147/sj.52.0078) defines optimal replacement; [Mattson's stack distance](https://doi.org/10.1147/sj.92.0078) makes locality measurable across all cache sizes in one pass. These two are the twin roots of all locality profiling.
- **Compiler-era locality (1991-2003):** loop-nest reuse theory [(Wolf & Lam, 1991)](https://www.semanticscholar.org/paper/f4dff66ba8f2338d118f379f2eff1410feb57ce6) makes reuse a static, tiling-driven quantity; [Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159) makes trace-driven reuse distance scalable and predictive. Branch point: ANALYTICAL (from the loop nest) vs TRACE-DRIVEN (from the reference stream) locality, a split that persists to today.
- **Scratchpad-vs-cache debate (2002-2005):** [Banakar, 2002](https://doi.org/10.1109/codes.2002.1003604) shows scratchpads win on area/energy WHEN the access pattern is statically allocatable; cache-aware allocation (2004) and memory coloring (2005) push static management further. This is why accelerators overwhelmingly chose scratchpads.
- **Parallel/accelerator locality (2010-2014):** reuse distance is extended to concurrent execution [(Nugteren et al., 2014)](https://doi.org/10.1109/hpca.2014.6835955; multicore RD, 2010), proving trace-driven profiling works for a shared HW cache fed by many PEs.
- **DNN dataflow analytics (2016-2021):** [Eyeriss](https://doi.org/10.1109/jssc.2016.2616357) fixes the scratchpad-based spatial template; [MAESTRO](https://doi.org/10.1145/3352460.3358252)/[Timeloop](https://doi.org/10.1109/ispass.2019.00042)/[Interstellar](https://doi.org/10.1145/3373376.3378514)/[ZigZag](https://doi.org/10.1109/tc.2021.3059962) formalize analytical reuse from the mapping; [CoSA](https://doi.org/10.1109/isca52012.2021.00050) turns it into an MILP. Paradigm: reuse is optimized statically by the schedule, buffers are explicit.
- **Learned/reuse-aware cache policy (2012-2017):** [Hawkeye, 2016](https://doi.org/10.1109/isca.2016.17) and reuse-distance-aware replacement (2012) revive the cache side by learning near-Belady behavior from reuse intervals.
- **-> Today's frontier (2022-2026):** hybrid cache/scratchpad organizations (Compad, 2023), reuse-aware cacheability for accelerators (HyDRA, 2026), and SNN-specific memories (scratchpad SNN accelerators, 2023-2024). The open convergence: bring trace-driven reuse-distance profiling (branch 1a) to bear on the analytically-scheduled accelerator (branch 1b/1c) to decide if a cache beats the scratchpad.

## Cross-family insights
- The **architecture/compiler** community measures reuse from TRACES (reuse distance, MRC) and designs POLICIES (replacement, prefetch) around it. The **ML-accelerator** community computes reuse ANALYTICALLY from the mapping and eliminates dynamic management via scratchpads. The user sits at the seam: an ML-accelerator scheduler (CoSA-family) that wants to adopt an architecture-community memory (a cache), which requires importing the architecture-community's profiling methodology (reuse distance / MRC / Belady) that the ML-accelerator tools do not provide.
- Both agree on the decision rule: a cache pays off only when reuse is dynamic/irregular enough that static allocation leaves misses on the table; when reuse is fully statically capturable, the scratchpad wins on area/energy.
