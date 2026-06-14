# SNN CoSA Scripts

All scripts run from the **project root** with the `cosa_snn` conda environment active:

```bash
conda activate cosa_snn
python scripts/<script>.py [options]
```

---

## Workflow Overview

```
1. Generate configs          2. Run sweeps               3. Analyse results
─────────────────────        ────────────────────        ──────────────────────
generate_arch_sweep.py  ──►  run_profiling_sweep.py ──► analyze_profiling_sweep.py
generate_workload_sweep.py►  run_subset_sweep.py    ──► analyze_shallow_sweep.py
                             run_full_sweep.py           analyze_mode_rates.py
                                                         deep_temporal_analysis.py
                                                         visualize_best_schedule.py

Weight calibration (standalone):
  find_weights.py
  sweep_weights.py
```

---

## 1. Config Generators

### `generate_arch_sweep.py`

Generates all hardware architecture YAML configs for the sweep space.

**Sweep axes:**
- Nodes: 16, 32, 64, 128, 256, 512, 1024
- GB (L2): 64, 128, 256, 512, 1024, 2048, 4096 KB
- L1: 4, 8, 16, 32 KB
- PEs/node: 16, 32, 64, 128
- Memory split: `w30_p1_v1` (weight-heavy) or `w24_p4_v4` (balanced)

Total: **1568 configs** written to `configs/arch/sweep/<nodes>/<gb>/<l1>/<pe>/<split>.yaml`.

```bash
python scripts/generate_arch_sweep.py                    # default output dir
python scripts/generate_arch_sweep.py --out-dir <path>   # custom output dir
```

> **Warning:** rewrites the output directory from scratch on every run.

---

### `generate_workload_sweep.py`

Generates workload YAML configs for ResNet-19, VGG-16, ResNet-34, and ResNet-50,
expanded over T values.

**Sweep axes:**
- Networks: resnet19, vgg16, resnet34, resnet50
- T: 4, 8, 16, 32, 64, 128

Output: `configs/workloads/generated/<network>/T<t>/<layer>.yaml`

```bash
python scripts/generate_workload_sweep.py                    # default output
python scripts/generate_workload_sweep.py --out-root <path>  # custom output
python scripts/generate_workload_sweep.py --clean            # wipe and regenerate
```

---

## 2. Sweep Runners

All sweep runners support `--dry-run` (print plan, no Gurobi solves) and
`--jobs N` (parallel subprocesses). Already-solved pairs are skipped
automatically — just rerun the same command to resume.

### `run_profiling_sweep.py`

Profiles all unique workload shapes at a **fixed hardware config** across all 11
traffic modes.

- **Fixed arch:** nodes=256, L1=8 KB, L2=256 KB, PE=64, split=w30:vmem1:psum1
- **Workloads:** 45 unique shapes (deduplicated from resnet19/vgg16/resnet34/resnet50/GEMM) × T ∈ {4, 32, 128} = **135 workloads**
- **Per pair:** 11 modes × 1 arch = 1485 Gurobi solves total

Output per workload: `outputs/profiling_sweep/<wl_key>.txt`
Summary: `outputs/profiling_sweep/summary.txt`

```bash
python scripts/run_profiling_sweep.py                  # serial
python scripts/run_profiling_sweep.py --jobs 8         # parallel
python scripts/run_profiling_sweep.py --dry-run        # plan only
python scripts/run_profiling_sweep.py --time-limit 60  # 60s per mode
```

---

### `run_subset_sweep.py`

Runs **all arch configs × 2 representative workloads** (shallow and deep conv).

- **Workloads:** resnet19/conv1 and vgg16/conv5_3, each at T ∈ {4, 32, 128}
- **Arch:** all 1568 configs from `configs/arch/sweep/`
- **Total:** 9408 pairs × 11 modes

Output per pair: `outputs/subset_sweep/<wl_label>__<arch_key>.txt`
Summary: `outputs/subset_sweep/summary.txt`

```bash
python scripts/run_subset_sweep.py                  # serial
python scripts/run_subset_sweep.py --jobs 8         # parallel
python scripts/run_subset_sweep.py --dry-run        # plan only
python scripts/run_subset_sweep.py --time-limit 30  # 30s per mode (default)
```

---

### `run_full_sweep.py`

Runs **all generated arch configs × all generated workload configs** — the
complete cross-product sweep.

- **Arch:** `configs/arch/sweep/**/*.yaml` (1568 files)
- **Workloads:** `configs/workloads/generated/**/*.yaml` (690 files)
- **Total:** ~1.08M pairs (run in batches with `--skip-existing`)

Results written as JSONL to `outputs/full_sweep/results.jsonl` (one JSON object
per pair), which supports incremental resumption.

```bash
python scripts/run_full_sweep.py                          # serial
python scripts/run_full_sweep.py --jobs 8                 # parallel
python scripts/run_full_sweep.py --skip-existing          # resume
python scripts/run_full_sweep.py --dry-run                # plan only
python scripts/run_full_sweep.py --w-u 0.1 --w-tr 1.0 --w-dl 10.0
python scripts/run_full_sweep.py --arch-dir <path> --wl-dir <path>
```

---

## 3. Analysis Scripts

All analysis scripts read from `outputs/` and write figures or tables. Run
after the corresponding sweep is complete.

### `analyze_profiling_sweep.py`

Analyses `outputs/profiling_sweep/*.txt` — the fixed-arch workload sweep.

**Questions answered:**
- Which mode wins per workload dimension (CIN, COUT, HO×WO, KH×KW, T)?
- What spatial split patterns appear per winning mode?

**Outputs:**
- `outputs/profiling_sweep/mode_rate_tables.md` — per-dimension win-rate tables
- `outputs/profiling_sweep/figures/sp_pie.pdf` — spatial-split pie charts per mode

```bash
python scripts/analyze_profiling_sweep.py
```

---

### `analyze_shallow_sweep.py`

Analyses `outputs/subset_sweep/` — both shallow and deep conv across all arch
configs. Generates a 3-row figure covering phase diagrams, T-placement, and
memory utilization.

**Questions answered:**
- Where does the mode phase boundary lie in (GB size × node count) space?
- How is T tiled across the memory hierarchy per mode?
- What is the weight-to-total footprint ratio for each mode?

**Outputs:**
- `outputs/figures/sweep_analysis.pdf` (default) — 6-panel figure

```bash
python scripts/analyze_shallow_sweep.py
python scripts/analyze_shallow_sweep.py --out outputs/figures/my_analysis.pdf
```

---

### `analyze_mode_rates.py`

Analyses `outputs/subset_sweep/` — computes for each hardware parameter value the
fraction of configs that choose each mode.

**Questions answered:**
- Does changing nodes / GB / L1 / PE / split systematically shift mode preference?
- Which (param, value) combinations strongly predict a specific mode?

**Outputs:**
- `outputs/mode_rate_tables.md` — markdown rate tables with bold highlighting
- `outputs/figures/mode_rate_heatmaps.pdf` — 2-D heatmap panels

```bash
python scripts/analyze_mode_rates.py
```

---

### `deep_temporal_analysis.py`

Deep-dives into the `deep_conv` subset sweep results. Three analyses:

1. **Within-mode conditional distributions** — for each mode bucket, which hardware
   parameter values are over/under-represented?
2. **GB-level temporal tiling** — contrasts `both_dram_oooo` (T at GB level) vs
   `psum_dram_ootk` (T at DRAM level)
3. **Minimal decisive combinations** — smallest hardware parameter sets that fully
   determine which mode wins

**Output:** `outputs/deep_temporal_analysis.txt`

```bash
python scripts/deep_temporal_analysis.py
```

---

### `visualize_best_schedule.py`

Visualizes winner distributions and score gaps from
`outputs/weight_sweep/metrics.jsonl` (produced by `sweep_weights.py`).

**Three figures:**
1. Winner heatmap — which mode wins per (arch, workload) pair
2. Score-gap strip — how much better the winner is vs the runner-up
3. Metric profiles — normalised delay / traffic / utilisation per mode (mean ± std)

**Output:** `outputs/weight_sweep/best_schedule_vis.pdf` (default)

```bash
python scripts/visualize_best_schedule.py
python scripts/visualize_best_schedule.py --out outputs/figures/vis.pdf
```

---

## 4. Weight Calibration

### `find_weights.py`

Grid-searches `(w_u, w_dl)` (with `w_tr=1` fixed) for a **single (arch, workload)
pair** to find weight triples that satisfy the winner constraints:

1. `Dl_winner ≤ (1 + slack) × min_mode(Dl)` — near-minimal latency
2. `Tr_winner = min_mode(Tr)` — exact minimum traffic (or relaxed to ≤ 1+slack)

Useful for understanding what objective weights mean for a specific layer.

```bash
python scripts/find_weights.py                                  # default arch+layer
python scripts/find_weights.py --layer configs/workloads/vgg16/conv5_3.yaml
python scripts/find_weights.py --arch configs/arch/sweep/nodes_1024/...
python scripts/find_weights.py --latency-slack 0.05 --traffic-slack 0.05 --steps 40
python scripts/find_weights.py --time-limit 60 --mip-gap 0.001
```

---

### `sweep_weights.py`

Same grid-search as `find_weights.py` but run across a **representative arch ×
workload space** (8 arch configs × 12 workloads = 96 pairs) to find a single
weight triple that works robustly.

**Arch space:** nodes ∈ {16, 1024} × GB ∈ {64, 4096} KB × split ∈ {w24_p4_v4, w30_p1_v1}, L1=16 KB, PE=64

**Workload space:** shallow (resnet19/conv1) and deep (vgg16/conv5_3) × T ∈ {4, 8, 16, 32, 64, 128}

**Two phases:**
1. Solve all modes for every pair, save metrics to `outputs/weight_sweep/metrics.jsonl`
2. Grid-search weight triples, report which triple maximises constraint satisfaction

```bash
python scripts/sweep_weights.py                  # full run (phase 1 + 2)
python scripts/sweep_weights.py --jobs 4         # parallel solves
python scripts/sweep_weights.py --search-only    # skip phase 1 (reuse checkpoint)
python scripts/sweep_weights.py --time-limit 60  # 60s per Gurobi solve
```

---

## Shared Library (`lib/`)

Internal helpers shared across scripts — not intended to be run directly.

| File | Contents |
|------|----------|
| `lib/workloads.py` | Canonical workload definitions (`build_unique_workloads`, `T_VALUES`, `shape_key`) |
| `lib/progress.py` | Progress-line printer (`print_progress`) |
| `lib/parse_output.py` | Output file parsers (`extract_best_block`, `classify_t_in_loop`, `kb_str_to_int`, `parse_bytes_str`, `sp_dims`) |
