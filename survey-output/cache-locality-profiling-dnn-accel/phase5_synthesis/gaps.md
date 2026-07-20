# Gaps & Open Questions

Numbered research questions (RQ) that emerged, oriented to the user's snn_cosa cache decision.

**RQ1 — Trace-driven reuse-distance profiling is missing from accelerator scheduler toolchains.**
MAESTRO/Timeloop/CoSA emit ANALYTICAL per-level reuse but no address trace or reuse-distance
histogram; libCacheSim/PyMimircache consume traces but know nothing about the DNN loop nest. No
released tool bridges "CoSA schedule -> per-tensor address trace -> reuse-distance/MRC". The user
must build this bridge; it is also a genuine contribution.

**RQ2 — Within-tile vs between-tile reuse is not separately profiled.**
MAESTRO names temporal (within-PE) vs spatial (across-PE) reuse but reports factors, not
distributions. No work reports a reuse-distance histogram split into a SHORT-distance mode
(within-tile inner-loop reuse) and a LONG-distance mode (across-tile / across-PE reuse) — exactly
the user's two regimes. This split is the direct input to line-size (short mode) and
capacity/replacement (long mode) choices.

**RQ3 — The cache-vs-scratchpad decision for weights lacks a locality-grounded criterion in the
SNN/DNN accelerator setting.** Banakar's rule (static-allocatable -> scratchpad) predates DNN
schedulers. Nobody has quantified, for a CoSA-style weight schedule, the miss-rate GAP between the
schedule's static residency and Belady-optimal on the same trace — the gap that a cache could
recover. Without that number the cache's tag/control overhead cannot be justified.

**RQ4 — SNN-specific access patterns are unprofiled for caching.** SNN weight reuse is modulated
by spike sparsity and timesteps (T); membrane-potential (vmem) state adds a second, differently
-reused tensor. Whether spike-driven irregularity makes weight reuse cache-favorable (dynamic) or
still schedule-capturable (static) is open. Existing SNN accelerators (ping-pong 2023, scratchpad
SNN 2024) use scratchpads without reporting reuse-distance evidence.

**RQ5 — Replacement/prefetch policy evaluation on accelerator weight traces is absent.**
Hawkeye/OPTgen and reuse-distance-aware replacement are validated on CPU/SPEC traces, not on the
highly regular, tiled weight streams of an accelerator. Is LRU near-Belady here (making a simple
cache fine), or is a reuse-distance-aware / schedule-hinted policy needed? Prefetch is even less
explored: the schedule KNOWS the next tile's addresses, so a scheduler-driven prefetch (a
"perfect" prefetcher) is uniquely available to accelerators and unstudied.

**RQ6 — Working-set / MRC-driven cache sizing vs the fixed scratchpad capacity.** The node buffer
is a fixed 1024/2048-entry scratchpad today. No study derives the node-cache capacity from the
knee of the weight miss-ratio curve for representative SNN layers. This is a low-effort, high-value
first experiment.

## Note on survey scope (not open problems, just thin coverage here)
- Hybrid cache+scratchpad organizations (Compad, reconfigurable partitioning) surfaced but were not
  deep-read; a follow-up pass on that sub-area is warranted before a design decision.
- Coherence/write-traffic for a writable cache (psum/vmem) is out of scope of the read-heavy weight
  focus and under-covered here.
