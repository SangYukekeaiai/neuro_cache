# Figure 1 energy segments

Physical hierarchy: DRAM ↔ local buffers ↔ PEs. `NoCLevel` is an inert parser slot, not storage. No GB operation, capacity, leakage, or area belongs in Figure 1.

On-chip SRAM contains only local SRAM macros: the swept weight scratchpad, PTB local spike buffers, and the fixed local psum/vmem buffers. Psum is 256 KiB and vmem is 512 KiB in every architecture and SRAM bar; the sizing derivation is in `configs/arch_manifest.json`. Register-based FIFOs, registers, and the potential register file are logic and are included with compute; they are not relabeled as SRAM. Other local geometries are preserved. Fixed state capacity gives a fixed inventory, not identical leakage energy when duration varies. All added psum/vmem SRAM dynamic access counts are zero: state work remains in the native register/LIF/RF operations, with no extra SRAM boundary. Each fixed buffer contributes area and leakage once.

[Machine-readable map](../configs/segment_map.json). Inventory/count inputs with GB activity fail [the count contract](../src/contracts.py).

## ptb

| Operation | Segment |
|---|---|
| `ptb.adder16.add` | Compute and local logic |
| `ptb.l1_weight_spad.read` | On-chip SRAM (local) |
| `ptb.l1_weight_spad.write` | On-chip SRAM (local) |
| `ptb.lif_unit.step` | Compute and local logic |
| `ptb.output_spike_queue.read` | On-chip SRAM (local) |
| `ptb.output_spike_queue.write` | On-chip SRAM (local) |
| `ptb.reg16.read` | Compute and local logic |
| `ptb.reg16.rmw` | Compute and local logic |
| `ptb.spike_fifo.pop` | Compute and local logic |
| `ptb.spike_fifo.push` | Compute and local logic |
| `ptb.spike_mask_overlap.check` | Compute and local logic |
| `ptb.spike_vector_buffer.read` | On-chip SRAM (local) |
| `ptb.spike_vector_buffer.write` | On-chip SRAM (local) |
| `ptb.weight_fifo.pop` | Compute and local logic |
| `ptb.weight_fifo.push` | Compute and local logic |

## loas

| Operation | Segment |
|---|---|
| `loas.adder16.add` | Compute and local logic |
| `loas.and_gate.and` | Compute and local logic |
| `loas.bsf32.scan` | Compute and local logic |
| `loas.l1_weight_spad.read` | On-chip SRAM (local) |
| `loas.l1_weight_spad.write` | On-chip SRAM (local) |
| `loas.lif_unit.step` | Compute and local logic |
| `loas.output_fifo.push` | Compute and local logic |
| `loas.reg16.read` | Compute and local logic |
| `loas.reg16.rmw` | Compute and local logic |
| `loas.spike_fifo.pop` | Compute and local logic |
| `loas.spike_fifo.push` | Compute and local logic |
| `loas.spike_prefix_scan32.scan` | Compute and local logic |
| `loas.weight_fifo.pop` | Compute and local logic |
| `loas.weight_fifo.push` | Compute and local logic |

## gustavsnn

| Operation | Segment |
|---|---|
| `gustavsnn.adder16.add` | Compute and local logic |
| `gustavsnn.l1_weight_spad.read` | On-chip SRAM (local) |
| `gustavsnn.l1_weight_spad.write` | On-chip SRAM (local) |
| `gustavsnn.leading_spike_detector.scan` | Compute and local logic |
| `gustavsnn.lif_core.step` | Compute and local logic |
| `gustavsnn.output_fifo.push` | Compute and local logic |
| `gustavsnn.potential_regfile.rmw` | Compute and local logic |
| `gustavsnn.reg16.rmw` | Compute and local logic |
| `gustavsnn.spike_fifo.pop` | Compute and local logic |

## Off-chip traffic

| Price basis | Weight transfers | Other transfers |
|---|---|---|
| `shared.ddr4.read` | Off-chip (weights) | Off-chip (other) |
| `shared.ddr4_io.byte` | Off-chip (weights) | Off-chip (other) |

Tensor annotations determine the split before per-transaction burst rounding. The partition must sum exactly to measured DRAM totals; a missing traffic class is reported as zero only when the trace proves it. No input/psum traffic is invented to populate a segment.

Single-node outputs must have zero GB reads/writes and zero inter-node packet/chain hops. Shared GB and inter-node router/link inventory are absent. The ideal comparison substitutes only weight-related off-chip traffic and its implied local weight fills; other operations and time remain fixed.

The fixed `psum_sram.read/write` and `vmem_sram.read/write` events in each architecture have count zero and map to local SRAM. The one-HO GustavSNN front end has one detector and no merger. Off-chip other contains standing DDR4/IO leakage; emitted DRAM dynamic traffic is entirely weight traffic.
