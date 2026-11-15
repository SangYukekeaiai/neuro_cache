# ASAP7 tool probe

Host: `dt-login02.delta.ncsa.illinois.edu`. Timestamp: `2026-11-14T01:46:33.232687+00:00`.

- Genus, Innovus, lmutil, Yosys and OpenROAD: absent from the current PATH.
- Module availability search: no Cadence/Genus/Innovus/ASAP/EDA match. Lmod spider cannot locate genus, innovus or cadence.
- CDS_LIC_FILE, LM_LICENSE_FILE and SNPSLMD_LICENSE_FILE: unset. No license server was contacted, so this is not a license-denial result.
- Existing flow: `/u/yyu9/projects/auto_syn_pnr`, revision `d60655d3be4f2efee81402ff8becf2b4b6f34580`; reusable Genus/Innovus scripts, SDC, extraction and ASAP7 enablement are readable.
- Five ASAP7 RVT FF Liberty files, 1x technology/cell LEFs and QRC tech file are present. Library units are ps; FF nominal voltage0.7V, temperature25C; cell names include `_ASAP7_75t_R`.
- No tool invocation, license checkout, remote login or synthesis job was launched. The prior composition-only validation job had already finished before this probe.

The existing TNN7 adder timing report names historical host `scooby.ece.local.cmu.edu` and Innovus19.10-p002_1, and reports **no constrained timing paths**. This is a lead for the lab operator, not proof of current access or a timing certificate. Its path is `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/src/archx/interface/csv_cmos/syn_pnr_rpt/TNN7/tnn_adder/tnn_adder_CRITICAL_PATH.rpt`.

Execution is blocked until a licensed host/module setup is provided. Prefer the lab host already supporting this Cadence flow; Delta is viable only if its operator supplies the missing EDA installation/license setup. No runnable cluster-wide EDA environment was established by this read-only probe; private or hidden installations are not ruled out.

[TOOL_PROBE.json](TOOL_PROBE.json) retains actual commands, return codes, module outputs and hashes of every inspected flow/library asset. [ASAP7_SYNTHESIS_PLAN.md](ASAP7_SYNTHESIS_PLAN.md) specifies the RTL interfaces and execution/measurement gates.
