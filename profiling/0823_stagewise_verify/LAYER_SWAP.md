# Layer swap: executed on Delta, 2026-08-23

The deliverable `LAYER_SWAP_PLAN.md` asked for. Stages 1 and 2 were re-run over
four layers on NCSA Delta, host `dt-login03`, repo
`/u/yyu9/projects/neuro_cache`, branch `wcache-rebuild-phase-a`.

## What was swapped

The 0823 verification ran on two layers that the survey later placed above every
published spike-density profile. Rather than replace them, both regimes are now
carried:

| tag | layer | shape | density | role |
|---|---|---|---|---|
| **V8** | vgg16 `layer_08_features_27` | KH3 KW3 CIN512 COUT512 HO4 WO4 T4 | 0.207 | representative, added |
| **R9** | resnet19 `layer_09_layer2_0_conv2` | KH3 KW3 CIN256 COUT128 HO8 WO8 T4 | 0.178 | representative, added |
| **V9** | vgg16 `layer_09_features_30` | KH3 KW3 CIN512 COUT512 HO4 WO4 T4 | 0.578 | stress case, kept |
| **R16** | resnet19 `layer_16_layer3_0_conv2` | KH3 KW3 CIN512 COUT256 HO4 WO4 T4 | 0.449 | stress case, kept |

Densities are the median over the five samples, from
`stage2_weight_trace/outputs/stage2_report.json`.

Keeping V9 and R16 costs nothing (their artifacts already existed and were not
regenerated) and gives Stage 4 two density points to read against, which
`HANDOFF-ANSWER.md` section 5 recommends. R16's 0.449 is close to LoAS Table
II's own R-L19 figure of 0.421, so it is defensible as the paper's own deep-layer
regime rather than as an accident.

Nothing was deleted. `profiling/0820_phaseD_spad_vs_cache/grids/cache16.json`
still names V9 and R16, and its 2160 committed result rows still stand on them;
that grid is deliberately left alone until Stage 4 has been verified.

## Commands, in order

```
conda run -n base --no-capture-output python stage1_mip_solver/run_stage1.py
conda run -n base --no-capture-output python stage2_weight_trace/run_stage2.py
conda run -n base --no-capture-output python stage2_weight_trace/verify_reconstruction.py
conda run -n base --no-capture-output python stage2_weight_trace/wcts_excerpt.py <dump>.wcts
```

All from `profiling/0823_stagewise_verify/`. `run_stage1.py` and `run_stage2.py`
have no CLI; the layer list is the `LAYERS` / `COMBOS` constant near the top of
each, and both were edited to carry the four layers above. gurobipy 13.0.2,
license `/u/yyu9/gurobi.lic`. Login node, no Slurm, matching how Stage 1 ran the
first time; wall time is well inside Delta's 30-minute login CPU cap.

Wall time: Stage 1 1m36s for 108 solves. Stage 2 9m15s. Reconstruction check
1m35s. WCTS decodes a few seconds each.

## Stage 1 outcome

`stage1_mip_solver/outputs/RESULTS.md` has the full write-up. The three claims
worth repeating:

**V8 and V9 solve to the same schedule.** The two JSON files differ in exactly
one field, `layer_name`. This was predicted by the scout in `LAYER_SWAP_PLAN.md`
and is now measured:

```
$ diff schedules/pe16/loas/vgg16_T4_all/layer_0{8_features_27,9_features_30}.json
4c4
<  "layer_name": "layer_08_features_27",
---
>  "layer_name": "layer_09_features_30",
```

A layer's captured tensor is its input, so `archmodels/trace.py:105-143` takes
CIN from that tensor and COUT from the next layer's CIN. Both layers hold
`[4, 5, 512, 4, 4]` with a next-layer CIN of 512. The vgg16 swap therefore costs
Stage 1 nothing and changes only which spikes Stage 2 replays.

**R9 is a genuinely new solve** and it lands in the same family: `gb_oooo`,
NodeLevel COUTx4 spatial with KH/KW/CIN/T full, NoCLevel COUTx16 spatial. Its
`dram_num_steps` is 2 against V9's 16 and R16's 32, and its NoC temporal
permutation is five factors deep (`WOx2 -> HOx4 -> WOx2 -> HOx2 -> WOx2`)
because its 8x8 output plane has to be walked somewhere.

**The two retained layers re-solved byte-identically** to the first run, 18
hours earlier, and all 26 shared rows of `mode_sweep.json` match field for
field. Run-to-run determinism holds.

Two findings generalized now that there are four shapes:

- The **NoC feasibility floor is the NodeLevel weight footprint** `KH*KW*CIN*4`
  scaled by 32/30. R9 at CIN 256 is feasible down to 16 KiB where the CIN 512
  layers stop at 32 KiB, exactly as that rule predicts.
- The **useful floor is `KH*KW*CIN*64`** scaled by 32/30, below which the
  solver stops spreading COUT across the 16 cores and starts spreading HO or
  WO instead. 307 KiB for CIN 512, 154 KiB for R9. The canonical 2 MiB clears
  both.

R9 also worsens the known degeneracy: its objective is bit-identical across
five NoC sizes from 4 MiB to 256 KiB while `dram_num_steps` goes 2, 2, 64, 64,
128, a 64x swing decided by a tie-break rather than by the model. Comparisons
across NoC sizes remain unsafe to read as a size effect. Comparisons at a fixed
size are reproducible.

## Stage 2 outcome

`stage2_weight_trace/outputs/RESULTS.md` has the full write-up. Five samples per
layer, CIFAR-10 images 2697, 3078, 5110, 6367, 8502, the same five everywhere.

Per-sample input density:

| layer | s0 | s1 | s2 | s3 | s4 | median | range/median |
|---|---|---|---|---|---|---|---|
| V8 | 0.2073 | 0.2064 | 0.1924 | 0.1869 | 0.2251 | 0.2064 | 0.185 |
| R9 | 0.1949 | 0.1638 | 0.1606 | 0.1776 | 0.2083 | 0.1776 | 0.269 |
| V9 | 0.5783 | 0.5880 | 0.5902 | 0.5683 | 0.5781 | 0.5783 | 0.038 |
| R16 | 0.4214 | 0.4619 | 0.4699 | 0.4144 | 0.4490 | 0.4490 | 0.124 |

The representative layers emit roughly half the rows of the stress layers: V8 is
0.48x V9 on an identical schedule, R9 is 0.68x R16.

**The reconstruction check now exists as code.** `verify_reconstruction.py` was
written this run, since the first run described the check in prose but never
committed it. It reimplements `LoASGen.h:66-119` in NumPy from the raw `.npy`
and the schedule alone, importing neither the generator nor the native bridge,
and derives the tile-instances-per-pixel multiplier from the schedule as
`COUT / node_spatial_COUT`. Result on all 20 samples:

```
all row and mac_cycles counts reproduce exactly
```

It also verifies the COUT partition per layer: 16 cores, disjoint contiguous
blocks, every channel covered exactly once, 32 channels per core for the vgg16
layers, 8 for R9, 16 for R16. The cores never contend for the same weight
address, which is the fact Stage 4 turns on.

All eight WCTS dumps validate (trailer magic, burst recount, byte count), and
each full stream's `total_bursts` equals the corresponding `.json.gz`
`total_rows`, so two independent writers of the same reconstruction agree.

## One thing to plan for

**Five samples resolve R9 poorly.** Its per-sample emitted-row count spans
1,070,560 to 1,382,144, a range of 0.247 of the median, against 0.028 for R16. A
dense layer is dense on every image; a sparse layer is sparse by an
image-dependent amount, and the representative layers are the sparse ones.

This does not by itself trigger the plan's "raise n if the range exceeds 5% of
the median" rule, which governs the per-sample *ratio* in a paired A-vs-B
comparison. A paired ratio is much tighter than raw workload volume because both
arms replay the same image. But it is a warning that n = 5 has less headroom on
R9 than the earlier two layers implied, and the ratio spread should be checked
explicitly at Stage 4 rather than assumed.

## What remains

- **Stage 3, nocsim.** Not started. Its input is a subset of the 20
  `sample_*.json.gz` under
  `stage2_weight_trace/outputs/weight_traces/loas/noc2MiB_node32kb/`. Which
  subset is the open question: all four layers, or the representative pair only.
- **Stage 4, wcache.** Not started, and still blocked on the same gap: the
  engine has no event logging, so the five requested event traces need an
  emitter written first.
- **Campaign re-runs.** `grids/cache16.json` and its 2160 rows still stand on V9
  and R16 alone. Whether to extend that grid to V8 and R9 is a decision for
  after Stage 4 is verified, not before.
- **The snapshot deadline stands.** `capture/` and the LoAS checkpoints live in
  `/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/`
  and that snapshot expires around 2026-09-10.
