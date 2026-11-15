# Stokes sample-0 results

All 559 kept feasible cases completed and produced 1,677 priced rows. Cache B uses `next_line` at both levels. The energy and EDP values use **dummy prices**, not characterized estimates or lower bounds.

| Architecture | Completed feasible cases | Nominal kept layers | Complete model/arm groups |
| --- | ---: | ---: | ---: |
| spinalflow | 113 | 113 | 24/24 |
| ptb | 113 | 113 | 24/24 |
| loas | 113 | 113 | 24/24 |
| gustavsnn | 113 | 113 | 24/24 |
| prosperity | 107 | 113 | 21/24 |

The six infeasible Prosperity A08 layers give that architecture 6/12 layers in the benchmark. Its three whole-model totals are blank and hatched, rather than computed from the partial layer set. Every other whole-model group is complete.

- [Latency overview PDF](stage2/figures/model_latency_overview.pdf) and [PNG](stage2/figures/model_latency_overview.png): count-derived, independent of the energy table.
- [Energy overview PDF](stage2/figures/model_energy_overview.pdf) and [PNG](stage2/figures/model_energy_overview.png): dummy prices with table SHA in the caption.
- [EDP overview PDF](stage2/figures/model_edp_overview.pdf) and [PNG](stage2/figures/model_edp_overview.png).
- [Eight-page latency/energy/EDP PDF](stage2/figures/whole_model.pdf).
- [Separate sum-of-layer-EDP PDF](stage2/figures/sum_layer_edp.pdf).
- [Per-layer results.csv](stage2/results.csv) and [whole_model.csv](stage2/whole_model.csv).
- [All 559 case outcomes](stage1/all_cases.csv), [successes](stage1/success.csv), [failures (empty)](stage1/fail.csv), and [manual checkpoint paths](stage1/manual_probes.json).

Stage 1 took 2535.216 seconds (42m15s), including startup recovery and retries. The Stage-2 batch took 631 seconds (10m31s), including checkpoint validation, pricing, and plotting; pricing and collection alone took 398.024 seconds. First submission through the rendered figures took 3165.682 seconds (52m46s).

Dummy table SHA256: `892e6e2c77b920232f0db0caf81fbd69eb35925f825750e9e1f8cb333c78cbcb`. The exact table bytes are retained as `stage2/dummy_table_892e6e2c77b920232f0db0caf81fbd69eb35925f825750e9e1f8cb333c78cbcb.json`.

Stage B reused all 34,081 checkpoint files byte-identically. [Independent arithmetic checks](independent_validation.json) recompute layer EDP, every whole-model sum, both EDP compositions, core consistency across arms, and all nine zero exclusions; maximum relative error is 3.42e-16. Whole-model EDP is `(sum E) × (sum T)`; `sum_layer_EDP_nJ_s` is a separate statistic.

The remote source is `/lustre/fs1/home/ya867177/snn_edp_stokes_20261114/`; complete per-case Stage-A artifacts remain under `stage1/cases/`, and priced per-case products under `stage2/cases/`. Local CSVs, figures, coverage and hash records are copies of the remote outputs. No Stage-A artifact or simulator input was changed by pricing.

Count-checkpoint examples (Stokes):

- small_prosperity: `/lustre/fs1/home/ya867177/snn_edp_stokes_20261114/stage1/cases/prosperity/A04/sdt_2_512_cifar100_T4_n500/layer_14_block_1_attn_proj_conv/sample_00000/counts`
- large_historical_spinalflow: `/lustre/fs1/home/ya867177/snn_edp_stokes_20261114/stage1/cases/spinalflow/C01/sma_azo_vgg_cifar10_dvs_T10_n500/layer_01_core_block2_0_0/sample_00000/counts`
- small_other_arch: `/lustre/fs1/home/ya867177/snn_edp_stokes_20261114/stage1/cases/ptb/A04/sdt_2_512_cifar100_T4_n500/layer_14_block_1_attn_proj_conv/sample_00000/counts`

Run commands and resource policy: [runner README](../README.md). The two stages remain separately executable. Licensed synthesis is held; these figures do not claim synthesized prices.

The eight files under `stage2_ng45/` are a **manager pull from stokes stage2_ng45 root**, retained for immediate viewing. Their bytes match the [canonical NanGate45 report](../results_ng45_20261114/README.md), which includes the independent analysis and full provenance. These interim-price copies do not replace the dummy-price products under `stage2/`.
