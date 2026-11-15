# Standalone SNN energy design

The model lives at `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/`. The name describes the hardware and energy-delay analysis without naming the figure campaign. The full archx backend is vendored in `zoo/archx/`, pinned at 49449c4 (version 0.1.1); no separate checkout or archx package fetch is needed.

## Ownership and execution

1. `neuro_cache_wcache/zoo/fig12_edp/` selects the CNN/GEMM workload using `docs/workload_layer_scope.md`, runs the existing generators and simulators, and writes a case directory containing `case.json`, `counts.json`, `noc/result.json`, `cache_a.csv`, `cache_b.csv`, and Prosperity's `record_count.csv`.
2. `archx/zoo/snn_edp/README.md` defines that saved-counter interface once. The energy design has no imports from, or filesystem dependency on, the campaign repository. Campaign layer-name selection belongs in the caller; the design validates architecture, counter identities and numeric inputs.
3. The model uses the vendored backend. `designs/snn/description.py` builds the programmatic AGraph. Stage A uses the actual archx compile/extract/execute commands and saves counted graphs with zero metrics. Stage B binds the pinned unit table and aggregates native archx metrics. Every invocation disables the performance cache and caps thread pools.
4. Hardware specifications, `energy_table.json`, characterization recipes, YAMLs, synthesis worklist, model fixtures, validation workspace and model documentation move with the zoo design. Recipes live in `characterization/`; the table is at the design root and remains overridable by an explicit path. This makes the model a single transferable archx tree. Production cache simulator JSONs remain with the performance driver under `fig12_edp/configs/`.
5. A small `fig12_edp/energy_driver.py` locates the zoo design (explicit `SNN_EDP_MODEL_ROOT`, otherwise the vendored zoo/archx tree), imports its public API, and exposes model/table paths for provenance. Scientific hashes name model files separately from campaign sources. Parked remote-runner paths are adjusted for the move, without undertaking its unrelated deferred repairs.
6. Final case results, collection, CSVs and plots remain in fig12_edp. Count and pricing checkpoints remain outside receipted sample folders, preserving the existing layout and independent Stage-A/Stage-B fingerprints. A new table reprices checkpoints without touching simulator inputs or rerunning Stage A.

## Move and validation

Before relocation, archive the model, recipes and changed callers, and record the pinned table, reference CSV, cache configs and existing archx tree hashes. No prior archived data is restored or deleted. Model-specific tests move; receipt and workload-selection tests stay with orchestration.

Run the five saved fixture cases (three arms each) from the new zoo location, comparing every count, expression, energy term and total with `reference_t84_results.csv` at relative error below 1e-9 (expected zeros exact). Exercise repricing without access to case inputs, run model/characterization and affected caller tests, and confirm imports resolve to the vendored backend. No campaign compute is launched.

Update the model's README, WORKED_EXAMPLE and CONFIGURATION with its self-contained paths. Keep `fig12_edp/docs/workflow.md` and `model_walkthrough.md` as caller documentation linking to the model's authoritative interface. Archive pointers stay with their originating campaign. The single live design is `zoo/archx/zoo/snn_edp/`; the original checkout has no second design copy.
