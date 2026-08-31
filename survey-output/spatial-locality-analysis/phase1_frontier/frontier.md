# Phase 1: Frontier (2022-2026)

Topic: **methodologies for measuring and characterizing spatial locality in memory address traces**.

Family routing: computer architecture + performance analysis (ISCA/MICRO/HPCA/ASPLOS, ISPASS, IISWC, MEMSYS, SC, PACT, TACO, ToC).
Sources actually reachable: Crossref, OpenAlex, arXiv. Semantic Scholar was rate-limited on every attempt (no API key); see search_log.md.

## Recent on-topic papers (19)

| Year | Cites | Title | Venue |
|---|---|---|---|
| 2026 | 0 | [SLAWS: Spatial Locality Analysis and Workload Orchestration for Sparse Matrix Multiplication](https://doi.org/10.1145/3779212.3790222) | Proceedings of the 31st ACM International Conference on |
| 2026 | 0 | [Sequential Memory Access Characterization and Schedule Optimization for Deep Neural Network Inference](https://doi.org/10.2139/ssrn.6835478) |  |
| 2025 | 0 | [CASM: A Generalizable and Accessible Security Metric to Evaluate Security of Cache Architectures](https://doi.org/10.1109/iiswc66894.2025.00024) | 2025 IEEE International Symposium on Workload Character |
| 2025 | 0 | [Learning Architectural Cache Simulator Behaviour](https://doi.org/10.1109/iiswc66894.2025.00025) | 2025 IEEE International Symposium on Workload Character |
| 2025 | 0 | [Advancing runtime data-locality via memory-centric graph-based hardware accelerators](https://doi.org/10.32657/10356/204495) |  |
| 2024 | 6 | [CARM Tool: Cache-Aware Roofline Model Automatic Benchmarking and Application Analysis](https://doi.org/10.1109/iiswc63097.2024.00016) | 2024 IEEE International Symposium on Workload Character |
| 2024 | 2 | [HBPB, applying reuse distance to improve cache efficiency proactively](https://doi.org/10.1016/j.jpdc.2024.104919) | Journal of Parallel and Distributed Computing |
| 2023 | 64 | [FIFO queues are all you need for cache eviction](https://doi.org/10.1145/3600006.3613147) |  |
| 2023 | 7 | [Data Locality Aware Computation Offloading in Near Memory Processing Architecture for Big Data Applications](https://doi.org/10.1109/hipc58850.2023.00019) | 2023 IEEE 30th International Conference on High Perform |
| 2023 | 4 | [Characterization of Memory Access in Deep Learning and Its Implications in Memory Management](https://doi.org/10.32604/cmc.2023.039236) | Computers, Materials &amp; Continua |
| 2023 | 2 | [Analyzing Data Locality on GPU Caches Using Static Profiling of Workloads](https://doi.org/10.1109/access.2023.3307315) | IEEE Access |
| 2023 | 1 | [Exploiting data locality in cache-coherent NUMA systems](https://doi.org/10.5821/dissertation-2117-367546) |  |
| 2023 | 1 | [Dynamic First Access Isolation Cache to Eliminate Reuse-Based Cache Side Channel Attacks](https://doi.org/10.1142/s0218126623500263) | Journal of Circuits, Systems and Computers |
| 2023 | 0 | [Applying machine learning to enhance the cache performance using reuse distance](https://doi.org/10.1007/s12065-022-00730-1) | Evolutionary Intelligence |
| 2023 | 0 | [A tool for profiling memory accesses locality on NUMA architectures](https://doi.org/10.5753/eradsp.2023.232017) | Anais da XIV Escola Regional de Alto Desempenho de São  |
| 2023 | 0 | [Smart memory management through locality analysis](https://doi.org/10.5821/dissertation-2117-93280) |  |
| 2022 | 9 | [Analyzing Memory Access Traces of Deep Learning Workloads for Efficient Memory Management](https://doi.org/10.1109/itme56794.2022.00090) | 2022 12th International Conference on Information Techn |
| 2022 | 3 | [A Counter-Based Profiling Scheme for Improving Locality Through Data and Reducer Placement](https://doi.org/10.1007/978-981-16-8930-7_4) | Intelligent Systems Reference Library |
| 2022 | 1 | [Exploiting data locality in memory for ORAM to reduce memory access overheads](https://doi.org/10.1145/3489517.3530547) | Proceedings of the 59th ACM/IEEE Design Automation Conf |

## Trending directions (3-5)

1. **Locality analysis moves to accelerators and irregular workloads.** The one genuinely
   new methodology paper in the window, SLAWS (2026), applies spatial-locality analysis to
   sparse matrix multiplication scheduling. DNN memory-access characterization (2022, 2023,
   2026) is the other active thread. Both take the classical trace-analysis toolkit and
   re-aim it at accelerator dataflow rather than at CPU programs.
2. **Learned surrogates for cache simulation.** "Learning Architectural Cache Simulator
   Behaviour" (IISWC 2025) and the ML-plus-reuse-distance work (2023) try to replace the
   simulation pass with a regression model. Methodologically this is a departure: the
   classical methods are all exact single-pass measurements.
3. **Reuse distance used as an actuator, not a metric.** HBPB (2024), reuse-distance
   victim caches, reuse-distance-based replacement. The measurement matured, so it moved
   from offline characterization into online hardware.
4. **Static/compile-time locality profiling** for GPUs (2023) as an alternative to the
   trace pass.
5. **The frontier for MEASUREMENT METHODOLOGY itself is nearly empty.** Almost every
   recent hit applies an existing metric; very few define a new one. That is a finding, not
   a search failure, and it means the methodology corpus is dominated by 1970-2015 work.
   Phase 2 therefore weights the roots heavily.

## Key groups

- Ding / Xiang / Zhong (Rochester): reuse distance, footprint theory, reference affinity.
- Hagersten / Berg / Eklov (Uppsala): sampled reuse distance, StatCache / StatStack.
- Ding, Gu, Bai: the component model of spatial locality.
- Snavely / Weinberg (SDSC): the HPC locality scores.
- Wood / Sardashti (Wisconsin): spatial locality for compressed and sectored caches.
