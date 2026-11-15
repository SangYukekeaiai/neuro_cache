# NanGate45 interim results

NanGate45-characterized prices applied to a 7nm/500MHz performance model; interim until ASAP7 synthesis.

All 559 feasible kept cases are priced: 1,677 rows, 117 complete whole-model groups, and three hatched Prosperity A08 groups (6/12 layers). Missing layers never contribute partial whole-model bars. The energy and EDP figures include the caveat and full table SHA. Latency and all event counts are identical to the [sample-0 results](../results_20261114/README.md).

- Energy: [PDF](stage2/figures/model_energy_overview_ng45.pdf), [PNG](stage2/figures/model_energy_overview_ng45.png).
- EDP: [PDF](stage2/figures/model_edp_overview_ng45.pdf), [PNG](stage2/figures/model_edp_overview_ng45.png).
- [Per-layer results](stage2/results_ng45.csv), [whole-model totals](stage2/whole_model_ng45.csv), [coverage](stage2/coverage.json).
- [Independent arithmetic and unchanged-count checks](analysis/validation.json), [full module shares](analysis/full_module_energy.csv), [top three per architecture and arm](analysis/top3.csv).
- [Pricing sources](../../../archx/zoo/snn_edp/characterization/NANGATE45.md), [substitution manifest](../../../archx/zoo/snn_edp/characterization/nangate45_substitutions.json).

Table SHA256: `2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3`. The pinned table is retained in `stage2/`. Default and dummy tables remain unchanged and separately selectable. Nine excluded prefetch operations retain their counts and zero prices.

The 45nm memory models use exact original geometries at ITRS-LOP 0.7V/360K. Some report fmax below 500MHz; no performance timing is inferred from these prices. Logic uses explicit primitive neighbors and scaling. DDR4/IO remain the pinned off-chip rows. [All assumptions](../../../archx/zoo/snn_edp/characterization/nangate45_substitutions.json) accompany the table.

Slurm job 1140673 completed in 261 seconds (4m21s); pricing and collection took 248.749 seconds. Stage B preserved all 34,081 Stage-A files byte-identically, including the identical T97 inventory digest `fd60ecbfb58e9e35ec20ba8a8e0594403c841ac91e1021d49dc4b04793fe4093`. No simulator or count model ran. Independent checks cover all 43,072 terms with exactly zero term-energy error; maximum relative arithmetic error is 4.38e-16. All 117 complete model sums and EDP compositions match exactly.

Top module shares below sum dynamic and standing leakage over completed layer cases across all three arms, rather than averaging percentages or using partial whole-model bars. SpinalFlow/PTB/LoAS/GustavSNN each cover 113 cases; Prosperity covers 107. Per-arm shares and dynamic/leakage splits are in [top3.csv](analysis/top3.csv).

| Architecture | Largest | Second | Third |
| --- | --- | --- | --- |
| spinalflow | `shared.ddr4` 61.13% | `cache.l1` 13.11% | `shared.ddr4_io` 11.02% |
| ptb | `shared.ddr4` 60.55% | `shared.ddr4_io` 11.65% | `cache.l1` 11.47% |
| loas | `shared.ddr4` 64.16% | `shared.ddr4_io` 18.83% | `cache.l1` 6.48% |
| gustavsnn | `shared.ddr4` 59.00% | `cache.l1` 13.39% | `shared.ddr4_io` 10.22% |
| prosperity | `shared.ddr4` 42.65% | `shared.gb` 11.89% | `shared.router` 10.60% |

[artifact_sha256.json](artifact_sha256.json) indexes every delivered result file except itself. Per-case priced products remain on Stokes under `/lustre/fs1/home/ya867177/snn_edp_stokes_20261114/stage2_ng45/cases/`; the original count checkpoints remain under `stage1/cases/`. [Submission sources](submission.json) and [batch accounting](accounting.tsv) identify the execution.
