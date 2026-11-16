# LoAS SAF contract

Scope: input-sparse, weight-dense LoAS; 16 nodes × 4 COUT PEs, campaign schedules. PTB and GustavSNN are outside this task. Tier B/C are held at GATE V.

## Paper and measured semantics

LoAS IV-A states: “only the non-silent neurons will be treated as non-zero values”. It packs all timestep bits of a presynaptic neuron together, uses a row-wise bitmask for non-silent positions, and stores the packed temporal values. IV-B describes a TPPE producing the output neuron's sums across all timesteps. This is not four independent scalar sparse convolutions. The paper's weight-side compression/inner join is excluded by the requested weight-dense variant. [Paper, IV-A/B](../vendor/papers/loas.pdf).

| Quantity | Native contract | Proposed Sparseloop representation |
|---|---|---|
| Input representation | T=4 packed bits per neuron; absent iff all bits are zero | Bitmask `B` representation is supported; preserve packed-neuron identity |
| Weight operand | Dense weights | Dense, no weight metadata or intersection |
| Local weight reads | Temporal-union activity `S_or` | Input-led weight skipping, conditioned at the packed-neuron boundary |
| Accumulations | Spike activity `S_sum`, replicated over output channels | Must distinguish per-bit arithmetic from packed-vector issue cycles |
| Node compute cycles | Native T-vector processing; not scalar-MAC count divided by PE count | Requires an explicit vector-throughput contract before claiming cycle comparability |
| DRAM/GB transfers | Campaign schedule's dense weight tile transfers and native rounding | No sparsity skipping at these levels unless the source counters actually implement it |
| Multi-node fabric | 16 COUT-spatial nodes; four COUT PEs each | Two nested spatial fanouts; no modeled hop/serialization equivalence |
| Repeated HO/WO loops | Interleaved prime-factor loops | Split-index affine coordinates; coordinate bijections checked for all twelve layers |

The stock SAF grammar supports input-led `skipping` through `condition-on: [Inputs]`, bitmask format `B`, and compute skipping. Those features alone do **not** establish that its scalar issue/compute model matches LoAS's T-vector execution. `docs/open_mapping_questions.md` records the unresolved timestep contract. No executable sparse-opt YAML is presented as validated until this is resolved.

## Actual-data input

See [O2_actual_data.md](O2_actual_data.md). The paper-pinned backend consumes the complete binary presence mask, first projected coordinate fastest. `inputs/traces/*.npz` retains all four bits for each selected neuron/sample. Flattening must match the declared operand projection, including padding. Mean spike density is not substituted for a real-data mask.

There are 23 captured samples per layer but only 12 Tier C Timeloop invocations in the plan. A representative sample, an aggregated batch, or 23 separate model evaluations imply different runtime statistics; that aggregation must be named before execution. Neither averaging masks nor OR-ing independent samples is a faithful substitute for their individual occupancy patterns.

## Energy boundary

ERT comparisons include dynamic events only, using one shared price source. NoC hop energy and leakage-duration terms are outside the energy join. The figure-1 logic table's synthesis-only, mixed-corner, unconstrained-I/O and interpolation caveats remain attached. Its memory geometries do not include the campaign's 32KiB local SRAM and 2MiB GB; S4 awaits the declared memory-price source.
