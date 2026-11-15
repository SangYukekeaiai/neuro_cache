# Native-project and_gate pilot

Driver: `bash auto_syn_pnr.sh ASAP7 snn_and_gate`, workspace `/home/net/ya867177/snn_edp_syn/auto_syn_pnr`, host net1580. All24 basic jobs contain one flat `.v` file with one fixed module and one-file `rtl_list.tcl`; Verilator lint passes for all24. Sequential ports are `i_clk/i_rst_n`; no clock/reset environment overrides or VCDs are used. Combinational primitives retain their original data-only ports.

The current workspace differs in exactly two existing files: five TT library filenames in `lib_setup.tcl`, and clock-gating insertion disabled in `run_genus_hybrid.tcl`. `CLK_PERIOD_NS=2` uses the README hook. CPU settings,70% square floorplan,I/O constraints and activity use project defaults. Exact diffs/hashes and source derivations are linked from [pilot status](and_gate_pilot_status.json).

Attempt1 failed Genus POPT-78 with clock gating enabled. Attempt2 synthesized successfully but exited137 during QRC import after14m47s, maximum RSS9,907,716KiB; no P&R reports were produced. The cause of the kill is not established. Native Genus timing showed an unconstrained input-to-output path;28ps logic delay is not a2ns timing pass.

Attempt3 used the strict flat-source layout and project CPU defaults (launcher PGID1331144, Innovus PID1332303). It exited137 during native QRC import; the remote exit_code file and project.log confirm the exit and killed Innovus PID. Elapsed time was8m23.62s and maximum RSS10,071,772KiB. At2026-11-14T17:27:08-05:00, the PID was absent and neither required CRITICAL_PATH nor DETAILS report existed. Accepted variants remain0; no prices were harvested. The cause of exit137 is unproven.

Required output: `syn_pnr_rpt/ASAP7/snn_and_gate/{snn_and_gate_CRITICAL_PATH.rpt,snn_and_gate_DETAILS.rpt}`. Accepted reports will be extracted by the byte-identical archx `csv_cmos_extract.py` staged here, not a custom report parser. No energy-table update has occurred.

Resource blocker: the parent account cgroup is capped at10GiB RAM (10,737,418,240bytes), observed usage10,737,328,128bytes with1,870,233limit hits. Session limits are unlimited, but the parent cap applies. No cgroup limit is changed or bypassed; adequate allocation is required before fan-out. The prior exit137 cause remains unproven (the observed cgroup OOM-kill counter is0).

Post-exit resource check: parent limit10,737,418,240bytes, usage902,422,528bytes, historical maximum10,737,426,432bytes, failcnt2,289,976; under_oom=0 and oom_kill=0. These observations confirm the allocation limit and prior saturation, not the cause of termination. This status update launched no jobs, sent no signals, and changed no flow or RTL.

[A91 archive](/u/yyu9/peon-snapshots/energy-performance-estimation/T91-20261114-asap7-500mhz/A91-attempt3-exit137-20261114T2226Z) contains the three prior status documents, project.log, exit_code, time.txt, the remote observation, and SHA256 provenance in archive_manifest.json.
