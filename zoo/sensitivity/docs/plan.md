# RQ5 plan - reuse distance vs performance, performance vs controlled density - AWAITING REVIEW, nothing implemented

Target: `\subsection{RQ5: Sensitivity to Layer Size and Sparsity}`,
`\label{sec:eval-sensitivity}`, `src/08_evaluation.tex:209-221` of
`/u/yyu9/projects/2027_ASPLOS_neuro_cache`. The
subsection opens at `:209`, the label is `:210`, the open
`\todo{analyze reuse distance?}` is `:211`, "Layer size." is `:213-215`,
"Sparsity." is `:217-219`, and the closing commitment -
"For both, we report the gap between the scratchpad and the cache in
off-chip traffic, latency, and energy" - is `:221`.

RQ5 is **two graphs**, and the reported metric in both is **performance**:

- **G1** - reuse-distance CDF across the swept VGG16 layers, **tied to
  performance**: each swept layer contributes one CDF curve, and that
  layer's measured performance is carried in the legend, so a reader checks
  CDF shape against performance in one figure. Answers the `\todo` at
  `:211` directly.
- **G2** - **performance change** across a density sweep run **downward**,
  three curves, one per layer type (shallow / mid / deep), **cacheA only**.
  Answers "Sparsity." at `:217-218`.

**A tension the user should see, recorded rather than resolved.** The paper's
closing line at `08_evaluation.tex:221` currently commits RQ5 to "the gap
between the scratchpad and the cache in off-chip traffic, latency, and
energy". The figures here contain **no scratchpad**, report **performance rather
than latency**, and report **neither off-chip traffic nor energy**. `:221`
therefore has to be rewritten, and so do `:213-215` and `:217-219`. This is
Q8 and Q10 below, and it is a prose decision, not a figure decision.

All writes under `zoo/sensitivity/`, own configs, own snapshot of anything
borrowed, own retained trace corpus (same law as `zoo/eval_scaling`,
`zoo/roofline`, `zoo/cache_dse`).

## Why the density sweep is synthetic, and why that is the main point

**This plan's density sweep is controlled, not observational. That is its
single most important property.**

The obvious alternative - comparing real captured layers whose spike
densities happen to differ, grouped into "iso-shape families" so that shape
is held fixed and only density moves - is the best construction available
from real captures alone, and it has two defects that no amount of care
removes:

1. **Density is not a free variable in a capture.** It is whatever the
   trained network produced at that depth on that dataset. Within an
   iso-shape family, density co-varies with position in the block, which
   co-varies with the statistics of the incoming feature map. The honest
   reading of an iso-shape family curve is "deeper layers of this block are
   denser and also slower", not "density causes this".
2. **The observable range is often too narrow to resolve anything.**
   Measured over samples 0-9 of
   `examples/input_trace/delta/B09/loas_vgg16_T4_n500` (one `np.count_nonzero`
   pass, done in planning; S1 re-runs it and commits the numbers):

   | real iso-shape pair/family | shape | measured mean input density |
   |---|---|---|
   | `layer_05_core_features_17` / `layer_06_core_features_20` | 256/256, 8x8 | 0.1669 / 0.1705 |
   | `layer_08_core_features_27` / `layer_09_core_features_30` | 512/512, 4x4 | 0.1968 / 0.5746 |
   | `layer_10/11/12_core_features_34/37/40` | 512/512, 2x2 | 0.2729 / 0.4189 / 0.5303 |

   The mid-shape family spans **0.167 to 0.171** - a 2.5 % range. A density
   sweep built on it has essentially no x-extent. Only the 512/512 4x4 pair
   spans anything (2.9x), and it is two points.

A synthetic corpus removes both defects: shape, schedule, sample count and
simulator configuration are byte-identical across the sweep, and **density
is the only thing that moves**, over a grid chosen by us rather than by the
network. That is what "controlled factor" means here, and the caption must
say it: *density is set, not observed*.

The same move makes **G1 controlled in the other direction**. G1 draws all
three depths at **one** density, so depth (shape, footprint, tile structure)
varies while density is pinned. G1 and G2 are therefore the two orthogonal
slices of one 2-factor design (depth x density), not two unrelated studies.
Real captures do not permit that slice at all: they do not let you pin
density while varying depth.

**What it costs.** Random spikes at a target density are not real spikes.
Real spike tensors are spatially and temporally correlated; an i.i.d. draw
destroys that structure, and reuse distance and cache behaviour depend on
the *arrangement* of spikes, not only on their count. So G1's synthetic CDF
is the CDF of a structureless stream. The plan's answer is not to hide this
but to measure it: S4 below runs the *real* `.npy` of each of the three
layers through the identical chain and overlays its CDF as a dashed
validation curve at the layer's own measured density. If the synthetic and
real curves are close, the controlled sweep is credible; if they are far
apart, that gap is itself the finding and the caption says so. Open
question Q6.

**Not part of this plan**, so that the scope is unambiguous: the real-capture
observational density sweep over iso-shape families, the depth scatter over
25 real layers, and the one-factor-availability table for layer size (which
CIN/COUT/spatial pairs exist in VGG16 and ResNet19). The iso-shape pairs
survive in two roles only - as the argument above for going synthetic, and
as the free real-data overlay on the deep layer, where `layer_08` and
`layer_09` are the same shape at 0.197 and 0.575.

## Counter-exact definitions

Every column below is emitted by `csv_columns()` at
`src/lays/cachesim/native/src/instrument/stats.cpp:175` onward; the order is
a stability contract.

- **Reuse distance** = Mattson stack distance in **unique 64 B weight
  lines** between successive references to the same line; cold first
  references binned as infinite and reported as a separate fraction, not
  plotted. This is verbatim the definition Fig 5 already fixes
  (`zoo/fig5_reuse_distance/docs/plan.md:12`, granularity at `:13`, cold
  handling at `:32`), so RQ5 and Fig 5 stay on one axis.
  **The stream is the demand reference stream, not the trace.** It comes
  from `cachesim_run --access-log PATH`, 8 bytes per record, written at
  exactly the two sites that increment `l1_accesses` and `l2_accesses` and
  inside the same `if (r.demand)` guard
  (`src/lays/cachesim/native/src/core/engine.cpp:290-295` for L1,
  `:486-490` for L2). The header states the design intent outright - "The
  reuse-distance analysis that consumes it lives entirely outside the
  engine" (`src/lays/cachesim/native/include/cachesim/instrument/access_log.h:5-6`) - and the
  co-location with the counters is what makes the histogram total equal the
  row's access count *by construction* (`access_log.h:22-27`). So the engine
  needs no change. **G1 plots the L1 stream.**
  **Re-triage caveat, and it must be asserted, not assumed.**
  `l1_accesses` counts *probes*; a refused request re-probes and is logged
  twice (`access_log.h:29-34`). The two readings coincide only when nothing
  blocks. The calibration row below has `max_wait_depth = 0`, and the
  consumer must refuse any row where it is not 0.
**Path convention.** Every path is repo-relative from the `neuro_cache`
root. After a file is given once in full, later citations use its bare name
and line: `stats.cpp` is `src/lays/cachesim/native/src/instrument/`,
`engine.cpp` is `src/lays/cachesim/native/src/core/`, `access_log.h` is
`src/lays/cachesim/native/include/cachesim/instrument/`, and `cli.py`,
`trace.py` and `dense.py` are `src/lays/weight_trace_gen/`.

- **Latency** = `total_cycles` (`stats.cpp:168`), at
  `frequency_MHz = 500`, read from the cachesim row. It is not plotted; it
  is the quantity performance is defined from.
- **Performance**, the reported metric, is **not a column in any CSV in
  this project** and has to be defined here. It is the reciprocal of
  latency:

  > `performance = 1 / T_s = (frequency_MHz * 1e6) / total_cycles`

  with `seconds = cycles / (frequency_MHz * 1e6)`
  (`zoo/archx/zoo/snn_edp/pricing.py:72`) at 500 MHz
  (`zoo/archx/zoo/snn_edp/characterization/cache.architecture.yaml:2`;
  asserted in `test_legacy_counts.py:64` as `T_s == cycles/(500*1e6)`).
  **Relation to latency: it is its reciprocal**, and because the clock is
  fixed and identical across every point in this plan, any *normalized*
  performance is exactly an inverse cycle ratio - the frequency cancels. A
  point that was 0.8x latency is 1.25x performance.

- **G2 plots performance CHANGE, normalized per layer to that layer's own
  dense anchor**:

  > `y(d) = performance(d) / performance(d = 1.00)
  >      = total_cycles(d = 1.00) / total_cycles(d)`

  This is what makes three layer types share one panel: their absolute cycle
  counts differ by more than an order of magnitude (the deep calibration row
  is 240,720 cycles), but their *change* with density is directly
  comparable, and 1.0 at the left edge is a real anchor rather than an
  arbitrary scaling.

  **The one confound this normalization does not remove, and it is not a
  detail.** `stats.cpp:167-172` emits three numbers: `total_cycles`,
  `tick_base_total` (the trace's own timeline) and
  `stretch_cycles = total_cycles - tick_base_total`.
  `tick_base_total` falls on its own as density falls, because
  a sparser trace is a shorter trace with less work in it, so part of every
  rising curve is "there was less to do" rather than "the memory system did
  better". Normalizing to the dense anchor does not remove it. The plan
  therefore keeps the **stretch-only companion series**,
  `tick_base_total(1.00) + stretch_cycles` held against the same anchor, as
  a lighter second line - the part the cache design is actually responsible
  for. At the calibration row `stretch_cycles` is 87,304 of 240,720 cycles,
  36 %. Q12 asks whether that companion series ships in the figure or only
  in the CSV.

- **Off-chip traffic** (reported in the companion CSV, not plotted - see
  Q10) = `dram_bytes = dram_accesses * line_size_bytes()`
  (`stats.cpp:282`). **`dram_accesses` is not demand-only**: it counts
  prefetch fills, and the engine comment says so in those words - "the one
  memory counter that is not demand-only"
  (`engine.cpp:573-575`). This is load-bearing for G2's prediction below.
- **Spike density** of a synthetic trace = `np.count_nonzero(x) / x.size`
  over the `[T, N, Cin, Hin, Win]` uint8 array, per sample. For a synthetic
  trace this is a *set* value, and S2 records the realized value and asserts
  it against the target. **Do not use the `count_d_out` column** of the
  fig12 CSVs: `zoo/fig12_edp/counts/capture_counts.py:103-111` defines
  `density_layer = all_layers[min(position + 1, ...)]`, so `d_out` of layer
  N is the *input* density of layer N+1 - a predecessor proxy, and wrong for
  any layer whose predecessor was excluded.
- **Weight footprint** of a layer = `CIN * COUT * KH * KW * weight_bytes`
  with `weight_bytes = 1` (`zoo/wt500_fig3cfg/arch.yaml:12`, `BW_WEIGHT: 8`).

### The operating point, and the fact that decides what G2 can show

Read from a committed result row,
`/work/hdd/bebv/yyu9/neuro_cache_figs_20261116/fig12_edp/demo/all_bench/cases/loas/B09/loas_vgg16_T4_n500/layer_08_core_features_27/sample_00000/cache_a.csv`
(the production config JSONs are not in this checkout,
so the echoed config columns of a result row are the record -
`stats.cpp:141-165`, `:176-187`):

```
l1_size_bytes=16384  l1_assoc=8    l2_size_bytes=524288  l2_assoc=16
line_size_bytes=64   cin_block=16  cout_block=4          weight_bytes=1
layout=khkw_split    inclusion=non_inclusive             n_cores=16
policy=lru           l2_policy=pf_lru
prefetch_policy=next_access         prefetch_distance=4
l2_prefetch_policy=distance_aware   l2_prefetch_distance=1
l2_prefetch_min_touches=9  l2_prefetch_trigger=touch  l2_prefetch_axis=CIN
```

Measured on that row: `l1_hit_rate=0.972230`, `l2_hit_rate=0.0`,
`l2_accesses=1152`, `l1_accesses=2454656`, `dram_accesses=81471`,
`dram_bytes=5214144`, `total_cycles=240720`, `sim_wall_seconds=1.737395`,
`max_wait_depth=0`.

**At this operating point the L2 is effectively bypassed, and G2 must be
read in that light.** `l2_accesses` is 1,152 against 2,454,656 L1 accesses -
a factor of 2,130. The cause is structural, not a bug: `l2_accesses` and
`l2_hits` are incremented only under `if (r.demand)`
(`engine.cpp:486-488`), and with `next_access` prefetching at
`prefetch_distance=4` covering nearly the whole stream, a demand reference
that misses in L1 merges onto an already in-flight prefetch MSHR and never
becomes an L2 *demand* probe. `l2_hit_rate = 0.0` on 1,152 accesses is
therefore not "the L2 is useless"; it is "almost nothing reaches the L2 as a
demand". **Consequence for G2: at this operating point the latency
difference between arms is an L1-and-DRAM story.** The caption must say so,
or a reader who checks `l2_hit_rate` will conclude the design is broken.

**Consequence for G1**: the L2 access log would contain ~1,152 records and
its CDF would be noise. G1 plots the L1 stream only. The L2 log is still
written (it costs nothing) and its record count is reported as a diagnostic.

**A falsifiable prediction G2 exists to test.** Because `dram_accesses`
counts prefetch fills (`engine.cpp:573-575`), and because `next_access`
prefetches ahead by 4 regardless of how sparse the stream is, cacheA's
off-chip traffic should **not** fall proportionally with density. At the
sparse end the prefetcher should be fetching lines the spikes never consume,
so the latency curve should flatten - or, in the extreme, stop improving -
below some density. If that happens, the honest RQ5 result is "the
neuromorphic cache's advantage saturates below d ~ X, and the mechanism is
prefetch over-fetch", which is a better paper sentence than a monotone
curve. G2 is designed so that this is visible rather than averaged away.

## The design

### Which VGG16 layers are shallow / mid / deep

Real shapes, from `zoo/wt500_fig3cfg/layer_shapes.md`, section
"B09 / `loas_vgg16`" (`:213`; the table is `:217-231`; capture described at
`:215`: `cifar10/test`, T = 4, N = 500, 13 captured layers). Note the
column order in that table is `oc` (= COUT) before `inc` (= CIN).

| role | layer | row | CIN | COUT | HO x WO | K | T | weight footprint | measured real input density (s0-9) |
|---|---|---|---|---|---|---|---|---|---|
| **shallow** | `layer_01_core_features_3` | `layer_shapes.md:219` | 64 | 64 | 32 x 32 | 3x3 | 4 | 36,864 B = 36 KiB | 0.1424 (0.1193-0.1636) |
| **mid** | `layer_05_core_features_17` | `:223` | 256 | 256 | 8 x 8 | 3x3 | 4 | 589,824 B = 576 KiB | 0.1669 (0.1546-0.1840) |
| **deep** | `layer_08_core_features_27` | `:226` | 512 | 512 | 4 x 4 | 3x3 | 4 | 2,359,296 B = 2.25 MiB | 0.1968 (0.1587-0.2308) |

Why these three and not others:

- The footprints form a clean **16x then 4x ladder** - 36 KiB, 576 KiB,
  2.25 MiB - that **crosses the 2 MiB shared capacity exactly once**,
  between mid and deep (`arch.yaml:29`, `NoCLevel weight: 2097152`, with
  `BW_WEIGHT: 8` at `:12` so entries == bytes). That single crossing is the
  mechanism G1 is supposed to expose: the deep layer's weight working set
  does not fit, the mid layer's does.
- All three are square (CIN == COUT), so "depth" moves channel count and
  spatial size together in the way the network actually does, without a
  confounding aspect-ratio change.
- `layer_08_core_features_27` is the layer the committed calibration row
  above was measured on, so the deep arm of both graphs has a real anchor to
  check the synthetic pipeline against on day one.
- All three are 3x3 stride-1, so they are admitted by the replay eligibility
  rule under either statement of it (see below).
- `layer_13_core_classifier` is the fully connected classifier
  (`layer_shapes.md:231`, `spiking-GEMM`) and is excluded; the paper's own
  rule excludes it from whole-model aggregates.

**The 1x1 eligibility conflict is now
resolved, by reading the code rather than the two prose statements.**
`zoo/fig2_hw_n_sweep/README.md:26-27` says the admitted set is "1x1 (PAD=0)
or 3x3 (PAD=1) convolutions with stride 1"; `docs/plans/2026-11-04-cin-khkw-concat-layout-plan.md:110-111`
says `exclusion_reason` "rejects any layer whose kernel is not 3x3
stride-1". The code is `src/lays/weight_trace_gen/trace.py:101-118`:
`KERNEL_PADDING = {1: 0, 3: 1}` (`:27`) and the test is
`if kernel not in KERNEL_PADDING or p["stride"] != 1` (`:111`). **1x1
stride-1 is admitted; the 2026-11-04 plan doc is stale.** This does not
change RQ5 (all three layers are 3x3 stride-1) but it removes a standing
open question and it matters to `zoo/cache_dse`, which carries the same
unresolved note.

### The density grid

Nine values, swept **downward**, which is the order the figure draws them:

```
1.00  0.70  0.50  0.35  0.25  0.15  0.10  0.05  0.02
```

Justification, point by point - this grid is chosen, not inherited:

- **1.00 is the degenerate dense limit and is the figure's built-in sanity
  check.** At density 1 every weight line is spike-selected, so spike-gated
  fetching degenerates to fetching everything and the cache's advantage over
  the scratchpad must collapse toward 1x. If the plotted curves do not
  converge at d = 1.00, something in the pipeline is wrong, and we find that
  out from the figure rather than from a reviewer.
- **0.70 / 0.50 / 0.35 / 0.25 / 0.15 bracket the real operating band.**
  The measured input densities of VGG16's 13 captured layers span roughly
  0.14 to 0.58 (the three table rows above plus
  `layer_09_core_features_30` at 0.5746 and
  `layer_12_core_features_40` at 0.5303, measured the same way). Five grid
  points inside that band mean the synthetic curve can be compared against
  real layers wherever a real layer exists.
- **0.10 / 0.05 / 0.02 extend about an order of magnitude below anything
  the real captures reach.** This is the regime the design is for and it is
  entirely unobserved today: no VGG16 capture is sparser than ~0.12. It is
  also where the prefetch-over-fetch prediction above should bite.
- **Spacing is roughly geometric below 0.5** because the interesting
  structure in the sparse regime is multiplicative (halving density halves
  the spikes), while linear spacing would spend most of the grid in the
  dense end where nothing happens.
- **Cost is monotone increasing in density** (generation and replay time
  both scale with the spike count), so the three sparse points together cost
  less than the single d = 1.00 point. Extending downward is nearly free;
  extending upward is not.

**Realization, and the arithmetic Q5 rests on.** A target density can be hit
two ways: draw each element Bernoulli(d), or place exactly `round(d*N)` ones
at uniformly chosen positions. Bernoulli leaves the *realized* density
random, with relative standard error

> `sqrt((1 - d) / (N * d))`, `N` = CIN x Hin x Win x T spike sites.

At the G1 conditioning density `d = 0.15` that is, per layer:

| layer | `N` | relative s.e. of realized density |
|---|---|---|
| shallow 64, 32x32, T=4 | 64*32*32*4 = 262,144 | 0.46 % |
| mid 256, 8x8, T=4 | 256*8*8*4 = 65,536 | 0.93 % |
| deep 512, 4x4, T=4 | 512*4*4*4 = 32,768 | 1.3 % |

**The deep layer is the worst case, not the best**, because it has the
fewest spike sites: its 4x4 spatial extent costs more than its 512 channels
buy. 1.3 % is small in absolute terms, but it is noise injected into the one
factor this experiment exists to control, and it is *largest* exactly where
the footprint is largest and the cache effect is most interesting. That is
the argument for exact-count placement (Q5). Exact-count still randomizes
*which* sites are set - only the count is pinned - so the sample-to-sample
variation the five samples are there to capture is preserved.

The measured real band is drawn on G2 as a shaded span so the reader can see
at a glance which part of the curve is interpolation into observed territory
and which part is extrapolation.

### The arms: cacheA only (decided)

**G2 is the cache design only - `cacheA` - and its three curves are the
three layer types (shallow / mid / deep). No `spad` curve, no `cacheB`
curve.** Decided by the user; Q1 records it closed.

Three consequences, because they govern the stages below:

- **The panel's comparison axis is layer shape, not arm.** The question the
  figure answers is "does the cache's benefit from sparsity depend on how
  big the layer is?", not "does the cache beat the scratchpad?". That is a
  narrower claim and a cleaner one, and it is the question RQ5's title
  ("Sensitivity to Layer Size and Sparsity") actually names - both factors
  appear in one panel instead of one each.
- **One arm sets the cost.** One cachesim replay per (layer, density,
  sample), with no second replay and no nocsim run. The `spad` arm is the
  expensive one: it needs nocsim and its own generation path, not a replay
  of a retained `.wcts`. The compute section below is priced on one arm.
- **No capacity question arises.** The cache's 16 KiB / 512 KiB against the
  scratchpad's 32 KiB / 2 MiB (`zoo/wt500_fig3cfg/arch.yaml:18-32`) would
  matter if G2 compared those two arms, since the mismatch would be measured
  as part of "the gap". With no spad on the chart there is no gap to
  contaminate. **Q2 is closed: keep the 16 KiB / 512 KiB cacheA operating
  point**, consistent with `zoo/cache_dse/docs/plan.md`.

**What is lost, stated plainly so it is a choice and not an oversight.** The
scratchpad is the only arm whose fetch volume is *structurally*
density-insensitive - it fetches whole weight tiles whether or not any spike
selects them. It was therefore the only arm whose curve would have had a
**different shape** rather than a different offset, and it was the thing that
made the sparsity argument visible rather than merely quantified. With
cacheA alone, the reader sees that performance improves as density falls but
has nothing on the chart showing that a non-cache design would not improve.
That comparison exists elsewhere in the paper - RQ3's figure
(`fig:eval-spad-cache`, `08_evaluation.tex:194-200`) - so the fix is a
cross-reference in the caption rather than a curve. Q1 below records this
for the user in case they want the spad curve back as a dashed reference.

For the record, the arm set the machinery emits is wider than what this plan
runs, and is available if that decision is revisited:
`zoo/fig12_edp/stokes/stage1_worker.py:231` asserts the arm set is
`{'spad', 'cacheA', 'cacheB'}`, and `:303-312` dispatches the two cache arms
as `cachesim_run --trace ... --config cache_{a,b} --arm cache --out
cache_{a,b}.csv`, with the spad arm's result collected from
`noc/result.json` alongside them (`:325`). The one arm this plan runs:

| arm | simulator | what it is |
|---|---|---|
| `cacheA` | `cachesim_run --arm cache` | `next_access` d1=4 + `distance_aware` d=1 `min_touches=9`, `l2_policy=pf_lru`, 16 KiB L1 / 512 KiB L2 (the config block above) |

**Panel structure for G2**: **one panel, three curves** - one per layer
type. This is only legible because of the per-layer normalization defined
above; on absolute cycle counts the three layers differ by more than an
order of magnitude and would need one panel each.

## What machinery exists, and what is new

### The input-trace chain, end to end

This is the part the new spec asks to be laid out explicitly. The chain from
a spike-input tensor to a `.wcts` stream to a simulator result is:

```
synthetic .npy + meta.json  (trace dir)
      |  lays.weight_trace_gen.trace: load_layer_trace / build_workload_from_trace
      v
cached schedule JSON  (arch=loas, per layer)
      |  lays.weight_trace_gen.cli --stream  (native bridge reconstruction)
      v
.wcts stream on stdout, --dump-trace to retain it
      |                                   \
      |  cachesim_run --config cache_a --access-log
      v
cacheA row (total_cycles, dram_bytes, ...)
+ 8-byte access log  ->  NEW Mattson consumer  ->  reuse-distance CDF
```

**The decisive reuse fact, and it is worth stating loudly: the trace loader
is provenance-agnostic.** `src/lays/weight_trace_gen/trace.py` reads a
directory holding one `meta.json` plus one `<layer_name>.npy` per layer, and
nothing else (`trace.py:4-9`, `load_layer_trace` at `:31-74`). It validates
the array's shape against `meta["layers"][layer]` (`:68-73`) and derives the
workload dims from `meta["layer_params"]` (`build_workload_from_trace`,
`:127-161`). It does not know, and cannot know, whether the `.npy` came from
a GPU capture or from a random number generator. **So a synthetic corpus
needs no change to the generator at all - only a correctly-formed trace
directory.**

The exact `meta.json` schema to reproduce, read from the real capture
`examples/input_trace/delta/B09/loas_vgg16_T4_n500/meta.json` (9,163 bytes):
keys `arch`, `batch_size`, `captured_at`, `dataset`, `device`, `dtype`,
`excluded_layers`, `gemm`, `layer_params`, `layers`, `n_samples`, `subset`,
`timestep`. Of these the loader requires only `layers`
(`{name: [T, B, Cin, Hin, Win]}`) and `layer_params`
(`{name: {cout, kernel, stride}}`); the rest are provenance and must be
rewritten honestly for a synthetic corpus (`dataset: "synthetic/bernoulli"`,
`device` absent, a new `synthetic` block carrying the target density, the
seed derivation and the generator commit).

**The second decisive reuse fact: no Gurobi solve is needed.**
`check_schedule_matches_trace` (`src/lays/scheduler/artifact.py:130-152`)
compares the cached schedule's `workload.problem` against the dims derived
from `meta.json` and raises only if they differ (`:143-152`). The schedule is
a pure function of the *shape*, not of the spike content. The campaign's
`loas` schedules for all 13 VGG16 layers are committed in this checkout at
`zoo/wt500_fig3cfg/outputs/schedules/loas/loas_vgg16_T4_n500/*.json`, and I
verified the three this plan needs carry exactly the right dims:

| layer | schedule `workload.problem` | `dram_num_steps` | NodeLevel spatial split |
|---|---|---|---|
| `layer_01_core_features_3` | CIN 64, COUT 64, HO/WO 32, KH/KW 3, T 4 | 512 | COUT x 4 |
| `layer_05_core_features_17` | CIN 256, COUT 256, HO/WO 8, KH/KW 3, T 4 | 64 | COUT x 4 |
| `layer_08_core_features_27` | CIN 512, COUT 512, HO/WO 4, KH/KW 3, T 4 | 32 | COUT x 4 |

Because the synthetic layers reuse these shapes, these schedule files are
reused byte-for-byte. **That removes the Gurobi dependency, the solver
licence, and the largest single source of variance between the synthetic and
the real arms** - the synthetic run and the real `layer_08` calibration row
execute the identical schedule.

### `gen_inputs.py` and its lineage - what it is and is not

The spec asks to start from `zoo/fig2_hw_n_sweep/gen_inputs.py` and
`zoo/wt500_fig3cfg/gen_inputs.py`. Both were read, and the first thing to
record is that **neither generates input traces.** The name is a misnomer
inherited from the zoo convention "inputs = the simulator's inputs":

- `zoo/fig2_hw_n_sweep/gen_inputs.py` writes **architecture YAMLs and
  hand-built schedules** for a single-node hardware-size sweep: it emits
  `spinalflow_1node_n{N}.yaml` at `:93-115` and one manual schedule JSON per
  (network, layer, N) at `:135-144`, then validates each with
  `check_schedule_matches_trace` (`:145`) and `load_schedule` (`:146-149`).
  Its only contact with traces is reading each capture's `meta.json`
  (`:39-41`, `:71`) to derive workloads. Its docstring says so: "Generate
  single-node SpinalFlow hardware-size sweep architectures and mappings"
  (`:1`).
- `zoo/wt500_fig3cfg/gen_inputs.py` does the campaign-scale version of the
  same job: "it derives a workload from each capture's `meta.json`,
  enumerates all traffic modes and selects one schedule for every
  `(arch, trace, layer)` pair" (`:5-9`), over five architectures (`:61-67`)
  and eight captures (`:71-80`). Again: no trace content is generated.

What both contribute to this plan is the **template for a reproducible input
stage**: derive workloads from `meta.json` only, assert every downstream
contract before anything expensive runs, and freeze the result in a
manifest. `zoo/fig2_hw_n_sweep/gen_inputs.py:72-81` is the model - four
`assert`s (sample total, stride-2 support, trace path, valid layer set)
before a single file is written. `zoo/sensitivity/gen_synth_inputs.py`
copies that discipline.

**No synthetic spike-tensor generator exists anywhere in the tree.** A
search across `src/`, `zoo/` and `tests/` for Bernoulli/binomial/random
spike construction returns nothing. `src/lays/weight_trace_gen/dense.py` is
not it, despite the name: it is the analytic `ArchComputeModel` that assigns
every tile the same cycle count and "ignores the real trace and the
NodeTileSpec entirely" (`dense.py:1-9`), returning `[]` for weight addresses
(`:46-47`). **This is the one genuinely new piece of input-side code.**

### The `--stream` path to `.wcts`

`lays.weight_trace_gen.cli` (`src/lays/weight_trace_gen/cli.py`) mode 3
(`:301-319` for `emit_stream`,
`:322-379` for `run_stream`) is the path that turns
a loaded spike tensor into a `.wcts` stream:

- `run_stream` (`cli.py:322`) refuses any selection that is not exactly one
  sample (`:327-330`), locates the cached schedule at
  `<schedule-cache>/<arch>/<trace-dir>/<layer>.json` (`:332`), runs
  `check_schedule_matches_trace` (`:338-339`), derives
  `n_cores` from the schedule's spatial factors rather than from the data
  (`:349-359`, with the reasoning given inline at `:349-352`: taking
  `max(core_id)` "undercounts whenever some core drew no work"), loads the
  tensor via `load_layer_trace` (`:361-362`), reconstructs through the
  arch's native C++ bridge (`reconstruct_samples`, `:366-369`), and writes
  the stream (`emit_stream`, `:371-373`).
- `emit_stream` (`cli.py:301-319`) calls `stream_weight_trace` from
  `lays.cachesim.stream` and, with `--dump-trace PATH` (`cli.py:418-420`),
  writes a second, valid copy to disk (`stream_weight_trace` itself is
  `src/lays/cachesim/stream.py:194`). The docstring is explicit that this
  is "Not a byte tee ... a second pass over data already in memory produces
  a VALID short stream instead of a truncated one".
- `--stream` is serial by construction and refuses more than one sample
  (`cli.py:327-330`) or multiple workers (`:442-443`). Parallelism is across
  (layer, density, sample) tasks, not inside one.

**So `--dump-trace` is the retention mechanism this plan needs, and it
already exists.** No new code is required to materialize a `.wcts`.

### Trace retention - why this plan must own its corpus

The campaign never keeps weight traces: ~23 TB gzipped against a 1 TB quota,
so `zoo/wt500_fig3cfg/stokes/sim_shard.py` unlinks each stream as soon as
its results are durable (`_delete_consumed`, `sim_shard.py:192-204`). A
plan that expects to find campaign `.wcts` files will find nothing. This
plan therefore generates and **retains** a small corpus of its own, with the
provenance schema `zoo/concat_vs_khkw/provenance.json` already uses:
top-level `base_config`, `base_sha256`, `binary`, `binary_sha256`,
`stream_adapter`, `streams`, `warnings`, and per-stream
`{arch, layer, workload, sample_idx, path, bytes, sha256, tiles, cores,
burst_dim, burst_span, burst_stride, format_version}`. Copy it verbatim;
`binary_sha256` in particular is what makes "byte-identical regeneration"
checkable at all, since the stream bytes depend on the native bridge binary
as well as on the input.

### New code - the complete list

Four pieces, all small, none touching the engine:

1. **`zoo/sensitivity/gen_synth_inputs.py`** - writes the synthetic trace
   directories (one per density: `meta.json` + three `.npy`). ~120 lines.
   New, because nothing in the tree generates spike tensors.
2. **`zoo/sensitivity/build_corpus.py`** - for each (layer, density,
   sample), invokes `weight_trace_gen --stream --dump-trace`, hashes the
   result, and appends to `provenance.json`. Modeled line-for-line on
   `zoo/concat_vs_khkw/run.py`. New glue, no new mechanism.
3. **`zoo/sensitivity/mattson.py`** - the reuse-distance consumer: an
   O(N log N) stack-distance tree over the 8-byte access-log records,
   emitting per-(layer, density, sample) histograms and a CDF. **New, and
   it is the only piece with any algorithmic content.** See the sharing
   question below.
4. **`zoo/sensitivity/aggregate.py` + `plot.py`** - join, aggregate, render.

Explicitly **not** new: any cachesim engine change, any new CLI flag, any
scheduler/Gurobi run, any change to `weight_trace_gen`.

### The Mattson consumer, and sharing it with Fig 5

No Mattson tool exists. `zoo/fig5_reuse_distance/` contains exactly one
file, `docs/plan.md`, stamped "FOR BOSS REVIEW, NOT IMPLEMENTED" (`:1`) -
no code, no outputs. Its C8 (`:33`) makes the whole figure conditional on a
Stage-0 inventory - "existing campaign traces/checkpoints (zero new
simulation) if the cachesim input streams are recoverable from retained
artifacts; otherwise regenerate streams" - and its Stage 0 (`:37`) defers
that determination.

**RQ5 settles C8 for itself and partially unblocks Fig 5.** RQ5 does not
depend on recovering campaign streams at all: it generates and retains its
own corpus, so the "otherwise regenerate" branch is taken by construction
and costs what the cost section below says. Building the consumer here hands
Fig 5 the tool, its validation fixture (fig5 plan `:40`: a tiny synthetic
stream with known distances, plus a cross-check that the stack-distance CDF
predicts the LRU miss ratio at two capacities), and its output format.

**But the curves do not transfer, and the plan must not pretend they do.**
Fig 5 wants CDFs over *real* captures across five architectures
(fig5 plan C1, `:26`); RQ5's are over *synthetic* traces at one architecture
(`loas`). RQ5's G1 is not a substitute for Fig 5's panel. What transfers is
the tool and the definition. Q3 below asks whether to build it.

### Access-log sizing

8 bytes per demand reference (`access_log.h:36`). The widest run in the
0831 corpus was 4,995,072 L1 references = 40 MB (`access_log.h:36-38`), and
the header notes the driver deletes each log once consumed (`:38-40`).

For G1's grid, scaling from the calibration row's `l1_accesses = 2,454,656`
at a measured density of ~0.197:

| layer | L1 refs at d~0.197 (calibration row) | access log there | at d=1.00 |
|---|---|---|---|
| deep (`layer_08`) | 2,454,656 (measured) | 19.6 MB | ~98 MB |
| mid (`layer_05`) | not measured | - | - |
| shallow (`layer_01`) | not measured | - | - |

The mid and shallow figures are **not determinable from anything on disk**:
no committed cachesim row for those two layers was found in this checkout or
on the Lustre snapshot, so their `l1_accesses` is unknown until S3 produces
it. The deep layer is the largest footprint of the three, so 98 MB is a
reasonable per-log ceiling; at 3 layers x 9 densities x 5 samples that is
under 15 GB of transient scratch, deleted per case. Campaign-wide
access-logging would be ~45 TB, so this stays a bounded subset and is never
enabled on a WT500 wave.

## Compute cost

Grounded in measured numbers, with every extrapolation marked as one.

**Measured anchors:**

- cachesim replay, cacheA, VGG16 `layer_08`, one sample, real density
  ~0.197: `sim_wall_seconds = 1.737395` (the calibration row above).
- Weight-trace generation (stage 1) is the dominant cost and is linear in
  MAC cycles: **4.44 us per MAC cycle, range 4.15-4.84**
  (`zoo/fig2_hw_n_sweep/T1_perf_report.md:86`), fitted on the six-case table
  at `:70-77`. The model is restated at `:183` as
  "baseline stage 1 = 4.44 us x `count_cycles`". The fit's own caveat is at
  `:249`: six points spanning 132 K-3.6 M MAC cycles.
- nocsim itself is **negligible**: 0.004-0.042 s per case, "under 2 % of the
  total" (`T1_perf_report.md:90`). This plan runs no nocsim; the figure is
  included because it is what makes the spad arm expensive - its cost is the
  generation in front of it, not the simulation - and that is the claim the
  arms section rests on.
- One retained `.wcts`, VGG16 `layer_08`, 16 cores, one sample:
  **72,753,392 bytes** (`zoo/concat_vs_khkw/provenance.json`, first
  `streams` entry, with `tiles: 128`).

**Extrapolations, marked as such.** Both generation and replay scale
approximately linearly with the spike count, hence with density. Writing
`D = sum of the grid = 1.00 + 0.70 + 0.50 + 0.35 + 0.25 + 0.15 + 0.10 +
0.05 + 0.02 = 3.12`, a whole-grid pass costs `(D / d_ref)` times a single
run at the reference density `d_ref = 0.197`, i.e. **15.8x** one reference
run per (layer, sample).

- **Cache replay**: 1.74 s x 15.8 = ~27 s per (layer, sample) for the whole
  grid. One arm (cacheA) x 3 layers x 5 samples = 27 x 15 = ~405 s,
  **~7 CPU-minutes**. Shallow and mid are smaller than deep, so this is an
  over-estimate.
- **Trace generation**: the per-layer MAC-cycle count is **not recorded in
  any CSV or doc in the tree** for these three layers, so the 4.44 us model
  cannot be applied exactly. Bounding it from the stream size instead: the
  T1 table's largest case is 3.58 M MAC cycles producing a 100.2 MB
  `out.bin` at 16.5 s of stage 1 (`T1_perf_report.md:72`), and our deep
  stream is 72.8 MB at the reference density - the same order. Taking
  ~12 s per reference-density generation and scaling by 15.8:
  12 x 15.8 = ~190 s per (layer, sample) for the whole grid, x 3 layers x 5
  samples = 190 x 15 = 2,850 s = **~0.8 CPU-hours**. (The 15.8x whole-grid
  factor is already inside the 190 s; it is applied once, not again at the
  15-task level.) This is the plan's dominant cost and it is the number S0
  must replace with a measurement on the first generated trace before S2
  commits.
- **Corpus size on disk**: 72.8 MB at d=0.197 scales to ~370 MB at d=1.00
  for the deep layer; summed over the grid, ~1.15 GB per (deep layer,
  sample), x 5 samples = ~5.8 GB. Shallow and mid are smaller but not by a
  fixed factor (shallow has 64x the spatial positions - 32x32 = 1,024 against
  4x4 = 16 - and 1/64 the channel pairs). Budget **10-25 GB** for the corpus, gzipped less. Well inside
  quota, and retainable - which is the whole point of owning it.
- **Energy staging (archx `snn_edp`)**: **not determinable** - no per-layer
  wall time for the pricing stage is recorded in any doc or CSV in the tree.

**Headline: RQ5 is login-scale.** ~0.8 CPU-hours of generation and
~7 CPU-minutes of replay, with modest parallelism across the 135 (layer,
density, sample) tasks. No Stokes submission is required. The expensive
item is Q3 - the Mattson consumer has to be written before G1 exists at all -
not the compute.

## Execution chain

Each stage names its gate. Nothing after S0 runs until boss answers the
blocking questions.

- **S0 - snapshot, settle, and price.** Snapshot `arch.yaml`, the three
  schedule JSONs, and the `layer_shapes.md` rows into
  `zoo/sensitivity/configs/`, with SHA256s. Reconstruct `cache_a.json` and
  `cache_b.json` from the echoed config columns of the committed row (they
  are not in this checkout; the root `.gitignore` ignores `*.json`) and
  record their hashes. Generate **one** synthetic trace - deep layer,
  d = 0.197, sample 0 - end to end and **measure**: stage-1 wall time, MAC
  cycles, `.wcts` bytes, cachesim `sim_wall_seconds`, `l1_accesses`,
  `max_wait_depth`, access-log bytes. Replace every extrapolated number in
  the cost section with that measurement.
  **Gate**: if measured cost is more than 2x the estimate above, re-scope
  the grid or the sample count before S2.
  Cost: ~1 hour, login node.
- **S1 - real-density pass.** For each of the 13 VGG16 captured layers and
  samples 0-9, compute `np.count_nonzero(x)/x.size` and commit
  `outputs/real_density.csv`. This produces the shaded real band on G2 and
  the overlay points, and it replaces the planning-time measurements quoted
  above with committed ones. Minutes, no simulation.
- **S2 - generate the corpus.** `gen_synth_inputs.py` writes 9 synthetic
  trace dirs (one per density); `build_corpus.py` drives
  `weight_trace_gen --stream --dump-trace` over 3 layers x 9 densities x S
  samples, hashing each stream into `provenance.json`.
  **Gate**: every realized density must match its target within the
  tolerance S2 asserts, and every `check_schedule_matches_trace` must pass.
  A failure here means the synthetic `meta.json` is malformed and nothing
  downstream is meaningful.
- **S3 - replay.** For each retained stream: `cachesim_run` under **cacheA
  only** (see "The arms"), with `--access-log` on every run. No cacheB
  replay and no nocsim spad run: neither appears in either figure, and
  pricing them would be work with no consumer.
  **Gate**: refuse any row with `max_wait_depth != 0`, because the access
  log's re-triage caveat (`access_log.h:29-34`) makes the reuse-distance
  histogram incorrect when anything blocks. Also assert
  `l2_accesses << l1_accesses` on the cacheA rows, to confirm the
  prefetch-merge behaviour described above still holds at synthetic
  densities - if it stops holding at the sparse end, that is itself a
  finding and G2's caption changes.
- **S4 - reuse distance + real validation.** Consume each access log with
  `mattson.py`, emit `outputs/reuse_cdf.csv`, delete the log. Then run the
  *real* `.npy` of each of the three layers through the identical chain at
  its own measured density and emit its CDF as the dashed validation curve.
  **Gate**: boss decides (Q6) whether the validation curve ships in the
  figure or only in the text.
- **S5 - aggregate.** `outputs/sensitivity.csv`, one row per
  (layer, density, arm, sample) with `total_cycles`, `tick_base_total`,
  `stretch_cycles`, `dram_bytes`, `l1_hit_rate`, `l2_accesses`, and the
  realized density; plus `outputs/reuse_cdf.csv`.
- **S6 - plot.** `plot.py` renders the two figures described below.
- **S7 - paper integration.** Only after figure sign-off: the two floats,
  their captions, the rewrite of `:213-218` (Q8) and the resolution of the
  `\todo` at `:211`.

**Standing gates**: Q1 and Q2 are closed, so nothing blocks S0 or S1. The
user answers **Q4, Q5 and Q7** before S2, because they fix the corpus the
later stages consume (grid and conditioning density, realization, sample
count); **Q3** is an implementation prerequisite that must be built before
S4; **Q6, Q9, Q11 and Q12** can be answered at figure sign-off, since they
change what is drawn rather than what is generated; **Q8 and Q10** are prose
and gate S7 only. Archie reviews every implementation commit; figure
sign-off before any paper edit.

## Figure form, and why

**Decision: two separate single-column figures, not one two-panel float.**

Justification:

- **They share nothing that a shared float would exploit.** G1's y is a
  cumulative fraction in [0, 1] over an x of reuse distance in lines on a
  log axis. G2's y is a dimensionless performance ratio over an x of
  density, linear and **reversed**. No axis, no unit and no scale is common. A two-panel float
  would assert a visual pairing that the encodings contradict, and its
  single caption would have to describe two unrelated readings.
- **They answer different sentences, in different places.** G1 resolves the
  `\todo{analyze reuse distance?}` at `08_evaluation.tex:211`, which sits
  above both paragraphs and is scoped to the whole subsection. G2 answers
  "Sparsity." at `:217-218`. A combined
  float would be referenced twice with half of it irrelevant each time.
- **Float pressure.** Both fit a single column. In the ACM two-column
  layout two single-column floats place far more freely than one
  `figure*`, and RQ5 is the last subsection, where placement is worst.

**G1 - reuse-distance CDF, tied to performance.**

- x: reuse distance in unique 64 B lines, log scale.
- y: cumulative fraction of **non-cold** references, 0 to 1. Monotone
  non-decreasing, drawn as a step curve (it is an empirical CDF over integer
  distances, and a smooth line would misrepresent it).
- One curve per swept layer - shallow, mid, deep - distinguished by both
  colour and dash pattern, each labelled with its real layer name and shape.
- **Each legend entry carries that layer's measured performance**, as
  `1 / T_s` in inferences/s with the raw `total_cycles` beside it, so the
  reader checks CDF shape against performance without leaving the figure.
  This is why G1 is one graph rather than a CDF panel plus a performance
  panel.
- Two vertical capacity rules: **L1 = 256 lines** (16,384 B / 64 B) and
  **L2 = 8,192 lines** (524,288 B / 64 B), both from the operating-point
  config above. A reader then reads "X % of reuses fit in L1" straight off
  the curve, which is the one number the panel exists to deliver - and the
  legend's performance number is what that fraction is supposed to predict.
- Cold-reference fraction per layer in the legend, since it is the
  compulsory-traffic floor and is excluded from the plotted y.
- **Conditioning density: propose `d = 0.15`**, the grid point nearest the
  three layers' measured mean real input density (0.1424 / 0.1669 / 0.1968,
  mean 0.169). The caption must state it, because the CDF is drawn at one
  grid point and is not density-invariant. Part of Q4.

**The alternative reading of G1, recorded for the user.**
"Across swept VGG16 layers" admits two readings, and they differ in how many
curves the panel holds:

- *(drawn)* the **three representative layers** this plan's synthetic corpus
  is built for, with per-layer performance in the legend. Three curves,
  legible, and every curve has a performance number that was actually
  measured on the same trace.
- *(alternative)* **all twelve replayable VGG16 convs**, giving a twelve-curve
  CDF fan ordered by depth, with performance encoded as a colour ramp rather
  than legend text. It shows the depth trend continuously instead of at
  three points, but it needs a synthetic corpus nine layers wider - the
  generation cost scales with it - and twelve step curves on one log axis
  overlap badly in the 10-100 line range where they differ most.

This plan draws the three-curve reading. **Q11** below puts the
twelve-layer alternative to the user.

**G2 - performance change across the downward density sweep.**

- **One panel, three curves**, one per layer type (shallow / mid / deep).
  `cacheA` only; no `spad`, no `cacheB` (see "The arms", decided).
- x: density, **decreasing left to right** (1.00 at the left, 0.02 at the
  right). This is the user's "drop down" and it is also the right reading
  order: the left edge is the degenerate dense limit where spike-gating buys
  nothing, and the eye travels into the regime the design is for.
- y: **performance change**, `performance(d) / performance(d = 1.00)` for
  that same layer, as defined in the counter-exact section. The three layers
  share one axis only because of that per-layer normalization; on absolute
  cycle counts they differ by more than an order of magnitude.
- A horizontal rule at 1.0 labelled "dense anchor", which every curve starts
  on by construction. That the curves *start* together is the normalization,
  not a result; the caption must say so, or a reader credits the figure with
  an agreement it built in.
- **Lines and markers, never bars.** Nine density points per layer is a
  curve, not nine categories, and the x-axis is ordered and continuous.
- A shaded span marking the **measured real density band** for each layer,
  so interpolation and extrapolation are visually distinct.
- The **stretch-only companion series** as a lighter dashed line per layer,
  for the reason given in the definitions: without it a rising performance
  curve cannot be attributed to the memory system rather than to there being
  less work. Q12 asks whether it ships in the figure or only in the CSV; the
  mock draws it for the deep layer alone, to show the encoding without
  doubling the curve count.

**Rejected alternatives:**

- *One two-panel figure sharing a y-axis.* Impossible: one y is a
  probability, the other a dimensionless performance ratio.
- *G2 as grouped bars per density.* Rejected: the x-axis is ordered and
  continuous, so nine densities are a curve rather than nine categories, and
  27 bars would carry what 3 curves carry. (Note the companion RQ4 figure
  *is* a bar chart - correctly, because its x-axis is an unordered list of
  named configs. The two figures differ in form because their x-axes differ
  in kind, not by inconsistency.)
- *G2 with density increasing left to right.* Rejected: it reverses the
  user's framing, and it puts the degenerate d = 1 anchor on the right,
  which makes the figure read as converging to triviality rather than
  departing from it.
- *G1 as a histogram or PDF of reuse distance.* Rejected: the question a
  reader brings is "what fraction fits in this capacity", which a CDF
  answers by intersection with a vertical rule. A PDF requires integration
  by eye.
- *G1 with one curve per (layer, density).* 27 curves. The density
  conditioning goes in the caption; a sparse-end companion panel is an
  appendix figure if anyone asks.
- *A gap ratio `spad / cacheA` as G2's y.* Rejected on two grounds: there
  is no spad arm on the chart, and a ratio-of-arms y hides whether a moving
  curve is the cache improving or the other arm degrading - at a controlled
  density that distinction is the result. The ratio is reported in the
  companion CSV and quoted in the text.
- *Raw `total_cycles` as G2's y.* Rejected: three layers whose absolute
  cycle counts differ by more than an order of magnitude cannot share one
  panel on a raw axis, and the per-layer normalization is exactly what makes
  one panel legible.

**The mock.** `sensitivity_mock.py` renders **both figures into one PNG/PDF
for review convenience only**. The two panels in that file ship as two
separate `\begin{figure}` floats; the mock's side-by-side layout is not the
proposed float structure, and the mock says so in its own title. Every
plotted number in it is invented; every layer name, shape and capacity rule
is real.

## Open questions

**Closed by user decision** (recorded so they are not relitigated):

- **Q1 - CLOSED.** G2's arm set: **cacheA only**, three curves = the three
  layer types. No spad, no cacheB. Recorded for the user, not reopened: the
  scratchpad was the only arm whose curve would have a *different shape*
  rather than a different offset, so the figure does not show on its own
  that a non-cache design fails to improve with sparsity. Propose carrying
  that with a caption cross-reference to RQ3's `fig:eval-spad-cache`
  (`08_evaluation.tex:194-200`), or adding the spad curve back as a single
  dashed reference line if the user wants it on the chart after all.
- **Q2 - CLOSED.** Capacities: keep the 16 KiB L1 / 512 KiB L2 cacheA
  operating point, matching the same decision in
  `zoo/cache_dse/docs/plan.md`. With no spad on G2 the mismatch against the
  scratchpad's 32 KiB / 2 MiB does not gate the figure.
- **Q3 - an implementation prerequisite, not a plan blocker.** The Mattson
  consumer that turns an access log into a reuse-distance distribution does
  not exist and must be written; G1 cannot be produced without it. It blocks
  **implementation**, not this plan or its mock, and it is the first item of
  S-stage work.

**Open:**

- **Q4.** The density grid and G1's conditioning density. Propose the
  nine-point grid as listed and `d = 0.15` for G1, the grid point nearest
  the three layers' measured mean real density (0.169).
- **Q5.** Synthetic spike realization: exact-count or Bernoulli? Propose
  **exact-count**. The arithmetic in "The density grid" gives a Bernoulli
  realized-density error of 0.46 / 0.93 / 1.3 % for the shallow / mid / deep
  layers at `d = 0.15` - small, but it is noise injected into the one factor
  this experiment exists to control, and it is worst on the deep layer,
  which has the fewest spike sites and the most interesting cache
  behaviour.
- **Q6.** Does the real-capture validation curve ship inside G1, or only in
  the companion CSV? Propose shipping it: it is the only evidence in the
  figure that the synthetic traces resemble real ones. Shipping all three
  doubles G1's curve count, so the mock draws it for the **deep layer
  alone**, thin and dashed, to show the encoding without committing to it -
  the same device G2 uses for the stretch-only series.
- **Q7.** Sample count. Propose **S = 5** per (layer, density), matching the
  companion RQ4 plan.
- **Q8 (prose).** `08_evaluation.tex:213-215` ("Layer size") promises a
  sweep of input channels, output channels and output spatial size across
  VGG16 *and ResNet19*; `:217-219` ("Sparsity") compares "representative"
  and "dense" layers from a Methodology section that does not define those
  terms. Neither describes the amended figures. **Propose rewriting both.**
- **Q9.** Two separate single-column floats (proposed) or one `figure*`?
  The two graphs share no axis, no unit and no scale, and they answer
  different sentences in different places, so propose two.
- **Q10 (prose, BLOCKING for the paper, not for the plan).**
  `08_evaluation.tex:221` commits RQ5 to "the gap between the scratchpad and
  the cache in off-chip traffic, latency, and energy". The amended figures
  have no scratchpad, report performance rather than latency, and report
  neither traffic nor energy. That sentence cannot stand as written. Propose
  replacing it with a performance-and-reuse-distance commitment and moving
  the traffic/energy gap to the companion CSV and RQ3's figure. The figures
  follow the user; this is only a question about the prose.
- **Q11.** G1's layer set: the three representative layers with per-layer
  performance in the legend (drawn), or all twelve replayable VGG16 convs as
  a depth-ordered fan with performance as a colour ramp? The twelve-curve
  reading shows the depth trend continuously but needs a corpus nine layers
  wider and overlaps badly where the curves differ most. **Propose three.**
- **Q12.** Does the stretch-only companion series ship in G2, or only in the
  CSV? Without it a rising performance curve cannot be attributed to the
  memory system rather than to a sparser trace having less work in it; with
  it, the curve count doubles. **Propose shipping it for all three layers**
  and accepting six lines; the mock draws it for the deep layer only, to
  show the encoding.

## Things this plan could not determine

- **Per-layer MAC-cycle counts** for `layer_01_core_features_3` and
  `layer_05_core_features_17` under the campaign `loas` schedule. Not
  recorded in any CSV or doc in the tree, so the 4.44 us/MAC-cycle model
  cannot be applied to them exactly. S0 measures them.
- **`l1_accesses` for the shallow and mid layers.** No committed cachesim
  row for either was found in this checkout or on the Lustre snapshot, so
  their access-log sizes are extrapolated from the deep layer only.
- **archx `snn_edp` staging wall time.** Not recorded anywhere.
- **Whether the synthetic reuse-distance CDF resembles the real one.**
  Unknowable before S4 runs; the plan's answer is to measure it, not to
  assume it.
