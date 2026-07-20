---
aliases: [Hawkeye, OPTgen, learned Belady, reuse-interval replacement]
topics: [replacement-policy, belady-optimal, reuse-distance, cache-management]
author: Jain, Lin
venue: ISCA
year: 2016
status: pass-2
bibkey: jain2016back
gist: Reconstructs Belady-optimal decisions from PAST accesses (OPTgen) and learns them to drive a practical replacement policy.
---

# Back to the Future: Leveraging Belady's Algorithm for Improved Cache Replacement (Jain & Lin, 2016)

- **problem**: LRU is far from optimal; Belady's MIN needs future knowledge and cannot run online.
- **challenge**: Approximate Belady online using only observed history.
- **current SoTA (then)**: LRU, DIP/RRIP, dead-block predictors - all history heuristics, not optimal-derived.
- **novelty**: **OPTgen** computes what Belady's OPT WOULD have done over a past window by analyzing **usage intervals** (the span between successive references to a line) and reuse distances: a line "hits under OPT" iff the cache has capacity across its usage interval. Then a PC-indexed predictor learns which loads lead to cache-friendly vs cache-averse lines from OPTgen's labels.
- **proposal**: Offline-style OPT reconstruction over a rolling history feeds an online predictor; lines predicted cache-averse are inserted with low priority / evicted first.
- **evaluation**: ~20-30% MPKI reduction and single-digit-to-~15% IPC gains over LRU on memory-intensive workloads; beats DIP/RRIP/SHiP class policies.
  - Table row: `2016 | replacement-policy | SPEC memory-intensive | MPKI, IPC vs LRU | -20-30% MPKI, up to ~15% IPC | needs PC + history storage | github (crc2 variants)`
- **assumptions**: Past usage intervals predict future ones; PC correlates with reuse behavior; set-associative LRU-managed cache.
- **limitation**: Storage for OPTgen occupancy vector + predictor; phase changes/unseen code hurt accuracy.
- **impact**: Reframes replacement-policy design as "learn Belady from reuse intervals" - the method by which reuse/locality DATA justifies a policy.
- **risks**: For an accelerator with a highly regular weight schedule, OPT and the schedule may nearly coincide, shrinking the cache's advantage over a well-managed scratchpad.
- **related work**: Optimal baseline [Belady, 1966](https://doi.org/10.1147/sj.52.0078); reuse-distance-driven policies ([Dynamic Reuse Distances, 2012](https://www.semanticscholar.org/paper/bb0ecaa562f8af82a895fa70409e5982e6d22907)).
- **my take**: For snn_cosa, OPTgen run OFFLINE on the weight address trace gives the Belady-optimal miss count = the best any node-cache replacement could do. Comparing that to LRU on the same trace tells you whether replacement policy even matters here, and whether a reuse-distance-aware policy is worth the hardware.
- **relevance**: HIGH - supplies the Belady-optimal lower bound and the reuse-interval method to evaluate cache replacement policy choice.
- **future work**: Learned/perceptron replacement (Glider); prefetch-aware OPT.
- **triage**: Pass-2 (full PDF read).
- **terms**: OPTgen, usage interval, Belady/MIN, cache-averse load, PC-indexed predictor.
- **citation**: [Jain & Lin, 2016](https://doi.org/10.1109/isca.2016.17)
- **code**: Hawkeye (2nd Cache Replacement Championship).
- **refs**: Belady 1966; RRIP.
- **obsidian links**: [[replacement-policy]], [[belady-optimal]]
