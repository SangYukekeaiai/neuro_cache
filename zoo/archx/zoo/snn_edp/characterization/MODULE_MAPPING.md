# Complete RTL-module mapping

**Source:** [UnaryLab/verilog_modules](https://github.com/UnaryLab/verilog_modules), pinned `3e6135c9cb8c735439e2968cd3446dbd10fe55b3` at `/u/yyu9/projects/verilog_modules`. **Target:** ASAP7 RVT TT,0.70V/25°C (`PVT_0P7V_25C`),500MHz (2000ps). **Status:** four one-assignment glue leaves are present;13 authored whole tops are unsynthesized references only. All48 logic rows use measured-basic composition prices.

Every hardware.json key appears once in the architecture tables: **98/98 rows accounted for; 48 RTL, 41 physical-model, 9 excluded by decision (prefetch control).** Push/pop and read/write remain separate visible operations but share their physical instance. Event counts and geometry are retained. The nine intentional zero prices are specified by [pricing_policy.json](pricing_policy.json). Exact source hashes/contracts, full key lists and document archives are in [STRUCTURAL_AUDIT.json](STRUCTURAL_AUDIT.json); geometry/top paths in [the worklist](auto_syn_pnr_worklist.json); flow in [the plan](ASAP7_SYNTHESIS_PLAN.md).

## Basic classes and composition basis

[**BASIC_MODULES.md**](BASIC_MODULES.md) is the single variant catalog: exact paths/ports for the five pinned repo classes, the four authored one-assignment glue leaves and the24 TT basic characterization variants. `adder64` has no active consumer; next-line, next-access and distance are all excluded. Router FIFO depth is fixed at2; its masks use register5 words, not new FIFO variants.

The canonical machine-readable counts and named decomposition terms are `STRUCTURAL_AUDIT.json.quantified_composition.operations`. The table below is generated from that object. Every integer is per **ONE physical unit**, not per node, bank pair, operation count or packet. Repeated read/write and push/pop rows share hardware. `N/node` means N units per node and16 nodes; `N/system` is already a system total. SpinalFlow arithmetic/compare/state use the four-lane override in `model.py::instances`. TCAM rows each describe one256×16 bank; two banks/node are standing inventory, not a multiplier inside the composition.

All48 logic rows use **composition pricing** from their unchanged integer vectors; direct primitives are one-term sums. No whole-top report is used. The exact union is24 basics; the authored whole tops are [unsynthesized references only](rtl_tops/README.md).

At500MHz, report energy per cycle(nJ)=dynamic power(mW)/500. Dynamic energy is `dynamic_event_cycles * sum(N * leaf_energy_per_cycle)`; leakage/area are `sum(N * leaf_leakage/area)`. All event multipliers are1 except router packet-hop=5 flit cycles. Never apply that multiplier to area/leakage; apply standing inventory once per physical module. Native I/O/activity defaults are retained without per-operation VCD. The no-VCD branch logs50% switch activity; preserve actual report provenance. N×register arrays do not model inactive-word gating, and sums do not characterize composed interconnect, fanout, optimization or timing.

## Quantified helper definitions

The structural vectors below are unchanged and all are used for pricing. Gate names follow BASIC_MODULES; `mux2` counts scalar bits. No NAND/NOR/decoder pseudo-primitive or conversion factor is used. Named terms in the audit preserve the formula for every count. Counts are the fixed preoptimization recipe, not a predicted optimized netlist; all declared comparator outputs and the catalog's priority-chain convention are retained.

- **EqualityW:** W xor_gate +(W−1) or_gate +1 not_gate. **Unsigned compareW:** 1 adderW +W xor_gate +W or_gate +(W+2) not_gate: `a+~b` carry=gt, equality as above, ge=gt OR eq, lt=NOT ge. **Signed compareW:** additionally1 xor_gate,1 or_gate,1 not_gate,2 mux2 for sign-difference selection and signed ge. Thus compare32 uses1 adder32 with explicit equality/sign glue; repo temporal less_equal is not used.
- **PriorityN:** N and_gate +N not_gate +(N−1) prefix/valid or_gate; index encoding adds log2(N)×(N/2−1) or_gate for16/32. Priority5 onehot uses the chain alone; original-index encoding needs2 or_gate. BSFN adds N xor_gate to clear the selected onehot. Lowest-set-bit wins; zero gives valid0/index0.
- **LIF core:** integration adder32 +signed compare32 +64 mux2 (32 leak shift-select,32 hard-zero select). Shifts/sign extension are wires; no multiplier/subtractor. Stateful adds1 register32 +1 register1 with step wired to both enables. The source `zoo/fig12_edp/docs/lif_unit.md` folds input scaling into weights.
- **Decoder N,A:** A=ceil(log2N), N×(A−1) and_gate +A shared not_gate; write-enable gating adds N and_gate. For320/384 entries A=9; unused codes assert no output without an extra comparator. Potential RF adds a64:1 read32 mux=(64−1)×32 mux2; target RF exposes all words and excludes the consumer's read mux.
- **CAM:** D tag64 and D valid1 words; D equality64 trees, D valid-match ANDs, priorityD, two decoders for input allocation/free indices,2D enable ANDs, and D each NOT/AND/OR for `next_valid=allocate OR (valid AND NOT free)`. Allocate wins; valid registers always enabled. Allocation index is an input, not an uncounted free-slot allocator.
- **TCAM:** ONE bank of256 register16;16 shared query NOT,4096 subset AND,256×15 reduction OR,256 result NOT, one256-output decoder plus256 write-enable ANDs. Search/write share this bank. Processed-valid masking belongs to pruner.
- **Pruner:**256 eligibility AND +255 unsigned compare13; each tournament node adds1 NOT,2 OR,1 AND and21 mux2 (key13+slot8). Original-row selection adds255×16 mux2, residual adds16 XOR and no-match bypass16 mux2. Original rows, subset matches, keys and processed-valid are input ports; this boundary does not claim their external generation/storage is covered by this row or silently duplicate TCAM.
- **Router depth2:** five unchanged FIFO64x2 contain their own output64 holding registers. Per input: two mirrored2-bit pointers/incrementers, two queued register5 masks, one pending register5 mask and one head-valid register1. Per output: RR register3, held-grant register3, lock register1, increment adder3. Five and_gate_5 clear pending masks with25 NOT; scalar ANDs are not also charged for those mask operations. The audit itemizes pointer acceptance, mask decoders/write/read muxes, requests, priority/rotate/encode/held-grant selection, ack/handshake/lock updates and five5:1 data64 crossbar muxes. Zero pending mask discards; head replaces only after all requested handshakes. iClr is tied0; hold reset through a clock edge for synchronous helpers and suppress handshakes in reset. This is an explicit proposed structural recipe, not an extracted simulator netlist.

## Quantified composition by module and operation

| Module / operation key | Structural primitive/glue leaves per ONE physical unit | Dynamic event cycles | Standing units (shared across operations) | Pricing basis |
|---|---|---|---|---|
| `spinalflow.adder32.add` | 1×adder32 | 1 | 4/node | composition |
| `spinalflow.cmp32.compare` | 1×adder32 + 33×or_gate + 33×xor_gate + 35×not_gate + 2×mux2 | 1 | 4/node | composition |
| `spinalflow.min_tree4.compare` | 3×adder32 + 3×and_gate + 102×or_gate + 96×xor_gate + 105×not_gate + 102×mux2 | 1 | 1/node | composition |
| `spinalflow.reg32.rmw` | 1×register32 | 1 | 4/node | composition |
| `ptb.adder16.add` | 1×adder16 | 1 | 32/node | composition |
| `ptb.lif_unit.step` | 2×adder32 + 1×register1 + 1×register32 + 33×or_gate + 33×xor_gate + 35×not_gate + 66×mux2 | 1 | 4/node | composition |
| `ptb.spike_mask_overlap.check` | 32×and_gate + 31×or_gate + 1×not_gate | 1 | 1/node | composition |
| `ptb.reg16.read` | 1×register16 | 1 | 128/node | composition |
| `ptb.reg16.rmw` | 1×register16 | 1 | 128/node | composition |
| `ptb.spike_fifo.pop` | 1×fifo16x8 | 1 | 1/node | composition |
| `ptb.spike_fifo.push` | 1×fifo16x8 | 1 | 1/node | composition |
| `ptb.weight_fifo.pop` | 1×fifo16x8 | 1 | 1/node | composition |
| `ptb.weight_fifo.push` | 1×fifo16x8 | 1 | 1/node | composition |
| `loas.adder16.add` | 1×adder16 | 1 | 128/node | composition |
| `loas.and_gate.and` | 1×and_gate | 1 | 128/node | composition |
| `loas.bsf32.scan` | 32×and_gate + 106×or_gate + 32×xor_gate + 32×not_gate | 1 | 4/node | composition |
| `loas.lif_unit.step` | 2×adder32 + 1×register1 + 1×register32 + 33×or_gate + 33×xor_gate + 35×not_gate + 66×mux2 | 1 | 4/node | composition |
| `loas.output_fifo.push` | 1×fifo32x8 | 1 | 1/node | composition |
| `loas.spike_prefix_scan32.scan` | 31×adder1 + 30×adder2 + 28×adder3 + 24×adder4 + 16×adder5 | 1 | 4/node | composition |
| `loas.reg16.read` | 1×register16 | 1 | 128/node | composition |
| `loas.reg16.rmw` | 1×register16 | 1 | 128/node | composition |
| `loas.spike_fifo.pop` | 1×fifo32x8 | 1 | 1/node | composition |
| `loas.spike_fifo.push` | 1×fifo32x8 | 1 | 1/node | composition |
| `loas.weight_fifo.pop` | 1×fifo16x8 | 1 | 1/node | composition |
| `loas.weight_fifo.push` | 1×fifo16x8 | 1 | 1/node | composition |
| `gustavsnn.adder16.add` | 1×adder16 | 1 | 4/node | composition |
| `gustavsnn.leading_spike_detector.scan` | 32×and_gate + 106×or_gate + 32×not_gate | 1 | 2/node | composition |
| `gustavsnn.lif_core.step` | 2×adder32 + 33×or_gate + 33×xor_gate + 35×not_gate + 66×mux2 | 1 | 4/node | composition |
| `gustavsnn.merger_tree2.merge` | 1×adder32 + 1×and_gate + 33×or_gate + 32×xor_gate + 35×not_gate + 68×mux2 | 1 | 1/node | composition |
| `gustavsnn.output_fifo.push` | 1×fifo32x8 | 1 | 1/node | composition |
| `gustavsnn.potential_regfile.rmw` | 64×register32 + 384×and_gate + 6×not_gate + 2016×mux2 | 1 | 4/node | composition |
| `gustavsnn.reg16.rmw` | 1×register16 | 1 | 4/node | composition |
| `gustavsnn.spike_fifo.pop` | 1×fifo32x8 | 1 | 1/node | composition |
| `prosperity.adder16.add` | 1×adder16 | 1 | 4/node | composition |
| `prosperity.bitonic_cmp.compare` | 1×adder13 + 13×or_gate + 13×xor_gate + 15×not_gate + 26×mux2 | 1 | 1/node | composition |
| `prosperity.bsf16.scan` | 16×and_gate + 43×or_gate + 16×xor_gate + 16×not_gate | 1 | 4/node | composition |
| `prosperity.lif_core.step` | 2×adder32 + 33×or_gate + 33×xor_gate + 35×not_gate + 66×mux2 | 1 | 4/node | composition |
| `prosperity.lif_state.rmw` | 1×register32 | 1 | 4/node | composition |
| `prosperity.popcount16.count` | 8×adder1 + 4×adder2 + 2×adder3 + 1×adder4 | 1 | 8/node | composition |
| `prosperity.pruner.prune` | 255×adder13 + 511×and_gate + 3825×or_gate + 3331×xor_gate + 4080×not_gate + 9451×mux2 | 1 | 1/node | composition |
| `prosperity.reg16.rmw` | 1×register16 | 1 | 4/node | composition |
| `prosperity.tcam.search` | 256×register16 + 6144×and_gate + 3840×or_gate + 280×not_gate | 1 | 2/node (banks) | composition |
| `prosperity.tcam.write` | 256×register16 + 6144×and_gate + 3840×or_gate + 280×not_gate | 1 | 2/node (banks) | composition |
| `cache.mshr_cam_l1.search` | 16×register1 + 16×register64 + 176×and_gate + 1067×or_gate + 1024×xor_gate + 56×not_gate | 1 | 16/system | composition |
| `cache.mshr_cam_l2.search` | 32×register1 + 32×register64 + 416×and_gate + 2154×or_gate + 2048×xor_gate + 106×not_gate | 1 | 1/system | composition |
| `cache.mshr_targets_l1.write` | 320×register64 + 2880×and_gate + 9×not_gate | 1 | 16/system | composition |
| `cache.mshr_targets_l2.write` | 384×register64 + 3456×and_gate + 9×not_gate | 1 | 1/system | composition |
| `shared.router.hop` | 10×adder2 + 5×adder3 + 10×register1 + 10×register2 + 10×register3 + 15×register5 + 5×fifo64x2 + 225×and_gate + 5×and_gate_5 + 65×or_gate + 10×xor_gate + 115×not_gate + 1560×mux2 | 5 | 16/system | composition |

The41 physical-model rows below keep their macro/DRAM/wire geometry; the9 excluded rows retain Stage A counts and archived contracts without active synthesis/pricing allocations.



## spinalflow

Coverage: **18 of 18 rows mapped to an explicit implementation/model** (4 RTL;14 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `spinalflow.adder32.add` | repo adder(32) | RTL mapped |
| `spinalflow.cmp32.compare` | adder32 + signed compare glue | RTL mapped |
| `spinalflow.input_spike_buffer.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.input_spike_buffer.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.l1_weight_spad.read` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `spinalflow.l1_weight_spad.write` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `spinalflow.min_tree4.compare` | 3×compare32 + mux/valid glue | RTL mapped |
| `spinalflow.output_spike_queue.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.output_spike_queue.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.psum_l1.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.psum_l1.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.psum_l2.read` | cacti_fn SRAM 32×16384 | Physics: SRAM/cache |
| `spinalflow.psum_l2.write` | cacti_fn SRAM 32×16384 | Physics: SRAM/cache |
| `spinalflow.reg32.rmw` | common register 32 | RTL mapped |
| `spinalflow.vmem_l1.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.vmem_l1.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `spinalflow.vmem_l2.read` | cacti_fn SRAM 32×16384 | Physics: SRAM/cache |
| `spinalflow.vmem_l2.write` | cacti_fn SRAM 32×16384 | Physics: SRAM/cache |

## ptb

Coverage: **15 of 15 rows mapped to an explicit implementation/model** (9 RTL;6 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `ptb.adder16.add` | repo adder(16) | RTL mapped |
| `ptb.l1_weight_spad.read` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `ptb.l1_weight_spad.write` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `ptb.lif_unit.step` | common LIF stateful | RTL mapped |
| `ptb.spike_mask_overlap.check` | 32×and_gate + OR/invert | RTL mapped |
| `ptb.output_spike_queue.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `ptb.output_spike_queue.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `ptb.reg16.read` | common register 16 | RTL mapped |
| `ptb.reg16.rmw` | common register 16 | RTL mapped |
| `ptb.spike_fifo.pop` | common fifo 16×8 | RTL mapped |
| `ptb.spike_fifo.push` | common fifo 16×8 | RTL mapped |
| `ptb.spike_vector_buffer.read` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `ptb.spike_vector_buffer.write` | cacti_fn SRAM 32×256 | Physics: SRAM/cache |
| `ptb.weight_fifo.pop` | common fifo 16×8 | RTL mapped |
| `ptb.weight_fifo.push` | common fifo 16×8 | RTL mapped |

## loas

Coverage: **14 of 14 rows mapped to an explicit implementation/model** (12 RTL;2 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `loas.adder16.add` | repo adder(16) | RTL mapped |
| `loas.and_gate.and` | repo and_gate (scalar) | RTL mapped |
| `loas.bsf32.scan` | common priority32 + selected-bit clear | RTL mapped |
| `loas.l1_weight_spad.read` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `loas.l1_weight_spad.write` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `loas.lif_unit.step` | common LIF stateful | RTL mapped |
| `loas.output_fifo.push` | common fifo 32×8 | RTL mapped |
| `loas.spike_prefix_scan32.scan` | adder1..5 five-level prefix-popcount | RTL mapped |
| `loas.reg16.read` | common register 16 | RTL mapped |
| `loas.reg16.rmw` | common register 16 | RTL mapped |
| `loas.spike_fifo.pop` | common fifo 32×8 | RTL mapped |
| `loas.spike_fifo.push` | common fifo 32×8 | RTL mapped |
| `loas.weight_fifo.pop` | common fifo 16×8 | RTL mapped |
| `loas.weight_fifo.push` | common fifo 16×8 | RTL mapped |

## gustavsnn

Coverage: **10 of 10 rows mapped to an explicit implementation/model** (8 RTL;2 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `gustavsnn.adder16.add` | repo adder(16) | RTL mapped |
| `gustavsnn.l1_weight_spad.read` | cacti_fn SRAM 16×16384 | Physics: SRAM/cache |
| `gustavsnn.l1_weight_spad.write` | cacti_fn SRAM 16×16384 | Physics: SRAM/cache |
| `gustavsnn.leading_spike_detector.scan` | common priority32 (and_gate + prefix/reduction glue) | RTL mapped |
| `gustavsnn.lif_core.step` | common LIF core | RTL mapped |
| `gustavsnn.merger_tree2.merge` | compare32 + two key/lane/valid muxes | RTL mapped |
| `gustavsnn.output_fifo.push` | common fifo 32×8 | RTL mapped |
| `gustavsnn.potential_regfile.rmw` | common regfile 32×64, selected read | RTL mapped |
| `gustavsnn.reg16.rmw` | common register 16 | RTL mapped |
| `gustavsnn.spike_fifo.pop` | common fifo 32×8 | RTL mapped |

## prosperity

Coverage: **18 of 18 rows mapped to an explicit implementation/model** (10 RTL;8 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `prosperity.adder16.add` | repo adder(16) | RTL mapped |
| `prosperity.bitonic_cmp.compare` | compare13 + two key muxes | RTL mapped |
| `prosperity.bsf16.scan` | common priority16 + selected-bit clear | RTL mapped |
| `prosperity.l1_weight_spad.read` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `prosperity.l1_weight_spad.write` | cacti_fn SRAM 32×8192 | Physics: SRAM/cache |
| `prosperity.lif_core.step` | common LIF core | RTL mapped |
| `prosperity.lif_state.rmw` | common register 32 | RTL mapped |
| `prosperity.popcount16.count` | 8×adder1 +4×adder2 +2×adder3 +adder4 | RTL mapped |
| `prosperity.pruner.prune` | compare13 tree + eligibility/mux/XOR glue | RTL mapped |
| `prosperity.ps_table.read` | cacti_fn SRAM 48×256 | Physics: SRAM/cache |
| `prosperity.ps_table.write` | cacti_fn SRAM 48×256 | Physics: SRAM/cache |
| `prosperity.psum_buffer.read` | cacti_fn SRAM 16×512 | Physics: SRAM/cache |
| `prosperity.psum_buffer.write` | cacti_fn SRAM 16×512 | Physics: SRAM/cache |
| `prosperity.reg16.rmw` | common register 16 | RTL mapped |
| `prosperity.spike_row_buffer.read` | cacti_fn SRAM 16×512 | Physics: SRAM/cache |
| `prosperity.spike_row_buffer.write` | cacti_fn SRAM 16×512 | Physics: SRAM/cache |
| `prosperity.tcam.search` | common subset array16×256 (register + match glue) | RTL mapped |
| `prosperity.tcam.write` | common subset array16×256 (register + decode) | RTL mapped |

## Cache hardware

Coverage: **17 of 17 rows mapped to an explicit implementation/model** (4 RTL;4 physics;9 excluded by decision).

| Module / operation key | Built from | Status |
|---|---|---|
| `cache.distance_logic.step` | common distance(d1,t9): adder32/64 + tag/tile/count/FSM glue | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.distance_metadata.read` | cacti_fn SRAM 64×8192 | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.distance_metadata.write` | cacti_fn SRAM 64×8192 | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.l1.read` | cacti_fn cache 16 KiB/8-way | Physics: SRAM/cache |
| `cache.l1.write` | cacti_fn cache 16 KiB/8-way | Physics: SRAM/cache |
| `cache.l1_tags.read` | cacti_fn SRAM 256×32 | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.l2.read` | cacti_fn cache 512 KiB/16-way | Physics: SRAM/cache |
| `cache.l2.write` | cacti_fn cache 512 KiB/16-way | Physics: SRAM/cache |
| `cache.l2_tags.read` | cacti_fn SRAM 512×512 | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.mshr_cam_l1.search` | common regfile64×16 + valid/equality/priority glue | RTL mapped |
| `cache.mshr_cam_l2.search` | common regfile64×32 + valid/equality/priority glue | RTL mapped |
| `cache.mshr_targets_l1.write` | common regfile64×320, write decoder | RTL mapped |
| `cache.mshr_targets_l2.write` | common regfile64×384, write decoder | RTL mapped |
| `cache.next_access_logic.step` | common next_access(d4): adder32/64 + fifo64×4 + register/FSM glue | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.next_access_state.rmw` | common register32, three words/core | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.next_line_l1.add` | repo adder(64): literal `line+1` physical line ID | Excluded by decision: prefetch control (Stage A count retained) |
| `cache.next_line_l2.add` | repo adder(64): literal `line+1` physical line ID | Excluded by decision: prefetch control (Stage A count retained) |

## Shared hardware

Coverage: **6 of 6 rows mapped to an explicit implementation/model** (1 RTL;5 physics).

| Module / operation key | Built from | Status |
|---|---|---|
| `shared.ddr4.read` | cacti7 DDR4 array/access | Physics: DRAM/IO |
| `shared.ddr4_io.byte` | cacti7 DDR4 IO per byte | Physics: DRAM/IO |
| `shared.gb.read` | cacti_fn SRAM 256×65536 | Physics: SRAM/cache |
| `shared.gb.write` | cacti_fn SRAM 256×65536 | Physics: SRAM/cache |
| `shared.link.hop` | ASAP7 wire 0.5CV² | Physics: wire |
| `shared.router.hop` | 5×common fifo64×2 + register/arbiter/mux/mask glue | RTL mapped |

## Source-derived functional contracts

Paths below are relative to `/u/yyu9/projects/neuro_cache_wcache/`; the audit records their full paths/hashes. These are source-defined behavior plus explicitly stated finite implementation choices, not extracted gate-level netlists.

**TPPE scan.** `docs/loas_energy.md` §3.1 and `counts/loas_counts.py` specify32-bit spike-word prefix-popcount/compaction; LoASGen.h itself emits non-silent fetches and contains no scan netlist. Concrete combinational realization: five levels at distances1/2/4/8/16 with31 adder1,30 adder2,28 adder3,24 adder4,16 adder5. Inclusive counts/total use6bits; exclusive positions use5bits. This is a complete circuit contract; the old~80-FA price budget is not its gate count. BSF selects/clears lowest set bit; per-word AND is scalar replicated32 times by the count expression.

**Pruner and TCAM.** `src/lays/weight_trace_gen/prosperity/ProsperityGen.h::reconstruct_sample` stores ORIGINAL rows, sorts stable ascending(popcount,original index), then takes the last processed non-strict subset. The RTL equivalent uses processed_valid AND subset-match, maximum13-bit(popcount5,index8) key, and original-row XOR chosen-original-prefix; equal rows ARE eligible and yield zero residual. No match returns the original row. No strict-only filter is in the source-aligned top; that belongs only to the archived estimate alternative. Per-bank storage is256×16 flops; two banks are physical inventory. Unused zero words are masked by processed_valid. Bitonic compares13-bit keys with stable equality; popcount16 is the15-adder balanced tree.

**Gustav merger record.** `src/lays/weight_trace_gen/gustavsnn/GustavGen.h::reconstruct_tile/addresses_and_ticks` defines per-HO ordered(kh,kw,cin) streams, with separate lane refetches and no cross-lane dedup. Map NR2 comparison to unsigned compact key K=(kh×KW+kw)×CIN+cin,valid and lane sideband; require KH×KW×CIN<=2^32. Compare32 plus two key/sideband muxes puts valid first,ascending key,stable lane0 ties,retaining BOTH equal records. The32-bit hardware row is a key comparator, not the six-int AddressRow serializer. This source-compatible key convention realizes the specified NR2 energy block; it does not assert the generator sorts across lanes or change its timing. min_tree4 similarly excludes invalid lanes and uses stable low-index ties.

**MSHR and target service.** CAMs hold16/32 tag64+valid records, exact-match search,low-hit priority and allocation/free decode; allocate wins same-slot allocate/free. Target arrays hold64×320/384 bits,valid-address write decode and all-word outputs; the consumer's selected-read mux is an explicit external boundary of the write-only row. No missing macro is implied by a flop array. Potential RF32×64 instead includes a selected combinational read. Read/write operations share inventory.

## Excluded by decision / archived prefetch contracts

These nine rows are excluded from Stage B pricing and the active synthesis round by the prefetch-control decision; their Stage A counts remain visible. This is a scope decision, not a claim that the circuits cannot be built. The former prefetcher worklist entry is preserved in `STRUCTURAL_AUDIT.json.excluded_archive`.

| Excluded operation | Archived implementation boundary |
|---|---|
| `cache.next_access_logic.step` | Controller with one FIFO64×4 and scratch counters/FSM; exact arithmetic sharing/state encoding was not fixed. No invented primitive total. |
| `cache.distance_logic.step` | Touch/update/threshold controller and forward-COUT helper; exact sequencer/divider sharing was not fixed. No invented primitive total. |
| `cache.next_access_state.rmw` | 1×register32 per word; three words/core, 48 standing words/system are defined but not charged; repeated RMWs do not add storage. |
| `cache.distance_metadata.read` | One shared SRAM64×8192 read/write macro; archived packing/fidelity limits below. |
| `cache.distance_metadata.write` | Same SRAM64×8192 as read, not a second macro. |
| `cache.l1_tags.read` | Extra prefetch tag probes modeled as SRAM256×32 accesses; zero extra standing units (tags already in L1). |
| `cache.next_line_l1.add` | One adder64 per incrementer;16/system; literal `line+1` physical line ID; excluded with zero price. |
| `cache.next_line_l2.add` | One adder64 per incrementer;1/system; literal `line+1` physical line ID; excluded with zero price. |
| `cache.l2_tags.read` | Archived SRAM512×512 extra-probe model; zero added standing inventory. Stage A count: `l2_pf_issued+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve`. |

The following contracts are historical proposals, not current priced inventory or scheduled tops. References to charging/characterization inside them describe the archived proposal only.

**next_access d4.** `src/lays/cachesim/native/src/prefetch/next_access.cpp` and `engine.cpp::prefetch_on_demand` specify: per core `{pf_cursor,last_tile,last_burst}` are three32-bit words, reset `{0,-1,-1}` per tile (store the last_* words complemented so the repo zero-reset register decodes −1). Suppress duplicate(tile,k); then set cursor=max(cursor,k+1) and enumerate bursts through min(k+4,n_bursts−1). The schedule/address-generator port supplies each indexed future burst and its expanded increasing/distinct line stream; this is lookahead input, not an address prediction from the current line. A four-entry64-bit ADDRESS FIFO streams one burst at a time with shared burst/end counters; no4×64B data buffer or unbounded on-chip trace vector. Resident/in-MSHR drops count as handled; budget refusal aborts the batch. Only a whole handled burst advances cursor; partial issue keeps it until the next demand pull-forward. Engine credits/tag probes/ports are inputs to this controller, not duplicate inventories. Persistent three state words are logic-top state ports, priced by next_access_state; scratch iterator/FIFO/FSM registers belong to the controller. Finite backpressure preserves candidate order, not a claimed cycle-equivalent implementation of the software callback.

**distance_aware d1,t9.** `src/lays/cachesim/native/src/prefetch/distance_aware.cpp`, `config.h` and `engine.cpp::on_l1_probe/on_l2_probe` specify every demand L1 probe—including hits/reprobes—updates `{tile,count}`. Changed tile resets count before increment; the ninth touch triggers exactly once. Production A's effective default is **Touch**, so L2 miss/retrigger firing is disabled. The separately supported Miss mode gates on count>=9, with an unused-prefetch demand-hit retrigger bypass; do not mistake it for production mode. One candidate is the next COUT block, rejected at its extent. Implement tag/tile/threshold comparators,incrementer,RMW sequencer,candidate register and FSM with repo adder/register/gates. SRAM is a distinct read/write port, not logic synthesized into flops.

**Finite metadata contract, explicit fidelity limit.** Keep8192×64 bits. Full tag+tile32+count32 cannot fit64 bits. Proposed implementable packing is **tag28 + tile32 + saturating-count4**, index=line[12:0],tag=line[40:13],supported line_id<2^41. On a tag/tile mismatch initialize count1; otherwise increment to9 then hold, firing only when old<9 and new==9. Initialize tile words to invalid0xffffffff before use. Count saturation preserves threshold decisions; tag collisions replace history and thus differ from the simulator's unbounded unordered_map. This resolves the hardware, not the mathematical impossibility of exact unbounded history in64KiB. The capacity/collision idealization stays explicit; no simulator eviction logic, table geometry or results are changed. Metadata remains charged per L1 access; distance_logic's existing l2_pf_issued count is a proxy that omits filtered-touch logic activity, so future report extraction must expose touch/issue activity separately before treating it as a complete per-event price.

**Archived layout-neighbour contract: forward COUT address logic.** `src/lays/cachesim/native/src/layout/khkw_split.cpp::neighbour` gives stride=ceil(CIN/16)×min(8,KH×KW),radix=ceil(COUT/4),block=(line/stride)%radix; emit line+stride only if block+1<radix. A finite shift/subtract divider/remainder uses repo adder/compare/register/mux; fixed layer constants may specialize it. No timing or energy result is inferred from this mapping.

**Current Config B NextLine.** NextLine emits physical line IDs `line+1` through `line+d`. Production d1 at both L1 and L2 emits the literal next physical line, `line+1`. The `cache.next_line_l1.add` and `cache.next_line_l2.add` rows map this increment and remain excluded by decision with zero dynamic energy, leakage and area.

## Characterization execution boundary

Active job RTL is the24 flat-derived fixed sources in [basic_variants.json](rtl_tops/basic_variants.json): one `.v`, one module, no hierarchy and a one-file `rtl_list.tcl` per `src/<top>/`. The manifest preserves original-source pin/hashes and derivation; only existing clock/reset ports are renamed `i_clk`/`i_rst_n`, with no clock added to combinational gates.

T91 schedules only the24 basics in BASIC_MODULES, using the project's own `auto_syn_pnr.sh`. The18 worklist families consume their measured reports; all48 operation vectors are priced sums. Authored whole tops are unsynthesized reference-only and their staged tests are not scheduled. The frozen T95 archive retains its prior catalog; these working documents describe the current T91 scope.

Target TT RVT0.70V25C, official `PVT_0P7V_25C`,500MHz (`CLK_PERIOD_NS=2`,2000ps), is pinned by verified [ASAP7_TT_LIBRARIES.json](ASAP7_TT_LIBRARIES.json). Retain native I/O/activity defaults and record report provenance. The config diff is only TT library paths and authorized clock-gating-off; CPU edits are reverted with no CPU environment knob. Keep the original70% square floorplan and native I/O/activity defaults, no VCD or TCL/SDC rewrite. Use the own-project driver and archx `csv_cmos_extract`. Native attempt1 failed Genus POPT-78/no ICG; authorized clock-gating-off attempt2 exited137 at QRC; strict flat-source pilot3 is staging. No successful or accepted result is claimed.

## Modules NOT achievable from repo logic

- **DRAM cells/IO PHY:** retain commodity-memory cacti7 prices; gates do not implement its analog cells/PHY.
- **SRAM/cache/GB macros:** retain cacti_fn; prefetch metadata/tag-probe exclusions remain separate; flop RF/CAM/subset arrays are explicitly digital and ARE mapped.
- **Physical wire:** retain ASAP7-wire0.5CV² and stated zero leakage/area; geometry/capacitance is not a logic primitive.

## DRAM and NoC router schedule

DRAM/IO remain physical models; query-frequency metadata is500MHz while DDR4 bus frequency remains1600MHz. Router uses fixed depth2 and16 standing routers/system. Its price is the explicit measured-leaf sum, with five64-bit flit cycles per320-bit packet-hop for dynamic energy only. A future whole-router characterization would be a distinct result; none is claimed here.

## ALTERNATIVE: archived CSV-composition estimates

[composition_draft_archive.json](composition_draft_archive.json) indexes the tnn/NanGate45 estimate recipe/table and exact source references. If synthesis is delayed it is a separately labeled alternative, never the active default or a500MHz whole-top characterization.

Coverage: cmp32/min-tree; arithmetic/registers; PTB/LoAS FIFOs,merge/AND,scans and LIF; Gustav l1d/merger/LIF-core/RF/FIFOs; Prosperity popcount/bitonic/BSF/pruner/LIF-core; cache next-line/CAM/targets. The draft estimated34 of the then39 pending rows and retained14 then-priced TNN rows. It did NOT cover TCAM read/write,credible router or full controllers; their later arbitrary dummy magnitudes are not characterized estimates. Its strict-only pruner and~80-FA scan budget differ from the explicit source-derived contracts here. Source clocks include100MHz TNN and400MHz NanGate45; interpolation/transfer does not prove500MHz timing,power or activity. Any selection requires a distinct table SHA and visible caveats. Nothing is restored or executed by this document.
