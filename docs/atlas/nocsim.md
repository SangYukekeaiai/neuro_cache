# Code atlas: src/nocsim (and src/cachesim)

Built from code only, at commit 8fa0916 (branch wcache-rebuild-phase-a). No
.md/.txt/log/dump/debug file was read. Line numbers come from `grep -n` and
`ast`. All paths are relative to the repo root.

---

## 1. Top-down

### 1.1 Purpose

nocsim turns one solved SNN-CoSA loop schedule (output of `mip_solver solve`)
into a dependency graph of NoC transactions ("TCs") for a 2-D mesh of PEs
with a Global Buffer (GB) port and a DRAM port. It writes that graph as
`tc.csv` and reports three static per-tensor costs (unicast hops, multicast
hops, DRAM cost) for weight, psum and vmem. A separate C++ program,
`eventsim`, replays the CSV as a discrete-event simulation with
dependency, actor and link contention and reports a makespan
(`total_cycles`). In this repo that makespan is the **baseline that wcache
is compared against** (`speedup_vs_nocsim` in profiling/). nocsim's
`schedule/` subpackage is also a library: `tracegen.py` and
`archmodels/dense.py` import it to decode schedules and enumerate tiles.

### 1.2 Entry points

| Entry | Where | Notes |
|---|---|---|
| CLI `python -m nocsim.sim` | src/nocsim/sim.py:312 `main(argv=None) -> int` | Needs `PYTHONPATH=src` (imports are top-level `parsers`, `archmodels`, `mip_solver`, `tracegen`). |
| `--schedule JSON` (required) | src/nocsim/sim.py:266 | Raw solver doc, or a `tracegen.ScheduleArtifact` that nests it under `"result"` (src/nocsim/sim.py:62). |
| `--layer YAML` (required) | src/nocsim/sim.py:272 | Read by `parsers.layer.SNNProb`. Must match the layer used when solving. |
| `--arch YAML` (required) | src/nocsim/sim.py:278 | Read twice: `SNNArch` (for `single_node`) and `SNNBitwidths` (bit widths, `DRAM_LATENCY`). |
| `--out CSV` (default `outputs/tc.csv`, relative to cwd) | src/nocsim/sim.py:255, :284 | Suffix `.csv` or `.json` (src/nocsim/core/generator.py:243). |
| `--weight-trace JSON_GZ` (optional) | src/nocsim/sim.py:290 | One `sample_NNNNN.json.gz`; loaded by `tracegen.load_step_cycles` (src/tracegen.py:436), giving per-step MAC cycles. |
| `--simulate` (flag) | src/nocsim/sim.py:300 | After writing the CSV, runs `src/nocsim/eventsim/eventsim` and prints its 5 counters. |
| `run(x, prob, bitwidths, out_file, ...)` | src/nocsim/sim.py:79 | Gurobi-variable path (`decode()`); no caller in src/, scripts/, profiling/ or tests/. |
| `run_from_json(schedule_path, ...)` | src/nocsim/sim.py:137 | JSON path used by the CLI. |
| `run_eventsim(csv_path, X, Y, dram_port, dram_latency, binary=None)` | src/nocsim/sim.py:198 | subprocess to the C++ binary, parses one JSON line. |
| `eventsim <tc.csv> --X --Y --dram-port --dram-latency` | src/nocsim/eventsim/main.cpp:24, :60 | All four flags required (src/nocsim/eventsim/main.cpp:53). Build: `make` in src/nocsim/eventsim (g++ -O2 -std=c++17, src/nocsim/eventsim/Makefile:1-2). |

Exit codes of the CLI: 0 ok; 2 on bad inputs, bad weight trace, failed
simulation, missing or failing eventsim (src/nocsim/sim.py:323-397).

### 1.3 Who calls nocsim

- `src/tracegen.py:41-42` imports `schedule_from_strategy`, `iter_node_tiles`
  (weight-trace generation, the input of both nocsim `--weight-trace` and wcache).
- `src/archmodels/dense.py:18` imports `Schedule` (and `combine.py:75` imports
  `DenseStaticComputeModel` back: a two-way package dependency).
- `scripts/generate_weight_traces.py:51` imports `schedule_from_strategy`.
- `profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:64` and
  `profiling/0831_all_layer_streams/run_compare.py:147` run
  `python -m nocsim.sim ... --weight-trace ... --simulate` with
  `cwd=ROOT`, `PYTHONPATH=ROOT/src`, and parse the `total_cycles:` etc. lines
  from stdout. run_compare.py:49 fixes the arch YAML to
  `loas_inst16_node32kb_noc2MiB_pe16.yaml`; :55 hardcodes `N_NODES = 16`
  to turn `count_cycles` into per-node compute.
- Later profiling stages (0903, 0907_*, 0831_l2_prefetch, stage4_wcache)
  read `all_layers_vs_nocsim.csv` / `stage3_results.json` produced above
  and report wcache as a speedup over nocsim.
- wcache's C++ apps accept `--arm spad_nocsim` only as a label for the
  `arm` column (src/wcache/native/apps/app_support.h:77-80); no wcache code
  calls nocsim.
- tests: see 2.6.

### 1.4 Data flow (CLI path)

1. **Inputs -> parsed objects** (src/nocsim/sim.py:320-322):
   layer YAML -> `SNNProb`; arch YAML -> `SNNArch`, `SNNBitwidths`;
   optional weight trace -> `StepCycles.by_step: {(dram_i, noc_i): ComputeCycles}`.
2. **Schedule JSON -> `Schedule`** (src/nocsim/schedule/decode.py:238):
   `strategy` dict -> spatial factors per dim, NoC and DRAM temporal
   `LoopItem` lists (one per prime factor, inner->outer), `data_size` per
   tensor (elements in one GB tile).
3. **`Schedule` -> `BufSpatial`** (src/nocsim/schedule/buf_spatial.py:63):
   PE index tuples under the "Way-2" layout, per-tensor address tuples,
   K-chain and T-chain groups.
4. **`Schedule` -> `StepInfo`** (src/nocsim/schedule/steps.py:55):
   first/last-K and first/last-T flags per `(dram_i, noc_i)`, "GB-free"/
   "DRAM-free" structural flags, `weight_changes()`.
5. **`combine()` -> `TC_Generator`** (src/nocsim/combine.py:120): the nested
   DRAM x NoC loop calls the `transactions/*` builders, which call
   `TC_Generator.unicast/multicast/count`, which create `TC` objects and add
   to the three cost dicts.
6. **`TC_Generator.to_file()` -> `tc.csv`** (src/nocsim/core/generator.py:243):
   two lines per TC: `# annotation` then `tc_id,actor_id,op,size,src,dest,dep`.
7. **(optional) `tc.csv` -> eventsim -> JSON** (src/nocsim/eventsim/EventSim.h:55):
   `{"total_cycles","unicast_cycles","multicast_cycles","count_cycles","dram_cycles"}`.

### 1.5 Key abstractions

```
 Schedule ──► BufSpatial (who is where, which PEs share data)
    │   └───► StepInfo   (where in K / T each step is)
    │                         │
    └──────────► combine() ◄──┘   (+ SNNBitwidths, SNNArch.single_node,
                    │               cycle source: by_step | model)
                    ▼
     transactions/{weight,psum,vmem,compute,dram}.py
                    │  unicast / multicast / count
                    ▼
     TC_Generator ── NoC (X x Y mesh, gb_port, dram_port, XY routing)
          │  list[TC], unicast_hops, multicast_hops, dram_cost
          ▼
       tc.csv  ──►  eventsim (C++: NoC.h, Transaction.h, EventSim.h)
```

Conventions that hold everywhere:
- Dims are `parsers.layer.DIM_*`: KH=0, KW=1, CIN=2, COUT=3, HO=4, WO=5, T=6
  (src/parsers/layer.py:35-41). K (reduction) dims = {KH, KW, CIN}.
- Tensor-dim relevance is `mip_solver.constants._A` (src/mip_solver/constants.py:83):
  weight uses KH,KW,CIN,COUT; psum uses COUT,HO,WO,T; vmem uses COUT,HO,WO
  (vmem size does not depend on T).
- Way-2 PE layout: X axis = T, WO, HO (inner->outer); Y axis = CIN, KW, KH,
  COUT; `pe_id = y*X + x` (src/nocsim/combine.py:179-180,
  src/nocsim/schedule/buf_spatial.py:54).
- Loop lists are always inner->outer; the strategy JSON stores temporal
  loops outer->inner and decode reverses them (src/nocsim/schedule/decode.py:278, :282).
- A packet is 256 bits = 4 payload flits of 64 bits (src/nocsim/core/transaction.py:22-24).

### 1.6 One run, step by step (`combine`, src/nocsim/combine.py:120)

1. Mesh: `X = sf[T]*sf[WO]*sf[HO]`, `Y = sf[CIN]*sf[KW]*sf[KH]*sf[COUT]`;
   `TC_Generator(NoC(X, Y), dram_latency)` (:178-181).
2. Cycle source (:224-235), in priority order: `cycles_by_step` table (per
   step, from the weight trace) > single-node per-core model calls reduced by
   `max` per step (`tiles_by_step`) > one call of the model for the whole run.
   Default model is `DenseStaticComputeModel` (src/archmodels/dense.py:32).
3. For each `dram_i` (:260):
   a. DRAM->GB loads (:272-297): weight always; psum unless first-K-at-DRAM
      or psum DRAM-free; vmem only if last-K-at-DRAM and not first-T-at-DRAM
      and not vmem DRAM-free. All skipped in single-node mode.
   b. For each `noc_i` (:325): (1) weight load if `weight_changes` (:376);
      (2) psum load to K-chain tail PEs (:410); (3) MAC COUNT on every PE
      (:426); (4) K-chain unicasts (:436); (5) psum store from K tails
      (:451); if not last-K, next step (:461). Else (6) vmem load to T-chain
      head PEs (:485); (7) LIF COUNT on every PE (:508); (8) T-chain
      (:517); (9) vmem store from T tails (:531).
   c. GB->DRAM stores for psum and vmem (:553-578), which also set the
      dependency the next `dram_i`'s DRAM loads wait on.
4. Dependency rules (module docstring :25-48, code :365-539): sequential GB
   weight sends (noc_i-1); node double buffer (MAC at noc_i-2); GB double
   buffer for psum (store at noc_i-2) and same-T data order (store at
   noc_i - T_noc_steps); vmem/LIF use 2-deep rings counted in "vmem steps"
   (last-K firings), not raw noc_i (:310-311).
5. "GB-free" flags force skips: if K dims are innermost in the integrated
   NoC+DRAM loop, psum never goes to GB (passed as `is_first_K=True`,
   `is_last_K=True`, :412, :453); same for vmem with T (:487, :533).
6. Single-node arch (`arch.single_node`, src/parsers/arch.py:172): there is
   no GB leg; loads/stores use `src_port/dest_port = dram_port` (:381, :415,
   :456, :490, :536), and RAW ordering across `dram_i` comes from the last
   NoC-step store (:559-561, :574-576).

---

## 2. Bottom-up

### 2.1 src/nocsim/sim.py

- `_solver_result(data: Dict) -> Dict` (src/nocsim/sim.py:62): `data.get("result", data)`; accepts both schedule JSON shapes.
- `run(x, prob, bitwidths, out_file, y=None, arch=None, compute_model=None, trace=None, cycles_by_step=None) -> (unicast_hops, multicast_hops, dram_cost)` (src/nocsim/sim.py:79): decode Gurobi vars -> combine -> write. `y` is unused (:84, :99).
- `run_from_json(schedule_path, prob, bitwidths, out_file, arch=None, compute_model=None, trace=None, cycles_by_step=None)` (src/nocsim/sim.py:137): same via `schedule_from_strategy`; `ValueError` if `has_solution` is false (:178).
- `_DEFAULT_EVENTSIM_BINARY` (src/nocsim/sim.py:195): `<this dir>/eventsim/eventsim`.
- `run_eventsim(csv_path, X, Y, dram_port, dram_latency, binary=None) -> Dict[str,int]` (src/nocsim/sim.py:198): `subprocess.run(check=True)`; `FileNotFoundError` if not built.
- `_DEFAULT_OUT = "outputs/tc.csv"` (src/nocsim/sim.py:255).
- `_build_parser()` (src/nocsim/sim.py:258): flags in 1.2.
- `main(argv=None) -> int` (src/nocsim/sim.py:312): `tracegen` imported lazily (:335) to avoid an import cycle. TC count is re-read from the written file (:353). With `--simulate` it re-opens the JSON, rebuilds the Schedule and recomputes X, Y and `NoC(X,Y).dram_port` (:375-381) instead of getting them from combine.

### 2.2 src/nocsim/combine.py

- `_dim_totals(loops) -> Dict[int,int]` (src/nocsim/combine.py:95): product of factors per dim.
- `_vals(d) -> List[int]` (src/nocsim/combine.py:103): dict values as list.
- `_chain_tails(chain_dict) -> List[int]` (src/nocsim/combine.py:108): last link id per chain group; single-PE groups contribute nothing, so callers fall back to the COUNT ids (:444-445, :523-524).
- `combine(schedule, bs, si, prob, bitwidths, arch=None, compute_model=None, trace=None, cycles_by_step=None) -> TC_Generator` (src/nocsim/combine.py:120): see 1.6. Details: a missing `(dram_i, noc_i)` key in `cycles_by_step` raises `KeyError` on purpose (:333-338). `lif_cycles=None` becomes 0 (:235, :340); traces written by tracegen store `lif_cycles=None` (src/tracegen.py:284), so with `--weight-trace` every LIF COUNT is 0 cycles. `T_noc_steps` = product of T factors at NoC level (:251). `model` is built even when `cycles_by_step` makes it unused (:224).

### 2.3 src/nocsim/core/

**noc.py**
- `Link` (src/nocsim/core/noc.py:38): `((x0,y0),(x1,y1))`.
- `class NoC(X, Y, gb_port=None, dram_port=None)` (src/nocsim/core/noc.py:41, `__init__` :59): `num_rports = 4XY - 2Y(X-1) - 2X(Y-1)` (:74), which equals `2X+2Y`; `num_ports = XY + num_rports`. Defaults: `gb_port = X*Y` (:78) -> coordinate (0, Y); `dram_port = num_ports-(X+Y) = XY+X+Y` (:79-82), chosen to match an external CoSA C++ backend (`testbench.cpp`, not in this repo). Both must lie in `[X*Y, num_ports)` and differ (:84-94).
- `get_xy(pe_id)` (src/nocsim/core/noc.py:100): `(id % X, id // X)`, also used for ports past the grid.
- `_hops_single(src, dest)` (src/nocsim/core/noc.py:111): XY route as list of links.
- `count_hops(src, dests)` (src/nocsim/core/noc.py:134): unique links over all dests. Not called anywhere.
- `manhattan(src, dest)` (src/nocsim/core/noc.py:148): used for all hop metrics.
- `all_pe_ids()` (src/nocsim/core/noc.py:158): not called anywhere.

**transaction.py**
- `UNICAST=0, MULTICAST=1, COUNT=2` (src/nocsim/core/transaction.py:15-17).
- `FLIT_SIZE=64, FLITS_PER_PACKET=4, PACKET_SIZE=256` bits (src/nocsim/core/transaction.py:22-24).
- `class TC(tc_id, actor_id, op, deps, var_name, entries, datawidth, annotation="")` (src/nocsim/core/transaction.py:30): `srcs` is always `[actor_id]`; `size` is packets (send) or cycles (COUNT). `create_unicast` :74, `create_multicast` :79, `create_count` :84, `_fmt` :93, `format_csv` :97 (columns `tc_id,actor_id,op,size,src,dest,dep`). `var_name/entries/datawidth` reach only the JSON output.
- `class TCEncoder(JSONEncoder)` (src/nocsim/core/transaction.py:119): dumps `TC.__dict__`; used only by `to_file(.json)`.

**generator.py**
- `_TRAFFIC_VARS = ("weight","psum","vmem")` (src/nocsim/core/generator.py:44).
- `class TC_Generator(noc, dram_latency=0.25)` (src/nocsim/core/generator.py:47, `__init__` :59): owns tc_id counter, `tcs`, `write_deps` (label -> [tc_id]), three cost dicts pre-seeded with all three keys.
- `_num_packets(size_bits)` (src/nocsim/core/generator.py:82): ceil(size_bits/256). Note: 0 bits gives 0 packets.
- `_append(tc, label)` (src/nocsim/core/generator.py:86): stores and returns the id.
- `unicast(var_name, size_bits, datawidth, src, dest, deps, label) -> int` (src/nocsim/core/generator.py:97): `unicast_hops += manhattan + 4*packets` only when `src == gb_port and dest != dram_port` (:122); `dram_cost += ceil(packets*dram_latency)` when either end is `dram_port` (:126-127). PE->GB stores and PE->PE chains add nothing to any metric.
- `multicast(...)` (src/nocsim/core/generator.py:131): GB-sourced only: `multicast_hops += max manhattan + 4*packets` (:157-160, "farthest node"). No `dram_cost` branch.
- `count(cycles, node_id, deps, label)` (src/nocsim/core/generator.py:164).
- `_get_reqs(base, pe_id, out)` (src/nocsim/core/generator.py:187) and `get_deps(dep_labels, pe_id=-1)` (src/nocsim/core/generator.py:215): label-based dependency lookup. No caller anywhere; combine passes tc_ids directly.
- `to_file(out_file)` (src/nocsim/core/generator.py:243): `.csv` or `.json`, else `ValueError`.

### 2.4 src/nocsim/schedule/

**decode.py**
- `class LoopItem(dim, dim_name, factor, level)` (src/nocsim/schedule/decode.py:48): one prime factor; lower `level` = more inner.
- `class Schedule(spatial_factors, noc_temporal_loops, dram_temporal_loops, data_size, gb_start, dram_start, perm_levels)` (src/nocsim/schedule/decode.py:65); `noc_num_steps` :92 and `dram_num_steps` :100 are products of factors.
- `decode(x, prob) -> Schedule` (src/nocsim/schedule/decode.py:112): reads Gurobi `.X > 0.5` (:138). Levels: NoC slots `[1, 1+P)`, DRAM slots `[1+P, 1+2P)` with `P` = total prime-factor count and `SNN_GB_START_LEVEL = 1` (src/mip_solver/constants.py:58). `data_size` multiplies every factor at levels below `dram_start` for dims relevant to the tensor (:181-191). Only reached from `sim.run`.
- `_expand_loops(entries, name_to_idx, start_level)` (src/nocsim/schedule/decode.py:208): splits each fused size into ascending primes (smallest = innermost, :231); synthetic level numbers.
- `schedule_from_strategy(strategy, prob) -> Schedule` (src/nocsim/schedule/decode.py:238): reads `NoCLevel.spatial_splitting.loops` (sizes kept fused), and reverses `NoCLevel/DRAM.temporal_permutation.loops`. `data_size[v] = prod_{relevant j} total_j // dram_total_j` (:292-301), so NodeLevel factors are implied, not read.

**steps.py**
- `_K_DIMS`, `_T_DIM`, `_WEIGHT_DIMS = {KH,KW,CIN,COUT}` (src/nocsim/schedule/steps.py:50-52).
- `class StepInfo(schedule, _prob)` (src/nocsim/schedule/steps.py:55, `__init__` :64): `prob` unused. Flags (:84-90): `is_psum_dram_free` / `is_vmem_dram_free` test the DRAM loop alone; `is_psum_gb_free` / `is_vmem_gb_free` test NoC+DRAM concatenated.
- `k_position(dram_i, noc_i)` :96, `t_position` :104: combined index `noc_idx + noc_total*dram_idx`; a dim absent from both levels counts as first and last.
- `dram_k_position(dram_i)` :117, `dram_t_position` :125: DRAM level only.
- `weight_changes(dram_i, noc_i) -> bool` (src/nocsim/schedule/steps.py:133): True at (0,0); otherwise compares weight-dim indices against the previous step of the integrated loop, which at `noc_i==0` is `(dram_i-1, last noc)` (:158-161).
- `_integrated_idx(dram_i, noc_i, dim)` :169; `_combined_position` :184.
- `_is_dims_innermost(loops, target)` (src/nocsim/schedule/steps.py:217): True if no non-target loop is inner to any target loop; absent target counts as True.
- `_compute_totals(loops)` :250 (third copy of `_dim_totals`).
- `_decode_dim(step, loops, dim)` (src/nocsim/schedule/steps.py:258): mixed-radix decode of a flat step for one dim, handling a dim split over several LoopItems.
- `_level_position(step, loops, totals, target)` :289.

**tiles.py**
- `_CORE_ID_ORDER = [T, WO, HO, CIN, KW, KH, COUT]` (src/nocsim/schedule/tiles.py:57): same order as Way-2, so `core_id == pe_id`.
- `encode_core_id(idx, spatial_factors)` (src/nocsim/schedule/tiles.py:60): inverse of decode; no caller in src/scripts/profiling/tests.
- `decode_core_id(core_id, spatial_factors)` (src/nocsim/schedule/tiles.py:70): radix 1 for missing dims.
- `_dim_totals(loops)` :84 (second copy).
- `iter_node_tiles(schedule, prob) -> Iterator[NodeTileSpec]` (src/nocsim/schedule/tiles.py:97): one spec per `(dram_i, noc_i, core_id)`, nested in that order. `node_bound[j] = max(total_j // (dram_t*noc_t*spatial), 1)` (:131-132). `tile_offset[j]` = spatial slice + NoC offset + DRAM offset (:154-161), only for dims that vary. Builds its own `StepInfo` (:123) for `is_last_K`. Imports the private `steps._decode_dim` (:45).

**buf_spatial.py**
- `_WAY2_ORDER` (src/nocsim/schedule/buf_spatial.py:54), `_K_DIMS` tuple (:57, duplicates steps.py:50), `AddrGroups` (:60).
- `class BufSpatial(schedule, prob)` (src/nocsim/schedule/buf_spatial.py:63, `__init__` :76): only dims with `sf > 1` get a stride (:80); `num_pes` = their product, equal to X*Y. `weight/psum/vmem` are per-PE 7-tuples with irrelevant dims zeroed (`_make` :116).
- `addr_groups(buf)` (static, :134): address -> sorted pe_ids.
- `k_chain_groups()` :157: groups by psum address; ascending pe_id = ascending K (K dims are on Y). Cached.
- `k_max_pes()` :172: tail of each K-chain (receives psum loads, sends stores).
- `t_chain_groups()` :184: only PEs whose K indices are all at max (:197), grouped by vmem address, sorted by T index. Cached.
- `t_min_pes()` :215 (vmem load target), `t_max_pes()` :219 (vmem store source).

### 2.5 src/nocsim/transactions/

All builders return `{addr_tuple: tc_id}` (or `{addr: [link ids]}` for
chains), iterate groups in `sorted()` order so output is deterministic, and
split the GB tile evenly: `size_bits = (data_size[t] // num_groups) * bw`
(integer division; remainder is dropped). Labels `<prefix>__<kind>_<pe>` are
only used as `write_deps` keys and CSV comments.

- `mac_count(gen, node_ids, pe_cycles, deps, label_prefix)` (src/nocsim/transactions/compute.py:26) and `lif_count(...)` (src/nocsim/transactions/compute.py:61): one COUNT per PE with the same deps; identical bodies. LIF runs on all PEs, not only the K-max row.
- `load_from_dram(gen, var_name, data_size, datawidth, skip, deps, label_prefix) -> Optional[int]` (src/nocsim/transactions/dram.py:42): DRAM->GB, whole tile; `None` when skipped.
- `store_to_dram(...)` (src/nocsim/transactions/dram.py:80): GB->DRAM; actor is `gb_port`.
- `load_weight(gen, bs, data_size, bw_weight, weight_changes, deps, label_prefix, src_port=None)` (src/nocsim/transactions/weight.py:45): `{}` if weight unchanged (:86); unicast for single-PE groups, multicast otherwise.
- `load_psum(..., is_first_K, deps, label_prefix, src_port=None)` (src/nocsim/transactions/psum.py:31): GB -> each K-chain tail; `{}` if first K.
- `k_chain(gen, bs, data_size, bw_psum, deps, label_prefix)` (src/nocsim/transactions/psum.py:86): link i+1 depends only on link i; first link on `deps`.
- `store_psum(..., is_last_K, deps, label_prefix, dest_port=None)` (src/nocsim/transactions/psum.py:141): K tail -> GB; `{}` if last K.
- `load_vmem(..., is_first_T, ...)` (src/nocsim/transactions/vmem.py:41): GB -> T-chain head.
- `t_chain(...)` (src/nocsim/transactions/vmem.py:95): T head -> tail serial links.
- `store_vmem(..., is_last_T, ...)` (src/nocsim/transactions/vmem.py:147): T tail -> GB.

### 2.6 src/nocsim/eventsim/ (C++17)

- `Link`, `struct NoC` (src/nocsim/eventsim/NoC.h:15, :17): `get_xy` :22, `manhattan` :26, `hops_single` :34, copies of noc.py. No port defaults: `dram_port` comes from the CLI.
- `struct Transaction` (src/nocsim/eventsim/Transaction.h:16); `parse_int_list` :26; `split_csv_line` :34; `parse_csv(path)` :49: skips empty and `#` lines; exactly 7 fields or throws.
- `FLITS_PER_PACKET = 4` (src/nocsim/eventsim/EventSim.h:37): must match transaction.py:23 by hand.
- `struct SimResult` (src/nocsim/eventsim/EventSim.h:39); `touches_dram(tc, dram_port)` :47.
- `simulate(tcs, noc, dram_port, dram_latency) -> SimResult` (src/nocsim/eventsim/EventSim.h:55): list scheduler. A TC becomes ready when all deps have completed; ready ties go by ascending tc_id (:107). Start = max(dep finish times :131-134, actor free time, free time of every link on its route). Durations: COUNT = `size`; DRAM-touching send = `ceil(size*dram_latency)` with no links (:140-145); other sends = `hops + 4*size`, multicast routed only to its farthest dest (:161, :171). An actor runs one TC at a time, and only its last finish is kept (:176), so there is no backfilling into earlier gaps. Every GB-sourced send (and `store_to_dram`) has actor `gb_port`, so they serialize. `*_cycles` are sums of durations; `total_cycles` is the makespan. Unknown dep ids or a cycle throw (:75-78, :202).
- `struct Args`, `parse_args`, `main` (src/nocsim/eventsim/main.cpp:17, :24, :60): prints one JSON line (:68-73).

### 2.7 Tests that touch nocsim (tests/)

- tests/test_step_cycles.py: `tracegen.load_step_cycles` key coverage, single-node shape, identity guard, duplicate keys, tile count. Real-data checks skip if the 0823 Stage 2 corpus is absent.
- tests/test_combine_cycles_table.py: `combine(cycles_by_step=...)` charges each step its trace value, differs from dense, works single-node, missing key raises. Needs `profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces/...` and `outputs/schedules/loas/vgg16_T4_n5` (lines 45-52), neither present in this worktree.
- tests/test_sim_weight_trace.py: CLI end to end (`--weight-trace`, both JSON shapes, `--simulate`); needs the same corpus and the eventsim binary (line 183).
- tests/test_eventsim_deps.py: hand-written CSVs check that deps delay successors across actors, fan-in takes the max, chains add up. Skips if the binary is missing (line 92).
- tests/test_weight_resend.py: `StepInfo.weight_changes` sends equal the reloads the schedule calls for (campaign schedules), plus a synthetic nest.
- No tests target src/cachesim.

---

## 3. src/cachesim: verdict and atlas

### 3.1 Verdict: predecessor of wcache, sibling of nocsim

- **Not related to nocsim in code.** cachesim imports nothing from nocsim and
  nocsim nothing from cachesim. Both consume the tracegen weight trace;
  nocsim models NoC traffic and time, cachesim models weight-cache hit rates.
- **Predecessor of wcache.** Evidence: (a) wcache's archived v1 header cites a
  "cachesim-redesign-plan" (src/wcache/native_v1_archive/include/wcache/types.h:2);
  (b) the current wcache wire format names cachesim's bridge as the format it
  matches (src/wcache/native/include/wcache/stream_format.h:9-10);
  (c) wcache has no import of cachesim; (d) git history: last cachesim
  commit 2026-08-04 (3648cc7); wcache rebuild starts 2026-08-18 (aff9b42);
  (e) the Python reference modules `cache.py, layout.py, policy.py,
  sweep.py` were deleted from src/cachesim in 2811a66 and comments now point
  at `dump/python_reference/cachesim/` (e.g. src/cachesim/layout.h:90,
  src/cachesim/hierarchy.h:18).
- **Live callers:** only `profiling/0803_l1_l2_cache/run_sweep.py:19-20`
  (`DIMS`, `native_hierarchical_sweep`). A script under debug/ also imports
  it (seen in grep output only, not read).

### 3.2 Purpose and flow

Replays one weight-trace sample's weight addresses through LRU caches and
counts hits. Three binaries, each fed binary data on stdin by
`native_bridge.py`:

1. `cache_replay` (src/cachesim/main.cpp:47): one cache, old flat schema
   (`tile["weight_addresses"]`). Prints `hits total rate`.
2. `cache_replay_hierarchical` (src/cachesim/main_hierarchical.cpp:131): one
   private L1 per core + shared L2, nested schema (tiles -> ticks -> cores ->
   weight_addresses), hybrid layout only. Prints counts per core and totals.
3. `cache_sweep_hierarchical` (src/cachesim/main_hierarchical_sweep.cpp:98):
   fixed 24-point grid (3 structures x 2 L1 sizes x 4 L2 sizes), prefetch and
   pinning both on.

Event -> elements (`for_each_element`) -> line `Tag` (inner_dim or hybrid
4x4 cin x cout block) -> packed int64 (`TagPacker`) -> `Cache.access`.
Within one event, repeated consecutive tags are counted once.

Build: `make` in src/cachesim (g++ -O3 -std=c++17, src/cachesim/Makefile:1-2).
None of the three binaries is built in this worktree; all are gitignored.

### 3.3 Bottom-up

**config.py**
- `DIMS = ("kh","kw","cin","cout")` (src/cachesim/config.py:23), `CACHE_TYPES` :24, `POLICIES` :31 (only `lru` is real), `LAYOUTS` :41, `CIN_BLOCK = COUT_BLOCK = 4` :48-49, `_DIM_KEYS` :55.
- `class CacheConfig` (frozen, src/cachesim/config.py:59): `__post_init__` :85 checks positivity, associativity only with set_associative, hybrid needs all four shape bounds and `line_size_bytes == cin_block*cout_block` (1 byte per weight), non-hybrid must not have bounds, capacity divisible by ways. `capacity_lines` :154 = `max(1, size // line)`.
- `load_cache_config(path)` (src/cachesim/config.py:163): YAML with top-level `cache:`; does not read shape bounds, so `layout: hybrid` in YAML always fails validation. No live caller.
- `hybrid_config_from_dims(workload_dims, cache_size_bytes, cache_type, associativity=None)` (src/cachesim/config.py:199): builds a hybrid config from `KH/KW/CIN/COUT`; no live caller.

**stats.py**
- `class HierarchyStats` (src/cachesim/stats.py:20): `per_core_l1` tuples, `l1_hits/accesses`, `l2_hits/accesses` (`l2_accesses == l1_accesses - l1_hits`). Rates: `per_core_l1_hit_rates` :33, `l1_hit_rate` :37, `l2_hit_rate` :42 (over L1 misses), `overall_hit_rate` :47 (`(l1_hits+l2_hits)/l1_accesses`).
- `class HierarchySweepResult` (src/cachesim/stats.py:54).

**native_bridge.py**
- `_NATIVE_BIN`, `_NATIVE_HIERARCHICAL_BIN`, `_NATIVE_HIERARCHICAL_SWEEP_BIN` (src/cachesim/native_bridge.py:27-29): binaries next to the module.
- `load_sample(sample_path)` (src/cachesim/native_bridge.py:32): gzip JSON.
- `_write_events(path, sample_path)` :42: `<I n` then `<iiiii` per event.
- `_run_replay(trace_path, config, order)` :54: 13 positional args; temp dir via `tempfile.TemporaryDirectory` (:81).
- `native_sample_hit_rate(...) -> float` :92 (6 decimals only) and `native_sample_hit_counts(...) -> (int,int)` :105. No live caller.
- `_write_tick_data(path, data)` :111: cores sorted by core_id per tick; `_write_ticks` :136.
- `native_hierarchical_stats(trace_path, l1_config, l2_config, order, *, l2_prefetch, same_tick_pinning)` :140: no live caller.
- `native_hierarchical_sweep(trace_path, order)` :208: parses 9-field rows (:248), rejects trailing output.

**C++ headers**
- `enum Dim`, `dim_from_name`, `parse_order` (src/cachesim/dims.h:10, :12, :23): order must be a permutation of the 4 dims; last entry is the ranged dim.
- `CacheType`, `Layout`, `struct CacheConfig`, `capacity_lines` (src/cachesim/config.h:18, :29, :37, :50): no validation in C++; `associativity 0` = not set.
- `num_sets_and_ways` (src/cachesim/cache.h:15); `class Cache` (:35) with `access`, `access_pinned`, `contains`, `stamp`; `set_index` (:65) = `packed_tag mod num_sets`.
- `PinStamps` (src/cachesim/policy.h:22); `class LRUPolicy` (:27): one set; `contains` (:47) has no side effects; `stamp` (:57) is a per-set clock; `choose_victim` (:100): least recent unpinned line, else the pinned line with the smallest start-of-tick stamp; `require_policy_implemented` (:124) throws for anything but `lru`.
- `Element`, `Tag` (src/cachesim/layout.h:25, :29); `for_each_element` (:37): range is `[v3, v4)`; `tag_for_element_hybrid` (:58); `tag_for_element` (:64); `TagPacker` (:95, `pack` :101, cout is the innermost radix); `hybrid_cout_lines` (:113); `hybrid_packer` (:124, ceil division by block).
- `CoreRequest`, `CoreL1Stats`, `class TwoLevelHierarchy` (src/cachesim/hierarchy.h:36, :41, :47); `run_tick` (:66): lookup phase uses L2 as it was at tick start (`contains`, :98), pins L2 hits (:105), queues prefetch of the next cout block on an L2 miss (:115); fill phase (:140) applies L2 fills in ascending core order. L1 is filled at once by `access`. `prefetch_target` (:193) returns -1 at the last cout block.

**C++ mains**
- src/cachesim/main.cpp:47 `main`: needs `argc == 14` (:48); policy always `lru` (:61); for inner_dim, radices come from this sample's observed maxima plus 1 (:95-117), so set indices depend on the sample; dedup loop (:128-143).
- src/cachesim/main_hierarchical.cpp: `WireCore` :71, `read_pod` :77, `read_ticks` :83, `packed_tags` :105, `parse_flag` :122, `main` :131 (17 args, hybrid only :163).
- src/cachesim/main_hierarchical_sweep.cpp: `read_pod` :24, `read_packed_events` :31, `read_ticks` :51, `Structure`/`STRUCTURES` :74/:80 (fully assoc, 32-way, 4-way), `L1_SIZES` :85 (16, 32 KiB), `L2_SIZES` :86 (128 KiB-1 MiB), `config_for` :88, `main` :98; line 16 B and 4x4 blocks hardcoded (:108, :114-115); prefetch and pinning hardcoded on (:134).

---

## 4. Findings for cleanup (code evidence)

**Dead or unreachable code**
1. `TC_Generator.write_deps/_get_reqs/get_deps` (src/nocsim/core/generator.py:64, :187, :215): never called; the PE-encoded labels exist only for them (src/nocsim/transactions/weight.py:103).
2. `NoC.count_hops`, `NoC._hops_single`, `NoC.all_pe_ids` (src/nocsim/core/noc.py:134, :111, :158): no callers.
3. `lif_hist` written but never read (src/nocsim/combine.py:305, :512).
4. `sim.run` and `decode()` (src/nocsim/sim.py:79, src/nocsim/schedule/decode.py:112): the Gurobi path has no caller in the tree; `y` arg is unused (src/nocsim/sim.py:84).
5. `encode_core_id` (src/nocsim/schedule/tiles.py:60): no caller outside debug/.
6. `combine`'s `compute_model`/`trace` parameters (src/nocsim/combine.py:127-128): no caller passes them (the CLI never does).
7. cachesim: `load_cache_config`, `hybrid_config_from_dims`, `native_sample_hit_rate/counts`, `native_hierarchical_stats` (src/cachesim/config.py:163, :199; src/cachesim/native_bridge.py:92, :105, :140) have no live caller; `cache_replay` and `cache_replay_hierarchical` are reachable only through them.

**Duplicated logic**
8. Dim-totals helper in three places: src/nocsim/combine.py:95, src/nocsim/schedule/tiles.py:84, src/nocsim/schedule/steps.py:250 (plus inline at src/nocsim/schedule/decode.py:288-290 and in src/archmodels/dense.py).
9. Mesh X/Y formula in src/nocsim/combine.py:179-180 and src/nocsim/sim.py:379-380; `--simulate` also re-reads and re-decodes the JSON (src/nocsim/sim.py:375-377).
10. `_K_DIMS` in src/nocsim/schedule/steps.py:50 (frozenset) and src/nocsim/schedule/buf_spatial.py:57 (tuple); Way-2 order in buf_spatial.py:54 and tiles.py:57.
11. psum.py and vmem.py builders are the same three shapes (load/chain/store); `mac_count` and `lif_count` have identical bodies (src/nocsim/transactions/compute.py:26, :61); `load_from_dram`/`store_to_dram` differ only in direction.
12. Constants kept equal by hand across languages: `FLITS_PER_PACKET` (src/nocsim/core/transaction.py:23 vs src/nocsim/eventsim/EventSim.h:37); routing (noc.py vs NoC.h); default `dram_latency=0.25` (src/nocsim/core/generator.py:59 vs src/parsers/bitwidths.py:35).
13. cachesim: `read_pod` twice (src/cachesim/main_hierarchical.cpp:77, src/cachesim/main_hierarchical_sweep.cpp:24); per-event dedup three times (src/cachesim/main.cpp:128-143, main_hierarchical.cpp:105, main_hierarchical_sweep.cpp:31); hybrid argument checks twice (main.cpp:74-79, main_hierarchical.cpp:169-172).

**Config values written as literals**
14. `outputs/tc.csv` default relative to cwd (src/nocsim/sim.py:255). Packet size 256 bits (src/nocsim/core/transaction.py:22-24). Port placement formulas (src/nocsim/core/noc.py:74-82).
15. cachesim sweep grid, 16 B line, 4x4 block, prefetch/pinning on (src/cachesim/main_hierarchical_sweep.cpp:80-86, :108, :114-115, :134). Policy forced to `lru` (src/cachesim/main.cpp:61, main_hierarchical.cpp:159).
16. Callers: `N_NODES = 16` (profiling/0831_all_layer_streams/run_compare.py:55, profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:46) instead of reading X*Y.

**Comments and docstrings that no longer match the code**
17. tiles.py module docstring says one tile per `dram_i` with `node_bound = total // dram_total` (src/nocsim/schedule/tiles.py:1-10); the code divides by DRAM, NoC and spatial factors (:131).
18. dram.py docstring skip table omits the `not is_last_K_dram` vmem condition and the single-node skip (src/nocsim/transactions/dram.py:11-15 vs src/nocsim/combine.py:294, :570).
19. `lif_count`/`mac_count` docstrings say the LIF dep is "noc_i-2" (src/nocsim/transactions/compute.py:82); combine uses the vmem-step ring (src/nocsim/combine.py:505-506). `t_chain` docstring says deps are "all K_max-row PEs" (src/nocsim/transactions/vmem.py:119) but LIF runs on all PEs.
20. steps.py docstring line "is_last_T -> skip vmem store to GB (result is not the final vmem yet)" contradicts itself (src/nocsim/schedule/steps.py:13).
21. combine.py cites `tracegen.py:282` (src/nocsim/combine.py:212); it still matches today, but line-number citations break silently.
22. cachesim comments describe `config.py/layout.py/policy.py/cache.py/sweep.py` as siblings (src/cachesim/main.cpp:1-4, src/cachesim/config.py:7-9, :25, src/cachesim/policy.h:2-3, src/cachesim/cache.h:2, src/cachesim/native_bridge.py:2, :93); four of those files are gone from src/cachesim. They also point at `profiling/0726/...` (src/cachesim/native_bridge.py:96).
23. Code comments point at design docs outside the code (src/nocsim/sim.py:155, :209; src/nocsim/combine.py:143, :193, :214; src/nocsim/core/generator.py:13; src/nocsim/eventsim/EventSim.h:3) and at an external CoSA backend not in the repo (src/nocsim/core/noc.py:19-30).

**Inconsistent conventions**
24. Metric asymmetry: `multicast` never adds `dram_cost` (src/nocsim/core/generator.py:131-162), but eventsim treats any send touching `dram_port` as DRAM (src/nocsim/eventsim/EventSim.h:128). In single-node mode a weight send with `src_port=dram_port` to a multi-PE group would be uncounted in Python and counted in eventsim (only matters if a single-node schedule has more than one PE).
25. Union syntax `int | None` (src/nocsim/core/noc.py:63, src/nocsim/transactions/weight.py:53) next to `Optional[...]` elsewhere; works only because of `from __future__ import annotations`.
26. `import math` placed after a relative import (src/nocsim/core/generator.py:39).

**Build products and data in git**
27. No `__pycache__` or compiled binary is tracked (`git ls-files` clean); `src/nocsim/eventsim/eventsim` and the three cachesim binaries are gitignored (.gitignore:60, :66-68).
28. About 297 MB of run outputs are tracked without LFS: `profiling/0823_stagewise_verify/stage3_nocsim/outputs/tc/*.csv` (20 files, 24 MB) and `.../outputs/weight_traces_single_node/**/sample_*.json.gz`.
29. The on-disk `eventsim` binary is dated 2026-08-20, but EventSim.h and main.cpp changed in commit ba468ed (2026-08-31; +38/-13 lines, including the dep-finish-time logic and `std::stod` for a fractional `--dram-latency`). Rebuild before trusting it.

---

## 5. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

- **Python.** Syntax needs Python 3.7+ (`from __future__ import annotations`, no newer features seen); this shell has system 3.12.3 and no `conda` on PATH, while callers and tests assume `conda run -n base` (e.g. profiling/0831_all_layer_streams/run_compare.py:25). `requirements.txt` is tracked but was not read (rule); no pyproject/setup.py.
- **Packages imported.** nocsim: `numpy` (src/nocsim/sim.py:41), PyYAML through `parsers` (src/parsers/layer.py:30); `tracegen` (for `--weight-trace`) also uses numpy via `archmodels.trace`. cachesim: PyYAML (src/cachesim/config.py:21). No gurobipy is needed for the JSON path (src/mip_solver/constants.py:16 says so); producing schedules upstream needs Gurobi.
- **Import path.** Nothing is installable; every caller sets `PYTHONPATH=<repo>/src` and `cwd=<repo>` (profiling/0831_all_layer_streams/run_compare.py:154-156).
- **External binaries.** `src/nocsim/eventsim/eventsim` (g++ with C++17, make) for `--simulate`; `src/cachesim/cache_*` (g++ -O3 C++17). Neither is built by any script; both fail with FileNotFoundError until `make` is run (src/nocsim/sim.py:232-236, src/cachesim/native_bridge.py:57-58).
- **Missing inputs.** The 31-layer comparison reads `profiling/0831_all_layer_streams/schedules/` and `weight_traces/` (run_compare.py:50-52), which are not tracked. Tests need `profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces/` and `outputs/schedules/loas/vgg16_T4_n5/` (tests/test_combine_cycles_table.py:45-52), absent here. Tracked inputs are only 4 multi-node schedules, 4 single-node schedules and 4 layer YAMLs under profiling/0823_stagewise_verify/, plus input spike traces (`input_trace/loas/*/*.npy`, 34 tracked files) used upstream by tracegen.
- **Hardcoded paths.** None absolute inside nocsim or cachesim. Relative-to-cwd default output (src/nocsim/sim.py:255). Callers fix one arch YAML and the node count (run_compare.py:49, :55).
- **Determinism.** nocsim and eventsim are deterministic (sorted groups; tc_id tie-break). Inputs from tracegen use sampling (`import random` at src/tracegen.py:31); seeds were not checked here.

---

## 6. Open questions the code cannot answer

1. Which commit's EventSim.h was the on-disk `eventsim` built from, and were the Stage 3 / 0831 baselines produced before or after the ba468ed changes?
2. Is `sim.run` (Gurobi path) still meant to be called by mip_solver, or can it and `decode()` be deleted?
3. Is LIF time meant to be 0 under `--weight-trace` (traces store `lif_cycles=None`), given that the baseline runs all use that flag?
4. Should `store_to_dram` (actor `gb_port`) block GB->PE sends in eventsim, as it does now?
5. Is the GB/DRAM port placement, matched to an external CoSA `testbench.cpp`, still needed now that eventsim takes `dram_port` explicitly?
6. Is `N_NODES = 16` in callers always equal to X*Y of the arch used, or should it come from the schedule?
7. Should `src/cachesim` be moved to dump/ now that wcache supersedes it, given the only live caller is the 0803 profiling sweep?
8. Which Python/conda environment produced the tracked baselines (no version is recorded in the code)?
9. Are the 297 MB of tracked tc/trace outputs required to be in git, or can they be regenerated and dropped?
10. Is the `spad_nocsim` arm in wcache filled from nocsim's `total_cycles`, and by which script?
