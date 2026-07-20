---
aliases: [Ding Zhong reuse distance, approximate reuse distance, near-linear stack distance]
topics: [reuse-distance, profiling-methodology, locality-scaling, working-set]
author: Ding, Zhong
venue: PLDI
year: 2003
status: pass-2
bibkey: ding2003predicting
gist: Approximate reuse-distance analysis in near-linear time with bounded error; predicts locality vs input size.
---

# Predicting Whole-Program Locality through Reuse Distance Analysis (Ding & Zhong, 2003)

- **problem**: Exact stack distance is too slow for whole-program traces; also want to PREDICT locality at unseen (larger) input sizes without re-tracing.
- **challenge**: Measure reuse-distance histograms cheaply, and model how the histogram shifts as the working set grows.
- **current SoTA (then)**: Exact O(N log M) stack simulation; no cross-input prediction.
- **novelty**: (1) **Approximate reuse distance** with guaranteed relative error bound using a balanced tree / scale-tree over the distance axis, giving near-linear time and log space. (2) **Cross-input prediction**: fit each reuse-distance bin's growth as a function of data size (constant, linear, or sub-linear pattern) from two-three training runs, then extrapolate the histogram to any input size.
- **proposal**: Build the reuse-distance histogram per run; classify bins by how their mass moves with input size; predict the miss-rate curve for a new input without tracing it.
- **evaluation**: SPEC + scientific benchmarks; reports high accuracy predicting the reuse-distance distribution across input sizes (paper claims >90% accuracy on most programs), at analysis cost near-linear in trace length.
  - Table row: `2003 | profiling-method | SPEC/sci traces | reuse-dist histogram accuracy | >90% cross-input | approx error bound | n/a`
- **assumptions**: Locality patterns scale regularly with input size; single reference stream.
- **limitation**: Approximation error in the tails; assumes smooth scaling; sequential/single-thread model (no PE interleaving).
- **impact**: Made reuse-distance profiling practical; standard method for working-set characterization; basis for cache-sizing and management studies.
- **risks**: Irregular/phase-changing workloads break the scaling model.
- **related work**: Approximates [Mattson et al., 1970](https://doi.org/10.1147/sj.92.0078); extended to multicore ([program locality analysis, 2009](https://www.semanticscholar.org/paper/93a6a32f1bbf1913e9e2232132ec4fa7a75ab152)).
- **my take**: For snn_cosa the cross-input prediction is the killer feature: profile reuse distance on a small layer, predict the node-cache working set for the full layer/timesteps without re-simulating the whole NoC trace.
- **relevance**: HIGH - the practical algorithm to compute weight reuse-distance histograms from the scheduler/sim trace at scale.
- **future work**: Multicore/parallel reuse distance; phase detection.
- **triage**: Pass-2.
- **terms**: approximate reuse distance, reuse signature, cross-input prediction, bin scaling.
- **citation**: [Ding & Zhong, 2003](https://doi.org/10.1145/781158.781159)
- **code**: reuse-distance tools (loca, PyRDA) implement this class of algorithm.
- **refs**: Mattson 1970; Zhong et al. 2009.
- **obsidian links**: [[reuse-distance]], [[working-set]]
