# Figure 1 energy inventory

One node. All operation counts come from the saved native/analytic inputs through archx performance callbacks. Logic instance replication follows the pinned COUT PE configuration. Physical owners are counted once even when several operations share them.

## State contract

Fixed psum/vmem SRAM provisions are 256/512 KiB in every bar. They have zero dynamic accesses and contribute area/leakage once. Accumulation and membrane updates remain in registers/LIF/RFs; no extra SRAM write/read boundary is modeled. This avoids charging state activity twice.

## Per-architecture physical inventory

### ptb

| Physical module | Instances | Geometry / segment |
|---|---:|---|
| `ptb.adder16` | 64 | width=16; compute |
| `ptb.l1_weight_spad` | 1 | width=64, depth=32768, bank=1; on_chip_sram |
| `ptb.lif_unit` | 8 | width=32; compute |
| `ptb.output_spike_queue` | 1 | width=32, depth=256, bank=1; on_chip_sram |
| `ptb.psum_sram` | 1 | width=16, depth=131072, bank=1; on_chip_sram |
| `ptb.reg16` | 256 | width=16; compute |
| `ptb.spike_fifo` | 1 | width=16, depth=8; compute |
| `ptb.spike_mask_overlap` | 1 | width=32; compute |
| `ptb.spike_vector_buffer` | 1 | width=32, depth=256, bank=1; on_chip_sram |
| `ptb.vmem_sram` | 1 | width=32, depth=131072, bank=1; on_chip_sram |
| `ptb.weight_fifo` | 1 | width=16, depth=8; compute |
| `shared.ddr4` | 1 | off_chip_other |
| `shared.ddr4_io` | 0 | off_chip_other |

### loas

| Physical module | Instances | Geometry / segment |
|---|---:|---|
| `loas.adder16` | 512 | width=16; compute |
| `loas.and_gate` | 512 | width=1; compute |
| `loas.bsf32` | 16 | width=32; compute |
| `loas.l1_weight_spad` | 1 | width=128, depth=16384, bank=1; on_chip_sram |
| `loas.lif_unit` | 16 | width=32; compute |
| `loas.output_fifo` | 1 | width=32, depth=8; compute |
| `loas.psum_sram` | 1 | width=16, depth=131072, bank=1; on_chip_sram |
| `loas.reg16` | 512 | width=16; compute |
| `loas.spike_fifo` | 1 | width=32, depth=8; compute |
| `loas.spike_prefix_scan32` | 16 | width=32; compute |
| `loas.vmem_sram` | 1 | width=32, depth=131072, bank=1; on_chip_sram |
| `loas.weight_fifo` | 1 | width=16, depth=8; compute |
| `shared.ddr4` | 1 | off_chip_other |
| `shared.ddr4_io` | 0 | off_chip_other |

### gustavsnn

| Physical module | Instances | Geometry / segment |
|---|---:|---|
| `gustavsnn.adder16` | 8 | width=16; compute |
| `gustavsnn.l1_weight_spad` | 1 | width=64, depth=32768, bank=1; on_chip_sram |
| `gustavsnn.leading_spike_detector` | 1 | width=32; compute |
| `gustavsnn.lif_core` | 8 | width=32; compute |
| `gustavsnn.output_fifo` | 1 | width=32, depth=8; compute |
| `gustavsnn.potential_regfile` | 8 | width=32, depth=64; compute |
| `gustavsnn.psum_sram` | 1 | width=16, depth=131072, bank=1; on_chip_sram |
| `gustavsnn.reg16` | 8 | width=16; compute |
| `gustavsnn.spike_fifo` | 1 | width=32, depth=8; compute |
| `gustavsnn.vmem_sram` | 1 | width=32, depth=131072, bank=1; on_chip_sram |
| `shared.ddr4` | 1 | off_chip_other |
| `shared.ddr4_io` | 0 | off_chip_other |

Weight SRAM geometry shown above is the 256KiB baseline; width is COUT PEs × 8 bits and depth alone changes with capacity. All other geometries and instance counts are fixed across each architecture's sweep. The complete twelve-config table is `configs/arch_manifest.json:energy_inventory`.

## Event and pricing checks

- `archx_config/description.py` defines root → segment → operation → physical-module graphs. Performance callbacks use only `case_dir`, with counts derived in `archx_config/model.py`.
- `archx_config/count.py` saves zero-metric counted graphs and input/code hashes; no table enters its fingerprint.
- `archx_config/price.py` binds `energy_table_asap7_syn.json`, aggregates energy through archx, and checks every term against count × price.
- Ideal changes DDR4 weight reads, IO bytes and local weight fills only. Duration, inventory, non-weight activity and leakage equal the 256KiB baseline.
- `outputs/energy_validation.json` checks all 33,600 term energies, complete 12-layer/10-sample coverage, and unchanged native/archx count inventories.
- Off-chip other is standing DDR4/IO leakage. No input-spike DRAM traffic is emitted by this model, so none is invented.

## Measurement caveat

Genus logic prices are synthesis-only estimates from default-activity reports, using linear width/depth interpolation and additive primitive composition. They omit route parasitics and carry mixed default library corners and unconstrained I/O. SRAM uses FN-CACTI, not synthesized SRAM macros. Both caveats remain in every result and the figure caption.
