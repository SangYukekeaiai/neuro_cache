# Phase 3 selection: 14 papers for full reading

Chosen for method diversity across the four operational definitions of spatial locality
(neighbor proximity, line utilization, line-size payoff, index-bit spread), weighted toward
papers that *define a measurement* over papers that consume one.

| # | Paper | Year | Why |
|---|---|---|---|
| 1 | [Mattson et al., Evaluation techniques for storage hierarchies](https://doi.org/10.1147/sj.92.0078) | 1970 | The root. Stack distance, the inclusion property, and the original treatment of block size in a one-pass evaluation. |
| 2 | [Smith, Line (block) size choice for CPU cache memories](https://doi.org/10.1016/0141-9331(87)90424-8) | 1987 | The canonical line-size methodology and the transfer-time tradeoff that makes the sweep non-monotone. |
| 3 | [Hill and Smith, Evaluating associativity in CPU caches](https://doi.org/10.1109/12.40842) | 1989 | The 3C model and all-associativity simulation: the tool that separates a conflict problem from a locality problem. |
| 4 | [Kumar and Wilkerson, Exploiting spatial locality in data caches using spatial footprints](https://doi.org/10.1109/isca.1998.694794) | 1998 | The direct per-line utilization measurement, and the predictor built on it. |
| 5 | [Johnson, Merten and Hwu, Run-time spatial locality detection and optimization](https://doi.org/10.1109/micro.1997.645797) | 1997 | Online spatial-locality classification from the address stream, no offline pass. |
| 6 | [Weinberg et al., Quantifying locality in the memory access patterns of HPC applications](https://doi.org/10.1109/sc.2005.59) | 2005 | The single-number spatial score, the most cited scalar metric. |
| 7 | [Berg and Hagersten, StatCache](https://doi.org/10.1109/ispass.2004.1291352) | 2004 | Sampled reuse distance: makes the measurement affordable on a long trace. |
| 8 | [Eklov and Hagersten, StatStack](https://doi.org/10.1109/ispass.2010.5452069) | 2010 | The successor: full miss-ratio curve from sparse sampling. |
| 9 | [Zhong et al., Miss rate prediction across program inputs and cache configurations](https://doi.org/10.1109/tc.2007.50) | 2007 | Extends reuse distance ACROSS LINE SIZES, which is the granularity-swept surface. The key methodological paper for this survey. |
| 10 | [Gu et al., A component model of spatial locality](https://doi.org/10.1145/1542431.1542446) | 2009 | Decomposes spatial locality into per-component contributions rather than one aggregate. |
| 11 | [Xiang et al., A higher order theory of locality](https://doi.org/10.1145/2247684.2247697) | 2012 | Footprint theory: converts window footprint to miss ratio, the alternative to stack distance. |
| 12 | [Qureshi et al., Line Distillation](https://doi.org/10.1109/hpca.2007.346202) | 2007 | Quantifies unused words per line and acts on it; the utilization-distribution evidence. |
| 13 | [Data-driven spatial locality](https://doi.org/10.1145/3240302.3240417) | 2018 | Recent attempt to derive layout from measured co-access rather than score a fixed one. |
| 14 | [SLAWS](https://doi.org/10.1145/3779212.3790222) | 2026 | The frontier: spatial-locality analysis applied to sparse workload scheduling. |
