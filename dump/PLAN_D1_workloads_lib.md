# D1 — Create `scripts/lib/workloads.py`

## What it does

`run_profiling_sweep.py` contains two concerns mixed together:

1. **Sweep orchestration** — task building, worker dispatch, progress printing
2. **Workload definitions** — per-network layer dicts + deduplicated workload list

The workload definitions are pure data-generation logic with no dependency on
sweep infrastructure. Any future script that wants to profile these networks
(e.g., `run_subset_sweep.py`, a new benchmark script) has to either re-define
the same layers or import from `run_profiling_sweep.py` — coupling a data
consumer to sweep orchestration code.

Moving them to `scripts/lib/workloads.py` gives one canonical source for
the 35-unique-shape workload list that all scripts can import.

---

## Functions extracted from `run_profiling_sweep.py`

| Function | Lines | Purpose |
|----------|-------|---------|
| `_conv` | 113–114 | Build a conv-layer dims dict from (cin,cout,ho,wo,kh,kw) |
| `_shape_key` | 117–122 | Canonical string key from dims (used as file/result name) |
| `_dedup_key` | 125–126 | Hashable tuple for deduplication |
| `_resnet19_layers` | 133–141 | Load from YAML files in configs/workloads/resnet19/ |
| `_vgg16_layers` | 144–154 | Load from YAML files, skip T128 variants |
| `_resnet34_layers` | 157–178 | Hard-coded ResNet-34 conv stack |
| `_resnet50_layers` | 209–240 | Hard-coded ResNet-50 conv stack |
| `_gemm_layers` | 181–206 | DeepBench GEMM as 1×1 conv |
| `build_unique_workloads` | 247–274 | Deduplicate × T_VALUES → list of (wl_key, wl_dict) |

Also moves constants: `T_VALUES = [4, 32, 128]` and `WORKLOAD_ROOT` reference.

---

## Minimal example

```python
from scripts.lib.workloads import build_unique_workloads

workloads = build_unique_workloads()
# → [("cin3_cout64_ho112_wo112_kh7_kw7_T4", {"KH":7,"KW":7,...,"T":4,"shape":"snn-layer"}), ...]
print(len(workloads))   # 105  (35 unique shapes × 3 T values)
```

---

## DFS call-graph position

```
run_profiling_sweep.py::main
  └─ build_unique_workloads  [scripts/lib/workloads.py]   ← D1 target (moved here)
       ├─ _resnet19_layers   (reads YAML files)
       ├─ _vgg16_layers      (reads YAML files)
       ├─ _resnet34_layers   (hardcoded)
       ├─ _resnet50_layers   (hardcoded)
       ├─ _gemm_layers       (hardcoded)
       ├─ _dedup_key         (tuple hash for dedup)
       └─ _shape_key         (string key for output naming)
```

---

## Changes

1. **Create** `scripts/lib/__init__.py` (empty, makes `lib` a package)
2. **Create** `scripts/lib/workloads.py` with all 9 functions + constants
3. **Edit** `run_profiling_sweep.py`:
   - Remove the 9 functions + `T_VALUES` local definition
   - Add `from scripts.lib.workloads import build_unique_workloads, T_VALUES`
   - `WORKLOAD_ROOT` stays in `run_profiling_sweep.py` as it's also used by the arch builder there; `workloads.py` receives it as a parameter to `_resnet19_layers` / `_vgg16_layers`

---

## Why `WORKLOAD_ROOT` is a parameter not a global

`run_profiling_sweep.py` defines `WORKLOAD_ROOT` relative to its own `__file__`.
`workloads.py` lives one level deeper in `scripts/lib/`. To avoid recomputing
the path inside `workloads.py` (which would give a different base), the two
YAML-loading functions accept `workload_root: Path` as an argument. The
hardcoded-network functions (`_resnet34_layers`, etc.) don't need it.
