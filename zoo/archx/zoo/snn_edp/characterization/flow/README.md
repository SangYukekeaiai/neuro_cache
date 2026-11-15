# Licensed characterization driver

The project root is `~/auto_syn_pnr` on net1580, commit `d60655d3be4f2efee81402ff8becf2b4b6f34580`. Invoke its own entry point:

```sh
export CLK_PERIOD_NS=2
bash auto_syn_pnr.sh ASAP7 snn_adder16
```

Each supplied job has one flat module in `src/<top>/<top>.v` and a single-file `rtl_list.tcl`. All expose `i_clk` and `i_rst_n`, unused for combinational logic. Source derivations and hashes are in [the run manifest](../asap7_500mhz/manifest.json).

The single adder16 pilot uses the authorized one-line `lp_insert_clock_gating false` setting in `run_genus_hybrid.tcl`. [Its workspace diff](../asap7_500mhz/adder16_pilot_20261114/workspace.diff) is the sole tracked change among 143 project files. CPU, I/O, utilization, square floorplan and activity settings remain project defaults; no VCD is supplied.

The five shipped RVT libraries have FF filenames but mixed nominal declarations: AO/INVBUF/OA/SEQ are 0.77 V/0 C, SIMPLE is 0.70 V/25 C. No uniform corner is claimed. [Pilot provenance](../asap7_500mhz/adder16_pilot_20261114/provenance.json) records exact paths and hashes.

**No licensed runs are armed.** The adder16 pilot completed Genus but was stopped during Innovus technology import because of shared-host memory pressure. There are no accepted post-route prices. [The evidence report](../asap7_500mhz/adder16_pilot_20261114/README.md) preserves the resource curve, stop/recovery measurements and Genus artifacts. Further execution requires the boss's host/cap decision. See [synthesis failure context](../SYNTHESIS_FAILURES.md).
