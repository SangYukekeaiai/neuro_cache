# Cache vs. Scratchpad and Weight-Locality Profiling for DNN/SNN Accelerators: A Survey

*A cited survey of how prior work measures data reuse/locality in accelerator dataflows, why
accelerators overwhelmingly chose software-managed scratchpads over hardware caches, and what
methodology a CoSA-style scheduler + NoC simulator can use to profile weight locality before
designing a node-level cache. Corpus: 82 papers; 9 deep-read.*

## Abstract

DNN and SNN accelerators must move weights and activations through a memory hierarchy whose energy
cost dominates computation, so the choice of on-chip memory (a software-managed scratchpad vs. a
hardware-managed cache) and its sizing turn on how much data reuse a workload exposes. This survey
organizes the literature along two axes: how reuse/locality is *measured* (trace-driven
reuse-distance analysis, analytical loop-nest models, or reuse encoded inside a scheduler) and how
on-chip memory is *organized and managed* (scratchpad, cache, or hybrid, with reuse-aware
replacement/prefetch policies). We trace the lineage from Belady's optimal replacement and Mattson's
stack distance through the compiler-era scratchpad-vs-cache debate to today's analytical DNN mappers
(MAESTRO, Timeloop, CoSA). The central finding for a scheduler that wants to replace its node
scratchpad with a cache: the accelerator community computes reuse *analytically* and eliminates
dynamic management, while the profiling machinery needed to justify a cache (reuse-distance
histograms, miss-ratio curves, Belady-optimal gap analysis) lives in the architecture/compiler
community and has not been wired into accelerator scheduler toolchains. We give a concrete
profiling recipe to close that gap, and identify six open problems, chief among them the absence of
a within-tile vs. between-tile reuse-distance decomposition for accelerator weight streams.

## 1. Introduction

Data movement, not arithmetic, sets the energy and latency budget of modern DNN accelerators
([Kwon et al., 2019](https://doi.org/10.1145/3352460.3358252); [Parashar et al., 2019](https://doi.org/10.1109/ispass.2019.00042)).
The dominant response has been a *software-managed scratchpad* (a directly-addressed SRAM whose
contents the schedule controls) rather than a hardware cache, a choice inherited from embedded
systems where a scratchpad was shown to cut area and energy substantially at equal capacity
([Banakar et al., 2002](https://doi.org/10.1109/codes.2002.1003604)). This survey targets a specific
question: when a CoSA-family scheduler ([Huang et al., 2021](https://doi.org/10.1109/isca52012.2021.00050))
considers replacing a node-level scratchpad with a hardware cache, what prior work tells it how to
*profile weight locality* first, so the cache's size, line size, associativity, replacement policy,
and prefetch can be grounded in evidence rather than guessed.

**Scope and contributions.** We (1) taxonomize reuse/locality measurement and on-chip memory
organization; (2) reconstruct the lineage from 1966 to 2026; (3) deep-read nine methodology-central
papers; and (4) synthesize a profiling recipe and an open-problem list oriented to a scheduler + NoC
simulator. We deliberately exclude the broad "accelerator survey" literature except where it bears
on reuse measurement.

## 2. Scope & Methodology

Families queried: **computer architecture** (ISCA/MICRO/HPCA/ASPLOS/ISPASS + embedded/compiler) and
**ML/systems** (MLSys/IISWC). The Nature family was not queried because the topic does not touch it.
We ran the paper-survey multi-source pipeline (Crossref, OpenAlex, Semantic Scholar, arXiv) across
Phase 1 (frontier) and Phase 2 (broadening + backward snowball to the seminal roots). Full query
strings and dates are in `search_log.md`.

| Stage | Count |
|-------|-------|
| Identified (all sources, merged) | 703 |
| After de-duplication | 627 |
| Included after relevance filter (cites-per-year, cap 72) | 72 |
| After dropping off-topic noise and adding seminal roots + frontier | 82 (the paper DB) |
| Deep-read in full (Phase 3) | 9 |

**Relation to a prior survey in this project.** A sibling run (`survey-output/dnn-noc-buffer-sizes/`,
127 papers) already characterized *buffer sizes* across DNN accelerators and deep-read Timeloop,
MAESTRO, Interstellar, Buffets, CoSA, Eyeriss, ZigZag, Marvel, and SCALE-Sim. Those papers are
*cross-referenced* here for their reuse-*quantification method* rather than re-surveyed for sizes;
the new deep reads target profiling methodology and the cache-vs-scratchpad decision that the prior
survey did not address.

## 3. Background

Three primitives recur. **Reuse distance** (equivalently **LRU stack distance**) of a reference is
the number of distinct addresses touched since that datum's previous use; its histogram yields the
miss ratio at every cache capacity in a single pass ([Mattson et al., 1970](https://doi.org/10.1147/sj.92.0078)).
**Working set** is the set of distinct blocks referenced in a window; its size bounds the capacity
needed to capture short-term reuse. **Belady's optimal (MIN)** replacement evicts the line reused
farthest in the future and is the unbeatable lower bound any cache policy is measured against
([Belady, 1966](https://doi.org/10.1147/sj.52.0078)). Reuse in a tiled loop nest splits into
*temporal* reuse (a datum reused across time at one PE) and *spatial* reuse (a datum multicast across
PEs) ([Kwon et al., 2019](https://doi.org/10.1145/3352460.3358252)); these map onto the user's
within-tile and between-tile regimes.

## 4. Evolution & Lineage

The field has two twin roots in 1966-1970: [Belady's MIN](https://doi.org/10.1147/sj.52.0078) defined
optimal replacement, and [Mattson's stack distance](https://doi.org/10.1147/sj.92.0078) made locality
measurable across all cache sizes at once. A compiler era followed: loop-nest reuse theory turned
reuse into a static, tiling-driven quantity ([Wolf & Lam, 1991](https://www.semanticscholar.org/paper/f4dff66ba8f2338d118f379f2eff1410feb57ce6)),
and [Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159) made trace-driven reuse-distance
analysis scalable (near-linear) and predictive across input sizes. This established the enduring
branch point between **analytical** reuse (derived from the loop nest) and **trace-driven** reuse
(measured from the reference stream).

The scratchpad-vs-cache debate crystallized next: [Banakar et al., 2002](https://doi.org/10.1109/codes.2002.1003604)
showed a scratchpad wins on area and energy *when the access pattern is statically allocatable*, and
compiler techniques ([cache-aware scratchpad allocation, 2004](https://doi.org/10.1109/date.2004.1269069);
[memory coloring, 2005](https://doi.org/10.1109/pact.2005.27)) pushed static management further, which
is why accelerators later defaulted to scratchpads. Meanwhile reuse-distance analysis was extended to
concurrent execution, most relevantly to a real GPU cache fed by many parallel threads
([Nugteren et al., 2014](https://doi.org/10.1109/hpca.2014.6835955)), proving trace-driven profiling
works for a shared hardware cache.

The DNN-dataflow era (2016-2021) formalized analytical reuse: [Eyeriss](https://doi.org/10.1109/jssc.2016.2616357)
fixed the scratchpad-based spatial template, [MAESTRO](https://doi.org/10.1145/3352460.3358252),
[Timeloop](https://doi.org/10.1109/ispass.2019.00042), [Interstellar](https://doi.org/10.1145/3373376.3378514),
and [ZigZag](https://doi.org/10.1109/tc.2021.3059962) quantified reuse from the mapping, and
[CoSA](https://doi.org/10.1109/isca52012.2021.00050) recast mapping as an MILP whose objective rewards
locality. In parallel, the cache side revived through reuse-aware policy: [Hawkeye](https://doi.org/10.1109/isca.2016.17)
learns near-Belady behavior from reuse intervals, and reuse-distance-aware replacement
([Improving Cache Management Policies Using Dynamic Reuse Distances, 2012](https://www.semanticscholar.org/paper/bb0ecaa562f8af82a895fa70409e5982e6d22907))
drives insertion/eviction from measured reuse. Today's frontier brings the two sides together:
hybrid cache/scratchpad organizations ([Compad, 2023 (preprint)](https://doi.org/10.2139/ssrn.4519730)),
reuse-aware cacheability for accelerators ([HyDRA, 2026 (preprint)](https://arxiv.org/abs/2605.08908)),
and SNN-specific scratchpad memories ([A Scratchpad Spiking Neural Network Accelerator, 2024](https://doi.org/10.1109/icmi60790.2024.10586065);
[SNN ping-pong accelerator, 2023](https://doi.org/10.1109/iscas46773.2023.10181432)).

## 5. Taxonomy of Approaches

| Method | Ref | Year | Family | Workload/Dataset | Metric | Result | Key Limitation | Code |
|--------|-----|------|--------|------------------|--------|--------|----------------|------|
| Stack distance (one-pass MRC) | [Mattson et al.](https://doi.org/10.1147/sj.92.0078) | 1970 | profiling | address traces | miss curve vs capacity | exact, all sizes in 1 pass | O(N*M), single stream | libCacheSim |
| Approx. reuse distance | [Ding & Zhong](https://doi.org/10.1145/781158.781159) | 2003 | profiling | SPEC/sci | RD histogram accuracy | >90%, near-linear | smooth-scaling assumption | PyMimircache |
| Parallel GPU cache RD model | [Nugteren et al.](https://doi.org/10.1109/hpca.2014.6835955) | 2014 | profiling | GPU kernels | hit-rate vs hardware | high, orders faster than sim | modeled interleaving | author repo |
| MAESTRO (data-centric reuse) | [Kwon et al.](https://doi.org/10.1145/3352460.3358252) | 2019 | ML-HW | CONV layers | model error vs RTL | 3.9%, ~1000-4000x faster | affine, <=2 dims | MAESTRO |
| Timeloop (per-level accounting) | [Parashar et al.](https://doi.org/10.1109/ispass.2019.00042) | 2019 | ML-HW | CONV/GEMM | access counts, energy | matches Eyeriss-class | assumes scratchpad | NVlabs/timeloop |
| CoSA (MILP scheduler) | [Huang et al.](https://doi.org/10.1109/isca52012.2021.00050) | 2021 | ML-HW | ResNet/DeepBench | speedup vs Timeloop | 2.5x geomean, 90x faster tts | reuse implicit, static | ucb-bar/cosa |
| Scratchpad vs. cache | [Banakar et al.](https://doi.org/10.1109/codes.2002.1003604) | 2002 | ARCH | embedded | energy, area-time | -40% energy, -46% area-time | needs static allocation | n/a |
| Hawkeye / learned Belady | [Jain & Lin](https://doi.org/10.1109/isca.2016.17) | 2016 | ARCH | SPEC | MPKI, IPC vs LRU | -20-30% MPKI, ~15% IPC | predictor storage | CRC2 |
| Pin or Fuse (cross-layer SPM) | [Jeong et al.](https://doi.org/10.1145/3579990.3580017) | 2023 | ML-HW | CNN models | off-chip transfer, latency | -50% transfer, -15% latency | activations, static | n/a |

The taxonomy has three branches. **Measurement** splits into trace-driven reuse distance (Mattson,
Ding & Zhong, Nugteren), analytical loop-nest models (MAESTRO, Timeloop, Interstellar, ZigZag,
[analytical cache model for affine programs, 2017](https://doi.org/10.1145/3158120)), and
scheduler-encoded reuse (CoSA, [DOSA, 2023](https://doi.org/10.1145/3613424.3623797)). **Organization**
splits into scratchpad (Banakar; [Buffets, 2019](https://doi.org/10.1145/3297858.3304025); Pin or
Fuse), cache, and hybrid (Compad). **Policy** covers optimal (Belady), learned-optimal (Hawkeye),
and reuse-distance-aware replacement.

## 6. Detailed Analysis

**Trace-driven reuse distance is the direct route to a cache's miss curve.** Stack distance produces,
from one pass over an address trace, the miss ratio at every capacity, because a smaller cache's
contents are always a subset of a larger one ([Mattson et al., 1970](https://doi.org/10.1147/sj.92.0078)).
The cost is O(N*M); [Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159) reduce it to
near-linear with a bounded-error tree and, crucially, predict how the histogram shifts with input
size, so a small profiling run extrapolates to a full workload. The essential adaptation for an
accelerator is parallelism: a node cache is shared by many PEs, so the reference stream must be the
*interleaved* per-PE streams. [Nugteren et al., 2014](https://doi.org/10.1109/hpca.2014.6835955) show
exactly how to do this for a GPU cache, folding in associativity, cache-line granularity, MSHRs, and
divergent accesses, and validate against real hardware, which is the closest published template for a
node-level cache fed by 1024 PEs.

**Analytical models quantify reuse but assume the schedule controls residency.**
[MAESTRO](https://doi.org/10.1145/3352460.3358252) decomposes reuse into temporal (within-PE) and
spatial (across-PE) directions and computes per-tensor reuse factors, buffer sizes, and energy within
3.9% of RTL and roughly a thousand times faster. [Timeloop](https://doi.org/10.1109/ispass.2019.00042)
performs exact per-level accounting of accesses, fills, and reuse for any mapping and searches the
mapspace, with [Accelergy](https://doi.org/10.1109/iccad45719.2019.8942149) converting counts to
energy. [CoSA](https://doi.org/10.1109/isca52012.2021.00050) encodes the same reuse implicitly: its
binary factor-placement tensor and traffic terms reward keeping a tensor resident, yielding a 2.5x
geometric-mean speedup over Timeloop-searched schedules with a 90x faster time-to-solution. The
shared limitation is decisive for the user: all three assume an *explicit scratchpad* whose fill and
eviction the schedule dictates, so none reports what a *cache* would do under dynamic replacement.
This is precisely the modeling layer a cache study must add on top.

**The scratchpad-vs-cache decision reduces to a locality question.**
[Banakar et al., 2002](https://doi.org/10.1109/codes.2002.1003604) quantified the scratchpad's
structural advantage (no tag array, comparators, or replacement logic): about 40% lower energy and 46%
lower area-time product at equal capacity, conditioned on the access pattern being statically
allocatable. A cache earns back its overhead only when reuse is dynamic or input-dependent enough that
a static schedule leaves misses on the table. Two accelerator-side results bracket the question.
[Pin or Fuse, 2023](https://doi.org/10.1145/3579990.3580017) shows that between-layer (across-tile)
activation reuse is largely capturable *statically*, cutting off-chip feature-map transfer by 50% and
latency by 15% purely by managing a scratchpad, which sets a high bar a cache must beat. On the other
side, [Hawkeye, 2016](https://doi.org/10.1109/isca.2016.17) shows how to turn reuse data into a
near-optimal policy: OPTgen reconstructs Belady's decisions from past reuse intervals, and the gap
between LRU and that reconstructed optimum on a given trace is exactly the quantity that tells you
whether a smart cache policy is worth its hardware. Running OPTgen offline on an accelerator's weight
trace yields the best achievable miss count, and comparing it to the schedule's static residency is
the cleanest cache-vs-scratchpad criterion available.

## 7. Datasets, Benchmarks & Evaluation

There is no standard benchmark for accelerator locality profiling; studies reuse their own traces.
The relevant evaluation artifacts are (1) *address traces* emitted per tensor per memory level, at
cache-line granularity, from a simulator or instrumented scheduler; (2) *reuse-distance histograms*
and the derived *miss-ratio curve* (MRC); and (3) *policy sweeps* (LRU, RRIP, Belady/OPT) on those
traces. Accuracy is judged against cycle-accurate simulation or hardware performance counters, as in
[Nugteren et al., 2014](https://doi.org/10.1109/hpca.2014.6835955), or against RTL, as in
[MAESTRO](https://doi.org/10.1145/3352460.3358252). For DNN mapping, the de-facto workloads are CONV
and GEMM layers of ResNet/VGG-class networks ([Huang et al., 2021](https://doi.org/10.1109/isca52012.2021.00050));
for SNNs the workload adds a timestep dimension and spike sparsity that no locality benchmark yet
standardizes.

## 8. Tools, Artifacts & Reproducibility

Two ecosystems matter and do not currently connect. Analytical mappers consume a loop-nest mapping:
[Timeloop](https://doi.org/10.1109/ispass.2019.00042)/[Accelergy](https://doi.org/10.1109/iccad45719.2019.8942149)
(github.com/NVlabs/timeloop), [MAESTRO](https://doi.org/10.1145/3352460.3358252)
(github.com/maestro-project/maestro), and [CoSA](https://doi.org/10.1109/isca52012.2021.00050)
(github.com/ucb-bar/cosa, which itself ships a nocsim/, the direct lineage of the user's project).
Trace-driven cache/reuse-distance simulators consume an address trace: libCacheSim
(github.com/1a1a11a/libCacheSim, >20M requests/s, many replacement policies and MRC support) with
Python bindings, the now-deprecated PyMimircache (reuse distance + MRC + Belady), and Dinero-style
trace simulators. GPGPU-Sim provides a cycle-accurate parallel-cache validation baseline. The missing
artifact, and a genuine contribution opportunity, is a bridge that turns a CoSA/Timeloop schedule into
a per-tensor address trace consumable by libCacheSim. See phase4_code/code_repos.md for the full
table.

## 9. Cross-Family Perspectives

The architecture/compiler community measures reuse from *traces* (reuse distance, MRC) and designs
*policies* (replacement, prefetch) around it; the ML-accelerator community computes reuse
*analytically* from the mapping and eliminates dynamic management with scratchpads. The user sits at
the seam: an ML-accelerator scheduler that wants an architecture-community memory (a cache), which
requires importing the architecture-community's profiling methodology that the ML-accelerator tools
omit. Both communities agree on the underlying rule: a cache pays off only when reuse is dynamic
enough that static allocation cannot capture it.

## 10. Open Problems & Future Directions

From gaps.md: (RQ1) no released tool bridges scheduler mapping to reuse-distance/MRC profiling;
(RQ2) no work reports a reuse-distance histogram split into a short-distance within-tile mode and a
long-distance between-tile mode, the exact decomposition needed to choose line size vs. capacity;
(RQ3) nobody has measured, for a CoSA-style weight schedule, the miss-rate gap between static
residency and Belady-optimal, the number that justifies a cache's overhead
([Banakar et al., 2002](https://doi.org/10.1109/codes.2002.1003604); [Jain & Lin, 2016](https://doi.org/10.1109/isca.2016.17));
(RQ4) SNN weight reuse under spike sparsity and timesteps is unprofiled for cacheability, and existing
SNN accelerators use scratchpads without reuse-distance evidence
([A Scratchpad Spiking Neural Network Accelerator, 2024](https://doi.org/10.1109/icmi60790.2024.10586065));
(RQ5) replacement and, especially, *scheduler-driven prefetch* (the schedule knows the next tile's
addresses, enabling a near-perfect prefetcher) are unstudied on accelerator weight traces; (RQ6)
node-cache capacity should be derived from the knee of the weight MRC rather than fixed a priori.

## 11. Limitations of This Survey

The search cutoff is July 2026 and the Nature family was not queried (justified, but it means any
neuromorphic-device work published only in Nature-family venues is absent). The corpus was ranked by
cites-per-year, which under-weights 2025-2026 papers that have not accrued citations, so the newest
frontier (HyDRA, Compad) is represented but thinly and partly by preprints. Hybrid cache+scratchpad
organizations surfaced but were not deep-read; a targeted follow-up on that sub-area is warranted
before a design decision. Nine of 82 papers were deep-read; quantitative claims trace to those nine
notes, while other papers are cited from metadata. Write-traffic and coherence for writable tensors
(psum, vmem) are under-covered relative to the read-heavy weight focus.

## 12. Conclusion

Accelerators chose scratchpads because a well-scheduled workload's reuse is largely static, and a
scratchpad captures static reuse without a cache's tag and control overhead. Whether an SNN
accelerator's weights break that assumption is an empirical, locality question, and the tools to
answer it exist but on the other side of a gap: trace-driven reuse-distance analysis and
Belady-optimal policy evaluation from the architecture/compiler world, not yet wired into
CoSA-family scheduler toolchains. The actionable path for snn_cosa is to emit per-tensor weight
address traces from the scheduler + NoC simulator, compute reuse-distance histograms split by the
within-tile and between-tile regimes, derive the miss-ratio curve and the LRU-to-Belady gap, and only
then size and specify a cache, if the data shows one is warranted.
