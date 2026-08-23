# 2026-08-23 stagewise verification: LoAS, 16 cores, two deep layers

A gated re-verification of the four-stage performance path on one narrow slice:
arch `loas`, 16 nodes, the two CIN=512 layers. Each stage stops for review
before it runs.

| Stage | Directory | Tool |
|---|---|---|
| 1 | `stage1_mip_solver/` | `mip_solver` via `tracegen.solve_and_cache_schedule` (Gurobi) |
| 2 | `stage2_weight_trace/` | `scripts/generate_weight_traces.py` + the LoAS native bridge |
| 3 | `stage3_nocsim/` | `src/nocsim` |
| 4 | `stage4_wcache/` | `src/wcache/native` |

## Folder contract

Every stage directory holds exactly three things:

```
stageN_<name>/
  run_stageN.py     the only thing that writes here
  inputs/           a copy of everything the stage reads, plus MANIFEST.json
  outputs/          everything the stage produces, and nothing else
```

Two rules make the stages separable:

1. **A stage reads only its own `inputs/`.** Files are copied in, never
   referenced in place, so `inputs/` is a complete record of what the stage
   actually saw. `MANIFEST.json` records the provenance and a short SHA-256 of
   each one.
2. **A stage never writes into another stage's directory.** Stage N+1's
   `inputs/` is populated by `run_stage(N+1).py` at the moment stage N+1 is
   approved, by copying from stage N's `outputs/`. Stage N's own run does not
   prepare it. So the generation of one stage's output is never mixed with the
   input analysis of the next.

The one exception to rule 1 is bulk read-only spike data. Stage 2 reads the
captured `.npy` traces from their durable location rather than copying
gigabytes in; `MANIFEST.json` records the absolute path, the sample indices,
and the array shapes instead.

## Read these first

- `CONCLUSIONS.md` -- what the verification found, and the method that found it.
- `HANDOFF.md` -- the open question about spike density, self-contained for a
  session on another machine.
- `input_trace_audit/` -- per-layer density across all 31 captured layers.

## Status

- Stage 1: **complete** at NoC 2 MiB, node 32 KiB, see `stage1_mip_solver/outputs/RESULTS.md`.
- Stage 2: **complete**, 10 samples, see `stage2_weight_trace/outputs/RESULTS.md`.
- Stages 3 and 4: not started, `inputs/` and `outputs/` deliberately empty.

**Blocked on a data question, not a code defect.** Both completed stages
verified clean, including an exact-integer independent recomputation of the
Stage 2 row counts. But the captured input spike traces run 0.42 to 0.92 density
where an SNN should be near 0.10, and both layers under verification are in that
bad regime. See `CONCLUSIONS.md` section 2 and `HANDOFF.md`.
