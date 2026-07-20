---
aliases: [MAESTRO, data-centric dataflow, temporal spatial reuse directions]
topics: [reuse-modeling, dataflow, analytical-model, tile-reuse, profiling-methodology]
author: Kwon, Chatarasi, Pellauer, Parashar, Sarkar, Krishna
venue: MICRO
year: 2019
status: pass-3
bibkey: kwon2019understanding
gist: Data-centric analytical model that quantifies temporal (within-PE) and spatial (across-PE) reuse from a mapping.
---

# Understanding Reuse, Performance, and Hardware Cost of DNN Dataflows (MAESTRO) (Kwon et al., 2019)

- **problem**: Architects lack a principled way to quantify how a chosen dataflow/mapping exposes data reuse and what buffer/NoC/energy cost it implies.
- **challenge**: Separate the two reuse regimes - reuse in time at one PE vs reuse in space across PEs - analytically from the loop nest.
- **current SoTA (then)**: Compute-centric loop-nest analysis and cycle-accurate RTL (slow, opaque about reuse).
- **novelty**: A **data-centric** representation with four directives - `SpatialMap(size,offset)`, `TemporalMap(size,offset)`, data-movement Order, and Cluster - that make reuse explicit. Distinguishes **spatial reuse** (a datum read once, wire-multicast to many PEs) from **temporal reuse** (a datum read once into a small local buffer, reused across time steps at one PE).
- **proposal**: From the mapping it infers, per tensor, the reuse factor (local accesses per remote fetch), the required buffer size per level, NoC bandwidth, runtime (compute+communication pipe model), and energy (activity counts x CACTI parameters).
- **evaluation**: Model output within 3.9% of cycle-accurate RTL, 1029-4116x faster (10 ms vs 7.2-28.8 h). DSE at 0.17M designs/s over 480M designs. Per-layer adaptive dataflow gives 37% runtime and 10% energy reduction; early layers show 5.8x/15.17x higher activation/filter reuse for a row-stationary map.
  - Table row: `2019 | analytical-reuse | CONV layers (VGG/ResNet) | model error vs RTL | 3.9%, ~1000-4000x faster | affine, <=2 coupled dims | github MAESTRO`
- **assumptions**: Affine tensor accesses with <=2 coupled dims; uniform sparsity; bus/crossbar NoC; 2-3 hierarchy levels.
- **limitation**: Cannot model modulus/strided-conv subscripts or statistical sparsity; mesh NoC approximated.
- **impact**: The canonical decomposition of within-tile (temporal) vs across-PE (spatial) reuse - exactly the two regimes the user wants to profile.
- **risks**: Analytical reuse assumes the mapping executes as modeled; ignores dynamic cache effects.
- **related work**: Sibling to [Timeloop, 2019](https://doi.org/10.1109/ispass.2019.00042); consumed by [Marvel, 2021](https://doi.org/10.1145/3485137) and [CoSA, 2021](https://doi.org/10.1109/isca52012.2021.00050).
- **my take**: MAESTRO's temporal-vs-spatial reuse split is the vocabulary for snn_cosa's within-tile vs between-tile regimes. But it gives ANALYTICAL reuse for a scratchpad; a cache adds dynamic eviction that MAESTRO does not model - the gap this survey targets.
- **relevance**: HIGH - defines and quantifies the two reuse regimes; contrast case for why a cache needs trace-driven profiling on top.
- **future work**: Sparse/irregular reuse; dynamic cache behavior.
- **triage**: Pass-3 (full ar5iv read).
- **terms**: temporal reuse, spatial reuse, reuse direction, SpatialMap/TemporalMap, reuse factor, data-centric.
- **citation**: [Kwon et al., 2019](https://doi.org/10.1145/3352460.3358252)
- **code**: MAESTRO (github.com/maestro-project/maestro).
- **refs**: Timeloop; Eyeriss.
- **obsidian links**: [[reuse-modeling]], [[dataflow]]
