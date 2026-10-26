# Code atlas: src/nocsim

Built from code only, at commit 39efd64 (branch wcache-rebuild-phase-a). No
.md/.txt/log/dump/debug file was read. Line numbers come from `grep -n` and
`sed -n`. All paths are relative to the repo root.

WCTS: nocsim does not read WCTS streams. Its only trace input is one
per-step cycles `sample_NNNNN.json.gz` (per tile: dram_i, noc_i, mac_cycles,
lif_cycles; no weight addresses), read by `tracegen.load_step_cycles`
with `json.load` (src/nocsim/sim.py:336-338, src/tracegen.py:471, :489);
`grep -i wcts src/nocsim` finds nothing.

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
| `--out CSV` (default `outputs/tc.csv`, relative to cwd) | src/nocsim/sim.py:255, :284 | Suffix `.csv` or `.json` (src/nocsim/core/generator.py:179). |
| `--weight-trace JSON_GZ` (optional) | src/nocsim/sim.py:291 | One per-step cycles `sample_NNNNN.json.gz` (written by `tracegen.save_step_cycles`, src/tracegen.py:356); loaded by `tracegen.load_step_cycles` (src/tracegen.py:471), giving per-step MAC cycles. |
| `--simulate` (flag) | src/nocsim/sim.py:300 | After writing the CSV, runs `src/nocsim/eventsim/eventsim` and prints its 5 counters. |
| `run(x, prob, bitwidths, out_file, ...)` | src/nocsim/sim.py:79 | Gurobi-variable path (`decode()`); no caller in src/, scripts/, profiling/ or tests/. |
| `run_from_json(schedule_path, ...)` | src/nocsim/sim.py:137 | JSON path used by the CLI. |
| `run_eventsim(csv_path, X, Y, dram_port, dram_latency, binary=None)` | src/nocsim/sim.py:198 | subprocess to the C++ binary, parses one JSON line. |
| `eventsim <tc.csv> --X --Y --dram-port --dram-latency` | src/nocsim/eventsim/main.cpp:24, :60 | All four flags required (src/nocsim/eventsim/main.cpp:53). Build: `make` in src/nocsim/eventsim (g++ -O2 -std=c++17, src/nocsim/eventsim/Makefile:1-2; the target also depends on constants.h, :11). |

Exit codes of the CLI: 0 ok; 2 on bad inputs, bad weight trace, failed
simulation, missing or failing eventsim (src/nocsim/sim.py:323-397).

### 1.3 Who calls nocsim

- `src/tracegen.py:39-40` imports `schedule_from_strategy`, `iter_node_tiles`
  (weight-trace generation, the input of both nocsim `--weight-trace` and wcache).
- `src/archmodels/dense.py:18` imports `Schedule`, and
  `src/nocsim/combine.py:75` imports `DenseStaticComputeModel` back: a
  two-way package dependency.
- `scripts/generate_weight_traces.py:52` imports `schedule_from_strategy`.
- `profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:64` and
  `profiling/0831_all_layer_streams/run_compare.py:131` run
  `python -m nocsim.sim ... --weight-trace ... --simulate` with
  `cwd=ROOT`, `PYTHONPATH=ROOT/src`, and parse the `total_cycles:` etc. lines
  from stdout. run_compare.py:50 fixes the arch YAML to
  `loas_inst16_node32kb_noc2MiB_pe16.yaml`; :56 hardcodes `N_NODES = 16`
  to turn `count_cycles` into per-node compute. Its layer list now comes from
  `profiling/common.py` `tags()` (run_compare.py:45-46).
- Later profiling stages (0903_l1_8k, 0907_*, 0831_l2_prefetch,
  stage4_wcache) read `all_layers_vs_nocsim.csv` / `stage3_results.json`
  produced above and report wcache as a speedup over nocsim.
- wcache's C++ apps accept `--arm spad_nocsim` only as a label for the
  `arm` column (src/wcache/native/apps/app_support.h:76-80); no wcache code
  calls nocsim.
- tests: see 2.7.

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
6. **`TC_Generator.to_file()` -> `tc.csv`** (src/nocsim/core/generator.py:179):
   two lines per TC: `# annotation` then `tc_id,actor_id,op,size,src,dest,dep`.
7. **(optional) `tc.csv` -> eventsim -> JSON** (src/nocsim/eventsim/EventSim.h:54):
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
       tc.csv  ──►  eventsim (C++: NoC.h, Transaction.h, EventSim.h, constants.h)
```

Conventions that hold everywhere:
- Dims are `parsers.layer.DIM_*`: KH=0, KW=1, CIN=2, COUT=3, HO=4, WO=5, T=6
  (src/parsers/layer.py:35-41). K (reduction) dims = {KH, KW, CIN}.
- Tensor-dim relevance is `mip_solver.constants._A` (src/mip_solver/constants.py:76):
  weight uses KH,KW,CIN,COUT; psum uses COUT,HO,WO,T; vmem uses COUT,HO,WO
  (vmem size does not depend on T).
- Way-2 PE layout: X axis = T, WO, HO (inner->outer); Y axis = CIN, KW, KH,
  COUT; `pe_id = y*X + x` (src/nocsim/combine.py:179-180,
  src/nocsim/schedule/buf_spatial.py:54).
- Loop lists are always inner->outer; the strategy JSON stores temporal
  loops outer->inner and decode reverses them (src/nocsim/schedule/decode.py:278, :282).
- A packet is 256 bits = 4 payload flits of 64 bits
  (src/nocsim/core/transaction.py:36-38). The flit count has one source,
  src/nocsim/eventsim/constants.h:5, which both the C++ build and the
  Python module read (see 2.3 and 2.6).

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
   b. For each `noc_i` (:325): (1) weight load if `weight_changes` (:375);
      (2) psum load to K-chain tail PEs (:409); (3) MAC COUNT on every PE
      (:425); (4) K-chain unicasts (:435); (5) psum store from K tails
      (:450); if not last-K, next step (:460). Else (6) vmem load to T-chain
      head PEs (:484); (7) LIF COUNT on every PE (:507); (8) T-chain
      (:515); (9) vmem store from T tails (:529).
   c. GB->DRAM stores for psum and vmem (:551-576), which also set the
      dependency the next `dram_i`'s DRAM loads wait on.
4. Dependency rules (module docstring :25-48, code :364-537): sequential GB
   weight sends (noc_i-1); node double buffer (MAC at noc_i-2); GB double
   buffer for psum (store at noc_i-2) and same-T data order (store at
   noc_i - T_noc_steps); vmem/LIF use 2-deep rings counted in "vmem steps"
   (last-K firings), not raw noc_i (:309-310).
5. "GB-free" flags force skips: if K dims are innermost in the integrated
   NoC+DRAM loop, psum never goes to GB (passed as `is_first_K=True`,
   `is_last_K=True`, :411, :452); same for vmem with T (:486, :531).
6. Single-node arch (`arch.single_node`, src/parsers/arch.py:172): there is
   no GB leg; loads/stores use `src_port/dest_port = dram_port` (:380, :414,
   :455, :489, :534), and RAW ordering across `dram_i` comes from the last
   NoC-step store (:557-559, :572-574).

---

## 2. Bottom-up

### 2.1 src/nocsim/sim.py

- `_solver_result(data: Dict) -> Dict` (src/nocsim/sim.py:62): `data.get("result", data)`; accepts both schedule JSON shapes.
- `run(x, prob, bitwidths, out_file, y=None, arch=None, compute_model=None, trace=None, cycles_by_step=None) -> (unicast_hops, multicast_hops, dram_cost)` (src/nocsim/sim.py:79): decode Gurobi vars -> combine -> write. `y` is unused (:84, :99).
- `run_from_json(schedule_path, prob, bitwidths, out_file, arch=None, compute_model=None, trace=None, cycles_by_step=None)` (src/nocsim/sim.py:137): same via `schedule_from_strategy`; `ValueError` if `has_solution` is false (:178).
- `_DEFAULT_EVENTSIM_BINARY` (src/nocsim/sim.py:195): `<this dir>/eventsim/eventsim`.
- `run_eventsim(csv_path, X, Y, dram_port, dram_latency, binary=None) -> Dict[str,int]` (src/nocsim/sim.py:198): `subprocess.run(check=True)`; `FileNotFoundError` if not built (:232-236).
- `_DEFAULT_OUT = "outputs/tc.csv"` (src/nocsim/sim.py:255).
- `_build_parser()` (src/nocsim/sim.py:258): flags in 1.2.
- `main(argv=None) -> int` (src/nocsim/sim.py:312): `tracegen` imported lazily (:335) to avoid an import cycle. TC count is re-read from the written file (:353). With `--simulate` it re-opens the JSON, rebuilds the Schedule and recomputes X, Y and `NoC(X,Y).dram_port` (:375-381) instead of getting them from combine.

### 2.2 src/nocsim/combine.py

- `_dim_totals(loops) -> Dict[int,int]` (src/nocsim/combine.py:95): product of factors per dim.
- `_vals(d) -> List[int]` (src/nocsim/combine.py:103): dict values as list.
- `_chain_tails(chain_dict) -> List[int]` (src/nocsim/combine.py:108): last link id per chain group; single-PE groups contribute nothing, so callers fall back to the COUNT ids (:443-444, :521-522).
- `combine(schedule, bs, si, prob, bitwidths, arch=None, compute_model=None, trace=None, cycles_by_step=None) -> TC_Generator` (src/nocsim/combine.py:120): see 1.6. Details: a missing `(dram_i, noc_i)` key in `cycles_by_step` raises `KeyError` on purpose (:332-337). `lif_cycles=None` becomes 0 (:235, :339); traces written by tracegen store `lif_cycles=None` (src/tracegen.py:282), so with `--weight-trace` every LIF COUNT is 0 cycles. `T_noc_steps` = product of T factors at NoC level (:251). `model` is built even when `cycles_by_step` makes it unused (:224). Sparse per-dram_i history is now only `vs_hist` (:305); the unused `lif_hist` was removed in f17278d.

### 2.3 src/nocsim/core/

**noc.py**
- `Link` (src/nocsim/core/noc.py:38): `((x0,y0),(x1,y1))`.
- `class NoC(X, Y, gb_port=None, dram_port=None)` (src/nocsim/core/noc.py:41, `__init__` :59): `num_rports = 4XY - 2Y(X-1) - 2X(Y-1)` (:74), which equals `2X+2Y`; `num_ports = XY + num_rports`. Defaults: `gb_port = X*Y` (:78) -> coordinate (0, Y); `dram_port = num_ports-(X+Y) = XY+X+Y` (:79-82), chosen to match an external CoSA C++ backend (`testbench.cpp`, not in this repo). Both must lie in `[X*Y, num_ports)` and differ (:84-94).
- `get_xy(pe_id)` (src/nocsim/core/noc.py:100): `(id % X, id // X)`, also used for ports past the grid.
- `_hops_single(src, dest)` (src/nocsim/core/noc.py:111): XY route as list of links. Only caller is `count_hops` (:145).
- `count_hops(src, dests)` (src/nocsim/core/noc.py:134): unique links over all dests. Not called anywhere.
- `manhattan(src, dest)` (src/nocsim/core/noc.py:148): used for all hop metrics.
- `all_pe_ids()` (src/nocsim/core/noc.py:158): not called anywhere.

**transaction.py**
- `UNICAST=0, MULTICAST=1, COUNT=2` (src/nocsim/core/transaction.py:17-19).
- `_EVENTSIM_CONSTANTS_H` (src/nocsim/core/transaction.py:24): path to `src/nocsim/eventsim/constants.h`, found from `__file__`.
- `_read_flits_per_packet() -> int` (src/nocsim/core/transaction.py:27): regex `^constexpr int FLITS_PER_PACKET = (\d+);` over the header; `RuntimeError` if the line is missing (:31-32). It runs at import time (:37), so importing `nocsim.core.transaction` (and therefore `combine`, `sim`) needs the header on disk. `nocsim.schedule` does not import `core`, so tracegen and archmodels do not trigger this read.
- `FLIT_SIZE=64`, `FLITS_PER_PACKET` (read from the header, currently 4), `PACKET_SIZE = FLIT_SIZE*FLITS_PER_PACKET` = 256 bits (src/nocsim/core/transaction.py:36-38).
- `class TC(tc_id, actor_id, op, deps, var_name, entries, datawidth, annotation="")` (src/nocsim/core/transaction.py:44): `srcs` is always `[actor_id]`; `size` is packets (send) or cycles (COUNT). `create_unicast` :88, `create_multicast` :93, `create_count` :98, `_fmt` :107, `format_csv` :111 (columns `tc_id,actor_id,op,size,src,dest,dep`). `var_name/entries/datawidth` reach only the JSON output.
- `class TCEncoder(JSONEncoder)` (src/nocsim/core/transaction.py:133): dumps `TC.__dict__`; used only by `to_file(.json)`.

**generator.py**
- `_TRAFFIC_VARS = ("weight","psum","vmem")` (src/nocsim/core/generator.py:38).
- `class TC_Generator(noc, dram_latency=0.25)` (src/nocsim/core/generator.py:41, `__init__` :53): owns the tc_id counter, `tcs`, and three cost dicts pre-seeded with all three keys. The label registry `write_deps` and its lookups `_get_reqs`/`get_deps` were removed in f17278d; labels now reach only the CSV comment line.
- `_num_packets(size_bits)` (src/nocsim/core/generator.py:75): ceil(size_bits/256). Note: 0 bits gives 0 packets.
- `_append(tc)` (src/nocsim/core/generator.py:79): stores the TC and returns its id (no label argument any more).
- `unicast(var_name, size_bits, datawidth, src, dest, deps, label) -> int` (src/nocsim/core/generator.py:89): `unicast_hops += manhattan + 4*packets` only when `src == gb_port and dest != dram_port` (:114); `dram_cost += ceil(packets*dram_latency)` when either end is `dram_port` (:118-119). PE->GB stores and PE->PE chains add nothing to any metric.
- `multicast(...)` (src/nocsim/core/generator.py:123): GB-sourced only: `multicast_hops += max manhattan + 4*packets` (:149-152, "farthest node"). No `dram_cost` branch.
- `count(cycles, node_id, deps, label)` (src/nocsim/core/generator.py:156).
- `to_file(out_file)` (src/nocsim/core/generator.py:179): `.csv` or `.json`, else `ValueError`.

### 2.4 src/nocsim/schedule/

**decode.py**
- `class LoopItem(dim, dim_name, factor, level)` (src/nocsim/schedule/decode.py:48): one prime factor; lower `level` = more inner.
- `class Schedule(spatial_factors, noc_temporal_loops, dram_temporal_loops, data_size, gb_start, dram_start, perm_levels)` (src/nocsim/schedule/decode.py:65); `noc_num_steps` :92 and `dram_num_steps` :100 are products of factors.
- `decode(x, prob) -> Schedule` (src/nocsim/schedule/decode.py:112): reads Gurobi `.X > 0.5` (:138). Levels: NoC slots `[1, 1+P)`, DRAM slots `[1+P, 1+2P)` with `P` = total prime-factor count and `SNN_GB_START_LEVEL = 1` (src/mip_solver/constants.py:51). `data_size` multiplies every factor at levels below `dram_start` for dims relevant to the tensor (:181-191). Only reached from `sim.run` (src/nocsim/sim.py:127).
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
- `_CORE_ID_ORDER = [T, WO, HO, CIN, KW, KH, COUT]` (src/nocsim/schedule/tiles.py:59): same order as Way-2, so `core_id == pe_id`.
- `encode_core_id(idx, spatial_factors)` (src/nocsim/schedule/tiles.py:62): inverse of decode; no caller in src/scripts/profiling/tests.
- `decode_core_id(core_id, spatial_factors)` (src/nocsim/schedule/tiles.py:72): radix 1 for missing dims.
- `_dim_totals(loops)` :86 (second copy).
- `iter_node_tiles(schedule, prob) -> Iterator[NodeTileSpec]` (src/nocsim/schedule/tiles.py:99): one spec per `(dram_i, noc_i, core_id)`, nested in that order. `node_bound[j] = max(total_j // (dram_t*noc_t*spatial), 1)` (:133-134). `tile_offset[j]` = spatial slice + NoC offset + DRAM offset (:156-161), only for dims that vary. Builds its own `StepInfo` (:125) for `is_last_K`. Imports the private `steps._decode_dim` (:47).

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
used only in the CSV comment line.

- `mac_count(gen, node_ids, pe_cycles, deps, label_prefix)` (src/nocsim/transactions/compute.py:26) and `lif_count(...)` (src/nocsim/transactions/compute.py:61): one COUNT per PE with the same deps; identical bodies. LIF runs on all PEs, not only the K-max row.
- `load_from_dram(gen, var_name, data_size, datawidth, skip, deps, label_prefix) -> Optional[int]` (src/nocsim/transactions/dram.py:44): DRAM->GB, whole tile; `None` when skipped. The module docstring skip table (:11-17) now lists the single-node and `not is_last_K_dram` conditions combine passes.
- `store_to_dram(...)` (src/nocsim/transactions/dram.py:82): GB->DRAM; actor is `gb_port`.
- `load_weight(gen, bs, data_size, bw_weight, weight_changes, deps, label_prefix, src_port=None)` (src/nocsim/transactions/weight.py:45): `{}` if weight unchanged (:86); unicast for single-PE groups, multicast otherwise.
- `load_psum(..., is_first_K, deps, label_prefix, src_port=None)` (src/nocsim/transactions/psum.py:31): GB -> each K-chain tail; `{}` if first K.
- `k_chain(gen, bs, data_size, bw_psum, deps, label_prefix)` (src/nocsim/transactions/psum.py:86): link i+1 depends only on link i; first link on `deps`.
- `store_psum(..., is_last_K, deps, label_prefix, dest_port=None)` (src/nocsim/transactions/psum.py:141): K tail -> GB; `{}` if last K.
- `load_vmem(..., is_first_T, ...)` (src/nocsim/transactions/vmem.py:41): GB -> T-chain head.
- `t_chain(...)` (src/nocsim/transactions/vmem.py:95): T head -> tail serial links.
- `store_vmem(..., is_last_T, ...)` (src/nocsim/transactions/vmem.py:147): T tail -> GB.

### 2.6 src/nocsim/eventsim/ (C++17)

- `constants.h` (new in 6835b9c): `FLITS_PER_PACKET = 4` (src/nocsim/eventsim/constants.h:5), the single definition for both languages. Its header comment (:1-2) says each value must stay on one `constexpr int NAME = N;` line because transaction.py parses it with a regex.
- `Link`, `struct NoC` (src/nocsim/eventsim/NoC.h:15, :17): `get_xy` :22, `manhattan` :26, `hops_single` :34, copies of noc.py. No port defaults: `dram_port` comes from the CLI.
- `struct Transaction` (src/nocsim/eventsim/Transaction.h:16); `parse_int_list` :26; `split_csv_line` :34; `parse_csv(path)` :49: skips empty and `#` lines; exactly 7 fields or throws.
- EventSim.h includes `constants.h` (src/nocsim/eventsim/EventSim.h:36) instead of defining the flit count itself.
- `struct SimResult` (src/nocsim/eventsim/EventSim.h:38); `touches_dram(tc, dram_port)` :46.
- `simulate(tcs, noc, dram_port, dram_latency) -> SimResult` (src/nocsim/eventsim/EventSim.h:54): list scheduler. A TC becomes ready when all deps have completed; ready ties go by ascending tc_id (:106). Start = max(dep finish times :130-133, actor free time, free time of every link on its route). Durations: COUNT = `size`; DRAM-touching send = `ceil(size*dram_latency)` with no links (:139-144); other sends = `hops + FLITS_PER_PACKET*size`, multicast routed only to its farthest dest (:160, :170). An actor runs one TC at a time, and only its last finish is kept (:175), so there is no backfilling into earlier gaps. Every GB-sourced send (and `store_to_dram`) has actor `gb_port`, so they serialize. `*_cycles` are sums of durations; `total_cycles` is the makespan. Unknown dep ids or a cycle throw (:74-77, :201).
- `struct Args`, `parse_args`, `main` (src/nocsim/eventsim/main.cpp:17, :24, :60): prints one JSON line (:68-73).

### 2.7 Tests that touch nocsim (tests/)

- tests/test_flits_per_packet.py (new in 6835b9c): pytest test `test_eventsim_uses_python_flits_per_packet` (:36). `_unicast_cycles(size, tmp_path)` (:26) writes a one-row CSV (a GB-free unicast, PE 0 -> PE 1 on a 4x4 mesh, `--dram-port 33`) and runs the built binary; the cycle difference between sizes 20 and 10, divided by 10, must equal Python's `FLITS_PER_PACKET`. This also catches a binary that is stale against constants.h. Skips if the binary is missing (:37-38). It is the only pytest-style test here; it needs `PYTHONPATH=src` (no conftest, no installed package).
- tests/test_step_cycles.py: `tracegen.load_step_cycles` key coverage, single-node shape, identity guard, duplicate keys, tile count. Real-data checks skip if the 0823 Stage 2 corpus is absent.
- tests/test_combine_cycles_table.py: `combine(cycles_by_step=...)` charges each step its trace value, differs from dense, works single-node, missing key raises. Needs `profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces/...` and `outputs/schedules/loas/vgg16_T4_n5` (lines 45-52), neither present in this worktree.
- tests/test_sim_weight_trace.py: CLI end to end (`--weight-trace`, both JSON shapes, `--simulate`); needs the same corpus and the eventsim binary (line 183).
- tests/test_eventsim_deps.py: hand-written CSVs check that deps delay successors across actors, fan-in takes the max, chains add up. Skips if the binary is missing (lines 91-92).
- tests/test_weight_resend.py: `StepInfo.weight_changes` sends equal the reloads the schedule calls for (campaign schedules), plus a synthetic nest.
- The four script-style tests above now document their run line as `conda run -n ${CONDA_ENV:-cosa_snn}` (e.g. tests/test_step_cycles.py:19), matching the default in scripts/env.sh:4.

---

## 3. src/cachesim (removed)

cachesim was removed on 2026-10-26 (superseded by wcache; last used by profiling/0803).

---

## 4. Findings for cleanup (code evidence)

Resolved by phase 2 and removed from this list: the label registry
`write_deps/_get_reqs/get_deps` (deleted, f17278d); the write-only
`lif_hist` (deleted, f17278d); the hand-kept `FLITS_PER_PACKET` copy
(now one definition in src/nocsim/eventsim/constants.h:5, parsed by
src/nocsim/core/transaction.py:27, checked by tests/test_flits_per_packet.py);
the stale tiles.py, dram.py, compute.py, vmem.py and steps.py docstrings
(fixed in 39efd64); the tracked 0823 Stage 3 bulk outputs (untracked in
9012d22, .gitignore:128-129); the stale on-disk eventsim binary (rebuilt
2026-10-25 22:02, after the last eventsim source change in 6835b9c).

**Dead or unreachable code**
1. `NoC.count_hops` and `NoC.all_pe_ids` (src/nocsim/core/noc.py:134, :158) have no callers; `NoC._hops_single` (:111) is called only by `count_hops` (:145).
2. `sim.run` and `decode()` (src/nocsim/sim.py:79, src/nocsim/schedule/decode.py:112): the Gurobi path has no caller in the tree; `y` arg is unused (src/nocsim/sim.py:84).
3. `encode_core_id` (src/nocsim/schedule/tiles.py:62): no caller outside debug/.
4. `combine`'s `compute_model`/`trace` parameters (src/nocsim/combine.py:127-128): no caller passes them (the CLI never does).

**Duplicated logic**
6. Dim-totals helper in three places: src/nocsim/combine.py:95, src/nocsim/schedule/tiles.py:86, src/nocsim/schedule/steps.py:250 (plus inline at src/nocsim/schedule/decode.py:288-290 and in src/archmodels/dense.py).
7. Mesh X/Y formula in src/nocsim/combine.py:179-180 and src/nocsim/sim.py:379-380; `--simulate` also re-reads and re-decodes the JSON (src/nocsim/sim.py:375-377).
8. `_K_DIMS` in src/nocsim/schedule/steps.py:50 (frozenset) and src/nocsim/schedule/buf_spatial.py:57 (tuple); Way-2 order in buf_spatial.py:54 and tiles.py:59.
9. psum.py and vmem.py builders are the same three shapes (load/chain/store); `mac_count` and `lif_count` have identical bodies (src/nocsim/transactions/compute.py:26, :61); `load_from_dram`/`store_to_dram` differ only in direction (src/nocsim/transactions/dram.py:44, :82).
10. Values still kept equal by hand across languages or modules: XY routing (src/nocsim/core/noc.py:111 vs src/nocsim/eventsim/NoC.h:34); default `dram_latency=0.25` (src/nocsim/core/generator.py:53 vs src/parsers/bitwidths.py:35).

**Config values written as literals**
12. `outputs/tc.csv` default relative to cwd (src/nocsim/sim.py:255). Flit width 64 bits (src/nocsim/core/transaction.py:36). Port placement formulas (src/nocsim/core/noc.py:74-82).
14. Callers: `N_NODES = 16` (profiling/0831_all_layer_streams/run_compare.py:56, profiling/0823_stagewise_verify/stage3_nocsim/run_stage3.py:46) instead of reading X*Y.

**Comments and docstrings that no longer match the code**
16. combine.py cites `tracegen.py:282` (src/nocsim/combine.py:212); it still matches today, but line-number citations break silently.
18. Code comments point at design docs outside the code (src/nocsim/sim.py:155, :209; src/nocsim/combine.py:143, :193, :214; src/nocsim/core/generator.py:12; src/nocsim/eventsim/EventSim.h:3) and at an external CoSA backend not in the repo (src/nocsim/core/noc.py:19-30).

**Inconsistent conventions**
19. Metric asymmetry: `multicast` never adds `dram_cost` (src/nocsim/core/generator.py:123-154), but eventsim treats any send touching `dram_port` as DRAM (src/nocsim/eventsim/EventSim.h:127). In single-node mode a weight send with `src_port=dram_port` to a multi-PE group would be uncounted in Python and counted in eventsim (only matters if a single-node schedule has more than one PE).
20. Union syntax `int | None` (src/nocsim/core/noc.py:63, src/nocsim/transactions/weight.py:53) next to `Optional[...]` elsewhere; works only because of `from __future__ import annotations`.
21. `import math` placed after a relative import (src/nocsim/core/generator.py:32-33).

**Build products and data in git**
22. No `__pycache__` or compiled binary is tracked (`git ls-files` clean); `src/nocsim/eventsim/eventsim` is gitignored (.gitignore:60).

---

## 5. Reproducibility gaps (fresh machine, e.g. NCSA Delta)

- **Python.** Syntax needs Python 3.7+ (`from __future__ import annotations`, no newer features seen); this shell has system 3.12.3 and no `conda` on PATH, while callers and tests document `conda run -n ${CONDA_ENV:-cosa_snn}` (e.g. profiling/0831_all_layer_streams/run_compare.py:25; default also in scripts/env.sh:4). `requirements.txt` is tracked but was not read (rule); no pyproject/setup.py. tests/test_flits_per_packet.py needs pytest.
- **Packages imported.** nocsim: `numpy` (src/nocsim/sim.py:41), PyYAML through `parsers` (src/parsers/layer.py:30); `tracegen` (for `--weight-trace`) also uses numpy via `archmodels.trace`. No gurobipy is needed for the JSON path (src/mip_solver/constants.py:16 says so); producing schedules upstream needs Gurobi.
- **Import path.** Nothing is installable; every caller sets `PYTHONPATH=<repo>/src` and `cwd=<repo>` (profiling/0831_all_layer_streams/run_compare.py:138-140).
- **Source files read at run time.** `import nocsim.core.transaction` reads src/nocsim/eventsim/constants.h (src/nocsim/core/transaction.py:24, :37), so a copy of the Python package without the eventsim directory fails at import.
- **External binaries.** `src/nocsim/eventsim/eventsim` (g++ with C++17, make) for `--simulate`. No script in scripts/ or profiling/ builds it; it fails with FileNotFoundError until `make` is run (src/nocsim/sim.py:232-236).
- **Missing inputs.** The 31-layer comparison reads `profiling/0831_all_layer_streams/schedules/` and `weight_traces/` (run_compare.py:51, :53), which are not tracked. Tests need `profiling/0823_stagewise_verify/stage2_weight_trace/outputs/weight_traces/` and `outputs/schedules/loas/vgg16_T4_n5/` (tests/test_combine_cycles_table.py:45-52), absent here. Tracked inputs are 4 multi-node schedules (stage2_weight_trace/inputs/schedules), 4 single-node schedules and 4 layer YAMLs under profiling/0823_stagewise_verify/stage3_nocsim/inputs/, plus 33 tracked files under `input_trace/loas/` (31 `.npy` spike traces and their meta.json) used upstream by tracegen. The Stage 3 `outputs/tc/` and `outputs/weight_traces_single_node/` are now untracked (.gitignore:128-129) and must be regenerated.
- **Data root.** `src/util.py` `data_root()` ($NEURO_CACHE_DATA, default `<repo>/data`) is not used by nocsim.
- **Hardcoded paths.** None absolute inside nocsim. Relative-to-cwd default output (src/nocsim/sim.py:255). Callers fix one arch YAML and the node count (run_compare.py:50, :56).
- **Determinism.** nocsim and eventsim are deterministic (sorted groups; tc_id tie-break). Inputs from tracegen use sampling (`import random` at src/tracegen.py:29); seeds were not checked here.

---

## 6. Open questions the code cannot answer

1. Were the Stage 3 / 0831 baselines produced before or after the ba468ed eventsim changes (dep-finish-time logic, fractional `--dram-latency`)? The binary on disk is now rebuilt from current sources, so it no longer records which version produced them.
2. Is `sim.run` (Gurobi path) still meant to be called by mip_solver, or can it and `decode()` be deleted?
3. Is LIF time meant to be 0 under `--weight-trace` (traces store `lif_cycles=None`), given that the baseline runs all use that flag?
4. Should `store_to_dram` (actor `gb_port`) block GB->PE sends in eventsim, as it does now?
5. Is the GB/DRAM port placement, matched to an external CoSA `testbench.cpp`, still needed now that eventsim takes `dram_port` explicitly?
6. Is `N_NODES = 16` in callers always equal to X*Y of the arch used, or should it come from the schedule?
8. Which Python/conda environment produced the tracked baselines (no version is recorded in the code)?
9. Is the `spad_nocsim` arm in wcache filled from nocsim's `total_cycles`, and by which script?
