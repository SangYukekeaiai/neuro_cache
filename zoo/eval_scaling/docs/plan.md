# Figure eval-scaling plan (RQ2 Scaling) - AWAITING BOSS REVIEW, nothing implemented

Target: `fig:eval-scaling` in `src/08_evaluation.tex` - "Compute utilization and off-chip traffic of a single node with growing scratchpad capacity and of the multi-node design at equal total on-chip capacity."

Claim the figure proves: growing a single node's scratchpad saturates - the fixed inherent dataflow cannot use the extra capacity, so utilization falls and traffic stops improving - while the multi-node design at the SAME total on-chip capacity keeps nodes at their efficient published size and converts capacity into parallelism instead.

Evidence this already works: fig1's runtime predictions measured PTB native compute fraction falling 92.8% (128k) -> 48.9% (1M) and LoAS 92.8% -> 48.1% as capacity grows under the fixed schedule - the saturation half of the figure exists in embryo.

All writes under `zoo/eval_scaling/`; S0-style ingest snapshots external inputs (same decoupling law as sparseloop_validation).

## Configuration knobs (proposed -> boss confirms)

| # | Knob | Proposed | Notes |
|---|---|---|---|
| C1 | Architecture | ONE arch (boss 2026-11-16): proposed LoAS (existing traces + T100 lineage) | three series on it: (a) single node, grown spad; (b) multi-node spad, equal total; (c) multi-node CACHE, equal total (our design, RQ3 machinery; boss 2026-11-16: cache is multi-node, not single-node) |
| C2 | Capacity sweep | published capacity x {1, 2, 4, 8, 16} | per arch, published size from its paper (recorded per-arch in configs); supersedes fig1's 128k-1M grid where they differ |
| C3 | Multi-node points | N in {2, 4, 8, 16} nodes of published capacity | equal TOTAL capacity to the x2..x16 single-node points; N=1 shared baseline |
| C4 | Multi-node schedule | our multi-node scheduler (the campaign machinery, wt500_fig3cfg-style NodeLevel/NoC/OffChip), free to tile all GEMM dims | this IS the system under evaluation; single-node side keeps the fixed inherent schedule |
| C5 | Workload | loas_vgg16 (existing traces), all 12 kept layers | ResNet19 only when its traces exist; "across layer sizes" satisfied by the 12 layers spanning the shape range |
| C6 | Samples | 10 (000-009) | matches fig1; 95% CI across samples |
| C7 | Utilization metric | native compute cycles / total cycles (nocsim) | identical definition to fig1's native_compute_fraction |
| C8 | Traffic metric | off-chip words per sample (weights + other), absolute and normalized to the x1 baseline | counts from nocsim DRAM level |
| C9 | Equal-capacity accounting | weight scratchpad only, or weight+psum+vmem total? Proposed: weight scratchpad only, fixed state buffers held constant per fig1 convention | the caption must state which; boss call |
| C10 | Venue | Stokes | same bridge rules |

## Y-axis formulas (counter-exact, from nocsim eventsim output)

Per (arch, capacity point, side, sample), nocsim/eventsim reports per layer `l`: `count_cycles` C_l = sum of compute-transaction (op==2) occupancy over ALL nodes (`eventsim/EventSim.h:178`), `dram_cycles` D_l, `total_cycles` T_l = makespan = max finish time (`EventSim.h:183`). N = node count (single-node N=1).

Row 1 - compute utilization:

```
U = ( sum_l C_l ) / ( N * sum_l T_l )
```

- C_l is summed across nodes, T_l is the shared makespan, so dividing by N*T_l gives the fraction of total node-cycles spent in native compute. At N=1 this is exactly fig1's native_compute_fraction = native_compute_cycles / baseline_cycles (`fig1_energy_profiling/src/analyze_whole_run_ideal.py:51`); the fig1 invariant max(C,D) <= T <= C+D holds per node-aggregate.
- Aggregation: cycle-weighted across the 12 layers (sum before divide, never mean of per-layer ratios), computed per sample, then mean +/- 95% CI over the 10 samples.
- U in [0,1]; the single-node series falls with capacity (growing exposed stalls T_l - C_l), the multi-node series stays near the published-size value.

Row 2 - off-chip traffic, normalized:

```
W = sum_l (bytes of all DRAM-port transactions in layer l)        [weights are 1 byte/word, so words = bytes]
y = W(x) / W_single(x=1)
```

- W counts every transaction whose source or destination is the DRAM port (weight fetches and any other off-chip stream), per sample, summed over layers.
- Normalization baseline is the arch's x1 single-node point (the shared N=1 case), one baseline per panel; both series divide by it, so y=1 at the left edge of the single-node curve.
- Mean +/- 95% CI over the 10 samples, computed on the per-sample ratio.

Closed form of W (weight stream; psum/vmem streams add analogously, spikes are not a DRAM stream):

- Multi-node (`combine.py:279`): every DRAM step loads one GB weight tile (no elision), so W_weight = dram_num_steps * GBtile_bytes = KernelBytes * R with R = product of DRAM-level temporal trip counts of the weight-invariant loops HO/WO/T.
- Single-node (`combine.py:365`, elision `weight.py:86` via `steps.py:133` weight_changes): direct DRAM->node sends, skipped when no weight dim advanced, so W_weight = KernelBytes * R' with R' = product of HO/WO/T temporal trips OUTSIDE the outermost weight-indexed loop.
- Capacity bounds the resident weight tile; growing it pulls weight loops inside residency and shrinks R toward 1 (compulsory-only). Single-node's fixed inherent loop order makes R(capacity) flatten early; multi-node partitions the kernel across N nodes so R falls roughly as 1/N.

Not on any axis: energy, hops, NoC contention cycles. D_l and the stall decomposition (exposed = T_l - C_l, overlapped = C_l + D_l - T_l, per fig1) are kept in the output CSVs as diagnostics but not plotted.

## Figure design (mock before implementation)

v2 (boss 2026-11-16, one arch + cache series): 1 row x 2 panels, left = compute utilization, right = off-chip traffic normalized to x1, with the compulsory floor as a dotted reference line. X axis: total on-chip capacity in multiples of published (log2: 1,2,4,8,16). Three series: single node grown spad (blue circles, falling U / flattening traffic), multi-node spad equal total (red squares, flat U / traffic toward floor), multi-node cache equal total = ours (green triangles, U held high, traffic nearest the floor: cache nodes capture cross-tile reuse the per-node spad partition misses). All three share the x1 point (published single node, spad). Mock: scaling_mock.py/.png/.pdf.

## Execution chain (summary; detailed execution_plan.md after boss review)

1. S0 ingest: arch bases + capacity variants (fig1 lineage), schedule manifest, traces list, published-capacity table with paper citations.
2. Single-node sweep: reuse fig1 count/cycle artifacts where the size grid overlaps; new nocsim runs only for sizes fig1 lacks (x2..x16 of published where != 128k-1M points). ~3 arch x <=5 sizes x 12 layers x 10 samples, minus reuse.
3. Multi-node sweep: scheduler -> schedules for N in {2,4,8,16} per arch/layer; nocsim multi-node runs. 3 x 4 x 12 x 10 = 1,440 cases (the new compute; Stokes-sized).
4. Join + aggregate: utilization and traffic per (arch, capacity point, side), 10-sample mean + CI.
5. Render per the approved mock; caption carries C9 accounting rule and the schedule asymmetry (fixed inherent vs scheduler-optimized) as the deliberate design of the experiment.
6. Boss gates: mock approval before runs; figure sign-off before paper integration.

## Open questions for boss

- Q1 (=C1): LoAS as the one architecture? (boss chose one-arch; LoAS proposed)
- Q2 (=C9): equal-capacity accounting - weight spad only, or total on-chip?
- Q3 RESOLVED by v2: cache is a series IN this figure, and it is the MULTI-NODE cache system (N cache nodes at equal total capacity); the spad multi-node series is its direct ablation. This figure shows scaling; RQ3 keeps the iso-capacity spad-vs-cache comparison.
- Q4: multi-node cache series semantics - same N and node geometry as the spad multi-node points, with each node's capacity managed as the paper's neuro-cache (replacement policy + line size fixed at the RQ4-chosen values), scheduler identical to the spad multi-node side? (proposed yes, so the ONLY delta between red and green is spad vs cache)
