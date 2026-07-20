# Plan 3 — Single-node mode

**Status: implemented and verified.**

> **Part A superseded.** The MIP-bypass described in Part A below
> (`model/fixed_schedule.py`, `arch.node_dims`, `arch.dram_order`,
> `nocsim/sim.py`'s `run_single_node()`) has been removed. Fixing the entire
> DRAM permutation order by hand (`dram_order`) was wrong — hardware only
> fixes the node's per-dimension *capacity*, not the DRAM loop order,
> which the MIP should still search over. It's replaced by a real MIP
> constraint, `model/constraints/node_capacity.py`
> (`arch.node_dim_capacity`), which bounds what may reside at NodeLevel and
> lets the solver freely decide the rest, including the full DRAM
> permutation — see `/home/yy/.claude/plans/gentle-singing-fairy.md`.
> **Part B (GB elision in `combine.py`) is unaffected and still current** —
> `arch.single_node` remains a pure hardware-topology flag, now decoupled
> from how the schedule itself is produced.

## Goal

For the degenerate case of a 1×1 NoC (one PE, no spatial unrolling, no
Global Buffer), two things change:

**A. Input generation bypasses the MIP solver entirely.** Once the
node-level tile size and the full DRAM permutation order are both fixed,
there is no remaining search — splitting each dimension's leftover prime
factors into DRAM slots is arithmetic, not optimization.

**B. nocsim eliminates the GB hop.** Every DRAM→GB→node / node→GB→DRAM
two-hop transaction pair collapses into one direct DRAM↔node transaction.

Tied together by an explicit `single_node: true` flag in the arch YAML.

## Decisions

1. **`decode()` stays 100% untouched.** `build_fixed_x` wraps each computed
   0/1 value in a trivial `_FixedVar` shim mimicking Gurobi's `.X`
   accessor, so `decode()`'s existing `x[(i,j,n,k)].X > 0.5` lines work
   against the bypass module's output with zero modification to
   `decode.py`.
2. **`dram_order` is a flat permutation, no interleaving, asserted twice**
   — once at arch-YAML parse time (`SNNArch._parse_dram_order`, fails
   loudly on a malformed config before anything else runs) and again
   defensively inside `build_fixed_x` itself (catches a hand-built `SNNArch`
   object that skipped the parser).
3. **`single_node: true`** is its own explicit boolean key in `arch.yaml`
   (not derived from `node_dims`/`dram_order` presence).
4. **`src_port`/`dest_port` parameterization**: `load_weight`/`load_psum`/
   `load_vmem` gained an optional `src_port` param; `store_psum`/
   `store_vmem` gained `dest_port`. Both default to `None`, meaning "fall
   back to `gen.noc.gb_port`, exactly like before this parameter existed"
   — every pre-existing call site is provably unaffected. Single-node mode
   passes `gen.noc.dram_port` explicitly and skips the separate
   `load_from_dram`/`store_to_dram` call, so two transactions become one.

## Part A — `src/snn_cosa/model/fixed_schedule.py`

`build_fixed_x(prob, arch) -> Dict[(i,j,n,k), _FixedVar]`:
1. Asserts `dram_order` is a valid permutation (decision 2).
2. Pre-populates every `(i,j,n,k)` key `decode()` might look up
   (`i` in `[0, dram_end)`, all `j,n,k` combinations) to `_FixedVar(0.0)` —
   required because `decode()` does dict lookups, not `.get()`.
3. For each dimension (walked in `dram_order` reverse, since the stored
   convention is outer→inner but `LoopItem.level` convention is
   lower-index-is-more-inner): factors `node_dims[dim]` into primes,
   multiset-matches them against the workload's actual prime factorization
   (`_factor_indices`, raises `ValueError` if `node_dims` doesn't evenly
   divide the real dimension bound), assigns matched indices to NodeLevel
   (`i=0, k=0`), and assigns every remaining prime factor to sequential
   DRAM permutation slots (`k=1`).
4. A dimension with bound 1 (`_get_prime_factors(1) == [1]`, a placeholder,
   not an empty list) is assigned to NodeLevel trivially, bypassing the
   node_dims/dram_order matching entirely — nothing to split.

Zero assignments ever go to any NoCLevel slot — this is what guarantees
`noc_temporal_loops == []` downstream, which `decode()`'s existing
`noc_num_steps` property (`product of an empty list = 1`) already collapses
to a single-iteration loop with no `combine.py` loop-structure changes
needed.

## Part B — GB elision in `combine.py`

`combine()` gained an optional `arch: Optional[SNNArch] = None` parameter;
`single_node = arch is not None and arch.single_node` gates every change
below. `None` (the default) is behaviorally identical to before this
parameter existed.

- **5a (DRAM→GB loads)**: `skip=single_node` added to weight's
  `load_from_dram` call (was `skip=False`); `single_node or ...` added to
  psum's and vmem's existing skip conditions. All three become permanently
  skipped (`dram_w_id`/`dram_p_id`/`dram_v_id` always `None`) in single-node
  mode.
- **Weight load**: `w_deps`'s `noc_i==0` branch now guards
  `if dram_w_id is not None` before appending (avoids appending `None`);
  `load_weight(..., src_port=dram_port if single_node else None)`.
- **Psum/vmem load**: added a 4th dependency branch —
  `if single_node and prev_dram_psum_store is not None: pl_deps.append(...)`
  (symmetrically for vmem) — this is the read-after-write ordering that
  `dram_p_id`/`dram_v_id` would normally provide, needed because those are
  now always `None`. `src_port=dram_port if single_node else None` added to
  both calls.
- **Psum/vmem store**: `dest_port=dram_port if single_node else None`
  added to both calls.
- **5d (GB→DRAM stores, end of `dram_i` loop)**: `single_node` added to
  both `store_to_dram` skip conditions (never fires — `store_psum`/
  `store_vmem` already wrote directly to DRAM). `prev_dram_psum_store`/
  `prev_dram_vmem_store` — previously always set from `store_to_dram`'s
  tc_id — now branch: in single-node mode, pulled from `ps_hist`/`vs_hist`
  (the direct-to-DRAM `store_psum`/`store_vmem` tc_id from the noc_i loop)
  instead, since there's no separate `store_to_dram` transaction to point
  to anymore.
- K-chain/T-chain calls: **no changes** — `BufSpatial`'s chain-group
  builder already produces empty chains for a single PE, so these are
  no-ops automatically (verified, not just assumed).

## Wiring — `src/snn_cosa/nocsim/sim.py`

- `run()`/`run_from_json()` gained an optional `arch: Optional[SNNArch]`
  parameter, threaded straight into `combine(..., arch=arch)`. Existing
  callers passing nothing are unaffected.
- New `run_single_node(prob, arch, bitwidths, out_file)`: calls
  `build_fixed_x` then the existing `run(x, prob, bitwidths, out_file,
  arch=arch)` — no duplicated pipeline logic.
- CLI: `--schedule` is now optional. `main()` requires exactly one of
  (`--schedule` given, `arch.single_node` false) or (`--schedule` omitted,
  `arch.single_node` true) — the other two combinations are rejected with a
  clear error before anything runs. `--simulate`'s eventsim invocation
  branches to `X=Y=1` directly for single-node mode instead of
  reconstructing `spatial_factors` from a (nonexistent) schedule JSON.

## Files added/changed

- `src/snn_cosa/parsers/arch.py` — `single_node`/`node_dims`/`dram_order`
  parsing and validation on `SNNArch`.
- `src/snn_cosa/model/fixed_schedule.py` — new, `build_fixed_x` +
  `_FixedVar` + `_factor_indices`.
- `src/snn_cosa/nocsim/transactions/weight.py`,`psum.py`,`vmem.py` —
  `src_port`/`dest_port` optional parameters.
- `src/snn_cosa/nocsim/combine.py` — `arch` parameter, single-node
  branching throughout (detailed above).
- `src/snn_cosa/nocsim/sim.py` — `run()`/`run_from_json()` gain `arch`
  param, new `run_single_node()`, CLI `--schedule` now optional.
- `configs/arch/snn_arch_single_node.yaml` — new example config (workload:
  `configs/workloads/sim_demo.yaml`; `node_dims: {COUT: 2, CIN: 2, T: 2}`,
  `dram_order: [T, HO, WO, COUT, CIN, KW, KH]`).
- `NOC_SIM_DESIGN.md`, `NOC_SIM_IMPL.md` — single-node mode documented.

## Verification

**End-to-end, `snn_arch_single_node.yaml` (K-dims not innermost variant)**:
```
transactions  : 9152
weight  dram_cost=39168   psum  dram_cost=76160   vmem  dram_cost=0
total_cycles: 77248   count_cycles: 18560   dram_cycles: 115328
```
- **GB fully absent**: `awk` over every `actor_id`/`dest` column in the CSV
  returns only `{0, 3}` (the single PE and DRAM port) — id `1` (GB) never
  appears, in either variant tested.
- **Direct routing confirmed by inspection**: `weight_0_0__send_0: unicast
  3→0` (DRAM→PE), `psum_N_0__store_0: unicast 0→3` (PE→DRAM),
  `psum_64_0__load_0: unicast 3→0 dep=[191]` (DRAM→PE, correctly gated on
  tc_id 191 — the previous `dram_i`'s store — confirming the new
  cross-`dram_i` RAW ordering dependency is both present and exercised).
- **Both traffic-free and traffic-generating configs tested**: a first
  `dram_order` (K-dims innermost) produced zero psum/vmem transactions
  (legitimately traffic-free by the existing, unmodified `StepInfo` logic);
  a second `dram_order` (K-dims outermost) produced real psum DRAM
  round-trips (2240 loads, 2240 stores, symmetric) — confirms the
  direct-DRAM path isn't just untested dead code.
- **Dependency graph validity**: `eventsim` ran both generated CSVs to
  completion with no `unresolved dependency cycle` / `unknown tc_id`
  errors and deterministic `total_cycles` across repeated runs — an
  independent, external validation that every dependency edge resolves.
- **`dram_order` assertion fires** both at `SNNArch` parse time and inside
  `build_fixed_x` directly, confirmed with a malformed (`["KH","KW"]`,
  not a full permutation) input at both call sites.
- **Zero regression on the normal multi-PE path**: re-ran the exact
  `sim_demo` command from Plan 1/2's verification (`snn_arch.yaml`, not
  single-node) — output byte-identical to before this change
  (`transactions: 672`, `weight unicast_hops: 1440`, `dram_cost: 1088`,
  `total_cycles: 3360`), confirming the `arch=None`/`single_node=False`
  default path is untouched.
