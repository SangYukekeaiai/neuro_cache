# Figure 1 input checks

## Hardware configuration

The approved per-architecture base is one node, with 16 PEs for LoAS and 8 PEs for PTB and GustavSNN. Each base differs from the campaign YAML in `single_node`, NodeLevel `instances`, `num_pes`, removal of `NoCLevel.entries`, and fixed psum/vmem sizing. Each SRAM variant differs from its base only in weight capacity. All twelve variants pass the architecture/mapspace fanout check.

[The SHA manifest](../configs/arch_manifest.json) records the exact differences. The plan's capacity-only requirement applies to these single-node bases, rather than to the campaign's 16-node/4-PE configuration.

The physical hierarchy is DRAM ↔ local buffers ↔ PEs. The shared parser requires the three named schema slots, so `NoCLevel` remains declared with one instance but no entries: `has_noc_buffer=False`. The existing single-node solver constraint empties that level's assignments, and nocsim sends traffic directly between DRAM and the node. This inert slot is not a physical GB and contributes no inventory or energy.

[No-GB evidence](../outputs/self_checks/no_gb/verification.json) checks all twelve configs with a tiny hand-specified transaction fixture: positive DRAM/local delivery, zero GB endpoints, reads, writes, and inter-node hops. A GB-present control produces reads/writes and is rejected. These are unit fixtures, not generated Figure 1 workload schedules. [The count contract](../src/contracts.py) requires explicit zero GB counters and rejects GB operation rows; the production count runner must call it before each commit. [The segment map](segment_map.md) includes only local SRAM in the on-chip SRAM segment.

## Traversal order and local-buffer feasibility

`src/lays/parsers/node_mapspace.py` consumes `dataflow.node_dim_capacity` and derives PE spatial splits. It does not consume `outer_order`. YAMLs specifying opposite orders produce identical parsed state for all three architectures; the evidence and source hashes are in [schema_check.json](../outputs/self_checks/schema/schema_check.json).

The scheduler's traffic modes constrain reduction (`KH/KW/CIN`) and time (`T`) groups, but do not order `COUT` relative to `HO/WO`. Single-node mode removes NoC-level assignments and leaves the DRAM permutation for the optimizer. `gen_inputs.py` offers no separate order constraint. Its actual input flags include `--arch-yaml` and `--mapspace-dir`, not the illustrative `--mapspace`/`--benchmark` flags in the plan.

The authorized Figure-1-local path is direct analytic construction, followed by the shared schedule decoder and native-bridge checks. The required orders are `HO, WO, COUT` for LoAS/PTB and `COUT, HO, WO, T` for GustavSNN. Temporal `T` is resident for LoAS/PTB and visits one pixel and one timestep per GustavSNN tile. The inert NoCLevel has no loops or spatial factors.

[The contract self-check](../outputs/self_checks/schedule_contract/verification.json) derives 144 schedules from the actual metadata: 12 kept convolutions × three architectures × four capacities, or 1,440 sample cases. The classifier is excluded by the canonical scope rule. Every schedule passes the shared native tile-shape checks and local-buffer capacity limits. [The manifest index](../outputs/manifest/index.json) pins all twelve production manifests and their 144 saved schedule artifacts. Construction is labeled `ANALYTIC_VALIDATED`, not solver-optimal.

The fixed state-buffer capacities are 256 KiB psum and 512 KiB vmem for every configuration. They cover the approved 128/256 KiB sizing envelope with 25% margin and power-of-two rounding. The one-pixel/timestep GustavSNN nest needs less simultaneous state, but these provisions remain fixed across all twelve configurations; state dynamic accesses remain zero. The hardware SHA manifest records their sizes and exact base changes. No convolution is dropped for state capacity.

The boss's 256 KiB LoAS example passes exactly: DRAM loops `HO=28, WO=28, COUT=4`, resident COUT64, spatial COUT16, weight tile144 KiB. The shared `StepInfo.weight_changes` yields3,136 loads, or784× compulsory weight bytes. It is a semantic test, not a claimed capture layer; the actual B09 capture is CIFAR-scale.

For actual `layer_04_core_features_14` at256 KiB, LoAS/PTB use `HO8, WO8, COUT2`, resident COUT128, spatial COUT16/8, and144 KiB weight tiles:64× compulsory. GustavSNN uses `COUT2, HO8, WO8, T4`, resident HO1×WO1×T1 and COUT128, spatial COUT8:1× compulsory. Its weight-change predicate is false across all pixel/time visits within a COUT tile. At512 KiB the full288 KiB weight tensor is resident and LoAS/PTB also reduce to1× compulsory. All quantities are independently checked through the shared decoder and weight-reload predicate.

The earlier 1 KiB-state diagnostic and configs are retained in [the local archive](../outputs/self_checks/schedule_contract/before_state_sizing/configs_and_check.tar.gz), SHA256 `b6bee66aa714efa40aac76bbed566c526004ee1b84ba5b13a7848a15aed7cf4e`.

## Synthesis report inspection

[inspection.json](../archx_config/asap7_genus/inspection.json) records nine existing Genus designs and 189 SHA-verified report files copied read-only from vlsi. Their source is `~/auto_syn_pnr/Flows/ASAP7/<module>/scripts/cadence/syn_rpt/`. No licensed tool was launched for this inspection.

- Reports identify Genus 21.18-s082_1 and operating condition `PVT_0P77V_0C`. The project's library set has mixed declarations: AO/INVBUF/OA/SEQ at 0.77 V/0 C and SIMPLE at 0.70 V/25 C. A uniform TT label would be inaccurate. [Library/flow evidence](../archx_config/asap7_genus/library_and_flow_provenance.txt) preserves hashes and declarations.
- Power reports explicitly use watts. Dynamic power is internal plus switching, converted to mW; energy per modeled 500 MHz cycle is mW/500. Leakage is converted separately. No post-route parasitics are included.
- Cell area is separate from estimated net area. Only cell area is included in the logic-area basis.
- Register and FIFO reports show constrained register-to-register slack of 1910 ps and 1300 ps, respectively. Combinational reports contain no constrained path; unconstrained I/O prevents claiming end-to-end 500 MHz timing closure.
- The stock `csv_cmos_extract.py` reads `postRouteOpt` rows and writes relative to its own interface directory. It cannot directly consume these Genus reports without misrepresenting their origin or violating Figure 1 write isolation. The local synthesis-report converter emits the established CSV schema with explicit synthesis-only provenance; the vendored `csv_cmos` interface performs interpolation. The extractor and backend remain unchanged.

## Native/NoC counts and price bank

The two Figure 1 arrays, 1147750 and 1147751, completed all 1,440 cases with exit 0:0. [The remote inventory](../outputs/count_validation.json) verifies every receipt and artifact; [the fetch check](../outputs/count_fetch_verification.json) independently verifies all 11,520 files on Delta. All cases have zero GB events, exact pinned weight traffic, and native unique-address counts equal to the independent spike-support oracle. Raw count artifacts occupy 57,730,099 bytes. Slurm's first start and last end span 82 seconds; [accounting.txt](../stokes/accounting.txt) retains every task record.

[The local price bank](../archx_config/energy_table_asap7_syn.json) assembles the Genus logic and FN-CACTI memory banks for twelve configurations. [Its manifest](../archx_config/table_manifest.json) pins source and output hashes. All eleven distinct SRAM queries report fmax above 500 MHz under the physical model. This is a model result, not SRAM timing signoff.

## Energy-model self-checks

State remains in architecture-native registers/LIF/RFs. The fixed SRAM provisions contribute area/leakage once and have zero added dynamic accesses. GustavSNN uses eight compute/LIF/RF lanes, one detector and no two-stream merger; LoAS/PTB use sixteen/eight COUT replication. [The physical inventory](energy_model.md) and `arch_manifest.json:energy_inventory` specify all owners.

The local archx description compiles and executes twelve designs. There are 1,440 price-free graphs, 1,800 priced layer rows including ideal, and 150 complete whole-model samples. [Energy validation](../outputs/energy_validation.json) verifies all terms and unchanged count files. Tests run counting with the table absent, block simulator-input reads and performance callbacks during pricing, and prove that a changed table leaves count checkpoints byte-identical. The ideal comparison retains baseline time/leakage and changes only needed-weight reads, IO and fills.

The former review gates are recorded self-checks: native schedule feasibility, independent ideal-demand oracle and source-backed price provenance, then complete aggregation and visual figure inspection. No review stop is required.


## Unique-weight ideal audit

[The independent audit](../outputs/self_checks/ideal_dedup_audit/verification.json) projects active input coordinates into valid output windows and unions kernel-offset/channel lines, then includes every COUT word on each line. It does not traverse or count the native access stream. All 360 ideal cases match the stored native boolean address union and their priced DDR4/IO/fill counts exactly.

Across twelve layers and ten samples, each architecture needs 118,852,096 unique weight words. The native address union is independently matched to active input coordinates and to the other architectures for every case. Mean absolute ideal off-chip weight energy is 2.396432955 mJ/sample for all three architectures. [The current audit](../outputs/self_checks/ideal_dedup_audit/verification.json) records stream-touch counts and the architecture-specific normalization denominators; repeated touches never enter ideal off-chip counts. [The timestep audit](../outputs/self_checks/temporal_order/native_verification.json) checks compulsory baseline weight transfers for all 480 GustavSNN cases; its companion priced report lists per-segment changes.

Repricing the 360 ideal cases leaves all 1,080 priced artifacts byte-identical to the before snapshot; energy before/after delta is zero. The figure caption explicitly distinguishes equal absolute unique-weight energy from unequal normalized heights. Tests duplicate native records across ticks/tiles and input spikes across timesteps, requiring invariant unique demand while stream counts grow.
