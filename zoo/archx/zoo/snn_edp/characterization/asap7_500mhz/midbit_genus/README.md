# Nine middle-design Genus results

Synthesis reports and handoff netlists are banked. They are not post-route prices. Default I/O paths are unconstrained; a positive internal slack is not full-interface timing closure. The sole tracked workspace edit disables clock gating. Adder16 uses its existing synthesis result.

| Module | Cells | Cell area (Genus report units) | Worst constrained slack (ps) |
|---|---:|---:|---:|
| snn_adder16 | 107 | 6.692 | No constrained paths |
| snn_register16 | 64 | 7.698 | 1909.7 |
| snn_fifo32x8 | 849 | 158.82 | 1300.3 |
| snn_and_gate | 2 | 0.102 | No constrained paths |
| snn_and_gate_5 | 10 | 0.51 | No constrained paths |
| snn_or_gate | 2 | 0.102 | No constrained paths |
| snn_xor_gate | 3 | 0.175 | No constrained paths |
| snn_not_gate | 1 | 0.044 | No constrained paths |
| snn_mux2 | 2 | 0.175 | No constrained paths |

The preparation command for P&R is `export CLK_PERIOD_NS=2; bash auto_pnr.sh ASAP7 <module>` in `~/auto_syn_pnr`; it reuses the banked netlist. P&R on vlsi is held pending a different venue; the [bounded INNOVUS211 probe](../adder16_innovus211/README.md) also stopped at technology import.

[Machine-readable results and archive SHA](results.json). [Failure context](../../SYNTHESIS_FAILURES.md).
