# Phase 3 — Deep-read selection (11 papers)

Chosen for the profiling-methodology question, cache-vs-scratchpad decision, replacement-policy
justification, and SNN target. Marked (X-ref) where the prior dnn-noc-buffer-sizes survey already
deep-read the paper for buffer *sizing*; here it is re-read for its reuse *methodology*.

1. **Mattson et al., 1970 — Evaluation techniques for storage hierarchies** — origin of stack/LRU
   distance; one-pass miss-ratio-vs-all-cache-sizes. The canonical trace-driven profiling method.
2. **Ding & Zhong, 2003 — Predicting whole-program locality through reuse distance analysis** —
   makes reuse-distance measurement tractable (approximate, near-linear); the practical algorithm.
3. **Nugteren et al., 2014 — A detailed GPU cache model based on reuse distance theory** — applies
   reuse-distance to a real parallel HW cache with associativity/MSHR effects; closest template for
   modeling a node-level cache from an address trace.
4. **Kwon et al., 2019 — Understanding Reuse... (MAESTRO)** (X-ref) — analytical temporal/spatial
   reuse directions from the mapping; the within-tile vs across-tile decomposition the user wants.
5. **Parashar et al., 2019 — Timeloop** (X-ref) — systematic reuse/traffic accounting per memory
   level from the loop nest; how an analytical model reports per-tensor reuse.
6. **Banakar et al., 2003 — Scratchpad memory: a design alternative for cache** — the seminal
   scratchpad-vs-cache area/energy/predictability tradeoff; the argument the user must overcome.
7. **Jain & Lin, 2016 — Back to the Future: Leveraging Belady's Algorithm (Hawkeye)** — how Belady
   -optimal reuse behavior is turned into a practical replacement policy; policy justification method.
8. **Sembrant et al. / "Improving Cache Management Policies Using Dynamic Reuse Distances", 2012** —
   reuse-distance-aware replacement; directly ties RD profiling to a policy.
9. **Gysi et al., 2017 — Analytical modeling of cache behavior for affine programs** — closed-form
   cache-miss counts from the loop nest + tiling; the analytical alternative to trace-driven RD.
10. **Pin or Fuse?, 2023 — Exploiting Scratchpad Memory to Reduce Off-Chip Data Transfer in DNN** —
    cross-tile/cross-layer reuse via scratchpad management; the across-tile regime in a DNN context.
11. **CoSA, 2021 — Scheduling by Constrained Optimization for Spatial Accelerators** (X-ref) — the
    user's own scheduler family; how it encodes reuse (y variables) and traffic in the MILP.

Fallback if any is blocked: SNN ping-pong accelerator (2023), ZigZag (2021), Interstellar (2020).