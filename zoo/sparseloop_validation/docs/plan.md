# Sparseloop vs nocsim validation plan (RQ1: simulator validation)

Goal: show the paper's event-driven simulator (nocsim, spad arm) agrees with an established analytical model (Sparseloop/Timeloop + Accelergy) where agreement is expected, and characterize the gap where the analytical model's independence assumptions break. Three tiers, each attributing disagreement to exactly one cause.

## What is comparable

| Quantity | Comparable? | Notes |
|---|---|---|
| Per-level access counts (l1_weight_spad reads, GB reads/writes, DRAM traffic) | YES | the core of the validation |
| MAC / accumulate counts | YES | sparsity-dependent in Tier B/C |
| Energy | YES, only with the SAME per-event table on both sides | inject our table as a custom Accelergy ERT; energy agreement then reduces to counts agreement |
| Latency / cycles | RATIO ONLY | Sparseloop reports idealized pipeline bound; nocsim models stalls/burstiness; report nocsim/Sparseloop ratio, expected >= 1 |
| Prosperity ProSparsity detector | NO | product sparsity is not expressible as a gating/skipping SAF; validate memory system only or exclude with a stated reason |

Timestep handling: Sparseloop has no temporal dimension. Validate per-timestep workloads and scale by T, matching nocsim's per-timestep aggregation.

## Tier A - REMOVED (boss decision 2026-11-15)

Dense is neither tool's specification; dropped as a paper tier. Mapping pinning still applies to all tiers: constraint YAML to the EXACT schedule from `zoo/wt500_fig3cfg/outputs/manifest.json` (no mapspace search). An all-ones trace remains available as an internal debug check if Tier B disagrees, but produces no paper artifact.

Precedent (Sparseloop MICRO'22, Sec 6.3): its own validation has no dense tier either - SCNN per-component activities under a uniform density model (<1% error), Eyeriss V2 per-layer cycles under uniform vs actual-data density models (>99% total, up to 7% per-layer for uniform), DSTC latency-vs-density sweep (7.6% avg error). Figure style: metric vs density with both sources overlaid (their Fig 13), per-layer under two density models (their Fig 12).

## Tier B - statistical sparsity (validates sparsity-dependent count logic)

- Synthetic Bernoulli traces at density p in {0.05, 0.1, 0.3, 0.5, 0.9}, >= 3 seeds each, through nocsim.
- Sparseloop: skipping/gating SAFs with hypergeometric density model at the same p.
- Expectation: nocsim seed-mean inside the analytical prediction within a few percent.
- Acceptance bar: < 5% mean absolute error across densities.

## Tier C - real traces (characterizes the gap; produces a figure, not pass/fail)

- Sparseloop fed the measured per-layer density from the real spike traces.
- nocsim side: ZERO new runs - join against the campaign's existing Stage-A count checkpoints on (layer, arch, level).
- Expectation: systematic deviation from temporal/spatial spike correlation (Sparseloop assumes independence). Quantify per layer; present as the motivation for event-driven simulation.

## Scope and cost

- Architectures: 2 - one dense-ish flow (PTB) as the clean case, one operand-sparse (LoAS, skipping SAF) as the SAF case.
- Layers: ~10 representative, spanning the KH*KW/CIN/COUT/HO*WO range of the 113 kept layers.
- Runs: dense + 4 densities + Tier C ~= 100 Sparseloop invocations, seconds-to-minutes each, CPU-only. Fits on a login node; independent of the T99 campaign.

## Infrastructure

1. `accelergy-timeloop-infrastructure` (docker or pip install of timeloop + accelergy).
2. Arch YAML per SNN memory hierarchy: sizes/widths from `zoo/archx/zoo/snn_edp/hardware.json`.
3. Mapping-constraint YAML per schedule (from the manifest; exact mapping, not a search space).
4. Workload YAML per layer with density attributes.
5. Custom Accelergy ERT carrying our energy table (NG45 now, ASAP7 later) so both tools price identically.
6. Harness (~200 lines): run timeloop-model, parse `timeloop-model.stats.txt` per-level counts, join with nocsim count artifacts, emit per-tier error tables + Tier C scatter figure.

## Deliverables

- `validation/` tree: configs, harness, raw stats, joined CSVs.
- Paper artifacts: Tier A/B error table (RQ1), Tier C per-layer gap scatter + 2-3 sentence explanation.
- Precedent framing: mirrors how Sparseloop itself was validated (dense Timeloop agreement + statistical sparsity model checks).
