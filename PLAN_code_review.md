# SNN CoSA — Code Review & Restructuring Plan (Updated)

> Last updated: 2026-06-13, reflecting post-profiling-sweep state of the project.

---

## 0. Polished Request

Four sequential, gated phases:

| Phase | Goal | Gate |
|-------|------|------|
| **1 — Digest** | Read every module and trace the data that flows between them. Includes the new scripts layer. | (this doc) |
| **2 — DFS Audit** | Walk the call graph caller-first. Every function ≥ 100 lines must carry a written justification; if no justification holds, it must be split. Audit covers both `src/` and `scripts/`. | (this doc) |
| **3 — Structure Proposal** | Show *why* the current layout needs to change, *what* the new layout looks like. No code written yet. | (this doc → await approval) |
| **4 — Iterative Implementation** | One function per iteration. Each iteration: write a `.md` explanation (what the function does, a minimal example, its DFS position in the call graph), wait for review, then apply the change. | (starts after approval) |

---

## 1. High-Level Digest

### 1.1 What the project does

SNN CoSA is a **Gurobi MIP scheduler** for a single SNN convolutional layer. It assigns seven loop dimensions `(KH, KW, CIN, COUT, HO, WO, T)` across three memory levels and two mapping kinds (spatial vs temporal), minimising a weighted combination of compute latency, buffer traffic, and buffer utilisation.

The project has grown beyond a single solver into a **research tool suite**:
- A core library (`src/snn_cosa/`) that builds and solves the MIP
- An enumerator that sweeps 8 traffic-mode variants and picks the best
- A suite of scripts that generates workload/arch configs, runs sweeps in parallel, and analyses results

### 1.2 Data flow (conceptual)

```
YAML configs
  layer.yaml    → SNNProb      (7 dims, prime-factor lists)
  arch.yaml     → SNNArch      (3 mem levels, fanout S, PE count)
               → SNNBitwidths  (bw_weight / bw_psum / bw_vmem)
  mapspace.yaml → SNNMapspace  (which dims may be spatially split)
         │
         ▼
  create_schedule_vars(prob, arch)
     X[(i,j,n,k)] binary  (level × dim × factor-idx × spatial/temporal)
     y[(v,i)]      int01  (reuse indicator spanning NoCLevel + OffChip perm)
         │
         ▼
  add_assignment_constraints  — column-sum=1, row-sum≤1, y monotonicity
  add_spatial_constraints     — log₂-sum fanout caps per region
  add_pe_spatial_split_constraints (optional) — pin PE split dims
  add_<mode>_constraints (optional) — ordering pattern per TrafficMode
         │
         ▼
  build_utilization_terms     → utilization (GB cap), util_hat (reward), data_size
  compute_temporal_traffic    → l[i], traffic[v]
  compute_spatial_traffic     → spatial_cost[v]
  build_objective             → Gurobi MINIMIZE target
         │
         ▼
  model.optimize()
         │
         ▼
  _collect_result / _extract_strategy / _extract_metrics
         │
         ▼
  JSON output  (schedule + optional metrics)
         │ (enumerator)
         ▼
  enumerate_modes             — repeats above for each of 8 TrafficModes
                                picks winner by: w_u·Σutil + w_tr·Σtraffic + w_dl·delay
```

### 1.3 Module inventory — core library

| File | Lines | Role |
|------|-------|------|
| `cli.py` | 296 | CLI (`solve` / `enumerate` commands) + terminal output formatting |
| `enumerator.py` | 129 | Sweep all 8 `TrafficMode` variants; pick lowest comparison score |
| `solver.py` | 398 | **Orchestrator**: parse → vars → constraints → objective → solve → collect |
| `util.py` | 141 | `build_strategy`: raw per-level factors → human-readable JSON strategy |
| `parsers/layer.py` | 178 | `SNNProb` — reads layer YAML, prime-factorises 7 dims |
| `parsers/arch.py` | 397 | `SNNArch` — reads arch YAML, validates 3-level hierarchy, derives `S[]` |
| `parsers/bitwidths.py` | 112 | `SNNBitwidths` — reads bitwidths block from arch YAML |
| `parsers/mapspace.py` | 225 | `SNNMapspace` — reads mapspace YAML, builds factor-space after `init()` |
| `model/constants.py` | 124 | `_A`, `_B`, `VAR_*`, `TRAFFIC_MULT`, `build_Z` |
| `model/schedule.py` | 117 | `create_schedule_vars` — adds X and y Gurobi variables |
| `model/constraints/assignment.py` | 142 | Column-sum=1, row-sum≤1, spatial-temporal exclusion, y monotonicity |
| `model/constraints/spatial.py` | 115 | Log₂-sum spatial fanout constraints per region |
| `model/constraints/node_level.py` | 96 | Constraint C: pre-defined PE spatial split equality |
| `model/constraints/temporal_order.py` | 392 | 7 functions — one per traffic-mode ordering pattern |
| `model/objectives/utilization.py` | 197 | GB capacity expressions + util reward + inner streaming cost |
| `model/objectives/compute.py` | 55 | Log-iteration count objective term |
| `model/objectives/combined.py` | 57 | Wires compute + utilisation + traffic into Gurobi objective |
| `model/objectives/traffic/spatial.py` | 79 | A-weighted NoCLevel spatial traffic expression |
| `model/objectives/traffic/temporal.py` | 147 | Bilinear weight/psum traffic + linear vmem traffic |
| `model/objectives/traffic/total.py` | 65 | 0.99·data_size + 0.99·spatial + temporal |

### 1.4 Module inventory — scripts layer (new since original plan)

| File | Lines | Role |
|------|-------|------|
| `scripts/generate_arch_sweep.py` | — | Generates arch YAML grid (nodes × L1 × L2 × PE × split) |
| `scripts/generate_workload_sweep.py` | — | Generates workload YAML grid (resnet/vgg layer shapes) |
| `scripts/run_profiling_sweep.py` | 559 | **Fixed-arch profiler**: 35 unique shapes × T ∈ {4,32,128} × 8 modes |
| `scripts/run_full_sweep.py` | 307 | **Full sweep**: all arch YAMLs × all workload YAMLs × 8 modes, parallel |
| `scripts/run_subset_sweep.py` | 339 | **Subset sweep**: selected arch×workload pairs, per-pair `.txt` output |
| `scripts/sweep_weights.py` | ~500 | Phase-1 solve (build comparison data) + Phase-2 grid search for weights |
| `scripts/analyze_profiling_sweep.py` | 406 | Parse profiling `.txt` files; produce mode-rate tables + pie charts |
| `scripts/analyze_mode_rates.py` | 545 | Parse sweep output; mode-rate tables × workload/arch parameters |
| `scripts/analyze_shallow_sweep.py` | 567 | Parse sweep output; scatter plots, heatmaps, utilisation charts |
| `scripts/deep_temporal_analysis.py` | 321 | Temporal tiling breakdowns (T-placement × mode × parameter) |
| `scripts/visualize_best_schedule.py` | 291 | Winner heatmap + score-gap + metric-profile figures from sweep JSONL |
| `scripts/find_weights.py` | — | Earlier weight-search utility (superseded by sweep_weights.py) |
| `scripts/experiments/similarity_probe.py` | — | One-off experiment, not part of main workflow |

### 1.5 What changed since the original plan

| Change | File | Status |
|--------|------|--------|
| **Enumeration expanded: 8 → 11 modes across 3 named categories** | `solver.py`, `temporal_order.py` | **Done** — see §1.6 for full breakdown |
| `w_u` default: `0.01585 → 0.1`, `w_dl` default: `43.1 → 10.0` | `enumerator.py` | **Done** — reverted to CoSA reference weights, validated by sweep_weights analysis |
| `NODE_COUNTS` cleaned to powers-of-2 | `generate_arch_sweep.py` | **Done** |
| `_eval_weights` + `_report_weight_check` extracted from `phase2_search` | `sweep_weights.py` | **Done** — removes inline duplication; also added CoSA-default check |
| Error-record skip in `phase1_solve` done-set | `sweep_weights.py` | **Done** — error records no longer marked as done |
| Profiling sweep run with 11-mode enumeration | `outputs/profiling_sweep/mode_rate_tables.md` | **Done** |
| 7 new analysis/sweep scripts added | `scripts/` | **Done** (untracked) |

### 1.6 Enumeration expansion: 3 categories, 11 modes (current) → 12 modes (pending)

The `TrafficMode` enum and `_MODE_SPECS` table in `solver.py` were restructured from 8 loosely named modes into **3 semantic categories + BASE**:

| Category | Mode name | Constraint fn | zero_vars | gb_only_vars |
|----------|-----------|--------------|-----------|--------------|
| **BASE** | `base` | — | ∅ | ∅ |
| **A — PSUM/ooTK** | `psum_gb_ootk` | `add_ootk_gb` | {psum} | ∅ |
| | `psum_dram_ootk` | `add_ootk_dram` | ∅ | {psum} |
| **B — VMEM/xxxT** | `vmem_dram_xxxt` | `add_xxxt_dram` | ∅ | {vmem} |
| | `vmem_gb_xxxt` | `add_xxxt_gb` | {vmem} | ∅ |
| **C — OOOO/OOOT/OOOK** | `dram_oooo` | `add_oooo_dram` | ∅ | {psum, vmem} |
| | `dram_ooot` | `add_ooot_dram` | ∅ | {psum, vmem} |
| | `dram_oook` | `add_oook_dram` | ∅ | {psum, vmem} |
| | `gb_oooo` | `add_oooo_gb` | {psum, vmem} | ∅ |
| | `gb_ooot` | `add_ooot_gb` | {psum, vmem} | ∅ |
| | `gb_oook` | `add_oook_gb` | {psum, vmem} | ∅ |

**Removed vs old**: `PSUM_BOUNDARY` (add_ootk_boundary) was dropped; `BOTH_DRAM_OOOO` / `BOTH_GB_OOOO` were renamed to `DRAM_OOOO` / `GB_OOOO`.

**Added vs old**: `DRAM_OOOT`, `DRAM_OOOK`, `GB_OOOT`, `GB_OOOK` — four new constraint functions in `temporal_order.py`:
- **D-group (oooT)**: T innermost, no K in any perm region → `add_ooot_gb` (D1), `add_ooot_dram` (D2)
- **E-group (oooK)**: K innermost, no T in any perm region → `add_oook_gb` (E1), `add_oook_dram` (E2)

`temporal_order.py` grew from 392 → 533 lines as a result.

> ⚠️ **Classification correction pending** — see `PLAN_temporal_modes.md` for full analysis.
> The current 11-mode table contains two errors and one missing mode:
>
> | Issue | Current | Corrected |
> |-------|---------|-----------|
> | `psum_gb_ootk` misclassified as psum-only | `zero_vars={psum}` | Move to C-group as `gb_ootk`; `zero_vars={psum, vmem}` — `add_ootk_gb` forces T out of DRAM so vmem DRAM traffic is also 0 |
> | `psum_dram_ootk` forces T adjacent to K at DRAM (too strict) | `add_ootk_dram` with adjacency | Relax to `add_otok_dram` (O can sit between T and K at DRAM); rename to `psum_dram_otok` |
> | True psum-only GB mode (oToK: K in GB, T at DRAM, K inner to T, no adjacency) | Missing | Add `psum_gb_otok` using new `add_otok_gb` |
>
> After correction the count becomes **12 modes**. The `run_profiling_sweep.py`
> log line "x11 modes each" is stale and will need updating to "x12 modes each".

---

## 2. DFS Audit — Function-by-Function

### 2.1 Core library: over-100-line functions

#### `solver.py::_extract_metrics` — **116 lines** (lines 233–349)

**What it does**: After `model.optimize()`, re-evaluates the formulas from `compute_temporal_traffic`, `compute_spatial_traffic`, and `build_utilization_terms` in *linear* (non-log) arithmetic using solved X/y values. Produces `util[v]`, `spatial_cost[v]`, `temporal_traffic[v]`, and `delay`.

**Problem**: Three distinct evaluations stuffed sequentially with no internal structure:
1. `util[v]` — ~22 lines
2. `spatial_cost[v]` — ~13 lines
3. `temporal_traffic[v]` for weight/psum — ~18 lines, then vmem — ~15 lines
4. `delay` — ~10 lines

Each duplicates logic already expressed in `objectives/`, creating two sources of truth.

**Verdict**: Must split. Extract `_eval_util`, `_eval_spatial_cost`, `_eval_temporal_traffic`, `_eval_delay` as private helpers; public function becomes a coordinator ≤ 30 lines.

---

#### `model/objectives/utilization.py::build_utilization_terms` — **124 lines** (lines 41–165)

**What it does**: Builds three completely separate Gurobi expressions in one function:
1. NoCLevel GB capacity expressions (capacity constraints only; NOT in objective)
2. NodeLevel L1 util + `util_hat` reward term
3. `data_size[v]` inner streaming cost

**Problem**: Three unrelated consumers. The function's own comment already identifies this. A reader cannot trace the capacity-expression path without reading the reward path too.

**Verdict**: Must split into `_build_noc_utilization`, `_build_node_util_reward`, and `_build_data_size`. Public function becomes a 25-line coordinator.

---

#### `model/constraints/assignment.py::add_assignment_constraints` — **103 lines** (lines 39–142)

**What it does**: Adds four constraint classes sequentially: (1) spatial-temporal exclusion per `(i,j,n)`, (2) column sum = 1 per `(j,n)`, (3) row sum ≤ 1 per perm slot, (4) unified y monotonicity across NoCLevel + OffChip.

**Problem**: Constraint 4 (y monotonicity, ~30 lines) is conceptually separate from the structural X constraints 1–3, but lives in the same function body.

**Verdict**: Marginal. Extract `_add_y_monotonicity` to drop the public function from 103 → ~70 lines.

---

#### `solver.py::solve_schedule` — **101 lines** (lines 95–196)

**What it does**: Parses all configs, creates variables, adds all constraints, builds objective, calls `model.optimize()`, dispatches to `_collect_result`. Pure sequential coordination — each step is one or two delegated calls.

**Verdict**: Justified as-is — every line is glue, no logic. Length is driven by the number of independent steps. If `TrafficMode`-related code moves to `modes.py`, the import block shrinks and the function stays readable.

---

### 2.2 Scripts layer: over-100-line functions

#### `run_full_sweep.py::run_sweep` — **~105 lines** (lines 136–241)

**What it does**: Loads checkpoint, builds task list, runs parallel sweep with bounded executor window, writes JSONL results.

**Problem**: Parallel executor management (~40 lines) and task-list construction (~25 lines) are interleaved with progress reporting and file I/O inside one function.

**Verdict**: Extract `_build_tasks` and `_run_parallel` as private helpers. Public `run_sweep` becomes a ~40-line coordinator.

---

#### `run_profiling_sweep.py::run_sweep` — **~90 lines** (lines 427–516)

**Verdict**: Borderline, justified — same parallel pattern as above but slightly shorter. Keep as-is; revisit if parallel boilerplate is shared.

---

#### `run_profiling_sweep.py::build_unique_workloads` — **~27 lines** — OK.

### 2.3 Scripts layer: correctness issues (not length-related)

| Issue | File | Line | Severity |
|-------|------|------|----------|
| Imports private `_print_enumeration_summary` from `cli.py` | `run_profiling_sweep.py` | 285 | Design smell — tight coupling to CLI internals |

### 2.4 Scripts layer: duplicate helper functions

The same helper exists (slightly varied) in 4–5 scripts:

| Helper | Scripts that define it |
|--------|----------------------|
| `kb_str_to_int` | `analyze_shallow_sweep.py`, `analyze_mode_rates.py`, `deep_temporal_analysis.py` |
| `classify_t_in_loop` | `analyze_profiling_sweep.py`, `analyze_mode_rates.py`, `analyze_shallow_sweep.py`, `deep_temporal_analysis.py` |
| `parse_bytes_str` | `analyze_shallow_sweep.py`, `deep_temporal_analysis.py` |
| `parse_file` (text → dict) | `analyze_profiling_sweep.py`, `analyze_mode_rates.py`, `analyze_shallow_sweep.py`, `deep_temporal_analysis.py` |
| `_print_progress` | `run_full_sweep.py`, `run_profiling_sweep.py`, `run_subset_sweep.py` |
| `pval` (parameter formatter) | `analyze_profiling_sweep.py`, `analyze_mode_rates.py`, `deep_temporal_analysis.py` |
| Network layer defs (`_resnet50_layers`, etc.) | Only in `run_profiling_sweep.py`, but needed by any future sweep |

### 2.5 All other functions

All remaining functions in `src/` are ≤ 80 lines. All remaining functions in `scripts/` are ≤ 75 lines individually. No further action required for those.

---

## 3. Structural Reconfiguration — Necessity and Proposal

### 3.1 Problems in the core library (`src/snn_cosa/`)

**Problem A — `solver.py` is a catch-all**

`solver.py` currently holds: `TrafficMode` enum, `_ModeSpec`/`_MODE_SPECS` config table, `solve_schedule` (correct), `_collect_result` (correct), `_extract_metrics` (duplicates `objectives/` formulas), `_extract_strategy` (output concern), tiny helpers. Result: 14 import lines at the top, two sources of truth for traffic formulas.

**Problem B — `_extract_metrics` duplicates `objectives/` logic**

Any formula fix in `objectives/` must be manually mirrored in `_extract_metrics`. Currently there are two separate implementations of the same traffic formula — one in log-space (symbolic Gurobi expressions) and one in linear-space (post-solve evaluation). They share no code, so they can drift silently.

**Problem C — `build_utilization_terms` does three separate jobs in 124 lines**

The function's own docstring says it returns `(utilization, util_hat, data_size)` — three distinct artefacts with different consumers. They share a 3-line setup but nothing else.

**Problem D — `util.py` name is misleading**

`util.py` contains exactly one public function: `build_strategy`. The name "util" implies a miscellany; the actual content is output strategy formatting. This confuses the module's purpose.

### 3.2 Problems in the scripts layer (`scripts/`)

**Problem E — No shared utilities module**

Every analysis script independently defines `classify_t_in_loop`, `parse_file`, `_print_progress`, etc. A bug fix (e.g., in `parse_file`) must be applied to 4 files. A new analysis script must copy-paste these helpers.

**Problem F — Workload definitions are embedded in a sweep script**

`_resnet19_layers`, `_vgg16_layers`, `_resnet34_layers`, `_resnet50_layers`, `_gemm_layers`, and `build_unique_workloads` live inside `run_profiling_sweep.py`. Any other script that wants the same workload set must duplicate or import from a sweep script, which is the wrong direction.

**Problem G — CLI internals exposed to scripts**

`run_profiling_sweep.py` imports `_print_enumeration_summary` (underscore-prefixed, i.e., private) from `cli.py`. This creates a brittle dependency: any refactor of CLI output formatting breaks the sweep script.

**Problem H — Stale string literal**

`run_profiling_sweep.py:450` says "x11 modes each" but `TrafficMode` has 8 values. This is misleading in log output.

---

### 3.3 Proposed new layout

```
src/snn_cosa/
  cli.py               ← no structural change
  enumerator.py        ← no structural change (weights already fixed)

  modes.py             ← NEW: TrafficMode enum + _ModeSpec + _MODE_SPECS
                          (extracted from solver.py lines 54–81)

  solver.py            ← SLIMMED: solve_schedule + _collect_result
                          + _extract_strategy + tiny helpers
                          (~200 lines after extraction)

  metrics.py           ← NEW: post-solve linear evaluation
                          _extract_metrics → coordinator (~30 lines)
                          + _eval_util, _eval_spatial_cost,
                            _eval_temporal_traffic, _eval_delay
                          (~130 lines total, each sub ≤ 40 lines)

  output.py            ← RENAMED from util.py (content identical, name reflects purpose)

  model/               ← structure unchanged
    constants.py
    schedule.py
    constraints/
      __init__.py
      assignment.py    ← REFACTOR: extract _add_y_monotonicity()
                          (public fn: 103 → ~70 lines)
      spatial.py
      node_level.py
      temporal_order.py
    objectives/
      __init__.py
      combined.py
      compute.py
      utilization.py   ← REFACTOR: extract 3 sub-functions
                          (public fn: 124 → ~25 lines)
      traffic/
        __init__.py
        spatial.py
        temporal.py
        total.py

  parsers/             ← no change

scripts/
  lib/                 ← NEW: shared script utilities package
    __init__.py
    workloads.py       ← move all network layer defs + build_unique_workloads
                          from run_profiling_sweep.py
    parse_output.py    ← consolidate: classify_t_in_loop, parse_file,
                          parse_bytes_str, kb_str_to_int, pval
    progress.py        ← consolidate: _print_progress (single def)

  run_profiling_sweep.py  ← import from scripts/lib/; fix "x11 modes" bug;
                            remove _print_enumeration_summary import from cli
  run_full_sweep.py       ← import _print_progress from scripts/lib/;
                            extract _build_tasks + _run_parallel
  run_subset_sweep.py     ← import _print_progress from scripts/lib/
  analyze_profiling_sweep.py ← import helpers from scripts/lib/
  analyze_mode_rates.py      ← import helpers from scripts/lib/
  analyze_shallow_sweep.py   ← import helpers from scripts/lib/
  deep_temporal_analysis.py  ← import helpers from scripts/lib/
  generate_arch_sweep.py     ← no change
  generate_workload_sweep.py ← no change
  sweep_weights.py           ← no change (already partially refactored)
  visualize_best_schedule.py ← no change
```

### 3.4 Change summary table

| # | File | Action | Reason |
|---|------|--------|--------|
| A1 | `src/snn_cosa/modes.py` | **Create** | Decouple `TrafficMode`+`_ModeSpec` from solver logic; reduces solver.py import count |
| A2 | `src/snn_cosa/metrics.py` | **Create** | Single source of truth for post-solve traffic evaluation; removes duplication with `objectives/` |
| A3 | `src/snn_cosa/output.py` | **Rename** `util.py` → `output.py` | Name matches content (strategy formatting, not general utilities) |
| B1 | `model/objectives/utilization.py` | **Refactor** | Split 124-line function into 3 private helpers + thin coordinator |
| B2 | `model/constraints/assignment.py` | **Refactor** | Extract `_add_y_monotonicity`; public fn drops 103 → ~70 lines |
| C1 | `solver.py` | **Slim** | Import `TrafficMode` from `modes.py`, `_extract_metrics` from `metrics.py`; update `util` → `output` import |
| D1 | `scripts/lib/workloads.py` | **Create** | Move network layer defs out of `run_profiling_sweep.py` |
| D2 | `scripts/lib/parse_output.py` | **Create** | Consolidate 4× duplicate parse helpers into one module |
| D3 | `scripts/lib/progress.py` | **Create** | Consolidate 3× duplicate `_print_progress` into one module |
| D4 | `run_profiling_sweep.py` | **Fix + refactor** | Import from `scripts/lib/`; fix "x11→x8 modes" bug; remove private CLI import |
| D5 | `run_full_sweep.py` | **Refactor** | Extract `_build_tasks` + `_run_parallel`; import progress from lib |
| D6 | `analyze_*.py` + `deep_temporal_analysis.py` | **Refactor** | Replace local helper defs with imports from `scripts/lib/` |

**What does NOT change**: All function signatures at module boundaries, all YAML formats, all JSON/JSONL output formats, all CLI flags, all solver behaviour.

---

## 4. Step 4 — Iterative Implementation Process

Once you approve the structural proposal above, each iteration follows this protocol:

1. **Write an explanation** in a small `.md` section (or appended here) covering:
   - What the target function/module does in plain language
   - A minimal input → output example
   - The DFS call-graph path from the project entry point down to this change
   - Exactly which lines move and why
2. **Wait for your review** of the explanation.
3. **Apply the one change**.
4. Proceed to the next in the order below.

**Proposed DFS order (innermost/least-dependent first):**

```
Phase A — new modules (nothing breaks, pure additions)
  A1. Create src/snn_cosa/modes.py          ← START HERE
  A2. Create src/snn_cosa/metrics.py
  [util.py rename dropped]

Phase B — refactor over-100-line functions in src/
  B1. utilization.py::build_utilization_terms  → 3 helpers + coordinator
  B2. assignment.py::add_assignment_constraints → extract _add_y_monotonicity

Phase C — slim solver.py (depends on A1 + A2)
  C1. Update solver.py imports; remove now-extracted code

Phase D — scripts/lib/ (independent of A–C)
  D1. Create scripts/lib/workloads.py
  D2. Create scripts/lib/parse_output.py
  D3. Create scripts/lib/progress.py
  D4. Refactor run_profiling_sweep.py (remove private CLI import)
  D5. Refactor run_full_sweep.py
  D6. Refactor analyze_*.py + deep_temporal_analysis.py
```
