# Stokes durable campaign outputs

23 fully committed samples, 38,571 case/arm result rows. `rows/sample_XXX/` contains the NG45-priced results, whole-model CSV, commit manifest, and per-case accounting for each sample. The source is Stokes `~/snn_edp_stokes_20261114/full500/rows/`.

`VERIFICATION.json` records local verification against `source_manifest.json`, the original per-sample commit manifests, and `SOURCE_CONTROL_SHA256`. All 344 transferred files match their source SHA256; all 207 commit-pinned artifacts match; there are zero missing files or mismatches.

`accounting/` contains the controller state, boundary, resource controls, recovery/quarantine records and cancellation accounting. `ledger_at_fetch.json` is a copy of the manager-owned local ledger. `quiescence_verified.json` confirms the controller is absent, its lock is free and the Stokes queue is empty.

Uncommitted/quarantined samples 001, 005, 024, 026 and 027 retain their work and scratch on Stokes; sample 024 also retains partial pricing. They are not included as complete samples here. No checkpoints were deleted by the stop/fetch operation. Resume requires reconciling cancelled job receipts; this fetch does not alter them.

The read-only milestone watcher remains running. Delta and DeltaAI jobs are untouched.
