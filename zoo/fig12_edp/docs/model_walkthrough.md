# Pipeline walkthrough, step by step

One case = one (architecture x layer x sample). The running example is real:
**spinalflow x loas_vgg16 `layer_01_core_features_3` x sample 0** (3x3 conv,
CIN=64, COUT=64, HO=WO=32, T=4). All shown contents are actual file contents.
All relative paths are under `/u/yyu9/projects/neuro_cache_wcache/zoo/fig12_edp/`.

Per-case orchestration: `demo/run.py run_case()` executes steps 1 to 7 in one
worker process. `demo/all_bench/run.py` (via `launch.sh`) spawns one such
worker per case over the whole benchmark grid. The per-case work directory is
`demo/all_bench/cases/<arch>/<group>/<benchmark>/<layer>/sample_00000/`
(called `<case>/` below; recreated by the fresh run).

The energy model (steps 5 and 6) is the
self-contained archx zoo design `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/` and has
two equivalent entries into the same code:

- **standalone**: `cd /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp && ./script.sh`
  runs count + price on the design's bundled fixture cases and default table,
  using the bundled backend and saved inputs, without simulator data;
- **driven** (the pipeline): `fig12_edp/energy_driver.py` locates the design
  (`SNN_EDP_MODEL_ROOT`, or the in-repo `zoo/archx/zoo/snn_edp` design) and calls its
  `archx_aggregate_case` API on the case directories this pipeline produces.

---

## Step 1: weight-trace generation

- **Command**
  `python -m lays.weight_trace_gen gen --arch spinalflow --layer layer_01_core_features_3 --stream --sample-start 0 --sample-count 1`
- **Inputs**
  - capture `/work/nvme/bebv/yyu9/input_trace_delta/loas_vgg16_T4_n500/layer_01_core_features_3.npy` (recorded spike activity)
  - schedule `zoo/wt500_fig3cfg/outputs/schedules/spinalflow/loas_vgg16_T4_n500/layer_01_core_features_3.json`
- **Driver**: `src/lays/weight_trace_gen` (invoked as a subprocess by `demo/run.py`)
- **Functionality**: replays the capture's spikes through the schedule and
  streams out, record by record, every weight access the hardware would make
  for this sample.
- **Intermediate result**: `<case>/sample_00000.wcts` (binary, temporary) and
  `<case>/generation.json`.
- **Meaning**: the `.wcts` is the exact weight-access sequence (the "memory
  demand" of the layer); `generation.json` records how many records it holds.
- **Content**: `.wcts` is binary (records + a trailer with the exact record
  count); `generation.json` is two fields:
  ```json
  {"sha256": "...", "records": 5506411}
  ```
- **Feeds into**: step 3 (cachesim reads it), step 4 (nocsim reads it),
  step 2 (Prosperity's exact record count). Deleted at step 7; it is the only
  expensive intermediate and is never stored.

## Step 2: analytic event counts

- **Command**: none (in-process function call inside the worker)
- **Inputs**
  - this layer's capture `.npy` and the NEXT layer's capture (for the measured
    output density `d_out`)
  - the case identity `<case>/case.json`
- **Driver**: `demo/run.py count_case()`, which imports
  `counts/spinalflow_counts.py` and calls `count_sample(...)`
- **Functionality**: closed-form counting of the architecture's events for
  this layer: how many accumulations, weight-row reads, LIF steps, output
  spikes, from the spike data and layer geometry. No simulation.
- **Intermediate result**: `<case>/counts.json`
  (Prosperity also writes `<case>/record_count.csv` with its exact R_p)
- **Meaning**: the architecture-core activity: how many times each compute
  unit fires, independent of memory-system timing.
- **Content** (this case, verbatim):
  ```json
  {"S_win": 287641, "A": 18409024, "R": 4602256, "L": 262144,
   "O": 37756.0, "d_out": 0.1440277099609375, "COUT": 64, "T": 4,
   "HO": 32, "WO": 32, "cout_n": 4, "kernel": 3, ...}
  ```
  Read: 287,641 spike windows; A = S_win x COUT = 18,409,024 accumulations;
  R = A / cout_n = 4,602,256 weight-row reads; L = HO x WO x COUT x T =
  262,144 LIF steps; O = L x d_out output spikes.
- **Feeds into**: step 5 (every `spinalflow.*` count expression evaluates over
  these numbers).

## Step 3: cache simulation (the two cache arms)

- **Command** (run twice, config A and B)
  `demo/native_build/cachesim_run --trace <case>/sample_00000.wcts --config configs/production_cache_a.json --arm cache --header --out <case>/cache_a.csv`
- **Inputs**: the `.wcts` trace (step 1) + `configs/production_cache_{a,b}.json`
  (the two fixed cache configurations: 16KB 8-way L1, 512KB 16-way L2, 64B
  lines, prefetcher settings)
- **Driver**: the native `cachesim_run` binary, subprocess of `demo/run.py`
- **Functionality**: cycle-accurate replay of the weight-access trace through
  the two-level cache hierarchy; counts hits, misses, prefetches, DRAM
  traffic, and the finish time.
- **Intermediate result**: `<case>/cache_a.csv`, `<case>/cache_b.csv` (one data
  row each).
- **Meaning**: the cache arm's memory-system activity and its latency
  (`total_cycles`).
- **Content** (cache_a.csv, key columns of its single row):
  ```
  total_cycles=288439  l1_accesses=4602256  l1_hits=4601691
  l2_accesses=64  dram_accesses=576  dram_bytes=36864
  ```
  Read: the cache serves the 4,602,256 weight-row reads (= R from step 2) with
  a 99.99% L1 hit rate, needing only 576 DRAM accesses.
- **Feeds into**: step 5 (the `cache.*` count expressions and the cacheA/cacheB
  `total_cycles`).

## Step 4: NoC / DRAM simulation (the spad arm)

- **Command**: none (in-process: `nocsim.driver.run_case(schedule, arch, trace)`,
  which runs the native `eventsim` binary internally)
- **Inputs**: the schedule (as in step 1) + the `.wcts` trace
- **Driver**: `nocsim/driver.py`
- **Functionality**: rebuilds the tiled schedule, generates the
  network-on-chip traffic trace (weight multicasts, chain packets, global
  buffer and DRAM transactions), and replays it to a finish time.
- **Intermediate results**: `<case>/noc/tc.csv` (the traffic trace), then
  `<case>/noc/result.json` (its aggregated counters).
- **Meaning**: the scratchpad arm's memory-system activity and its latency.
- **Content** (noc/result.json, key fields, verbatim):
  ```json
  {"total_cycles": 292673, "weight_packet_hops": 9792,
   "chain_packet_hops": 0, "gb_reads": 1152, "gb_writes": 147456,
   "dram_accesses": 73728, "dram_bytes": 4718592,
   "l1_delivery_bytes": 36864}
  ```
  Read: the spad arm must stream weights over the NoC every reuse round:
  73,728 DRAM accesses and 4.7MB moved, against cacheA's 576 / 36.9KB.
- **Feeds into**: step 5 (the `shared.*` count expressions, the spad
  `l1_weight_spad.write` expression, and the spad `total_cycles`).

---

## Step 5: energy model stage A, "count" (archx)

- **Command** (standalone form; inside the pipeline `demo/run.py` calls the
  same code through `archx_aggregate_case` at `demo/run.py:185`)
  ```bash
  PYTHONPATH=/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo conda run --no-capture-output -n fig12-archx python -B \
    -m snn_edp.run count \
    --case <case> --out <counts-dir>
  ```
- **Inputs**
  - `<case>/case.json`, `<case>/counts.json`, `<case>/noc/result.json`,
    `<case>/cache_a.csv`, `<case>/cache_b.csv` (steps 2 to 4)
  - `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/hardware.json` (every module's geometry, instance
    count, which arms it applies to, and its count expression)
  - Layer selection has already run in the caller using `docs/workload_layer_scope.md`; Stage A reads no campaign scope file.
- **Driver**: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/run.py count()`, which invokes the archx
  engine three times (each logged to `<counts-dir>/archx_{0,1,2}.log`):
  ```
  archx -compile /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/designs/snn/description.py -r <counts-dir>
  archx -r <counts-dir> -extract <counts-dir>/configurations.csv
  archx -x <counts-dir>/runs.txt -r <counts-dir>
  ```
- **Functionality and intermediates, sub-step by sub-step**:

  **5a. compile.** archx runs `designs/snn/description.py`, which programmatically declares
  (AGraph API) three workloads (spad / cacheA / cacheB, each carrying only
  `case_dir`), the event tree, the module inventory, and the three metrics.
  archx writes the compiled description:
  - `<counts-dir>/workload/spad/config_0.workload.yaml`. Meaning: which case
    and which arm. Content (complete file):
    ```yaml
    workload:
      configuration:
        case_dir: /u/.../cases/spinalflow/B09/loas_vgg16_T4_n500/layer_01_core_features_3/sample_00000
      name: spad
    ```
  - `<counts-dir>/event/event.yaml`. Meaning: the event hierarchy, root
    `spad` -> categories `core_spad`/`memory_spad` -> one event per operation ->
    one leaf per physical module. Content (excerpt, verbatim):
    ```yaml
    spad__spinalflow__adder32__add:
      performance: /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/performance.py
      subevent:
      - m__spinalflow__adder32
    ```
  - `<counts-dir>/architecture/config_0.architecture.yaml` (module inventory:
    names, instances, geometry queries), `<counts-dir>/metric/metric.yaml`
    (dynamic_energy nJ / leakage_power mW / area mm2), `<counts-dir>/runs.txt`
    (the batch index).

  **5b. extract.** archx enumerates the compiled configurations into
  `<counts-dir>/configurations.csv`, 3 rows (one per arm). Meaning: the map
  from arm name to its compiled YAMLs and its run directory. Content (header +
  row 0, abridged):
  ```
  config_id,arch_path,workload_name,...,checkpoint_path
  0,.../architecture/config_0.architecture.yaml,spad,...,.../runs/spad/arch_0/config_0/checkpoint.json
  ```

  **5c. execute.** `archx -x` walks each arm's event tree, calling the
  callbacks in `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/performance.py`. Each operation event
  computes its count by evaluating its count expression (from
  `hardware.json`, simple arithmetic over named counters) against the right
  input file:

  | operation (spad arm) | expression | source | value |
  |---|---|---|---:|
  | `spinalflow.adder32.add` | `A` | counts.json | 18,409,024 |
  | `spinalflow.reg32.rmw` | `A+L` | counts.json | 18,671,168 |
  | `spinalflow.l1_weight_spad.read` | `R` | counts.json | 4,602,256 |
  | `spinalflow.l1_weight_spad.write` | `l1_delivery_bytes*8/32` | noc/result.json | 9,216 |
  | `shared.router.hop` | `weight_packet_hops+chain_packet_hops` | noc/result.json | 9,792 |
  | `shared.ddr4.read` | `dram_accesses` | noc/result.json | 73,728 |

  Cache arms use their own roster: `cache.l1.read` = `l1_accesses` from that
  arm's CSV (4,602,256 for cacheA); the weight-spad and global-buffer
  operations drop out; the cache/MSHR/prefetch operations come in; the hop
  expression becomes `chain_packet_hops` only (0 here). The result of 5c is
  one **counted event graph** per arm:
  `<counts-dir>/runs/{spad,cacheA,cacheB}/arch_0/config_0/checkpoint.json`.
  Meaning: the full event tree with every node's count filled in and every
  metric still zero (no prices exist in stage A). Content (one node, verbatim,
  abridged):
  ```json
  {"name": "spad__spinalflow__adder32__add", "instance": 1.0,
   "metrics": {"dynamic_energy": {"unit": "nJ", "value": 0.0},
               "leakage_power": {"unit": "mW", "value": 0.0},
               "area": {"unit": "mm^2", "value": 0.0}}}
  ```

  **5d. export.** `run.py` reads the three graphs back and writes
  `<counts-dir>/counts.json`: per arm, every operation's aggregated count
  (archx `aggregate_event_count`), plus each arm's `total_cycles` carried over
  from steps 3 and 4. Content (excerpt, verbatim):
  ```json
  {"arch": "spinalflow",
   "cycles": {"spad": 292673.0, "cacheA": 288439.0, "cacheB": 288875.0},
   "counts": {"spad": {"shared.ddr4.read": 73728.0,
                        "shared.ddr4_io.byte": 4718592.0,
                        "shared.gb.read": 1152.0, ...}}}
  ```
- **Final result of stage A**: the counts directory
  (`<layer>/archx_artifacts/<sample>/counts/<hash>/` when called from the
  pipeline; `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/runs/<arch>/fixture_counts/` in the worked example):
  compiled YAMLs + 3 counted graphs + `counts.json` + logs. **It contains no
  energy numbers and no price-table content.**
- **Feeds into**: step 6, and ONLY step 6. When a new energy table arrives
  (ASAP7 synthesis), execution resumes from step 6 directly; steps 1 to 5
  never rerun.

## Step 6: energy model stage B, "price" (archx)

- **Command**
  ```bash
  PYTHONPATH=/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo conda run --no-capture-output -n fig12-archx python -B \
    -m snn_edp.run price \
    --counts <counts-dir> --table /u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/energy_table.json --out <priced-dir>
  ```
- **Inputs**
  - the stage A counts directory (counted graphs + counts.json)
  - `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/energy_table.json`: per operation, the characterized unit costs.
    Content (one row's cost fields, verbatim):
    ```json
    "spinalflow.adder32.add": {"dynamic_energy_nJ": 2.15616e-05,
      "leakage_power_mW": 8.08e-06, "area_mm2": 0.000194088, ...}
    ```
- **Driver**: `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/pricing.py price()` (pure archx metric
  application; no simulator, no case files opened)
- **Functionality**: loads each arm's counted graph, binds the table's unit
  costs onto the graph's physical modules (`graph.init_metrics` +
  `graph.set_module_data`, with instance counts, e.g. adder32 = 4 lanes x 16
  nodes = 64 instances), then asks archx to aggregate
  (`aggregate_event_metric`): per-operation dynamic energy, total dynamic
  energy, module-deduplicated leakage power and area. The wrapper converts
  units: `T = total_cycles / 500MHz`, `E_leak = P_leak x T`,
  `EDP = (E_dyn + E_leak) x T`. A null cost (not yet synthesized) contributes
  zero and an explicit reason, so the row is a marked lower bound.
- **Intermediate results**: the three priced graphs
  `<priced-dir>/{spad,cacheA,cacheB}.graph.json` (same event trees, metrics now
  filled) and the exact table snapshot `<priced-dir>/energy_table.json`.
- **Meaning of the priced terms** (spad arm, verbatim from result.json):
  ```
  spinalflow.adder32.add : count 18,409,024 x 2.15616e-5 nJ = 396.93 nJ
  spinalflow.reg32.rmw   : count 18,671,168 x 6.46464e-5 nJ = 1,207.02 nJ
  shared.router.hop      : count 9,792 x null -> 0 nJ + reason recorded
  cache.l1.read (cacheA) : count 4,602,256 -> 8,086.53 nJ
  ```
- **Final result of stage B**: `<priced-dir>/result.json`: three rows (one per
  arm), each carrying totals, the per-term breakdown, and the lower-bound
  flags. Content (spad row, top-level fields, verbatim):
  ```json
  {"arch": "spinalflow", "arm": "spad",
   "E_dyn_nJ": 963461.13, "E_leak_nJ": 377853.89,
   "T_s": 0.000585346, "EDP_nJ_s": 785.133,
   "area_mm2": 57.85, "total_cycles": 292673.0,
   "frequency_MHz": 500, "incomplete": true}
  ```
- **Feeds into**: step 7.

## Step 7: per-case commit

- **Command**: none (in-process, end of `demo/run.py run_case()`)
- **Driver**: `demo/run.py` (lines 185 to 189): calls
  `archx_aggregate_case(arch, case_folder, energy_table_path)` which runs
  steps 5 and 6 into content-addressed sibling directories, then commits.
- **Functionality**: writes the case's durable `<case>/result.json` (the three
  arm rows from step 6) atomically, then **deletes `sample_00000.wcts`**.
- **Final per-case result**: `<case>/result.json`, three rows, plus the stage
  A/B artifact trees `<layer>/archx_artifacts/sample_00000/counts/<hash>/`
  and `.../energy/<hash>/`.
- **Feeds into**: step 8.

## Step 8: collection

- **Command** (after the wave finishes; also run automatically at wave end)
  ```bash
  PYTHONDONTWRITEBYTECODE=1 conda run -n fig12-archx python -B \
    zoo/fig12_edp/demo/all_bench/run.py --collect-only
  ```
- **Inputs**: every `<case>/result.json` (step 7) over the kept grid of
  `docs/workload_layer_scope.md`
- **Driver**: `demo/all_bench/run.py` + `report.py`
- **Functionality**: flattens the per-case rows into campaign CSVs and
  aggregates to whole models.
- **Final results**:
  - `demo/all_bench/results.csv`: one row per case x arm with the step 6
    fields (T_s, E_dyn_nJ, E_leak_nJ, EDP_nJ_s, incomplete, identity columns).
  - `demo/all_bench/whole_model.csv`: one row per benchmark x arch x arm:
    `sum_energy = sum over layers (E_dyn + E_leak)`, `sum_latency = sum T`,
    whole-model `EDP = (sum E) x (sum T)`. A model missing any kept layer gets
    blank totals (hatched in the figure), never a partial bar.
  - `demo/all_bench/coverage.json`: which groups are complete.
- **Feeds into**: step 9.

## Step 9: figures

- **Command**
  ```bash
  MPLCONFIGDIR=$PWD/zoo/fig12_edp/demo/all_bench/mplconfig PYTHONDONTWRITEBYTECODE=1 \
    conda run -n gurobi python -B zoo/fig12_edp/demo/all_bench/plot.py
  ```
- **Inputs**: `whole_model.csv`, `coverage.json` (step 8)
- **Driver**: `demo/all_bench/plot.py` (matplotlib, env `gurobi`)
- **Final results**: `demo/all_bench/figures/whole_model.pdf` + per-benchmark
  PNG/PDF: latency / energy / EDP bars, spad vs cacheA vs cacheB per
  architecture x benchmark; `*` marks lower-bound (unpriced modules) bars,
  hatch marks incomplete groups. These are the Figure 12 panels.

---

## Dependency list

```
step 1 (trace)        needs: capture.npy, schedule.json
step 2 (counts)       needs: capture.npy (this + next layer)        [independent of 1]
step 3 (cachesim)     needs: step 1 trace, production_cache_{a,b}.json
step 4 (nocsim)       needs: step 1 trace, schedule.json
step 5 (archx count)  needs: steps 2+3+4 outputs, hardware.json, scope doc, archx backend
step 6 (archx price)  needs: step 5 counts dir, energy_table.json   [ONLY step that sees prices]
step 7 (commit)       needs: step 6 rows; deletes the step 1 trace
step 8 (collect)      needs: step 7 result.json of every kept case
step 9 (plot)         needs: step 8 CSVs
```

Static inputs and where to modify them:

| File | Used by | Role |
|---|---|---|
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/hardware.json` | step 5 | module geometry, instances, arm applicability, count expressions |
| `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/energy_table.json` | step 6 | unit costs (regenerated by `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/energy_harvest.py` after synthesis) |
| `configs/production_cache_{a,b}.json` | step 3 | the two cache configurations |
| `zoo/wt500_fig3cfg/outputs/schedules/` | steps 1, 4 | per-case tiled schedules |
| `docs/workload_layer_scope.md` | steps 5, 8 | which layers are in scope |
| `frequency_MHz` argument of `price()` | step 6 | clock for T and leakage |

A new energy table re-enters the pipeline at step 6 only. A hardware geometry
change re-enters at step 5. A cache-config change re-enters at step 3. A
schedule change re-enters at step 1.

The energy implementation and authoritative counter interface live in
[archx/zoo/snn_edp](../../archx/zoo/snn_edp/README.md#saved-counter-interface).
`energy_driver.py` is the campaign adapter; all model drivers and worked-example
fixture paths are listed in the zoo’s WORKED_EXAMPLE.md. The pipeline produces
counter files and consumes three result rows without owning energy formulas.

## Named temporary weight trace

For sample0 the generator writes
`demo/all_bench/cases/<arch>/<group>/<benchmark>/<layer>/sample_00000/sample_00000.wcts`
under fig12_edp. The filename is deterministic, including the sample index;
`sample_00000.part` is the uncommitted write. `generation.json` retains its
absolute `trace_path`, source `capture_path`, exact `generator_command` and
working directory, schedule path/hash, sample, record count and trace SHA256.
Each final row repeats that record under `input_count_provenance.trace`, so the
trace remains identifiable after the WCTS file is deleted. The pipeline commits
`result.json` before deleting the trace. No captured input is changed.

For hardware/event/formula inspection use the
[manual check map](../../archx/zoo/snn_edp/docs/manual_check_map.md).
