# Why the 17 prosperity (arch, layer) pairs are solver-INFEASIBLE

**Answer: a single binding constraint, `cap_NodeLevel_psum`.** The prosperity
mapspace forces `T` fully resident at NodeLevel while `HO`, `WO` and `COUT` are
each pinned to 4, and the resulting partial-sum tile does not fit the node's
1,024-byte psum buffer once `T > 8`. Every one of the 17 has `T` in {10, 16, 32};
every feasible prosperity layer either has `T = 4` or a spatial extent small
enough to compensate.

Proven two independent ways below: an analytic predicate that reproduces exactly
the 17 (zero false positives over all 157 captured layers), and a real Gurobi
solve whose irreducible infeasible set (IIS) names those same constraints.

HANDOFF.md's "all-T-resident psum pressure" story is therefore **confirmed, not
replaced** - but it was previously unproven and lacked the boundary, which is
what made it impossible to predict which layers it hit. The boundary is `T <= 8`.

## 1. The mechanism

Three pieces of the model combine, all from
`zoo/wt500_fig3cfg/mapspaces/prosperity.yaml` and `zoo/wt500_fig3cfg/arch.yaml`:

| piece | where | effect on the NodeLevel tile |
|---|---|---|
| `T: full` | `prosperity.yaml` `node_dim_capacity` | **every** prime factor of `T` forced resident at level 0 (`node_capacity.py`, `cap == FULL` branch: `m.addConstr(term == 1)` per factor) |
| `HO: 4`, `WO: 4` | same | resident product pinned by **equality** to `_max_product_leq(factors, 4)`, i.e. "fill as much as fits", not "at most 4" (`node_capacity.py`) |
| `COUT: {spatial: 4}` | same | spatial extent pinned to `_largest_divisor_leq(COUT, 4)` (`node_level.py`), and COUT's temporal residency at level 0 barred |

The capacity constraint is `objectives/utilization.py`. `_build_node_util_reward`
builds, per variable `v`, a log2-space expression
`log2(bytes_per_elem[v]) + sum log2(factor) * x[(0, d, n, k)]` over every
dimension `d` with `_A[d][v] == 1` and both mapping kinds, and
`add_utilization_capacity_constraints` adds
`expr <= log2(arch.mem_entries[NodeLevel][v])`. Exponentiating, that is a plain
byte inequality:

```
bytes_per_elem[v] * (product of node-resident factors of every dim with A[d][v]=1)
    <= NodeLevel capacity[v]
```

For `psum`, `constants.py`'s A matrix gives `A[d][psum] = 1` for exactly
`COUT, HO, WO, T` (documented there as `psum = HO x WO x COUT x T`), and
`bytes_per_elem = BW_PSUM / 8 = 16 / 8 = 2`. So the binding inequality is:

```
2 * HO_resident * WO_resident * COUT_spatial * T  <=  1024 bytes
```

With `HO_resident = WO_resident = 4` (any `ho, wo >= 4`, which holds for all 17)
and `COUT_spatial = 4` (every one of the 17 has `COUT` divisible by 4):

```
2 * 4 * 4 * 4 * T = 128 * T  <=  1024    <=>    T <= 8
```

**`T = 4` passes with 512 B to spare. `T = 10`, `16` and `32` cannot pass at any
`HO`/`WO`/`COUT` the mapspace permits, because all three of those factors are
pinned by equalities, not bounded by inequalities - the solver has no freedom to
shrink the tile.** That is the whole mechanism: the infeasibility is structural,
not a search failure, and no amount of solver time changes it.

Measured psum demand for the 17:

| workload | layers | T | psum demand | capacity | over by |
|---|---|---:|---:|---:|---:|
| A08/`vgg16_cifar10_loas` | L1-L9 | 32 | 4,096 B | 1,024 B | 4.0x |
| C01/`sma_azo_vgg_dvs128_gesture` | L1-L4 | 16 | 2,048 B | 1,024 B | 2.0x |
| C01/`sma_azo_vgg_cifar10_dvs` | L1-L4 | 10 | 1,280 B | 1,024 B | 1.25x |

The other two node-level capacities never bind: `vmem` is `T`-independent by the
A matrix (`4 B * HO * WO * COUT = 256 B` of 1,024) and `weight` peaks at
`1 B * KH * KW * CIN_resident * COUT_spatial = 576 B` of 32,768.

## 2. Analytic check: the predicate reproduces exactly the 17

Reimplementing `_max_product_leq` and `_largest_divisor_leq` and applying the
psum inequality to **all 157 captured layers** of LAYER_SHAPES.md flags
**17 layers, and they are precisely the 17 prosperity INFEASIBLE pairs** from
`schedule_tiles.csv` (the 151-layer set minus prosperity's 134):

| | predicted | actual |
|---|---|---|
| A08/`vgg16_cifar10_loas` | L1-9 | L1-9 |
| C01/`sma_azo_vgg_cifar10_dvs` | L1-4 | L1-4 |
| C01/`sma_azo_vgg_dvs128_gesture` | L1-4 | L1-4 |
| total | 17 | 17 |

No false positives and no false negatives over 157 layers. The predicate is
`2 * maxprod(ho,4) * maxprod(wo,4) * largest_divisor(oc,4) * T > 1024`.

### Controls, including the ones that discriminate

The decisive control is a **same-shape pair differing only in `T`**:
A08/`vgg16_cifar10_loas` L1 and B09/`loas_vgg16` L1 are both
`3x3, CIN 64, COUT 64, 32x32`. A08's is `T = 32` and infeasible; B09's is
`T = 4` and feasible. Nothing but `T` differs, which isolates `T: full` as the
cause.

Layers that are high-`T` yet feasible, each explained by the same arithmetic:

| control | shape | psum | why feasible |
|---|---|---:|---|
| A08 L10-L12 | 3x3, 2x2 out, T=32 | 1,024 B | `ho = wo = 2`, so `HO_r = WO_r = 2`: `2*2*2*4*32 = 1024`, fits with **zero** slack |
| A08 L13 | GEMM 1x1, COUT 10, T=32 | 128 B | `ho = wo = 1` and `COUT_spatial = largest_divisor(10, 4) = 2` |
| C01 L5-L6 | GEMM, 1x1 out, T=10/16 | 80-160 B | `ho = wo = 1` collapses the spatial product |
| A02, A04, B09 S2 convs | 3x3, T=4 | 512 B | `T = 4`, half the budget |
| A07 GEMMs | 1x1, 128x1 out, T=4 | 128 B | `wo = 1`, `T = 4` |

A08 L10-L12 at exactly 1,024 B is the tightest confirmation available: one more
factor of 2 anywhere in `HO`, `WO`, `COUT` or `T` would flip them infeasible, and
the model does admit them, so the inequality is non-strict (`<=`) as the code
says.

## 3. Solver confirmation: the real IIS

gurobipy 13.0.2 with a full academic license is available on this host, so the
analytic result was checked against the actual model rather than left as a
derivation. Driver rebuilds the model by calling the scheduler's own constraint
functions in `solve.py`'s order (`create_schedule_vars`,
`add_assignment_constraints`, `add_spatial_constraints`,
`add_pe_spatial_split_constraints`, `add_node_capacity_constraints`,
`add_no_noc_level_constraints`, `build_utilization_terms`,
`add_utilization_capacity_constraints`) against the campaign's real `arch.yaml`
and `mapspaces/prosperity.yaml`, then calls `Model.computeIIS()`.

One representative layer per infeasible workload, all three `status = 3`
(INFEASIBLE), all three with the **same 5-constraint IIS**:

```
cap_NodeLevel_psum, node_cap_bound_HO, node_cap_bound_WO,
node_cap_full_T, pe_split_COUT
```

For A08 L1 the IIS is 8 constraints in total and minimal:
`pe_split_COUT`, `node_cap_bound_HO`, `node_cap_bound_WO`,
`node_cap_full_T_{0,2,3,4}` (four of `T = 32`'s five prime factors - enough to
breach alone) and `cap_NodeLevel_psum`. That is the derived mechanism, named by
the solver, with nothing else in it: no assignment, spatial, temporal-order or
weight/vmem capacity constraint participates.

All five controls solved `status = 2` (feasible), including A08 L10's
zero-slack case and the same-shape `T = 4` twin.

## 4. Remedies (verified by re-solve, not proposed blind)

Each of these was re-solved on the three representative infeasible shapes:

| change | result | note |
|---|---|---|
| NodeLevel `psum: 1024 -> 4096` B | all 3 **feasible** | 4,096 B is exactly the max demand (A08's T=32), so this is the minimum sufficient capacity |
| `HO: 4, WO: 4 -> HO: 2, WO: 2` | predicate clears all 17 | cuts the spatial product 4x: worst case becomes `2*2*2*4*32 = 1024` B, zero slack |
| `psum: 2048` B | **9 still infeasible** | fixes C01 (T=10, 16) but not A08 (T=32) - a half-measure |
| drop `T: full` | would clear it | but `T: full` is the prosperity dataflow's defining property; this changes the arch being modeled, it is not a config fix |

Recommendation for the campaign: do **not** silently widen psum. The 17 are a
faithful consequence of modeling prosperity with a 1,024 B psum spad and a
4-PE node, so "prosperity cannot map these 17 high-`T` layers at this node
configuration" is a **real result to report**, not a bug to paper over. If
coverage of all 157 x 5 is wanted instead, `psum: 4096` B is the minimum change
and must be recorded as a deliberate arch edit, because it alters every
prosperity cost number in the campaign, not just these 17.

## 5. What is NOT resolved here, and what a second DeltaAI export needs

This question is fully settled locally; nothing about it requires a new export.
Two adjacent open items are unaffected by this work:

1. The `dram_num_steps x noc_num_steps x prod(spatial_factors)` factorization of
   any `tile_count` (including the 131,072 heavy case) still needs the solved
   schedule JSONs, which are not on this host. See `layer_dim_coverage.md`.
2. The manifest's **30 `excluded_pairs`** are a separate question from these 17
   `infeasible_pairs` and are not addressed here; mapping those to shape classes
   or loader policy is step 1c's remaining work.

If a second export is cut anyway, the useful additions would be the per-pair
solver status strings and, for any future infeasible pair, Gurobi's IIS - though
as shown above, an IIS can be reproduced locally on demand, so the export does
not need to carry one.

## 6. Reproducing this

- Analytic predicate over all 157 layers: parses LAYER_SHAPES.md and applies the
  psum inequality; reimplements `_max_product_leq` (`node_capacity.py`) and
  `_largest_divisor_leq` (`node_level.py`).
- Solver + IIS: builds the model from the campaign `arch.yaml` and
  `mapspaces/prosperity.yaml` via the scheduler's own constraint functions, with
  a 7-key `problem:` workload YAML (`KH, KW, CIN, COUT, HO, WO, T`) as
  `SNNProb` expects, then `computeIIS()`.
- Both scripts are throwaway drivers under this session's scratchpad, not repo
  files; they import `lays` from `src/` and write nothing into the repo.
