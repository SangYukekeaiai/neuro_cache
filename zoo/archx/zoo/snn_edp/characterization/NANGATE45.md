# NanGate45 interim pricing

NanGate45-characterized prices applied to a 7nm/500MHz performance model; interim until ASAP7 synthesis.

Table: [energy_table_nangate45.json](energy_table_nangate45.json), SHA256 `2d8e4ea0b0f836a547ee6ec9301bff004928a8b19814aeb007f102afdc8295a3`. [Manifest](energy_table_nangate45.manifest.json) and [operation-by-operation substitutions](nangate45_substitutions.json) pin sources, rows, reports, reasons and every scale factor. Default and dummy tables are unchanged.

The 98 operations comprise 48 logic compositions, 38 CACTI memories, one physics-based wire, two unchanged cacti7 DDR4/IO rows, and nine excluded zero-price prefetch operations. No retired tnn source is used.

Stage-A `technology_nm` and `query` remain the saved hardware contract. `characterization_technology_nm` and `price_basis` identify the independent pricing technology. This preserves count fingerprints; only Stage B runs. The 45nm costs do not establish 500MHz timing or a physically realizable mixed-node implementation.

Logic CSV columns named `dynamic_uw` and `leakage_uw` contain mW: each is checked against the raw postRouteOpt report headers and values. Energy is source dynamic mW divided by the source row frequency (400MHz for these rows), never divided by the performance clock. Area is the reported cell area in µm² converted to mm². Source activity is inherited; no operation-specific trace activity is characterized.

No whole-module characterization is implied by the additive vectors. Every operation uses the existing audited primitive-count vector; dynamic includes its declared event-cycle multiplier, while standing leakage/area do not. Width and FIFO storage-bit scaling retain source control overhead proportionally. Inactive register-array words receive no activity discount.

| Required primitive | Characterized 45nm source | Scale | Reason |
| --- | --- | ---: | --- |
| `adder1` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.03125 | 1-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder13` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.40625 | 13-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder16` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.5 | 16-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder2` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.0625 | 2-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder3` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.09375 | 3-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder32` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 1 | 32-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder4` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.125 | 4-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `adder5` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/adder.csv` (400MHz) | 0.15625 | 5-bit integer adder approximated by the characterized 32-bit adder with linear width scaling; no separate timing inference. |
| `and_gate` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/and_bitwise.csv` (400MHz) | 1 | One characterized one-bit AND. |
| `and_gate_5` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/and_bitwise.csv` (400MHz) | 4 | Five-input AND is a tree of four characterized two-input AND gates. |
| `fifo16x8` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/fifo.csv` (400MHz) | 1 | FIFO 16x8 uses characterized FIFO16x8 scaled by stored bits (16*8)/(16*8); pointer/control scaling is an explicit approximation. |
| `fifo32x8` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/fifo.csv` (400MHz) | 2 | FIFO 32x8 uses characterized FIFO16x8 scaled by stored bits (32*8)/(16*8); pointer/control scaling is an explicit approximation. |
| `fifo64x2` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/fifo.csv` (400MHz) | 1 | FIFO 64x2 uses characterized FIFO16x8 scaled by stored bits (64*2)/(16*8); pointer/control scaling is an explicit approximation. |
| `mux2` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/multiplexer.csv` (400MHz) | 0.0625 | One-bit 2:1 mux uses 1/16 of the characterized 16-bit 2:1 MULTIPLEXER; shared-select/control overhead scales with width. |
| `not_gate` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/xor_bitwise.csv` (400MHz) | 1 | No inverter CSV: a one-bit XOR with one input tied high is the logical neighbor; charge the complete characterized XOR, without constant-folding discount. |
| `or_gate` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/or_bitwise.csv` (400MHz) | 1 | One characterized one-bit OR. |
| `register1` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 1 | 1 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register16` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 16 | 16 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register2` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 2 | 2 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register3` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 3 | 3 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register32` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 32 | 32 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register5` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 5 | 5 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `register64` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/register.csv` (400MHz) | 64 | 64 independent stored bits, each priced with the characterized one-bit REGISTER; no clock gating or inactive-word activity discount. |
| `xor_gate` | `src/archx/interface/csv_cmos_asplos_2026_ae/include/csv/xor_bitwise.csv` (400MHz) | 1 | One characterized one-bit XOR. |

`COMPARATOR` is a one-bit equality-like characterization, not a numeric 32-bit compare. Numeric comparisons therefore use the specified adder/sign/glue vectors. Floating-point EXP_NORM/VLP blocks do not replace unrelated integer circuits. Unindexed width-specific adder reports lack a frequency declaration, so the exposed 32-bit CSV row supplies the explicit width-scaled basis.

Memory prices come from the bundled standard CACTI7 executable at **45nm ITRS LOP, 0.7V, 360K**, using the exact original nine geometries. They are analytical memory models, not measured Nangate SRAM macros. FN-CACTI does not support a 45nm device. [Memory evidence](nangate45_memory/memory_prices.json) retains configurations, reports, geometry checks, voltages, fmax and source hashes. Report/config paths inside memory price bases are relative to `characterization/nangate45_memory/`. Some 45nm memories do not meet 500MHz; their reported fmax is preserved, with no modification to the 7nm simulated latency.

The 1mm, 320-bit packet link uses native CACTI45 conservative global-wire capacitance and 0.5CV² at 0.7V; no repeater energy is added. Wire area/leakage remain zero by convention. DDR4 access and IO-per-byte rows are byte-identical to the pinned off-chip model; they are explicit exceptions to the 45nm on-chip basis.

Rebuild the price table after memory evidence is available:

```bash
conda run -n fig12-archx python -B zoo/archx/zoo/snn_edp/characterization/build_nangate45.py
```

The five-fixture [price-only check](nangate45_fixture_validation.json) covers 15 rows and 386 terms and preserves all 305 counted-checkpoint files. Full Stokes repricing uses the same saved checkpoints and records another before/after byte comparison.
