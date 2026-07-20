---
aliases: [Banakar scratchpad vs cache, SPM vs cache tradeoff]
topics: [scratchpad, cache, area-energy-tradeoff, on-chip-memory]
author: Banakar, Steinke, Lee, Balakrishnan, Marwedel
venue: CODES
year: 2002
status: pass-2
bibkey: banakar2002scratchpad
gist: Seminal quantitative case that a scratchpad beats a same-capacity cache on area and energy (no tag/compare/control overhead).
---

# Scratchpad Memory: A Design Alternative for Cache On-chip Memory (Banakar et al., 2002)

- **problem**: Should an embedded on-chip memory be a hardware-managed cache or a software-managed scratchpad (SPM)?
- **challenge**: Fair area/energy/performance comparison at equal capacity.
- **current SoTA (then)**: Caches assumed by default for on-chip memory.
- **novelty**: Direct head-to-head: a cache pays for tag array, comparators, and control logic that an SPM omits; SPM is directly addressed and deterministic.
- **proposal**: Compute area and energy for many SPM and cache sizes with CACTI; measure performance via trace-driven simulation of the target processor (AT91M40400); a compiler statically assigns the hottest data/code to the SPM.
- **evaluation**: SPM gives on average **40% energy reduction** and **46% smaller area-time product** than a cache of the same capacity, with comparable or better performance.
  - Table row: `2002 | SPM-vs-cache | embedded benchmarks | energy, area-time vs cache | -40% energy, -46% area-time | needs static SW allocation | n/a`
- **assumptions**: Access pattern known enough at compile time to allocate the SPM; single-core embedded.
- **limitation**: SPM benefit hinges on good static allocation; irregular/data-dependent access patterns (where a cache's dynamic management wins) are exactly where SPM struggles.
- **impact**: The canonical justification for scratchpads in accelerators - why nearly every DNN accelerator (Eyeriss, DianNao, CoSA's model) uses an explicit buffer, not a cache.
- **risks**: For the user this is the argument to BEAT: a node cache must pay tag/control overhead, so it only wins if dynamic weight reuse is irregular enough that static allocation (the scheduler) leaves reuse on the table.
- **related work**: Basis for [cache-aware SPM allocation, 2004](https://doi.org/10.1109/date.2004.1269069), memory coloring (2005); contrast to Buffets (2019).
- **my take**: Frames the whole snn_cosa question: profile whether weight reuse is STATICALLY capturable by the CoSA schedule (then keep the scratchpad) or has dynamic, input-dependent irregularity a cache would catch (then a cache's overhead may pay off). The locality profiling is precisely how to decide.
- **relevance**: HIGH - the decision criterion (static-predictable vs dynamic-irregular reuse) that the user's profiling must resolve.
- **future work**: Dynamic SPM overlays; hybrid SPM+cache.
- **triage**: Pass-2 (grounded on abstract + CACTI/AT91 methodology).
- **terms**: scratchpad (SPM), tag overhead, area-time product, static allocation, CACTI.
- **citation**: [Banakar et al., 2002](https://doi.org/10.1109/codes.2002.1003604)
- **code**: none.
- **refs**: CACTI; later SPM-allocation papers.
- **obsidian links**: [[scratchpad]], [[cache]]
