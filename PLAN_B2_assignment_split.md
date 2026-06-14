# B2 — Split `add_assignment_constraints` (104 lines → helper + coordinator)

## What it does

`add_assignment_constraints` enforces four constraint classes that give the
MIP its structural skeleton — no variable is created here, only linear
constraints are added to the Gurobi model:

| # | Name | Constraint | Purpose |
|---|------|-----------|---------|
| 1 | sp-tp | `x[i,j,n,0] + x[i,j,n,1] ≤ 1` | a factor is spatial OR temporal, not both |
| 2 | col | `Σ_{i,k} x[i,j,n,k] = 1` | every prime factor lands at exactly one level |
| 3 | row | `Σ_{j,n,k} x[i,j,n,k] ≤ 1` | each perm slot holds at most one factor |
| 4 | y-mono | `y[v,i] ≥ y[v,i-1]` and `y[v,i] ≥ row_sum(v,i)` | reuse indicator is non-decreasing |

Block 4 is the only one that builds output state (`s_gb`, `s_dram`) and adds
three sub-types of constraint. Extracting it clarifies the coordinator's role:
"add the three simple structural classes, then delegate reuse-indicator logic."

---

## Minimal example

```
perm_levels=2, gb_start_level=1, dram_start=3
Perm slots: 1,2 (NoCLevel) + 3,4 (OffChip)

y-monotonicity chain (VAR_WEIGHT, v=0):
  i=1: y[0,1] == row_sum(0,1)          ← init (no predecessor)
  i=2: y[0,2] >= y[0,1]  AND  y[0,2] >= row_sum(0,2)
  i=3: y[0,3] >= y[0,2]  AND  y[0,3] >= row_sum(0,3)
  i=4: y[0,4] >= y[0,3]  AND  y[0,4] >= row_sum(0,4)

row_sum(v,i) = Σ_{j,n} x[(i,j,n,1)] * A[j][v]
  = 1 iff a temporal factor relevant to v is placed at slot i, else 0

s_gb   = {(v,1): row_sum(v,1), (v,2): row_sum(v,2)}   # NoCLevel
s_dram = {(v,3): row_sum(v,3), (v,4): row_sum(v,4)}   # OffChip
```

Under a minimising traffic objective Gurobi drives `y[v,i]` to its minimum
feasible value (= `max(row_sum over [gb_start, i])`), so no upper-bound
constraint is needed.

---

## DFS call-graph position

```
solve_schedule  [solver.py]
  └─ add_assignment_constraints  [constraints/assignment.py]   ← B2 target
       ├─ (inline) _add_sp_tp_constraints     — block 1: x[i,j,n,0]+x[i,j,n,1] ≤ 1
       ├─ (inline) _add_col_constraints       — block 2: col sum == 1
       ├─ (inline) _add_row_constraints       — block 3: row sum ≤ 1
       └─ _add_y_monotonicity  (NEW)          — block 4: y chain + s_gb/s_dram
```

Blocks 1–3 stay inline; each is ≤ 10 lines and adds a single class of
identical constraints. Block 4 is extracted because it builds two output dicts
and adds three logically distinct sub-constraints (init / chain / row-lower-bound).

---

## Proposed change

### `_add_y_monotonicity(m, x, y, pf, gb_start_level, dram_start, perm_levels)`
- Iterates `v ∈ NUM_VARS`, `i ∈ [gb_start_level, dram_start + perm_levels)`
- Builds `row_sum(v,i) = Σ_{j,n} x[(i,j,n,1)] * A[j][v]`
- Adds: `y[v, gb_start] == row_sum` (init), then `y ≥ y_prev` + `y ≥ row_sum`
- Accumulates `s_gb` (NoCLevel slots) and `s_dram` (OffChip slots)
- Returns `(s_gb, s_dram)`
- ~30 lines

### `add_assignment_constraints` (coordinator, ~75 lines after split)
- Blocks 1–3 stay inline (compact, uniform)
- Delegates block 4 to `_add_y_monotonicity`
- Returns `s_gb, s_dram` from the helper unchanged

---

## Why this is borderline at 104 lines

The function is only 4 lines over the limit. Blocks 1–3 are each ≤ 10 lines
and are structurally uniform (one constraint type each). The audit rule still
applies: block 4 is legitimately different — it carries output state — and
deserves its own named boundary.
