---
aliases: [Mattson stack distance, LRU stack distance, one-pass cache simulation]
topics: [reuse-distance, stack-distance, cache-modeling, profiling-methodology]
author: Mattson, Gecsei, Slutz, Traiger
venue: IBM Systems Journal
year: 1970
status: pass-2
bibkey: mattson1970evaluation
gist: Origin of stack (LRU) distance; one trace pass yields the miss ratio for ALL cache sizes at once.
---

# Evaluation Techniques for Storage Hierarchies (Mattson et al., 1970)

- **problem**: Evaluating a storage hierarchy naively needs one simulation per cache size; infeasible to sweep the whole design space of capacities from a trace.
- **challenge**: Want the full miss-ratio-vs-capacity curve from a single pass over one address trace.
- **current SoTA (then)**: Per-configuration trace simulation, one run per (size, associativity).
- **novelty**: Defines **stack distance** for a "stack algorithm" (LRU, OPT, LFU): the position of a referenced block in the priority stack = number of distinct blocks referenced since its last use. The **inclusion property** guarantees a smaller cache's contents are a subset of a larger one, so one pass produces the miss count at every capacity simultaneously.
- **proposal**: Maintain an LRU stack; on each reference, find the block's depth d (its stack/reuse distance); a cache of C lines hits iff d <= C. Histogram of d over the trace gives, by cumulative sum, the hit ratio for every C. Generalizes to OPT and to set-associative caches.
- **evaluation**: Analytical/simulation demonstration on program traces; the method is exact for any stack algorithm, not an approximation.
  - Table row: `1970 | profiling-method | address traces | miss-ratio curve vs capacity | exact single-pass for all sizes | — | n/a`
- **assumptions**: Reference stream is a fixed trace; replacement is a stack algorithm (inclusion holds). Fully-associative in the base form.
- **limitation**: Naive stack search is O(N*M) (M distinct blocks); associativity/line effects need extra bookkeeping; single-thread trace (no parallel interleaving).
- **impact**: Foundational; every reuse-distance / working-set profiling tool descends from this. The miss-ratio curve (MRC) is exactly the "how big must the cache be" answer the user needs.
- **risks**: Cost of exact stack distance on billion-reference traces motivated later approximate methods.
- **related work**: Feeds [Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159); Belady OPT ([Belady, 1966](https://doi.org/10.1147/sj.52.0078)) is the companion optimal policy.
- **my take**: For snn_cosa, the stack-distance histogram of the weight address trace directly yields the node-cache miss curve; pick cache capacity at the knee of the MRC.
- **relevance**: HIGH - the exact tool to convert a weight/activation address trace into "cache size vs miss-rate" for the node level.
- **future work**: Approximation and parallel-aware variants (later papers).
- **triage**: Pass-2; canonical method understood.
- **terms**: stack distance, reuse distance, inclusion property, miss-ratio curve (MRC), stack algorithm.
- **citation**: [Mattson et al., 1970](https://doi.org/10.1147/sj.92.0078)
- **code**: none (algorithm; modern impls: PyRDA, `libcachesim`, `olken`).
- **refs**: Belady 1966.
- **obsidian links**: [[reuse-distance]], [[cache-modeling]]
