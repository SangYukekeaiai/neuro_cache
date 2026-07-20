# B1 — Split `build_utilization_terms` (124 lines → 3 helpers + coordinator)

## What it does

`build_utilization_terms` builds three distinct symbolic (log₂-scale) structures
that the Gurobi model uses during solve:

| Output | Purpose | Used by |
|--------|---------|---------|
| `utilization[(l,v)]` | log₂(bytes) footprint of variable `v` at memory level `l` | capacity constraints only |
| `util_hat` | CoSA total_util reward: sum of inner-level buf_util | objective (maximise) |
| `data_size[v]` | Inner-level streaming cost | traffic objective (× 0.99 coefficient) |

The three blocks are completely independent once `pf` and `bytes_by_var` are known.
Each block currently occupies 20–30 lines inside the 124-line coordinator — justified
neither by shared state nor by irreducibility.

---

## Minimal example

```
Loop dimensions: KH=2, KW=3  → pf = [[2],[3],...]
Levels:  0=NodeLevel, 1=NoCLevel(GB), 2=OffChip
gb_start_level = 1,  dram_start = 2
VAR_WEIGHT  _A[KH][w]=1  _B[w][MEM_NODE]=1  _B[w][MEM_NOC]=1

NoCLevel util for weight:
  expr = log2(bytes_weight)              # base
       + log2(2) * x[(0,KH,0,sp)]       # level-0 spatial
       + log2(2) * x[(0,KH,0,tp)]       # level-0 temporal
       + log2(3) * x[(0,KW,0,sp)] ...   # level-0 KW
       + (same for level-1 = dram_start-1)

NodeLevel util for weight (gb_start_level=1 → level 0 only):
  expr_node = log2(bytes_weight) + log2(2)*x[(0,KH,0,sp)] + ...
  util_hat += expr_node   # MEM_NODE contribution
  util_hat += expr_node   # MEM_NOC inner-Z contribution (level 0 ≤ gb_start)

data_size for weight (level 0 only, with gradient 0.8+0.04*0=0.8):
  size = 0.8 * log2(2) * (x[(0,KH,0,sp)] + x[(0,KH,0,tp)]) + ...
```

---

## DFS call-graph position

```
solve_schedule  [solver.py]
  └─ build_utilization_terms  [objectives/utilization.py]   ← B1 target
       ├─ _build_noc_utilization   (NEW)  → utilization[(MEM_NOC, v)]
       ├─ _build_node_util_reward  (NEW)  → utilization[(MEM_NODE, v)], util_hat
       └─ _build_data_size         (NEW)  → data_size[v]
```

---

## Proposed split

### `_build_noc_utilization(x, pf, bytes_by_var, dram_start)`
- Iterates `v ∈ NUM_VARS` where `_B[v][MEM_NOC] != 0`
- Sums log₂(factor) × x[(i,d,n,k)] for i ∈ [0, dram_start), both k
- Returns `Dict[(MEM_NOC, v), LinExpr]`
- ~25 lines

### `_build_node_util_reward(x, pf, bytes_by_var, gb_start_level, has_local_buffer)`
- Iterates `v ∈ NUM_VARS` where `_B[v][MEM_NODE] != 0` and `has_local_buffer`
- Sums log₂(factor) × x[(i,d,n,k)] for i ∈ [0, gb_start_level)
- Accumulates util_hat += expr_node twice (MEM_NODE + MEM_NOC inner Z-correction)
- Returns `Dict[(MEM_NODE, v), LinExpr], LinExpr (util_hat)`
- ~25 lines

### `_build_data_size(x, pf, gb_start_level)`
- Iterates `v ∈ NUM_VARS`; skips if `_B[v][MEM_NOC] == 0` (sets 0.0)
- Sums (0.8 + 0.04·i) × log₂(factor) × (x_sp + x_tp) for i ∈ [0, gb_start_level)
- Returns `Dict[v, LinExpr | float]`
- ~20 lines

### `build_utilization_terms` (coordinator, ~40 lines after split)
- Computes `bytes_by_var`, calls all three helpers, merges `utilization` dicts
- Logs and returns `(utilization, util_hat, data_size)`

---

## Why this stays ≤ 100 lines now

Each helper focuses on exactly one expression family. The coordinator is a
straight-line merge with no nested loops. All three helpers are reusable
independently if a future mode needs to inspect only one expression type.
