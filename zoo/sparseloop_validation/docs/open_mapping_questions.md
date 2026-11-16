# Mapping questions for GATE V

1. **Temporal union versus independent timesteps.** LoAS keeps all four timesteps local. Weight fetches depend on `S_or`, the OR across those timesteps; arithmetic depends on `S_sum`. In sample 000/layer 01, these are 98,453 and 287,641. Multiplying a single-timestep execution by four cannot in general preserve both. Proposed contract: express T explicitly and audit temporal-union skipping. If the installed SAF cannot express it, report the unsupported behavior instead of substituting a scalar density.
2. **Memory ERT geometry.** The fig1 price bank provides local SRAM variants 128/256/512/1024KiB, with no GB row. Campaign hardware is 32KiB per node plus a 2MiB shared GB. Logic prices can be reused directly, but the memory row requires a declared source/geometry decision. Requested: supplement the S0 snapshot with campaign physical-model memory prices; retain ASAP7 logic prices. No memory ERT has been fabricated.
3. **Repeated temporal factors.** Campaign layer 01 has DRAM HO2→WO4→HO2→WO4→HO2 and NoC HO2→WO2→HO2. Flattening each dimension into a single loop changes the schedule. Investigate exact split-index workload dimensions, including affine convolution projections, before generating mapping YAML.
4. **Cycle comparison.** Timeloop's idealized pipeline estimate is not a universal mathematical lower bound for an independently scheduled simulator. Treat nocsim/Timeloop≥1 as a hypothesis to check, not an enforced assertion.

Tier B/C execution remains held. These questions do not block the isolated installation and shipped-example smoke test.

The snapshot audit finds **108/276** saved cycle totals not divisible by four. Cycle rounding and overlap must be retained; divisibility is not a valid prerequisite for these real samples. Hypergeometric tile occupancy is exact conditional on fixed global NNZ; IID Bernoulli generation has a random global NNZ. The Tier B writeup must distinguish that finite-population conditioning from unconditional Bernoulli occupancy.

`outputs/self_checks/mapping_coordinates.json` proves all twelve schedules have 16 COUT-spatial nodes and four COUT-spatial PEs per node. Splitting repeated dimensions into independent mixed-radix indices reconstructs every original coordinate bijectively. This proves coordinate expressibility only, not that sparse reuse/cycle accounting remains equivalent; that requires the later configuration self-check.

## Tier C sample contract

Twelve layer-level actual-data evaluations cannot represent 23 independent masks per layer without a declared aggregation rule. The snapshot contains 276 case/mask pairs. Requested choice: twelve layer jobs containing 23 separate evaluations each (276 Timeloop invocations), or twelve evaluations restricted to one named sample and joined only to its matching nocsim rows. Averaging densities or OR-ing independent sample masks does not preserve actual-data semantics. No Tier C mask aggregation has been performed.
