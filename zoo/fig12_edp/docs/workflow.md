# Fig. 12 workflow

The energy model is the programmatic archx description in
[`/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp`](../../archx/zoo/snn_edp/README.md). Its complete hardware
mapping and performance settings are in
[CONFIGURATION.md](../../archx/zoo/snn_edp/CONFIGURATION.md); a concrete case with
full paths is in [WORKED_EXAMPLE.md](../../archx/zoo/snn_edp/WORKED_EXAMPLE.md).
A step-by-step breakdown of both models, traced end to end on one real case
with every intermediate number, is in [model_walkthrough.md](model_walkthrough.md).

1. Select spiking-CNN/GEMM layers using [workload_layer_scope.md](workload_layer_scope.md).
2. For an authorized compute run, generate one WCTS stream per case/sample;
   retain its exact record count and digest.
3. Derive analytic counts and next-layer output density into `counts.json`.
4. Run NoC/event simulation into `noc/result.json`, and both fixed cache
   configurations into `cache_a.csv` and `cache_b.csv`.
5. Stage A: archx compiles `designs/snn/description.py`, executes its native performance
   models on those saved files, and saves counted event-graph checkpoints.
   Counts include pending modules and have no dependency on prices.
6. Stage B: bind a versioned metric table to the saved graphs and use archx
   metric aggregation for energy, leakage inventory and area. Convert cycles
   to time and form EDP. Null characterization is zero plus explicit incomplete
   reasons. A synthesis update reruns this stage only.
7. Commit the three durable result rows before deleting the transient stream.
   Store Stage A/B artifacts outside receipted sample directories.
8. Collect kept cases and plot complete groups; missing, OOM and infeasible
   layers produce hatched markers, never partial whole-model bars. Whole-model
   EDP is `(sum energy) * (sum latency)`; the sum of layer EDPs is a separate statistic.

The [campaign driver](../demo/all_bench/README.md) starts from the canonical
kept scope with the archx model wired in. Model validation uses a pinned 15-row
reference and five minimal saved-input fixtures, independently of campaign
outputs. The purge manifest and archives are linked by
`../t88_deletion_manifest.json`. No new simulator run is part of an energy-table
update or a model validation command.

The thin caller is `../energy_driver.py`. It resolves `SNN_EDP_MODEL_ROOT`
(or the in-repo `zoo/archx/zoo/snn_edp` design), then passes the completed counter
directory and table path to the zoo API. The authoritative saved-counter
interface is [the zoo README](../../archx/zoo/snn_edp/README.md#saved-counter-interface).
Cache simulator configs are in `../configs/`; model hardware, unit table and
characterization recipes belong to the zoo design. Model source fingerprints
are namespaced separately from this repository’s driver sources.

Backend setup and import pinning are described in
[the vendor note](../../archx/VENDOR.md). Stage A (`snn_edp.run count`) needs no
energy table. Stage B (`snn_edp.run price`) can run in a later process with the
counter directory absent, binding a new table to the unchanged checkpoint.
The [two commands](../../archx/zoo/snn_edp/README.md#independent-count-and-price-commands)
are the supported synthesis-update path; no performance simulation is repeated.

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
