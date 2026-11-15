# SNN energy and delay model

This self-contained archx zoo design models SpinalFlow, PTB, LoAS, GustavSNN
and Prosperity with scratchpad, cacheA and cacheB memory arms.
`designs/snn/description.py` defines workload, hardware, events and metrics using
AGraph. The vendored archx backend compiles and executes it; there is no
energy-join fallback. [CONFIGURATION.md](CONFIGURATION.md) lists every module,
geometry, interface, inventory and performance expression.

## Saved-counter interface

A caller supplies one directory per (architecture, layer, sample). Files are
UTF-8 JSON objects or header-bearing CSVs. CSVs have exactly one data row.
Unknown extra fields are retained as provenance or ignored. Numeric counters
are finite and nonnegative; integer event totals are exact counts. No raw
capture, schedule, trace, simulator executable or campaign repository is read.
Paths embedded in provenance are descriptive strings, never opened.

| Relative file | Required content and units |
|---|---|
| `case.json` | `arch`: `spinalflow`, `ptb`, `loas`, `gustavsnn` or `prosperity`; `layer` and `trace_relative_dir`: opaque identity strings. |
| `counts.json` | All arches: positive integer `HO`, `WO`, `COUT`, `CIN`, `T`, `cout_n`; `d_out` in [0,1], the next-layer input firing density (a final-layer proxy must be labeled by the producer). SpinalFlow/GustavSNN: `S_win`; PTB/LoAS: `S_sum` and `S_or`. Counts span the whole layer and all nodes. Derived A/L/O/R/B fields may be supplied, but the performance model recomputes them. |
| `noc/result.json` | `sample_idx`; `total_cycles` for spad; `weight_packet_hops` and `chain_packet_hops` (multicast tree-edge traversals); `gb_reads`, `gb_writes` (32-byte words); `l1_delivery_bytes`; `dram_accesses` (64-byte bursts), `dram_bytes`. The producer derives chain hops from k/t neighbor traffic; cache arms reuse those chain hops and omit weight hops. |
| `cache_a.csv`, `cache_b.csv` | Counter columns below, for the same case/sample and corresponding cache policy; `total_cycles` supplies each cache arm’s own duration. Cache rows represent system-wide activity, not per-core averages. |
| `record_count.csv` | Required only for Prosperity: `capture`, `layer`, `sample`, `R_p`. Identity must equal `case.json` and `noc/result.json`; `R_p` is the exact generated trace record total, not a digest average. |

Required cache columns: `dram_accesses`, `dram_bytes`, `l1_accesses`, `l1_hits`, `l2_accesses`, `l2_hits`, `l2_pf_issued`, `pf_budget_exhausted`, `pf_dropped_array_hit`, `pf_dropped_matching`, `pf_dropped_no_slot`, `pf_dropped_reserve`, `pf_dropped_targets_full`, `pf_issued`, `total_cycles`.

The caller owns workload selection and simulator-policy configuration. Layer
names do not select formulas; `arch` and counters do. The design supports the
spiking CNN/GEMM counter semantics documented here. The campaign’s kept-layer
rule is applied before simulation by its driver. The model does not discover
or read campaign files. Fixtures demonstrate the complete saved-counter format.

## Count once, price independently

Stage A reads the counter interface and price-independent `hardware.json`.
`performance.py` derives counts; archx executes its callbacks and saves graph
checkpoints with zero-valued metrics from `interfaces/counts.py`. Pending
modules are present: zero means unpriced, not characterized zero energy.
Native `aggregate_event_count` exports activity. Fingerprints cover input
bytes, count code, hardware and vendored archx version/source/binary. No price
or table hash enters Stage A.

Stage B opens only a counted checkpoint and supplied `energy_table.json`,
binds module-operation metrics, and uses native `aggregate_event_metric` for
per-term/total dynamic energy, deduplicated standing leakage power and area.
DDR4, IO, link and router costs use the same graph.
The DDR4-access and IO-per-byte rows retain pinned cacti7-derived prices:
commodity memory is not synthesizable RTL and stays outside the RTL round.
A future datasheet/DRAMPower refinement reprices Stage B only. The on-chip
link likewise stays outside: it uses the physics-based ASAP7-wire0.5CV²
model with zero leakage/area by convention; a wire is not a logic cell.
These are explicit design decisions. Router logic is separate:
`router_5p_64b` is in the RTL round (five ports,64-bit flits, depth2 register
FIFOs/input, round-robin arbitration, mux-tree crossbar, multicast port mask,
500MHz ASAP7 RVT TT0.70V/25C,16 system instances), awaiting the primitive characterization reports.
All48 logic rows use sums over the [24 measured basics](characterization/BASIC_MODULES.md); the13 authored whole tops are unsynthesized references only. See [module specs](characterization/MODULE_MAPPING.md) and
[flow plan](characterization/ASAP7_SYNTHESIS_PLAN.md). The wrapper converts cycles
to seconds at `frequency_MHz` (default 500), standing power to leakage energy,
and forms EDP. Null costs contribute zero plus explicit incomplete reasons.
A new synthesis table reruns only Stage B. Hardware/count changes are rejected
as non-price changes. Each stage has independently hashed, immutable outputs.

The fixed system inventory is 16 nodes, 16 routers and 48 directed links,
regardless of active schedule topology. Spad charges weight plus chain hops;
cache arms charge chain hops only. Zero chain hops legitimately yield zero
cache-arm NoC dynamic energy. Repeated operations share physical inventory.

## Execution

From `zoo/archx`, using an environment prepared as described in [VENDOR.md](../../VENDOR.md):

```bash
export PYTHONPATH="$PWD/src:$PWD/zoo"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RAYON_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_MAX_THREADS=1
export POLARS_MAX_THREADS=1 TBB_NUM_THREADS=1 GOTO_NUM_THREADS=1
export ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONDONTWRITEBYTECODE=1
conda run --no-capture-output -n fig12-archx python -B -m snn_edp.run count --case /full/path/to/sample_00000 --out /full/path/to/counts
conda run --no-capture-output -n fig12-archx python -B -m snn_edp.run price --counts /full/path/to/counts --table "$PWD/zoo/snn_edp/energy_table.json" --out /full/path/to/energy
```

The count driver writes `request.json` with only `case_dir`, then executes:

```text
python -m archx.main -compile <model>/designs/snn/description.py -r <counts>
python -m archx.main -r <counts> -extract <counts>/configurations.csv
python -m archx.main -x <counts>/runs.txt -r <counts>
```

Each generated workload contains only `case_dir`; its name selects the arm.
`runtime/sitecustomize.py` caps the CLI pool to one worker without changing
archx. The Python API is
`archx_aggregate_case(arch, case_folder, energy_table_path, frequency_MHz=500)`.
It returns three rows, including totals, breakdown counts/expressions/energy,
incomplete reasons, table hash, caveats and provenance. Its checkpoints live
outside the case’s receipted tree at
`<layer>/archx_artifacts/<sample>/{counts,energy}/<hash>/`.

Unit-cost recipes, YAMLs and synthesis worklist live in
[characterization/](characterization/README.md); `energy_table.json` is a
pinned product. No characterization subprocess runs during per-case pricing.

## Validation

```bash
conda run --no-capture-output -n fig12-archx python -B -m snn_edp.verify
conda run --no-capture-output -n fig12-archx python -B -m pytest zoo/snn_edp/test_model.py -q -p no:cacheprovider
```

With the execution environment above, `verify` compiles five saved fixture
cases (15 arm rows), comparing counts, expressions, per-term energies and all
totals to the independently retained `reference_t84_results.csv` with the14 retired operation prices removed, at relative error <1e-9 and exact for zeros. `provenance/retired_logic.json` pins the historical costs and explicit physical inventory; validation subtracts each physical leakage/area once, keeps all historical counts unchanged, and does not manufacture a reference from current outputs.
`fixtures/manifest.json` pins the input/reference hashes. This checks model
arithmetic against retained outputs; simulator counters and unit prices are
shared inputs, not independent validations of those sources. Tests also prove
repricing without case reads, simulation or subprocesses and reject tampered
checkpoints and hardware changes. [WORKED_EXAMPLE.md](WORKED_EXAMPLE.md) gives
full paths and actual intermediate/result numbers for one fixture.

## Standalone and externally driven runs

Both entries call the identical `snn_edp.archx_aggregate_case` API, description,
performance callbacks and pricing code.

| Standalone: vendored archx tree | Driven by a simulator campaign |
|---|---|
| Prepare the environment using `../../VENDOR.md`; `cd zoo/snn_edp && ./script.sh --arch spinalflow` | Set `SNN_EDP_MODEL_ROOT` to this directory; call `energy_driver.archx_aggregate_case(arch, external_case_dir, table_path)` from fig12_edp. |
| Defaults to this design’s `fixtures/spinalflow/` and `energy_table.json`; `--arch` selects any of the five bundled examples. | The caller supplies the saved-counter interface above and an explicit table. No campaign implementation is imported by the model. |
| Prints the three full rows and writes `runs/example/spinalflow/rows.json`. | Returns the same three-row schema for the caller to commit and collect. |

The standalone entry compiles, executes and prices on its first invocation.
Identical later invocations reuse checked immutable artifacts. Its API cache
is under `fixtures/archx_artifacts/<arch>/`; these are generated files, not
fixture inputs. Five canonical saved-input sets and the default price table
ship with this design; only the containing archx tree and its dependencies are needed.

Characterization has an upstream FN-CACTI scratch-report side effect in its
package directory; see the [recipe notes](characterization/README.md).
Standalone examples and externally driven counting/pricing do not run CACTI.

## Logic price lineage

No retired library class or characterized logic price is active. Included logic rows await our own500MHz ASAP7 synthesis; default metrics for those rows are null. Explicit prefetch-control exclusions instead carry zero metrics. The optional dummy table uses finite uncharacterized magnitudes and marks retired-library magnitudes explicitly as DUMMY historical provenance. Source CSV paths from that library are retained only under historical provenance, never as active class/source_csv fields. The per-row retirement audit is `provenance/retired_logic.json` at the model root.

Both the standalone script and the campaign API pin `src/archx` relative to this
vendored design. A preloaded backend from another tree is rejected. CLI logs
and verification reports record `archx.__file__`. Neither entry fetches archx
or reads the original checkout. `SNN_EDP_MODEL_ROOT` overrides design location;
its containing archx tree must include the backend alongside `zoo/`.

## Independent count and price commands

From `zoo/archx`, with `PYTHONPATH="$PWD/src:$PWD/zoo"` and the thread/cache
settings above:

```bash
python -B -m snn_edp.run count --case /absolute/counters --out /absolute/count-checkpoint
python -B -m snn_edp.run price --counts /absolute/count-checkpoint --table /absolute/table.json --out /absolute/priced-default
python -B -m snn_edp.run price --counts /absolute/count-checkpoint --table /absolute/new-table.json --out /absolute/priced-new
```

Each command is an independent process. Count reads saved simulator counters,
hardware and performance code, and writes counted graphs, categories and a
price-free manifest. It works with **no energy table present**. Price reads
only that checkpoint and the chosen table: the original counter directory may
be absent. It writes a separate priced result and table fingerprint. Changing
prices reruns Stage B only; Stage A artifacts remain byte-identical. Hardware
or count-expression changes require a new Stage A checkpoint.

## Module and event names

Every hardware operation has a namespace-qualified key and an explicit module
`role` in `hardware.json`. Graph event names include arm, architecture, module
and operation; each operation event owns one physical-module child. Repeated
operations share one module inventory. The [manual check map](docs/manual_check_map.md)
links all98 rows, their events and their count formulas, architecture by architecture.
The retained historical CSV uses the exact aliases in
`provenance/operation_renames.json`; the active runtime accepts only current keys.

## Pricing exclusions and query clock

The nine operations in [pricing_policy.json](characterization/pricing_policy.json)
carry `excluded by decision (prefetch control)` with zero dynamic energy,
leakage and area in both tables. They remain in the counted graphs. They are
intentional exclusions, not missing characterization or DUMMY prices. The
other 48 uncharacterized operations remain pending; 41 operations retain
physical-model prices. L1/L2 fill writes, including prefetch-triggered fills,
remain charged. L1/L2 extra tag probes and cacheB next-line adders are excluded.

All query clock fields are 500 MHz. Separate FN-CACTI runs at 100 and 500 MHz
returned identical metrics for all 12 unique SRAM/cache geometries; frequency
is query metadata, not an optimization constraint. See the
[measured comparison](provenance/cacti_frequency.json). DDR4's separately
specified bus frequency and pinned prices are unchanged.

Pricing exclusions or a synthesis-table update rerun Stage B only. Changing
hardware query metadata changes the Stage-A fingerprint even when its counts
are identical; the clock metadata normalization is documented separately from
the pricing-only exclusion proof in [T95 validation](provenance/t95_validation.json).
