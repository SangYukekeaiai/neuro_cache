# SNN-CoSA Post-MIP NoC Simulator — Implementation Overview

---

## Concepts

### `buf_spatial`

`buf_spatial[var]` is a list of length = number of spatial PEs, indexed by `pe_id`.
Each entry is a tuple of spatial loop iteration indices — the **data address** that
`pe_id` accesses for variable `var`.

Dimensions that do not affect `var` (per the `_A` matrix in `model/constants.py`)
are **zeroed out**. PEs that differ only in irrelevant dimensions therefore land on
the same address, which is the mechanism that produces multicast groups vs. unicasts,
and identifies K-chain and T-chain reduction groups.

**Example** — K_s=2, T_s=2, M_s=2, N_s=2 (16 PEs), Way-2 order `[T, M, K, N]`:

```
PE at (t=1, m=0, k=1, n=0)  →  raw indices = [t=1, m=0, k=1, n=0]

  weight  (A: T→0, K→1):   zeroed = [t_z=0, m=0, k=1,   n=0]  →  "0_0_1_0"
  psum    (A: K→0, T→1):   zeroed = [t=1,   m=0, k_z=0, n=0]  →  "1_0_0_0"
  vmem    (A: K→0, T→0):   zeroed = [t_z=0, m=0, k_z=0, n=0]  →  "0_0_0_0"
```

`construct_addrs_dict(buf_spatial[var])` groups PEs by address:

| Address collision | Meaning |
|---|---|
| Same weight address | Same weight tile → **multicast** |
| Same psum address | Same K-reduction group → **K-chain** |
| Same vmem address | Same T-reduction group → **T-chain** |
| All addresses unique | Every PE gets distinct data → **unicast** |

`buf_spatial` is the single structure that drives every multicast, unicast,
K-chain, and T-chain decision in the simulator.

---

### NoC dimensions X and Y

Under the Way-2 layout:

```
X = M_s × T_s     (total columns:  T fast within M block, M selects block)
Y = N_s × K_s     (total rows:     K fast within N block, N selects block)

pe_id = y × X + x
      = (n × K_s + k) × (M_s × T_s) + (m × T_s + t)
```

The `NoC` class takes only `(X, Y)` as integers and has no knowledge of
M/N/K/T semantics.  The Way-2 geometric meaning is enforced by the
`buf_spatial` construction (canonical spatial loop order `[T, M, K, N]`).

---

## Project Structure

The simulator lives in a new subpackage `snn_cosa/nocsim/`, parallel to the
existing `model/` and `parsers/` subpackages.

```
src/snn_cosa/nocsim/
│
├── __init__.py
│
├── core/                      # infrastructure, reused/adapted from CoSA
│   ├── __init__.py
│   ├── noc.py                 # NoC class: (X,Y), GB port, hop counting
│   ├── transaction.py         # TC class, UNICAST/MULTICAST/COUNT ops, format_csv
│   └── generator.py           # TC_Generator: tc_id, unicast/multicast/count,
│                              #   unicast_hops/multicast_hops, write_deps/get_deps
│
├── schedule/                  # decode MIP solution into simulation-ready structures
│   ├── __init__.py
│   ├── decode.py              # x-vars → spatial_factors[dim], temporal_loops,
│   │                          #   data_size[var] at GB boundary
│   ├── buf_spatial.py         # build buf_spatial[var] (Way-2 order + _A zeroing);
│   │                          #   find_k_max / find_t_min / find_t_max helpers
│   └── steps.py               # steps[var][i], k_position[i], t_position[i]
│                              #   across all combined DRAM+GB temporal iterations
│
├── transactions/              # one file per traffic type; each returns new TC ids
│   ├── __init__.py
│   ├── weight.py              # GB → all nodes (multicast or unicast per addrs_dict)
│   ├── psum.py                # GB → K_max load; K-chain K=0→…→K_max; K_max → GB store
│   ├── vmem.py                # GB → T_min load; T-chain T=0→…→T_max; T_max → GB store
│   ├── compute.py             # MAC COUNT (all nodes) + LIF COUNT (all nodes)
│   └── dram.py                # DRAM ↔ GB: weight / psum / vmem loads and stores
│
├── combine.py                 # main nested loop: calls transaction builders in order,
│                              #   wires all double-buffer dependencies
│
├── eventsim/                  # compiled discrete-event latency backend (C++, optional)
│   ├── Makefile
│   ├── Transaction.h          # tc.csv parser
│   ├── NoC.h                  # XY routing, ported from core/noc.py
│   ├── EventSim.h             # the event loop: dependency + link/actor contention
│   └── main.cpp               # CLI: tc.csv + X/Y/dram-port/dram-latency → JSON summary
│
└── sim.py                     # entry point: MIP result + prob + arch → CSV + hop counts;
                               #   optional --simulate shells out to eventsim
```

**Single-node mode** (`arch.single_node: true`, see `PLAN_single_node.md`):
a pure hardware-topology flag, not a scheduling shortcut. `combine()` takes
an optional `arch` parameter; when `arch.single_node` is set, every
GB-mediated `DRAM→GB→node` / `node→GB→DRAM` transaction pair collapses into
one direct `DRAM↔node` transaction (the Global Buffer does not exist in
this mode). The schedule itself is always MIP-solved — CLI:
`python -m snn_cosa.nocsim.sim --schedule ... --layer ... --arch ... --out ...`,
`--schedule` always required. (**Superseded**: this used to also bypass the
MIP solver via `model/fixed_schedule.py`'s `build_fixed_x()`, constructing
`x[(i,j,n,k)]` from hand-fixed `node_dims`/`dram_order` arch inputs. Removed
— NodeLevel capacity is now `arch.node_dim_capacity`, enforced as a real MIP
constraint by `model/constraints/node_capacity.py`, leaving the DRAM
permutation order for the solver to decide.)

**10 Python source files** plus the `eventsim/` C++ module, each with a single
responsibility and an estimated 60–150 lines (eventsim's files are similarly
scoped). `unicast_hops`/`multicast_hops`/`dram_cost` (from `combine()`) are
static, non-contention-aware cost proxies used during MIP search; `eventsim`
is a separate, contention-aware discrete-event simulation over the same TC
list, used to get an actual simulated latency number after a schedule is
already chosen.

---

## Input and Output

### Input

`sim.py` accepts objects already in memory from the MIP phase — no new file
formats are introduced:

| Argument | Type | Source |
|---|---|---|
| `x` | `Dict` | Solved Gurobi variables from `solver.py` |
| `y` | `Dict` | Solved Gurobi variables from `solver.py` |
| `prob` | `SNNProb` | Parsed by `parsers/layer.py` |
| `arch` | `SNNArch` | Parsed by `parsers/arch.py` |
| `bitwidths` | `SNNBitwidths` | Parsed by `parsers/bitwidths.py` |
| `out_file` | `Path` | Destination CSV path |

### Output

A CSV file in the same format as CoSA's `tc.csv`:

```
# annotation string
tc_id, actor_id, op, size, src, dest, dep
```

`sim.py` also returns `(unicast_hops, multicast_hops, dram_cost)` as the
summary cost — each a per-variable dict keyed by `"weight"`/`"psum"`/
`"vmem"`. `dram_cost` weights DRAM-touching traffic (either direction) by
the arch YAML's `dram_latency` (default 17, CoSA parity); it is tracked
separately from the on-chip hop counters, not summed into them.

---

## Module Responsibilities

### `core/noc.py`

Owns the NoC topology.  Identical role to CoSA's `NoC` class.

- Stores `X`, `Y`, `globalbuf_port`, `dram_port`
- `get_xy_coordinate(pe_id)` → `(x, y)`
- `count_hops_single(src, dest)` → list of link pairs (XY routing)
- `count_hops(src, dests)` → number of unique links (deduplicates shared segments)

GB port defaults to bottom-left under Way-2: `pe_id = X * (Y + 1) - X` = `(x=0, y=Y)`.
Overridable via constructor argument.

---

### `core/transaction.py`

Owns the TC data structure.

- `TC(tc_id, actor_id, op, deps, var_name, entries, annotation)`
- Operations: `UNICAST = 0`, `MULTICAST = 1`, `COUNT = 2`
- `TC.format_csv()` → one CSV row + comment line

---

### `core/generator.py`

Owns the running state of the simulation: the TC list, dependency map, and
per-variable cost counters.

- `TC_Generator(noc, dram_latency=17)` — takes a constructed `NoC`
- `unicast(var, size_bits, datawidth, src, dest, deps, label)` — appends TC;
  updates `unicast_hops[var]` if `src == gb_port and dest != dram_port`;
  updates `dram_cost[var]` if `src == dram_port or dest == dram_port`
- `multicast(var, size_bits, datawidth, src, dests, deps, label)` — appends
  TC, updates `multicast_hops[var]` with farthest-node rule if
  `src == gb_port` (never DRAM-sourced in this simulator)
- `count(cycles, node_id, deps, label)` — appends COUNT TC
- `get_deps(dep_labels, pe_id=-1)` → list of TC ids
- `to_file(path)` — writes CSV

---

### `schedule/decode.py`

Translates the solved `x[(i,j,n,k)]` binary variables into concrete loop structures.

The MIP assigns factor *magnitudes* to levels but not inner-to-outer ordering within
a level.  `decode.py` applies the canonical Way-2 spatial order
`[T (innermost), M, K, N (outermost)]` and accepts a user-supplied ordering policy
for temporal loops (or uses a default outer-to-inner order matching the MIP level
hierarchy).

Outputs:
- `spatial_factors: Dict[str, int]` — e.g. `{T: 3, M: 2, K: 4, N: 2}`
- `noc_temporal_loops: List[LoopItem]` — GB↔node temporal loops, inner → outer
- `dram_temporal_loops: List[LoopItem]` — DRAM↔GB temporal loops, inner → outer
- `data_size: Dict[str, int]` — element count per GB tile for weight, psum, vmem

---

### `schedule/buf_spatial.py`

Builds `buf_spatial[var]` by iterating the spatial loops in Way-2 order and zeroing
irrelevant dimensions via `_A`.  Also exposes three lookup helpers used by the
transaction builders:

- `find_k_max(buf_spatial_psum)` → `pe_id` of the K-chain tail (largest K index)
- `find_t_min(buf_spatial_vmem)` → `pe_id` of the T-chain head (smallest T index)
- `find_t_max(buf_spatial_vmem)` → `pe_id` of the T-chain tail (largest T index)

---

### `schedule/steps.py`

Iterates all combined DRAM+GB temporal steps and emits per-step flags consumed by
`combine.py`.

- `steps[var][i]` — `1` if variable `var` has GB traffic at step `i`, else `0`
- `k_position[i]` — `(is_first_K, is_last_K)` across all DRAM+GB K factors combined
- `t_position[i]` — `(is_first_T, is_last_T)` across all DRAM+GB T factors combined

These mirror the K/T position logic described in the DRAM and GB traffic rules in
`NOC_SIM_DESIGN.md`.

---

### Traffic-Free Categories

Structural flags computed **once** from the schedule (not per-step).  They determine
whether entire classes of transactions can be omitted, independent of the per-step
first/last K/T position logic in `steps.py`.

#### DRAM traffic-free (from `dram_temporal_loops` only)

| Category | Condition (DRAM temporal loop) | Effect |
|---|---|---|
| **Both-Traffic-Free** | K-dims and T both innermost or absent | Skip ALL psum and vmem DRAM traffic |
| **Vmem-Traffic-Free** | T is the innermost DRAM temporal dimension | Skip ALL vmem DRAM load/store |
| **Psum-Traffic-Free** | K-dims are the innermost DRAM temporal dimensions | Skip ALL psum DRAM load/store |

Both-traffic-free patterns (outer → inner):

| Pattern | Description |
|---|---|
| OOOO | No K-dims and no T at DRAM temporal level |
| OOOT | T innermost at DRAM temporal; no K-dims |
| OOOK | K-dims innermost at DRAM temporal; no T |
| OOTK | K-dims innermost, T directly above K-dims |

#### GB traffic-free (from integrated DRAM + GB temporal loop)

Same categories, evaluated against the **integrated temporal loop** (DRAM dims outer,
GB dims inner):

| Category | Condition (integrated DRAM + GB temporal loop) |
|---|---|
| **Both-Traffic-Free** | K-dims and T both innermost or absent from the integrated loop |
| **Vmem-Traffic-Free** | T is the innermost dimension of the integrated loop |
| **Psum-Traffic-Free** | K-dims are the innermost dimensions of the integrated loop |

---

### `transactions/weight.py`

Generates GB → node weight load transactions.  Weight is **not** loaded at every
NoC temporal step — it is reloaded only when a weight-indexed dimension
(KH, KW, CIN, COUT) actually advances.

#### Loading rule (mirrors CoSA `iter_start_dim` logic)

1. Find `iter_start_dim` = the index of the **innermost** temporal loop that
   contains a weight-indexed dimension.  All loops at indices below this are
   weight-invariant ({HO, WO, T}) and form the **reuse block**.
2. Weight traffic fires at the first iteration of every outer block, i.e.,
   only when all inner reuse-block loop indices are 0.
3. Load count = product of loop bounds **outside** the reuse block.

| Loop order (outer → inner) | Innermost contiguous reuse block | Load count |
|---|---|---|
| T1–M1–N–T2 | {T2} | T1 × M1 × N |
| N–M–T | {M, T} | N |
| M–N–T | {T} (N breaks continuity) | M × N |
| N–M–K | none (K is weight-indexed) | N × M × K |

M represents outer HO/WO factors; {HO, WO, T} are all weight-invariant.

#### Send pattern

For each address group in `BufSpatial.addr_groups(bs.weight)`:
- 1 PE in group → `generator.unicast(src=gb_port, dest=pe)`
- >1 PEs in group → `generator.multicast(src=gb_port, dests=pes)`

Weight is load-only; there is no store transaction.

---

### `transactions/psum.py`

Three functions, called in order:

1. `load_psum(gen, k_max, data_size, deps)` — `generator.unicast(gb_port → k_max)`; skip if `is_first_K`
2. `k_chain(gen, buf_spatial_psum, data_size, deps)` — serial vertical unicasts along Y:
   `K=0 → K=1 → … → K_max`; returns TC ids for each link
3. `store_psum(gen, k_max, data_size, deps)` — `generator.unicast(k_max → gb_port)`; skip if `is_last_K`

---

### `transactions/vmem.py`

Three functions, called in order:

1. `load_vmem(gen, t_min, data_size, deps)` — `generator.unicast(gb_port → t_min)`; skip if `is_first_T`
2. `t_chain(gen, buf_spatial_vmem, data_size, deps)` — serial horizontal unicasts along X:
   `T=0 → T=1 → … → T_max`; returns TC ids for each link
3. `store_vmem(gen, t_max, data_size, deps)` — `generator.unicast(t_max → gb_port)`; skip if `is_last_T`

---

### `transactions/compute.py`

Two functions:

1. `mac_count(gen, all_node_ids, pe_cycles, deps)` — one `generator.count(pe_cycles, node_id, deps)` per node, all in parallel (same deps, independent TCs)
2. `lif_count(gen, all_node_ids, lif_cycles, deps)` — same pattern for LIF integrate-and-fire phase

`lif_count` is only called when `is_last_K` is true.

---

### `transactions/dram.py`

Generates DRAM ↔ GB transactions for each DRAM temporal step.

- `load_from_dram(gen, var, data_size, deps)` — `generator.unicast(dram_port → gb_port)`
- `store_to_dram(gen, var, data_size, deps)` — `generator.unicast(gb_port → dram_port)`

Called once per DRAM step for each variable that has traffic at that step.

---

### `combine.py`

The main nested loop.  Calls all transaction builders in the correct order and wires
the double-buffer dependency pattern throughout.

```
for dram_i in range(dram_num_steps):

    dram.load_from_dram(weight, ...)
    dram.load_from_dram(psum, ...)     # [skip if is_first_K at dram level]
    dram.load_from_dram(vmem, ...)     # [skip if is_first_T, only at all-last-K]

    for noc_i in range(noc_num_steps):

        # 1. Weight: GB → all nodes
        weight.load(...)
        #   dep: weight.load[noc_i-1]      (sequential GB sends, avoid bank collision)
        #        compute.mac[noc_i-2]       ← node double-buffer: bank freed 2 steps ago

        # 2. Psum load: GB → K_max         [skip if is_first_K]
        psum.load_psum(...)
        #   dep: psum.store_psum[noc_i-2]  ← GB double-buffer: bank freed
        #        dram.load_from_dram(psum)  (DRAM→GB must have landed)

        # 3. MAC COUNT — all nodes, parallel
        compute.mac_count(...)
        #   dep: weight.load[noc_i]
        #        psum.load_psum[noc_i]  (if loaded)
        #        compute.mac[noc_i-2]       ← node double-buffer

        # 4. K-chain: K=0 → … → K_max
        psum.k_chain(...)
        #   dep: compute.mac[noc_i]

        # 5. Psum store: K_max → GB        [skip if is_last_K]
        psum.store_psum(...)
        #   dep: psum.k_chain[noc_i]

        if is_last_K:

            # 6. Vmem load: GB → T_min     [skip if is_first_T]
            vmem.load_vmem(...)
            #   dep: vmem.store_vmem[vmem_step-2]  ← GB double-buffer: bank freed
            #        dram.load_from_dram(vmem)
            #
            #   NOTE: index is vmem_step (counting only is_last_K firings),
            #   NOT raw noc_i.  vs_hist is sparse (populated only at is_last_K
            #   noc_i values), so noc_i-2 would miss the correct entry whenever
            #   K is a NoC temporal dimension (consecutive is_last_K steps are
            #   separated by K_noc × N_inner raw noc_i steps, not 2).
            #   A rolling ring buffer of size 2 (vmem_store_ring) is used instead.

            # 7. LIF COUNT — all nodes, parallel
            compute.lif_count(...)
            #   dep: psum.k_chain[noc_i]
            #        vmem.load_vmem[noc_i]  (if loaded)
            #        compute.lif[vmem_step-2]  ← node double-buffer
            #
            #   Same issue as vmem load: lif_hist is sparse (only is_last_K),
            #   so a separate lif_ring rolling buffer of size 2 is used.

            # 8. T-chain: T=0 → … → T_max
            vmem.t_chain(...)
            #   dep: compute.lif[noc_i]

            # 9. Vmem store: T_max → GB    [skip if is_last_T]
            vmem.store_vmem(...)
            #   dep: vmem.t_chain[noc_i]

    dram.store_to_dram(vmem, ...)      # [skip if is_last_T at dram level]
    dram.store_to_dram(psum, ...)      # [skip if is_last_K at dram level]
```

#### Double-buffer dependency pattern

Both GB and node buffers are double-buffered.  This relaxes "wait for previous step"
from `i-1` to `i-2`:

| Buffer | Resource freed at | Index space | Dependency offset |
|--------|------------------|-------------|-------------------|
| GB psum load bank | After node finishes consuming it | raw `noc_i` | `noc_i-2` store |
| GB vmem load bank | After node finishes consuming it | **vmem-step** (is_last_K firings only) | `vmem_step-2` store |
| Node weight buffer | After MAC COUNT finishes | raw `noc_i` | `noc_i-2` MAC COUNT |
| Node vmem buffer (LIF) | After LIF COUNT finishes | **vmem-step** (is_last_K firings only) | `vmem_step-2` LIF COUNT |

**Key distinction — psum vs vmem index space:**

- `ps_hist` and `mac_hist` are populated at **every** `noc_i` (psum store fires at every
  non-is_last_K step; MAC fires every step), so `noc_i-2` always lands on a valid entry.

- `vs_hist` and `lif_hist` are populated **only at is_last_K steps**.  When K appears in
  `noc_temporal_loops` (K has NoC-level temporal iterations), consecutive is_last_K steps
  are separated by `K_noc × N_inner` raw noc_i steps — far more than 2.  Using `noc_i-2`
  would always land on a non-is_last_K noc_i, returning an empty dict and dropping the
  dependency entirely.

**Implementation — ring buffer for vmem/LIF:**

Instead of `vs_hist.get(noc_i-2, {})`, a rolling `collections.deque` of size 2
(`vmem_store_ring`) accumulates only the TC dicts from is_last_K steps:

```python
vmem_store_ring: deque  # length ≤ 2; each entry is the vs_tcs dict from one is_last_K step
lif_ring:        deque  # same for lif_tcs

# at each is_last_K step:
vl_deps_ring = _vals(vmem_store_ring[-2]) if len(vmem_store_ring) >= 2 else []
lif_deps_ring = _vals(lif_ring[-2])       if len(lif_ring) >= 2 else []
# ... after computing vs_tcs and lif_tcs:
vmem_store_ring.append(vs_tcs); lif_ring.append(lif_tcs)
```

`mac_hist` and `ps_hist` continue using raw `noc_i` since those histories are dense.

---

### `sim.py` — entry point

```python
def run(x, y, prob, arch, bitwidths, out_file: Path) -> tuple[dict, dict, dict]:
    schedule  = decode(x, prob, arch)
    buf_sp    = build_buf_spatial(schedule, prob)
    step_info = build_steps(schedule, prob)
    gen       = combine(schedule, buf_sp, step_info, arch, bitwidths)
    gen.to_file(out_file)
    return (gen.unicast_hops, gen.multicast_hops, gen.dram_cost)
```

Callable from `cli.py` as an additional subcommand after the MIP solve completes.

---

## Traffic Metric Rules (summary)

Each counter is a dict keyed by `"weight"`/`"psum"`/`"vmem"`.

| Counter | Fires when | Formula |
|---------|-----------|---------|
| `unicast_hops[var]` | `src == gb_port`, single dest, `dest != dram_port` | `dist(GB, node) + packets × flits_per_packet` |
| `multicast_hops[var]` | `src == gb_port`, multiple dests | `max(dist(GB, node_i)) + packets × flits_per_packet` |
| `dram_cost[var]` | `src == dram_port` or `dest == dram_port` (either direction) | `packets × dram_latency` |

Transactions **excluded** from `unicast_hops`/`multicast_hops`:
- K-chain unicasts (node → node)
- T-chain unicasts (node → node)
- Node → GB store unicasts
- DRAM ↔ GB unicasts (tracked in `dram_cost` instead)

No separate weight cost field beyond the same `var`-keyed dicts.  Weight
loads go GB → node and are counted in `unicast_hops` / `multicast_hops`
like any other GB-sourced send; weight's DRAM→GB load is counted in
`dram_cost["weight"]`.
