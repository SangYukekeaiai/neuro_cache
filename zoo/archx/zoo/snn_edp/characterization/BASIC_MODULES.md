# Basic modules for ASAP7 500 MHz characterization

**Nine middle-design jobs; all other widths use archx csv_cmos linear interpolation through the origin.** Source: UnaryLab/verilog_modules at `3e6135c9cb8c735439e2968cd3446dbd10fe55b3`. The 24 flat sources remain staged references; only the nine tops below are scheduled. The 13 whole tops are unsynthesized references. Every active flat source exposes `i_clk`/`i_rst_n`, unused on combinational logic.

The project is `~/auto_syn_pnr` at `d60655d3be4f2efee81402ff8becf2b4b6f34580`, with `CLK_PERIOD_NS=2` and the sole authorized clock-gating-off line. Libraries are the shipped mixed set: AO/INVBUF/OA/SEQ nominal 0.77 V/0 C, SIMPLE 0.70 V/25 C. No uniform TT corner is claimed. CPU, I/O, utilization and activity remain project defaults, without VCD. [Genus results](asap7_500mhz/midbit_genus/README.md) are banked; P&R on vlsi is held; both 21.x probes stopped at technology import. [INNOVUS211 bound evidence](asap7_500mhz/adder16_innovus211/README.md). [Synthesis failure context](SYNTHESIS_FAILURES.md).

## Nine-job catalog and interpolation

| Measured top | Serves | Linear price factor |
|---|---|---|
| `snn_adder16` | adder widths 1,2,3,4,5,13,16,32 | W/16 |
| `snn_register16` | register widths 1,2,3,5,16,32,64 | W/16 |
| `snn_fifo32x8` | FIFO 16x8,32x8,64x2 | (W/32)*(D/8) |
| `snn_and_gate` | scalar AND | 1 |
| `snn_and_gate_5` | five parallel ANDs | 1 |
| `snn_or_gate` | scalar OR | 1 |
| `snn_xor_gate` | scalar XOR | 1 |
| `snn_not_gate` | scalar inverter | 1 |
| `snn_mux2` | one-bit 2:1 mux | 1 |

The same dimension factor scales dynamic power, leakage and area. csv_cmos scales each queried dimension successively; FIFO uses explicit width and depth axes. Width/depth extrapolation is an approximation, especially for FIFO control overhead. Per-event energy uses the characterization frequency; the pipeline time base remains 500 MHz. No Genus-only result is harvested as a post-route price.

## Pinned primitive sources

| Primitive | Repo source | Contract |
|---|---|---|
| adder | `/u/yyu9/projects/verilog_modules/adder/adder.v` | BITWIDTH=W; two W-bit inputs, W+1-bit sum |
| register | `/u/yyu9/projects/verilog_modules/register/register.v` | WL=W; synchronous active-low reset, write enable |
| fifo | `/u/yyu9/projects/verilog_modules/fifo/fifo.v` | BITWIDTH, DEPTH, PTRWIDTH; registered output, async reset, synchronous clear |
| and_gate | `/u/yyu9/projects/verilog_modules/and_gate/and_gate.v` | scalar two-input AND |
| and_gate_5 | `/u/yyu9/projects/verilog_modules/and_gate_5/and_gate_5.v` | five parallel two-input ANDs |

## and_gate: `and_gate/and_gate.v` (1 variant)

`loas.and_gate.and` directly; ptb spike_mask_overlap (32×); AND terms in priority/subset/match glue (bsf16/bsf32, leading_spike_detector, TCAM match, MSHR search, router).

## and_gate_5: `and_gate_5/and_gate_5.v` (1 variant)

router_5p_64b port-mask/arbiter glue only.

## Glue gates (authored in the repo idiom; 4 variants)

The four one-line modules at `rtl_tops/common/` are original glue-source provenance. Their flat-derived basic files are the active measured sources, like the repo-derived basics. All priced glue is expressed as counts of these measured gates plus `and_gate`; there is **no conversion-factor approximation**.

```verilog
module or_gate  (input wire iDataA, iDataB, output wire oData); assign oData = iDataA | iDataB; endmodule
module xor_gate (input wire iDataA, iDataB, output wire oData); assign oData = iDataA ^ iDataB; endmodule
module not_gate (input wire iData,          output wire oData); assign oData = ~iData;          endmodule
module mux2     (input wire iDataA, iDataB, iSel, output wire oData); assign oData = iSel ? iDataB : iDataA; endmodule
```

Derived structural definitions (all composition prices use measured gates):
- **equality W bits** = W × xor_gate + (W-1) × or_gate + 1 × not_gate
- **mux2 W bits wide** = W × mux2; mux-tree N:1 = (N-1) × mux2 per bit
- **decoder N outputs**, A=ceil(log2(N)): N×(A−1) × and_gate + A shared not_gate; write-enable gating adds N × and_gate separately (including N=320/384 with A=9)
- **priority chain N bits** = N × and_gate + N × not_gate + (N-1) × or_gate
- **OR/AND reduction W bits** = (W-1) × or_gate / and_gate

## Not used from the repo

`less_equal` (temporal inhibit-pass operator, not a numeric comparator; compare is adder-carry on `a + ~b` plus glue), `multiplier`, `fp_adder`, `fp_multiplier`, `adder_bfloat16`, `pe*`/`systolic*`, `butterfly*`, `column_tnn7*`, `edge2pulse`/`pulse2edge`, `fft_pe`.

## Excluded operations (zero-priced by decision, prefetch control)

`cache.next_access_logic.step`, `cache.distance_logic.step`, `cache.next_access_state.rmw`, `cache.distance_metadata.read`, `cache.distance_metadata.write`, `cache.l1_tags.read`, `cache.next_line_l1.add`, `cache.next_line_l2.add`, `cache.l2_tags.read`.

Per-operation pricing modes and retained structural vectors live in the breakdown table of [MODULE_MAPPING.md](MODULE_MAPPING.md).
