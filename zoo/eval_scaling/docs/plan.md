# RQ2 eval_scaling plan - memory scaling of single-node vs multi-node, 5 architectures - AWAITING REVIEW, nothing implemented

Target: `fig:eval-scaling` in `src/08_evaluation.tex` of
`/u/yyu9/projects/2027_ASPLOS_neuro_cache`.

Basis: `docs/scaling_mock.py` (the figure's stated layout) plus the user's
specification of 2026-11-16. The figure sweeps **on-chip memory capacity**
at fixed node count, over the **whole layer set** of one workload, on
**five architectures**, reporting **performance and DRAM traffic**.

All writes under `zoo/eval_scaling/`. Nothing in this plan is implemented.

**Five questions were closed on 2026-11-16 and are recorded as closed, not
reopened**: the workload is the existing **CIFAR-10**
`B09/loas_vgg16_T4_n500` capture (Q1), the capacity grid is **1x / 2x / 4x**
exactly as the mock draws it (Q3), the figure carries **three series**
including the multi-node cache arm (Q4), and the previous campaign's Stokes
array is **cancelled** and is not a source of anything here (Q9). The fifth
was delegated by the user to boss, who adopted the **eventsim ablation** so
that row 1 compares weight-only makespans on all three series (Q11, with
`docs/q11_row1.md` as its finding and its spec). Section 12 holds all five
with their consequences, and the questions still open.

**Path convention.** Paths are repo-relative from the `neuro_cache` root,
except: a path beginning `configs/`, `outputs/` or `docs/` is relative to
`zoo/eval_scaling/`; `benchmarks.py`, `capture_traces.py`, `ckpts/` and
`upstream/` are under `/u/yyu9/neuro_cache_bench_trace/`; and
`src/08_evaluation.tex` is in the paper repo named above, not in this one.
Paths naming files this plan would create are marked where they appear
(`dedup.py`, `configs/sweep_config.json`, `outputs/dedup_map.json`,
`outputs/provenance.json`).

**Short forms used more than once**, each given in full here so a bare
basename in the text is unambiguous:

| short form | full path |
|---|---|
| `cli.py` | `src/lays/weight_trace_gen/cli.py` - the cachesim one is always written in full as `src/lays/cachesim/cli.py` |
| `sim.py` | `src/lays/nocsim/sim.py` |
| `decode.py` | `src/lays/nocsim/schedule/decode.py` |
| `stats.cpp` | `src/lays/cachesim/native/src/instrument/stats.cpp` |
| `config.cpp` | `src/lays/cachesim/native/src/config.cpp` |
| `cli_args.h` | `src/lays/cachesim/native/apps/cli_args.h` |
| `2026-11-11-fig12-edp-plan.md` | `docs/plans/2026-11-11-fig12-edp-plan.md` |
| `make_configs.py`, `run_case.py`, `gen_inputs.py`, `aggregate.py`, `plot.py`, `run_array.sbatch`, `test_hardening.py` | `zoo/eval_scaling/` |
| `layer_dim_coverage.md`, `prosperity_infeasibility.md`, `sweep_config.yaml`, `mapspaces/` | `zoo/wt500_fig3cfg/` |
| `meta.json` | inside a capture directory under `/work/nvme/bebv/yyu9/input_trace_delta/` |

---

## 0. What this plan is, in one paragraph

Two rows x five architecture panels. The x-axis is on-chip weight capacity at
**1x, 2x and 4x** of the sweep's base. Each panel carries **three series** -
single-node scratchpad, multi-node scratchpad, multi-node cache (ours) - as
`scaling_mock.py:15-19` draws them. Row 1 is performance, row 2 is DRAM
traffic, both normalized to the single-node 1x point of that panel. The claim
the figure exists to prove is that **growing one node's memory stops helping,
while spending the same bytes across nodes keeps converting capacity into
performance and into avoided DRAM traffic** - and that the cache organization
converts more of it than the scratchpad does.

**Three findings below change the design rather than decorate it.**

- The single-node schedule is **capacity-invariant** on all 13 LoAS layers,
  so the single-node series is not "saturating" - at this grid it is **exactly
  flat at 1.0 in both rows**, and the plan has to say why (section 3). This is
  a **measurement**, taken on the previous campaign's 130 solved LoAS
  schedules before those artifacts were deleted; section 3 states exactly what
  that leaves it standing as.
- That invariance makes a large fraction of the scratchpad simulation
  redundant, and the dedup is **provable rather than heuristic** - but it
  covers the two scratchpad series only. **The cache series cannot be
  deduped at all**, for a reason that is also mechanical (section 4).
- The cache series comes from a **different simulator** than the other two,
  covering the weight path only. That is the repo's established arrangement,
  not a departure, but it constrains what row 1 and row 2 may claim
  (section 5), and the 16-node geometry it needs is the one part of the
  three-series decision that cannot be delivered with the machinery as
  committed (section 7.7).

---

## 1. The workload: CIFAR-10, closed by the user

**Q1 is closed. The figure runs on `B09/loas_vgg16_T4_n500`, the existing
CIFAR-10 capture, and the caption states the dataset.** No checkpoint hunt,
no training, no new capture. This section records *why* the question was put,
because the plan was written against a CIFAR-100 specification and a reader
of the caption will want to know why the dataset there is not the one the
user named.

**The CIFAR-100 LoAS VGG16 model does not exist in this tree.** The evidence,
each item checked directly:

| what | state |
|---|---|
| captures under `/work/nvme/bebv/yyu9/input_trace_delta/` | 8 total; the only two LoAS VGG16 captures are `B09/loas_vgg16_T4_n500` and `A08/vgg16_cifar10_loas_T32_n500`, and **both report `"dataset": "cifar10/test"`** in their `meta.json` |
| the only CIFAR-100 captures | `A02/spikformer_4_384_cifar100_T4_n500` and `A04/sdt_2_512_cifar100_T4_n500` - different models, not VGG16 |
| benchmark registration | `benchmarks.py:352-356` (`vgg16_cifar10_loas`, T=32) and `:361-364` (`loas_vgg16`, T=4) both call `_cifar10(...)` and both load `ckpts/B09/vgg16_final_dict.pth.tar`. Neither has a CIFAR-100 form. |
| the LoAS checkpoint | `ckpts/CKPTS.md`, B09 section: copied byte-for-byte from `upstream/LoAS/sample_ckpts/`, i.e. the LoAS authors' own CIFAR-10 sample weights. The file is **not present on this machine** - `ckpts/` holds only `A02/cifar100/` and `A04/cifar100/`. |
| a CIFAR-100 LoAS checkpoint | **not in the tree, and not named in `CKPTS.md`.** A02 and A04 were switched to CIFAR-100 by swapping to published CIFAR-100 checkpoints (`CKPTS.md`, A02/A04 sections, both HuggingFace STEP URLs). `CKPTS.md` names no equivalent published CIFAR-100 LoAS checkpoint. |

**So "I switched to cifar100" had already happened for A02 and A04 and had
not happened for the LoAS models.** Producing it would have taken a
CIFAR-100-trained LoAS VGG16 checkpoint (I could not determine whether one is
published anywhere; absence from `CKPTS.md` and from the local `upstream/LoAS`
clone is not proof), a benchmark registration beside `benchmarks.py:361-364`
pairing it with `_cifar100("test", "cifar100/test")` (`benchmarks.py:193-194`,
the helper A02/A04 use), and a `capture_traces.py` run at T = 4, N = 500.
None of that is now in scope.

**Why the dataset does not cost the figure anything.** The 12 convolutional
layers are **unaffected** by the label count - their shapes depend on the
backbone. Only the classifier changes, `layer_13_core_classifier`, from
`oc = 10` to `oc = 100` (`layer_dim_coverage.md:66` records the current value
as 10), taking its weight footprint from 512x10 to 512x100, which is still
three orders below the sweep's smallest capacity. **The sweep's shape ladder,
and therefore every capacity argument in this plan, is identical between the
two datasets.** That is why the fallback was proposed and is why it costs the
claim nothing.

**What the caption must carry**: the dataset (CIFAR-10), the capture
(`B09/loas_vgg16_T4_n500`), T = 4 and N = 500. A reader comparing this figure
with any CIFAR-100 figure in the same paper needs that line to be there.

---

## 2. Scope, fixed by the user

| # | item | value | status |
|---|---|---|---|
| A1 | architectures | **all five**: SpinalFlow, PTB, LoAS, Prosperity, GustavSNN | fixed by user; matches the mock's 5 panels |
| A2 | workload | **one**: the LoAS VGG16 model, **CIFAR-10**, capture `B09/loas_vgg16_T4_n500` | fixed by user 2026-11-16 (Q1 closed); dataset stated in the caption |
| A3 | layer set | **the whole layer set** | fixed by user; count is Q2 |
| A4 | series | **three**: single-node spad, multi-node spad, multi-node cache (ours) | fixed by user 2026-11-16 (Q4 closed); matches `scaling_mock.py:15-19` |
| A5 | sweep | on-chip memory capacity at **1x / 2x / 4x** | fixed by user 2026-11-16 (Q3 closed); no sub-1x points, no 8x/16x |
| A6 | metrics | **performance and DRAM traffic** | fixed by user |
| A7 | schedule-identity dedup | required | fixed by user; section 4 - and section 4 states where it does not apply |

**"Sides" and "series" are not the same count.** There are two *machines* -
one node, and sixteen nodes holding the same total bytes - and three *series*,
because the sixteen-node machine is drawn twice, once with a scratchpad and
once with a cache. Every arch yaml, mapspace and schedule in this plan belongs
to one of the two machines; the third series reuses the multi-node machine's
schedules and changes only what simulates them (section 7.7).

**A6 needs no change to the mock**: `scaling_mock.py:49-50` already labels
the two rows `Speedup / single 1x` and `DRAM traffic / single 1x`.

All five architectures are supported by the machinery:
`ARCH_NATIVE_BRIDGES` resolves to exactly
`['gustavsnn', 'loas', 'prosperity', 'ptb', 'spinalflow']`
(`src/lays/weight_trace_gen/cli.py:385`, and the scheduler takes the same
set at `src/lays/scheduler/cli.py:103`), and all five mapspaces exist under
`zoo/wt500_fig3cfg/mapspaces/`. Replaying one capture on all five archs is
the wt500 campaign's own design - `zoo/wt500_fig3cfg/sweep_config.yaml:16-31`
lists the five architectures against eight captures as a cross product - so
this figure is a slice of a shape the machinery already runs.

---

## 3. The finding that changes the figure: the single-node schedule does not move

**Measured, not predicted - and the artifacts no longer exist.** The
previous campaign's 130 solved LoAS schedules were compared across its five
capacity points while they were still on disk. `zoo/eval_scaling/outputs/`
and `configs/` have since been deleted from the working tree on user command
(284 tracked deletions, uncommitted, recoverable from git history).

**What that does and does not do to this finding.** The numbers below were
read off real solver output and are recorded here as evidence; they are not
reproducible from the working tree as it stands, and nothing in this plan
treats them as an existing asset. **They were measured on exactly the
workload Q1 settled on** - the `B09/loas_vgg16_T4_n500` CIFAR-10 capture, the
LoAS mapspace, the same 13 layers - so the only things that differ between
that measurement and this figure are the grid, which narrows from five points
to three, and the architecture set, which widens from one to five. What the
finding measures is a property of the **mapspace and the layer shapes**, and
both are unchanged for LoAS. **S1b re-derives all of it from the new solves
and must not inherit these numbers** - they are the reason to expect a flat
single-node series and a large dedup, not a substitute for measuring either.

**Byte-level hashing is the wrong test and reports a false negative.** Every
schedule JSON carries `arch_yaml_sha256`, which differs by construction at
every capacity because the capacity *is* the arch yaml. All 130 files differ
byte-for-byte, and that fact means nothing.

**The right test is the loop nest.** Canonicalizing each schedule to
`{result.strategy, dram_num_steps, mode}` - the loop permutation, the spatial
split, the tile factors, and the DRAM step count, i.e. everything that
determines what is computed and what is fetched - and hashing that:

Measured on the deleted LoAS CIFAR-10 solves, x1 through x16:

| side | (layer, capacity) pairs | distinct schedules | identical across x1..x16 |
|---|---|---|---|
| single | 65 | **13** | **13 of 13 layers** |
| multi | 65 | 33 | 3 of 13 layers |

**Every single-node layer has one schedule for the entire capacity sweep.**
The analytic `delay`, the weight `temporal_traffic` and `dram_num_steps` are
identical at x1, x2, x4, x8 and x16 for all 13 layers.

**Why**, and this is the part that has to reach the caption: the capacity
constraint is **slack at every point on the single-node sweep**. The largest
weight working set over the 13 layers is 294,912 B (288 KiB, layers 08-12),
against a single-node capacity of 1,048,576 B (1024 KiB) at the x1 point
already. The binding multiplier would be **x0.28** - below the bottom of the
sweep. The sweep begins above the knee and only climbs.

The multi side is the opposite: per-node `lb` is 32,768 B at x1 and the
working set exceeds it for **12 of 13 layers**, so the constraint binds, the
scheduler is forced to re-tile, and the schedule moves with capacity.

**Three consequences, all design consequences:**

1. **The single-node series is a horizontal line in both rows** - exactly
   flat at 1.0, not "saturating". Section 5 shows this is not a bug in the
   figure, because nothing downstream of a fixed schedule can reintroduce a
   capacity dependence on that side.
2. **A reader will ask whether the x-axis is doing anything on that series.**
   The honest answer is that it is not, and that this is the result: at any
   capacity a single node can be given over this grid, the fixed inherent
   dataflow cannot convert it into performance or into avoided traffic.
3. **The onset of that flatness is out of frame, by decision.** The capacity
   constraint would bind at about **x0.28**, below the grid, so the knee
   itself is not in the figure. The user fixed the grid at 1x/2x/4x knowing
   this (**Q3**, closed). What the figure therefore shows on that series is
   the *consequence* of the knee having already been passed, not the knee;
   the caption has to say that, or a reader reads three flat points as a
   sweep that was never run.
4. **The numbers above are LoAS.** The other four architectures have
   different mapspaces and different working sets, so each needs its own
   identity check before its dedup is claimed. The check is the same script
   and costs seconds (section 4).

---

## 4. The schedule-identity check, and exactly what it skips

The user asked for this and for how the comparison is done. It rests on a
mechanical fact about the toolchain, which is why it is safe.

**It applies to the two scratchpad series and not to the cache series.** The
scope limit is stated at the end of this section and is mechanical in the same
way the dedup itself is - do not carry the saving across to the third series.

**The weight trace is a function of (schedule, spike sample) and nothing
else.** `run_case.py:391-414` invokes
`python -m lays.weight_trace_gen gen --arch <arch> --trace-root <...>
--trace-dir <capture> --layer <layer> --schedule-cache <s1>/schedules
--sample-start/--sample-count --out-dir <scratch>`.
**The arch yaml is never passed to the generator.** Capacity reaches the
trace only through the schedule the generator reads.

**The nocsim result is a function of (schedule, weight trace, `single_node`,
bitwidths, NoC dimensions) and nothing else.** `run_case.py:435-452` passes
`--schedule`, `--layer`, `--arch <arch yaml>`, `--weight-trace`. Of the arch
yaml, nocsim consumes only `arch.single_node` and the bitwidth block
(`SNNArch` / `SNNBitwidths`, `src/lays/nocsim/sim.py:334-335`); the NoC
dimensions are derived from the **schedule's** spatial factors, not from the
arch (`sim.py:393-395`). **`local_buffer.entries.weight` is read nowhere in
`src/lays/nocsim/`.** Capacity is a *scheduler* constraint; once a schedule
exists, the simulator never sees the capacity again.

**Therefore: identical canonical schedule implies bit-identical weight trace
and exactly equal `total_cycles` and `dram_bytes_*`.** Not approximately -
the downstream has no other input that varies. This is why the dedup is a
provable identity rather than a sampling shortcut.

**The procedure**, to be implemented as `zoo/eval_scaling/dedup.py`:

1. For each (arch, side, layer), load the schedule JSON at every capacity
   point from `outputs/s1/<arch>/<side>_x<m>/schedules/<arch>/<capture>/<layer>.json`.
2. Canonical key = `sha256` over
   `json.dumps({"strategy": result.strategy, "dram_num_steps": ...,
   "mode": ...}, sort_keys=True)`.
   **Excluded deliberately**: `arch_yaml_sha256` and
   `result.configs` (absolute paths), which vary by construction;
   `objective` and `mode_statuses` (solver bookkeeping, not the loop nest).
   **Included deliberately**: `dram_num_steps`, because it is the DRAM step
   count the traffic metric is built on, and a schedule that matched on
   `strategy` but not on it would be a canonicalization bug, not a match.
3. Group capacity points by key. One **representative** per group - the
   smallest multiplier - is enqueued for S3/S4.
4. Non-representative points are **not generated and not simulated**. Their
   rows are produced by copying the representative's result and stamping
   `deduped_from = <representative point>`.
5. **The gate that keeps this honest**: for one randomly chosen deduped group
   per (arch, side), run the skipped point for real and assert the result
   matches the representative **exactly** on `total_cycles` and every
   `dram_bytes_*`. The argument above says it must; the assertion is what
   catches a toolchain change that breaks the argument. A mismatch is a
   SEV-1 stop, not a warning.

**Saving, as measured on the deleted LoAS solves**: over the campaign's
**five-point** grid (x1-x16), **130 solved (layer, capacity) pairs - one
architecture, five capacity points** - collapsed to **46** distinct
schedules, so 84 pairs, **65 %**, were removed.

**That percentage does not transfer to this grid, and the plan does not
transfer it.** The measurement was over five capacity points; this figure has
**three**. Fewer points means fewer pairs to collapse, so the *fraction*
removed changes even if every schedule behaves identically. What does carry is
the mechanism, and it gives a bound rather than an estimate:

| | pairs per arch at 1x/2x/4x | after dedup | basis |
|---|---|---|---|
| single side | 3 x 13 = 39 | **13**, if section 3's flatness holds | one schedule per layer for the whole grid |
| multi side | 3 x 13 = 39 | between 13 and 39 | depends on how that arch's mapspace re-tiles; 3 of 13 layers were invariant on LoAS over x1-x16 |

So across five architectures the scratchpad work is **390 (arch, side, point,
layer) pairs**, falling to between **130 and 260 distinct schedules** - at 10
samples, 3,900 cases falling to between 1,300 and 2,600. **That lower bound
of 130 is a different quantity from the 130 solves above**, which were one
architecture over five capacity points; the two numbers coincide and have
nothing to do with each other. **S1b reports the real per-arch
figure before S3 is sized, and inherits no number from the deleted
campaign.**

**Where the dedup does not reach: the cache series.** The identity argument
above says that once a schedule is fixed, nothing downstream sees the
capacity. That is true of `lays.nocsim`, and it is **false of
`lays.cachesim`**: the cache simulator reads the capacity directly out of its
own config, as `l1_size_bytes` and `l2_size_bytes`
(`src/lays/cachesim/native/src/config.cpp:157-158`), and derives its line
counts from them (`config.cpp:425-427`). Two capacity points that share one
schedule therefore share the *trace* but **not the result** - the whole point
of a cache arm is that capacity changes the hit rate without changing the
loop nest. Consequently:

- **trace generation** for the cache arm is deduped on exactly the same key,
  because the WCTS stream is still a function of (schedule, sample) only;
- **simulation** for the cache arm is **not** deduped: every
  (point, layer, sample) is run. That is 5 x 3 x 13 x 10 = **1,950** cache
  runs, and the figure's total simulation cost is 3,250-4,550 cases rather
  than the 2,300 the five-point LoAS measurement suggested.

A dedup map that silently covered the cache arm would make the cache series
flat by construction - the exact artifact the figure would be accused of - so
`dedup.py` must carry the arm in its key and `aggregate.py` must refuse to
re-expand a cache row. **That refusal is a test, not a convention**
(section 8).

---

## 5. Metrics, counter-exact

For the two scratchpad series both metrics come from one nocsim run per
(point, layer, sample), parsed from its stdout by `run_case.py:248-286`. For
the cache series they come from one cachesim run per (point, layer, sample),
read out of its CSV row. The two sources are **not the same machine**, and
the subsection "The one thing row 1 may not claim" below is what keeps that
from becoming a wrong number.

**Performance.** nocsim reports `total_cycles`, the makespan. Performance is
its reciprocal, and the figure plots it normalized:

> `performance(point) = 1 / sum_l total_cycles(point, l)`
> `y_row1 = performance(point) / performance(single_x1)
>        = sum_l total_cycles(single_x1, l) / sum_l total_cycles(point, l)`

- Summed over layers **before** the ratio, per the paper's whole-model rule
  (`08_evaluation.tex:83-85`), never a mean of per-layer ratios.
- Normalized performance is a pure cycle ratio; no clock is involved and none
  needs to be stated. Higher is better; 1.0 is the single-node base point.
- Per-sample, then mean over the 10 samples with a 95 % CI.

**DRAM traffic.** nocsim reports `dram_bytes_weight`, `dram_bytes_psum`,
`dram_bytes_vmem` (`run_case.py:264-281`):

> `W(point) = sum_l (dram_bytes_weight + dram_bytes_psum + dram_bytes_vmem)`
> `y_row2 = W(point) / W(single_x1)`

Lower is better. **This all-traffic form is the scratchpad-to-scratchpad
comparison.** Putting the cache series on the same axis needs the weight-only
form instead, for the reason given two paragraphs below; `dram_bytes_weight`
is reported separately by nocsim, so the switch costs nothing but has to be
made deliberately and stated in the caption (**Q11**, closed: the weight-only
form is the one used). **Use the counted bytes, not the analytic CoSA product.**
`aggregate.py:3-8` records why, from a prior review: the analytic
`util x temporal_traffic` product "reconstructs total weight volume rather
than measuring capacity-dependent refetch, and over-counts when the GB tile
grows without the trip count shrinking". A capacity sweep is precisely where
that failure mode bites. The analytic value stays as a diagnostic column.

**The cache series' two counters.** `cachesim_run` emits a CSV row whose
schema is `src/lays/cachesim/native/src/instrument/stats.cpp:177-230`. Two
columns are the whole of what this figure takes from it:

- `total_cycles` (`stats.cpp:168`), the makespan of the weight path, with
  `tick_base_total` and `stretch_cycles` beside it as the no-stall baseline
  and the memory system's added cycles. Performance is its reciprocal, formed
  and normalized exactly as above.
- `dram_bytes` (`stats.cpp:282`), which is `dram_accesses * line_size_bytes`
  - whole 64 B lines, since `line_size_bytes = cin_block * cout_block *
  weight_bytes` = 16 x 4 x 1 (`config.cpp:422-424`, `examples/cache/base.json`).

**The one thing row 1 may not claim.** cachesim covers the **weight path
only**: "no psum/vmem/MAC/LIF/NoC"
(`docs/plans/2026-11-11-fig12-edp-plan.md:17-18`). nocsim's `total_cycles`
covers the whole node - MAC, LIF, psum and vmem traffic included. So a cache
`total_cycles` and a scratchpad `total_cycles` are **not two measurements of
one quantity**, and a ratio between them is not a speedup. This is the repo's
established arrangement rather than a departure - the results schema has an
`arm` column precisely so that a nocsim scratchpad row and a cachesim cache
row sit in one table (`arm = spad_nocsim` vs `cache`,
`src/lays/cachesim/native/apps/cli_args.h:53-59`; "the real scratchpad
numbers come from nocsim", `2026-11-11-fig12-edp-plan.md:26-28`) - but it has
to be handled, not inherited. **The handling, settled - Q11 is closed and the
ablation is adopted:** both rows are restricted to the weight path for all
three series. Row 2 is `dram_bytes_weight` for the scratchpad arms against
`dram_bytes` for the cache arm, and it is clean because nocsim reports weight
bytes separately. **Row 1 needed a weight-only makespan that nocsim does not
expose**, which `docs/q11_row1.md` establishes at the line; the adopted
answer is an **eventsim ablation re-run** - weight transfers and compute kept,
psum and vmem durations zeroed with their dependencies still enforced - whose
`total_cycles` is the weight-only makespan:

> `weight_makespan(point, l) = total_cycles` of the `--weight-only` run
> `row1_spad(point) = 1 / sum_l weight_makespan(point, l)`
> `row1_cache(point) = 1 / sum_l total_cycles_cachesim(point, l)`

`q11_row1.md` owns the instrumentation, the two gates, and the caption
requirement that comes with it: an ablation makespan is a **counterfactual
machine, not a decomposition** - both sides measure "the weight path, with
compute, everything else free" - so row 1 does not plot the scratchpad arms'
own `total_cycles`, and the caption and the CSV must both say so. The real
whole-node `total_cycles` is kept for every point.

**The compulsory floor** - every weight fetched exactly once - is drawn as a
dotted reference line on row 2, so a reader can see how much of the remaining
traffic is refetch and how much is unavoidable.

**Not plotted, kept in the CSV**: utilization, which A6 replaces;
`count_cycles`, `dram_cycles`, the stall decomposition, and the analytic
traffic from the scratchpad arms; `l1_hit_rate`, `l2_hit_rate`,
`dram_accesses`, `tick_base_total` and the stall-cause columns from the cache
arm. The hit rates are the first thing a reader asks the cache series about
and they belong in the text, not in a third row.

---

## 6. Input selection, step by step

**Step I1 - the workload.** One capture, settled: **`B09/loas_vgg16_T4_n500`**
- the LoAS VGG16 model on CIFAR-10, T = 4, N = 500 - which is present on
`/work` today (`/work/nvme/bebv/yyu9/input_trace_delta/B09/loas_vgg16_T4_n500/`,
`meta.json` plus per-layer `.npy`). Nothing in I1 has to be generated. Q1
closed; section 1 holds the dataset note the caption owes the reader.

**Step I2 - the layer set.** "Whole layer set" = every layer the capture's
`meta.json` marks valid, with the exclusion rules in
`src/lays/weight_trace_gen/trace.py`. For the CIFAR-10 capture that is
**13**: `zoo/wt500_fig3cfg/layer_dim_coverage.md:194` gives `B09/loas_vgg16`
as **1 GEMM + 12 conv = 13**. The deleted campaign solved exactly 13
schedules per point, which agreed.

> **This resolves the 12-vs-13 discrepancy** the campaign-state note left
> open, and it is not a disagreement about which layers exist. **12 is the
> count of 3x3 convolutions**; **13 includes `layer_13_core_classifier`**, the
> 1x1 GEMM head. `execution_plan.md` says 12 in its case arithmetic and 13 in
> its solve count, which is why it contradicted itself.
> `layer_dim_coverage.md` settles it at 13. Whether the GEMM head *belongs* in a memory-scaling
> figure is a judgement, not a fact - its working set is 5,120 B, three
> orders below the sweep's smallest capacity, so it is flat on every series
> and contributes almost nothing to either whole-model sum. **Q2.**

**Step I3 - samples.** 10 per case, indices 000-009, which is what
`run_array.sbatch:29` passes and what gives a 95 % CI over samples.

**Step I4 - architectures.** All five (A1). Each needs its own mapspace pair
(single / multi). **None exist**: `configs/` is deleted, and
`make_configs.py:79-96` - the generator that would recreate it - hardcodes a
single LoAS COUT split and emits one arch's pair only. Deriving five pairs
from `zoo/wt500_fig3cfg/mapspaces/{loas,ptb,spinalflow,prosperity,gustavsnn}.yaml`
is new work, listed in section 8.

**Step I4b - the capacity grid.** Three points, **m in {1, 2, 4}**, settled
(Q3). The base point is 1,048,576 B of total weight storage on each machine;
4x is 4,194,304 B. No point below 1x, so the single-node knee at about x0.28
is out of frame by decision (section 3, consequence 3).

**Step I5 - a per-arch feasibility pre-check, before any sweep.** The
mapspaces are not interchangeable and one is known to reject layers:
`zoo/wt500_fig3cfg/prosperity_infeasibility.md:1-9` records that Prosperity's
`cap_NodeLevel_psum` constraint rejects 6 of its 151 schedulable (arch, layer)
pairs under the current mapspace. **If any rejection lands on this capture's
layers, that arch's panel has a hole**, and the figure must either drop the
layer from every panel - keeping the whole-model sums comparable - or report
that arch over a different layer set and say so. S1 produces this list before
anything expensive runs; it is **Q6**.

**Step I6 - the cache arm's inputs.** The third series consumes three things,
none of which the scratchpad arms need:

1. **A WCTS weight-address stream per (point, layer, sample)**, produced by
   `lays.weight_trace_gen gen --stream` from the **multi-node schedule** at
   that point (`src/lays/weight_trace_gen/cli.py:322-375`). One stream is one
   sample: `--stream` refuses a selection that resolves to more
   (`cli.py:328-330`), so the 10 samples are 10 streams, run serially down a
   pipe with nothing materialized (`cli.py:298`).
2. **A cachesim config JSON per point**, a flat object
   (`src/lays/cachesim/native/src/config.cpp:155-158` lists the integer
   fields) derived from `examples/cache/base.json` by overwriting
   `l1_size_bytes` and `l2_size_bytes` per section 7.7 and leaving every other
   field as the committed base: `cin_block: 16`, `cout_block: 4`,
   `weight_bytes: 1`, `layout: khkw_split`, `l1_assoc: 8`, `l2_assoc: 16`,
   `l2_mshrs: 32`, `l1_latency: 0`, `l2_latency: 2`, `l2_miss_latency: 24`,
   `l2_banks: 1`, `prefetch_policy: none`, `prefetch_distance: 0`.
3. **A built native binary**: `cachesim_run`, built by
   `make -C src/lays/cachesim/native MODE=release apps` - which
   `lays.cachesim` does automatically on first use
   (`src/lays/cachesim/cli.py:22-24`).

**The cache arm needs no new schedules.** It reuses the multi-node side's,
which is what makes it a comparison of memory *organization* at a fixed
dataflow rather than a second experiment.

---

## 7. Every configuration a run consumes

**7.1 Arch yamls.** None exist; `configs/` is deleted. `make_configs.py:25-76`
emits one per (side, multiplier) and must be extended to emit one per
(arch, side, multiplier): **5 archs x 2 machines x 3 points = 30 files**.
Fields, all of which a run reads:

| field | single | multi |
|---|---|---|
| `single_node` | `true` | `false` |
| `NodeLevel.instances` | 1 | 16 |
| `NodeLevel.pe.num_pes` | 64 | 4 |
| `local_buffer.entries.weight` | `1048576 * m` | `32768 * m` |
| `m` | 1, 2, 4 | 1, 2, 4 |
| `local_buffer.entries.psum` / `vmem` | 16384 / 16384 | 1024 / 1024 |
| `NoCLevel.entries.weight` | - (direct DRAM->node) | `524288 * m` |
| `NoCLevel.entries.psum` / `vmem` | - | 65536 / 65536 |
| `bitwidths` | `BW_WEIGHT: 8`, `BW_PSUM: 16`, `BW_VMEM: 32`, `DRAM_LATENCY: 0.25` | identical |

**Equal-capacity accounting**, asserted at `make_configs.py:124-125`:
`16 * 32768 * m + 524288 * m == 1048576 * m`. The two sides hold the same
total weight bytes at every multiplier. psum/vmem are held constant across
the sweep so that only weight capacity moves; the caption must state this,
because a reader will otherwise assume "memory" means all of it.

**PE accounting**: the single node gets `num_pes: 64` against 16 x 4 = 64 on
the multi side, so compute capability is equal and **only the memory
organization differs**. This is an assumption carried in `make_configs.py`,
never a user decision - **Q5**.

**7.2 Mapspaces.** One per (arch, side), `node_dim_capacity` in the form
`make_configs.py:79-96` writes. Its LoAS values are all of KH/KW/CIN/T `full`
with `COUT: {spatial: 64}` single and `{spatial: 4}` multi. Ten pairs
(5 archs x 2 machines) are generated in S0 from the campaign mapspaces -
**the four non-LoAS spatial splits are not yet chosen, and must not be
guessed.** The rule proposed: keep each arch's
campaign mapspace exactly, change only the COUT spatial factor to 1 node's
worth on the single side and 1/16th on the multi side, so the arch's own
dataflow is preserved and only the partitioning differs. **Q7.**

**One number that only a solve can give.** The per-core geometry the cache
arm needs (7.7) is the schedule's **NoC-level spatial product**: `n_cores` is
the product of the factors in `strategy.NoCLevel.spatial_splitting.loops`
(`src/lays/nocsim/schedule/decode.py:272-275`, read for the stream at
`src/lays/weight_trace_gen/cli.py:347-357`), not a field of any config above.
Whether the multi-node schedule unrolls across 4, 16 or 64 cores is therefore
**not determinable from the mapspace alone** and is read off the first solves
in S1b. Everything in 7.7 that depends on it is written as a rule over that
number rather than as a value.

**7.3 Sweep manifest.** `configs/sweep_config.json`
(`make_configs.py:115-121`): capture name, sample list, arch, and one entry
per point with `side`, `multiplier`, `arch_yaml`, `mapspace_dir`,
`total_weight_bytes`. Extended with an `arch` field per point.

**7.4 Case list.** `outputs/cases.txt`, one `"<point> <layer>"` per line,
read by `run_array.sbatch:23-25`; written fresh by S1b. **For the scratchpad
arms it holds representatives only; for the cache arm it holds every point**
(section 4). Its `point` field must be widened to carry both the architecture
and the arm, since `run_case.py:50-84` parses the architecture, arm and
`side_xM` fields.

**7.5 Slurm.** `run_array.sbatch`: `--cpus-per-task=2`, `--mem=8G`,
`--time=12:00:00`, `%64` concurrency, `OMP_NUM_THREADS=1`,
`OPENBLAS_NUM_THREADS=1`, `TMPDIR`/`-dev-shm` scratch, one array task per
(point, layer) covering all 10 samples.

**7.6 Scheduler.** Gurobi on the Delta login node, `Threads=1`, single-
threaded BLAS. 13 layers x 2 machines x 3 points x 5 archs = **390 solves**,
all of them new, and the cache arm adds none. For scale: the deleted campaign
solved 130 of these in about 15 minutes, so 390 is still login-sized.

**7.7 The multi-node cache arm.** Same 16-node machine, same schedule, same
total bytes; the scratchpad is replaced by a two-level cache and the
simulator changes with it. The full configuration:

| field | value | why |
|---|---|---|
| schedule | the multi-node schedule at the same `m` | fixes the dataflow, so only organization differs |
| trace | WCTS stream from that schedule, one per sample | `cli.py:322-375`; capacity is not in it |
| `l1_size_bytes` | `32768 * m` per core | the per-node scratchpad's bytes, now a cache |
| `l2_size_bytes` | `524288 * m` | the NoC-level scratchpad's bytes, now a shared cache |
| line geometry | `cin_block: 16`, `cout_block: 4`, `weight_bytes: 1` -> 64 B lines | `config.cpp:422-424`; the committed base |
| `l1_assoc` / `l2_assoc` | 8 / 16 | `examples/cache/base.json`, unchanged |
| latencies, MSHRs, banks, layout, prefetch | `l1_latency: 0`, `l2_latency: 2`, `l2_miss_latency: 24`, `l2_mshrs: 32`, `l2_banks: 1`, `layout: khkw_split`, `prefetch_policy: none` | unchanged from the base, so the sweep moves capacity and nothing else |
| `--arm` | `cache`; the scratchpad rows are `spad_nocsim` | `cli_args.h:53-59` |
| cases | 5 archs x 3 points x 13 layers x 10 samples = **1,950**, none deduped | section 4 |

**Equal-capacity accounting holds for the cache arm too**:
`16 * 32768 * m + 524288 * m == 1048576 * m`, the same assertion, so all
three series hold the same total weight bytes at every point. **This is a
deliberate departure from the cache operating point used elsewhere**:
`examples/cache/base.json` sets `l1_size_bytes: 16384`, half the per-node
scratchpad, and `zoo/cache_dse/docs/plan.md` keeps 16 KiB L1 / 512 KiB L2 as
its operating point. A capacity-matched cache and a cache at the design-space
operating point are different machines and only the first answers this
figure's question; the choice has to be made explicitly rather than inherited
from whichever JSON is nearest. **Q12.**

**What cannot be delivered with the machinery as committed, stated plainly.**
cachesim has no node level and no NoC: it models cores with private L1s
behind one shared L2, and nothing above that
(`2026-11-11-fig12-edp-plan.md:17-18`). The 16-way node partition of the
multi-node machine lives in `arch.yaml` as `NodeLevel.instances: 16`, which
the stream generator never reads - it reads only the NoC-level spatial
factors (7.2 above). So **how 16 nodes map onto cachesim's core/L1/L2
geometry is not decidable from the code as it stands**, and I will not guess
it. The three readings, with what each would cost:

1. **`n_cores` from the solve is already the node count** (i.e. the
   NoC-level spatial product comes out 16). Then the mapping is exact, nothing
   new is needed, and `l1_size_bytes = 32768 * m` is one node's cache. This is
   the reading the configuration above is written for.
2. **`n_cores` is the PE count within one node** (4, or 64). Then one cachesim
   run is one node's PEs but the stream carries the whole layer's weight
   references, so per-node traffic would be overstated by the node count, and
   the generator needs a per-node slicing option that does not exist.
3. **Run 16 independent cachesim instances**, one per node's COUT slice, and
   sum. This is the faithful reading of a 16-node machine with private L1s and
   a shared L2 - except that the shared L2 cannot be shared across 16
   processes, so it needs either a 16-core single run or a new multi-node
   mode in the simulator.

**S1b settles which reading applies by printing the NoC-level spatial product
of the first multi-node solve per architecture.** If it is not 16, the cache
series needs new simulator or generator work that is **not scoped anywhere in
this plan**, and that is the honest cost of the three-series decision. It is
the second half of **Q12**.

---

## 8. Framework components, per step

| step | component | invocation / entry point |
|---|---|---|
| S0 configs | `zoo/eval_scaling/make_configs.py` | writes arch yamls, mapspaces, `sweep_config.json` from scratch; **extend to 5 archs** |
| S1 schedules | `lays.scheduler` via `zoo/eval_scaling/gen_inputs.py`, a thin wrapper over the frozen `wt_gen_inputs_snapshot.py` | MIP solve per (arch, side, capacity, layer); capture pinned at `gen_inputs.py:23` |
| S1b dedup | **new** `zoo/eval_scaling/dedup.py` | section 4; writes `outputs/dedup_map.json` and the reduced `cases.txt` |
| S3 traces | `lays.weight_trace_gen` | `run_case.py:391-414`; LoAS/PTB/... native bridge per `--arch` |
| S4 simulation, spad arms | `lays.nocsim` | `run_case.py:435-452`, `--simulate` |
| S3c streams, cache arm | `lays.weight_trace_gen gen --stream` | `cli.py:322-375`, one sample per stream, piped |
| S4c simulation, cache arm | `lays.cachesim run` -> native `cachesim_run` | `src/lays/cachesim/cli.py:15-17, 22-24`; config JSON + WCTS on stdin, CSV row out |
| S5 aggregate | `zoo/eval_scaling/aggregate.py` | **row 1 is performance** (A6), and the two arms' column names differ; re-expand deduped scratchpad rows only |
| S6 plot | `zoo/eval_scaling/plot.py`, styled from `docs/scaling_mock.py` | 2 x 5 panels |
| harness | `zoo/eval_scaling/run_array.sbatch`, `run_case.py` | one array task per (point, layer) |
| tests | `zoo/eval_scaling/test_hardening.py` | extend with the dedup identity gate |

**New code, the complete list**:

- `dedup.py` (section 4), with the **arm in its key** so it cannot deduplicate
  a cache point;
- the per-arch mapspace and arch yaml generation in `make_configs.py`;
- an **arch and arm** field through `sweep_config.json`, `cases.txt` and
  `run_case.py`'s point parser (`run_case.py:50-84`);
- the cache-arm case runner: config-JSON emission per point, and the
  `gen --stream | cachesim_run` pipe with its CSV row collected. This is new
  but small - both ends exist and the stream is designed for exactly this
  pipe (`cli.py:298`);
- the performance metric, the two arms' different column names, and the dedup
  re-expansion in `aggregate.py`;
- **the eventsim ablation** adopted for Q11 and dispatched as T72: `var_name`
  as an appended eighth column in `transaction.py`'s `format_csv`, one field
  in eventsim's `Transaction` struct and its parser, a `--weight-only` flag
  that zeroes psum/vmem durations with their dependencies still enforced, and
  a second eventsim invocation per case in the harness.
  **`docs/q11_row1.md` is the spec**, including its two gates;
- the 3-series, 5-panel `plot.py`;
- two gates in `test_hardening.py`: the dedup identity assertion, and an
  assertion that **no cache row is ever re-expanded from a representative**.

Everything else is existing machinery. **The one item that may not be small
is the 16-node cache geometry of section 7.7**, which is unresolved until S1b
prints the spatial product.

**Nothing under `zoo/eval_scaling/outputs/` or `configs/` survives from the
previous campaign** - both directories were deleted on user command. The
harness scripts above are what remains, and S0/S1 regenerate everything they
consume.

---

## 9. Output storage layout

```
zoo/eval_scaling/
  configs/
    arch_{arch}_{side}_x{m}.yaml            5 x 2 x 3 = 30
    mapspaces_{arch}_{side}/{arch}.yaml     5 x 2 = 10
    cache_x{m}.json                         3, the cachesim configs (7.7)
    sweep_config.json
  outputs/
    s1/{arch}/{side}_x{m}/
      manifest.json
      workloads/{capture}/{layer}.yaml
      schedules/{arch}/{capture}/{layer}.json
    dedup_map.json          (arch, side, layer, capacity) -> representative
    cases.txt               representatives only
    s4/{arch}_{side}_x{m}_{layer}.csv       spad arms, one row per sample
    s4c/{arch}_cache_x{m}_{layer}.csv       cache arm, one cachesim row per
                                            sample, native schema
    logs/                   per-case gen + nocsim logs
    slurm/                  es-%A_%a.{out,err}
    aggregate.csv           (arch, side, multiplier) -> perf_norm, perf_ci,
                            traffic_norm, traffic_ci, + diagnostics
    eval_scaling.{pdf,png}
    provenance.json         input SHA256s, commit, dedup map hash, case counts
```

**Weight traces are never retained.** `run_case.py:389-416, 474` generates
into scratch and `shutil.rmtree`s after S4 consumes them - the wave pattern the
other zoo figures use, and the reason this figure needs no trace quota. **The
cache arm materializes even less**: its WCTS stream goes down a pipe and is
never a file at all (`cli.py:298`), so `--dump-trace` is used only if a run
has to be reproduced byte-for-byte.

**Into the paper repo**: only `eval_scaling.pdf`, and only after sign-off.

---

## 10. Execution chain

- **S0 - configs, from nothing.** `configs/` does not exist. Extend
  `make_configs.py` to five architectures and three points; emit arch yamls,
  mapspaces, the three cachesim config JSONs (7.7), manifest. Snapshot the
  capture `meta.json` and the mapspace sources with SHA256s. *Gate*: the
  equal-capacity assertion passes for every arch **and for the cache
  configs**.
- **S1 - schedules.** Solve every (arch, side, capacity, layer). Delta login,
  Gurobi. *Gate*: every solve `OPTIMAL`; any `INFEASIBLE` is recorded per
  Q6 before anything downstream runs.
- **S1b - identity check, dedup, and the cache arm's geometry.** Section 4.
  *Gates*: (a) `dedup_map.json` written, keyed by arm, and its saving reported
  **per architecture**; (b) section 3's flatness finding re-derived on these
  solves and confirmed or refuted for all five architectures - it inherits no
  number from the deleted campaign; (c) the **NoC-level spatial product**
  printed for the first multi-node solve of each architecture, because
  section 7.7's cache mapping stands or falls on it. If (c) is not the node
  count, stop and report: the cache series needs work this plan has not
  scoped.
- **S2 - pilot.** One representative case end to end; measure wall time and
  peak RSS to size the array. *Gate*: reviewed before S3.
- **S3/S4 - trace generation and scratchpad simulation.** Slurm array over
  representatives only. *Gate*: the dedup identity assertion of section 4,
  step 5, on one skipped point per (arch, side).
- **S3c/S4c - cache arm.** For every (arch, point, layer, sample), stream the
  multi-node schedule's weight addresses into `cachesim_run` with that
  point's config, and keep the CSV row. **No dedup on the simulation side**
  (section 4). *Gates*: `max_wait_depth` and the stall-cause identity the
  binary asserts itself (`stats.cpp:422-427` throws if the eight causes do not sum to
  `stall_total`), and `total_cycles >= tick_base_total` for every row - a
  cache cannot make the weight path shorter than its no-stall baseline.
- **S4 carries a second eventsim run per case**, the `--weight-only`
  ablation, whose `total_cycles` is row 1's weight-only makespan for the
  scratchpad arms (Q11, closed). Its two gates are in `docs/q11_row1.md`, and
  section 4's step-5 assertion covers **both** runs.
- **S5 - aggregate.** Re-expand deduped **scratchpad** rows, refuse to
  re-expand a cache row, compute performance and traffic with CIs over the 10
  samples. *Gates*: `assert total_cycles >= count_cycles / nodes` per
  scratchpad row, already enforced at `run_case.py:282-285`; and every cache point
  present on its own, none inherited.
- **S6 - plot.** Three series per panel, 2 x 5. *Gate*: user sign-off before
  the paper copy.

**S0 can start now.** The four questions that gated it - workload, grid,
series count, and the old array - are closed, and so is Q11. What remains
open (Q2, Q5-Q8, Q10, Q12) either has a proposal S0 can run under, or lands
later in the chain:
Q7 is the only one S0 itself consumes, and it is a confirm-or-replace of a
stated rule rather than a missing input.

---

## 11. Figure form

**From `scaling_mock.py`, which is the stated basis.** 2 rows x 5 arch
panels, `sharex`, `sharey='row'` (`scaling_mock.py:21`). Row 1 performance,
row 2 DRAM traffic, both normalized to that panel's single-node base point.
Log x-axis with explicit `1x/2x/4x...` ticks and minor ticks off
(`:44-46`). Series distinguished by colour **and** marker **and** dash
(`:15-19`), so the panels survive greyscale printing. One legend, on the
first panel only (`:53`).

**Three series, as the mock draws them** (`scaling_mock.py:15-19`): single-node
spad, multi-node spad, multi-node cache (ours). Q4 closed.

Changes the mock needs, none of them structural:

- a dotted compulsory-traffic floor on row 2;
- CI bands over the 10 samples;
- the cache series' caption note that it is a weight-path measurement from a
  different simulator, so row 1 plots weight-only makespans on both sides
  (section 5, Q11 closed);
- **the single-node series must be redrawn flat.** The mock draws it as
  `x ** 0.25` at `:26`, a visible rise; section 3 measured it exactly flat and
  section 4 shows nothing downstream of a fixed schedule can reintroduce a
  capacity dependence. With the grid now fixed at 1x/2x/4x (Q3) there is no
  point below the knee either, so the series is three points on the line
  y = 1.0 in both rows. **The mock is the user's stated basis for this design,
  so I have not altered it; Q10 asks for the one-line confirmation.** Left as
  it is, the real figure will not look like the mock it was approved from.

**Not changed**: the 2x5 shape, the three series, the two metrics, the
normalization, the grid. Those are the user's, and they match the mock as
drawn.

---

## 12. Open questions

### Closed by the user, 2026-11-16 - recorded so they are not relitigated

**Q1 - CLOSED. The workload is the CIFAR-10 capture.** Run on
`B09/loas_vgg16_T4_n500` and state the dataset in the caption. No checkpoint
hunt, no training, no new capture. The scaling claim is dataset-independent
because the 12 convolutions are identical between the datasets and only the
classifier's `oc` changes (section 1).

**Q3 - CLOSED. The capacity grid is 1x / 2x / 4x**, as `scaling_mock.py:12`
draws it. No sub-1x points, no 8x or 16x. The user chose this knowing the
single-node flatness finding, so the figure deliberately shows three flat
points rather than the knee at about x0.28 (section 3, consequence 3). Two
things follow and are folded in: the case arithmetic is a three-point
arithmetic throughout (sections 4, 7.6), and the 65 % dedup figure measured
over five points **does not transfer** - section 4 gives the bound that does.

**Q4 - CLOSED. Three series**: single-node spad, multi-node spad, multi-node
cache (ours), as `scaling_mock.py:15-19` draws them. The campaign-state note's
two-series decision is overridden. Its configuration is enumerated at 7.7, and
it brings three consequences the plan now carries: the cache arm **cannot be
deduped** (section 4), it is measured by a **different simulator covering the
weight path only** (section 5, settled as Q11), and its **16-node geometry is
not decidable from the committed code** (7.7, which is Q12).

**Q9 - CLOSED. The previous campaign's Stokes array is cancelled.** The user
runs `scancel` on Stokes, since there is no Stokes access from Delta.
**Nothing in this plan reads its rows**, including as a cross-check: the
earlier suggestion that its single-node rows could confirm section 3 for free
is withdrawn with the array. It ran the wrong dataset for one architecture of
five against configs that no longer exist.

**Q11 - CLOSED 2026-11-16. Row 1 compares weight-only makespans, via an
eventsim ablation.** The two scratchpad series are nocsim whole-node
makespans and the cache series is a cachesim weight-path makespan, "no
psum/vmem/MAC/LIF/NoC" (`2026-11-11-fig12-edp-plan.md:17-18`), so they are
not two measurements of one quantity. `docs/q11_row1.md` establishes that
nocsim exposes no weight-only makespan and that none can be assembled from
its counters, and recommends the ablation re-run; **the user delegated the
call to boss, who adopted it (R1)**, dispatched as T72 with that file as the
spec - the four instrumentation steps, both gates, the step-5 assertion
extended to cover both runs, and the S2 pilot timing the second invocation.
The fallback of row 1 for the scratchpad series alone is **not** taken; it
would have cost the figure its performance claim for the cache arm, which is
the half that arm exists to carry. Section 5 holds the resulting definitions.

### Still open

**Q2 - layer set, 12 or 13.** 12 convolutions, or 13 including the 1x1 GEMM
classifier? Resolved as a *fact* in step I2; this is only the judgement.
**Propose 13** - "whole layer set" is the user's wording, the head is
solvable (the previous campaign solved it), and its 5,120 B working set
changes no conclusion.

**Q5 - PE accounting.** Single node at `num_pes: 64` against 16 x 4 = 64, so
only memory organization differs. Carried in `make_configs.py`, never
confirmed by the user. **Propose confirming it**; without it the two machines
differ in two variables and the figure cannot attribute anything.

**Q6 - per-arch layer feasibility.** Prosperity's mapspace rejects 6 of 151
pairs on `cap_NodeLevel_psum` (`prosperity_infeasibility.md:1-9`). If any
rejection hits this capture, does that arch's panel drop the layer from every
panel (keeping whole-model sums comparable) or report a different layer set?
**Propose dropping from every panel and stating it in the caption.** S1
produces the list; the answer is not needed until then.

**Q7 - the four new mapspace pairs.** The only open question S0 itself
consumes. Proposed rule: keep each arch's campaign mapspace exactly and
change only the COUT spatial factor - one node's worth on the single side,
1/16th on the multi side - so the arch's own dataflow survives and only the
partitioning differs. Confirm, or name the per-arch splits.

**Q8 - T, and the second LoAS VGG16 capture.** The model exists at T = 4
(`B09`) and T = 32 (`A08`). **Propose T = 4**, i.e. `B09`, which is what Q1
settled on and what the rest of the corpus uses. `A08` is named here only so
that the choice is visible.

**Q10 - the mock's single-node curve.** `scaling_mock.py:26` draws the
single-node series as `x ** 0.25`, a visible rise. Section 3 measured it flat
and Q3's grid has no point below the knee, so the real series is three points
on y = 1.0. **The mock is the stated basis for this design, so I have not
altered it. Propose redrawing that series flat** - one line in the mock -
because otherwise the figure will not look like the mock it was approved from,
and the flatness is the single-node half of the result.

**Q12 - NEW, from the three-series decision. The cache arm's capacity and
geometry.** Two parts:

1. **Capacity.** 7.7 sets `l1 = 32768 * m` and `l2 = 524288 * m` so that all
   three series hold equal total bytes. `examples/cache/base.json` and
   `zoo/cache_dse/docs/plan.md` instead use a 16 KiB L1 / 512 KiB L2
   operating point. **Propose the capacity-matched values**, because equal
   bytes is the comparison this figure exists to make; the operating-point
   values answer a different question.
2. **Geometry, and this one may cost work.** cachesim has no node or NoC
   level, and the 16-way node partition is in a field the stream generator
   never reads. Whether one cachesim run is one node depends on the
   schedule's NoC-level spatial product, which only a solve gives. **S1b
   prints it; if it is not 16, the cache series needs generator or simulator
   work that is not scoped in this plan** (7.7 lists the three readings and
   what each costs). No proposal is offered for a number that does not exist
   yet.

---

## 13. What this plan could not determine

- **How 16 nodes map onto cachesim's core/L1/L2 geometry.** The partition is
  `NodeLevel.instances: 16` in the arch yaml, which the stream generator never
  reads; what it reads is the schedule's NoC-level spatial product
  (`decode.py:272-275`, `cli.py:347-357`), and no solved schedule exists to
  read it from. 7.7 states the three readings rather than picking one. Q12.
- **~~Whether nocsim exposes a weight-only makespan~~ - DETERMINED.** It does
  not, and none can be assembled from its counters; `docs/q11_row1.md` gives
  the two impossibility arguments at the line and the adopted ablation. Kept
  here as the record that this was once open, since the plan's earlier text
  rested on it. Q11, closed.
- **The dedup factor for the four non-LoAS architectures**, and for LoAS over
  this three-point grid. It depends on each mapspace's tiling and is only
  knowable after S1. The 65 % figure is LoAS over a five-point grid and is
  labelled as such everywhere it appears; section 4 gives the bound that
  holds without it.
- **Whether `tick`-level nocsim behaviour is truly capacity-free for every
  arch.** The argument in section 4 is read off the `single_node` and bitwidth
  consumption in `src/lays/nocsim/` and holds for the code as committed. The
  step-5 assertion exists because an argument is not a measurement.
- **Per-case wall time and memory, for either simulator.** No eval_scaling S4
  run ever completed and `outputs/` is deleted, so the scratchpad array is
  unsized; no cachesim run has ever been made on a stream from this capture,
  so the cache arm is unsized too. S2 measures both before S3 commits, and
  the cache arm needs its own pilot case in S2 rather than sharing the
  scratchpad one.
- **Whether a CIFAR-100-trained LoAS VGG16 checkpoint exists anywhere.** Moot
  under Q1's closure, recorded because the question was asked: absent from
  `ckpts/`, unnamed in `CKPTS.md`, no `cifar100` reference in the local
  `upstream/LoAS` clone - and absence here is not proof that none is
  published.
