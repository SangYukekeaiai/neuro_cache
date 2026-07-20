# SNN NoC Simulator Design

## Dimension Notation

| Dimension | Index | Indexes tensor | Notes |
|-----------|-------|----------------|-------|
| KH        | j=0   | weight         | K-dim: psum reduction |
| KW        | j=1   | weight         | K-dim: psum reduction |
| CIN       | j=2   | weight         | K-dim: psum reduction |
| COUT      | j=3   | weight, psum, vmem | N-dim |
| HO        | j=4   | psum, vmem     | M-dim: weight-invariant |
| WO        | j=5   | psum, vmem     | M-dim: weight-invariant |
| T         | j=6   | psum           | T-dim: vmem reduction dim; weight-invariant |

## Variables

- **weight**: `KH × KW × CIN × COUT`, load-only
- **psum**: `HO × WO × COUT × T`, load + store
- **vmem**: `HO × WO × COUT`, load + store

### Dimension Type Classification

| Type | Dimensions | Role |
|------|------------|------|
| K-dims | KH, KW, CIN | Reduction for psum; index weight |
| N-dims | COUT | Index weight, psum, vmem |
| M-dims | HO, WO | Index psum and vmem; weight-invariant |
| T-dim  | T | Index psum; reduction dim for vmem; weight-invariant |

Weight-invariant dimensions (do not affect weight values): **{HO, WO, T}**

---

## DRAM Traffic-Free Categories

| Category | Condition |
|---|---|
| **Both-Traffic-Free** | K-dims and T are both innermost or absent from the DRAM temporal loop |
| **Vmem-Traffic-Free** | T is the innermost DRAM temporal dimension (xxxT pattern) |
| **Psum-Traffic-Free** | K-dims are the innermost DRAM temporal dimension (oToK pattern) |

Both-traffic-free patterns (outer → inner):

| Pattern | Description |
|---|---|
| OOOO | No K-dims and no T at DRAM temporal level |
| OOOT | T innermost at DRAM temporal; no K-dims |
| OOOK | K-dims innermost at DRAM temporal; no T |
| OOTK | K-dims innermost, T directly above K-dims |

---

## DRAM Traffic Rules

### Psum

**Reduction dims: K = {KH, KW, CIN}** | **Tile: HO × WO × COUT × T**

The DRAM temporal loop may contain **multiple K factors** (K-dim split and interleaved with non-K dims, e.g. K1–M–K2–N). Let all K-dim factors present in the DRAM temporal loop be K₁, K₂, …, Kₙ.

Traffic occurs at **every K-dim tile** — i.e., at every combination of K-factor indices — for all positions of the inner loops (T, HO, WO, COUT). The action depends on the **joint position across all K factors**:

| Condition | Action |
|-----------|--------|
| ALL K factors at their **first** index | STORE only (no load) |
| ALL K factors at their **last** index | LOAD only (no store) |
| Any other combination | LOAD → STORE |

No-load at the **all-first** combination: psum has not yet been written to DRAM, so there is nothing to reload.  
No-store at the **all-last** combination: psum is fully accumulated and immediately consumed by vmem.

---

### Vmem

**Reduction dim: T** | **Tile: HO × WO × COUT**

The DRAM temporal loop may similarly contain **multiple T factors** (T₁, T₂, …, Tₘ).

Traffic occurs **only when all K factors are simultaneously at their last index** (vmem cannot be updated until psum's full K-reduction is complete). At that point, the action depends on the **joint position across all T factors**:

| Condition | Action |
|-----------|--------|
| ALL T factors at their **first** index | STORE only (no load) |
| ALL T factors at their **last** index | LOAD only (no store) |
| Any other combination | LOAD → STORE |

No-store at the **all-last T** combination: applies to **all** (HO, WO, COUT) positions at that point — not just the last combination of those dims.

**Key contrast with psum**: psum has traffic at every K-dim tile; vmem has traffic only at the all-last-K tick because vmem cannot be updated until psum's K-reduction is complete.

**Single-factor special case**: when only one K factor (or one T factor) is present, "all at first/last" reduces to "first/last", recovering the original single-dimension rule exactly.

---

---

## GB Traffic-Free Categories

Same categories as DRAM, evaluated against the **integrated temporal loop (DRAM dims outer, GB dims inner)**:

| Category | Condition (integrated DRAM + GB temporal loop) |
|---|---|
| **Both-Traffic-Free** | K-dims and T are both innermost or absent from the integrated temporal loop |
| **Vmem-Traffic-Free** | T is the innermost dimension of the integrated temporal loop |
| **Psum-Traffic-Free** | K-dims are the innermost dimensions of the integrated temporal loop |

A K factor at DRAM level blocks Psum-Traffic-Free even if K is innermost at GB level, because the outer DRAM-level K loop causes psum state to cross the GB boundary.

---

## Single-Node Mode

`arch.single_node: true` is a pure hardware-topology flag (no Global Buffer
exists): every `DRAM→GB→node` / `node→GB→DRAM` transaction pair collapses
into one direct `DRAM↔node` transaction. It no longer implies anything about
how the schedule is produced — the schedule is always MIP-solved, same as
any other arch. (**Superseded**: this used to also bypass the MIP solver
entirely via `model/fixed_schedule.py::build_fixed_x()`, hand-fixing both
the NodeLevel tile size and the *entire* DRAM permutation order via
`node_dims`/`dram_order`. That's gone — per-dimension NodeLevel capacity is
now a real MIP constraint, `arch.node_dim_capacity` /
`model/constraints/node_capacity.py`, and the solver remains free to choose
the DRAM permutation order itself.) See `PLAN_single_node.md` for the
GB-elision design and `configs/arch/snn_arch_single_node.yaml` for an
example config.

---

## Node Layout

The 2D mesh NoC maps PE IDs to `(x, y)` coordinates:
- `x = pe_id % X` — column, left → right
- `y = pe_id // X` — row, top → bottom

Two layout conventions are supported.

---

### Way 1: CoSA NoC Simulator Rule

PE IDs are assigned by iterating the spatial loops **innermost-first**. The innermost spatial loop varies fastest and fills the x axis before the y axis.

For spatial loops listed `[dim_A (innermost), dim_B, dim_C (outermost)]` with sizes A_s, B_s, C_s:

```
pe_id = C_idx × (B_s × A_s) + B_idx × A_s + A_idx
x     = pe_id % X
y     = pe_id // X
```

**Example — M=2, N=2, K=3, T=3, spatial loop order [T (inner), M, K, N (outer)], X = T_s × M_s = 6:**

```
pe_id |  T  |  M  |  K  |  N  |  x  |  y
------+-----+-----+-----+-----+-----+-----
  0   |  0  |  0  |  0  |  0  |  0  |  0
  1   |  1  |  0  |  0  |  0  |  1  |  0
  2   |  2  |  0  |  0  |  0  |  2  |  0
  3   |  0  |  1  |  0  |  0  |  3  |  0
  4   |  1  |  1  |  0  |  0  |  4  |  0
  5   |  2  |  1  |  0  |  0  |  5  |  0
  6   |  0  |  0  |  1  |  0  |  0  |  1
  7   |  1  |  0  |  1  |  0  |  1  |  1
  ...
 35   |  2  |  1  |  2  |  1  |  5  |  5
```

The x/y assignment **depends entirely on the spatial loop order in the timeloop subnest XML** — there is no fixed geometric meaning for M, N, K, T on the grid axes.

---

### Way 2: T×K Base Tile with M×N Outer Tiling

The NoC is structured as a regular grid of K×T sub-tiles, replicated M times along X and N times along Y:

- **T** — column within each sub-tile (left → right, fast-varying in X)
- **K** — row within each sub-tile (top → down, fast-varying in Y)
- **M** — sub-tile column block index (slow-varying in X)
- **N** — sub-tile row block index (slow-varying in Y)

```
x = m_idx × T_s + t_idx        (total columns X = M_s × T_s)
y = n_idx × K_s + k_idx        (total rows    Y = N_s × K_s)

pe_id = y × X + x
      = (n × K_s + k) × (M_s × T_s) + (m × T_s + t)
```

**Example — M=2, N=2, K=3, T=3 → 6×6 NoC:**

Block-level view (each cell is a K(3)×T(3) sub-tile):

```
                M=0              M=1
         [K(3) × T(3)]    [K(3) × T(3)]
N=0:     N=0, M=0 block   N=0, M=1 block
N=1:     N=1, M=0 block   N=1, M=1 block
```

Expanded PE grid (row = y, column = x):

```
         t=0  t=1  t=2  t=0  t=1  t=2
         m=0  m=0  m=0  m=1  m=1  m=1
k=0,n=0:  0    1    2    3    4    5
k=1,n=0:  6    7    8    9   10   11
k=2,n=0: 12   13   14   15   16   17
k=0,n=1: 18   19   20   21   22   23
k=1,n=1: 24   25   26   27   28   29
k=2,n=1: 30   31   32   33   34   35
```

This is equivalent to CoSA Way 1 with the fixed loop order **[T (innermost), M, K, N (outermost)]**, but states the intent as a geometric layout constraint: the K×T sub-tile is the atomic unit, tiled by M (horizontal) and N (vertical).

---

## GB Traffic Rules (GB ↔ Node)

The GB↔node transaction rules mirror the DRAM rules exactly. The only difference is that the reduction-dimension position check spans the **integrated loop across both DRAM and GB levels**.

### Psum

**All K-dim factors across DRAM and GB levels** form the combined factor set: K₁^D, K₂^D, …, K₁^G, K₂^G, …

Traffic occurs at every GB-level K-dim tile. The action depends on the **joint position of all K factors (DRAM + GB)**:

| Condition | Action |
|-----------|--------|
| ALL K factors (DRAM + GB) at their **first** index | STORE only (no load) |
| ALL K factors (DRAM + GB) at their **last** index | LOAD only (no store) |
| Any other combination | LOAD → STORE |

---

### Vmem

**All T-dim factors across DRAM and GB levels** form the combined factor set: T₁^D, …, T₁^G, …

Traffic occurs only when **all K factors (DRAM + GB) are simultaneously at their last index**. The action depends on the **joint position of all T factors (DRAM + GB)**:

| Condition | Action |
|-----------|--------|
| ALL T factors (DRAM + GB) at their **first** index | STORE only (no load) |
| ALL T factors (DRAM + GB) at their **last** index | LOAD only (no store) |
| Any other combination | LOAD → STORE |

---

### Spatial Unrolling

#### Multicast vs. Unicast

| Spatial unrolling | Traffic type from GB |
|---|---|
| Reduction dim (K or T) is spatially unrolled | **Multicast**: same data sent to multiple nodes |
| No reduction dim is spatially unrolled | **Unicast**: each node receives distinct data |

#### Psum: Load/Store Node Target

When K is spatially unrolled, nodes form a K-reduction chain (K₀ → K₁ → … → K_max). The partial psum that must persist across temporal K tile boundaries resides at the tail of the chain. Both load and store target the **node with the largest K spatial index (K_max)**:

| Transaction | Direction | Node target |
|---|---|---|
| Load | GB → node | Largest K spatial index (K_max) |
| Store | Node → GB | Largest K spatial index (K_max) |

#### Vmem: Load/Store Node Target

When T is spatially unrolled, nodes form a T-reduction chain (T₀ → T₁ → … → T_max). The vmem value from the previous temporal T tile re-enters at the head of the chain and the updated vmem exits at the tail. Load and store therefore target **different ends of the chain**:

| Transaction | Direction | Node target |
|---|---|---|
| Load | GB → node | Smallest T spatial index (T₀) |
| Store | Node → GB | Largest T spatial index (T_max) |

---

### Weight

**Tile: KH × KW × CIN × COUT** | **Load-only, never stored.**

**Weight-invariant dims**: {HO, WO, T}

#### Loading Rule

**Step 1** — Find the **innermost contiguous reuse block**: starting from the innermost loop, walk outward including consecutive weight-invariant dims ({HO, WO, T}) until a weight-indexed dim ({KH, KW, CIN, COUT}) is hit.

**Step 2**:

| Condition | Load count |
|-----------|------------|
| Reuse block exists | Product of all loop iterations **outside** the block |
| Innermost dim is weight-indexed (no reuse block) | Product of **all** loop iterations |

#### Examples

| Loop order (outer → inner) | Innermost contiguous reuse block | Load count |
|----------------------------|----------------------------------|------------|
| T1-M1-N-T2                 | {T2}                             | T1 × M1 × N |
| N-M-T                      | {M, T}                           | N |
| M-N-T                      | {T}                              | M × N |
| N-M-K                      | none (K is weight-indexed)       | N × M × K |

---

## Node-to-Node Reduction Chains

Two independent reduction chains operate per NoC temporal step. Both are **pure serial chains** under the Way-2 layout (K owns Y, T owns X), so the general XY-reduction used by CoSA degenerates to a 1D chain in each axis.

### K-chain (psum reduction)

K-dims (KH, KW, CIN) are spatially unrolled along the **Y axis** (top → bottom). All K nodes in the same column hold partial psums for the same (COUT, HO, WO, T) output address and must be summed.

**Topology**: pure vertical serial chain within each column.

```
K=0 (y=0) ──→ K=1 (y=1) ──→ … ──→ K_max (y=K_s−1)
```

- Direction: top → bottom (increasing y, same x)
- Each node unicasts its accumulated partial sum to the node below
- **Tail node**: K_max (bottommost in the column) — holds the fully reduced psum
- GB load and store both target K_max (see Psum node target rules above)

### T-chain (vmem reduction)

T is spatially unrolled along the **X axis** (left → right). All T nodes in the same row hold partial vmem states for the same (COUT, HO, WO) address and must be chained through the LIF (integrate-and-fire) update.

**Topology**: pure horizontal serial chain within each row.

```
T=0 (x=0) ──→ T=1 (x=1) ──→ … ──→ T_max (x=T_s−1)
```

- Direction: left → right (increasing x, same y)
- Each node passes its updated vmem state to the next node to the right
- **Head node**: T=0 (T_min) — receives the vmem load from GB
- **Tail node**: T_max — produces the final vmem value, sends store to GB
- GB load targets T_min, GB store targets T_max (see Vmem node target rules above)

### Chain dependency

The T-chain **cannot start** until the K-chain is complete. vmem cannot be updated until the psum K-reduction is fully accumulated.

```
K-chain completes at K_max  →  T-chain begins at T_min
```

---

## Node Computation Cycles and Dependency Graph

### Computation phases per node

Each node runs two computation phases per NoC temporal step:

| Phase | Name | Trigger | Description |
|-------|------|---------|-------------|
| 1 | MAC COUNT | after weight + psum load | Multiply-accumulate: weight × input spike → accumulate into local psum |
| 2 | LIF COUNT | after K-chain completes (all-last-K only) | Integrate psum into vmem, compare threshold, generate spike, reset/decay vmem |

Phase 2 only executes when **all K factors (DRAM + GB + spatial) are simultaneously at their last index**.

### Full dependency graph per NoC temporal step

```
Load weight   (GB → all nodes, multicast)
      │
      ▼
Load psum     (GB → K_max node)          [skip if all-first-K]
      │
      ▼
MAC COUNT     (all nodes, in parallel)
      │
      ▼
K-chain       (K=0 → K=1 → … → K_max,   node-to-node unicast)
      │
      │  (only when all-last-K)
      ▼
Load vmem     (GB → T_min node)          [skip if all-first-T]
      │
      ▼
LIF COUNT + T-chain   (T=0 → T=1 → … → T_max,  integrate-fire + unicast)
      │
      ▼
Store vmem    (T_max → GB)               [skip if all-last-T]
      │
      ▼
Store psum    (K_max → GB)               [skip if all-last-K]
```

Weight load and psum load can overlap (both are prerequisites for MAC COUNT). The K-chain and T-chain are strictly sequential.

---

## Traffic Metric Tracking

The post-MIP NoC simulator tracks traffic using three per-variable counters,
each a dict keyed by `"weight"` / `"psum"` / `"vmem"` (always containing all
three keys, defaulting to 0):

| Counter | Accumulates when | Formula per transaction |
|---------|-----------------|------------------------|
| `unicast_hops[var]` | src == GB port, single destination, dest != DRAM port | `manhattan_dist(GB, node) + num_packets × flits_per_packet` |
| `multicast_hops[var]` | src == GB port, multiple destinations | `max(manhattan_dist(GB, node_i)) + num_packets × flits_per_packet` |
| `dram_cost[var]` | src == DRAM port **or** dest == DRAM port (either direction, same mechanism) | `num_packets × dram_latency` |

**Key rules:**

- `unicast_hops`/`multicast_hops` only fire when **source is the GB port**
  and the transfer stays on-chip (dest != DRAM port). Node-to-node reduction
  unicasts (K-chain, T-chain) and node-to-GB store unicasts do not
  accumulate `unicast_hops`.
- **Weight** is routed **GB → node** (not DRAM → node directly). Weight
  transactions therefore use GB as the source and are counted in
  `unicast_hops` or `multicast_hops` like any other GB-sourced send.
- For multicast (same weight tile or same psum/vmem tile broadcast to
  multiple nodes), the **farthest destination** sets the hop count —
  `max(manhattan_dist(GB, node_i))` over all nodes in the multicast group.
- **DRAM traffic** (DRAM↔GB loads/stores, `transactions/dram.py`) is
  excluded from `unicast_hops`/`multicast_hops` — DRAM access isn't modeled
  by mesh hop distance — but contributes to `dram_cost[var]` instead,
  weighted by `dram_latency` (configurable in the arch YAML, default 17 —
  CoSA parity: `gen_tc_io.py`'s `dram_latency = 17`). Both directions
  (DRAM→GB load and GB→DRAM store) follow the same mechanism; there is no
  direction-based exclusion.
- `unicast_hops[var] + multicast_hops[var]` is the on-chip NoC traffic cost
  for that variable; `dram_cost[var]` is the separate off-chip cost. The two
  are not summed together — they represent different physical resources.
