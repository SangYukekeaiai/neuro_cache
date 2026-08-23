# Stage 1 results: MIP solver

First run 2026-08-23 over two layers. **Re-run 2026-08-23 over four**, after the
spike-density survey (`../HANDOFF-ANSWER.md`) added a representative layer per
workload beside the two dense ones. `run_stage1.py`, `conda run -n base`,
gurobipy 13.0.2, 1m36s wall for 108 solves. Raw log `stage1.log`; records in
`solve_rows.json`, `num_pes_invariance.json`, `mode_sweep.json`,
`noc_size_sweep.json`. Schedules are written with `indent=1`
(`src/tracegen.py:130`), so they read as normal JSON.

## The four layers

| tag | layer | shape KH,KW,CIN,COUT,HO,WO,T | input density | role |
|---|---|---|---|---|
| **V8** | vgg16 `layer_08_features_27` | 3,3,512,512,4,4,4 | 0.1995 | representative |
| **R9** | resnet19 `layer_09_layer2_0_conv2` | 3,3,256,128,8,8,4 | 0.1840 | representative |
| **V9** | vgg16 `layer_09_features_30` | 3,3,512,512,4,4,4 | 0.5781 | stress case |
| **R16** | resnet19 `layer_16_layer3_0_conv2` | 3,3,512,256,4,4,4 | 0.4239 | stress case |

Densities are from `../input_trace_audit/density_audit.txt`. V8 and R9 sit
inside the 0.15 to 0.31 band the literature reports for CIFAR CNNs at T=4; V9
and R16 sit above it, R16 at almost exactly LoAS Table II's own R-L19 figure of
0.421. Both regimes are kept so Stage 4 can be read against density.

## Configuration

Canonical arch: `inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml`. Both
capacity levels are 30:1:1 by bytes:

```
NodeLevel   instances 16, num_pes 16
            local_buffer  weight   30720 / psum   1024 / vmem   1024  =  32 KiB
NoCLevel    instances 1
            entries       weight 1966080 / psum  65536 / vmem  65536  =   2 MiB
```

The YAML field named `entries` is bytes, not element counts:
`utilization.py:93` seeds the capacity expression with
`log2(bytes_by_var[v])`, `_bytes_by_var` is `bitwidth/8`, and
`utilization.py:185` compares byte totals.

`num_pes = 2` is not swept. It is rejected by `dataflow.py:116` before the
model is built, since the LoAS dataflow's NodeLevel spatial product is 4.

---

## The four schedules

| | V8 | R9 | V9 | R16 |
|---|---|---|---|---|
| KH,KW,CIN,COUT,HO,WO,T | 3,3,512,512,4,4,4 | 3,3,256,128,8,8,4 | 3,3,512,512,4,4,4 | 3,3,512,256,4,4,4 |
| NodeLevel temporal | KH3, KW3, CIN512, T4 | KH3, KW3, CIN256, T4 | KH3, KW3, CIN512, T4 | KH3, KW3, CIN512, T4 |
| NodeLevel spatial | COUTx4 | COUTx4 | COUTx4 | COUTx4 |
| NoCLevel temporal | WOx4 -> HOx2 | WOx2 -> HOx4 -> WOx2 -> HOx2 -> WOx2 | WOx4 -> HOx2 | HOx2 |
| NoCLevel spatial | COUTx16 | COUTx16 | COUTx16 | COUTx16 |
| DRAM temporal | COUTx8 -> HOx2 | COUTx2 | COUTx8 -> HOx2 | COUTx4 -> WOx2 -> HOx2 -> WOx2 |
| `dram_num_steps` | 16 | 2 | 16 | 32 |
| noc steps | 8 | 64 | 8 | 2 |
| tiles = dram x noc | 128 | 128 | 128 | 64 |
| mode | gb_oooo | gb_oooo | gb_oooo | gb_oooo |
| objective | 160.2873338750062 | 150.7638620694067 | 160.2873338750062 | 152.35586206940675 |
| delay | 2359296 | 1179648 | 2359296 | 1179648 |

**V8 and V9 produce the same schedule.** The two files differ in exactly one
field:

```
$ diff schedules/pe16/loas/vgg16_T4_all/layer_0{8_features_27,9_features_30}.json
4c4
<  "layer_name": "layer_08_features_27",
---
>  "layer_name": "layer_09_features_30",
```

That is the expected result, not a coincidence. A layer's captured tensor is its
*input*, so `archmodels/trace.py:105-143` derives CIN from that tensor and COUT
from the next layer's CIN. `features_27` and `features_30` both hold
`[4, 5, 512, 4, 4]` with a next-layer CIN of 512, so the derived workload is
byte-identical and the solve is deterministic. The swap therefore costs Stage 1
nothing and changes only which spikes Stage 2 replays.

NodeLevel is fully forced by the dataflow and identical in shape across all
four: `full` on KH/KW/CIN/T via `node_capacity.py:132-136`, COUT pinned
spatially by `node_level.py:62`, HO/WO barred by `node_capacity.py:124-128`.
Because HO and WO are barred, node occupancy depends only on KH, KW, CIN, the
COUT spatial factor and T, so psum and vmem are the same for every layer:

```
                   weight                        psum            vmem
V8, V9, R16   3*3*512*4 = 18432 B of 30720  4*4*2 = 32 B    4*4 = 16 B
R9            3*3*256*4 =  9216 B of 30720  4*4*2 = 32 B    4*4 = 16 B
```

Weight occupancy is 60% of the node budget at CIN 512 and 30% at CIN 256. psum
and vmem never exceed 3%.

NoCLevel occupancy at 2 MiB:

| | weight | psum | vmem |
|---|---|---|---|
| V8 | 294912 / 1966080 | 4096 / 65536 | 2048 / 65536 |
| R9 | 147456 / 1966080 | 32768 / 65536 | 16384 / 65536 |
| V9 | 294912 / 1966080 | 4096 / 65536 | 2048 / 65536 |
| R16 | 294912 / 1966080 | 1024 / 65536 | 512 / 65536 |

Nothing binds. R9 is the tightest at 50% of the psum budget, from its larger
8x8 output plane.

---

## A. num_pes does not move the schedule

| num_pes | Verdict |
|---|---|
| 4, 64, 256 | OPTIMAL, full schedule JSON identical to num_pes 16 |
| 16 | OPTIMAL (canonical) |

Twelve comparisons, twelve matches (`num_pes_invariance.json`). `num_pes`
reaches the model only as an upper bound (`spatial.py:78`, `dataflow.py:116`),
while `configs/dataflow/loas.yaml`'s `COUT: {spatial: 4}` becomes a linear
equality at `node_level.py:62` pinning NodeLevel COUT spatial to exactly 4. The
ceiling never binds.

---

## B. All 13 TrafficModes are enumerated; BASE never wins

`solve_best_schedule` iterates `for mode in TrafficMode` (`solve.py:300`).
`mode_sweep.json` records every mode's outcome rather than only the winner's:
52 rows, 4 layers x 13 modes.

| Mode | V8 | R9 | V9 | R16 |
|---|---|---|---|---|
| `base` | 7.39544e+07 | 2.28214e+07 | 7.39544e+07 | 3.22733e+07 |
| `psum_dram_otok`, `psum_gb_otok` | INFEASIBLE | INFEASIBLE | INFEASIBLE | INFEASIBLE |
| `vmem_dram_xxxt`, `vmem_gb_xxxt` | INFEASIBLE | INFEASIBLE | INFEASIBLE | INFEASIBLE |
| `dram_oooo`, `dram_ooot`, `dram_oook` | INFEASIBLE | INFEASIBLE | INFEASIBLE | INFEASIBLE |
| `both_dram_ootk` | INFEASIBLE | INFEASIBLE | INFEASIBLE | INFEASIBLE |
| **`gb_oooo`** | **6.13718e+07 WINS** | **1.65347e+07 WINS** | **6.13718e+07 WINS** | **3.07005e+07 WINS** |
| `gb_ooot`, `gb_oook`, `gb_ootk` | INFEASIBLE | INFEASIBLE | INFEASIBLE | INFEASIBLE |

Scores are `_mode_score` (`solve.py:272`); lower wins. 2 of 13 feasible for
every layer, and `gb_oooo` beats `base` every time, so the shipped schedule is
not the unconstrained BASE model.

The 11 infeasible modes all constrain the ordering of K (COUT) or T in the DRAM
or GB permutation regions. The LoAS dataflow empties those regions: KH/KW/CIN/T
are forced fully resident at NodeLevel and HO/WO are barred from it, so T is not
in the permutation regions at all and every pattern except `oooo` has no slot to
satisfy. That reasoning is shape-independent, and R9's different shape does not
change the outcome.

---

## C. NoCLevel global-buffer size

Ten totals swept at 30:1:1, num_pes 16, node buffer 32 KiB fixed. Reference for
the "same" column in the log is the canonical 2 MiB. `noc_size_sweep.json` has
the full records. V8 reproduces V9 exactly, so only one vgg16 table is given.

### V8 and V9, vgg16 (CIN 512, COUT 512)

| NoC total | weight cap | weight used | NoC spatial | `dram_num_steps` | objective |
|---|---|---|---|---|---|
| **2 MiB** | 1966080 | 294912 | COUTx16 | **16** | 160.2873338750062 |
| 4 MiB | 3932160 | 294912 | COUTx16 | 16 | 160.2873338750062 |
| 1 MiB | 983040 | 294912 | COUTx16 | 64 | 160.2873338750062 |
| 512 KiB | 491520 | 294912 | COUTx16 | 128 | 160.2873338750062 |
| 256 KiB | 245760 | 147456 | HOx2 -> COUTx8 | 32 | 160.2973338750062 |
| 128 KiB | 122880 | 73728 | WOx2 -> COUTx4 -> HOx2 | 128 | 160.3073338750062 |
| 64 KiB | 61440 | 36864 | WOx2 -> HOx4 -> COUTx2 | 64 | 160.3173338750062 |
| 32 KiB | 30720 | 18432 | WOx4 -> HOx4 | 128 | 160.3273338750062 |
| 16 KiB | 15360 | - | INFEASIBLE | | |
| 8 KiB | 7680 | - | INFEASIBLE | | |

### R9, resnet19 (CIN 256, COUT 128)

| NoC total | weight cap | weight used | NoC spatial | `dram_num_steps` | objective |
|---|---|---|---|---|---|
| **2 MiB** | 1966080 | 147456 | COUTx16 | **2** | 150.7638620694067 |
| 4 MiB | 3932160 | 147456 | COUTx16 | 2 | 150.7638620694067 |
| 1 MiB | 983040 | 147456 | COUTx16 | 64 | 150.7638620694067 |
| 512 KiB | 491520 | 147456 | COUTx16 | 64 | 150.7638620694067 |
| 256 KiB | 245760 | 147456 | COUTx16 | 128 | 150.7638620694067 |
| 128 KiB | 122880 | 73728 | COUTx8 -> HOx2 | 64 | 150.7738620694068 |
| 64 KiB | 61440 | 36864 | HOx4 -> COUTx4 | 128 | 150.7838620694068 |
| 32 KiB | 30720 | 18432 | WOx4 -> HOx2 -> COUTx2 | 64 | 150.7938620694067 |
| 16 KiB | 15360 | 9216 | WOx8 -> HOx2 | 128 | 150.8038620694067 |
| 8 KiB | 7680 | - | INFEASIBLE | | |

### R16, resnet19 (CIN 512, COUT 256)

| NoC total | weight cap | weight used | NoC spatial | `dram_num_steps` | objective |
|---|---|---|---|---|---|
| **2 MiB** | 1966080 | 294912 | COUTx16 | **32** | 152.35586206940675 |
| 4 MiB | 3932160 | 294912 | COUTx16 | 32 | 152.35586206940675 |
| 1 MiB | 983040 | 294912 | COUTx16 | 64 | 152.35586206940675 |
| 512 KiB | 491520 | 294912 | COUTx16 | 32 | 152.35586206940675 |
| 256 KiB | 245760 | 147456 | WOx2 -> COUTx8 | 32 | 152.36586206940677 |
| 128 KiB | 122880 | 73728 | WOx2 -> COUTx4 -> HOx2 | 64 | 152.37586206940676 |
| 64 KiB | 61440 | 36864 | HOx4 -> COUTx2 -> WOx2 | 64 | 152.38586206940676 |
| 32 KiB | 30720 | 18432 | WOx4 -> HOx4 | 64 | 152.39586206940675 |
| 16 KiB | 15360 | - | INFEASIBLE | | |
| 8 KiB | 7680 | - | INFEASIBLE | | |

Delay never moves with NoC size: 2359296 for the vgg16 layers, 1179648 for both
resnet19 layers, at every feasible size.

### Two different minimums, and both scale with CIN

The four layers now give the rule rather than one instance of it.

**Feasibility floor = the NodeLevel weight footprint.** The NoC capacity
expression covers levels `[0, dram_start)`, which includes level 0, so the NoC
weight budget can never be smaller than what one node holds, `KH*KW*CIN*4`
bytes, scaled by 32/30 for the 30:1:1 split.

| layer | node weight | floor = x32/30 | smallest feasible in the sweep |
|---|---|---|---|
| V8, V9, R16 (CIN 512) | 18432 B | 19661 B, 19.2 KiB | 32 KiB |
| R9 (CIN 256) | 9216 B | 9830 B, 9.6 KiB | 16 KiB |

R9 is feasible one step further down precisely because its CIN is half.

**Useful floor = holding all 16 cores' COUT slices, `KH*KW*CIN*64` bytes.**
Below it the solver keeps all 16 cores busy but spreads a different dimension
across them.

| layer | COUTx16 weight | floor = x32/30 | last size holding COUTx16 |
|---|---|---|---|
| V8, V9, R16 (CIN 512) | 294912 B | 314573 B, 307.2 KiB | 512 KiB |
| R9 (CIN 256) | 147456 B | 157286 B, 153.6 KiB | 256 KiB |

The canonical 2 MiB is 6.7x clear for the CIN 512 layers and 13.3x clear for R9.

### Below the useful floor the spatial mapping changes character

The spatial product stays 16 at every feasible size: all 16 cores are always
used. What changes is **which dimension is spread across them**. Weight depends
only on KH/KW/CIN/COUT (`constants.py:83-91`), so mapping HO or WO spatially
replicates the same weight tile across nodes and shrinks the NoC footprint. For
the CIN 512 layers:

```
COUTx16  -> 294912 B      512 KiB and up
COUTx8   -> 147456 B      256 KiB
COUTx4   ->  73728 B      128 KiB
COUTx2   ->  36864 B       64 KiB
COUTx1   ->  18432 B       32 KiB
```

For a weight-cache study this is decisive. Under COUTx16 the 16 cores fetch 16
different weight slices; under WOx4 -> HOx4 they fetch the same slice, perfectly
shared. Opposite cache workloads. It also trips a known downstream hazard: the
campaign grids burst along COUT, and `PROGRESS.md` U29 records that a non-COUT
`burst_dim` "decodes silently wrong rather than being refused". Any NoC at or
below 256 KiB puts a non-COUT dimension in the spatial split for three of the
four layers. 2 MiB is comfortably clear for all four.

---

## The objective does not pin down the schedule

At 4 MiB, 2 MiB, 1 MiB and 512 KiB the vgg16 objective is bit-identical at
`160.2873338750062` and the delay is identical, yet `dram_num_steps` is
16, 16, 64, 128. R9 is worse: identical objective `150.7638620694067` across
five sizes from 4 MiB down to 256 KiB, with `dram_num_steps` 2, 2, 64, 64, 128,
a 64x swing. None of those capacities binds (147456 used against 3932160 down
to 245760). The models differ only in a non-binding right-hand side, so the LP
relaxation differs, Gurobi's search path differs, and a different member of the
same optimal face comes back.

2 MiB and 4 MiB are the closest pair, and for vgg16 they still are not the same:

```
R9, R16    identical in every field but the echoed capacity numbers
V8, V9     NoCLevel temporal permutation reversed
             2 MiB  WOx4 -> HOx2
             4 MiB  HOx2 -> WOx4
           same factors, same dram_num_steps (16), same objective
```

That reversal is consumed, not cosmetic. `decode.py:245` reads the JSON
outer-to-inner and `decode.py:278` reverses it into an ordered list; `tiles.py`
emits tiles in `(dram_i, noc_i, core_id)` order and `tiles.py:157` decodes
`noc_i` against that ordered list. Reversing the loops permutes which
`(ho, wo)` each `noc_i` names, so the same set of tiles is emitted in a
different sequence. Harmless for Stage 2 and 3 totals; not harmless for Stage 4,
where under LRU the access order is the recency stack.

**Run-to-run reproducibility is intact, and now confirmed across runs 18 hours
apart.** The two layers carried over from the first run re-solved to
byte-identical JSON:

```
IDENTICAL  schedules/pe16/loas/vgg16_T4_all/layer_09_features_30.json
IDENTICAL  schedules/pe16/loas/resnet19_T4_all/layer_16_layer3_0_conv2.json
```

and all 26 shared rows of `mode_sweep.json` match field for field, ignoring
`solve_seconds`. The tie-break bites only when comparing across different arch
configurations, not when re-running one.

## What Stage 2 consumes

Only `outputs/schedules/pe16/loas/`, the 2 MiB canonical solve, four layers. The
other `pe*` trees and `schedules_noc/` exist to support the claims above and are
not pipeline inputs.
