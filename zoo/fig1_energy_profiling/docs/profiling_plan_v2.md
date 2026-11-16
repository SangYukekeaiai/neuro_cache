# Figure 1 profiling specification

The executable commands and artifact index are in [README.md](../README.md). All writes stay under `zoo/fig1_energy_profiling/`; shared performance-model, campaign and vendored archx files are read-only.

## Configuration

| Item | Definition |
|---|---|
| Workload | B09 `loas_vgg16_T4_n500`, twelve kept convolutions, samples 000–009 |
| Node scope | One node; inert NoCLevel schema slot, no GB inventory/events |
| COUT PEs | LoAS 16; PTB 8; GustavSNN 8 with one HO stream |
| Weight scratchpad | 128/256/512 KiB and 1 MiB |
| Fixed state capacity | Psum 256 KiB; vmem 512 KiB, identical across all twelve designs |
| State activity | Native register/LIF/RF work; fixed SRAM provisions add area/leakage only, zero dynamic accesses |
| Traversal | LoAS/PTB HO→WO→COUT with T resident; GustavSNN COUT→HO→WO→T, weights retained across pixel/time visits |
| Timing | Native/NoC cycles at 500 MHz; ideal retains baseline time |
| Energy | Local ASAP7 Genus synthesis/interpolation/composition bank, FN-CACTI SRAM, pinned commodity DDR4/IO |

The fixed state capacities cover maxima of 128/256 KiB plus 25% margin and power-of-two rounding. They do not change weight storage. The exact inventory is in [energy_model.md](energy_model.md) and `configs/arch_manifest.json`.

## Execution and self-checks

1. **Construct schedules.** The local analytic constructor expresses the approved loop order directly, then uses the shared decoder and native bridge validator. `outputs/manifest/index.json` identifies twelve manifests and 144 schedules. Every kept layer is feasible; there is no pixel-blocking workaround.
2. **Count on Stokes.** Separate `fig1-counts` arrays run 1,440 native/NoC cases. Each case verifies zero GB/inter-node activity, exact schedule-derived weight traffic, and native unique weight addresses against an independent input-support oracle. Seven artifacts and a SHA receipt are committed before transient scratch deletion.
3. **Compile/execute archx Stage A.** `archx_config/count.py` compiles the local AGraph description and saves per-case counted, zero-metric event graphs. Only counter files and price-independent hardware/source fingerprints enter this stage.
4. **Apply Stage B prices.** `archx_config/price.py` reads saved graphs and the supplied table, with no simulator-input reads or performance callbacks. Every operation is checked against count × price; physical inventory is charged once. All 4,320 Stage A files remain byte-identical.
5. **Ideal at 256 KiB.** Union the weight words touched by any nonzero spike across all timesteps, pixels and tiles. Substitute only DDR4 reads/IO and implied local fills. Every other count, inventory and duration stays fixed. Duplicate touches never enter the ideal. Absolute ideal weight energy is identical across the three architectures; normalized heights differ because baseline denominators differ.
6. **Aggregate and render.** Sum all twelve layers within each sample. Report ten-sample means and Student-t 95% CI, normalized by each architecture's fixed mean 256 KiB baseline. Fifteen bars contain four segments: compute/local logic, local SRAM, off-chip weights, and off-chip other (standing DDR4/IO leakage). No partial bar or missing layer is accepted.

The review gates are self-checks recorded in `outputs/self_checks/`, `outputs/count_validation.json`, `outputs/energy_validation.json`, and `outputs/figure_provenance.json`. The unique-weight audit checks all 360 ideal cases by an independent active-coordinate method. Its before snapshot and zero before/after energy delta are retained.

## Price caveats

The Genus reports have no post-route parasitics and unconstrained I/O. Default library declarations are mixed: AO/INVBUF/OA/SEQ 0.77V/0C and SIMPLE 0.70V/25C. They do not establish a uniform TT corner or end-to-end 500 MHz signoff. Linear width/depth interpolation and additive composition are estimates. SRAM uses the existing FN-CACTI 7nm/0.7V extrapolated physical model; DDR4/IO are commodity-memory models. These caveats are carried into every priced row and the figure.

## Outputs

`outputs/fig1_energy_profiling.pdf`, `.png`, `fig1_numbers.csv`, `whole_model_samples.csv`, `layer_energy.csv`, and `caption.txt`. The local table is `archx_config/energy_table_asap7_syn.json`, with its full hash and sources in `archx_config/table_manifest.json`. Raw counts, counted graphs, priced graphs, reports and provenance remain available for inspection.
