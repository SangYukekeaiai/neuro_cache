# QRC initialization diagnosis

The current evidence identifies an administrative memory limit and the failing initialization phase, but does not establish why Innovus was killed. No additional synthesis/P&R run has started.

## Limits in the detached launcher

The same launcher was invoked with `T91_ENV_ONLY=1` under `nohup setsid -f`, skipping lint and both EDA tools. Its captured PID/PGID/SID was 1338369. This measures the current launch environment; the exited attempt3 shell cannot be inspected retrospectively.

- Soft and hard data, resident-memory, and address-space limits are unlimited. There is no 10-GiB shell ulimit to raise.
- The host uses cgroup v1. `/sys/fs/cgroup/user.slice/user-1227910567.slice/memory.max` is absent; the applicable file is `/sys/fs/cgroup/memory/user.slice/user-1227910567.slice/memory.limit_in_bytes`, root-owned and not writable by the run user, with value **10,737,418,240 bytes (10 GiB)**.
- `/etc/systemd/system/user-.slice.d/50-memory.conf` sets `MemoryMax=10G`, `MemoryHigh=11G`, `MemorySwapMax=11G`, and legacy `MemoryLimit=11G`. The effective kernel memory limit is 10 GiB. Historical cgroup peak is 10,737,426,432 bytes; limit-hit count is 2,289,976; OOM-kill counter is zero.
- Kernel journal access is denied to this account. Exit137 and saturation do not identify the killing agent. This requires host-admin evidence; no limit was altered or bypassed.

## Failure phase and assets

Innovus21.38 loaded five TT libraries and only **two standard-cell instances**. Its log reports about 1,065.5 MB current memory before extraction setup. The final lines are:

```
Initializing multi-corner RC extraction with 2 active RC Corners ...
Importing multi-corner technology file(s) for preRoute extraction...
../../../../../Enablements/ASAP7/qrc/ASAP7.tch
Generating auto layer map file.
```

This is inside `init_design`, before floorplanning, routing, or postRoute extraction. The measured process maximum RSS was 10,071,772 KiB. No continuous RSS series was retained for that attempt, so these endpoints are not a reconstructed growth curve.

Both Cmax/Cmin use the same existing file, resolved from the actual Cadence working directory to `/home/net/ya867177/snn_edp_syn/auto_syn_pnr/Enablements/ASAP7/qrc/ASAP7.tch`. The 83,765,417-byte file hashes to `3fab20686dcdb4f9ea1053504f50e4fbbf47de46668545c7c350a7359e4d9aae`, exactly matching the pinned Delta original. Both 1x LEFs, `mmmc_setup.tcl`, and `run_invs.tcl` also match byte-for-byte. The QRC path strings in `lib_setup.tcl` are unchanged; its only differences are the authorized FF-to-TT library filenames. No missing-path or altered-tech-file evidence was found. The cap-table message describes native advanced-node behavior, not a missing cap-table error.

## Historical cross-check and controls

The inspected `csv_cmos/syn_pnr_rpt/TNN7` tree has 20 completed report pairs, including `tnn_and_gate` (postRouteOpt report area1.633 um2, wirelength14.148 um). All20 timing headers identify **Innovus19.10-p002_1 on scooby.ece.local.cmu.edu**. The flow README assigns TNN7 to branch `prabhu`; pinned main accepts ASAP7/NanGate45. These reports prove a tiny gate can complete in that historical environment, not that this TT/QRC/tool combination fits 10 GiB. No historical RSS/runtime logs were found in the inspected original-flow, Verilog, or report trees. The tiny-gate timing report also says no constrained timing paths.

The native driver exposes no QRC effort/thread environment hook. Genus has hard-coded8 CPUs; Innovus's localCpu8 line is commented. `setNanoRouteMode -grouteExpWithTimingDriven false` at run_invs.tcl:237 is a later routing workaround, not a control for the failing initialization. No effort/thread settings were changed.

## Proposed next action

Ask the host administrator to identify the kill from kernel/service logs and provide an adequate allocation for a **single** diagnostic pilot, or provide a known-good ASAP7/Innovus21 QRC-import baseline. A controlled allocation above the measured10-GiB ceiling (for example16–24GiB if host capacity permits) is a diagnostic proposal, not a demonstrated sufficient bound or a proven fix. Keep the project flow and QRC asset unchanged. Fan-out remains held; no automatic rerun is armed.

The launcher now captures limits immediately before the project invocation and starts a session-scoped RSS/VSZ/process sampler every10s on a future authorized run. It also records cgroup memory/swap/limit-hit counters and host available memory. The instrumentation changes only the outer launcher, not auto_syn_pnr. Its environment-only mode does not start the sampler or any EDA tool.

## Evidence

[Raw evidence and launcher diff](/u/yyu9/peon-snapshots/energy-performance-estimation/T91-20261114-asap7-500mhz/qrc_diagnosis/): `detached_environment.log`, `remote_qrc.txt`, `remote_assets.txt`, `kill_log_visibility.txt`, `launcher_instrumentation.diff`, `monitor_memory.sh`. The initial diagnostic attempted setup paths before accounting for the driver's flattening; those read errors concern the probe paths, not the actual flow. The generated setup files live in `scripts/cadence`, as auto_syn_pnr.sh specifies.
