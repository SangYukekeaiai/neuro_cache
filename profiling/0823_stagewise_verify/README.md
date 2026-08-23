# 2026-08-23 stagewise verification: LoAS, 16 cores, four layers

A gated re-verification of the four-stage performance path on one narrow slice:
arch `loas`, 16 nodes, four layers in two density regimes. Each stage stops for
review before it runs.

| tag | layer | density | role |
|---|---|---|---|
| V8 | vgg16 `layer_08_features_27` | 0.207 | representative |
| R9 | resnet19 `layer_09_layer2_0_conv2` | 0.178 | representative |
| V9 | vgg16 `layer_09_features_30` | 0.578 | stress case |
| R16 | resnet19 `layer_16_layer3_0_conv2` | 0.449 | stress case |

The run started on V9 and R16 alone. A spike-density survey then placed both
above every published profile, so the two representative layers were added and
the dense pair kept and labelled. See `LAYER_SWAP.md`.

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
- `LAYER_SWAP.md` -- what the layer swap changed, and what it measured.
- `HANDOFF-ANSWER.md` -- the survey that settled the density question, cited.
- `HANDOFF.md` -- the question as it was posed, self-contained for a session on
  another machine.
- `input_trace_audit/` -- per-layer density across all 31 captured layers.

## Status

- Stage 1: **complete**, four layers at NoC 2 MiB and node 32 KiB, see
  `stage1_mip_solver/outputs/RESULTS.md`.
- Stage 2: **complete**, four layers x 5 samples, see
  `stage2_weight_trace/outputs/RESULTS.md`.
- Stages 3 and 4: not started, `inputs/` and `outputs/` deliberately empty.

**The data question is settled and the traces are kept.** The survey in
`HANDOFF-ANSWER.md` showed the capture reproduces LoAS's own released profiling
output to within 0.03 to 3.3 points, and that the "SNN density should be near
0.10" premise was a citation-chain figure LoAS's own Table II contradicts: it
reports ResNet19 at 0.314 density and its deepest layer at 0.421. Deep-layer
densities of 0.6 to 0.92 remain outside every published profile, so the dense
layers are carried as a stated stress case rather than as representative work.

**Stage 4 is still blocked on a code gap**, not on data: `src/wcache`'s engine
has no event logging, so the five requested event traces need an emitter first.
