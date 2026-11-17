# Validating our simulator against Sparseloop (paper RQ1) — high-level plan

Status: proposal for review. No step-by-step plan, no code, no experiments are
implied by this document; it fixes *what* the comparison is and *what counts as
a pass*, so that a later plan can fill in the mechanics.

Sources read for this plan: `src/lays/nocsim/` (whole package),
`src/lays/weight_trace_gen/` and `docs/weight_trace_gen_archs.md`,
`src/lays/scheduler/objectives/`, `examples/arch/*.yaml`;
`/u/yyu9/projects/2027_ASPLOS_neuro_cache/src/{05_theory,08_evaluation,09_discussion}.tex`;
the Sparseloop MICRO'22 paper (`/u/yyu9/projects/sparseloop/sparseloop-micro22.pdf`)
and its artifact (`/u/yyu9/projects/sparseloop/micro22-sparseloop-artifact/`).

---

## 1. What RQ1 actually requires

RQ1 is currently one line in the paper: "validation of our given simulator,
compare with the other performance simulator to see the difference"
(`src/08_evaluation.tex:7`). The subsection that follows it still carries the
*previous* RQ1 — off-chip energy and unused weights
(`src/08_evaluation.tex:40-44`) — so the evaluation text and the question list
disagree today. Resolving that is part of RQ1's scope, not a side issue: the
plan below assumes the new reading (simulator validation) and that the
energy/unused-weight material moves elsewhere.

Read as validation, RQ1 has to deliver three things, and they are not the same
claim:

1. **Credibility.** Our pipeline is new and unvalidated. A reviewer needs
   evidence that the numbers RQ2–RQ5 rest on are not artifacts of our own
   modeling choices. The only practical evidence available is agreement with an
   independent, peer-reviewed model on the subset of behavior both can express.
2. **Differentiation.** The paper claims in `src/09_discussion.tex:15` that
   DNN-oriented schedulers and models, Timeloop among them, "model no timestep
   loop or neuron state". RQ1 is where that claim gets substantiated
   quantitatively rather than asserted. Sparseloop is the strongest available
   stand-in for that class: it is the state-of-the-art analytical model for
   *sparse* accelerators, so it is the hardest baseline for us to claim to
   extend.
3. **Characterization of the gap.** "See the difference" is the honest framing.
   Where we and Sparseloop disagree, RQ1 must say which abstraction causes it
   and in which direction, with an explanation per divergence rather than a
   single aggregate error number.

A fourth thing RQ1 must *not* do: Sparseloop is not ground truth. Its own
accuracy is 0.1%–8% average error against cycle-level baselines and silicon
(Sparseloop §6.3), measured on dense-ish DNN and GEMM workloads, none of them
spiking. Disagreement is therefore a two-sided finding, and the plan below never
treats a Sparseloop number as the true value.

---

## 2. What each side models

### 2.1 Our pipeline

Four stages (`src/05_theory.tex:41-47`):

- **Scheduler** — a CoSA-style MIP over a three-level loop nest
  (NodeLevel / NoCLevel / OffChip), minimizing a weighted sum of a log-scale
  temporal-iteration surrogate, a traffic term, and a negative utilization
  reward (`src/lays/scheduler/objectives/combined.py:15-45`,
  `objectives/compute.py:1-12`). Output is an exact schedule, not a search
  trace.
- **Weight-trace generator** — replays a *captured spike tensor* through a
  C++ model of each target core and emits, per tile, the weight addresses
  fetched and the cycle count (`docs/weight_trace_gen_archs.md`, "The short
  version"). This is where sparsity enters our pipeline, and it enters as
  **real data, not a distribution**.
- **NoC simulator** — turns the schedule into a transaction dependency graph
  (unicast / multicast / count) and replays it as discrete events. Two
  independent cost models coexist:
  - *Static metrics*: `unicast_hops`, `multicast_hops`, `dram_cost`, each
    per-tensor (`src/lays/nocsim/core/generator.py:67-69`). Hops are
    XY-routed Manhattan distance plus a flit term
    (`core/generator.py:116`), multicast is charged by its farthest receiver
    (`core/generator.py:150-152`), and DRAM traffic is charged
    `ceil(packets x dram_latency)` with **no** mesh-link term at all
    (`core/generator.py:119`, `transactions/dram.py:26-34`).
  - *Latency*: the compiled `eventsim` backend, which claims an entire route
    for a transaction's full duration, serializes each port to one
    transaction at a time, and dispatches when dependencies, actor, and every
    link on the route are free (`src/lays/nocsim/eventsim/EventSim.h:5-22`).
    Invoked via `sim.py:198`.
- **Cache simulator** — replays the weight-address stream against a cache.
  Out of scope for RQ1 as framed here (Sparseloop models buffers/scratchpads,
  not caches); see §6.

Compute time is *not* modeled analytically in the NoC simulator. Each schedule
step is charged the per-tile cycle count the trace generator already measured
(`src/lays/nocsim/combine.py:346-349`), or, when running live, the **max over
that step's cores** (`combine.py:350-360`) — the step finishes when its slowest
PE does. The stored number is already that max
(`src/lays/nocsim/step_cycles.py:78-82`).

What we do **not** model: energy, power, area. There is no energy back end in
the tree; the only mention is a note about possible future per-PE energy/area
modeling (`src/lays/parsers/arch.py:287`), and the paper's own methodology
leaves energy as a TODO (`src/08_evaluation.tex:33-34`).

### 2.2 Sparseloop

Three decoupled analytical steps on top of Timeloop (Sparseloop §5):

1. **Dataflow modeling** — Timeloop's dense analysis: coordinate-space tiling
   of each tensor per the given loop-nest mapping, then per-level dense traffic
   from tile stationarity.
2. **Sparse modeling** — per-tile effects of three *sparse acceleration
   features* (SAFs): representation format, gating, skipping. Fibers are
   characterized **statistically** by a density model — fixed-structured,
   uniform, banded, or actual-data (Sparseloop Table 4) — because examining
   every fiber is too slow for DSE.
3. **Micro-architectural modeling** — capacity-validates the mapping, then
   derives cycles from actual plus gated accesses and computes, throttled by
   per-level bandwidth, and energy from an Accelergy ERT/ART
   (`micro22-sparseloop-artifact/.../input_specs/{ERT,ART}.yaml`).

Explicitly out of its scope: "design-specific micro-architectural analysis,
e.g., impact of an exact routing protocol" (Sparseloop §5.4). It assumes no
bank conflicts, which the paper names as a source of its DSTC error
(Sparseloop §6.3.3). There is no network topology, no hop count, no
contention, and no DRAM timing model — off-chip is a storage level with a
bandwidth.

### 2.3 Fidelity side by side

| Aspect | Ours | Sparseloop |
|---|---|---|
| Mapping | solved by MIP, one exact schedule | supplied, or searched over a mapspace |
| Sparsity input | captured spike tensor, replayed | density model (incl. actual-data) |
| Sparsity effect | per-tile fetch list + cycle count from a per-arch core model | per-tile access counts from SAF analyzers |
| Compute time | measured per tile, max over cores | derived from actual+gated accesses, bandwidth-throttled |
| Interconnect | 2-D mesh, XY routing, link/port contention | none (storage levels + bandwidth) |
| Off-chip | port occupancy `ceil(pkts x dram_latency)` | storage level with bandwidth |
| Multi-node | yes (K-chain, T-chain, mesh) | single accelerator topology only |
| Energy / area | none | Accelergy ERT/ART |
| Granularity | per transaction, discrete event | closed-form per level |
| Runtime | minutes–hours per layer-sample | >2000x faster than cycle-level (Sparseloop §6.2) |

The two models are **complementary, not redundant**: the only quantity both
produce today is a cycle/latency count, plus per-level access counts if we
derive ours from the transaction list.

---

## 3. Mapping our designs onto Sparseloop's representation

Sparseloop takes four inputs (Sparseloop §5.1): workload (Einsum shape +
densities), architecture, SAFs, mapping. Each maps onto us with a different
amount of friction.

### 3.1 Workload — partly expressible

Our layer is `KH KW CIN COUT HO WO T` (`examples/workloads/sample_snn_layer.yaml`).
Six of the seven dimensions are an ordinary CNN Einsum and translate directly.
`T` does not: Einsum has no sequential state, and our `T` axis carries the
membrane potential forward (`vmem`), which is why our NoC simulator needs a
T-chain at all (`src/05_theory.tex:248-258`). Options, in order of preference:

- **Treat T as a batch-like outer dimension and drop the LIF/vmem dependency.**
  Honest, simple, and it bounds the comparison to the weight/psum traffic both
  sides model. It is also exactly the "no timestep loop or neuron state"
  limitation the paper asserts, which makes the restriction itself a result.
- Encode vmem as a third data-space read-written along T. Expressible as an
  Einsum tensor, but Sparseloop will still schedule it without the serial
  ordering constraint, so it buys fidelity we cannot check.

Spike density becomes the input tensor's density. Our traces are real, so the
**actual-data** density model is the right setting for the headline comparison;
a **uniform** run at the same measured density is worth having as a second point
because the difference between them isolates "statistical approximation of
actual data", the first of Sparseloop's own three error sources (§6.3). That
pairing is precisely what Sparseloop's own Fig. 12 validation does
(`fig12_eyerissv2_pe_setup/ref_outputs/uniform_actual/`).

### 3.2 Architecture — expressible for single-node, not for multi-node

Our single-node archs (`single_node: true`, e.g. `examples/arch/loas.yaml`) are
a PE array fed from one buffer level with an off-chip level behind it. That is a
standard Sparseloop architecture. Our multi-node archs
(`examples/arch/*_multinode.yaml`, 128 nodes with a shared 1 MiB-per-tensor GB)
are **not**: the K-chain and T-chain are node-to-node transfers over a mesh,
which Sparseloop has no vocabulary for. Multi-node is therefore outside the
comparable set, and RQ1 should say so rather than approximate it.

### 3.3 Mapping — the key enabler

Because Sparseloop accepts an *exact* mapping — the artifact's DSTC setup is
driven that way, by a hand-written loop nest
(`fig13_dstc_setup/input_specs/Os-mapping.yaml`), while its other four setups
run the mapper — and because our scheduler is CoSA-style over a
Timeloop-shaped loop nest, we can feed Sparseloop our solved schedule instead
of letting its mapper search. This is what makes the
comparison apples-to-apples: same dataflow, same tiling, two models. Running
Sparseloop's mapper instead would conflate "is our model right" with "is our
scheduler's choice good", which is RQ2's question, not RQ1's. (A secondary,
clearly-labeled experiment comparing our MIP schedule against Sparseloop's
best-found mapping is attractive, but it belongs to RQ2.)

### 3.4 Sparsity mechanisms — where the taxonomy runs out

Our five core models and what each does, from `docs/weight_trace_gen_archs.md`
§8 and the per-arch sources:

| Arch | Mechanism (our model) | SAF equivalent | Expressible? |
|---|---|---|---|
| SpinalFlow | one weight fetch per spike, walked t-outermost (`spinalflow/SpinalFlowGen.h:4-9`, loop at `:61-64`) | skipping of W conditioned on I, T innermost-free | **yes** |
| LoAS | one fetch per `(kh,kw,cin)` that spikes at *any* t (`loas/LoASGen.h:3-8`, implemented at `:73-92`) | skipping conditioned on the OR over T of I | **yes**, if T is flattened into the condition |
| PTB | LoAS's addresses, plus a systolic-timing formula over merged non-overlapping lines (`ptb/PTBGen.h:11-15` and `:126-144` for the merge, `:21-26` for the cycle model) | addresses: as LoAS. Timing: none | **partly** — traffic yes, cycles no |
| Prosperity | reuses an earlier row whose bitmask is a subset, fetches only the difference (`prosperity/ProsperityGen.h:11-18`, subset test at `:141-148`) | none: this is computation reuse, not gating or skipping | **no** |
| GustavSNN | fetches a weight once per HO row, with up to *wave-width* rows in parallel (`gustavsnn/GustavGen.h:3-12`) | none: reuse across rows + intra-core parallel issue | **no** |

This is the single most important structural finding in this plan. Sparseloop's
taxonomy is deliberately three SAFs (format, gating, skipping) applied per
storage level, and two of our five architectures save work by a mechanism that
is none of the three. So:

- SpinalFlow and LoAS are the **validation targets**.
- PTB is a **partial** target: traffic comparable, cycle count not.
- Prosperity and GustavSNN are **demonstrations of the gap**, and the right
  result for them is a statement of inexpressibility plus, optionally, the
  size of the error a best-effort Sparseloop encoding makes.

Note also a structural constraint on our side: LoAS/PTB/SpinalFlow tiles are one
output pixel, and all 198 cached schedules for these archs have `HO=WO=1`
(`docs/weight_trace_gen_archs.md`, "Assumptions and running them"). Any layer
chosen for RQ1 must respect that, or the bridge silently uses only the first
pixel.

---

## 4. Comparison axes and metrics

Only compare what both sides independently produce. Three tiers:

**Tier A — directly comparable.**

- *Per-layer cycle count*: our `eventsim` `total_cycles` (`sim.py:393`) against
  Sparseloop's `Cycles` summary stat. For single-node archs this is the
  headline number.
- *Per-tensor off-chip traffic (words or bytes)*: ours derivable from the
  transaction list's weight/psum/vmem DRAM transfers; Sparseloop's from the
  backing-storage level's actual scalar reads/fills/updates. Sparseloop also
  separates *algorithmic*, *actual*, *gated*, and *skipped* accesses per level,
  which is a finer breakdown than we produce and a good diagnostic when the
  totals disagree.
- *Sparsity-driven savings ratio*: each side's sparse result normalized to its
  own dense result. This is the most robust axis, because it cancels
  per-model constant factors, and it is the form Sparseloop's own validations
  take (its Fig. 13 reports latency normalized to dense).

**Tier B — comparable with an assumption we must declare.**

- *On-chip (buffer) access counts*: ours are implied by the transaction list and
  the per-tile fetch counts rather than directly counted, so any comparison
  here rests on a derivation we write down.
- *Weight fetch counts*: our trace generator's fetch-burst counts
  (`docs/weight_trace_gen_archs.md`, "Real numbers") against Sparseloop's actual
  weight-level reads, after agreeing on what one "access" is — our burst covers
  a `cout` range of 16 or 128 weights, Sparseloop counts scalars.

**Tier C — not comparable, report one-sided.**

- *Energy, power, area*: Sparseloop produces them, we do not (§2.1). Either
  exclude them from RQ1 or, better, note that Accelergy/CACTI is the intended
  back end for both sides later, so the RQ3–RQ5 energy numbers and the
  Sparseloop ones will eventually share a cost model.
- *NoC hop counts, link contention, multi-node chain latency*: we produce them,
  Sparseloop has no equivalent.
- *Cache behavior*: ours only.

---

## 5. Proposed validation methodology

A four-stage ladder. Each stage adds exactly one source of disagreement, so
when a number moves we know what moved it.

**Stage 0 — dense, single-node, no sparsity.** Same layer, same mapping, both
models with sparsity disabled (dense core model on our side,
`DenseStaticComputeModel`, `src/lays/nocsim/combine.py:225`; no SAFs on
Sparseloop's). This tests the shared Timeloop-style dataflow accounting and
nothing else. Any disagreement here is a bug or a unit mismatch, not a
modeling difference, and must be resolved before Stage 1.

**Stage 1 — dense, add our interconnect.** Same as Stage 0 with `eventsim`
enabled. The difference between Stage 0 and Stage 1 on our side *is* the
contention and routing term Sparseloop cannot model — a number worth reporting
in its own right, since it quantifies what an interconnect-free analytical model
omits.

**Stage 2 — sparse, single-node, expressible archs.** SpinalFlow and LoAS,
real spike traces on our side; Sparseloop twice, once with the actual-data
density model and once with uniform at the same measured density. Three numbers
per layer (ours, Sparseloop-actual, Sparseloop-uniform) decompose the error into
"statistical approximation" versus "everything else". Add PTB for the traffic
axis only.

**Stage 3 — the inexpressible archs and multi-node.** Prosperity, GustavSNN, and
all multi-node configurations. Here the deliverable is not an error bar but a
statement, per design, of which mechanism has no SAF encoding and what the
best-effort encoding over- or under-predicts.

**Workloads.** The paper's methodology already fixes two sparse and two dense
representative layers (`src/08_evaluation.tex:21`), though their measured spike
densities are still a TODO (`:22`) — so RQ1 cannot yet state the density each
Sparseloop run should be parameterized with, which is the same open end as the
`HO=WO=1` question in §7.
RQ1 should use that same set so RQ1 and RQ2–RQ5 are about the same workloads,
subject to the `HO=WO=1` schedule constraint of §3.4. Sample count per layer is
still a TODO in the paper (`src/08_evaluation.tex:31`) and matters here: our
side varies per input sample, Sparseloop's actual-data model is run per tensor,
so RQ1 needs to say whether it compares per-sample or sample-averaged.

### Acceptance criteria

Stated as a pass/explain bar, not pass/fail: a miss is a finding, provided it is
attributed.

| Stage | Axis | Pass | Explain-or-fail |
|---|---|---|---|
| 0 | cycles, per-level accesses | within 2% | any gap > 2% must be traced to a definitional difference, in writing |
| 1 | our cycles, Stage 1 vs Stage 0 | n/a — reported, not bounded | — |
| 2 | per-layer cycles, actual-data density | within 10% | > 10% must name the responsible abstraction and its direction |
| 2 | savings ratio vs dense | within 10%, and same ordering across layers | a sign or ordering inversion is a hard fail; it means the models disagree about the design's merit |
| 2 | off-chip traffic per tensor | within 10% | as above |
| 2 | uniform vs actual-data spread | reported | — |
| 3 | all | no numeric bar | each design gets a named, argued inexpressibility |

The 10% figure is set against Sparseloop's own validated accuracy of 0.1%–8%
average error (Sparseloop §6.3) and the 0.935–1.005 per-layer cycle ratios in its
Eyeriss-v2 validation data
(`fig12_eyerissv2_pe_setup/results-summary/num_cycles.csv`). Agreement inside
our own band is the strongest claim available; **ordering agreement matters more
than absolute agreement**, because every downstream RQ is a comparison between
designs rather than an absolute number.

---

## 6. Risks and known gaps

**Risk 1 — circularity.** Nothing stops a reviewer from observing that we feed
Sparseloop *our* schedule and *our* density, so agreement partly reflects shared
inputs. Mitigation: Stage 0 isolates the shared dataflow accounting, and the
distinctive claims live in Stages 2–3 where the mechanisms differ. The plan
should state the shared inputs explicitly rather than let them be discovered.

**Risk 2 — the comparable set is small.** Two of five architectures validate
cleanly, one partly, two not at all; multi-node not at all; energy not at all.
RQ1 therefore cannot be "our simulator is validated". It can be "our simulator
agrees with the state-of-the-art analytical model wherever that model can
express our designs, and we show exactly where it cannot". That is a defensible
and, for this paper, more useful claim — but it needs to be the stated claim from
the start, not a retreat.

**Risk 3 — unit and definition mismatches will dominate early effort.** A
"weight access" is a 16- or 128-weight burst for us and a scalar for Sparseloop;
our DRAM cost is port-occupancy cycles, not bytes; our hop metric mixes a
distance term and a flit term in one integer (`core/generator.py:116`). None of
this is hard, all of it is easy to get silently wrong, and Stage 0 exists to
catch it.

**Risk 4 — Sparseloop's own error is not negligible and not uniform.** It is
optimistic about micro-architecture (no bank conflicts, Sparseloop §6.3.3) and
its uniform density model mis-predicts intersections by up to 7% on
doubly-sparse layers (§6.3.2). Spiking workloads are far outside its validated
envelope. Treat every disagreement as two-sided.

**Risk 5 — T is the crux and the hardest thing to compare.** Our whole
contribution lives around the timestep loop and neuron state, and that is
exactly what Sparseloop cannot represent. The validation is therefore strongest
precisely where our contribution is weakest, and silent where it is strongest.
This is unavoidable with any DNN-oriented baseline and should be said plainly;
it is also the reason Stage 3 is a deliverable rather than an appendix.

**Risk 6 — toolchain and effort.** The artifact is Docker-based
(`micro22-sparseloop-artifact/docker-compose.yaml.template`, with
`accelergy-timeloop-infrastructure`), and its five provided setups are a
SpMSpM format comparison, an Eyeriss-v2 PE on MobileNet, a DSTC GEMM study, an
STC study, and Eyeriss on AlexNet conv1-5 — none of them a template for an SNN
layer, and only the DSTC one driven by a fixed mapping rather than the mapper.
Standing up a correct
architecture + SAF + mapping encoding for even one of our archs is a real
engineering task and is the gating item for the step-by-step plan.

**Risk 7 — paper-text inconsistency.** The RQ list and the RQ1 subsection
disagree (§1), and the energy/unused-weight material has to land somewhere. That
is an editorial decision for the user, not something this plan should presume.

---

## 7. What I could not determine

- **Whether any Sparseloop/Timeloop SNN encoding already exists** in the wild
  that handles a timestep axis. I did not search outside the two local
  repositories.
- **Whether `lif_cycles` is produced by all five core models** or only some. It
  is carried through the per-step cycles file
  (`src/lays/nocsim/step_cycles.py:50-51`) and defaults to 0 when absent
  (`combine.py:349`), but I did not read each core model to confirm which
  populate it. This matters for the cycle axis in Stage 2.
- **The exact off-chip byte counts our pipeline can report.** `dram_cost` is
  port-occupancy cycles weighted by `dram_latency`
  (`core/generator.py:119`), not bytes; bytes are recoverable from the
  transaction list, but no existing reporting path emits them, and I did not
  verify that one could be added without touching the simulator.
- **Which exact layers of VGG16 / ResNet19 have cached schedules satisfying the
  `HO=WO=1` constraint**, and whether the paper's four named representative
  layers are among them.
- **Whether Sparseloop's actual-data density model can accept a spike tensor
  of our shape** `[T, B, Cin, Hin, Win]` without a reshape that changes what
  "a fiber" means. This is the most load-bearing unknown in §3.1 and should be
  settled before Stage 2 is planned.
