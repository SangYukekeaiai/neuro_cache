# Unit-cost characterization

The per-case energy model is [snn_edp](../README.md). This directory
contains its unit-cost characterization recipes; the pinned metric table is `../energy_table.json`.

`--design cache` prices the shared 16 KiB/8-way L1 and 512 KiB/16-way L2
at a 64-byte line size. Both production config JSONs use 32 L2 MSHRs,
the smaller-count tie-break from the Config A two-layer demo; 32 and 64
tied exactly, and Config B inherits 32 without a separate sweep. L1 remains 16. Config A reproduces the
production policies with next_access d4 and distance_aware d1/t9, pf_lru.
Config B uses `NextLine`, which emits physical line IDs `line+1` through
`line+d`. Production uses d1 at both L1 and L2, emitting only `line+1`,
with plain LRU.
`scope=system` makes physical inventories global: 16 L1s, one L2, and
per-policy control definitions. The nine explicit prefetch-control exclusions are priced zero by `pricing_policy.json`; L1/L2 array fill writes remain charged. Both extra tag-probe rows retain Stage A counts but are excluded from Stage B costs; they have zero extra standing inventory because the cache model already includes tags.
Distance-aware state is the bounded 8192x64-bit (64 KiB) SRAM proxy for
an unbounded software map; the excluded historical geometry does not establish an exact tag+tile32+count32 packing. The bounded tag28/tile32/count4 proposal and fidelity limits remain archived in MODULE_MAPPING. No finite-capacity eviction is simulated. Next-access
state is three 32-bit registers per core (192 B system-wide). Metadata
activity and MSHR target writes use the documented counter proxies in rows.

`--design prosperity` includes the double-buffered 256x16 TCAM, detector,
dispatcher, four PEs, buffers and shared LIF; SFU is excluded. Front-end
logic is pending ASAP7 synthesis. Comparing against the paper's 28 nm area,
efficiency and power ordering requires those results; null entries cannot
establish that validation. Spike-row storage is two 256x16 banks (1 KiB),
with one load and one read per row. Sorter leakage currently assumes one
reused compare-exchange unit until RTL establishes its physical inventory.

`--design gustavsnn` uses the two-input merger, four accumulate PEs, and
potential register files totaling 1 KiB per node (64x32 bits per PE).
The LIF core excludes its internal state register; the separately charged
register-file RMW supplies state. No vmem SRAM is introduced. Output FIFO
costs use expected packed words without per-tile tail padding. Both LIF variants use the same explicit measured-basic composition definitions.

`--design loas` adds 128 physical 16-bit adders/register lanes (four TPPEs,
32 lanes each), shared LIF and shallow FIFO placeholders. FTP scan costs
are three pending subblock entries: `A/cout_n` bit scans, `B` prefix scans,
and `32*B` one-bit AND operations. Their costs use separate structural vectors over the24 measured basics; do not add a whole tppe_scan cost on top. The
primitive pieces allow the different per-bit/per-word activity counts.

Additional architecture slices use `energy_harvest.py --design ptb` (and
the matching `<design>.architecture.yaml`). A run replaces only that design's
rows. `physical_instances` is the per-node inventory for leakage and area;
dynamic costs remain per single operation. Count expressions are per layer
across all nodes. All operations of one module share physical inventory;
deduplicate by design/module for leakage and area, including memory read/write,
register read/RMW and FIFO push/pop. PTB has 32 adders and 128 potential registers,
four LIF units, and two shallow staging FIFOs. The shared LIF block has a
32-bit state and 16-bit input.
Its null costs include leak, integration, threshold, hard reset and state.
`auto_syn_pnr_worklist.json` follows the parent plan's consolidated inventory;
no multiplier is needed for the resolved power-of-two leak.

The harness executes a Rust-backed archx graph with seven SRAM modules and
two characterized compute modules, runs the one-event workload, and queries dynamic energy,
leakage and area with `query_module_metric`. Missing dependencies, invalid
schemas and interface failures stop the run; there is no fallback. The table
replaces only `spinalflow.*` keys and preserves other designs such as `ptb.*`.

Run from the repository root in the isolated `fig12-archx` conda environment:

```bash
setsid -w systemd-run --user --scope -q -p OOMPolicy=continue \
  conda run --no-capture-output -n fig12-archx python \
  zoo/snn_edp/characterization/energy_harvest.py
conda run -n fig12-archx python -m pytest \
  zoo/snn_edp/characterization/test_energy_harvest.py -q
```

`energy_table.json` contains nJ/access, mW and mm². The declared comparator and min-tree modules are
excluded from priced queries until their measured-basic composition costs arrive; their table rows
have `placeholder=pending-ASAP7-synthesis` and null energy, leakage and area.
Null means unavailable, not zero; consumers must reject incomplete totals.
Harvest scratch graphs, reports and caches are regenerable and are not retained.
The CSVs and extractor sources described below belong to the archx package;
they are characterization inputs, not archived campaign intermediates.
Use `--run-dir` outside this source directory for a characterization run.
Preserve other designs' table rows when replacing one characterization slice.

Provisioning, if needed (network access required):

```bash
setsid -w systemd-run --user --scope -q -p OOMPolicy=continue \
  conda create -y -n fig12-archx -c conda-forge python=3.12 rust maturin pip pytest
setsid -w systemd-run --user --scope -q -p OOMPolicy=continue \
  env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  NUMEXPR_NUM_THREADS=1 RAYON_NUM_THREADS=1 CARGO_BUILD_JOBS=1 \
  conda run --no-capture-output -n fig12-archx python -m pip install \
  --no-build-isolation -e /u/yyu9/projects/neuro_cache_wcache/zoo/archx
```

The harvester caps thread pools before importing archx, and builds a missing
FN-CACTI binary with `make -j1`. The editable install builds the Rust extension
without changing archx source. On hosts without a user systemd bus, retain
`setsid -w` and omit `systemd-run` and its options.

Compute provenance and assumptions:

- All logic uses own-RTL classes and awaits500MHz ASAP7 synthesis. Default logic costs are null; historical library magnitudes exist only in the archived provenance and explicitly labeled dummy table.
- `cmp32` and `min_tree4` target ASAP7 at 7 nm. The tree comprises three
  32-bit comparisons. Both use their explicit primitive/glue vectors and individually measured basics; no numerical process scaling is applied. The active catalog has24 basic variants; no whole-top report is scheduled.

SRAM geometry is a 32 KiB weight scratchpad, 1 KiB input/output queues and
1 KiB/64 KiB psum/vmem levels. Queues assume a 32-bit record (16-bit timestamp
plus 16-bit neuron ID), hence 256 records per queue and one access per record.
This is an explicit packing assumption, not a measured trace record layout.
Input spines use `R` reads plus `R` writes; output spines use `O` writes.
The output read unit cost remains available, with count expression `0` in this
layer because the next layer counts its own input reads. FIFO pointer logic is included in the unchanged measured FIFO primitive. All these KB-scale buffers are
`cacti_fn` SRAM at technology 7.
The weight row models the maximum four-lane 32-bit burst; smaller active-lane
counts still pay for that physical word.

All SRAMs use FN-CACTI at 7 nm, 0.7 V, with a 500 MHz query clock. Frequency is metadata: the separate100/500MHz runs in [cacti_frequency.json](../provenance/cacti_frequency.json) return identical metrics. The
`finfet_7nm_0p7.xml` device is **synthetic**, derived from the 0.45 V file using
alpha-power Ion scaling (alpha 1.3) and DIBL Ioff scaling (40 mV/V,
68 mV/dec), as its XML header states. It needs TCAD/SPICE characterization
at 0.7 V before publication; this caveat is also recorded in every SRAM row.

Weight NoC movement is outside this node-component slice and requires the
shared model using tc.csv traffic. For the SpinalFlow model, psum/vmem
NoC/GB movement is zero; the retained SRAM unit costs do not imply accesses.
Control/sequencer energy is excluded per the plan. This graph supplies unit
costs only; its synthetic one-event workload is not a delay or node-total
energy model. The integration tests exercise priced graph queries, pending
synthesis entries, spine counts, report parsing and preservation of other designs.

`--design shared` prices a 2 MiB GB SRAM, router packet hops, 1 mm ASAP7
wire links, and closed-page 64-byte DDR4 reads including separate IO and
standing power. A packet is four 64-bit payload flits plus one header.
Both cache arms retain the schedule's k/t-chain hops; only weight-movement
GB and mesh terms are exclusive to the scratchpad arm.
Router energy uses the [Stillmaker/Baas scaling implementation](https://accelergy-project.github.io/hwcomponents/_modules/hwcomponents/scaling/techscaling.html)
with 32 nm at 0.9 V and 7 nm at 0.7 V; area scales by 0.13.
The archived router dynamic value is exceptionally small and its leakage
is zero: this remains explicitly incomplete until the published-range check
or characterization resolves it. Link length and omission of repeaters
are assumptions. DDR4 reports explicitly verify the configured interface;
READ minus IDLE IO power supplies incremental byte energy, while IDLE
IO/PHY, eight-bank leakage and refresh supply standing power.
For the demo only, unavailable costs contribute zero with an incomplete
flag; the resulting EDP is not a publication-ready estimate.

Cache activity expressions use only native CSV columns. Demand misses are
accesses minus hits; L1 fills use demand misses plus issued prefetches minus
all five drop counters (merged/retried demands make this an upper-bound
proxy). L2 fills equal `dram_accesses`. The L1 prefetch tag probe bound is
`2*pf_issued+pf_budget_exhausted`: engine.cpp probes the array once in its
redundancy filter, and admitted requests probe again at triage. Combined
filter/triage drop counters cannot separate these sites, so dropped issues
may be counted twice. Budget exhaustion occurs after the first array probe.
L2 prefetch tag probes use `l2_pf_issued` plus accepted L1 prefetches as an
upper-bound proxy for their forwarded probes; `l2_pf_filtered` is excluded
because that policy-level filter runs before issuing a cache-array probe.
LRU/pf_lru replacement-state RMW is folded into cache-array accesses;
khkw_split indexing is charged zero. DRAM access/IO and standing costs
come from `shared.ddr4.read` and `shared.ddr4_io.byte`.

The router uses the standard pending-ASAP7-synthesis marker and null
energy/leakage/area. Its unvalidated scaled estimate is audit metadata only;
the archx model never charges it. Characterization or a validated published source
is required before pricing the router.
Router and link rows apply to all three arms: the scratchpad uses weight
plus k/t-chain packet-hops, and cache arms use k/t-chain packet-hops only.
Wire leakage/area and the separate DDR IO row's leakage/area are zero by
modeling convention; DDR IO standing power is already in the DDR access row.

FN-CACTI’s native executable also writes `pcacti_report.txt` in its package
`include/cacti_fn/` directory. The upstream wrapper fixes that working directory;
`--run-dir` redirects the requested reports but does not suppress this scratch
file. When characterizing against a checkout that must remain unchanged,
preserve that generated file before the run and restore its exact bytes afterward
(or remove it if the run created it). This does not affect the per-case count or
pricing path, which never invokes CACTI. Do not run characterization concurrently
against the same checkout if that scratch report is being used for auditing.

## Own-RTL characterization

[ASAP7_SYNTHESIS_PLAN.md](ASAP7_SYNTHESIS_PLAN.md) defines the24-basic TT500MHz native-project characterization scope. All48 logic rows use composition vectors;41 rows retain physical models and9 are excluded by decision. Four glue leaves are present;13 authored whole tops are [unsynthesized references only](rtl_tops/README.md). Native I/O/activity defaults remain, with no replacement TCL or SDC. The first and_gate pilot failed POPT-78/no ICG; clock-gating disable is authorized and the parent owns the retry. No accepted primitive result or new composition-priced table is claimed here.

## Logic price lineage

No retired library class or characterized logic price is active. Included logic rows await our own500MHz ASAP7 synthesis; their default metrics are null. The nine prefetch-control operations in [pricing_policy.json](pricing_policy.json) instead carry explicit zero metrics and the exclusion marker; their counted events remain present. The optional dummy table uses finite uncharacterized magnitudes and marks retired-library magnitudes explicitly as DUMMY historical provenance. Source CSV paths from that library are retained only under historical provenance, never as active class/source_csv fields. The per-row retirement audit is `provenance/retired_logic.json` at the model root.
