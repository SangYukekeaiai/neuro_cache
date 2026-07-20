# Phase 1 — Frontier: Cache-vs-Scratchpad & Locality/Reuse Profiling for DNN/SNN Accelerators

Date: 2026-07-18 | Families surveyed: **Computer architecture** + **ML/systems** (MLSys/ISPASS/IISWC).
The topic does **not** touch the Nature family, so that routing recipe was not run (see Limitations).

Merged Phase-1 corpus: **303 unique** records; **108** title-relevant to reuse/locality/cache/scratchpad/tiling/dataflow.

## Trending / active directions (3–5)

1. **Analytical reuse/locality models tied to the loop-nest + tiling** — data-centric mapping
   analyzers that compute per-tensor reuse and buffer traffic directly from the loop nest
   (MAESTRO, Timeloop, Interstellar, ZigZag, CoSA lineage). Framed in the prior survey for buffer
   *sizing*; here the interest is their reuse-quantification method itself.
2. **Scratchpad vs. hardware-managed cache as an explicit design choice** — the classic
   embedded-systems debate (Banakar scratchpad-vs-cache; "Balancing Scratchpad and Cache")
   resurfacing in accelerators, plus hybrid cache/scratchpad organizations (Compad 2023;
   "Partitioning and Data Mapping in Reconfigurable Cache and Scratchpad", 2017; reconfigurable
   cache/scratchpad FPGA prototypes).
3. **Reuse-distance / stack-distance profiling methodology** — trace-driven and analytical
   reuse-distance histograms ("Fast Modeling L2 Cache Reuse Distance Histograms", 2019; "Beyond
   Reuse Distance Analysis", 2013; "Modeling Shared Cache Performance using Reuse Distance", 2019;
   reuse-distance-driven cache-line management, 2021).
4. **Reuse-aware cacheability / replacement / prefetch for accelerators** — HyDRA (deadline &
   reuse-aware cacheability for HW accelerators, 2026); reuse-distance-aware replacement/copy-back;
   reuse prediction for last-level caches.
5. **SNN-specific accelerator memory hierarchies** — "A Scratchpad Spiking Neural Network
   Accelerator" (2024); DeVSA compressor-tree weight reuse (2026); SNN processors with explicit
   on-chip weight/membrane memories — directly relevant to the user's SNN cache question.

## Key frontier papers (≥10)

| Year | Title (trunc.) | Why it's on the frontier |
|------|----------------|--------------------------|
| 2018 | Understanding Reuse, Performance, and HW Cost of DNN Dataflows (MAESTRO) | Data-centric reuse quantification from the mapping; overlaps prior survey |
| 2019 | Fast Modeling L2 Cache Reuse Distance Histograms | Reuse-distance histogram modeling methodology |
| 2013 | Beyond Reuse Distance Analysis | Dynamic locality characterization beyond stack distance |
| 2019 | Modeling Shared Cache Performance using Reuse Distance | Reuse-distance to miss-rate for shared caches |
| 2017 | Partitioning & Data Mapping in Reconfigurable Cache and Scratchpad Architectures | Cache-vs-scratchpad partitioning decision |
| 2023 | Compad: Heterogeneous Cache-Scratchpad CPU with Data Layout Compaction | Hybrid cache+scratchpad organization |
| 2024 | A Scratchpad Spiking Neural Network Accelerator | SNN accelerator scratchpad memory (direct analog to user's node buffer) |
| 2026 | HyDRA: Deadline and Reuse-Aware Cacheability for Hardware Accelerators | Reuse-aware cache policy for accelerators |
| 2025 | HARP: Taxonomy for Heterogeneous/Hierarchical Processors for Mixed-reuse Workloads | Reuse-regime taxonomy |
| 2003 | Scratchpad memory: a design alternative for cache on-chip memory (Banakar) | Seminal scratchpad-vs-cache tradeoff |
| 2026 | DeVSA: Density-Efficient Vector SNN Accelerator Exploiting Reuse | SNN weight-reuse exploitation |
| 2025 | FactorFlow: Mapping GEMMs on Spatial Architectures (adaptive) | Mapping/reuse search, CoSA-family |

See `search_log.md` for the full query audit trail; `_merged.jsonl` holds all 303 records.
