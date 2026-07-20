# NoC Transaction Dependency Specification

Dependencies for every TC emitted by `combine.py`. Each TC must list all TC ids
it waits on before it may start. Dependencies fall into three categories:

- **D — Data**: the source data must be committed before the consumer reads it.
- **B — Buffer**: a shared double-buffer slot must be free before it can be reused.
- **S — Sequence**: resource contention (single GB port, DRAM bus) enforces order.

---

## Index of variables

| Variable | Acronym | Lives in    | Indexed by          |
|----------|---------|-------------|---------------------|
| Weight   | W       | GB → PE     | KH, KW, CIN, COUT   |
| Psum     | P       | GB ↔ PE     | KH, KW, CIN         |
| Vmem     | V       | GB ↔ PE     | COUT, HO, WO        |

---

## Hierarchy 1 — DRAM ↔ GB  (per `dram_i`)

These transactions fire once per outer `dram_i` iteration, outside the inner
`noc_i` loop.

### `load_weight_dram`  (DRAM → GB)

Always fires. No prior DRAM weight store exists.

| Dep TC | Type | Reason |
|--------|------|--------|
| *(none)* | — | First operation; DRAM weight is fixed input |

### `load_psum_dram`  (DRAM → GB)

Skipped when `is_first_K_dram` or `is_psum_dram_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `prev_dram_psum_store` (dram_i-1) | S | DRAM store from prior outer step must finish before reloading the same DRAM bank |

### `load_vmem_dram`  (DRAM → GB)

Skipped when `not is_last_K_dram` or `is_first_T_dram` or `is_vmem_dram_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `prev_dram_vmem_store` (dram_i-1) | S | DRAM vmem store from prior outer step must finish before reloading |

### `store_psum_dram`  (GB → DRAM)

Skipped when `is_last_K_dram` or `is_psum_dram_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `store_psum_gb[last_noc]` or `k_chain_tails[last_noc]` | D | Latest partial sum must be in GB before DRAM writeback |

### `store_vmem_dram`  (GB → DRAM)

Skipped when `not is_last_K_dram` or `is_last_T_dram` or `is_vmem_dram_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `store_vmem_gb[last_noc]` or `t_chain_tails[last_noc]` | D | Latest vmem must be in GB before DRAM writeback |

---

## Hierarchy 2 — GB ↔ PE  (per `noc_i` within a `dram_i`)

History variables used below:

- `w_hist[noc_i]`   — `load_weight` TC dict at step `noc_i`
- `mac_hist[noc_i]` — `mac_count` TC dict at step `noc_i`
- `ps_hist[noc_i]`  — `store_psum` TC dict at step `noc_i`
- `vmem_store_ring` — `deque(maxlen=2)` of `store_vmem` TC dicts, one per vmem-step
- `lif_ring`        — `deque(maxlen=2)` of `lif_count` TC dicts, one per vmem-step

> **vmem-step vs raw noc_i**: `vs_hist` and `lif_hist` are populated only at
> `is_last_K` steps. When K has NoC-level temporal factors, consecutive
> `is_last_K` events are `K_noc_steps` raw noc_i apart (not 2). The ring
> buffers count only vmem-steps, so `[-2]` always means "2 vmem events ago".

### Step 1: `load_weight`  (GB → all PEs, broadcast)

Always fires unless `weight_changes()` is False.

| Dep TC | Type | Reason |
|--------|------|--------|
| `w_hist[noc_i-1]` or `load_weight_dram` at noc_i=0 | S | GB weight bank has one port; only one send at a time |
| `mac_hist[noc_i-2]` (if noc_i ≥ 2) | B | PE weight buffer is double-buffered; slot freed when MAC 2 steps ago completed |

### Step 2: `load_psum`  (GB → K_max PE per group)

Skipped when `is_first_K` or `is_psum_gb_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `ps_hist[noc_i-2]` (if noc_i ≥ 2) | B | GB psum buffer is double-buffered; the slot reused at `noc_i` was last written at `noc_i-2` |
| `ps_hist[noc_i - T_noc_steps]` (if noc_i ≥ T_noc_steps) | D | **Same-T data ordering**: for T-inner-K loops, the psum for temporal-T index `t` is stored at `noc_i = k*T_noc + t` and loaded at `noc_i = (k+1)*T_noc + t`; the prior K's store at `noc_i - T_noc_steps` must commit before this load reads it |
| `load_psum_dram` (if present) | D | DRAM psum tile must have landed in GB first |

> `T_noc_steps = _dim_totals(schedule.noc_temporal_loops).get(DIM_T, 1)`
> When `is_psum_gb_free` is True this step is skipped entirely, so dep #2 is moot.
> When `T_noc_steps == 2`, dep #1 (offset -2) and dep #2 (offset -T_noc_steps)
> coincide and there is no bug; bugs appear only for T_noc_steps ≥ 3.

### Step 3: `mac_count`  (all PEs, parallel)

Always fires.

| Dep TC | Type | Reason |
|--------|------|--------|
| `w_hist[noc_i]` | D | Weights must have arrived at each PE |
| `ps_hist_load[noc_i]` (if psum was loaded) | D | Carry-over partial sum must have arrived |
| `mac_hist[noc_i-2]` (if noc_i ≥ 2) | B | PE MAC buffer is double-buffered; node must have finished the MAC 2 steps ago |

### Step 4: `k_chain`  (K=0 → K=1 → … → K_max, serial per group)

| Dep TC | Type | Reason |
|--------|------|--------|
| `mac_hist[noc_i]` (all PEs) | D | All PEs must finish MAC before K=0 forwards its partial sum |
| `k_chain_link[i-1]` (within group) | D | Serial propagation: each link waits for the previous link in the same group |

### Step 5: `store_psum`  (K_max PE → GB per group)

Skipped when `is_last_K` or `is_psum_gb_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `k_chain_tails[noc_i]` | D | K-chain result (accumulated partial sum) must be ready |

---

## Hierarchy 2 (vmem path) — fires only when `is_last_K`

### Step 6: `load_vmem`  (GB → T_min PE per group)

Skipped when `is_first_T` or `is_vmem_gb_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `vmem_store_ring[-2]` (if ring size ≥ 2) | B | GB vmem buffer is double-buffered; slot freed 2 vmem-steps ago |
| `vmem_store_ring[-1]` (if ring size ≥ 1) | D | **Prev-T data ordering**: the T_max PE's store from the previous T step must commit to GB before T_min can reload it for the next T step |
| `load_vmem_dram` (if present) | D | DRAM vmem tile must have landed in GB first |

### Step 7: `lif_count`  (all PEs, parallel)

| Dep TC | Type | Reason |
|--------|------|--------|
| `k_chain_tails[noc_i]` | D | Accumulated psum (after K-chain) must be ready |
| `load_vmem[noc_i]` (if loaded) | D | Carry-over membrane potential must have arrived at T_min |
| `prev_tchain_tails` (previous vmem-step's `t_chain` tails) | D | **T carry-over**: when `is_vmem_gb_free=True` (T-inner-K), vmem never goes through GB; the only ordering dep on the prior T step's vmem result is through the previous `t_chain` tail → this LIF |
| `lif_ring[-2]` (if ring size ≥ 2) | B | PE LIF buffer is double-buffered; freed 2 vmem-steps ago |

> When `is_vmem_gb_free=False`, `prev_tchain_tails` is still added (harmless
> redundancy — the data dep already flows through store_vmem → load_vmem → lif).
> When `is_vmem_gb_free=True`, it is the **only** vmem ordering dep.

### Step 8: `t_chain`  (T=0 → T=1 → … → T_max, serial per group)

| Dep TC | Type | Reason |
|--------|------|--------|
| `lif_tcs[noc_i]` (all PEs) | D | LIF must complete before T=0 forwards its updated vmem |
| `t_chain_link[i-1]` (within group) | D | Serial propagation within group |

### Step 9: `store_vmem`  (T_max PE → GB per group)

Skipped when `is_last_T` or `is_vmem_gb_free`.

| Dep TC | Type | Reason |
|--------|------|--------|
| `t_chain_tails[noc_i]` | D | T-chain result (updated membrane potential) must be ready |

---

## Summary: two-sided dependency rule

Every GB **load** has two independent deps:

| Dep | Type | What it guards |
|-----|------|----------------|
| Ring/hist offset **-2** | B | Double-buffer slot: the consumer at step `i` reuses the same GB buffer bank as step `i-2`; that prior occupant must have finished |
| Ring/hist offset **-1** or **-T_noc_steps** | D | Data correctness: the specific data being loaded must already be committed by its producer |

These are independent and both must appear — neither subsumes the other.

| Variable | Buffer dep | Data dep |
|----------|-----------|---------|
| Psum load | `ps_hist[noc_i-2]` | `ps_hist[noc_i - T_noc_steps]` |
| Vmem load | `vmem_store_ring[-2]` | `vmem_store_ring[-1]` |
| LIF (T carry) | `lif_ring[-2]` | `prev_tchain_tails` |
