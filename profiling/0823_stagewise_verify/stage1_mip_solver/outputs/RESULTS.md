# Stage 1 results: MIP solver

Run 2026-08-23 by `run_stage1.py`, `conda run -n base`, gurobipy 13.0.2.
Raw log `stage1.log`; records in `solve_rows.json`, `num_pes_invariance.json`,
`mode_sweep.json`, `noc_size_sweep.json`. Schedules are written with
`indent=1` (`src/tracegen.py:130`), so they read as normal JSON.

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

## The two schedules

| | vgg16 `layer_09_features_30` | resnet19 `layer_16_layer3_0_conv2` |
|---|---|---|
| KH,KW,CIN,COUT,HO,WO,T | 3,3,512,512,4,4,4 | 3,3,512,256,4,4,4 |
| NodeLevel temporal | KH3, KW3, CIN512, T4 | KH3, KW3, CIN512, T4 |
| NodeLevel spatial | COUTx4 | COUTx4 |
| NoCLevel temporal | WOx4 -> HOx2 | HOx2 |
| NoCLevel spatial | COUTx16 | COUTx16 |
| DRAM temporal | COUTx8 -> HOx2 | COUTx4 -> WOx2 -> HOx2 -> WOx2 |
| `dram_num_steps` | 16 | 32 |
| mode | gb_oooo | gb_oooo |
| objective | 160.2873338750062 | 152.35586206940675 |
| delay | 2359296 | 1179648 |

NodeLevel is fully forced by the dataflow and identical in both layers: `full`
on KH/KW/CIN/T via `node_capacity.py:132-136`, COUT pinned spatially by
`node_level.py:62`, HO/WO barred by `node_capacity.py:124-128`. Occupancy of
the 32 KiB node buffer:

```
weight  3*3*512*4 = 18432 B  of 30720   60%
psum        4*4*2 =    32 B  of  1024    3%
vmem          4*4 =    16 B  of  1024    2%
```

NoCLevel occupancy at 2 MiB:

| | weight | psum | vmem |
|---|---|---|---|
| vgg16 | 294912 / 1966080 | 4096 / 65536 | 2048 / 65536 |
| resnet19 | 294912 / 1966080 | 1024 / 65536 | 512 / 65536 |

Nothing binds at NoCLevel. Weight sits at 15% of the 2 MiB budget.

---

## A. num_pes does not move the schedule

| num_pes | Verdict |
|---|---|
| 4, 64, 256 | OPTIMAL, full schedule JSON identical to num_pes 16 |
| 16 | OPTIMAL (canonical) |

Six comparisons, six matches. `num_pes` reaches the model only as an upper
bound (`spatial.py:78`, `dataflow.py:116`), while
`configs/dataflow/loas.yaml`'s `COUT: {spatial: 4}` becomes a linear equality
at `node_level.py:62` pinning NodeLevel COUT spatial to exactly 4. The ceiling
never binds.

---

## B. All 13 TrafficModes are enumerated; BASE never wins

`solve_best_schedule` iterates `for mode in TrafficMode` (`solve.py:300`).
`mode_sweep.json` records every mode's outcome rather than only the winner's.

| Mode | vgg16 `layer_09` | resnet19 `layer_16` |
|---|---|---|
| `base` | feasible, score 7.39544e+07 | feasible, score 3.22733e+07 |
| `psum_dram_otok`, `psum_gb_otok` | INFEASIBLE | INFEASIBLE |
| `vmem_dram_xxxt`, `vmem_gb_xxxt` | INFEASIBLE | INFEASIBLE |
| `dram_oooo`, `dram_ooot`, `dram_oook` | INFEASIBLE | INFEASIBLE |
| `both_dram_ootk` | INFEASIBLE | INFEASIBLE |
| **`gb_oooo`** | **feasible, 6.13718e+07, WINS** | **feasible, 3.07005e+07, WINS** |
| `gb_ooot`, `gb_oook`, `gb_ootk` | INFEASIBLE | INFEASIBLE |

2 of 13 feasible for both layers, and `gb_oooo` beats `base` on `_mode_score`
(`solve.py:272`), so the shipped schedule is not the unconstrained BASE model.

The 11 infeasible modes all constrain the ordering of K (COUT) or T in the
DRAM or GB permutation regions. The LoAS dataflow empties those regions:
KH/KW/CIN/T are forced fully resident at NodeLevel and HO/WO are barred from
it, so T is not in the permutation regions at all and every pattern except
`oooo` has no slot to satisfy.

---

## C. NoCLevel global-buffer size

Ten totals swept at 30:1:1, num_pes 16, node buffer 32 KiB fixed. Reference
for the "same" column is the canonical 2 MiB. `noc_size_sweep.json` has the
full records.

### vgg16 `layer_09_features_30`

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

### resnet19 `layer_16_layer3_0_conv2`

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

Delay is 2359296 and 1179648 at every feasible size. It never moves.

### Two different minimums

**Feasibility floor: 32 KiB.** The NoC capacity expression covers levels
`[0, dram_start)`, which includes level 0, so the NoC weight budget can never
be smaller than the NodeLevel weight footprint of 18432 B. 16 KiB gives a
weight cap of 15360 and fails. The exact floor is `18432 * 32/30 = 19661 B`.

**Useful floor: about 307 KiB.** Holding all 16 cores' COUT slices resident
needs `3*3*512*(4*16) = 294912 B` of weight, so the total must be at least
`294912 * 32/30 = 314573 B`, roughly 307.2 KiB. 512 KiB clears it; 256 KiB
does not. The canonical 2 MiB is 6.7x clear of it.

### Below 307 KiB the spatial mapping changes character

The spatial product stays 16 at every feasible size: all 16 cores are always
used. What changes is **which dimension is spread across them**. Weight
depends only on KH/KW/CIN/COUT (`constants.py:83-91`), so mapping HO or WO
spatially replicates the same weight tile across nodes and shrinks the NoC
footprint:

```
COUTx16  -> 294912 B      512 KiB and up
COUTx8   -> 147456 B      256 KiB
COUTx4   ->  73728 B      128 KiB
COUTx2   ->  36864 B       64 KiB
COUTx1   ->  18432 B       32 KiB
```

For a weight-cache study this is decisive. Under COUTx16 the 16 cores fetch 16
different weight slices; under WOx4 -> HOx4 they fetch the same slice,
perfectly shared. Opposite cache workloads. It also trips a known downstream
hazard: the campaign grids burst along COUT, and `PROGRESS.md` U29 records
that a non-COUT `burst_dim` "decodes silently wrong rather than being
refused". Any NoC at or below 256 KiB puts a non-COUT dimension in the spatial
split. 2 MiB is comfortably clear.

---

## The objective does not pin down the schedule

At 4 MiB, 2 MiB, 1 MiB and 512 KiB the vgg16 objective is bit-identical at
`160.2873338750062` and the delay is identical, yet `dram_num_steps` is
16, 16, 64, 128. None of the NoC capacities binds at the top three sizes
(294912 used against 3932160, 1966080, 983040; psum and vmem two orders
clear). The models differ only in a non-binding right-hand side, so the LP
relaxation differs, Gurobi's search path differs, and a different member of
the same optimal face comes back.

2 MiB and 4 MiB are the closest pair, and they still are not the same:

```
resnet19   identical in every field but the echoed capacity numbers
vgg16      NoCLevel temporal permutation reversed
             2 MiB  WOx4 -> HOx2
             4 MiB  HOx2 -> WOx4
           same factors, same dram_num_steps (16), same objective
```

That reversal is consumed, not cosmetic. `decode.py:245` reads the JSON
outer-to-inner and `decode.py:278` reverses it into an ordered list; `tiles.py`
emits tiles in `(dram_i, noc_i, core_id)` order and `tiles.py:157` decodes
`noc_i` against that ordered list. Reversing the loops permutes which
`(ho, wo)` each `noc_i` names, so the same set of tiles is emitted in a
different sequence. Harmless for Stage 2 and 3 totals; not harmless for Stage
4, where under LRU the access order is the recency stack.

**Run-to-run reproducibility is intact.** The canonical `pe16` solve and the
NoC sweep's own 2 MiB solve are independent invocations of the same model and
return byte-identical schedules, for both layers. A whole second execution of
this script also reproduced every number above. The tie-break bites only when
comparing across different arch configurations, not when re-running one.

## What Stage 2 consumes

Only `outputs/schedules/pe16/loas/`, the 2 MiB canonical solve. The other
`pe*` trees and `schedules_noc/` exist to support the claims above and are not
pipeline inputs.
