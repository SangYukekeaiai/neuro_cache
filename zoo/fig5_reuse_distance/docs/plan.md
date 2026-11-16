# Figure 5 (fig:reuse-distance) generation plan - FOR BOSS REVIEW, NOT IMPLEMENTED

Paper target: `2027_ASPLOS_neuro_cache/src/04_motivation.tex`, `\label{fig:reuse-distance}` ("Distribution of reuse distance", caption flagged `need update`). Position: after the four locality patterns (Fig 4), before "Why conventional cache fails?".

## What the figure must show

The spike-driven weight request stream exhibits concentrated, cache-capturable locality: a large fraction of re-references happen within a reuse distance smaller than practical cache capacities. This is the empirical bridge from the locality taxonomy to the cache proposal - and it quantifies which of TITL/MITL/NISL actually dominate.

## Definition (the quantity plotted)

- Stream: the demand weight-request sequence per case (arch, layer, sample) - EXACTLY the request stream cachesim consumes (the input trace the cache arms see), so the figure and the simulator describe the same object. No cache model involved; this is a property of the stream itself.
- Reuse distance = stack distance in UNIQUE 64 B weight lines between successive references to the same line (Mattson; cold first references binned as infinite).
- Granularity 64 B lines (matches the cache configs in the paper: 16 KB 8-way L1, 512 KB 16-way L2, 64 B lines).

## Presentation (proposed)

- CDF of reuse distance (x = distance in lines, log scale; y = fraction of non-cold requests), one curve per architecture, one panel (or one benchmark per panel if curves differ qualitatively).
- Vertical capacity markers: L1 = 256 lines (16 KB) and L2 = 8192 lines (512 KB). The reader sees directly "X% of reuses fit in L1, Y% in L2".
- Cold-miss fraction reported in the legend or a small inset table (it is the compulsory-traffic floor, ties to Figure 1's ideal bar).
- Style: same family as fig1 (Tol palette, CDF lines, no stacked bars).

## Configuration knobs (proposed values - boss confirms/overrides)

| # | Knob | Proposed | Notes |
|---|---|---|---|
| C1 | Architectures | all 5 (spinalflow, ptb, loas, gustavsnn, prosperity) | streams already exist for all; cheap once traces are read |
| C2 | Benchmark(s) | loas_vgg16 (consistency with Fig 1) + spikingLM (the attention counterpoint) | 1-2 curves panels; more benchmarks = appendix |
| C3 | Samples | 10 (000-009) | distance CDFs are stable across samples; CI band optional |
| C4 | Schedule | the CAMPAIGN schedules (multi-node, as simulated in Fig 12) | this figure motivates the cache in OUR system context, unlike Fig 1's single-node baselines - boss please confirm this scope choice |
| C5 | Stream scope | per-case streams; aggregate CDF = request-weighted union across layers | per-layer small-multiples available as appendix |
| C6 | Line size | 64 B | matches cache configs |
| C7 | Cold references | excluded from CDF, reported as a separate fraction | standard practice |
| C8 | Data source | existing campaign traces/checkpoints (zero new simulation) if the cachesim input streams are recoverable from retained artifacts; otherwise regenerate streams for C1-C3 only (~50 small gen runs) | Stage-0 of the pipeline determines which |

## Pipeline (steps; gates only if something surprises)

1. Stage 0 - inventory: determine whether the per-case weight request streams are recoverable from fetched/retained artifacts (trace gen outputs) or need regeneration; report the cheaper path.
2. Stream extraction: per case, the ordered 64 B-line request sequence.
3. Stack-distance computation: tree-based Mattson (O(N log N)); per-case histograms -> request-weighted aggregate per (arch, benchmark).
4. Validation: tiny synthetic stream with known distances; plus one case cross-checked against cachesim's miss counts at 2 capacities (stack-distance CDF must predict LRU miss ratio at those capacities - a strong end-to-end check tying Fig 5 to the simulator).
5. Render: CDF panel(s) with capacity markers; numbers CSV alongside.
6. Paper integration after boss review: PDF into fig/, caption written (definition + stream provenance + capacity markers), `need update` resolved.

## Folder (decoupled, same convention as fig1)

```
zoo/fig5_reuse_distance/
  docs/plan.md (this)   src/   outputs/{histograms,figure}   configs/
```

No writes to fig12_edp/, wt500_fig3cfg/, fig1_energy_profiling/, or vendored archx.

## Effort estimate

Stage 0 ~1 h; extraction+distance ~2-4 h compute for ~100-150 case streams (login-scale); validation + render ~2 h. No cluster dependency unless regeneration is needed (then the ~50 gen runs go wherever fig1's fan-out runs).

## Open question for the boss (the one real scope decision)

C4: this plan uses the CAMPAIGN (multi-node, scheduled) request streams, because Figure 5 motivates the cache inside our system. The alternative - single-node streams a la Figure 1 - would make Figs 1 and 5 share context but would measure locality of the baselines rather than of the system the cache serves. Which context do you want?
