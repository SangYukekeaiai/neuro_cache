# Pricing-policy validation

The nine operations below carry `excluded by decision (prefetch control)` in both tables. All three metrics are zero; the operations remain counted. This is a Stage-B policy, not synthesized zero-cost hardware.

## Per-operation price delta

Each cell shows before → after. Null means an unavailable default price; its numeric contribution was already zero. Leakage and area are per physical instance. Metadata read/write share one inventory and are deducted once; L1 and L2 extra tag-probe inventories are already zero.

| Operation | Default nJ/access | Dummy nJ/access | Default mW / mm² | Dummy mW / mm² |
|---|---:|---:|---|---|
| `cache.next_access_logic.step` | null → 0 | 0.00026687384814 → 0 | null / null → 0 / 0 | 0.000102128623853 / 0.0031719765 → 0 / 0 |
| `cache.distance_logic.step` | null → 0 | 0.0003449856 → 0 | null / null → 0 / 0 | 0.00012928 / 0.003105408 → 0 / 0 |
| `cache.next_access_state.rmw` | null → 0 | 6.46464e-05 → 0 | null / null → 0 / 0 | 8e-06 / 0.000246336 → 0 / 0 |
| `cache.distance_metadata.read` | 0.00155178 → 0 | 0.00155178 → 0 | 4.62287 / 0.018883581232 → 0 / 0 | 4.62287 / 0.018883581232 → 0 / 0 |
| `cache.distance_metadata.write` | 0.00141797 → 0 | 0.00141797 → 0 | 4.62287 / 0.018883581232 → 0 / 0 | 4.62287 / 0.018883581232 → 0 / 0 |
| `cache.l1_tags.read` | 0.000298219 → 0 | 0.000298219 → 0 | 0.0789755 / 0.0015063556635 → 0 / 0 | 0.0789755 / 0.0015063556635 → 0 / 0 |
| `cache.next_line_l1.add` | null → 0 | 4.31232e-05 → 0 | null / null → 0 / 0 | 1.616e-05 / 0.000388176 → 0 / 0 |
| `cache.next_line_l2.add` | null → 0 | 4.31232e-05 → 0 | null / null → 0 / 0 | 1.616e-05 / 0.000388176 → 0 / 0 |
| `cache.l2_tags.read` | 0.00179353 → 0 | 0.00179353 → 0 | 2.28963 / 0.011481977862 → 0 / 0 | 2.28963 / 0.011481977862 → 0 / 0 |

The 30-row [machine-readable comparison](t95_validation.json) records each affected event count and its exact before/after dynamic contribution for both tables, plus deduplicated leakage, area and EDP deltas. Every other breakdown term, every count/expression, all cycles, core energy and chain energy are unchanged. All five spad rows are numerically identical.

## Default-table fixture deltas

Signed differences, after minus before, in nJ. All cacheA cases remove the same 0.018883581232 mm² metadata inventory; cacheB area is unchanged.

| Architecture | cacheA dynamic Δ | cacheA leakage Δ | cacheB dynamic Δ | cacheB leakage Δ |
|---|---:|---:|---:|---:|
| spinalflow | -16820.3830628 | -2666.83199986 | -2574.55896175 | -0 |
| ptb | -5608.77676179 | -954.08640208 | -881.97527659 | -0 |
| loas | -5608.77676179 | -916.3452914 | -881.97527659 | -0 |
| gustavsnn | -33509.650131 | -6644.37708508 | -5150.74032639 | -0 |
| prosperity | -2997.36335132 | -680.69911602 | -458.59332606 | -0 |

## Stage separation and clocks

The exclusion-only test repriced saved checkpoints with case-file access, count calls and subprocess calls forbidden: 30 rows / 772 terms checked, all 305 counted-checkpoint files byte-identical. Changing table prices therefore requires only Stage B.

The independent query-clock normalization changes `hardware.json` metadata, and therefore its Stage-A fingerprint. The five fixtures were refreshed for that metadata change; all 386 operation counts/expressions, cycles, input provenance and category rollups are identical. Final prices exactly equal the exclusion-only outputs. No campaign simulation was run.

FN-CACTI: 12 unique SRAM/cache geometries, 24 separate native queries. At 100 versus 500 MHz, read/write energy, leakage, area and generated configuration bytes match exactly. Query frequency is output metadata, not a clock-optimization constraint. The minimum reported maximum frequency is 646.395697590 MHz; this is an analytical estimate, not physical timing closure. The DDR4 query metadata is also removed before its native invocation; the separate 1600 MHz bus setting and pinned DDR4/IO prices stay unchanged. System time remains cycles / 500 MHz.

L1/L2 array writes retain all prefetch-fill counts. L1/L2 tag prefetch probes and both cacheB next-line adders are among the nine excluded rows.

## Artifacts

- Default table SHA256: `8c3589272e2a68dc9b01847be61f2076fb5dbb84eee7a4dc582671da9ff79942`.
- Dummy table SHA256: `892e6e2c77b920232f0db0caf81fbd69eb35925f825750e9e1f8cb333c78cbcb`.
- [Frequency measurements and native report paths](cacti_frequency.json).
- [Prior per-row prices and inventory](prefetch_control_exclusion.json).
- [Fixture validation](../validation.json): 15 rows / 386 terms; zero term error, maximum total relative error 2.692250735113692e-16.
- Before archive: `/u/yyu9/peon-snapshots/energy-performance-estimation/T95-20261114-pricing-policy/before.tar.gz`; SHA256 `88a010ff1d3da31c797250904f87191ca21649717cecb075e9a913bf2d14537e`.

## L2-tag exclusion contribution

Compared with the eight-row policy, only `cache.l2_tags.read` dynamic energy and its EDP contribution change. Leakage, area, latency and all counts are identical. Signed dynamic deltas in nJ:

| Architecture | cacheA Δ | cacheB Δ |
|---|---:|---:|
| spinalflow | -417.64498286 | -1.15862038 |
| ptb | -0.91828736 | -1.15862038 |
| loas | -0.91828736 | -1.15862038 |
| gustavsnn | -723.71805148 | -4.13229312 |
| prosperity | -85.27876444 | -1.22677452 |

All five spad deltas are zero. Geometry notes remain under `geometry_assumption` on excluded table rows; archived pre-exclusion rows retain the full original records.
