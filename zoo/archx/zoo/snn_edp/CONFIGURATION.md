# Architecture configuration

This is the configuration consumed by `designs/snn/description.py`, with the performance
setting beside every operation. `hardware.json` is the price-independent source.
Unit-cost values come from the pinned table, not from this document. Selection
follows the caller’s workload selection (see [input contract](README.md#saved-counter-interface)).

All counts are system-wide. Physical inventory is per node times 16 unless
`scope=system`; repeated operations share one physical module. The model uses
16 nodes / 16 routers / 48 directed links regardless of schedule topology.
SpinalFlow adder/comparator/register inventory is four lanes per node.
Tag-only cache rows have zero extra standing inventory; cache arrays already
include it. A zero count does not remove physically present standing power.

Compute is ASAP7/7 nm (characterized rows or pending synthesis); SRAM is
cacti_fn SRAM tech7, cache arrays are cacti_fn cache tech7, and off-chip DRAM
is cacti7 DDR4. Own-RTL logic characterization targets500MHz; memory query frequencies are500MHz metadata; the physical-model prices are frequency-independent. Simulated cycles are converted at500MHz by default. Source interfaces below describe unit-cost provenance.
Stage A uses a local zero-metric interface; Stage B binds those prices through
archx native module metrics without querying characterization tools again.

Cache A: L1 next_access distance4; L2 distance_aware distance1, min_touches9;
pf_lru. Cache B: NextLine distance1 at both levels, LRU. NextLine emits physical
line IDs `line+1` through `line+d`; production d1 emits only `line+1`. Both use 16 KiB/8-way
L1 and 512 KiB/16-way L2, 64-byte lines, khkw_split, L1 MSHRs16, L2 MSHRs32,
L2 targets12. The MSHR saturation evidence is at L2 prefetch distance4;
32 at production distance1 is a fixed choice, not a new tuning measurement.

Next-access registers total192 B. Distance metadata is a bounded64 KiB SRAM;
simulator history is unbounded, with no modeled metadata eviction. LRU/pf_lru
replacement-state RMW is folded into cache accesses; indexing energy is zero.
Prefetch probes often outnumber demand-only L2 data reads; prefetch fills still
charge L2 writes. The explicit engine-derived probe expressions are listed below.

## spinalflow

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| spinalflow.adder32.add / spinalflow.adder32 | class=adder, width=32 | csv_cmos; 7 | 64 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| spinalflow.cmp32.compare / spinalflow.cmp32 | class=comparator, width=32 | csv_cmos; 7 | 64 | spad: `A`; cacheA: `A`; cacheB: `A` | pending; null metrics |
| spinalflow.input_spike_buffer.read / spinalflow.input_spike_buffer | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `R`; cacheA: `R`; cacheB: `R` | priced; see unit-cost assumptions |
| spinalflow.input_spike_buffer.write / spinalflow.input_spike_buffer | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `R`; cacheA: `R`; cacheB: `R` | priced; see unit-cost assumptions |
| spinalflow.l1_weight_spad.read / spinalflow.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `R` | priced; see unit-cost assumptions |
| spinalflow.l1_weight_spad.write / spinalflow.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `l1_delivery_bytes*8/32.0` | priced; see unit-cost assumptions |
| spinalflow.min_tree4.compare / spinalflow.min_tree4 | class=comparator, num_instances=3, width=32 | csv_cmos; 7 | 16 | spad: `R`; cacheA: `R`; cacheB: `R` | pending; null metrics |
| spinalflow.output_spike_queue.read / spinalflow.output_spike_queue | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `0`; cacheA: `0`; cacheB: `0` | priced; see unit-cost assumptions |
| spinalflow.output_spike_queue.write / spinalflow.output_spike_queue | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `O`; cacheA: `O`; cacheB: `O` | priced; see unit-cost assumptions |
| spinalflow.psum_l1.read / spinalflow.psum_l1 | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.psum_l1.write / spinalflow.psum_l1 | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.psum_l2.read / spinalflow.psum_l2 | bank=1, class=sram, depth=16384, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.psum_l2.write / spinalflow.psum_l2 | bank=1, class=sram, depth=16384, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.reg32.rmw / spinalflow.reg32 | class=register, width=32 | csv_cmos; 7 | 64 | spad: `A+L`; cacheA: `A+L`; cacheB: `A+L` | pending own-RTL500MHz; default null / dummy historical magnitude |
| spinalflow.vmem_l1.read / spinalflow.vmem_l1 | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.vmem_l1.write / spinalflow.vmem_l1 | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.vmem_l2.read / spinalflow.vmem_l2 | bank=1, class=sram, depth=16384, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
| spinalflow.vmem_l2.write / spinalflow.vmem_l2 | bank=1, class=sram, depth=16384, width=32 | cacti_fn; 7 | 0 | excluded from per-case graph (no accesses or inventory) | priced; see unit-cost assumptions |
## ptb

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| ptb.adder16.add / ptb.adder16 | class=adder, width=16 | csv_cmos; 7 | 512 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| ptb.l1_weight_spad.read / ptb.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `B` | priced; see unit-cost assumptions |
| ptb.l1_weight_spad.write / ptb.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `l1_delivery_bytes*8/32.0` | priced; see unit-cost assumptions |
| ptb.lif_unit.step / ptb.lif_unit | class=lif_unit, input_width=16, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending; null metrics |
| ptb.spike_mask_overlap.check / ptb.spike_mask_overlap | class=and_gate, reduction=True, width=32 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| ptb.output_spike_queue.read / ptb.output_spike_queue | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `0`; cacheA: `0`; cacheB: `0` | priced; see unit-cost assumptions |
| ptb.output_spike_queue.write / ptb.output_spike_queue | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `O`; cacheA: `O`; cacheB: `O` | priced; see unit-cost assumptions |
| ptb.reg16.read / ptb.reg16 | class=register, width=16 | csv_cmos; 7 | 2048 | spad: `L`; cacheA: `L`; cacheB: `L` | pending own-RTL500MHz; default null / dummy historical magnitude |
| ptb.reg16.rmw / ptb.reg16 | class=register, width=16 | csv_cmos; 7 | 2048 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| ptb.spike_fifo.pop / ptb.spike_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| ptb.spike_fifo.push / ptb.spike_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| ptb.spike_vector_buffer.read / ptb.spike_vector_buffer | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | priced; see unit-cost assumptions |
| ptb.spike_vector_buffer.write / ptb.spike_vector_buffer | bank=1, class=sram, depth=256, width=32 | cacti_fn; 7 | 16 | spad: `0`; cacheA: `0`; cacheB: `0` | priced; see unit-cost assumptions |
| ptb.weight_fifo.pop / ptb.weight_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| ptb.weight_fifo.push / ptb.weight_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
## loas

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| loas.adder16.add / loas.adder16 | class=adder, width=16 | csv_cmos; 7 | 2048 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| loas.and_gate.and / loas.and_gate | class=and_gate, width=1 | csv_cmos; 7 | 2048 | spad: `32*B`; cacheA: `32*B`; cacheB: `32*B` | pending; null metrics |
| loas.bsf32.scan / loas.bsf32 | class=bsf32, width=32 | csv_cmos; 7 | 64 | spad: `A/cout_n`; cacheA: `A/cout_n`; cacheB: `A/cout_n` | pending; null metrics |
| loas.l1_weight_spad.read / loas.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `B` | priced; see unit-cost assumptions |
| loas.l1_weight_spad.write / loas.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `l1_delivery_bytes*8/32.0` | priced; see unit-cost assumptions |
| loas.lif_unit.step / loas.lif_unit | class=lif_unit, input_width=16, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending; null metrics |
| loas.output_fifo.push / loas.output_fifo | class=fifo, depth=8, width=32 | csv_cmos; 7 | 16 | spad: `W_o`; cacheA: `W_o`; cacheB: `W_o` | pending; null metrics |
| loas.spike_prefix_scan32.scan / loas.spike_prefix_scan32 | class=psum_scan32, width=32 | csv_cmos; 7 | 64 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| loas.reg16.read / loas.reg16 | class=register, width=16 | csv_cmos; 7 | 2048 | spad: `L`; cacheA: `L`; cacheB: `L` | pending own-RTL500MHz; default null / dummy historical magnitude |
| loas.reg16.rmw / loas.reg16 | class=register, width=16 | csv_cmos; 7 | 2048 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| loas.spike_fifo.pop / loas.spike_fifo | class=fifo, depth=8, width=32 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| loas.spike_fifo.push / loas.spike_fifo | class=fifo, depth=8, width=32 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| loas.weight_fifo.pop / loas.weight_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
| loas.weight_fifo.push / loas.weight_fifo | class=fifo, depth=8, width=16 | csv_cmos; 7 | 16 | spad: `B`; cacheA: `B`; cacheB: `B` | pending; null metrics |
## gustavsnn

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| gustavsnn.adder16.add / gustavsnn.adder16 | class=adder, width=16 | csv_cmos; 7 | 64 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| gustavsnn.l1_weight_spad.read / gustavsnn.l1_weight_spad | bank=1, class=sram, depth=16384, width=16 | cacti_fn; 7 | 16 | spad: `R_g` | priced; see unit-cost assumptions |
| gustavsnn.l1_weight_spad.write / gustavsnn.l1_weight_spad | bank=1, class=sram, depth=16384, width=16 | cacti_fn; 7 | 16 | spad: `l1_delivery_bytes*8/16.0` | priced; see unit-cost assumptions |
| gustavsnn.leading_spike_detector.scan / gustavsnn.leading_spike_detector | class=l1d, width=32 | csv_cmos; 7 | 32 | spad: `R_g`; cacheA: `R_g`; cacheB: `R_g` | pending; null metrics |
| gustavsnn.lif_core.step / gustavsnn.lif_core | class=lif_unit, input_width=16, state_register=False, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending; null metrics |
| gustavsnn.merger_tree2.merge / gustavsnn.merger_tree2 | class=merger_tree2, inputs=2, width=32 | csv_cmos; 7 | 16 | spad: `R_g`; cacheA: `R_g`; cacheB: `R_g` | pending; null metrics |
| gustavsnn.output_fifo.push / gustavsnn.output_fifo | class=fifo, depth=8, width=32 | csv_cmos; 7 | 16 | spad: `W_o/32`; cacheA: `W_o/32`; cacheB: `W_o/32` | pending; null metrics |
| gustavsnn.potential_regfile.rmw / gustavsnn.potential_regfile | class=register_file, depth=64, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending; null metrics |
| gustavsnn.reg16.rmw / gustavsnn.reg16 | class=register, width=16 | csv_cmos; 7 | 64 | spad: `A`; cacheA: `A`; cacheB: `A` | pending own-RTL500MHz; default null / dummy historical magnitude |
| gustavsnn.spike_fifo.pop / gustavsnn.spike_fifo | class=fifo, depth=8, width=32 | csv_cmos; 7 | 16 | spad: `R_g`; cacheA: `R_g`; cacheB: `R_g` | pending; null metrics |
## prosperity

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| prosperity.adder16.add / prosperity.adder16 | class=adder, width=16 | csv_cmos; 7 | 64 | spad: `A_p`; cacheA: `A_p`; cacheB: `A_p` | pending own-RTL500MHz; default null / dummy historical magnitude |
| prosperity.bitonic_cmp.compare / prosperity.bitonic_cmp | class=bitonic_cmp, width=13 | csv_cmos; 7 | 16 | spad: `SORT`; cacheA: `SORT`; cacheB: `SORT` | pending; null metrics |
| prosperity.bsf16.scan / prosperity.bsf16 | class=bsf16, width=16 | csv_cmos; 7 | 64 | spad: `R_p`; cacheA: `R_p`; cacheB: `R_p` | pending; null metrics |
| prosperity.l1_weight_spad.read / prosperity.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `R_p` | priced; see unit-cost assumptions |
| prosperity.l1_weight_spad.write / prosperity.l1_weight_spad | bank=1, class=sram, depth=8192, width=32 | cacti_fn; 7 | 16 | spad: `l1_delivery_bytes*8/32.0` | priced; see unit-cost assumptions |
| prosperity.lif_core.step / prosperity.lif_core | class=lif_unit, input_width=16, state_register=False, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending; null metrics |
| prosperity.lif_state.rmw / prosperity.lif_state | class=register, width=32 | csv_cmos; 7 | 64 | spad: `L`; cacheA: `L`; cacheB: `L` | pending own-RTL500MHz; default null / dummy historical magnitude |
| prosperity.popcount16.count / prosperity.popcount16 | class=popcount16, width=16 | csv_cmos; 7 | 128 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | pending; null metrics |
| prosperity.pruner.prune / prosperity.pruner | channels=256, class=pruner, width=16 | csv_cmos; 7 | 16 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | pending; null metrics |
| prosperity.ps_table.read / prosperity.ps_table | bank=1, class=sram, depth=256, width=48 | cacti_fn; 7 | 16 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | priced; see unit-cost assumptions |
| prosperity.ps_table.write / prosperity.ps_table | bank=1, class=sram, depth=256, width=48 | cacti_fn; 7 | 16 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | priced; see unit-cost assumptions |
| prosperity.psum_buffer.read / prosperity.psum_buffer | bank=1, class=sram, depth=512, width=16 | cacti_fn; 7 | 16 | spad: `seed_reads_bound`; cacheA: `seed_reads_bound`; cacheB: `seed_reads_bound` | priced; see unit-cost assumptions |
| prosperity.psum_buffer.write / prosperity.psum_buffer | bank=1, class=sram, depth=512, width=16 | cacti_fn; 7 | 16 | spad: `psum_writes`; cacheA: `psum_writes`; cacheB: `psum_writes` | priced; see unit-cost assumptions |
| prosperity.reg16.rmw / prosperity.reg16 | class=register, width=16 | csv_cmos; 7 | 64 | spad: `A_p`; cacheA: `A_p`; cacheB: `A_p` | pending own-RTL500MHz; default null / dummy historical magnitude |
| prosperity.spike_row_buffer.read / prosperity.spike_row_buffer | bank=1, class=sram, depth=512, width=16 | cacti_fn; 7 | 16 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | priced; see unit-cost assumptions |
| prosperity.spike_row_buffer.write / prosperity.spike_row_buffer | bank=1, class=sram, depth=512, width=16 | cacti_fn; 7 | 16 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | priced; see unit-cost assumptions |
| prosperity.tcam.search / prosperity.tcam | class=tcam_256x16, depth=256, width=16 | csv_cmos; 7 | 32 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | pending; null metrics |
| prosperity.tcam.write / prosperity.tcam | class=tcam_256x16, depth=256, width=16 | csv_cmos; 7 | 32 | spad: `N_rows`; cacheA: `N_rows`; cacheB: `N_rows` | pending; null metrics |
## cache

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| cache.distance_logic.step / cache.distance_logic | class=prefetcher, width=64 | csv_cmos; 7 | 1 | cacheA: `l2_pf_issued` | excluded by decision (prefetch control); all three metrics zero |
| cache.distance_metadata.read / cache.distance_metadata | bank=1, class=sram, depth=8192, width=64 | cacti_fn; 7 | 1 | cacheA: `l1_accesses` | excluded by decision (prefetch control); all three metrics zero |
| cache.distance_metadata.write / cache.distance_metadata | bank=1, class=sram, depth=8192, width=64 | cacti_fn; 7 | 1 | cacheA: `l1_accesses` | excluded by decision (prefetch control); all three metrics zero |
| cache.l1.read / cache.l1 | associativity=8, bank=1, class=cache, size=131072, width=512 | cacti_fn; 7 | 16 | cacheA: `l1_accesses`; cacheB: `l1_accesses` | priced; see unit-cost assumptions |
| cache.l1.write / cache.l1 | associativity=8, bank=1, class=cache, size=131072, width=512 | cacti_fn; 7 | 16 | cacheA: `l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve`; cacheB: `l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | priced; see unit-cost assumptions |
| cache.l1_tags.read / cache.l1_tags | bank=1, class=sram, depth=32, width=256 | cacti_fn; 7 | 0 | cacheA: `2*pf_issued+pf_budget_exhausted`; cacheB: `2*pf_issued+pf_budget_exhausted` | excluded by decision (prefetch control); all three metrics zero |
| cache.l2.read / cache.l2 | associativity=16, bank=1, class=cache, size=4194304, width=512 | cacti_fn; 7 | 1 | cacheA: `l2_accesses`; cacheB: `l2_accesses` | priced; see unit-cost assumptions |
| cache.l2.write / cache.l2 | associativity=16, bank=1, class=cache, size=4194304, width=512 | cacti_fn; 7 | 1 | cacheA: `dram_accesses`; cacheB: `dram_accesses` | priced; see unit-cost assumptions |
| cache.l2_tags.read / cache.l2_tags | bank=1, class=sram, depth=512, width=512 | cacti_fn; 7 | 0 | cacheA: `l2_pf_issued+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve`; cacheB: `l2_pf_issued+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | excluded by decision (prefetch control); all three metrics zero |
| cache.mshr_cam_l1.search / cache.mshr_cam_l1 | class=mshr_cam, depth=16, width=64 | csv_cmos; 7 | 16 | cacheA: `l1_accesses-l1_hits+l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve`; cacheB: `l1_accesses-l1_hits+l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | pending; null metrics |
| cache.mshr_cam_l2.search / cache.mshr_cam_l2 | class=mshr_cam, depth=32, width=64 | csv_cmos; 7 | 1 | cacheA: `l2_accesses-l2_hits+dram_accesses`; cacheB: `l2_accesses-l2_hits+dram_accesses` | pending; null metrics |
| cache.mshr_targets_l1.write / cache.mshr_targets_l1 | class=register_file, depth=320, width=64 | csv_cmos; 7 | 16 | cacheA: `l1_accesses-l1_hits`; cacheB: `l1_accesses-l1_hits` | pending; null metrics |
| cache.mshr_targets_l2.write / cache.mshr_targets_l2 | class=register_file, depth=384, width=64 | csv_cmos; 7 | 1 | cacheA: `l2_accesses-l2_hits`; cacheB: `l2_accesses-l2_hits` | pending; null metrics |
| cache.next_access_logic.step / cache.next_access_logic | class=prefetcher, width=64 | csv_cmos; 7 | 16 | cacheA: `pf_issued` | excluded by decision (prefetch control); all three metrics zero |
| cache.next_access_state.rmw / cache.next_access_state | class=register, width=32 | csv_cmos; 7 | 48 | cacheA: `3*pf_issued` | excluded by decision (prefetch control); all three metrics zero |
| cache.next_line_l1.add / cache.next_line_l1 | class=adder, width=64 | csv_cmos; 7 | 16 | cacheB: `pf_issued` | excluded by decision (prefetch control); all three metrics zero |
| cache.next_line_l2.add / cache.next_line_l2 | class=adder, width=64 | csv_cmos; 7 | 1 | cacheB: `l2_pf_issued` | excluded by decision (prefetch control); all three metrics zero |
## shared

| Operation / physical module | Geometry and query | Source interface; nm | System instances | Performance count by arm | Cost status |
|---|---|---|---:|---|---|
| shared.ddr4.read / shared.ddr4 | class=ddr4, size=8589934592 bits (1 GiB), 64 B burst, eight 8 B array reads, 1600 MHz/64-pin IO | cacti7; 22 | 1 | spad: `dram_accesses`; cacheA: `dram_accesses`; cacheB: `dram_accesses` | priced; see unit-cost assumptions |
| shared.ddr4_io.byte / shared.ddr4_io | incremental per-byte DDR4 IO; standing power in ddr4 row | cacti7_ddr4_external_io; 22 | 0 | spad: `dram_bytes`; cacheA: `dram_bytes`; cacheB: `dram_bytes` | priced; see unit-cost assumptions |
| shared.gb.read / shared.gb | bank=1, class=sram, depth=65536, width=256 | cacti_fn; 7 | 1 | spad: `gb_reads` | priced; see unit-cost assumptions |
| shared.gb.write / shared.gb | bank=1, class=sram, depth=65536, width=256 | cacti_fn; 7 | 1 | spad: `gb_writes` | priced; see unit-cost assumptions |
| shared.link.hop / shared.link | 320-bit packet, 1 mm link, 0.7 V, C=1.9362352e-16 F/um | ASAP7_global_wire_CV2; 7 | 48 | spad: `weight_packet_hops+chain_packet_hops`; cacheA: `chain_packet_hops`; cacheB: `chain_packet_hops` | priced; see unit-cost assumptions |
| shared.router.hop / shared.router | 320-bit packet, 4x4 mesh, pending 7 nm characterization | scaled_archx_router_csv; 7 | 16 | spad: `weight_packet_hops+chain_packet_hops`; cacheA: `chain_packet_hops`; cacheB: `chain_packet_hops` | pending; null metrics |

The LoAS output FIFO count is packed timestep words. GustavSNN uses
`W_o/32` packed bits. Prosperity front-end scans count every row, including
rows that prune to no weight records; exact `R_p` comes from `record_count.csv`.
Prosperity psum seed/write bounds use `N_rows*COUT`. Its LIF core omits state;
the separate register RMW charges state. Core counts are identical across arms.
Cache arms retain only k/t-chain mesh hops; spad also charges weight hops.
When characterized, all arms pay the full fixed-router standing inventory.

## Dry-run RTL specification

Coverage is48 RTL-priced composition rows,41 physical-model rows and9 prefetch-control exclusions. All48 vectors use the24-basic catalog; four glue leaves are present and13 authored whole tops are unsynthesized references only.

TCAM: two256x16 flop-based masked-match banks, match=(entry AND query)==entry. Archived excluded contracts: L1 next_access has four64-bit address entries, no data buffer and three32-bit state words/core; L2 distance metadata is8192x64-bit SRAM. Both extra L1/L2 tag-probe rows are excluded while retaining their count formulas. The event set/count expressions are unchanged. The optional `characterization/energy_table_dummy.json` fills all48 pending rows with DUMMY prices; every filled row remains incomplete and its assumption propagates into result.json. This table is only a dry-run sensitivity point, not ASAP7 synthesis.

The [manual check map](docs/manual_check_map.md) links each module role, operation event and count formula to its definition.

Query frequency is 500 MHz throughout. FN-CACTI accepts it as metadata: twelve unique geometries returned exactly equal read/write energy, leakage and area in separate 100/500 MHz runs ([measurement](provenance/cacti_frequency.json)). This is not a clock-constrained memory implementation; the system time base is 500 MHz and the DDR bus stays at its separately pinned 1600 MHz.
