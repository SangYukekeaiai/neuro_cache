# Figure 1 energy profiling

Figure 1 compares single-node PTB, LoAS and GustavSNN on all twelve kept B09 VGG16 convolution layers, samples 000–009. Only weight scratchpad capacity varies: 128 KiB, 256 KiB, 512 KiB and 1 MiB. The ideal bar uses deduplicated unique-weight reads and fills at 256 KiB and its own runtime bracket. Its height is the midpoint energy; asymmetric whiskers cover the runtime bounds and sample uncertainty. [The full dedup audit](outputs/self_checks/ideal_dedup_audit/verification.json) confirms that all three architectures have the same absolute ideal off-chip weight energy; their normalized heights use different baseline denominators.

- [PDF](outputs/fig1_energy_profiling.pdf) · [PNG](outputs/fig1_energy_profiling.png) · [caption](outputs/caption.txt)
- [Bar/segment means and 95% CI](outputs/fig1_numbers.csv) · [whole-model samples](outputs/whole_model_samples.csv) · [layer rows](outputs/layer_energy.csv)
- [Energy validation](outputs/energy_validation.json) · [figure provenance](outputs/figure_provenance.json)

There are 1,440 native/NoC cases and price-free archx checkpoints, 1,800 priced layer rows including ideal, and 150 complete whole-model sample groups. All 15 bars contain twelve layers and ten samples. The saved SHA inventories verify 11,520 native files and 4,320 archx files unchanged by pricing.

Logic prices are **ASAP7 Genus synthesis-only estimates**, using the nine measured basic modules, linear width/depth interpolation and explicit compositions. Reports have unconstrained I/O and mixed default library declarations (AO/INVBUF/OA/SEQ 0.77V/0C; SIMPLE 0.70V/25C). No post-route parasitics or uniform-TT/end-to-end timing claim is made. SRAM uses the FN-CACTI 7nm/0.7V extrapolated physical model; commodity DDR4/IO retain the pinned CACTI7 model. The full table hash is in [table_manifest.json](archx_config/table_manifest.json) and the caption. These are not final post-route prices.

## Hardware and input contracts

LoAS has sixteen COUT PEs; PTB has eight; GustavSNN has one HO stream and eight COUT lanes, one detector and no two-stream merger. [The inventory](docs/energy_model.md) and [architecture manifest](configs/arch_manifest.json) record every physical instance and geometry.

All twelve configurations have fixed 256 KiB psum and 512 KiB vmem capacity. They cover the approved 128/256 KiB sizing envelope with 25% margin and power-of-two rounding; one-pixel GustavSNN visits use less simultaneous state without resizing these provisions. They are capacity/feasibility provisions, charged once for area/leakage with **zero added dynamic SRAM accesses**. State activity remains in native registers/LIF/RFs. Fixed inventory does not imply fixed leakage energy when duration varies. No GB exists: the required NoCLevel schema slot is inert and every case has zero GB events.

The schedule constructor enforces HO→WO→COUT for LoAS/PTB, with the complete T batch resident inside each visit; GustavSNN uses COUT→HO→WO→T with one pixel/timestep per visit and a resident weight tile across pixel/time steps. [The twelve manifests](outputs/manifest/index.json) contain 144 native-bridge-compatible schedules. [Schema and report checks](docs/schema_and_report_checks.md) record the exact contracts. The classifier is excluded; no convolution is dropped for state-buffer capacity.

Inputs under `/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_vgg16_T4_n500/` are read-only. All generated files are in this directory; the shared simulator and vendored archx are imported without edits. The retained PTB/LoAS counts come from `fig1-counts` arrays 1147750/1147751; GustavSNN counts come from array 1149283 with the decoded T-innermost traversal. T99 retained state is untouched. [Submission](stokes/submission.json), [preflight](stokes/preflight.json), [accounting](stokes/accounting.txt), and [fetch verification](outputs/count_fetch_verification.json) retain evidence. [The timestep recount](outputs/self_checks/temporal_order/REPORT.md) records all 480 cases, unique-weight and compulsory-traffic gates, and the measured segment deltas.

## Reproduce from retained counts

Run from the repository root, with all BLAS/OMP thread counts set to one, `PYTHONDONTWRITEBYTECODE=1` and `ARCHX_DISABLE_PERFORMANCE_CACHE=1`. The `fig12-archx` environment handles the backend; the existing `gurobi` environment supplies Matplotlib for plotting only (no solver/license invocation). Gill Sans is unavailable; the figure uses Cantarell with DejaVu Sans digits.

```bash
# Stage A: counter files -> saved graph; no table argument or table read.
conda run -n fig12-archx python -B zoo/fig1_energy_profiling/archx_config/count.py

# Stage B: saved graphs + table only; simulator inputs are not opened.
conda run -n fig12-archx python -B zoo/fig1_energy_profiling/archx_config/price.py \
  --table zoo/fig1_energy_profiling/archx_config/energy_table_asap7_syn.json

conda run -n fig12-archx python -B zoo/fig1_energy_profiling/src/collect_whole_run_bounds.py
MPLCONFIGDIR=zoo/fig1_energy_profiling/outputs/mplconfig \
  conda run -n gurobi python -B zoo/fig1_energy_profiling/src/plot_energy.py
```

Both stages also accept a single-case/checkpoint path and output directory (`--help`). A synthesis/table update runs Stage B only. Tests execute counting with the table absent, pricing with simulator-input access blocked and count callbacks forbidden, and a changed-table reprice with byte-identical count checkpoints. The retained fixed-time pricing test checks the source dynamic estimate. The displayed whole-run ideal is computed by `collect_whole_run_bounds.py`: native compute is fixed, duration is bracketed, and leakage follows that bracket. [The pre-execution analysis](outputs/self_checks/whole_run_ideal/PRE_EXECUTION.md) supplies coverage, native work/stalls, and per-case bounds; [the fixed-time figure archive](outputs/archive/fixed_time_before_whole_run.json) remains available for comparison.

```bash
PYTHONPATH=src:. conda run -n fig12-archx python -B -m pytest -q \
  zoo/fig1_energy_profiling/src \
  --basetemp=zoo/fig1_energy_profiling/outputs/tmp/tests -p no:cacheprovider
```
