# Phase 4 — Code & Artifacts: tools for reuse/locality profiling and cache-vs-scratchpad studies

Two ecosystems matter for the user: (A) **analytical reuse models** that consume a loop-nest
mapping (what snn_cosa already emits), and (B) **trace-driven cache/reuse-distance simulators**
that consume an address trace (what the user must add to study a hardware cache).

## A. Analytical reuse / mapping models (mapping -> per-level reuse, traffic, energy)

| Tool | URL | Lang | What it provides | Maintained |
|------|-----|------|------------------|-----------|
| Timeloop | https://github.com/NVlabs/timeloop | C++ | Per-tensor, per-level access/fill/reuse accounting from a mapping; mapspace search | Active |
| Accelergy | https://github.com/Accelergy-Project | Python | Access-count -> energy back end for Timeloop | Active |
| Sparseloop | https://github.com/Accelergy-Project/micro22-sparseloop-artifact | C++ | Adds sparse-tensor reuse modeling on Timeloop | Artifact |
| timeloop-python | https://github.com/Accelergy-Project/timeloop-python | Python | Python wrapper (scriptable per-level stats) | Active |
| MAESTRO | https://github.com/maestro-project/maestro | C++/Py | Temporal vs spatial reuse factors, buffer/NoC/energy from a mapping | Active |
| CoSA | https://github.com/ucb-bar/cosa | Python | The user's own MILP scheduler; **ships an `nocsim/`** (snn_cosa lineage) | Active |

Takeaway: these give the ANALYTICAL, static reuse the schedule captures. None models a
hardware cache's dynamic eviction; that is the gap the trace-driven tools below fill.

## B. Trace-driven reuse-distance / cache simulators (address trace -> miss curve, policy sweep)

| Tool | URL | Lang | What it provides | Maintained |
|------|-----|------|------------------|-----------|
| libCacheSim | https://github.com/1a1a11a/libCacheSim | C | High-perf trace-driven cache sim (>20M req/s); many replacement policies; MRC/reuse-distance | Active |
| libCacheSim-python | https://github.com/cacheMon/libCacheSim-python | Python | Python bindings for the above; rapid policy/MRC experiments | Active |
| PyMimircache | https://github.com/1a1a11a/PyMimircache | Python | Reuse-distance + miss-ratio-curve (MRC) profiling; Belady/OPT, LRU, etc. (deprecated, superseded by libCacheSim) | Deprecated |
| DineroIV (+ py reimpls) | https://github.com/Serpent999/Dinero_Cache_Simulator_Python | C/Python | Classic trace-driven multi-level cache simulator (line size, associativity, policy) | Community |
| Nugteren GPU RD model | https://cnugteren.github.io/ (downloads) | C++ | Parallel reuse-distance model for a GPU cache (associativity, MSHRs, warp interleave) | Reference |
| GPGPU-Sim | http://www.gpgpu-sim.org/ | C++ | Cycle-accurate parallel cache behavior (validation baseline for a node cache) | Active |

## C. Reuse-distance analysis primitives (compute RD histograms from a trace)
- **Olken / tree-based stack distance**: the O(N log M) exact algorithm ([Mattson 1970](https://doi.org/10.1147/sj.92.0078) lineage) implemented in libCacheSim and PyMimircache.
- **Approximate reuse distance** ([Ding & Zhong 2003](https://doi.org/10.1145/781158.781159)): near-linear RD histograms for long traces; the scalable option for full-layer weight traces.

## Recommendation for snn_cosa
Instrument the scheduler + `nocsim` to emit a **per-tensor weight/activation address trace**
(one line per PE reference, cache-line-granular), then feed it to **libCacheSim** (or its Python
bindings) to get: the miss-ratio curve (cache-size sweep), reuse-distance histogram (within- vs
between-tile modes), and a replacement-policy sweep (LRU vs Belady/OPT via PyMimircache/OPTgen).
The analytical Timeloop/CoSA numbers give the static-reuse baseline to compare against.

Gate: >=3 empirical repos — met (Timeloop, MAESTRO, CoSA, libCacheSim, PyMimircache, GPGPU-Sim).
