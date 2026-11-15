# Basic modules for ASAP7 500 MHz characterization

Source: [UnaryLab/verilog_modules](https://github.com/UnaryLab/verilog_modules) pinned `3e6135c9cb8c735439e2968cd3446dbd10fe55b3` at `/u/yyu9/projects/verilog_modules`. Target: ASAP7 RVT TT 0.70 V/25 °C (PVT_0P7V_25C), 500 MHz (2000 ps), Genus + Innovus on `vlsi.eecs.ucf.edu`. **24 basic characterization variants; zero whole-top jobs.** All48 logic-operation vectors are priced from measured basics, including one-term direct operations. Four glue leaves are present; the13 authored whole tops and their staged tests are unsynthesized [references only](rtl_tops/README.md).

## Exact repo paths and ports

All five paths below identify original-source provenance at the pinned commit. Active sources are the24 flat-derived, fixed-parameter single-module files in `rtl_tops/basic/`, recorded with per-file derivation and hashes in [basic_variants.json](rtl_tops/basic_variants.json). Each remote `src/<top>/` job has one `.v`, one module, no hierarchy and a one-file `rtl_list.tcl`. Existing clock/reset ports are renamed `i_clk`/`i_rst_n`; combinational gates gain no clock ports. Original repo/glue sources are unchanged; standing inventory is separate.

| Basic class | Exact repo RTL path | Parameters and actual ports |
|---|---|---|
| adderW | `/u/yyu9/projects/verilog_modules/adder/adder.v` | `BITWIDTH=W`; `iDataA[W-1:0],iDataB[W-1:0] -> oData[W:0]`; no cin. |
| registerW | `/u/yyu9/projects/verilog_modules/register/register.v` | `WL=W`; `aclk,rst,d[W-1:0],wen -> q[W-1:0]`; synchronous active-low zero reset. |
| fifoWxD | `/u/yyu9/projects/verilog_modules/fifo/fifo.v` | `BITWIDTH=W,DEPTH=D,PTRWIDTH=$clog2(D)`; `iClk,iRstN,iEnW,iEnR,iClr,iData[W-1:0] -> oData[W-1:0]`; async active-low reset, sync clear, registered output. Full/empty are internal, not ports; full rejects simultaneous write, empty rejects simultaneous read. |
| and_gate | `/u/yyu9/projects/verilog_modules/and_gate/and_gate.v` | Scalar `iDataA,iDataB -> oData`; one two-input AND. |
| and_gate_5 | `/u/yyu9/projects/verilog_modules/and_gate_5/and_gate_5.v` | `iDataA[4:0],iDataB[4:0] -> oData[4:0]`; five parallel two-input ANDs, not a five-input reduction. |

## adder: `adder/adder.v` (param BITWIDTH; two W-bit operands, W+1-bit result, no cin)

Standalone characterization widths: **1, 2, 3, 4, 5, 13, 16, 32** (8 variants).

| Width | Composition consumers |
|---|---|
| 1, 2, 3, 4 | Popcount16 and prefix32 networks; router also uses2/3 |
| 5 | Prefix32 final level |
| 13 | Bitonic comparator and pruner key tournament |
| 16 | Direct arithmetic rows |
| 32 | SpinalFlow arithmetic/comparison, min tree, merger and LIF |

adder64 is **out**: its only consumers, next_line/next_access/distance, are excluded prefetch rows. It returns if the breakdown table surfaces another 64-bit user.

## register: `register/register.v` (param WL; sync active-low reset, wen)

Standalone characterization widths: **1, 2, 3, 5, 16, 32, 64** (7 variants).
Consumers: direct register words, potential RF, TCAM, MSHR tag/valid/target arrays, router state and stateful LIF (register32 +register1). register4/6/8/9/13/33 have no vector consumers and are not scheduled. Native FIFO internals are included in the FIFO primitive, not additional register jobs.

## fifo: `fifo/fifo.v` (params BITWIDTH, DEPTH; power-of-two depth, registered output)

| Config | Consumers |
|---|---|
| 16×8 | ptb/loas weight_fifo, ptb spike_fifo |
| 32×8 | loas spike/output fifo, gustavsnn spike/output fifo |
| 64×2 | router_5p_64b inputs ×5 (**depth 2 decided**; 64×4 dropped) |

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

## Final characterization catalog: 24 basics

The exact union of all48 operation vectors is8 adders +7 registers +3 FIFOs +6 gates. Whole-top references add no jobs.

| Group | Exact variant names | Count |
|---|---|---|
| Adders | `adder1`, `adder2`, `adder3`, `adder4`, `adder5`, `adder13`, `adder16`, `adder32` | 8 |
| Registers | `register1`, `register2`, `register3`, `register5`, `register16`, `register32`, `register64` | 7 |
| FIFOs | `fifo16x8`, `fifo32x8`, `fifo64x2` | 3 |
| Gates | `and_gate`, `and_gate_5`, `or_gate`, `xor_gate`, `not_gate`, `mux2` | 6 |

Use only the project's own `auto_syn_pnr.sh`, `CLK_PERIOD_NS=2`, native70% square floorplan and native I/O/activity defaults without VCD. The source config diff is limited to verified TT library paths and authorized clock-gating-off; CPU edits are reverted, with no CPU environment override or replacement TCL. Harvest through archx's own `csv_cmos_extract`, not a custom parser. Native attempt1 failed Genus POPT-78/no ICG; authorized clock-gating-off attempt2 exited137 at QRC; strict flat-source pilot3 is awaiting QRC import under the account RAM cap. No successful or accepted result is claimed.

## Not used from the repo

`less_equal` (temporal inhibit-pass operator, not a numeric comparator; compare is adder-carry on `a + ~b` plus glue), `multiplier`, `fp_adder`, `fp_multiplier`, `adder_bfloat16`, `pe*`/`systolic*`, `butterfly*`, `column_tnn7*`, `edge2pulse`/`pulse2edge`, `fft_pe`.

## Excluded operations (zero-priced by decision, prefetch control)

`cache.next_access_logic.step`, `cache.distance_logic.step`, `cache.next_access_state.rmw`, `cache.distance_metadata.read`, `cache.distance_metadata.write`, `cache.l1_tags.read`, `cache.next_line_l1.add`, `cache.next_line_l2.add`, `cache.l2_tags.read`.

Per-operation pricing modes and retained structural vectors live in the breakdown table of [MODULE_MAPPING.md](MODULE_MAPPING.md).
