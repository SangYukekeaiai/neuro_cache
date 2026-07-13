# SNN CoSA — Temporal Mode Classification: Correction & Upcoming Changes

> Created: 2026-06-22. Captures the corrected loop-ordering theory and
> the resulting code changes required in `temporal_order.py` and `modes.py`.
> **No code has been changed yet.**

---

## 1. Background: What the Traffic Modes Express

The scheduler's traffic modes constrain the *loop permutation* at each memory level
so that psum and/or vmem DRAM traffic can be eliminated or reduced.

Two variables drive SNN-specific traffic beyond ordinary CNN:

| Variable | Source | Crosses DRAM when… |
|----------|--------|---------------------|
| **psum** | Partial K-reduction for each (T, output position) | K is split across DRAM tiles (K_d > 0) |
| **vmem** | Membrane state vmem[t] consumed by next timestep | T is split across DRAM tiles (T_d > 0) |

**Elimination** (zero_vars) means the variable's DRAM traffic = 0 (the constraint
forces the relevant dimension out of the DRAM perm region entirely).

**Reduction** (gb_only_vars) means the variable's DRAM perm contributes no
multiplicative factor to traffic (Td = 1); it still appears at GB level.

---

## 2. Key Finding: y-Monotonicity and the A Matrix

Understanding the following is critical to the corrected classification.

From `model/constants.py`, the A-matrix for **psum** is:

```
A[KH][psum]  = 0     K dims do NOT seed y[(psum, i)]
A[KW][psum]  = 0
A[CIN][psum] = 0
A[COUT][psum]= 1
A[HO][psum]  = 1
A[WO][psum]  = 1
A[T][psum]   = 1     T DOES seed y[(psum, i)]
```

From `model/constraints/assignment.py`, y is **monotonically non-decreasing**
across perm slots (inner → outer):

```
y[v, i] = row_sum(v, i)          at the first slot
y[v, i] >= y[v, i-1]             for all subsequent slots
y[v, i] >= row_sum(v, i)
```

Under a minimising objective, y[v,i] = max(y[v,i−1], row_sum(v,i)).

**Consequence for OOKT vs OOTK** (both T and K in GB, neither at DRAM):

- **OOTK** (K inner at slot i_K < i_T, T outer at slot i_T):
  - At i_K: row_sum(psum, i_K) = 0 (A[K][psum]=0) → y[(psum,i_K)] = 0
  - At i_T: row_sum(psum, i_T) = 1 (A[T][psum]=1) → y[(psum,i_T)] = 1
  - K's slot contributes **0** to psum traffic (y was 0 there)
  - psum traffic = MULT × T_GB × (outer factors only)

- **OOKT** (T inner at slot i_T < i_K, K outer at slot i_K):
  - At i_T: y[(psum,i_T)] = 1 (T fires y=1)
  - At i_K: y[(psum,i_K)] ≥ y[(psum,i_T)] = 1 via monotonicity → **y=1**
  - K's outer slot contributes **K_GB** to psum traffic via monotonicity
  - psum traffic = MULT × T_GB × K_GB × (outer factors)

**OOKT therefore has non-zero psum traffic despite K not crossing DRAM.**

This is the foundation of the corrected classification.

---

## 3. Corrected Classification

### 3.1 Psum-only elimination — oToK (two variants)

The oToK pattern has two distinct variants depending on which perm region the
constraint targets. In both, "oToK" means: reading the loop ordering from outer to
inner, T appears before K with other O dims potentially between them.

---

#### psum_dram_oToK — DRAM-perm-only view

The constraint is expressed entirely within the **DRAM perm region**. Both T and K
appear at DRAM level; K is innermost, T is above K with **at least one non-K/T
dimension between them** (not adjacent).

```
DRAM perm (outer → inner):   (O …) T … [≥1 O] … K
                                              ↑
                               K innermost in DRAM
                               T above K, at least one O between T and K
                               O dims before T are optional (may be absent)
GB   perm:  unconstrained
```

K is innermost in DRAM with y[(psum, i_K)] = 0 (A[K][psum] = 0). The required O
between K and T (where those O dims are non-psum-seeding K-dims KH/KW/CIN) keeps
y = 0 through the gap, so K's DRAM factor contributes **0** to psum traffic. T is
outer, but the psum reduction completes inside K → **psum DRAM traffic = 0**
(zero_vars={VAR_PSUM}). This is a **new mode** that does NOT replace `add_ootk_dram`
— the adjacent adjacent pattern is a separate valid schedule and must be kept. The
two DRAM-side psum modes will coexist:

| Existing | `PSUM_DRAM_OOTK` | `add_ootk_dram` | T and K adjacent at DRAM |
| New | `PSUM_DRAM_OTOK` | `add_otok_dram` | T and K non-adjacent at DRAM, zero_vars |


---

#### psum_gb_oToK — integrated view

The constraint spans **both perm regions** together as one ordering. K is the
**innermost dimension across the integrated loop** (NodeLevel → GB → DRAM); K does
not appear in the DRAM perm (K_d = 0 implicitly enforced by K being innermost in
GB). T is outer to K ("outer-T") but is **not forced to DRAM** — T may land in GB
or DRAM. At least one O dim must sit between T and K (non-adjacent) wherever they
appear in the ordering.

```
DRAM perm (outer → inner):   (O …) [T optional here]   (T may or may not be at DRAM)
          ── level boundary ──
GB   perm (outer → inner):   (O …) [T if not at DRAM] (O …) K
                                                              ↑
                                                  K innermost across all levels
                                                  at least 1 O between T and K
```

Because K is not in the DRAM perm (K_d = 0), psum never crosses DRAM → **psum DRAM
traffic = 0** (zero_vars={VAR_PSUM}). Vmem DRAM traffic depends on whether T is at
DRAM. This is the true psum elimination mode.

**Currently missing** from the codebase. `add_ootk_gb` was labelled as this mode
but actually implements OOTK joint elimination (see §3.3).


---

### 3.2 Vmem-only elimination — xxxT

**Condition**: T not at DRAM (T_d = 0, T innermost in GB); K has at least one
factor somewhere (GB or DRAM). Vmem DRAM traffic = 0; psum traffic is computed
normally and is non-zero (K's factor enters via y-monotonicity regardless of
whether K is at DRAM or at an outer GB slot).

`zero_vars={VAR_VMEM}` correctly zeroes vmem traffic. **No change needed to
`add_xxxt_gb`.**

The "at least one K in GB or DRAM" constraint in `add_xxxt_gb` is *necessary*: it
prevents the OOOT (joint) case (K only at NodeLevel, no K in perm) from leaking
into this mode.

### 3.3 Joint elimination — OOOO / OOOT / OOOK / OOTK

**Condition**: Neither K nor T at DRAM. Both psum and vmem DRAM traffic = 0.

Four sub-patterns by GB-level ordering:

| Name | GB ordering | Existing function |
|------|-------------|-------------------|
| **OOOO** | No K, no T in any perm (both at NodeLevel) | `add_oooo_gb` ✓ |
| **OOOT** | T innermost in GB, no K in any perm | `add_ooot_gb` ✓ |
| **OOOK** | K innermost in GB, no T in any perm | `add_oook_gb` ✓ |
| **OOTK** | T above K in GB (K innermost of the pair), O above T | `add_ootk_gb` ✓ (but **misclassified**) |

**OOTK is the current `add_ootk_gb`**: it forces K in GB, T in GB, T above K, O
above T. Both K and T are out of DRAM → joint elimination. However, the current
`_MODE_SPECS` entry assigns `zero_vars={VAR_PSUM}` only — incorrect. Vmem DRAM
traffic is also 0 (T not at DRAM) but is not zeroed in the objective.

---

## 4. Impact on Existing Code

### 4.1 `temporal_order.py` — what needs to change

| Function | Current state | Required change |
|----------|--------------|-----------------|
| `add_ootk_gb` | Implements OOTK joint pattern correctly | **No change to constraints.** Reclassify in `modes.py` only (see §4.2). |
| `add_ootk_dram` | Forces T adjacent to K at DRAM (no O between T and K) | **No change.** The strict adjacent OOTK-DRAM pattern is a valid separate mode and must be kept. |
| *(new)* `add_otok_dram` | Does not exist | **Create** (psum_dram_oToK): K and T both at DRAM, K innermost, T above K, **at least one O between T and K** (non-adjacent). Name TBD — see naming note in §3.1. |
| *(new)* `add_otok_gb` | Does not exist | **Create** (psum_gb_oToK): integrated view. K innermost across all levels (K_d = 0), T not forced to DRAM (may be at GB or DRAM), at least one O between T and K. |
| `add_xxxt_gb` | T innermost in GB, K somewhere (GB or DRAM) | **No change.** |
| `add_xxxt_dram` | T innermost in DRAM, K in DRAM | **No change.** |
| `add_oooo_gb` | No K/T in any perm | **No change.** |
| `add_ooot_gb` | T in GB, no K in any perm | **No change.** |
| `add_oook_gb` | K in GB, no T in any perm | **No change.** |

**Net additions**: 2 new functions (`add_otok_dram`, `add_otok_gb`).
**Net modifications**: 0.
**Net reclassifications** (modes.py only, no constraint change): `add_ootk_gb`.

### 4.2 `modes.py` — what needs to change

| Mode | Current spec | Required change |
|------|-------------|-----------------|
| `PSUM_GB_OOTK` | `add_ootk_gb`, `zero_vars={VAR_PSUM}` | Move to C-group. Rename to `GB_OOTK`. Change `zero_vars` to `{VAR_PSUM, VAR_VMEM}`. |
| `PSUM_DRAM_OOTK` | `add_ootk_dram`, `gb_only_vars={VAR_PSUM}` | Add `VAR_VMEM`: `gb_only_vars={VAR_PSUM, VAR_VMEM}`. |
| *(new)* `PSUM_DRAM_OTOK` | — | Add: `add_otok_dram`, `zero_vars={VAR_PSUM}`. DRAM non-adjacent psum elimination. |
| *(new)* `PSUM_GB_OTOK` | — | Add: `add_otok_gb`, `zero_vars={VAR_PSUM}`. True psum-only GB elimination. |
| `VMEM_GB_XXXT` | `add_xxxt_gb`, `zero_vars={VAR_VMEM}` | **No change.** |
| `VMEM_DRAM_XXXT` | `add_xxxt_dram`, `gb_only_vars={VAR_VMEM}` | **No change.** |
| `GB_OOOO`, `GB_OOOT`, `GB_OOOK` | joint, `zero_vars={VAR_PSUM, VAR_VMEM}` | **No change.** |
| `DRAM_OOOO`, `DRAM_OOOT`, `DRAM_OOOK` | DRAM-side, `gb_only_vars={VAR_PSUM, VAR_VMEM}` | **No change.** |

**Net additions**: 2 new modes (`PSUM_DRAM_OTOK`, `PSUM_GB_OTOK`).
**Net reclassifications**: `PSUM_GB_OOTK` → `GB_OOTK` (C-group, both vars zeroed).
**Net renamings**: 0.

### 4.3 `constraints/__init__.py`

Export the 2 new functions once named.

### 4.4 Enumerator impact

The total mode count changes: **11 → 13** (two new modes added).
The `run_profiling_sweep.py` log line currently says "x11 modes each" — this will
need updating to "x13 modes each".

---

## 5. Why the Current `PSUM_GB_OOTK` Classification Is Wrong

The misclassification matters beyond naming. With `zero_vars={VAR_PSUM}` only:

1. The vmem traffic objective term is **not zeroed**. The vmem formula sums ALL
   temporal non-reduction factors (COUT, HO, WO, T) across the full perm range.
   Since T is forced to GB by `add_ootk_gb`, the T_GB factor still contributes a
   non-zero vmem formula value.

2. The optimizer therefore tries to minimize a **spurious GB-level vmem cost**
   (proportional to T_GB × spatial factors) that does not correspond to any actual
   DRAM crossing. Under joint elimination, both psum and vmem DRAM traffic are 0;
   the optimizer should focus purely on weight traffic and delay.

3. The result is that `PSUM_GB_OOTK` produces sub-optimal schedules for OOTK
   configurations, because it wastes objective budget penalizing
   non-existent vmem DRAM traffic.

Fixing this (`zero_vars={VAR_PSUM, VAR_VMEM}`) aligns the objective with the
actual traffic structure.

---

## 6. Summary: Complete Change List

| # | File | Type | Description |
|---|------|------|-------------|
| M1 | `temporal_order.py` | **No change** | `add_ootk_dram` kept as-is (strict adjacent OOTK-DRAM). |
| M2 | `temporal_order.py` | **Add** | New `add_otok_dram` (psum_dram_oToK): K and T both at DRAM, K innermost, T above K, at least one O between T and K (non-adjacent). |
| M3 | `temporal_order.py` | **Add** | New `add_otok_gb` (psum_gb_oToK): integrated view. K innermost across all levels (K_d=0), T outer but not forced to DRAM, at least one O between T and K. |
| M4 | `modes.py` | **Modify** | Reclassify `PSUM_GB_OOTK` → `GB_OOTK` (C-group, joint): `zero_vars={VAR_PSUM, VAR_VMEM}`. Constraint function `add_ootk_gb` is unchanged. |
| M5 | `modes.py` | **Modify** | `PSUM_DRAM_OOTK`: add `VAR_VMEM` to gb_only_vars → `gb_only_vars={VAR_PSUM, VAR_VMEM}`. |
| M6 | `modes.py` | **Add** | New mode `PSUM_DRAM_OTOK`: uses `add_otok_dram`, `zero_vars={VAR_PSUM}`. DRAM non-adjacent psum elimination. |
| M7 | `modes.py` | **Add** | New mode `PSUM_GB_OTOK`: uses `add_otok_gb`, `zero_vars={VAR_PSUM}`. True psum-only GB elimination. |
| M8 | `constraints/__init__.py` | **Modify** | Export the 2 new constraint functions (names TBD). |
| M9 | `run_profiling_sweep.py` | **Fix** | Update mode count string to x13. |

**Unchanged** (constraints): `add_ootk_gb`, `add_ootk_dram`, `add_xxxt_gb`, `add_xxxt_dram`, all OOOO/OOOT/OOOK functions, all parsers, all objectives, all scripts logic.
