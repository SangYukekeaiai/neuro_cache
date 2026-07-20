---
aliases: [CoSA, MILP scheduler, constrained-optimization mapping]
topics: [scheduler, MILP, reuse-encoding, traffic-model, dataflow]
author: Huang, Yazdanbakhsh, Nakamura, Genc, Shao, et al.
venue: ISCA
year: 2021
status: pass-3
bibkey: huang2021cosa
gist: One-shot MILP mapper; encodes tiling/permutation as binary X, models per-level utilization and inter-level traffic.
---

# CoSA: Scheduling by Constrained Optimization for Spatial Accelerators (Huang et al., 2021)

- **problem**: Mapspace search (Timeloop-style) is slow and iterative; want an optimal schedule in one shot.
- **challenge**: Express reuse, buffer capacity, and traffic as linear constraints so an MILP solver finds the mapping directly.
- **current SoTA (then)**: Random/heuristic mapspace search ([Timeloop, 2019](https://doi.org/10.1109/ispass.2019.00042); Marvel; GAMMA).
- **novelty**: Binary decision tensor **X(j,n,i,k)**: layer-dim j, prime-factor index n, memory level i, spatial/temporal k - places each prime factor of each loop bound at exactly one level as spatial or temporal. Utilization constraint (Eq. 2, log-linearized): sum of placed log-factors <= log(capacity M) per buffer. Traffic objective (Eq. 11) = sum over tensors of D_v (data size) + L_v (spatial multicast/unicast/reduction cost) + T_v (temporal outer-loop iteration multiplier).
- **proposal**: Reuse is IMPLICIT: keeping a tensor's factors inner/resident lowers its T_v traffic term, so the objective rewards locality without an explicit reuse variable. Auxiliary Y encodes traffic iteration factors; O encodes permutation rank.
- **evaluation**: 2.5x geomean speedup over Timeloop-Hybrid schedules; 90x faster time-to-solution (4.2 s vs 379.9 s per layer) on ResNet-50/ResNeXt-50/DeepBench. Hierarchy modeled: register 64B, accum buffer 3KB, weight buffer 32KB, input buffer 8KB, global buffer 128KB, DRAM.
  - Table row: `2021 | MILP-scheduler | ResNet/ResNeXt/DeepBench | speedup vs Timeloop | 2.5x geomean, 90x faster tts | reuse implicit, static | github cosa`
- **assumptions**: Explicit multi-level scratchpad hierarchy with known capacities; single layer at a time; affine dense tensors.
- **limitation**: Reuse only via traffic terms, not a residency/eviction model; assumes software-managed buffers (no cache).
- **impact**: The user's own scheduler family; shows how snn_cosa can EMIT a per-level address/traffic model that a cache profiler could consume.
- **risks**: Because buffers are assumed scratchpads, swapping in a cache changes the traffic accounting the MILP relies on.
- **related work**: Same lineage as [MAESTRO, 2019](https://doi.org/10.1145/3352460.3358252), Timeloop; Gemmini backend.
- **my take**: CoSA's X and Y variables already localize which tensor factors sit at the node buffer; the T_v/L_v terms are an analytical reuse proxy. To profile a node CACHE, generate the per-level reference stream implied by X and run stack-distance analysis - CoSA gives the schedule, the trace-driven model gives the miss curve.
- **relevance**: HIGH - the exact scheduler snn_cosa is built on; the natural place to instrument the address trace.
- **future work**: Cache-aware objective; dynamic residency.
- **triage**: Pass-3 (abstract + ar5iv equations).
- **terms**: MILP, factor placement X, utilization constraint, traffic term T_v/L_v/D_v, permutation rank.
- **citation**: [Huang et al., 2021](https://doi.org/10.1109/isca52012.2021.00050)
- **code**: CoSA (github.com/ucb-bar/cosa).
- **refs**: Timeloop; MAESTRO; Gemmini.
- **obsidian links**: [[scheduler]], [[reuse-encoding]]
