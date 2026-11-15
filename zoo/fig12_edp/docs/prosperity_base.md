# Prosperity BASE-mode schedules and the Fig 12 energy model

Status: for user review. Parent plan:
`docs/plans/2026-11-11-fig12-edp-plan.md`; per-arch sibling
`zoo/fig12_edp/docs/spinalflow_energy.md`. Sources: the 749 committed
schedules under `zoo/wt500_fig3cfg/outputs/schedules/`,
`zoo/wt500_fig3cfg/outputs/manifest.json`,
`zoo/wt500_fig3cfg/prosperity_infeasibility.md`,
`zoo/wt500_fig3cfg/walkthroughs/prosperity.md`, and the solver / nocsim
code cited inline. Every count below was measured on this host against the
committed schedules; the one re-solve is marked as such.

**Recommendation: no exclusion, and no BASE-specific energy term.** The 29
prosperity BASE layers need exactly the accounting every other layer gets.
What they do invalidate is one *inference*. `spinalflow_energy.md` §3 row 8
counts psum/vmem buffer accesses from tc.csv transactions, which is the
right source; but it argues the granularity of that count - "per-tile
store/collect, NOT per-accumulate" - from the solver's `temporal_traffic`
being 0 on 149 of its 151 schedules and 2.0 on the two sdt_2_512 MLP
exceptions, read there as "one extra round, x2". On prosperity's 29 BASE
layers the same metric reads 64.0, 96.0, 128.0 or 384.0. Read the same
way, that is 32 to 192 rounds of psum store/collect per tile, and
prosperity's memory-side energy inflates accordingly. nocsim emits
**zero** psum/vmem boundary transactions for all 29. Section 2 shows why
the magnitude of that metric carries no round count, and section 3 gives
the test to use in its place.

## 1. What "BASE mode" is, and where it shows up

**Problem.** `gen_inputs.py` does not solve one schedule per (arch, layer):
it solves all 13 traffic modes and keeps one. The energy model has to know
whether the surviving label changes what the hardware does.

**Importance.** BASE is the only mode that is feasible everywhere -
`manifest.json`'s `mode_digest.per_mode` gives it `OPTIMAL` on all 749
feasible pairs, against `gb_oooo` 621 and `both_dram_ootk`, `gb_ootk`,
`psum_dram_otok`, `vmem_dram_xxxt` and `vmem_gb_xxxt` at 0. If BASE were a
fallback for layers no constrained mode could place, it would be a
self-selected class of hard layers needing separate treatment. It is not:
it won 30 pairs on score (`mode_digest.winner_mode_counts`), and in every
one of the 29 prosperity cases 5 or 6 modes were simultaneously `OPTIMAL`
(the per-pair `result.mode_statuses` list).

**Innovation.** BASE is the *absence* of an ordering constraint, not a
dataflow: `_MODE_SPECS[TrafficMode.BASE]` is the one spec whose
`add_constraints` is `None` and whose `zero_vars`/`gb_only_vars` are empty
(`src/lays/scheduler/modes.py:54`, `:80`). The other 12 each pin a loop
pattern that lets the solver's traffic term *drop* a variable's crossing
cost - not by making the machine cheaper, but by making the cost
expression smaller. Selection is then a plain argmin over the CoSA
reference score, with no special case for BASE
(`src/lays/scheduler/solve.py:264-266`, `:303-305`; weights
`w_u, w_tr, w_dl = 0.1, 1.0, 10.0` at `:261`). BASE wins where the
constrained orders cost more weight traffic than the psum/vmem term they
erase.

**Implementation.** The label is written once, at
`zoo/wt500_fig3cfg/gen_inputs.py:300` (`"mode": best_mode`), alongside the
full 13-entry `mode_statuses` (`:277-279`). It lands in each schedule
JSON's top-level `mode` key, e.g.
`outputs/schedules/prosperity/loas_resnet19_T4_n500/layer_09_core_layer2_0_conv2.json`.
Measured distribution over the committed schedules: prosperity
`gb_oook` 86, **`base` 29**, `dram_oook` 19, `gb_oooo` 11; the only other
BASE winner campaign-wide is gustavsnn
`sma_azo_vgg_dvs128_gesture_T16_n500/layer_05_core_others_5`.

**In `step_cycles`: it does not appear at all.** `save_step_cycles` writes
exactly nine keys - format, arch, trace_dir, layer_name, sample_idx,
workload_dims, dram_num_steps, noc_num_steps, and per-tile
`{dram_i, noc_i, mac_cycles, lif_cycles}`
(`src/lays/nocsim/step_cycles.py:40-54`). There is no mode field and no
field derived from one except the two step counts. A counts script that
wants the mode must join back to the schedule JSON on
(arch, trace_dir, layer_name); `StepCycles.check_against`
(`step_cycles.py:93`) will catch a mis-join, because it compares both step
counts and the workload dims against the artifact.

The 29 pairs, grouped by benchmark and layer shape
(KH=KW, CIN, COUT, HO, WO, T), with the weighted record estimates from
`zoo/wt500_fig3cfg/stokes/shards/shards.json`:

| benchmark | shape | layers | est. records (500 samples) |
|---|---|---:|---:|
| `spikinglm_t4` | 1x1, 3072, 768, 128x1, T4 | 12 | 2.24e10 |
| `loas_resnet19` | 3x3, 256, 256, 8x8, T4 | 5 | 6.79e9 |
| `spikformer_4_384_cifar100` | 1x1, 1536, 384, 64x1, T4 | 4 | 5.92e8 |
| `spikformer_4_384_cifar100` | 3x3, 384, 384, 8x8, T4 | 1 | 1.21e9 |
| `sdt_2_512_cifar100` | 1x1, 2048, 512, 8x8, T4 | 2 | 4.29e8 |
| `sdt_2_512_cifar100` | 3x3, 512, 512, 8x8, T4 | 1 | 4.28e9 |
| `loas_vgg16` | 3x3, 256, 256, 8x8, T4 | 2 | 2.08e9 |
| `sma_azo_vgg_cifar10_dvs` | 3x3, 512, 512, 8x8, T10 | 1 | 3.70e9 |
| `sma_azo_vgg_dvs128_gesture` | 3x3, 512, 512, 8x8, T16 | 1 | 5.97e9 |

Two properties of that table matter. The mode is a function of the layer
*shape*, not of the instance: every pair whose shape appears in that table
picks BASE, and no shape is split between BASE and another mode. The table
has nine (benchmark, shape) groups over eight distinct shapes -
`loas_resnet19` and `loas_vgg16` share 3x3/256/256/8x8/T4. And the
29 carry **20.0% of prosperity's whole weighted record volume**
(4.75e10 of 2.37e11; 0.83% of the campaign's 5.70e12), spread over 7 of
the 8 benchmarks - every one except A08/`vgg16_cifar10_loas`, whose large
layers are the six the solver refuses outright
(`prosperity_infeasibility.md` §2). Excluding BASE cases would therefore
punch a fifth out of seven of prosperity's eight bars, not trim a corner
case.

## 2. Why non-zero `temporal_traffic` does not mean a memory access

**Problem.** The 29 BASE schedules carry prosperity's largest psum and
vmem entries in `result.metrics.temporal_traffic`, by a factor of 32 to
192: `psum: 384.0, vmem: 384.0` on the spikinglm `output_dense` GEMMs,
`psum: 64.0, vmem: 64.0` on the 3x3 256-channel convs. 76 of the 749
schedules have both entries non-zero at all - prosperity `base` 29 and
`dram_oook` 19, gustavsnn `dram_ooot` 23 and `base` 1, ptb and spinalflow
`dram_oooo` 2 each. Every one of the 46 constrained-mode schedules among
them sits at 2.0, the smallest non-zero value the `TRAFFIC_MULT` doubling
permits; the 29 prosperity BASE values run 64.0 to 384.0 (and the single
gustavsnn BASE winner 1024.0). Read as access counts, the BASE values
would add psum/vmem round-trips to a fifth of prosperity at 32x to 192x
the value any constrained-mode schedule in the campaign carries.

**Importance.** This is the one place where the Fig 12 model could acquire
a scheduling artifact as a physical cost. The psum term is the largest
single entry in the score for these layers - for
`loas_resnet19/layer_09`, `util x sp x tt` for psum is 4096 x 16 x 64 =
4.19e6 against the weight term's 1.18e6 - so a count built on it would
dominate prosperity's memory energy and would make prosperity look worse
than its own simulated machine is.

**Innovation.** `temporal_traffic` is a *score proxy evaluated in
log2 space*, not an access count, and three of its properties make it
unusable as one. It carries a hard-coded read/write doubling,
`TRAFFIC_MULT = [1, 2, 2]` for (weight, psum, vmem)
(`src/lays/scheduler/constants.py:68`). For weight and psum it is the
product of the temporal factors at the slots where a per-variable
indicator `y[(v,i)]` is set, i.e. one term per *boundary crossing the
expression charges for*, which includes the first, unavoidable pass over
distinct tiles - for `layer_09` the value 64 is `2 x 32`, the 32 COUT
tiles each written once, not 32 re-fetches of the same data
(`src/lays/scheduler/metrics.py:85-120`). And it is a solver-side mirror
of the objective, built for comparing modes against each other, with no
consumer anywhere outside mode selection and reporting: a repo-wide grep
for `temporal_traffic` finds it only in `scheduler/` plus
`scheduler/cli.py:320`, `:346`.

nocsim does not read it. It re-derives its own traffic question from the
decoded loop order, which is the alternative this rejects: four structural
flags, each "are these dims never preceded by a non-target dim, scanning
inner to outer" (`_is_dims_innermost`,
`src/lays/nocsim/schedule/steps.py:217-247`):

```
is_psum_dram_free = K dims innermost in the DRAM loop            (steps.py:84)
is_vmem_dram_free = T innermost in the DRAM loop                 (steps.py:85)
is_psum_gb_free   = K dims innermost in NoC+DRAM integrated loop (steps.py:89)
is_vmem_gb_free   = T   innermost in that integrated loop        (steps.py:90)
```

**Implementation.** Decoding all 749 committed schedules
(`schedule_from_strategy` + `StepInfo`) gives all four flags `True` for
**every** schedule of every arch, the 29 prosperity BASE ones included.
For `loas_resnet19/layer_09` the reason is visible in the strategy: the
DRAM permutation is `COUTx32 -> CINx16` (outer to inner), so the reduction
dim `CIN` is the innermost temporal loop and each output tile's reduction
finishes before the next tile starts; `T` never appears in a temporal loop
at all, because the prosperity mapspace pins `T: full` at NodeLevel
(`prosperity_infeasibility.md` §1), which makes `is_vmem_*_free`
trivially true. Those flags then suppress the transactions:
`skip_psum_gb`/`skip_vmem_gb` at `src/lays/nocsim/combine.py:246-247`
force `load_psum`/`store_psum`/`load_vmem`/`store_vmem` to skip
(`:429` passes `is_first_K=(is_first_K or skip_psum_gb)`), and
`si.is_psum_dram_free` / `is_vmem_dram_free` skip the DRAM legs
(`:293` and the two calls after it). So a BASE schedule contributes
**zero** psum/vmem GB or DRAM transactions to `tc.csv`, exactly like a
`gb_oook` one, and the solver metric's non-zero value corresponds to no
event in the simulated machine.

What does survive is the intra-step psum/vmem movement, which is not
gated by these flags at all: `k_chain` (`combine.py:457`) and `t_chain`
fire every step, so cross-PE psum reduction and the LIF carry appear in
`tc.csv` under BASE as under any other mode.

## 3. The accounting model for the 29 layers

**Problem.** Fig 12 needs one rule per arch that says which counts come
from where. Prosperity's BASE layers are the test of whether that rule can
be mode-blind.

**Importance.** A mode-dependent rule would need per-mode validation on
all five archs and would put the mode label - a solver artifact that a
re-solve can legitimately change, as `walkthroughs/prosperity.md` warns
at its head - into the energy numbers.

**Innovation.** Make the rule mode-blind, and justify it on the one thing
the mode cannot touch: the **node tile**. The prosperity mapspace pins
every NodeLevel extent by equality rather than by inequality
(`node_capacity.py`'s `FULL` branch and `_max_product_leq` equality pins;
see `prosperity_infeasibility.md` §1), so no mode has any freedom in the
node tile, and the traffic modes constrain only the *order* of the NoC and
DRAM loops and the split of factors between those two levels. A re-solve
of `loas_resnet19/layer_09` under `base`, `gb_oook`, `gb_oooo` and
`dram_oook` (gurobipy on this host, 120 s limit each) confirms it: all
four return the identical node tile, `KH3 x KW3 x CIN16 x HO8 x T4`
temporal with `COUT4` spatial, and the identical `delay` of 2,359,296;
they differ only in the loop orders, in the spatial split, and in score
(base 3.106e7, `gb_oooo`/`gb_oook` 3.303e7, `dram_oook` 4.247e7). Since
Prosperity's record count, spike count and per-tile `mac_cycles` are all
functions of the node tile and the capture, every compute and node-local
memory count is mode-invariant.

The modes *do* move the shared-memory side, and there the right move is to
let the simulators count rather than to model the mode. BASE won
`layer_09` by keeping `COUT` spatial (weight spatial fanout 2, GB weight
tile 1,152 B) where `gb_oooo` spreads `CIN` across the 16 nodes (fanout
16, tile 9,216 B); because psum's spatial address zeroes the reduction
dims (`buf_spatial.py:116-128`), that same choice makes all 16 psum
groups singletons, so BASE's `k_chain` emits no inter-node links at all
while `gb_oooo` would pay a 16-PE psum chain every step. That is a real
energy difference, in BASE's favour, and it reaches the model for free
because `tc.csv` records the transactions that the solved schedule
actually produces.

**Implementation.** For the 29 BASE pairs, use the prosperity rule
unchanged:

```
compute + node-local      from the node tile and the capture
  (accumulate, compare,     (mode-invariant: identical node tile across modes;
   Vmem register, L1        counts per walkthroughs/prosperity.md's fetch rule,
   weight bursts)           which is a per-tile property)
shared memory-side        from tc.csv for the spad design, from the cachesim
  (GB, NoC hops, DRAM,      counters for the cache design - both generated from
   psum/vmem, k/t chain)    this schedule, so no mode term appears
T (delay)                 nocsim / cachesim total_cycles, as for every layer
```

and add one guard rather than one term: **never derive a count from
`result.metrics.temporal_traffic`.** `spinalflow_energy.md` §3 row 8 already
takes its count from tc.csv; what does not generalise is its use of the
metric's *magnitude* as a round count ("one extra round, x2" for the two
sdt_2_512 exceptions). For granularity as for presence, the test should be
nocsim's four structural flags, or the tc.csv psum/vmem transaction count
itself, which is what the energy join reads anyway. Under the flags, the
answer for prosperity is the same as for spinalflow (no GB/DRAM psum or
vmem traffic on any of the 749 schedules), but it is now established on
the quantity the simulator uses rather than on a proxy whose scale is not
in accesses.

The exclusion alternative is rejected on both grounds: the 29 are not a
degenerate class (5-6 modes feasible each, winner `OPTIMAL`, bridge gate
passed - `manifest.json` `bridge_gate.passed_schedule_count = 749` with
zero violations), and dropping them would remove 20% of prosperity's
record volume from 7 of 8 benchmarks.

## 4. Not determined here

1. **Whether the two traffic models agree in general.** Section 2 shows
   that for all 749 committed schedules nocsim finds no psum/vmem boundary
   traffic while the solver metric is non-zero on 76 of them: the 29
   prosperity BASE schedules, 46 constrained-mode schedules at 2.0, and
   the gustavsnn BASE winner at 1024.0. Which definition is the more
   faithful model of the psum boundary is not settled here; the Fig 12
   model follows nocsim because nocsim is what produces `tc.csv`. A
   mapspace change that puts a reduction dim outside a non-reduction one
   would make the flags false and the question live.
2. **The delay and node-tile invariance is verified on one layer**
   (`loas_resnet19/layer_09`, four modes) plus the structural pinning
   argument. A sweep over the eight distinct BASE shapes would make it a
   measurement rather than an argument; it costs one solve per
   (shape, mode).
3. **No `tc.csv` for these layers exists on this host**, so the "zero
   psum/vmem transactions" claim is derived from the skip conditions and
   the decoded flags, not from a run. The S2 nocsim stage will confirm it
   directly; the check is one assertion on the transaction-type histogram.
4. **The gustavsnn BASE layer** (`dvs128_gesture/layer_05_core_others_5`,
   `temporal_traffic` psum/vmem 1024) is outside this note's scope but has
   the same four flags `True` and so the same conclusion.
