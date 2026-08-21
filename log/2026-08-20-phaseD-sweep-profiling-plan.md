# 2026-08-20 Phase D Sweep-Profiling Campaign Plan

Status: **PLAN ONLY. Structure approved 2026-08-20; still no execution and
no Phase D code.** This is the experiment plan for the
spad-versus-cache compute-latency campaign that Phase D of
`log/2026-08-17-wcache-event-driven-plan-v3.md` is expected to carry. It
does not modify that plan; it assesses whether that plan accommodates
this campaign, and says where it does not.

Scope boundary: this document specifies **what to run and why**. It
specifies no harness code, no sweep script, no config generator and no
Phase D implementation. Section 9 *describes* the results-collection
design; it does not implement it.

## Revision 2026-08-20 (user review)

The user read the plan as first written and issued five rulings (R1-R5);
a second pass the same day added two more (R6-R7). All seven are applied
below; this block is the index of what each one moved, so a later reader
can tell a ruled number from an original one.

| # | Ruling | Where it lands |
|---|---|---|
| R1 | **U27 ruled: the burst axis and stride ARE needed and belong in the trace format, emitted by the trace-generation side, not supplied by the reader.** `burst_dim` and `burst_stride` join the stream header beside `n_cores` and `spatial_factors`. One header settles U25-U28 together. Status: **ruled, implementation pending**; no code or C++ header was touched by this revision. | §10.4, §10.8 (Q11 now **resolved: yes**), and the U27 row in `PROGRESS.md` |
| R2 | **Q1 resolved: the spad L1 is 32 KB PER CORE at every core count** (so the aggregate scales with the core count), and the spad L2 stays 4 MB shared. The **L1 cache axis changes to {2, 4, 8, 16, 32} KB**, replacing {16, 32, 64} KB. | §0, §2, §3.3, §4.2, §4.3, §4.4, new §4.5, §8, §9.3, §10.5, §11 Q1. Every downstream count is recomputed with its arithmetic shown. |
| R3 | **G5 correction: the `COUT: {spatial: 4}` cap in `configs/dataflow/{loas,ptb}.yaml` is INTRA-NODE** - four output channels handled spatially *inside one node's PE array* - **not** an inter-node distribution limit. The 4-core MIP-infeasibility concern was a misreading and is **withdrawn**, along with the matching half of Q2. 4 / 16 / 64 cores stand. | §1.3 G5, §8.2 Stage 0, §11 Q2 |
| R4 | **The in-flight / no-intermediate-storage requirement is confirmed as the user's own.** The concern is the JSON round trip and the staleness risk, not disk. An **opt-in debug dump is acceptable**. §10's recommended design (Option B pipe + broadcast lockstep + stream header) stands as recommended. | §10.8 Q9 and Q10 both **resolved** |
| R5 | **The staged tier plan is approved in structure.** Tier 0 through Tier 4 keep their roles; only the counts are recomputed against the 180-config grid. | §4.4 |
| R6 | **G14 resolved: the L1 axis {2, 4, 8, 16, 32} KB STANDS as designed.** The sweep cannot be sized for layer 1 alone - the hardware is fixed and has to serve several different layers, so the axis is sized for the machine across the workload mix, and a flat L1 curve on shallow layers is an acceptable finding, not a defect. Consequence: the per-core per-tile distinct-address histogram is **demoted from an axis-siting gate to an explanatory diagnostic** - still folded into Stage 1 (it is free and it explains the curves per architecture), but it no longer gates Tier 2 and its outcome does not change the axis. | §1.3 G14 (status), §3.3 cross-reference, §8.2 Stage 1 |
| R7 | **Execution hosts confirmed.** CECSUnaryLab runs demo and smoke runs only - build, tests, fixture-slice runs, single-point sanity checks. The full campaign (all tiers, trace generation, MIP solves at scale) runs on **NCSA Delta**; **no campaign tier runs locally**. A local demo run over a few configs on the `examples/` fixture slices is the pre-Delta smoke test that precedes Tier 0. | §8.1 |

**Left open on purpose, and this revision did not touch them:** Q3 (layer
picks - reassessed under R2 in §3.3, but the pick itself stays the user's
call), Q4 (`l1_mshrs` 16 or 4), Q5 (prefetch figure of merit), Q6 (Q13
grid merge), Q7 (keep or drop nocsim), Q8 (`l2_demand_reserve`).

**One new gap the axis change exposed, now closed:** G14 in §1.3 - the L1
axis may not cross a working-set edge on the shallow layers. **Resolved
by R6: the axis stands**, and the cheap measurement stays as a
diagnostic that explains the curves rather than as a gate on Tier 2.

---

## 0. Summary of the request

| Axis | Values | Kind |
|---|---|---|
| Architecture | LoAS, PTB, Spinalflow | shared |
| Core count | 4, 16, 64 | shared |
| Workload | 2 VGG16 conv layers + 2 ResNet-19 conv layers | shared |
| Spad baseline | L1 **32 KB per core** (128 / 512 / 2048 KB aggregate at 4 / 16 / 64 cores), L2 4 MB shared (fixed) | baseline arm |
| L1 cache size | **2 / 4 / 8 / 16 / 32 KB** (per core) | cache arm |
| Cache line size | 16 / 32 / 64 B, as 16 cout x {1,2,4} cin | cache arm |
| L2 cache size | 256 / 512 / 1024 KB | cache arm |
| Prefetch distance | chosen here: 0 / 2 / 4 / 8 (+16 in the ridge) | cache arm |
| L1/L2 MSHRs, targets/MSHR | gem5 defaults, with one deviation (§6) | fixed |
| L1/L2 miss penalty | eDRAM-derived (§7) | fixed |

Pipeline per configuration: MIP solver produces the schedule ->
`archmodels` generates the weight trace -> `nocsim` gives the spad
compute latency -> `wcache` gives the cache compute latency.

Added 2026-08-20: weight-trace generation must be **in flight, with no
intermediate storage**. §10 assesses that requirement in full.

---

## 1. Assessment of the existing Phase D plan

### 1.1 What Phase D actually says

v3 defines Phase D as three engineering units
(`log/2026-08-17-wcache-event-driven-plan-v3.md:1358-1364`):

- **D1** - "Config load + validation (N7, N11, N13, N14, N15, N16, G1),
  single source of truth for the parameter set", plus `core_accept_ii`,
  `prefetch_policy`, `prefetch_distance`, `l1_demand_reserve`,
  `l2_demand_reserve`.
- **D2** - "Statistics and the results CSV". Exit: "every stat in Part 8
  emitted, one row per config".
- **D3** - "Sweep driver". Exit: "a full grid point runs end to end and
  reproduces byte-identically".

Entry condition (`:1366-1368`): "**All of Phase D depends on C2**". C2 is
done; the Phase C gate passed 2026-08-18.

### 1.2 Verdict

**Phase D as written is the right container but it is not this campaign.**
D1/D2/D3 are the three pieces of machinery a campaign needs, and they are
correctly scoped as machinery. What v3 never does is *name a campaign*: it
lists no architectures, no workloads, no core counts and no cache sizes.
The only grids v3 contains are a different study - `l1_mshrs` x
`prefetch_distance` (Q13, `:1586-1589`) with sizes held fixed. This
campaign is its mirror image: sizes swept, MSHRs held fixed. Nothing in
v3 reconciles the two.

So the answer to "does the existing Phase D plan accommodate this sweep"
is: **the interfaces do, the specification does not, and four things
are outright missing.**

### 1.3 Gaps, in priority order

**G1 - blocking: plan unit A3 (`TraceReader`) does not exist.**
`src/wcache/PROGRESS.md:63` marks A3 `-` in every column. Only an abstract
`trace.h` plus `FakeTrace` stand-ins exist. The engine today runs from C++
test fixtures on synthetic traces and **cannot read a real weight trace**.
A3 is not in Phase D and is not on v3's stated critical path
(`A1 -> A2 -> A4 -> A5 -> gate -> B3 -> C1 -> C2 -> C3`, `:1366`), which
omits it entirely. Nothing in this campaign can run until A3 lands.

**G2 - blocking: there is no program.** `src/wcache/native/src/` has no
`main.cpp`, no config loader and no CSV writer. The CLI shape
(`wcache_run --config cfg.json --trace sample.json.gz`,
`wcache_sweep --config-grid grid.json`) is from
`log/2026-08-05-cachesim-redesign-plan.md:535` and was never carried into
v3's Phase D. D1+D2+D3 must build all three.

**G3 - the headline metric is undefined.** Part 8 (`:1417-1471`) reports
`core_stall`, `fetch_latency`, per-tile stretch, stall attribution,
prefetch states and model health. It does **not** define a per-layer
makespan / `total_cycles` column. That column is exactly what a
spad-versus-cache latency comparison compares. D2 must add it.

**G4 - `l2_latency` and `l2_miss_latency` have no values.**
`:361-363` marks both "*(to set)*"; `PROGRESS.md:740` defers them "to be
set before D3". This campaign is what forces the decision. §7 proposes
values.

**G5 - 4 cores is outside the settled range and has no config.**
**Half of this gap is WITHDRAWN 2026-08-20 by the user's R3 ruling.** What
was written here first said that `configs/dataflow/loas.yaml` and
`ptb.yaml` cap `COUT` at `{spatial: 4}` and that 4-core MIP feasibility
was therefore in doubt. **That was a misreading.** The cap is
**intra-node**: `loas.yaml`'s own comment says "One TPPE handles each
spatial output channel", i.e. four output channels are handled spatially
*inside one node's PE array*. It says nothing about how many nodes exist
or how work is distributed between them. There is no MIP-infeasibility
argument against 4 cores, and none is made here any more. **4 / 16 / 64
cores stand.**

What survives, and it is all still true:

- `PROGRESS.md:738`: "**settled 2026-08-17**: **8 to 256**". 4 is below
  that range. Keeping it is a **deliberate exception the user chose**,
  not an oversight, and the write-up should say so rather than let a
  reader discover the inconsistency.
- The generated arch grid (`scripts/tmp/generate_multinode_arch_sweep.py`)
  uses `INSTANCE_COUNTS = (16, 64, 256, 1024)`; **there is no 4-core arch
  file**, so one must be produced before Stage 0.
- **The 4-core third is the expensive third.** Fewer cores means more
  ticks per sample (316,280 ticks at 16 cores against 7,158 at 1024,
  `log/2026-08-05-cachesim-redesign-plan.md:88-92`), so the 4-core
  tracegen and simulation cost is roughly **4x the 16-core third**. That
  is an extrapolation from the tick-scaling row, not a measurement.

**G6 - the trace does not record the machine size, the spatial factors,
the burst axis or the stride.** U25 (`PROGRESS.md:948`): "**Nothing on
disk states the machine's core count**". U26 (`:949`): "**`spatial_factors`
is not in the trace file.**" U27 (`:950`): the burst axis and stride are
in no trace file either. U28 (`:951`): the address tuple has no declared
field order.

**RULED 2026-08-20 (R1), for U27 and by extension for all four.** The
burst axis and stride **are** needed and **belong in the trace format,
emitted by the trace-generation side**, not supplied by the reader. So
`burst_dim` and `burst_stride` join `n_cores` and `spatial_factors` (and
U28's field-order declaration) in **one stream header**. This closes the
"reader supplies them" branch that `types.h` and `layout.h` currently
name after B161's comment correction; those two comments will need
updating when the header lands, which is implementation work and is
**not** done by this revision.

The reasoning that made this the cheap moment is unchanged and is now
also the user's: this campaign regenerates the whole corpus for 4/16/64
cores regardless, so the regeneration cost is already being paid; the
alternative makes A3 depend on a Python schedule decode it cannot reach;
and §10's stream design **forces** a header to exist anyway, because a
stream with no header is unreadable. Status: **ruled, implementation
pending in A3 plus `tracegen.py`.**

**G7 - the prefetch axis currently has no metric.** U19 (`:869`) measured
`core_stall - fetch_latency == 0` throughout, and `EXPLAIN.md:1170` says
"the prefetch study currently has no metric for the thing it exists to
measure, and picking the replacement is a D2 decision that should be made
before the grid runs". Two candidates are on the table (`fetch_latency`
against the `d = 0` baseline, or `served - fill_time` per burst) and
neither is chosen. Choose before Tier 2 runs.

**G8 - nocsim and wcache do not measure the same thing.**
`src/nocsim/sim.py:186` returns
`{total_cycles, unicast_cycles, multicast_cycles, count_cycles, dram_cycles}`
- a NoC-plus-DRAM transaction count driven by the schedule, with
`DRAM_LATENCY: 17` as a per-packet multiplier
(`configs/arch/loas.yaml`). wcache's latency is a self-timed core-stall
integral over an event-driven timing model. Putting them side by side as
"spad latency vs cache latency" compares two different quantities.
**Mitigation, and it is already in the plan:** v3 `:394-397` states that
at `l1_latency = 0` "**a 100% hit run reproduces the scratchpad timeline
exactly**", `tile_origin[N] == tick_base[N]`, which is invariant V1
(`:1380`). So the metric-matched spad baseline is computable **inside
wcache, from the trace alone, at zero simulation cost**. §2 uses that as
the primary baseline and keeps nocsim as an independent cross-check
rather than as the comparison arm.

**G9 - associativity is unspecified.** Neither the request nor v3 pins
L1/L2 associativity. The predecessor study swept three structures
(fully-associative, 32-way, 4-way; `log/2026-08-03-l1-l2-cache-policy-plan.md:45-46`).
It must be pinned here or the grid quadruples. §4.4 proposes a value.

**G10 - power-of-two aliasing is a live confound.**
`src/wcache/HANDOFF.md:190-192`: every layer is `KH=KW=3` with CIN and
COUT in {64,128,256,512}, "so every radix is a power of two, which is why
a strided walk aliases perfectly against a power-of-two set count rather
than degrading gracefully". A low-associativity choice under G9 will
produce conflict-miss pathologies that are an artifact of the layout, not
a cache result.

**G11 - `l2_demand_reserve` is dead.** `PROGRESS.md:950`, B159 `:1115`:
"D2 must not emit it and D1 must not offer it as a sweep dimension".
Accept-or-reject at config load is still an open coordinator call.

**G12 - the spad baseline was ambiguous. CLOSED 2026-08-20 by the user's
R2 ruling.** The question was whether the spad L1 was per-core or shared;
the two readings differed by about 64x in the storage-saving claim. The
ruling: **the spad L1 is 32 KB per core at every core count**, so the
aggregate scales with the core count (128 / 512 / 2048 KB at 4 / 16 / 64),
and the spad L2 is 4 MB shared. Note that the *figure* changed as well as
the reading: the 512 KB in the original request is gone, and 32 KB is
what the repo's own arch grid uses per node
(`scripts/tmp/generate_multinode_arch_sweep.py`, 2-32 KiB per node,
512 KiB-4 MiB shared). The consequences are large enough that they are
listed where they land rather than here: the L1 cache axis (§4.2), the
decision rule and the storage arithmetic (§2), the layer rationale (§3.3)
and every run count (§4.3, §4.4).

One casualty worth naming: the appendix row anchoring "512 KB / 4 MB" to
DaDianNao's 512 KB-per-tile input buffer **no longer anchors the L1
side**. The 4 MB shared L2 keeps its DaDianNao anchor - which also keeps
§7's `l2_latency = 10` from Table III's *central* 4 MB eDRAM intact - but
the 32 KB per-core L1 is anchored on this repo's own arch sweep instead.

**G13 - Phase D assumes traces live on disk, and the trace interface as
built is random-access.** The 08-05 contract is "a process boundary with
JSON on both sides... the back end binary takes a config JSON path and
**a trace path**" (`log/2026-08-05-cachesim-redesign-plan.md:534-536`),
and `trace.h`'s `TileTrace` is indexed by `(core, tile, k)` rather than
being a sequential pull. The in-flight requirement the user added on
2026-08-20 is therefore a change to plan unit A3's *shape*, not just to a
command-line flag. **§10 assesses it in full.** The short version: it is
feasible, A3 is unbuilt so nothing is being retrofitted, and a stream
header is the cheapest fix available for G6 and the three sibling format
gaps at the same time.

**G14 - NEW 2026-08-20, RESOLVED 2026-08-20 by the user's ruling R6:
nothing yet shows that the L1 axis crosses a working-set edge, and the
quantity that would show it has never been measured.** This gap was
exposed by R2, not created by it. **The axis stands as designed**; the
measurement below is kept as a diagnostic, not as a gate.

The plan as first written justified the L1 axis against **whole-layer
weight footprints** (36 / 72 / 1125 / 2304 KB). That is the wrong
quantity for a **per-core** L1. What an L1 sees is one core's distinct
weight addresses, and the machine-wide barrier (N4) means the natural
unit is **per core, per tile**.

Measured 2026-08-20 on the only real trace data in this worktree, the
two-tile fixture slices under `src/wcache/examples/` (8 cores, vgg16
`layer_01` / resnet19 `layer_01`):

| Arch / layer | distinct addresses per core per tile | bytes per core per tile | tile 0 ∩ tile 1, per core |
|---|---|---|---|
| loas vgg16 `layer_01` | 24 | **384 B** | 0-1 of 24 |
| spinalflow vgg16 `layer_01` | 24 | **384 B** | 0-1 of 24 |
| ptb resnet19 `layer_01` | 24 | **384 B** | 11-21 of 24 |

(Each address is `[kh, kw, cin, cout_start, cout_end]` spanning 16 COUT
at `weight_bytes = 1`, so 16 B.) Two things follow, and both are
uncomfortable:

1. **A tile's per-core working set is ~384 B on these layers, which is
   below even the smallest swept L1 (2 KB).** If that holds at the deep
   layers and the other core counts, the L1 axis will be **flat**: every
   swept size already holds a whole tile's per-core set, and the only
   capacity level doing work is the shared L2.
2. **Cross-tile reuse is architecture-dependent, not layer-dependent.**
   LoAS and Spinalflow carry essentially none (0-1 addresses of 24 shared
   between adjacent tiles), so L1 capacity beyond one tile buys nothing
   there. PTB carries a lot (11-21 of 24), so PTB is the architecture
   where an L1 knee is most likely to be visible at all.

**This is an argument in favour of R2, not against it.** The old
{16, 32, 64} KB axis was 40x to 170x the measured per-core tile set; the
new {2, 4, 8, 16, 32} KB axis reaches down to 5x it. The change makes an
L1 knee *more* likely to be observable, not less. But 5x is still above,
and nobody has checked the deep layers, where the per-tile set should be
far larger.

**RULED 2026-08-20 (R6): the axis stands, and the measurement is
demoted.** The user's rationale: the sweep cannot be sized for layer 1
alone. The hardware is fixed and has to serve several different layers,
so the L1 axis is sized for the *machine* across the workload mix, not
for whichever layer has the smallest per-core tile set. A **flat L1 curve
on the shallow layers is an acceptable finding, not a defect** - it is
the honest report that those layers already fit.

**What to do, and it is cheap.** The distinct-address count per (core,
tile) is a counting pass over the trace, and the trace is being generated
anyway. **Fold a per-core per-tile distinct-address histogram into Stage
1** (or into A3's stream reader, which already touches every burst). It
is now an **explanatory diagnostic**: it says, per architecture, *why*
each L1 curve has the shape it has - in particular the LoAS/Spinalflow
versus PTB cross-tile reuse difference in point 2 above. **It does not
gate Tier 2, and its outcome does not change the axis.**

Caveats on the table above, stated because they are severe: it is **two
tiles of one sample of one layer at one core count (8)**, from the
fixture corpus, not from the campaign's corpus - which does not exist in
this worktree at all (`outputs/weight_traces/` is absent; it lives on
Delta). Treat every number in it as an **indication**, not a measurement
of the campaign's workload.

---

## 2. The claim, the metric, and the decision rule

**Claim.** For weight streaming in LoAS, PTB and Spinalflow, a
conventional two-level cache of **2-32 KB per-core L1 and 256 KB-1 MB
shared L2** delivers compute latency close to a scratchpad of **32 KB per
core plus a 4 MB shared L2**, at a small fraction of the storage.

**What R2 did to the shape of this claim, stated plainly because it
changes what is being tested.** The cache L1 axis now **tops out at
exactly the spad's per-core L1** (32 KB = 32 KB), and every other swept
value is below it. So `l1_cache <= l1_spad` holds **by construction at
every point of the grid**. Three consequences:

- The storage saving is now almost entirely an **L2** saving: 4 MB down
  to 256 KB-1 MB, a 4x to 16x cut on a term that does not scale with the
  core count. The L1 term can only ever match the spad's, never beat it
  by more than the axis's own range.
- The `l1 = 32 KB` row becomes a **control worth its slot**: identical L1
  capacity, cheaper L2, everything else equal. Any latency it loses is
  attributable to the L2 and the memory system, not to L1 capacity.
- The claim is now a **strictly harder** one than the original. The old
  axis let the cache have 64 KB against an assumed-shared 512 KB; the new
  one never lets it have more L1 than the scratchpad has.

**Dependent variable.** `total_cycles`, the layer makespan: the cycle at
which the last core clears the last tile barrier. Units: simulated
cycles. This is the column D2 does not yet emit (G3).

**Derived headline.** `latency_ratio = total_cycles(cache) /
total_cycles(spad)`, paired on the same `(arch, n_cores, layer,
sample_idx)`.

**Three arms.**

| Arm | How it is produced | Role |
|---|---|---|
| `spad_oracle` | `tick_base` summed from the trace alone (V1, `:1380`) | the metric-matched baseline. Free: no simulation. |
| `spad_nocsim` | `python -m nocsim.sim --simulate`, `total_cycles` | independent cross-check on a different model (G8) |
| `cache` | wcache at the swept configuration | the measurement |

A fourth arm, `spad_wcache` - wcache run with **L1 = 32 KB per core**
(R2) and L2 = 4 MB, prefetch off - is worth including because it is the honest apples-to-apples
scratchpad: it pays the same MSHR, port and barrier costs the cache arm
pays, and any gap between it and `spad_oracle` is the cost of the memory
system rather than of the cache size.

**Decision rule, and the storage arithmetic behind it.** Both sides now
scale with the core count, so the rule has to be evaluated per core
count rather than once.

Spad storage `= n_cores * 32 KB + 4096 KB`:

```
 4 cores:    4 * 32 +  4096  =   128 +  4096  =  4224 KB   quarter =  1056 KB
16 cores:   16 * 32 +  4096  =   512 +  4096  =  4608 KB   quarter =  1152 KB
64 cores:   64 * 32 +  4096  =  2048 +  4096  =  6144 KB   quarter =  1536 KB
```

Cache storage `= n_cores * l1_KB + l2_KB`, `l1 in {2,4,8,16,32}`,
`l2 in {256,512,1024}`. The rule **survives**: at every core count there
are configurations under the quarter threshold, and the binding term is
always the L2.

```
64 cores, budget 1536 KB:   l1=2  ->  128 + l2   ->  all three l2 pass (max 1152)
                            l1=4  ->  256 + l2   ->  all three pass    (max 1280)
                            l1=8  ->  512 + l2   ->  all three pass    (max 1536, exactly at)
                            l1=16 -> 1024 + l2   ->  256 and 512 pass; 1024 gives 2048, fails
                            l1=32 -> 2048        ->  already over budget before any l2; all fail
16 cores, budget 1152 KB:   l1=2  ->   32 + l2   ->  all pass (max 1056)
                            l1=4  ->   64 + l2   ->  all pass (max 1088)
                            l1=8  ->  128 + l2   ->  all pass (max 1152, exactly at)
                            l1=16 ->  256 + l2   ->  256 and 512 pass; 1024 gives 1280, fails
                            l1=32 ->  512 + l2   ->  256 and 512 pass; 1024 gives 1536, fails
 4 cores, budget 1056 KB:   l1=2  ->    8 + l2   ->  all pass (max 1032)
                            l1=4  ->   16 + l2   ->  all pass (max 1040)
                            l1=8  ->   32 + l2   ->  all pass (max 1056, exactly at)
                            l1=16 ->   64 + l2   ->  256 and 512 pass; 1024 gives 1088, fails
                            l1=32 ->  128 + l2   ->  256 and 512 pass; 1024 gives 1152, fails
```

So: **the cache is a viable replacement if there exists at least one
cache configuration whose total storage is at most one quarter of the
spad's *at that core count*, with `latency_ratio <= 1.10` at every one of
the 36 (arch, cores, layer) points.** The threshold is unchanged; what
changed is that it must be read per core count, and that `l1 = 8 KB` sits
**exactly on** the quarter line at all three core counts with the largest
L2 - which is one of the two reasons 8 KB is the new nominal (§4.4).

It is **refuted** if `latency_ratio > 1.5` at the *largest* cache
configuration - now **32 KB / 1 MB**, best prefetch distance - for any
architecture. R2 makes this clause sharper than it was: at 32 KB the
cache has **exactly the scratchpad's per-core L1 capacity**, so a
refutation there cannot be blamed on L1 size. It isolates the L2 (4 MB
down to 1 MB), the associativity and the miss cost as the cause. That is
a better refutation condition than the old one, which compared 64 KB
against an ambiguous 512 KB.

**One thing the rule can no longer claim.** With `l1_cache <= l1_spad`
everywhere, a headline of the form "a quarter of the storage" is now
mostly a statement about the L2. Report the split - L1 term and L2 term
separately - rather than only the total, or a reader will reasonably ask
which level did the work.

**Minimum effect size.** A 10% latency difference. Below that the result
is "indistinguishable at this sample count" rather than a win.

**Statistical plan.** n = 5 samples, the same five CIFAR-10 images
(indices `[2697, 3078, 5110, 6367, 8502]`, `numpy.random.default_rng(0)`,
`input_trace/README.md`) across every layer, every architecture and every
arm. That makes every comparison **paired**: report the per-sample ratio
and its median plus full range, not a t-test - n = 5 does not support
one, and saying so is more honest than quoting a p-value. Variance is
expected to be small because the schedule is identical across samples and
only the input spike pattern differs; if the observed per-sample range
exceeds 5% of the median, raise n before drawing conclusions (the full
10,000-sample captures exist off-repo, `input_trace/README.md`).

**Determinism.** wcache must "reproduce byte-identically" (D3 exit,
`:1364`). Gurobi is not bit-reproducible across thread counts, so pin
`Threads=1` or - better, and already how `scripts/solve_schedules.py`
works - solve once, cache the schedule under `outputs/schedules/`, and
reuse it for every arm.

**Known-answer checks that must pass before any sweep row is trusted.**

1. **V1** (`:1380`): unbounded cache, `l1_latency = 0` ->
   `tile_origin[N] == tick_base[N]` for every tile, exactly. This is the
   calibration of the whole comparison.
2. **V27** (`:1409`): `l1_latency = 1`, everything else free, every
   access a hit -> the drift equals the trace-computed sum of per-tile
   maximum per-core burst counts.
3. **V21** (`:1402`): the stall breakdown sums to total stall, and
   `core_stall` sums to the tile stretch.
4. The four prefetch outcome states (timely / late / wasted / dropped,
   `:1445-1449`) sum to prefetches issued.
5. `padding_fraction == 0` for all four chosen layers - they divide
   exactly (§3), so a nonzero value means the address mapper is wrong.
6. Q13's duplicate check (`:1592-1595`): a prefetch distance above the
   budget must reproduce the last in-budget point *exactly*. This
   campaign gets that check for free from `d = 16` (§5).

---

## 3. Workload layers

### 3.1 What actually exists

There is no per-network workload YAML in the repo. `src/archmodels/trace.py`
derives the problem from trace metadata: `KH = KW = 3`, stride 1, pad 1,
so `HO = Hin`, `WO = Win`, and `COUT` is the next layer's `CIN` (the last
layer falls back to its own `CIN`). Ground truth is
`input_trace/loas/{vgg16_T4_n5,resnet19_T4_n5}/`: CIFAR-10, `T = 4`,
uint8 spikes, shapes `[T, B, Cin, Hin, Win]`. VGG16 has 12 conv layers,
ResNet-19 has 19 (including three `shortcut_0` layers, which the blanket
`KH = KW = 3` assumption treats as 3x3).

### 3.2 The four chosen layers

Weight footprint at `BW_WEIGHT: 8` (`configs/arch/loas.yaml`), i.e. 1
byte per weight, is `9 * CIN * COUT` bytes.

| Pick | Layer | CIN | COUT | HxW | Weights | Where it sits (against the **shared L2** axis) |
|---|---|---|---|---|---|---|
| VGG16 shallow | `layer_01_features_3` | 64 | 64 | 32x32 | **36 KB** | well inside every L2 |
| ResNet-19 shallow | `layer_01_layer1_0_conv1` | 64 | 128 | 32x32 | **72 KB** | well inside every L2 |
| ResNet-19 deep | `layer_16_layer3_0_conv2` | 512 | 256 | 4x4 | **1125 KB** | *straddles the top of the L2 axis*: just above 1024 KB |
| VGG16 deep | `layer_09_features_30` | 512 | 512 | 4x4 | **2304 KB** | above every L2, inside the 4 MB spad |

The "where it sits" column is now stated **against the L2 only**. Under
R2 the L1 axis tops out at 32 KB, which is below all four footprints, so
a whole-layer footprint says nothing about the L1 axis any more. What
does speak to the L1 axis is the *per-core* working set, and §3.3 handles
it separately.

### 3.3 Why these four - REWORKED 2026-08-20 under R2

**Outcome: the four layers are RE-JUSTIFIED, not swapped.** But one of
the two original reasons is dead and its replacement rests on an
estimate, so the reasoning is set out in full rather than asserted.

**What R2 killed.** The original argument was that the four footprints
bracket the capacity boundaries of *both* swept axes, and that
"36 KB sits inside the L1 sweep, so the L1 axis crosses a real
working-set edge exactly once". With the L1 axis now {2, 4, 8, 16, 32} KB,
**36 KB is above every swept L1**, and so are 72, 1125 and 2304. The
36 KB layer no longer straddles anything on the L1 axis. That half of the
argument is struck.

**What survives untouched: the L2 half.** The L2 is shared and sees the
whole layer, so the footprint column is exactly the right quantity there,
and the bracketing is as good as it was: 36 and 72 KB fit entirely
(the "cache holds everything" regime), 1125 KB straddles the 1024 KB
ceiling, 2304 KB is above every L2 but inside the 4 MB spad (the
"streaming" regime). Four layers, three distinct L2 regimes, one of them
straddling. Nothing about R2 touches this, and it is the axis where the
storage saving now lives (§2), so it is the axis that most needed good
bracketing.

**The replacement for the L1 half, and it is weaker than what it
replaces.** For a per-core L1 the relevant quantity is the **per-core
working set**, which is bounded below by `footprint / n_cores` (cores
partition the weights perfectly) and above by `footprint` (every core
touches every weight). Measured on the fixture slices, neither bound
holds: at 8 cores on vgg16 `layer_01`, per-core distinct addresses are
47-48 against a union of 117, so cores **overlap heavily but are not
identical** - roughly 40% of the union each. The lower bound is therefore
badly wrong and the upper bound is loose.

Taking `footprint / n_cores` as the optimistic bound anyway, purely to
see whether the axis is plausibly crossed:

```
per-core weight slice = footprint / n_cores   (LOWER BOUND, ESTIMATE)

layer                       footprint   /4      /16      /64
vgg16   layer_01  (64x64)      36 KB     9 KB    2.25 KB   0.56 KB
resnet19 layer_01 (64x128)     72 KB    18 KB    4.5  KB   1.13 KB
resnet19 layer_16 (512x256)  1125 KB   281 KB   70    KB  17.6   KB
vgg16   layer_09  (512x512)  2304 KB   576 KB  144    KB  36     KB
```

Twelve (layer, core count) points spanning 0.56 KB to 576 KB. They cross
**every** point of the new axis: 2 KB is crossed between resnet19
`layer_01`@64 (1.13) and vgg16 `layer_01`@16 (2.25); 8 KB by vgg16
`layer_01`@4 (9); 16 KB by resnet19 `layer_16`@64 (17.6) and resnet19
`layer_01`@4 (18); and 32 KB by vgg16 `layer_09`@64 (36 - the same 36 KB
number as before, now arriving as a *per-core* figure). On this reading
the four layers bracket the new L1 axis better than they bracketed the
old one, and **no swap is warranted**.

**Why that is not yet a justification, only a defence.** The bound above
assumes a COUT partition across cores. The fixture slice says the real
mapping is not that: cores share most of their addresses. And the
sharper measurement (G14) says the per-core *per-tile* set is ~384 B on
these layers, which is below the whole axis. So the honest position is:

- **The layer set is not the problem** - it spans the full reuse range
  (1024 output positions per weight at 32x32, 16 at 4x4) and covers the
  L2 axis properly. Swapping a layer would not change the L1 axis.
- **The L1 axis siting is settled by ruling R6** (§1.3 G14): the axis is
  sized for the fixed machine across the whole workload mix, not for the
  shallowest layer, so a flat L1 curve on `layer_01` is a finding to
  report. The per-core per-tile measurement is still taken in Stage 1,
  but as a diagnostic that explains the curves, not as a gate on the
  axis.

**Secondary reasons, unchanged by R2:**

- **Reuse spans the useful range.** Shallow layers have 1024 output
  positions per weight (32x32), deep layers have 16 (4x4). Weight reuse
  is what a weight cache exists to capture, so the two extremes must both
  be present.
- **The padding confound is zero.** With `cout_block = 16` and
  `cin_block` in {1,2,4}, every chosen layer has CIN and COUT exactly
  divisible, so `padding_fraction` (the column `PROGRESS.md:894` mandates
  on every row) is 0 for all four. Nothing in the comparison is
  contaminated by intra-line padding waste.
- **"Shallow" and "deep" are by position in the network**, layer 1 of 12
  and 1 of 19 against layer 9 of 12 and 16 of 19.

**A sweep whose four layers all overflow every cache would produce four
flat, identical curves.** That was the original warning and R2 makes it
sharper, not softer: on the whole-layer reading all four now overflow
every L1. It is the per-core reading that rescues the axis, and the per-
core reading is the one nobody has measured.

**One judgement call to confirm (see §11, Q3, still open).** For VGG16 the deepest
layers (10, 11, 12) share `layer_09`'s 2304 KB footprint but drop to 2x2
spatial, which is 4 output positions and effectively no reuse. That makes
them a purer streaming stress case but a degenerate one - both spad and
cache stream cold and the comparison flattens. `layer_09` keeps 16
positions, which is enough for the cache to do something. For ResNet-19,
`layer_19_layer3_1_conv2` is literally the deepest but has the same
2304 KB footprint as the VGG16 pick, which would waste one of the four
slots on a duplicate capacity point; `layer_16` was chosen instead
because 1125 KB is the only footprint in either network that lands on the
L2 ceiling.

---

## 4. Configuration matrix

### 4.1 Which axes are shared and which are independent

This is the single most important structural fact about the campaign, and
it is what keeps the run count tractable.

**The MIP schedule and the weight trace depend only on `(arch, n_cores,
layer, sample)`. They do not depend on any cache parameter.** The same
trace feeds nocsim and every wcache configuration. So:

- Shared stage cost: **36 schedule points** (3 arch x 3 cores x 4 layers)
  and **180 trace instances** (x 5 samples).
- Independent stage cost: the cache configurations multiply *only* the
  wcache stage.

This also creates a control worth stating plainly: the schedule the MIP
produces is tuned for the scratchpad's capacity, and the cache arm
inherits it unchanged. That is the correct controlled comparison (same
work, same order, different memory system), but it biases **against** the
cache, because the cache never gets a schedule chosen for it. Say so in
the eventual write-up rather than letting a reviewer find it.

### 4.2 The cache axes

```
L1 size            5   {2, 4, 8, 16, 32} KB          per core   (R2, 2026-08-20)
line size          3   {16, 32, 64} B  ==  cout_block 16 x cin_block {1,2,4} x 1 B
L2 size            3   {256, 512, 1024} KB           shared
prefetch distance  4   {0, 2, 4, 8}                                        (§5)
                  ---
cache configs      5 x 3 x 3 x 4  =  15 x 12  =  180
```

**The count went 108 -> 180**, a factor of 5/3 = 1.667, and it multiplies
every tier that runs a full grid (Tier 0 and Tier 3) and the
full-factorial comparison figure. The one-factor ridge (Tier 2) grows by
only two configs, because an OFAT ridge is additive in the axis lengths
rather than multiplicative.

Note on the line-size axis: `line_size_bytes = cin_block * cout_block *
weight_bytes` (`src/cachesim/config.py:127-133`), and `BW_WEIGHT: 8`
gives `weight_bytes = 1`, so 16 x {1,2,4} x 1 = {16, 32, 64} B exactly as
requested. Because `cout_block` is pinned at 16, this axis varies **only
the cin packing**. That is a clean property: it isolates cin-direction
spatial locality and leaves `lines_per_burst` - and therefore
`l1_demand_reserve` and the prefetch budget - unchanged across the axis.

### 4.3 Full factorial, and why it is not the plan

```
shared points      3 arch x 3 cores x 4 layers            =    36
samples                                                   x     5
cache configs                                             x   180
                                                            ------
full-factorial wcache runs   36 x 5 x 180                 =  32,400
spad arms   36 x 5 x (nocsim + wcache-spad)  = 180 x 2    =     360
spad_oracle 36 x 5                                        =     180   (no simulation)
                                                            ------
total simulated runs         32,400 + 360                 =  32,760
```

32,400 is a **65% increase** on the 19,440 the 108-config grid implied
(32,400 / 19,440 = 1.667, exactly the 5/3 the L1 axis grew by). At the
§8 planning figure of 15 core-seconds per row that is

```
32,400 x 15 s  =  486,000 core-s  =  135.0 core-hours
    plus 360 spad rows x 15 s  =  5,400 core-s  =  1.5 core-hours
                                   ------------------------------
                                   136.5 core-hours  =  8.5 h on 16 CPUs
```

against the old grid's ~82 core-hours. **8.5 hours on one 16-CPU
allocation does not fit the 2 h Slurm wall cap and would need at least
five resumable jobs.** That is still not impossible, but it is a worse
use of the budget than it was: most of it is spent on interior points of
a four-dimensional grid where the one-factor curves are already flat, and
it commits the whole budget before a single per-run cost has been
measured. **The staged plan matters more after R2 than before it.**

### 4.4 The staged plan

Held constant across every tier: `l1_assoc = 8`, `l2_assoc = 16`,
`policy = lru`, `inclusion = non_inclusive`, `l2_banks = 1`, `l2_ii = 1`,
`core_accept_ii = 1`, `l1_latency = 0`, MSHR values per §6, latencies per
§7. Associativity is 8-way L1 / 16-way L2, which is **gem5's own standard-
library pairing** (§6.2) rather than a number invented here; it also
answers G10, because every radix in this corpus is a power of two and a
2-way or 4-way L1 would show conflict pathologies that belong to the
layout, not to the cache size under test. Fully-associative is rejected as
unbuildable at the top of the axis (32 KB / 16 B lines is 2048 lines).
This resolves G9 by pinning, not by sweeping. **R2 makes the 8-way choice
matter more, not less**: at 2 KB the associativity is what stands between
the grid and a conflict-miss pathology, which §4.5 works out in full.

**The tier architecture is APPROVED in structure (R5, 2026-08-20).** Each
tier keeps its role. Every count below is recomputed against the
180-config grid, with the arithmetic shown so it can be checked.

**Tier 0 - pilot / calibration (180 runs).**
LoAS, 16 cores, `vgg16 layer_01`, 1 sample, all 180 cache configs.

```
1 arch x 1 core count x 1 layer x 1 sample x 180 configs  =  180 runs
```

Purpose: measure the real per-run wall-clock cost, confirm the grid runs
end to end, and confirm V1/V21/V27 pass. **This is the go/no-go for
everything below**; the §8 runtime figures are estimates until Tier 0
replaces them. Tier 0 also now carries a second job: it is the first
place the **2 KB configurations** run at all, so it is where §4.5's
small-cache warnings either fire or do not.

**Tier 1 - baselines (360 simulated + 180 free). UNCHANGED by R2**, since
no baseline arm touches the cache-size axis.

```
spad_oracle   36 shared points x 5 samples  =  180 rows, no simulation
spad_wcache   36 x 5                        =  180 runs
spad_nocsim   36 x 5                        =  180 runs
                                               ---------
                                               360 simulated
```

The `spad_wcache` arm now runs at **L1 = 32 KB per core, L2 = 4 MB**,
prefetch off (R2), not at the 512 KB of the original request.

**Tier 2 - one-factor-at-a-time ridge (2,520 runs).**

**New nominal configuration: L1 8 KB, line 32 B, L2 512 KB, `d = 4`.**
(Was 32 KB; see the justification below.) Vary one axis at a time:

```
L1 size            5   {2, 4, 8, 16, 32}
line size          3   {16, 32, 64} B
L2 size            3   {256, 512, 1024} KB
prefetch distance  6   {0, 1, 2, 4, 8, 16}   (the ridge carries d=1 and d=16; §5)
                  ---
sum                5 + 3 + 3 + 6            =   17
minus 3 repeats of the nominal point        =   14 distinct configs
                                               (the nominal appears once per axis,
                                                4 times; keep 1, drop 3)
36 shared points x 14 configs x 5 samples   =  2,520 runs
```

The ridge grew by only **360 runs** (2,160 -> 2,520), because an OFAT
ridge is additive in axis lengths: two more L1 values cost
`2 x 36 x 5 = 360` and nothing else.

*Not counted in the 2,520:* §6.3's classic `l1_mshrs = 4` calibration
row. It is one extra config, so `36 x 1 x 5 = 180` further runs if it is
taken. The original plan also left it uncounted; it is stated explicitly
here so the omission is visible rather than inferred.

This covers **every** architecture, core count and layer on every axis,
which is what the deliverable actually asks for.

**Why 8 KB is the new nominal.** Two independent reasons, and they agree:

1. **It is the geometric centre of the axis.** {2, 4, 8, 16, 32} is
   log-spaced with ratio 2, and 8 is the third of five, so the ridge has
   **two points below and two above** on the L1 axis, which is what an
   OFAT ridge wants and what 32 KB (an endpoint of the new axis) would
   not give. Under the old {16, 32, 64} axis, 32 KB was the centre for
   exactly this reason; 8 KB inherits the role rather than replacing it.
2. **It sits exactly on the decision rule's quarter-storage line.** From
   §2's arithmetic, `l1 = 8 KB` with the largest L2 (1024 KB) gives
   totals of 1056 / 1152 / 1536 KB at 4 / 16 / 64 cores - which are
   *exactly* the quarter thresholds at all three core counts. The nominal
   is therefore the point the claim is actually about, so every one-factor
   curve pivots through the configuration under test rather than through
   an arbitrary interior point.

Rejected alternatives: **32 KB** (matches the spad L1 exactly, which is a
useful *control* but a bad ridge pivot - it is an endpoint, so three of
the five L1 points would lie on one side); **4 KB** (centre of the
storage-viable region, but it puts the pivot inside the regime §4.5 warns
about, so a §4.5 artifact would contaminate every other axis's curve).

**Tier 3 - focused full factorial (4,320 runs).**
The full 180-config grid at the pivot core count, to catch interactions
the ridge cannot see (the expected one is line size x prefetch distance,
and R2 adds a second candidate: L1 size x line size, because at 2 KB the
line size changes the set count by 4x):

```
3 arch x 1 core count (16) x 4 layers        =   12 points
12 points x 180 configs x 2 samples          =  4,320 runs
```

Tier 3 grew by 1,728 runs (2,592 -> 4,320), the largest single cost of
R2 and 5/3 of the old figure, as expected for a full grid.

**Totals.**

```
Tier 0     180
Tier 1     360   (+180 oracle rows, no simulation)
Tier 2   2,520
Tier 3   4,320
Tier 4     180   latency sensitivity study (§7.3), unchanged by R2
        ------
         7,560 simulated runs   vs 32,760 full factorial

reduction  32,760 / 7,560  =  4.33x    (was 3.7x at 108 configs)
```

Sum check: `180 + 360 = 540`; `540 + 2,520 = 3,060`;
`3,060 + 4,320 = 7,380`; `7,380 + 180 = 7,560`.

The staged plan therefore **saves more** after R2 than before it (4.33x
against 3.7x), because the tier that grew most is the one the staging
exists to avoid running blind.

**Cross-tier duplicates: 288 rows** (recomputed; the original text said
"about 264" and did not show its arithmetic, so it is replaced rather
than scaled).

```
Tier 2 configs that also exist in Tier 3's grid:
  14 ridge configs minus d=1 and d=16,           =  12 configs
  which are not in Tier 3's {0,2,4,8} axis
Tier 2 and Tier 3 overlap on 16 cores only:      =  12 shared points
Tier 3 runs 2 samples; Tier 2 runs 5 (superset)  =   2 samples
                                                    ------
12 configs x 12 points x 2 samples               =    288 rows
```

**Those duplicates are kept deliberately** as a cross-tier
reproducibility check, in the same spirit as v3's own "those duplicates
are the check, not waste" (`:1594`).

**Escalation rule.** If Tier 2 shows a curve that is not monotone, or if
Tier 3 shows an interaction the ridge missed, extend Tier 3 to 4 and 64
cores rather than running the full factorial blind:

```
2 further core counts x 12 points x 180 configs x 2 samples  =  8,640 runs
```

(was 5,184 at 108 configs). Note that this escalation now costs **more
than the entire staged campaign** (8,640 against 7,560), so it should be
escalated one core count at a time - 4,320 for the 64-core arm alone,
which is the arm where the storage argument is most interesting because
the spad's aggregate L1 is largest there.

---

### 4.5 Small-cache sanity at the bottom of the new L1 axis

R2 takes the L1 axis down to 2 KB, an order of magnitude below anything
this plan previously contemplated. At 8-way associativity the geometry
gets thin enough that some of the model's own assumptions need checking,
and D1 must enforce a few of them rather than let a degenerate config
run and produce a plausible-looking number.

**The geometry, worked out.** `num_lines = l1_size / line_size` and
`num_sets = num_lines / l1_assoc`, with `l1_assoc = 8` (§6.3):

| L1 | line 16 B | line 32 B | line 64 B |
|---|---|---|---|
| **2 KB** | 128 lines / **16 sets** | 64 lines / **8 sets** | 32 lines / **4 sets** |
| 4 KB | 256 / 32 | 128 / 16 | 64 / **8** |
| 8 KB | 512 / 64 | 256 / 32 | 128 / 16 |
| 16 KB | 1024 / 128 | 512 / 64 | 256 / 32 |
| 32 KB | 2048 / 256 | 1024 / 128 | 512 / 64 |

The corner the user named - **2 KB / 64 B / 8-way = 32 lines in 4 sets** -
is the extreme point of the whole grid and is where every concern below
is at its worst.

**Four findings, in order of how much they matter.**

**(1) The MSHR file becomes comparable to the array. This is the real
one.** `l1_mshrs = 16` (§6.3) against **32 lines** at 2 KB / 64 B means
**half the cache can be in flight at once**. At that point the structure
under test is no longer mostly a cache; it is a 32-line array with a
16-entry miss buffer bolted on, and a "cache size" curve through it is
measuring the MSHR file as much as the capacity. Worse, the prefetch axis
is designed to *fill* those MSHRs: at `d = 8` the budget is
`16 - lines_per_burst` = 15 for LoAS/PTB and 12 for Spinalflow (§5.2), so
a prefetch-heavy run can have 8-15 of the 32 lines speculatively
allocated. Expect `pf_pollution_evictions` to be large and expect the
prefetch axis and the L1-size axis to **interact strongly** at the bottom
of the range - which is a result worth having, but only if it is labelled
as such rather than read as an L1-capacity result.

> **Constraint for D1: WARN when `l1_mshrs >= num_lines / 2`.** At
> 2 KB / 64 B this fires exactly (16 >= 16). D2 should emit
> `l1_num_lines` and `l1_num_sets` as columns so the condition is
> reconstructable from the CSV rather than only from a log line.

**(2) Four sets on a power-of-two-radix corpus is a conflict-miss
generator, and G10 already predicted it.** `HANDOFF.md:190-192`: every
layer is `KH = KW = 3` with CIN and COUT in {64, 128, 256, 512}, "so
every radix is a power of two, which is why a strided walk aliases
perfectly against a power-of-two set count rather than degrading
gracefully". §4.4 pinned `l1_assoc = 8` specifically to blunt that, and
8-way over 4 sets still gives 32 places for a line to live - but a 2-bit
set index over perfectly power-of-two-strided addresses is the worst case
the corpus can present.

> **Constraint for D1: WARN when `l1_num_sets < 8`**, naming G10, so
> every 2 KB / 64 B row and every 4 KB / 64 B row carries the warning.
> The 2 KB / 64 B point should be **kept and reported**, not dropped: it
> is the corner where the layout artifact and the capacity effect are
> both largest, and a plan that silently removes its own worst case is
> not measuring the axis.

**(3) A whole burst must still be placeable, and it is.** N7 requires a
burst's lines to be placeable at once, which is why `l1_demand_reserve`
defaults to `lines_per_burst` (§6.3). The worst case is Spinalflow: a
64-COUT burst at `cout_block = 16` expands to **4 lines**. Even in the
4-set geometry, 4 lines fit - they are consecutive addresses, so under a
low-bit set index they land in 4 *different* sets, and even if they
collided in one set, 8 ways holds them. **No constraint needed; this one
checks out.** Worth stating because it was the plausible-sounding failure
and it is not real.

**(4) The config must have at least one set, and at 2 KB it does.**
`l1_size >= l1_assoc * line_size` is the floor: `8 x 64 = 512 B`, and
2 KB is 4x that. So nothing on this grid is degenerate. The constraint is
still worth enforcing because it is one line and because it becomes live
the moment anyone raises `l1_assoc` - at `l1_assoc = 16` (the L2's
value), 2 KB / 64 B would be **2 sets**, and at 32-way it would be 1.

> **Constraint for D1: REJECT at config load when
> `l1_size_bytes < l1_assoc * line_size_bytes`** (fewer than one set),
> and the same for L2. This is a V-style validation in D1's existing
> "config load + validation" remit, not new machinery.

**What none of this changes.** The L2 axis is untouched: the smallest L2
is 256 KB at 16-way, which is 4096 lines / 256 sets at 64 B - nowhere
near thin. And `l2_mshrs = 20` against 4096 lines is 0.5%, so finding (1)
has no L2 counterpart.

**Summary of what D1 owes because of R2:** two warnings
(`l1_mshrs >= num_lines / 2`; `num_sets < 8`) and one rejection
(`size < assoc * line`), plus two new D2 columns (`l1_num_lines`,
`l1_num_sets`). None of it is written here; this is the requirement, not
the implementation.

---

## 5. Prefetch distance

**Chosen: `d` in {0, 2, 4, 8} for the factorial tiers, and {0, 1, 2, 4,
8, 16} for the Tier 2 ridge.**

Four reasons, in order of how much weight each carries.

**5.1 The repo has already measured this curve.** `PROGRESS.md:869`
(measurement U19) records `fetch_latency` against prefetch distance:

| `d` | 0 | 1 | 2 | 4 | 8 |
|---|---|---|---|---|---|
| `fetch_latency` | 6600 | 3213 | 2067 | 1155 | 825 |
| fraction of `d=0` | 1.00 | 0.487 | 0.313 | 0.175 | 0.125 |

The whole useful range lies between 0 and 8: the step from 4 to 8 buys
5% of the `d = 0` latency and the curve is close to flat afterwards.
`{0, 2, 4, 8}` brackets it with four points; `d = 1` is kept in the ridge
because 1.00 -> 0.487 is the largest single step in the table and it
would be a shame to lose its shape.

**5.2 The upper end is set by the MSHR budget, not by the distance.**
v3 `:370`: the prefetch budget is `l1_mshrs - l1_demand_reserve`, and
`l1_demand_reserve` defaults to `lines_per_burst`; "prefetch does nothing
at all unless `l1_mshrs > lines_per_burst`". Steady-state throughput goes
as `min(d, budget) + 1` (`:1592`). With `l1_mshrs = 16` (§6) and
`cout_block = 16`:

| Arch | burst span (cout) | `lines_per_burst` | budget |
|---|---|---|---|
| LoAS | 16 | 1 | 15 |
| PTB | 16 | 1 | 15 |
| Spinalflow | 64 | 4 | 12 |

(Spans from `src/wcache/examples/manifest.json`.) So `d = 8` is inside
the budget for all three architectures and `d = 16` is above it for all
three. That makes `d = 16` a **free correctness check**, not a data
point: it must reproduce `d = 8`'s row exactly, and if it does not, the
`min(d, budget)` model is wrong (v3's own reasoning, `:1592-1595`).

**5.3 Full latency coverage is out of reach, and that is a result.**
With `l2_latency = 10` and `l2_miss_latency = 100` (§7) a full miss costs
110 cycles, and the corpus has `gap = 1` throughout
(`src/wcache/examples/manifest.json`: `gap_min = gap_max = 1`), so a core
wants a new burst every cycle. Covering 110 cycles would need `d` near
110, which is far beyond any achievable budget at any plausible
`l1_mshrs`. The campaign therefore measures **partial** coverage, and the
correct reported conclusion is that prefetch distance is bounded by MSHR
capacity rather than by the policy. Sweeping `d` to 32 or 64 would only
re-measure the budget ceiling.

**5.4 `d = 0` is the control.** With prefetching off, `core_stall` and
`fetch_latency` are equal by construction (`:1438`), which makes the
`d = 0` row a free consistency check on every other row in its group.

**Caveat tied to G7.** The metric that is supposed to judge the policy -
`core_stall - fetch_latency`, "the latency the policy hid" (`:1440`) -
was measured as identically zero (U19). Until D2 picks a replacement, the
prefetch axis will produce `fetch_latency` differences with no accepted
figure of merit attached to them. Decide before Tier 2.

---

## 6. gem5 MSHR and targets-per-MSHR values

### 6.1 The correction that matters: gem5 has no library default

`mshrs` and `tgts_per_mshr` are declared in `src/mem/cache/Cache.py`
(class `BaseCache`, `abstract = True`) **with a description string and no
default value**:

```python
mshrs = Param.Unsigned("Number of MSHRs (max outstanding requests)")
demand_mshr_reserve = Param.Unsigned(1, "MSHRs reserved for demand access")
tgts_per_mshr = Param.Unsigned("Max number of accesses per MSHR")
write_buffers = Param.Unsigned(8, "Number of write buffers")
```

Source: <https://raw.githubusercontent.com/gem5/gem5/stable/src/mem/cache/Cache.py>,
lines 86-104, read 2026-08-20 at `stable` HEAD
`62c7bf284864b83f7308f5e14ca9c80812621c29`; byte-identical at release tag
`v25.1.0.1`. In gem5's parameter system a `Param` with no default is
**required**, so a configuration that omits it fails at instantiation.
Note that `write_buffers` (8) and `demand_mshr_reserve` (1) *do* carry
library defaults; MSHR count and target depth do not.

Two further corrections to the older references in this repo:
`src/mem/cache/BaseCache.py` does not exist on `stable` (the parameters
live in `Cache.py`), and `configs/example/se.py` is now a deprecation stub
- the working script moved to `configs/deprecated/example/se.py`.

So every number below is an **example-configuration value**, not a
library default, and this plan should say so rather than repeating the
common shorthand.

### 6.2 The three gem5 configuration families

| Source | L1I/L1D `mshrs` | L1 `tgts_per_mshr` | L1 `assoc` | L2 `mshrs` | L2 `tgts_per_mshr` | L2 `assoc` |
|---|---|---|---|---|---|---|
| `configs/common/Caches.py` (classic, used by the deprecated `se.py`) | 4 | 20 | 2 | 20 | 12 | 8 |
| `configs/learning_gem5/part1/caches.py` (tutorial) | 4 | 20 | 2 | 20 | 12 | 8 |
| `src/python/gem5/components/cachehierarchies/classic/caches/` (modern standard library) | **16** | 20 | **8** | 20 | 12 | **16** |

- Classic: <https://raw.githubusercontent.com/gem5/gem5/stable/configs/common/Caches.py>,
  lines 52-99. Verbatim: `class L1Cache(Cache): assoc = 2; tag_latency = 2;
  data_latency = 2; response_latency = 2; mshrs = 4; tgts_per_mshr = 20`
  and `class L2Cache(Cache): assoc = 8; tag_latency = 20; data_latency = 20;
  response_latency = 20; mshrs = 20; tgts_per_mshr = 12; write_buffers = 8`.
  This is the same block `log/2026-08-05-cachesim-redesign-plan.md:261-262`
  already cited as "`Caches.py:52-78`"; that citation is confirmed correct.
- Tutorial: <https://raw.githubusercontent.com/gem5/gem5/stable/configs/learning_gem5/part1/caches.py>,
  lines 46-54 and 112-122 (same numbers, plus `size = "16KiB"` L1I,
  `"64KiB"` L1D, `"256KiB"` L2).
- Standard library: `l1dcache.py`, `l1icache.py`, `l2cache.py` under
  <https://raw.githubusercontent.com/gem5/gem5/stable/src/python/gem5/components/cachehierarchies/classic/caches/>.
  L1D/L1I: `assoc = 8`, latencies 1/1/1, `mshrs = 16`, `tgts_per_mshr = 20`.
  L2: `assoc = 16`, latencies 10/10/1, `mshrs = 20`, `tgts_per_mshr = 12`.

Cache sizes in the classic family come from the command line
(`configs/common/Options.py:189-199`): `--l1d_size` 64 KiB, `--l1i_size`
32 KiB, `--l2_size` 2 MiB, `--l1d_assoc`/`--l1i_assoc` 2, `--l2_assoc` 8,
`--cacheline_size` **64**. That last one is worth noting: gem5's default
line size is exactly the top of this campaign's line-size axis.

### 6.3 What this campaign adopts

| Parameter | Value | Source |
|---|---|---|
| `l1_mshrs` | **16** | gem5 standard library `l1dcache.py` |
| `l1_tgts_per_mshr` | **20** | all three families agree |
| `l2_mshrs` | **20** | all three families agree |
| `l2_tgts_per_mshr` | **12** | all three families agree |
| `l1_assoc` | **8** | gem5 standard library `l1dcache.py` |
| `l2_assoc` | **16** | gem5 standard library `l2cache.py` |

**Why the standard-library L1 rather than the classic L1 (this is the one
deviation, and it is not arbitrary).** The classic value `mshrs = 4`
would make the prefetch axis **inert for Spinalflow**. v3 `:370`:
prefetching does nothing unless `l1_mshrs > lines_per_burst`, and
Spinalflow's 64-cout bursts expand to 4 lines at `cout_block = 16`
(`src/wcache/examples/manifest.json`). At `l1_mshrs = 4` the budget is
`4 - 4 = 0`, and D1 is specified to *warn* about exactly this
(`:1362`, "a prefetch budget smaller than `lines_per_burst` **warns**").
One third of the architectures would carry no prefetch information at all.
`mshrs = 16` is still a gem5 number, from the family gem5 currently
recommends, and it gives budgets of 15 / 15 / 12 (§5.2). It also brings
the associativity that resolves G9 and G10 in the same move.

**Calibration point.** Run the classic `l1_mshrs = 4` as one labelled
extra row in the Tier 2 ridge, so the campaign reports both gem5 families
rather than silently choosing one.

**A note on `demand_mshr_reserve`.** gem5's library default is 1; this
model's `l1_demand_reserve` defaults to `lines_per_burst`, which is 1 for
LoAS and PTB and 4 for Spinalflow. The two agree for two of the three
architectures. The divergence is deliberate on this model's side (N7
requires a whole burst to be placeable at once) and should be stated, not
hidden.

---

## 7. eDRAM-derived L1 and L2 miss penalties

### 7.1 What the numbers have to be

In this model the two penalties are:

- **L1 miss penalty** = `l2_latency + l2_to_l1_latency` - the cost of
  reaching the shared L2, which in this design is on-die eDRAM.
- **L2 miss penalty** = `l2_miss_latency` - the round trip to whatever
  backs the L2.

Both are currently "*(to set)*" (`:361-363`, G4).

### 7.2 Evidence

**Measured silicon, bare eDRAM macros (fastest tier).**

| Node | Random access | Random cycle | Source |
|---|---|---|---|
| 14 nm | **1.0 ns** | 2.0 ns/bank | G. Fredeman, D. Plass et al., "A 14 nm 1.1 Mb Embedded DRAM Macro With 1 ns Access", *IEEE JSSC* 51(1):230-239, Jan 2016, doi:10.1109/JSSC.2015.2456873 |
| 45 nm SOI | **1.35 ns** | 1.7 ns | J. Barth, D. Plass, E. Nelson, C. Hwang, G. Fredeman et al., "A 45 nm SOI Embedded DRAM Macro for the POWER Processor 32 MByte On-Chip L3 Cache", *IEEE JSSC* 2011 (ISSCC 2010, pp. 342-343) |
| 65 nm SOI | **1.5 ns** | 2.0 ns (500 MHz) | J. Barth, W. R. Reohr, P. Parries, G. Fredeman et al., "A 500 MHz Random Cycle, 1.5 ns Latency, SOI Embedded DRAM Macro Featuring a Three-Transistor Micro Sense Amplifier", *IEEE JSSC*, Jan 2008 |

**Measured silicon, eDRAM as a last-level cache (adds tags, arbitration,
chip-crossing wire).**

| System | Latency | Source |
|---|---|---|
| IBM POWER7, 32 MB eDRAM L3, 3.55 GHz | 24 cycles = **6.8 ns** | <https://www.7-cpu.com/cpu/Power7.html> (microbenchmark on a Power 730 Express) |
| IBM POWER8, 96 MB 22 nm eDRAM L3, 3.69 GHz | 27 cycles = **7.3 ns** | <https://www.7-cpu.com/cpu/Power8.html> |
| Intel Crystal Well, 128 MB eDRAM L4, off-package over OPIO | **36.6 ns** load-to-use | C. Lam, "Broadwell's eDRAM: VCache before VCache was Cool", Chips and Cheese, Nov 2024, <https://chipsandcheese.com/p/broadwells-edram-vcache-before-vcache> (measured on a Xeon E3-1285 v4; same machine's DRAM latency 64.3 ns) |

**The directly relevant accelerator anchor: DaDianNao.** Y. Chen, T. Luo,
S. Liu, S. Zhang, L. He, J. Wang, L. Li, T. Chen, Z. Xu, N. Sun, O.
Temam, "DaDianNao: A Machine-Learning Supercomputer", *MICRO-47*, 2014,
pp. 609-622, doi:10.1109/MICRO.2014.58.
PDF: <https://course.ece.cmu.edu/~ece742/S23/paper_pdfs/DaDianNao_A_Machine-Learning_Supercomputer.pdf>
Table III, verbatim:

```
Frequency                    606MHz    tile eDRAM latency     ~3 cycles
# of tiles                       16    central eDRAM size          4MB
                                       central eDRAM latency ~10 cycles
tile eDRAM size/tile            2MB    Link latency               80ns
```

This is the right anchor for three reasons: it is an accelerator, not a
CPU; its storage organisation (**per-node buffers plus a 4 MB central
eDRAM weight store**) is **the same organisation this campaign's spad
baseline uses**; and it clocks at 606 MHz precisely because that is
the eDRAM's speed at 28 nm, so its cycle counts and its latencies are
internally consistent. These are post-layout / RTL-simulated numbers
(VCS + CACTI 5.3, ST 28 nm LP), **not fabricated silicon** - say so.
Note what R2 did *not* change here: `l2_latency = 10` comes from
DaDianNao's **central 4 MB** eDRAM, and this campaign's L2 is still a
4 MB shared store, so the anchor holds exactly. It is only the *L1* side
of the DaDianNao correspondence that R2 broke, and §7 never used it.

One modern modeled cross-check: T. Xia and S. Q. Zhang, "Kelle: Co-design
KV Caching and eDRAM for Efficient LLM Serving in Edge Computing",
*MICRO '25*, doi:10.1145/3725843.3756071, <https://arxiv.org/pdf/2510.16040>,
Table 1: a 4 MB 65 nm eDRAM macro at **1.9 ns** against SRAM's 2.6 ns,
modeled in Destiny.

### 7.3 The values this campaign assumes

**Adopt DaDianNao's cycle counts directly, rather than converting through
an assumed clock.** The model has no stated clock frequency, and
inventing one only to convert nanoseconds back into cycles adds an
assumption without adding information. DaDianNao's cycle counts are
already those of an accelerator whose eDRAM sets the clock; taking them
as-is makes the assumed clock 606 MHz implicitly and keeps the set
self-consistent.

| Parameter | Value | Justification |
|---|---|---|
| `l1_latency` | **0** | Required, not chosen: v3 `:392-397` shows that only at 0 does a 100% hit run reproduce the scratchpad timeline exactly (V1), which is the calibration of this whole comparison. It measures the cost of an L1 hit *above* the access the trace already assumes. |
| `l2_to_l1_latency` | **0** | v3 default (`:362`) |
| `l2_latency` (= **L1 miss penalty**) | **10 cycles** (~16.5 ns @ 606 MHz) | DaDianNao Table III, **central** eDRAM ~10 cycles. Central, not tile, because this model's L2 is shared across all cores, which is what the central eDRAM is. |
| `l2_miss_latency` (= **L2 miss penalty**) | **100 cycles** | See below - this one is *not* eDRAM-sourced. |
| Full miss (`l2_latency + l2_miss_latency`) | **110 cycles** | Matches v3's own worked example verbatim (`:1200-1201`: "`l2_latency = 10`, `l2_miss_latency = 100`, so a full miss costs 110 cycles") and every derived threshold in the plan (`:1565`, `:1577`). |

**Be honest about `l2_miss_latency = 100`.** It is **not** derived from
eDRAM and it is **not** from gem5. It is this repo's own prior choice
(`log/2026-08-05-cachesim-redesign-plan.md:465`,
`l2_miss_latency_ticks = 100 {50, 100, 200}`), and the 08-05 plan already
flags it as an assumption. What eDRAM literature can say is what it
*brackets*: if the backing store is off-chip DRAM, 64.3 ns measured on the
Broadwell machine is ~39 cycles at 606 MHz, and a loaded DRAM with
queueing is several times that, so 100 is plausible but on the high side
of unloaded. If the backing store is instead a DaDianNao-style
on-package eDRAM reached over a link, Table III's 80 ns link plus the
10-cycle central access gives ~59 cycles. **Mark 100 as an assumption to
confirm, and carry {50, 100, 200} as a small sensitivity study** (§7.4),
not as a main grid axis.

**Sensitivity study (not in the main grid).** At the nominal
configuration only, on all 36 shared points, 1 sample:

- `l2_latency` in {3, 10, 17}: DaDianNao tile eDRAM / central eDRAM /
  central expressed at 1 GHz. 3 x 36 = 108 runs.
- `l2_miss_latency` in {50, 100, 200}: on-package eDRAM / nominal /
  contended DRAM. 3 x 36 = 108 runs.

216 runs, minus 36 duplicated nominal points, is 180 extra runs - about
2.4% of the campaign (180 / 7,560) - and it converts "we assumed 110
cycles" into "the conclusion holds across a 4x range of miss penalty",
which is the difference between a result and an assertion.

**Unchanged by R2.** This study runs at the nominal configuration only,
so it costs `(3 + 3) x 36 = 216` runs regardless of how many points the
L1 axis has; only the *nominal* changed, from 32 KB to 8 KB (§4.4). It
did become a smaller share of the campaign, 3% -> 2.4%, purely because
the campaign grew.

### 7.4 Two eDRAM behaviours this model does not capture

Both are named explicitly by DaDianNao as the reason it banks its eDRAM
four ways: **reads are destructive** (a read implies a write-back, so
back-to-back reads on one row are not free) and the array needs
**periodic refresh** (45 us at 65 nm per Kelle Table 1; 100 us at 95 C
for Intel's 22 nm macro, F. Hamzaoglu et al., "A 1 Gb 2 GHz 128 GB/s
Bandwidth Embedded DRAM in 22 nm Tri-Gate CMOS Technology", *IEEE JSSC*
50(1):150-157, 2015, doi:10.1109/JSSC.2014.2353793). This model has a
fixed `l2_latency` and no refresh, so it will be slightly optimistic
about the eDRAM level. State it as a limitation; do not try to model it.

### 7.5 Not verified

- No gem5.org documentation page was fetched. The live source above
  supersedes it, and any gem5.org number that disagrees should be treated
  as stale.
- The Intel 22 nm eDRAM paper does **not** state a random-access latency
  in nanoseconds; it is cited here only for the refresh figure.
- A "6.86 ns POWER8 eDRAM load-to-use" figure appeared in search results
  and could not be traced to a primary source. It is rejected in favour
  of the 7.3 ns figure derived from the measured 27-cycle result.
- Eyeriss supplies no eDRAM latency (its global buffer is SRAM) and is
  not cited for one.
- Beyond DaDianNao, no accelerator paper with an explicit eDRAM
  access-latency assumption in cycles was located. If a second
  accelerator anchor is wanted, DaDianNao's descendants (Cnvlutin,
  Bit-Pragmatic) inherit its timing, but their tables were not checked.

---

## 8. Execution order, phasing and runtime

### 8.1 Hosts

Two machines are in play and the plan must not confuse them. **Confirmed
2026-08-20 by the user's ruling R7.**

- **NCSA Delta**, project root `/u/yyu9/projects/neuro_cache`, account
  `bebv-delta-gpu`, partition `gpuA40x4`, 16 CPUs, 128 GB, **2 h wall
  cap** (`profiling/0803_l1_l2_cache/run_sweep.slurm`). The account is
  GPU-only, so the job requests one otherwise-unused A40
  (`profiling/0803_l1_l2_cache/README.md`). **The whole campaign runs
  here**: every tier (Tier 0 through Tier 4), all trace generation, and
  the MIP solves at scale.
- **CECSUnaryLab**, 32 cores, no scheduler, unlimited `ulimit -t`
  (`PROGRESS.md:1037`, B81). This is where wcache is built and tested.
  **Demo and smoke runs only**: build, tests, fixture-slice runs, and
  single-point sanity checks. **No campaign tier runs locally.**

**Pre-Delta smoke test.** Before Tier 0 is submitted on Delta, run a
**local demo** on CECSUnaryLab: a few configurations over the
`src/wcache/examples/` fixture slices, end to end through the pipeline.
It exists to catch build, wiring and config errors on the cheap machine;
it produces no campaign result and is not a tier.

Note the 2 h wall cap: no single stage below may assume a longer job.
Every stage must be resumable, which the existing driver pattern already
is.

### 8.2 Stages

**Stage -1: unblock (G1, G2, G5, G6, G13).** Build A3, D1, D2, D3;
decide the 4-core question; settle U25-U28 as stream header fields; and
build A3 **as the streaming reader** rather than as a file reader and
then a stream reader (§10). Not estimated here - it is Phase D
implementation and out of this plan's scope. It is stated because **the
campaign cannot start without it**, and because the in-flight requirement
changes what A3 is rather than adding work after it.

**Stage 0: MIP schedules.** `scripts/solve_schedules.py`, Gurobi.
36 combinations x the 13-mode enumerator = 468 solver calls.
Measured basis: ~1.5-2.0 s per combination
(`log/2026-07-30-tracegen-refactor-and-multinode-sweep-plan.md:24`).
Concurrency is capped by the Gurobi WLS licence: 2-8 workers clean, 16
stalls, 64 crashes with "Too many sessions"
(same log) - **8 workers is the verified-safe setting**.

> ~14 min serial, **~2 min at 8 workers**. Estimate, from measured
> per-call cost. **The 4-core infeasibility risk this line used to carry
> is WITHDRAWN (R3): the `COUT: {spatial: 4}` cap is intra-node and says
> nothing about node count.** What Stage 0 still owes is the missing
> 4-core arch config, which does not exist in
> `scripts/tmp/generate_multinode_arch_sweep.py`'s
> `INSTANCE_COUNTS = (16, 64, 256, 1024)` and must be produced before
> this stage runs.

**Stage 1: weight-trace generation.** `scripts/generate_weight_traces.py`,
no Gurobi, `--workers` parallel. 36 combinations x 5 samples = 180
samples. Measured basis: **2-5 s per sample per (arch, layer)**
(`scripts/generate_weight_traces.py:29`).

> 16-core and 64-core thirds: ~6-15 min serial, **~1-2 min at 16
> workers**. The 4-core third is the problem: fewer cores means more
> ticks per sample (measured 316,280 ticks at 16 cores against 7,158 at
> 1024, `log/2026-08-05-cachesim-redesign-plan.md:88-92`), so expect
> roughly 4x the 16-core tick count. Allow **1-2 h wall** for the 4-core
> third. **This last figure is an extrapolation, not a measurement.**
> Disk: ~12 MB per compressed sample (620 files / 7.7 GB in the 0803
> corpus), so ~2-4 GB total. Not a constraint.

**Stage 2: spad baselines.**
`spad_oracle` is computed from the trace header and costs nothing.
`spad_nocsim` is `python -m nocsim.sim --schedule ... --simulate`, 180
runs, requiring the compiled backend (`cd src/nocsim/eventsim && make`).

> **No measured nocsim timing exists anywhere in the repo.** Estimate
> only: a compiled event simulator over a transaction CSV, on the order
> of seconds to a few minutes per run, so 1-6 h serial and minutes
> parallel. Measure one run before scheduling the rest.

**Stage 3: wcache sweep.** Tiers 0 through 4, **7,560 runs** (§4.4).

Two measured anchors bracket the per-run cost:

- The predecessor sweep produced **14,880 rows in 38:52 on 16 CPUs**
  (`profiling/0803_l1_l2_cache/README.md`, Slurm job 20823836) =
  **2.51 core-seconds per row**, including amortised trace ingest. That
  model was tick-atomic and functional - no ports, no MSHRs, no events.
- The wcache engine itself: **64,000 bursts -> 154,072 lines in 0.66 s**
  at 11 MB peak, on the `-O0` fixture build
  (`src/wcache/FINDINGS.md:340`). A real 16-core LoAS sample is roughly
  316,000 bursts, about 4.9x that, so ~3.3 s at `-O0` and perhaps 1-2 s
  at `-O2 -DNDEBUG`.

An event-driven timing model does more work per access than a functional
replay, so the planning figure is **15 core-seconds per row, bracketed
3-25**. It is an estimate; Tier 0 replaces it.

> **Reduced plan, recomputed for R2:**
>
> ```
> 7,560 rows x 15 core-s  =  113,400 core-s  =  31.5 core-hours
>                                            =  1.97 h on 16 CPUs
> bracket at 3 core-s:      22,680 core-s    =   6.3 core-h  =  0.39 h on 16
> bracket at 25 core-s:    189,000 core-s    =  52.5 core-h  =  3.28 h on 16
> ```
>
> So **~2.0 h on 16 CPUs, bracket 0.4-3.3 h** (was 1.4 h, bracket
> 0.3-6 h). Full factorial for comparison: `32,760 x 15 s = 491,400
> core-s = 136.5 core-hours = 8.5 h on 16 CPUs`.

**R2 broke the "it fits in one job" property, and that is the single
scheduling consequence worth flagging.** At the planning figure the
reduced campaign is now **1.97 h against a 2 h Slurm wall cap** - inside
it only by three minutes, which is not a margin. Plan for **two to three
resumable jobs for Stage 3 alone**, and note that at the pessimistic end
of the bracket (3.3 h) it is definitely two or more. The per-unit atomic
result cache (§9.1) already makes this free to do; what changes is that
it is now mandatory rather than a convenience.

**Hard requirement on D3, from a measured number.** Python `json.loads`
on one 15.54 MB gzipped sample took **20.84 s**
(`log/2026-08-05-cachesim-redesign-plan.md:88-92`; extrapolated to ~3.6 h
of parsing for the 620-file corpus). If the sweep driver re-parses the
trace once per configuration, the reduced plan pays roughly
`7,380 x 20 s = 41 hours` of parsing alone (7,560 minus the 180
oracle-adjacent rows that need no re-parse), which would dominate
everything above by an order of magnitude. R2 made this worse in
proportion to the grid: it was 29 hours at 108 configs. **The unit of
work must be one trace, materialised once, run against all configurations
for that trace in memory** - which is exactly what the planned
`wcache_sweep --config-grid` shape does
(`log/2026-08-05-cachesim-redesign-plan.md:535`) and what the 0803 driver
already did with its 24 configs per unit. §10 extends this from
"parse once" to "generate once, in flight, never write it down".

**Stage 4: merge and report.** `--merge-only` pass, then the comparison
pivot and figures.

> Minutes for the merge; the analysis is interactive.

### 8.3 Total

| Stage | Estimate | Basis |
|---|---|---|
| 0 MIP | ~2 min @ 8 workers | measured per-call |
| 1 tracegen | 1-2 h (4-core dominated) | measured per-sample, extrapolated for 4 cores |
| 2 nocsim | 1-6 h serial, unmeasured | **estimate only** |
| 3 wcache | **2.0 h @ 16 CPUs (0.4-3.3 h)** | two measured anchors, scaled to 7,560 rows |
| 4 merge | ~30 min | measured analogue |

> **Roughly one working day of wall-clock on Delta, split across four to
> seven 2-hour resumable jobs** - conditional on Stage -1 being complete
> and on Tier 0 confirming the per-run cost. R2 moved Stage 3 from 1.4 h
> to 2.0 h, which is *over* the 2 h wall cap once job startup is counted,
> so Stage 3 alone is now at least two jobs. The two figures most likely
> to be wrong are unchanged: the nocsim estimate (no measurement exists
> anywhere in the repo) and the 4-core tracegen extrapolation.

---

## 9. Results collection (described, not implemented)

### 9.1 Directory layout

Mirror `profiling/0803_l1_l2_cache/`, which is the pattern that already
worked on this cluster:

```
profiling/0820_phaseD_spad_vs_cache/
  README.md                  what was run, job id, wall time
  run_sweep.py               preview by default; --run to execute
  run_sweep.slurm            16 CPUs, 128 GB, 2 h
  grids/                     the tier definitions as data, not code
  results/                   per-unit atomic caches (resume lives here)
  per_core/                  gzipped per-core CSVs
  spad_vs_cache.csv          the merged summary
  artifact/                  build_artifact.py dashboard
```

Unit of work = one `(arch, n_cores, layer, sample)` trace. One unit
parses its trace once, runs every configuration in its tier against it,
and writes one atomic per-unit file. Rerunning the job resumes missing
units. Driver flags follow the existing one: `--run`, `--workers`,
`--unit-index`, `--merge-only`, `--results-dir`, `--out`.

### 9.2 Row schema

One row per `(arm, arch, n_cores, workload, layer, sample_idx, config)`.

- **Identity**: `run_id`, `git_commit`, `arm`
  (`spad_oracle | spad_wcache | spad_nocsim | cache`), `tier`.
- **Shared keys**: `arch`, `n_cores`, `workload`, `layer`, `sample_idx`.
- **Configuration**: `l1_size_bytes`, `l1_assoc`, `l2_size_bytes`,
  `l2_assoc`, `line_size_bytes`, `cin_block`, `cout_block`,
  `weight_bytes`, `l1_mshrs`, `l1_tgts_per_mshr`, `l2_mshrs`,
  `l2_tgts_per_mshr`, `l1_demand_reserve`, `prefetch_policy`,
  `prefetch_distance`, `l1_latency`, `l2_latency`, `l2_miss_latency`,
  `l2_banks`, `l2_ii`, `core_accept_ii`, `inclusion`, `policy`, and -
  **added by R2, see §4.5** - `l1_num_lines`, `l1_num_sets`, so that
  §4.5's two warning conditions are reconstructable from the CSV rather
  than only from a log line.
- **Headline**: `total_cycles` (the column G3 says D2 must add),
  `tick_base_total`, `stretch_cycles = total_cycles - tick_base_total`.
- **Memory**: `l1_hits`, `l1_accesses`, `l1_hit_rate`, `l2_hits`,
  `l2_accesses`, `l2_hit_rate`, `dram_accesses`, `dram_bytes`.
- **Stall attribution**, which must sum (V21): `stall_l1_slot`,
  `stall_l1_line`, `stall_l1_port`, `stall_l2_slot`, `stall_l2_line`,
  `stall_l2_port`, `stall_channel`, `stall_barrier`, `stall_total`.
- **Core schedule**: `core_stall_sum`, `fetch_latency_sum`,
  `hidden_latency` (subject to the G7 decision).
- **Prefetch**, which must sum: `pf_issued`, `pf_timely`, `pf_late`,
  `pf_wasted`, `pf_dropped_{array_hit,matching,no_slot,targets_full,reserve}`,
  `pf_coverage`, `pf_coverage_ceiling`, `pf_budget_exhausted`,
  `pf_pollution_evictions`.
- **Model health**: `padding_fraction` (mandated, `PROGRESS.md:894`),
  `port_bound_threshold` (`:1464`), MSHR occupancy p50/p95/max per level,
  `max_wait_depth`, `hits_downgraded_to_miss`, `events`,
  `events_per_cycle`, `sim_wall_seconds`.

`l2_demand_reserve` is **not** a column (G11).

### 9.3 The comparison report

A separate analysis stage - not the driver - joins each `cache` row to
its paired `spad_*` row on `(arch, n_cores, workload, layer, sample_idx)`
and adds `latency_ratio` and `storage_bytes = n_cores * l1_size_bytes +
l2_size_bytes`. Four figures carry the argument:

1. `latency_ratio` against L1 size, one line per line size, faceted by
   architecture x core count.
2. `latency_ratio` against L2 size, faceted the same way.
3. `latency_ratio` against prefetch distance, with the `d = 16`
   duplicate-check point marked.
4. **The headline**: a `storage_bytes` against `latency_ratio` Pareto
   scatter, all **180** configurations, with the spad's storage marked as
   a vertical line - **one line per core count now**, since under R2 the
   spad's storage scales with the core count (4224 / 4608 / 6144 KB, §2)
   rather than being a single figure. The claim in §2 is a claim about
   that plot.

R2 adds a fifth figure, because the storage saving now comes almost
entirely from the L2 and a total-only plot hides that:

5. `storage_bytes` **decomposed** into `n_cores * l1_size_bytes` and
   `l2_size_bytes`, stacked, at the Pareto-front configurations. This is
   what answers "which level did the saving come from", and §2 says it
   must be reported rather than left to the total.

### 9.4 Stage ownership

| Piece | Owner |
|---|---|
| Emitting one row per run | **D2** |
| Driver, unit cache, resume, merge | **D3** |
| Tier definitions as data files | **D3** (`grids/`) |
| Join, ratio, Pareto, figures | a new analysis stage, downstream of D3 |

---

## 10. In-flight trace generation (no intermediate storage)

Added to the request 2026-08-20: *"I would like to make sure the weight
trace generation is in-flight, with no intermediate storage."*
This section assesses feasibility and recommends a design. It implements
nothing.

### 10.1 How traces are materialised today

There is exactly one materialisation point, and it is a
build-then-dump:

- `src/tracegen.py:326-347`, `save_weight_trace(trace: LayerWeightTrace,
  path)`, whose body is `with gzip.open(tmp_name, "wt") as fh:
  json.dump(asdict(trace), fh)`. The **whole sample** is built as a
  Python dataclass, converted with `asdict`, serialised to JSON text and
  gzipped.
- `scripts/generate_weight_traces.py` calls it per sample and writes
  `<out-dir>/<arch>/<combo_tag>/<trace_dir>/<layer>/sample_NNNNN.json.gz`,
  default `outputs/weight_traces`, skipping files that already exist.
- Consumers then read those files back. wcache's planned contract is a
  process boundary: `wcache_run --config cfg.json --trace
  sample.json.gz` (`log/2026-08-05-cachesim-redesign-plan.md:535`).

The v2 document is, structurally, already a header plus an ordered record
sequence - which is why this is tractable:

```
{arch, trace_dir, layer_name, sample_idx, workload_dims,
 dram_num_steps, noc_num_steps,
 tiles[]:  {dram_i, noc_i, mac_cycles, lif_cycles, ticks[]}
   ticks[]: {tick, cores[]}
     cores[]: {core_id, weight_addresses[[kh,kw,cin,cout_start,cout_end], ...]}}
```

Canonical order is `dram_i -> noc_i -> tick -> core`, core fastest-varying
(`tracegen.merge_cores_by_tick:170`). Nothing back-references anything
earlier. The obstacle is the JSON *encoding*, which cannot be parsed
record by record, not the data's shape.

**Disk cost.** Measured corpus density is 620 files / 7.7 GB compressed,
about 12 MB per sample, and one such sample expands to **315.8 MB** of
JSON text (`log/2026-08-05-cachesim-redesign-plan.md:88`). The existing
`outputs/weight_traces` corpus is 155 layer directories / 7.7 GB
(`src/wcache/HANDOFF.md`), and a full 5-architecture x 10,000-sample
corpus was estimated at **2.15 TB**, scoped down to ~856 GB
(`log/2026-07-26-workflow-optimization-plan.md` lineage). For *this*
campaign specifically the figure is modest: 36 shared points x 5 samples
= 180 samples x ~12-50 MB is **2-9 GB**, which Delta absorbs without
noticing.

**So the honest argument for in-flight is not disk.** It is time and
correctness:

- **Time.** The round trip is `asdict` + JSON encode + gzip on the way
  out, then gunzip + JSON parse on the way in. The measured read half
  alone is **20.84 s of `json.loads` against 0.86 s of gunzip** for one
  sample - the cost is the JSON text encoding, not the compression. At
  180 samples that is over an hour of pure parsing, and the write half is
  the same work again in the other direction.
- **Correctness.** Regenerating for 4/16/64 cores means the current
  corpus is stale anyway (§8, G5), and a pipeline that never writes the
  intermediate cannot serve a stale one by accident.

### 10.2 Does the existing Phase D plan assume on-disk traces?

**Yes, in two places, and one of them is load-bearing.**

- The 08-05 contract is explicit: "**The boundary is a process boundary
  with JSON on both sides.** The back end binary takes a config JSON path
  and **a trace path**" (`:534-536`), with the rationale that "a sweep
  point that crashes or exceeds memory takes down one process rather than
  the Python driver holding the whole grid".
- v3's plan unit A3 is specified as a reader of format v2 *files*.

The deeper problem is the **shape of the interface, not the file path**.
`src/wcache/native/include/wcache/trace.h` defines `TileTrace` as a
**random-access query surface**, not a stream:

```cpp
virtual std::int32_t n_tiles() const = 0;
virtual std::int32_t n_cores() const = 0;
virtual std::int32_t n_bursts(CoreId core, std::int32_t tile) const = 0;
virtual const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
virtual LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
virtual LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const = 0;
virtual LocalTick tile_tail(std::int32_t tile) const = 0;
```

Note this **differs from the 08-05 plan's sketch** of `TraceReader` as
`bool next(TickBatch&)` (`:575`), which was pull-based and would have
streamed trivially. v3's built interface is indexed by `(core, tile, k)`.
Add this to the assessment in §1.3 as a further gap:

**G13 - the trace interface as built is random-access, and the in-flight
requirement is a change to it, not just to the file path.**

### 10.3 What makes it feasible anyway

Three properties of this model rescue it.

**(a) The engine only ever needs one tile.** Part 5's barrier is
machine-wide (N4): every core walks the same tile sequence and no core
enters tile `N+1` until all have cleared tile `N`. `trace.h`'s own
comment says "Trace time is only ever tile-local. The engine never uses
`tick_base`". So `TileTrace` can be backed by a **sliding window of one
tile** instead of the whole sample, with the same interface and no
change to the engine at all. At ~128 tiles per sample that turns
315.8 MB resident into roughly **2.5 MB resident**, a 100x reduction.

**(b) The producer is already incremental; only the middle buffers.**
The archmodel binaries write tick-by-tick through `write_tick_grouped`
(`src/archmodels/tick_output.h`) into an `std::ofstream` given as
`argv[3]`, so **pointing that stream at stdout makes the producer a true
stream with no logic change at all**. One level up,
`native_bridge._unpack_output` is already a generator
(`yield tile_idx, sample_idx, mac_cycles, ticks`). The buffering is in
one place: `tracegen.assemble_layer_traces` (`src/tracegen.py:240`)
consumes that generator into a `groups` dictionary before emitting
`LayerWeightTrace` objects, and `save_weight_trace` then collapses each
into one document.

**(b') No header field needs a global reduction.** `noc_num_steps`
(`assemble_layer_traces:263`) and `n_cores` both come from the *schedule*
(`NodeTileSpec.core_id`), not from the trace, so they are known before
generation starts. `mac_cycles` per tile is a max over that tile's cores
(`:278`) - tile-local. `tile_tail = mac_cycles - max_tick` - tile-local.
So a header-first stream is emittable without a prepass.

**(b'') There is already a binary wire format to copy.**
`src/cachesim/native_bridge.py:111` `_write_tick_data` emits

```
u32 n_ticks
  per tick: u32 n_cores
    per core: i32 core_id, u32 n_events
      per event: 5 x i32  (kh, kw, cin, cout_start, cout_end)
```

and the C++ side already reads it from **stdin** - today that stdin
happens to be a temp file opened with `subprocess.run(stdin=...)`
(`:188-191`), so switching to `Popen(stdin=PIPE)` needs **no C++ change**.
The design below is that format plus a header and tile framing.

**(c) nocsim does not consume the weight trace.** `src/nocsim/sim.py`
takes `--schedule <json> --layer <yaml> --arch <yaml>`; its inputs are
the MIP schedule and the configs, not the burst stream. **No tee is
needed.** Only wcache consumes the trace, which removes the hardest part
of a streaming design.

### 10.4 What would have to change, and what breaks

| Piece | Change |
|---|---|
| `TileTrace` implementation | A `StreamingTileTrace` holding a one-tile window, satisfying the existing pure-virtual interface unchanged. The engine never learns which reader it has - that separation is already decision B10/B23. **Nothing is being retrofitted here: A3 is unbuilt and `FakeTrace` (`tests/engine_fixture.h:122`) is the only implementation that exists, so the streaming reader can simply *be* A3's first implementation.** |
| Wire format | Not JSON text. The `native_bridge` binary format above, wrapped in tile framing: a header, then per tile a length-prefixed block plus that tile's `mac_cycles`. |
| Header | Must carry `n_tiles`, `n_cores`, `spatial_factors`, **`burst_dim` and `burst_stride`**, and the address field order - i.e. exactly U25 through U28. **RULED 2026-08-20 (R1): the burst axis and stride are needed, belong in the format, and are emitted by the trace-generation side, not supplied by the reader.** One header settles all four. Status: ruled, implementation pending. |
| Archmodel `main.cpp` (5 files) | Swap `for tile { for sample }` to `for sample { for tile }`, and allow `argv[3]` to name stdout. |
| `save_weight_trace` | Gains a sibling that writes the stream to a file descriptor instead of a path. `save_weight_trace` itself stays, for the debug dump (§10.6). |
| `wcache_run` / `wcache_sweep` | Accept `--trace -` (stdin) or `--trace fd:N` alongside a path. |
| Sweep driver (D3) | See §10.5: a stream is single-pass, and a config grid is not. |

**What breaks, stated plainly:**

1. **`tile_tail` needs the whole tile before the tile starts.**
   `tile_tail(tile) = mac_cycles[tile] - max_tick[tile]`, and `max_tick`
   is a maximum over that tile's cores. So the window granularity cannot
   be finer than one complete tile. This is a constraint, not an
   obstacle - it is why the window is a tile and not a burst.
2. **`n_tiles()` and `n_cores()` must be known before the first tile.**
   Today **neither is in the format**: that is U25 ("Nothing on disk
   states the machine's core count") and U26 (`spatial_factors` absent),
   plus U27 (burst axis and stride absent) and U28 (no declared address
   field order) - **four header fields the format does not carry**, and
   B156 explicitly "refused to write a reader that papers over the four
   gaps" (`PROGRESS.md:1117`). A streaming format **forces all four to be
   declared**, because a stream with no header is unreadable. This was
   the strongest argument in favour of the change, and **2026-08-20 the
   user ruled it (R1): U27's two fields are needed, belong in the format,
   and are emitted by the generator.** So this is no longer an argument
   for the design - it is a settled requirement on it. The in-flight
   requirement and the four open format questions have **the same fix**,
   and the campaign was going to regenerate the corpus for 4/16/64 cores
   anyway. What R1 leaves open is **B22's obligation row**, which was
   written against a header field that did not exist: with the field now
   ruled into existence, B22 stands as written and does *not* want the
   "the axis is a property of the reader" correction U27 offered as its
   alternative. `types.h` and `layout.h` carry B161's comments saying the
   reader supplies the two values; those comments become wrong the day
   the header lands and must be updated with it.
3. **The 08-05 crash-isolation rationale weakens.** A generator bound
   into the consumer's pipeline means a generator fault takes the
   consumer with it. Mitigated by keeping the process boundary (§10.5,
   option B) rather than moving to in-process binding.
4. **Determinism must be re-argued.** D3's exit criterion is
   "reproduces byte-identically" (`:1364`). With a file, the trace is
   fixed and only the engine must be deterministic. With a stream, the
   *generator* is now inside the reproducibility claim. `tracegen`'s
   sample selection is seeded (`sample_indices(n, seed=0)`), and the
   schedule is cached, so this is arguable - but it must be argued and
   tested, not assumed.
5. **The archmodel emits in the wrong nesting order.** The per-arch
   `main.cpp` runs `for tile { for sample }`, so one sample's tiles are
   interleaved across the whole output, while a stream needs
   `for sample { for tile }`. Two fixes, both small: invoke the binary
   once per sample (`sample_indices` of length 1), or swap the two loops
   in the five `main.cpp` files. The first costs process launches; the
   second touches five files and is the cleaner one. **This is the only
   change in the whole design that reaches into the architecture
   models.**
6. **Skip-existing resumability disappears.** Both generator modes resume
   by testing `sample_{i:05d}.json.gz` for existence
   (`scripts/generate_weight_traces.py:140, 200`). With nothing on disk
   there is nothing to test. The replacement is the *sweep* driver's
   per-unit atomic result cache (§9.1), which resumes on results rather
   than on inputs - strictly better, because it also catches a unit whose
   trace was regenerated.
7. **The generator's worker pools must move up a level.** Mode 1 chunks
   samples across a `multiprocessing.Pool`; mode 2 uses a
   `ProcessPoolExecutor` over `(trace_dir, layer)` with
   `SAMPLE_CHUNK_SIZE = 10` to bound peak memory after a recorded OOM. N
   workers cannot share one stdout pipe into one consumer. The workable
   shape is **one producer paired with one consumer per unit, with
   parallelism moved up to N independent pipeline pairs** - which also
   removes the reason `SAMPLE_CHUNK_SIZE` exists, since only one sample
   is ever live.
8. **Per-core ordering is safe.** The survey of 124 v2 layers and
   76,150,578 bursts found `gap` is exactly 1 everywhere and "no (core,
   tick) pair anywhere carries more than one burst"
   (`PROGRESS.md:942`), so burst index and local tick are in bijection
   inside a `(core, tile)`. Trace order is service order (I13). A stream
   that preserves emission order preserves everything the engine needs.

### 10.5 Design options

**Option A - in-process binding (pybind11 or a C++ generator).**
Lowest latency, no serialisation at all. Rejected: it puts the Python
generator inside the C++ address space, discards the crash isolation the
08-05 plan chose deliberately, and is the largest change to the least
finished part of the system.

**Option B - process boundary over a pipe. *(recommended)***
`generate_weight_traces.py --stream ... | wcache_sweep --config-grid
grid.json --trace -`. Keeps every advantage the 08-05 rationale names:
the binary is still runnable from a shell, a crash still takes down one
pipeline rather than the driver, and Slurm arrays over independent
pipelines is unchanged. The only new machinery is a binary record format
and a `StreamingTileTrace`. Backpressure is free - an OS pipe blocks the
generator when the consumer is behind, which is exactly the right
behaviour and needs no buffering logic.

**Option C - generator callback into the engine.** A push interface
where the generator drives. Rejected: it inverts control against an
interface (`TileTrace`) that is a pull-style query surface, so it would
require changing the engine as well as the reader.

**The single-pass problem, and the answer.** A stream can be read once;
a config grid has **180** points (R2). Three ways out, and only one is
good:

- Re-run the generator per configuration: 180x the generation cost.
  Unacceptable.
- Buffer the whole sample in memory and replay it: 315.8 MB resident,
  and it is "in-flight" only in the sense of not touching disk.
  Acceptable but timid.
- **Broadcast lockstep, recommended:** one reader holds the current tile
  window; every engine in the grid consumes that same tile; the window
  advances when all engines have finished it. Each engine keeps its own
  simulated clock (they diverge, and that is fine - the window is indexed
  by tile number, not by cycle), and every engine processes the same
  tile sequence in the same order. Resident memory becomes **one tile
  (~2.5 MB) plus N engine states**, and the measured engine footprint is
  11 MB peak (`src/wcache/FINDINGS.md:340`), so **180 engines is
  `180 x 11 MB ~= 2.0 GB`** plus the window - against Delta's 128 GB, so
  R2's larger grid does not threaten this design at all (it was ~1.2 GB
  at 108). This composes exactly with the one-tile window and with
  `wcache_sweep`'s existing reason to exist. Headroom check: even at 4
  concurrent pipeline pairs on one node the footprint is ~8 GB, still
  well inside 128 GB.

### 10.6 The debuggability cost, and how to pay it

Losing on-disk traces costs three things the current workflow relies on:
reproducing one sweep point from a shell, bisecting a bad result, and
the corpus surveys that discharged Q10 and Q11 (`PROGRESS.md:942`).

Keep all three with an **opt-in dump**: `--dump-trace <path>` on the
generator writes the same stream to a file as it passes, byte-identical
to what the consumer saw, and `wcache_run --trace <path>` replays it.
Off by default, so the normal path never materialises anything; on when
someone is debugging. This is a tee to disk rather than a tee to a second
consumer, and it costs nothing when unused. Pair it with
`--dump-trace-tiles N` to capture only the first N tiles, since a
two-tile slice is what `src/wcache/examples/` already uses as its fixture
corpus.

### 10.7 Effect on phasing, runtime and storage

This lands in **Stage -1** (§8.2), as work on A3 and D3, and it is not
free: it adds a wire format, a header definition that settles U25-U28,
and a broadcast-lockstep driver. It should be scoped as part of A3
rather than bolted on afterwards, because A3 is unbuilt and this decides
what A3 is.

Revised estimates:

| Quantity | On-disk | In-flight |
|---|---|---|
| Intermediate trace storage | 2-9 GB for this campaign | **0** |
| Trace serialise + parse cost | ~1 h+ of JSON encode/decode across 180 samples | ~0 (binary records, no text encoding) |
| Peak resident per pipeline | 315.8 MB (parsed sample) | ~2.5 MB window + engine states |
| Stage 1 (tracegen) as a separate stage | 1-2 h | **folded into Stage 3**; generation and simulation overlap instead of running in sequence |
| Stage 3 (wcache) | 1.4 h @ 16 CPUs | unchanged, unless generation becomes the limiter |

The one new risk: with the stages fused, **the generator may become the
bottleneck**. Trace generation is 2-5 s per sample against an estimated
15 core-s per engine run, so for a 180-config grid the engine side
dominates by a wide margin and the pipe will sit full. For a *single*
configuration the generator would dominate instead. That is an argument
for always running a grid, never one point at a time - which the campaign
does anyway.

### 10.8 Open decisions this forces

**Q9 - Is the disk saving actually the goal, or is it the round trip?**
**RESOLVED 2026-08-20 (R4): the round trip and the staleness risk, not
disk.** The requirement is confirmed as the user's own. So the change
**is** worth doing and **is** scoped into A3 now, and §10's cost/benefit
should be read against time and correctness rather than against the
2-9 GB of intermediate storage, which was never the point.

**Q10 - Does the opt-in dump satisfy the "no intermediate storage" rule?**
**RESOLVED 2026-08-20 (R4): yes, an opt-in debug dump is acceptable.**
§10.6's `--dump-trace` design stands: off by default, so the normal path
materialises nothing; on when someone is debugging. The three
debuggability affordances it preserves (shell reproduction of one sweep
point, bisection, corpus surveys) are kept without weakening the rule.

**Q11 - Settle U25-U28 as part of the stream header?** **RESOLVED
2026-08-20 (R1): YES.** The plan recommended it and the user ruled it,
via U27 specifically: the burst axis and stride are needed, belong in the
format, and are emitted by the trace-generation side rather than supplied
by the reader. `burst_dim` and `burst_stride` therefore join `n_cores`,
`spatial_factors` and the address field order in **one header**, and
U25-U28 are settled together. Status: **ruled, implementation pending**
in A3 plus `tracegen.py` plus the two header comments B161 corrected.
The reasoning is unchanged and is now the user's: a stream needs a
header, the four gaps are all missing header fields, B156 refused to
write a reader that papers over them, and the corpus is being regenerated
regardless.

**Q12 remains open** and is the only one of the four this section raised
that the 2026-08-20 review did not settle.

**Q12 - Accept the determinism re-argument?** With a stream, the
generator enters the "byte-identical reproduction" claim (D3's exit
criterion). Confirm that a seeded generator plus a cached schedule is
enough, or require the dump-and-replay path for any result that goes in a
paper.

---

## 11. Open questions the user must decide

Q1-Q8 below; the four questions the in-flight requirement adds (Q9-Q12)
are in §10.8, next to the reasoning that raises them.

**Status after the 2026-08-20 user review:** Q1 **resolved**, Q2
**mostly withdrawn**, Q9, Q10 and Q11 **resolved** in §10.8. Q3, Q4, Q5,
Q6, Q7, Q8 and Q12 remain **open and undecided**; the review deliberately
left them so.

**Q1 - Is the spad L1 per core or shared? RESOLVED 2026-08-20 (R2).**
**Per core, 32 KB, at every core count**, so the aggregate scales with
the core count; the L2 stays 4 MB shared. Note the figure moved as well
as the reading: the request's 512 KB is gone, and 32 KB is the top of the
per-node range in the repo's own arch grid
(`scripts/tmp/generate_multinode_arch_sweep.py`, 2-32 KiB per node,
512 KiB-4 MiB shared). Consequences, all applied above: the **L1 cache
axis becomes {2, 4, 8, 16, 32} KB** (§4.2), 180 cache configs, every tier
count and runtime recomputed (§4.3, §4.4, §8), a new nominal of 8 KB
(§4.4), the decision rule evaluated per core count with the saving now
coming almost entirely from the L2 (§2), the layer rationale re-grounded
on per-core working sets (§3.3), new small-cache constraints for D1
(§4.5), and G12 closed (§1.3).

**Q2 - 4 cores: keep, or move to 8? MOSTLY WITHDRAWN 2026-08-20 (R3).**
The MIP-infeasibility half of this question rested on reading the LoAS/PTB
`COUT: {spatial: 4}` dataflow cap as an inter-node limit. **It is
intra-node** - four output channels handled spatially inside one node's
PE array - so there is no feasibility argument against 4 cores and no
feasibility probe is owed. **4 / 16 / 64 cores stand.** What is left is
not really a question any more, just two facts to carry into the
write-up: 4 is below v3's settled 8-256 range (`PROGRESS.md:738`) and is
kept as a **deliberate exception the user chose**, and the 4-core arch
config still has to be produced because
`INSTANCE_COUNTS = (16, 64, 256, 1024)` does not contain it.

**Q3 - VGG16 deep: `layer_09` or `layer_12`? STILL OPEN.** Reassessed
under R2 in §3.3 and the outcome was **re-justify, do not swap** - the L2
bracketing that motivates both picks is untouched by the L1 axis change,
and the L1 half of the rationale was replaced rather than repaired. So R2
gives no new reason to move either pick, and the question is left exactly
where it was.

The question, restated: VGG16 deep, `layer_09` or `layer_12`? And
ResNet-19 deep,
`layer_16` (1125 KB, on the L2 ceiling) or `layer_19` (2304 KB, literally
deepest but a duplicate capacity point)? §3.3 argues for `layer_09` and
`layer_16`; the alternative is defensible if "deepest layer" matters more
than covering the capacity boundaries.

**Q4 - `l1_mshrs = 16` (gem5 standard library) or `4` (gem5 classic)?**
See §6.3. gem5 has no library default at all, so this is a choice between
two gem5 example families, and the classic value makes the prefetch axis
inert for Spinalflow. The plan proposes 16 with 4 as a labelled
calibration row; confirm.

**Q5 - Which prefetch figure of merit?** G7: `core_stall - fetch_latency`
measures identically zero. D2 must pick the replacement before Tier 2.

**Q6 - Do the Q13 grid and this campaign merge?** v3 already specifies an
`l1_mshrs` x `prefetch_distance` grid with sizes fixed. This campaign
fixes MSHRs and sweeps sizes. Two campaigns, or one crossed grid? Crossing
them multiplies the run count by 5 and is not recommended; running Q13 as
a separate, smaller study at the nominal size point is.

**Q7 - Is `spad_nocsim` required?** Given that V1 gives a metric-matched
scratchpad baseline inside wcache for free (G8), nocsim's role reduces to
an independent cross-check on a different model. That is worth having,
but it is 180 runs of unmeasured cost against a quantity that is not
directly comparable. Keep it as a cross-check, or drop it?

**Q8 - Accept or reject `l2_demand_reserve` at config load?** Still an
open coordinator call (B159, `PROGRESS.md:1115`). Rejecting is the safer
default: a dead knob that loads silently is a knob someone will sweep.

---

## Appendix. Provenance of every number used above

| Number | Value | Source | Kind |
|---|---|---|---|
| MIP solve cost | 1.5-2.0 s / combination | `log/2026-07-30-tracegen-refactor-and-multinode-sweep-plan.md:24` | measured |
| Gurobi worker ceiling | 8 clean, 16 stalls, 64 crashes | same | measured |
| Trace generation | 2-5 s / sample / (arch, layer) | `scripts/generate_weight_traces.py:29` | measured |
| Prior sweep throughput | 14,880 rows / 38:52 / 16 CPUs = 2.51 core-s per row | `profiling/0803_l1_l2_cache/README.md` (job 20823836) | measured |
| wcache engine speed | 64,000 bursts -> 154,072 lines in 0.66 s, `-O0` | `src/wcache/FINDINGS.md:340` | measured |
| Python trace parse | 20.84 s for a 15.54 MB gzipped sample | `log/2026-08-05-cachesim-redesign-plan.md:88-92` | measured |
| Tick scaling with cores | 316,280 ticks @ 16 cores vs 7,158 @ 1024 | same | measured |
| Corpus density | 620 files / 7.7 GB compressed | `src/wcache/HANDOFF.md` | measured |
| Prefetch `fetch_latency` curve | 6600 / 3213 / 2067 / 1155 / 825 at d = 0,1,2,4,8 | `src/wcache/PROGRESS.md:869` (U19) | measured |
| Burst spans | LoAS 16, PTB 16, Spinalflow 64 cout | `src/wcache/examples/manifest.json` | measured |
| `gap` in corpus | `gap_min = gap_max = 1` | same | measured |
| Layer shapes | §3.2 table | `input_trace/loas/*/layer_*.npy` headers, read 2026-08-20 | measured |
| `weight_bytes` | 1 (`BW_WEIGHT: 8`) | `configs/arch/loas.yaml` | repo config |
| Corpus survey scale | 155 layer dirs, 124 format v2 + 31 legacy v1, 76,150,578 bursts | `src/wcache/PROGRESS.md:942` | measured |
| `gap` over the corpus | exactly 1, min and max alike; no (core, tick) pair carries two bursts | same | measured |
| `tile_tail` over the corpus | never 0; 1 on 116 of 124 layers, 1-22 on the other 8 (all ptb, mode 21) | same | measured |
| gzip ratio on a trace | ~19.5x (9.64 MB -> 0.49 MB) | `scripts/generate_weight_traces.py` docstring | measured |
| gem5 cache parameters | §6.2 table | live `stable` HEAD `62c7bf28…`, fetched 2026-08-20 | fetched source |
| eDRAM latencies | §7.2 tables | per-row citations in §7.2 | mixed: see the measured / modeled labels there |
| Spad L2 4 MB precedent | DaDianNao: 4 MB/tile eDRAM weight store. **The 512 KB/tile input-buffer half of this row no longer anchors anything**: R2 set the spad L1 to 32 KB per core, so only the 4 MB L2 keeps its DaDianNao anchor (which is also what §7's `l2_latency = 10` rests on) | `survey-output/dnn-noc-buffer-sizes/phase6_report/report.md`, citing Chen et al., MICRO 2014, doi:10.1109/MICRO.2014.58 | prior survey |
| Spad L1 32 KB per core | top of the per-node range in this repo's own arch sweep (2-32 KiB per node, 512 KiB-4 MiB shared) | `scripts/tmp/generate_multinode_arch_sweep.py`; **fixed by the user's R2 ruling**, 2026-08-20 | **user ruling**, consistent with a repo config |
| `COUT: {spatial: 4}` is intra-node | "One TPPE handles each spatial output channel" | `configs/dataflow/loas.yaml` comment, read 2026-08-20; **confirmed by the user's R3 ruling** | repo config + **user ruling** |
| Per-core distinct addresses, 2-tile fixture slice | loas/spinalflow vgg16 `layer_01`: 47-48 per core against a 117-address union; ptb resnet19 `layer_01`: 27-48 per core against 144 | `src/wcache/examples/*.json`, counted 2026-08-20 | measured, but **two tiles of one sample at 8 cores** - an indication, not a workload measurement |
| Per-core per-tile working set | 24 addresses x 16 B = **384 B**, all three archs | same | same caveat; the basis for G14 |
| Cross-tile per-core reuse | loas/spinalflow 0-1 of 24 addresses shared between adjacent tiles; ptb 11-21 of 24 | same | same caveat |
| Per-core weight slice by core count | `footprint / n_cores`, 0.56-576 KB over the 12 (layer, cores) points | §3.3 table | **estimate, and a lower bound the fixture slice shows is not met** |
| wcache per-run cost | 15 core-s (bracket 3-25) | scaled from the two anchors above | **estimate** |
| nocsim per-run cost | seconds to minutes | none exists in the repo | **estimate, unverified** |
| 4-core tracegen cost | ~4x the 16-core cost | extrapolated from the tick-scaling row | **estimate** |
| All run counts and runtimes after R2 | 180 configs; tiers 180 / 360 / 2,520 / 4,320 / 180 = 7,560; full factorial 32,760; ~2.0 h on 16 CPUs | arithmetic shown in §4.3, §4.4 and §8.2 | **derived**, on top of the 15 core-s **estimate** |
