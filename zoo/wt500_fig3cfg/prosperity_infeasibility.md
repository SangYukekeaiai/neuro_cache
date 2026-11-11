# Prosperity: which layers the solver rejects, and why

**Answer: a single binding constraint, `cap_NodeLevel_psum`.** The prosperity
mapspace forces `T` fully resident at NodeLevel while `HO` and `COUT` are each
pinned, and the resulting partial-sum tile does not fit the node's 1,024-byte
psum buffer once the product crosses that line.

Under the finalized mapspace this rejects **6** of prosperity's 151 schedulable
(arch, layer) pairs. A second, larger effect sits downstream of the solver: the
same mapspace bars the kernel dimensions from residency, so every 3x3 layer
solves with a split kernel and is then refused by the bridge gate. The net is
that **prosperity generates only 1x1 and GEMM-shaped layers**.

Proven two ways throughout: an analytic predicate applied to all 157 captured
layers, and real Gurobi solves whose irreducible infeasible sets (IIS) name the
constraints. Both are reproducible on this host.

## 0. The two configurations these numbers belong to

Every count below is tagged with the configuration it was measured under,
because the two differ in which dimensions are capped and therefore in the
boundary.

**Config F - finalized** (`mapspaces/prosperity.yaml`, commit `9b87861`), the
one the campaign runs:

```
node_dim_capacity:  CIN: 16   COUT: {spatial: 4}   HO: 8   T: full
```

`KH`, `KW` and `WO` are **absent**, which the node-capacity rule treats as
barred from NodeLevel entirely (absent == cap 1).

**Config K - capped kernel**, a variant with the kernel and both pixel axes
capped instead of barred:

```
node_dim_capacity:  KH: 4   KW: 4   CIN: 16   COUT: {spatial: 4}   HO: 4   WO: 4   T: full
```

Config F is current. Config K's measurements are kept because they isolate the
mechanism cleanly - its IIS carries one more constraint, which shows exactly
which pin is doing the work.

## 1. The mechanism

Three pieces of the model combine, independent of which configuration is in
force:

| piece | where | effect on the NodeLevel tile |
|---|---|---|
| `T: full` | `node_dim_capacity` | **every** prime factor of `T` forced resident at level 0 (`node_capacity.py`, `cap == FULL` branch: `m.addConstr(term == 1)` per factor) |
| an integer cap, e.g. `HO: 8` | same | resident product pinned by **equality** to `_max_product_leq(factors, cap)`, i.e. "fill as much as fits", not "at most" (`node_capacity.py`) |
| a dimension's absence | same | barred: resident product forced to 1 (the cap-1 special case of the same rule) |
| `COUT: {spatial: 4}` | same | spatial extent pinned to `_largest_divisor_leq(COUT, 4)` (`node_level.py`), and COUT's temporal residency at level 0 barred |

The capacity constraint is `objectives/utilization.py`.
`_build_node_util_reward` builds, per variable `v`, a log2-space expression
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

**Under config F**, `WO` is barred so `WO_resident = 1`, and
`HO_resident = _max_product_leq(factors(ho), 8)`. For a layer with `ho >= 8`
and `COUT` divisible by 4 that gives `HO_resident = 8`, `COUT_spatial = 4`:

```
2 * 8 * 1 * 4 * T = 64 * T  <=  1024    <=>    T <= 16
```

**Under config K**, `HO` and `WO` are both capped at 4, so a layer with
`ho, wo >= 4` gives `4 * 4` and the line falls at `128 * T <= 1024`, i.e.
`T <= 8`.

In both cases the infeasibility is **structural, not a search failure**: every
factor in the product is pinned by an equality, so the solver has no freedom to
shrink the tile, and no amount of solver time changes the outcome.

## 2. What config F rejects at the solver: 6 layers

Measured psum demand, and verified by real solve (section 4):

| workload | layers | ho | `HO_res` | T | psum demand | capacity | over by |
|---|---|---:|---:|---:|---:|---:|---:|
| A08/`vgg16_cifar10_loas` | L1 | 32 | 8 | 32 | 2,048 B | 1,024 B | 2.0x |
| A08/`vgg16_cifar10_loas` | L2, L3 | 16 | 8 | 32 | 2,048 B | 1,024 B | 2.0x |
| A08/`vgg16_cifar10_loas` | L4, L5, L6 | 8 | 8 | 32 | 2,048 B | 1,024 B | 2.0x |

That is the complete set: **A08 L1-L6**, all at `T = 32`. The analytic
predicate over all 157 captured layers flags exactly these six and nothing
else.

Three layers sit on the boundary rather than over it. A08 **L7-L9** have
`ho = 4`, so `HO_resident = _max_product_leq(factors(4), 8) = 4` rather than 8,
giving `2 * 4 * 1 * 4 * 32 = 1,024 B` - **exactly** the capacity, feasible with
zero slack. One more factor of 2 in `ho`, `COUT` or `T` would flip them.

The eight C01 convolutions clear comfortably: `HO_res = 8` and `COUT_spatial = 4`
give `2 * 8 * 1 * 4 * 10 = 640 B` at `T = 10` and `1,024 B` at `T = 16` - the
latter another exact-capacity case.

`vmem` and `weight` never bind. `vmem` is `T`-independent by the A matrix and
`weight` has `KH`, `KW` barred, so both sit far under their budgets.

## 3. What config F rejects after the solver: 47 more layers

`KH` and `KW` absent means barred, so a 3x3 layer receives
`node_bound[KH] = node_bound[KW] = _max_product_leq([3], 1) = 1`, not 3: the
kernel is split and each tile holds one tap of nine. The native bridges have
**no kernel-offset field**, so a one-tap tile is indistinguishable from a
whole-window tile on the wire.

The bridge gate catches exactly this. `gen_inputs.py` raises
`kernel_tile_bound` when a tile's `KH`/`KW` bound differs from the problem's,
so those layers are **refused loudly rather than mis-reconstructed** on the
campaign path. (A caller reaching the bridge without that gate would get the
silent version - see `CAVEATS.md` L2.)

Full accounting over prosperity's 151 schedulable pairs:

| outcome | pairs | which |
|---|---:|---|
| infeasible at solve (psum) | 6 | A08 L1-L6, `T = 32` |
| refused by `kernel_tile_bound` | 47 | every remaining 3x3 stride-1 layer |
| **generated** | **98** | the 1x1 convolutions and GEMMs (classes S1 and S3) |
| total | 151 | |

`6 + 47 + 98 = 151`. The 47 is the 53 class-S2 layers of
`layer_dim_coverage.md` minus the 6 that never reach the gate. This is
user-accepted and recorded in the mapspace comment: under this mapspace
prosperity is a 1x1/GEMM-only architecture.

## 4. Solver confirmation: the real IIS

gurobipy 13.0.2 with a full academic license is available on this host, so
every count above was checked against the actual model. The driver rebuilds the
model by calling the scheduler's own constraint functions in `solve.py`'s order
(`create_schedule_vars`, `add_assignment_constraints`,
`add_spatial_constraints`, `add_pe_spatial_split_constraints`,
`add_node_capacity_constraints`, `add_no_noc_level_constraints`,
`build_utilization_terms`, `add_utilization_capacity_constraints`) against the
campaign's real `arch.yaml` and `mapspaces/prosperity.yaml`, then calls
`Model.computeIIS()`.

**Config F.** All nine A08 `T = 32` convolutions solved individually: L1-L6
`status = 3` (INFEASIBLE), L7-L9 `status = 2` (feasible), matching the
boundary arithmetic exactly. All six infeasible ones carry the **same
4-constraint IIS**:

```
cap_NodeLevel_psum, node_cap_bound_HO, node_cap_full_T, pe_split_COUT
```

Both C01 convolutions that config K rejects solve feasible under config F, as
do the 1x1 and GEMM shapes that prosperity actually generates (A08 L13,
A04 L5, A07 L5 all `status = 2`).

**Config K.** The same three representative layers are infeasible with a
**5-constraint IIS**:

```
cap_NodeLevel_psum, node_cap_bound_HO, node_cap_bound_WO,
node_cap_full_T, pe_split_COUT
```

The difference between the two IIS sets is exactly `node_cap_bound_WO`: under
config F `WO` is barred rather than capped, so it contributes no bound
constraint and cannot participate. That is the mechanism visible in the
solver's own output - the set of pins in the IIS is the set of pins in the
inequality.

For one config-K layer the IIS is 8 constraints in full and minimal:
`pe_split_COUT`, `node_cap_bound_HO`, `node_cap_bound_WO`,
`node_cap_full_T_{0,2,3,4}` (four of `T = 32`'s five prime factors - enough to
breach alone) and `cap_NodeLevel_psum`. No assignment, spatial, temporal-order
or weight/vmem capacity constraint appears in either configuration's IIS.

### Controls

Under config K, the decisive control is a **same-shape pair differing only in
`T`**: A08 L1 and B09/`loas_vgg16` L1 are both `3x3, CIN 64, COUT 64, 32x32`.
A08's is `T = 32` and infeasible; B09's is `T = 4` and feasible. Nothing but
`T` differs, which isolates `T: full` as the cause.

Config-K layers that are high-`T` yet feasible, each explained by the same
arithmetic:

| control | shape | psum | why feasible |
|---|---|---:|---|
| A08 L10-L12 | 3x3, 2x2 out, T=32 | 1,024 B | `ho = wo = 2`, so `HO_r = WO_r = 2`: `2*2*2*4*32 = 1024`, fits with **zero** slack |
| A08 L13 | GEMM 1x1, COUT 10, T=32 | 128 B | `ho = wo = 1` and `COUT_spatial = largest_divisor(10, 4) = 2` |
| C01 L5-L6 | GEMM, 1x1 out, T=10/16 | 32-128 B | `ho = wo = 1` collapses the spatial product; these heads are among the only four layers campaign-wide where `_largest_divisor_leq(COUT, 4) < 4` |
| A02, A04, B09 S2 convs | 3x3, T=4 | 512 B | `T = 4`, half the budget |
| A07 GEMMs | 1x1, 128x1 out, T=4 | 128 B | `wo = 1`, `T = 4` |

All four layers with `COUT_spatial < 4` are the small classifier heads:
`COUT = 10` gives 2 (A08 L13, B09/`loas_vgg16` L13, C01/cifar10_dvs L6) and
`COUT = 11` gives 1 (C01/dvs128_gesture L6). Every other layer in all 157 has
`COUT` divisible by 4, so `COUT_spatial = 4` holds everywhere else.

The four C01 head values in full: cifar10_dvs L5 (`COUT 1024`, T=10) 80 B and
L6 (`COUT 10` -> `COUT_spatial` 2, T=10) 40 B; dvs128_gesture L5 (`COUT 1024`,
T=16) 128 B and L6 (`COUT 11` -> `COUT_spatial` 1, T=16) 32 B.

A08 L10-L12 at exactly 1,024 B is the tightest confirmation available: one more
factor of 2 anywhere in `HO`, `WO`, `COUT` or `T` would flip them infeasible,
and the model does admit them, so the inequality is non-strict (`<=`) as the
code says.

## 5. Remedies (verified by re-solve, not proposed blind)

Measured under config K on its three representative infeasible shapes:

| change | result | note |
|---|---|---|
| NodeLevel `psum: 1024 -> 4096` B | all 3 **feasible** | 4,096 B is exactly the max demand there, so this is the minimum sufficient capacity |
| `HO: 4, WO: 4 -> HO: 2, WO: 2` | predicate clears all 17 | cuts the spatial product 4x |
| `psum: 2048` B | **9 still infeasible** | fixes the C01 layers but not A08's `T = 32` set - a half-measure |
| drop `T: full` | would clear it | but `T: full` is the prosperity dataflow's defining property; this changes the arch being modeled, it is not a config fix |

Under config F the equivalent minimum is `psum: 2048` B, since the demand of
the 6 infeasible layers is 2,048 B exactly.

The campaign does **not** apply any of these. The rejections are a faithful
consequence of modeling prosperity with a 1,024 B psum spad on a 4-PE node, so
"prosperity cannot map these layers at this node configuration" is a result to
report rather than a defect to paper over. Widening psum would alter every
prosperity cost number in the campaign, not just the rejected layers.

## 6. Scope

Settled here: which layers the solver rejects and why, under both
configurations, and why the 3x3 layers do not generate.

Not addressed here:

1. The `dram_num_steps x noc_num_steps x prod(spatial_factors)` factorization of
   any `tile_count` needs the solved schedule JSONs, which are not on this host.
   See `layer_dim_coverage.md`.
2. The manifest's **30 `excluded_pairs`** are a separate question from these
   infeasible pairs; mapping those to shape classes or loader policy is step
   1c's remaining work.
3. Counts in `layer_dim_coverage.md` derived from `schedule_tiles.csv` describe
   the pre-finalization solve and need a refresh once prosperity re-solves.

## 7. Reproducing

- Analytic predicate over all 157 layers: parses `LAYER_SHAPES.md` and applies
  the psum inequality; reimplements `_max_product_leq` (`node_capacity.py`) and
  `_largest_divisor_leq` (`node_level.py`).
- Solver + IIS: builds the model from the campaign `arch.yaml` and
  `mapspaces/prosperity.yaml` via the scheduler's own constraint functions,
  with a 7-key `problem:` workload YAML (`KH, KW, CIN, COUT, HO, WO, T`) as
  `SNNProb` expects, then `computeIIS()`. Config K is reproduced by restoring
  the `KH: 4, KW: 4, HO: 4, WO: 4` caps in a scratch copy of the mapspace.
- Both drivers are throwaway scripts under this session's scratchpad, not repo
  files; they import `lays` from `src/` and write nothing into the repo.
