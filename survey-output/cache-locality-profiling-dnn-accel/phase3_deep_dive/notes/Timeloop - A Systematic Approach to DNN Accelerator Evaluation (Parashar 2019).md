---
aliases: [Timeloop, mapspace search, per-level access accounting]
topics: [analytical-model, dataflow, reuse-accounting, buffer-sizing, profiling-methodology]
author: Parashar, Raina, Shao, Chen, Ying, Mukkara, Venkatesan, Khailany, Keckler, Emer
venue: ISPASS
year: 2019
status: pass-2
bibkey: parashar2019timeloop
gist: Analytical infra that accounts accesses/fills/reuse per tensor per memory level for any mapping, and searches the mapspace.
---

# Timeloop: A Systematic Approach to DNN Accelerator Evaluation (Parashar et al., 2019)

- **problem**: Comparing accelerator architectures and mappings fairly needs a uniform way to project performance/energy from a loop-nest mapping.
- **challenge**: Given an arbitrary tiling/permutation and memory hierarchy, compute exact per-level data movement without RTL.
- **current SoTA (then)**: Point cost models tied to one architecture; cycle-accurate sim (slow, not general).
- **novelty**: A unified loop-nest + hierarchy representation; an analytical engine that does exact **accounting of accesses, fills, and reuse per tensor per memory level**; derives buffer occupancy per level from the mapping; and a mapspace search (random/heuristic pruning) to find optimal mappings. Pairs with [Accelergy, 2019](https://doi.org/10.1109/iccad45719.2019.8942149) to turn access counts into energy.
- **proposal**: Model = (workload loop nest) x (hardware topology) -> per-level read/write/fill/update counts, occupancy, and utilization; sweep mappings to report the Pareto set.
- **evaluation**: Reproduces Eyeriss and other designs; access-count-based energy/performance close to published/RTL numbers; enumerates and prunes very large mapspaces.
  - Table row: `2019 | analytical-reuse | CONV/GEMM | per-level access counts, energy | matches Eyeriss-class designs | static mapping only | github timeloop`
- **assumptions**: Affine, dense tensors; a mapping is fixed and executes exactly as accounted; explicit (scratchpad) buffers with known fill policy.
- **limitation**: No dynamic/hardware-cache behavior (assumes managed buffers); dense-only in base form; mapspace search can be costly.
- **impact**: The de-facto reuse/traffic accounting tool; anchors the analytical-reuse family and the buffer-size reasoning in the prior survey.
- **risks**: Because it assumes explicit buffering, it cannot tell you a CACHE's miss rate - it presumes the schedule controls residency.
- **related work**: Co-designed with Accelergy; extended by [ZigZag, 2021](https://doi.org/10.1109/tc.2021.3059962), DOSA (2023); the analytical counterpart to trace-driven [Nugteren 2014](https://doi.org/10.1109/hpca.2014.6835955).
- **my take**: snn_cosa already produces exactly the loop-nest mapping Timeloop consumes; its per-level access counts are the ANALYTICAL reuse baseline. To evaluate a cache, feed Timeloop's per-level address stream into a stack-distance model (the missing dynamic layer).
- **relevance**: HIGH - defines the analytical per-level reuse accounting; shows precisely what a scratchpad model gives and what a cache model must add.
- **future work**: Sparse tensors (later Sparseloop); dynamic residency.
- **triage**: Pass-2 (method from tutorial + paper).
- **terms**: mapspace, access/fill accounting, occupancy, per-level reuse, permutation.
- **citation**: [Parashar et al., 2019](https://doi.org/10.1109/ispass.2019.00042)
- **code**: Timeloop + Accelergy (accelergy.mit.edu).
- **refs**: Accelergy; Eyeriss.
- **obsidian links**: [[analytical-model]], [[reuse-accounting]]
