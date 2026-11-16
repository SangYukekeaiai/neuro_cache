# Sparseloop validation

LoAS-only comparison against the campaign's multi-node nocsim results. The [execution plan](docs/execution_plan.md) defines the stages; Tier B/C require GATE V approval.

- `inputs/snapshot_manifest.json`: sealed source hashes and copied/derived inputs. There are 12 layers × 23 samples = 276 retained LoAS/spad cases.
- `inputs/traces/`: lossless selected spike arrays; no later access to the protected trace source is required.
- `docs/O2_actual_data.md`: paper-pinned Sparseloop mask format and exact flattening order.
- `docs/saf_mapping.md`: paper-to-model contract; `docs/open_mapping_questions.md` lists decisions needed before configuration finalization.
- `outputs/env_manifest.json`: actual installation/smoke status. A layout mock is not a validation result.
- `repro.md`: commands, environment pins, and preserved installation failures.

Verify the sealed ingest with `conda run -p vendor/envs/tlv python -B src/verify_inputs.py` on Stokes. Install/build with `bash src/install_stokes.sh`, then run the unchanged shipped smoke example with `bash src/run_smoke_stokes.sh`. The environment and backend live under this folder; other zoo task directories are not runtime dependencies.
