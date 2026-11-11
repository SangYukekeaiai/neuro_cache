# WT500 S2: mode-sweeping schedule solve: run count and execution plan

Scope: step S2 of `2026-11-11-wt500-stokes-generation-plan.md`. Directive:
every schedule must be MODE-SWEEPING (never BASE), each solver run capped at
30 seconds, all modes swept. Status: plan, awaiting user review before any
dispatch.

## 1. How many scheduler runs are about to run

Counted today against the FINAL configs (arch.yaml + the five finalized
mapspaces) with a fresh `gen_inputs.py --dry-run`:

| quantity | value | source |
|---|---|---|
| captures | 8 | dry-run inventory |
| valid (arch, layer) pairs | **755** | 151 replayable layers x 5 archs |
| excluded pairs | 30 | 6 stride-2 layers x 5 archs (loader policy; matches directive "skip stride-2") |
| traffic modes per pair | **13** | `TrafficMode` enum: base, psum_dram_otok, psum_gb_otok, vmem_dram_xxxt, vmem_gb_xxxt, dram_oooo, dram_ooot, dram_oook, both_dram_ootk, gb_oooo, gb_ooot, gb_oook, gb_ootk |
| **Gurobi solves** | **755 x 13 = 9,815** | one `enumerate` call per pair sweeps all 13 |

Note the sweep INCLUDES base as one of the 13 candidates; the directive is
satisfied because the best mode is picked by comparison score across all 13,
not forced to base.

Known-infeasible subset: prosperity on A08 layers L1-L6 (6 pairs). Pilot run
confirms all 13 modes return INFEASIBLE for these (modes only add
constraints), so the sweep ends with best_mode=null; the campaign records
them INFEASIBLE exactly as before. Expected final tally: 749 scheduled pairs,
6 infeasible, 30 excluded.

## 2. The 30-second cap

`lays.scheduler enumerate --time-limit 30` sets `model.Params.TimeLimit = 30`
**per mode** (`solve.py:76`), i.e. per Gurobi solve: the cap the directive
asks for. Semantics when the cap fires: Gurobi returns status TIME_LIMIT with
the best incumbent found; a mode with an incumbent still enters the
comparison, one without drops out. Per-mode `status` is recorded in the
enumeration JSON so capped runs are auditable.

## 3. Measured cost (pilots on this login node, gurobi env, license OK)

| pilot | result | wall time |
|---|---|---|
| loas x A02 layer_01 (typical small), 13 modes | best gb_oooo | 8.0 s |
| prosperity x A08 layer_01 (hard, infeasible), 13 modes | all INFEASIBLE | 6.4 s |

~3 s of each is conda/python startup. No pilot mode came near the 30 s cap.

Projection: 755 pairs x ~8 s = **~1.7 h serial**; absolute worst case if
every mode of every pair hit the cap: 755 x 13 x 30 s = 82 h (not expected -
treat as the ceiling that makes a runaway impossible). With 4 parallel
workers: ~25-30 min. In-process batching (one python looping pairs instead of
one process per pair) would cut the ~3 s/pair startup; optional.

## 4. Required code change before running

`gen_inputs.py` solves via `lays.scheduler solve` (BASE only). Change its
solve stage to the sweeping entry point:

1. `_solver_command`: subcommand `solve` -> `enumerate`, add
   `--time-limit 30`.
2. Result handling: enumeration JSON carries `best_mode` / `best_strategy` /
   `candidates` instead of a flat solve result. Exit code 3 with
   `best_mode: null` = INFEASIBLE pair (record it, do not treat as
   EXEC_FAILED: pilot 2 shows conda surfaces rc 3 as "failed").
3. Artifact stamping: schedule artifact gets `mode: <best_mode>` plus the
   per-mode status table; `_artifact_matches` must reject `mode: base`
   artifacts from the old cache (sweep provenance required).
4. Output root: solve into a fresh `outputs/` (the existing cache is BASE
   provenance, not authoritative: do not reuse; `--force` or clean dir).

## 5. Execution steps (after user approves)

1. Dispatch the gen_inputs.py change (sec. 4) to impl; archie reviews.
2. Smoke: `--smoke` (5 pairs, one per arch) + spot-check that each artifact
   stamps a non-base-forced best_mode and the 13-mode table.
3. Full run on THIS login node (gurobi licensed): `setsid` background, log to
   file; progress = `[n/755]` lines; checkpoint counts per S6.
4. Close-out: manifest tally 749/6/30, per-arch best_mode histogram, and the
   schedule digest feeds S3 (run-order + record counts, incl. prosperity's 47
   3x3 layers).
