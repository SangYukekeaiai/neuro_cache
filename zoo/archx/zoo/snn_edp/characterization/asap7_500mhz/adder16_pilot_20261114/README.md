# snn_adder16 memory-pressure evidence

The single pilot is stopped. No post-route price is accepted and no CSV row was harvested. T91 is held for the boss's decision on a larger memory allocation or the known-good scooby environment; no retry or fan-out is armed.

On net1580, the command was `export CLK_PERIOD_NS=2; bash auto_syn_pnr.sh ASAP7 snn_adder16` in `~/auto_syn_pnr`, commit `d60655d3be4f2efee81402ff8becf2b4b6f34580`. The only tracked flow change is the authorized `lp_insert_clock_gating true -> false`; [workspace.diff](workspace.diff) records it. Default CPU, I/O, floorplan and library settings remain. AO/INVBUF/OA/SEQ declare 0.77 V/0 C; SIMPLE declares 0.70 V/25 C. This is a mixed default library set, not a uniform corner; [provenance.json](provenance.json) pins all five files.

Genus completed with 107 combinational cells and preserved its netlist, databases and reports. I/O paths are unconstrained, so this is not evidence of 500 MHz timing closure. Innovus stalled during `init_design`, importing ASAP7.tch for two RC corners, before floorplanning or routing. No CRITICAL_PATH/DETAILS post-route pair exists.

## Stop and resource measurements

All times below are host EST on 2026-11-14. Launch was 22:20:01. Only owned PGID 1379812 received TERM at 22:50:11. Cleanup remained blocked while swap fell further; KILL followed at 22:52:27. The group was absent at 22:52:57. The other user's/session's pre-existing Genus group was untouched. Kernel OOM-kill count remained zero.

| Measurement | Observed value |
|---|---:|
| Innovus peak RSS + VmSwap | 23.785 GiB |
| User-cgroup peak RAM + swap (includes another session) | 25.336 GiB |
| User-cgroup RAM cap | 10 GiB |
| Additional memory-limit hits | 3,489,737 |
| Host MemAvailable / free swap at 22:47:40 | 4.02 / 4.65 GiB |
| Host MemAvailable / free swap after recovery | 13.21 / 16.91 GiB |

These interrupted, still-growing peaks are lower bounds. Request **at least 32 GiB**, possibly more, with sufficient host capacity. Pathological technology-file import remains a hypothesis; a larger cap alone is not proven to resolve it.

[Memory curve](memory_curve.pdf), [RSS series](rss.tsv), [RSS/swap series](rss_swap.tsv), [stop log tail](innovus_tail_at_stop.txt), and [recovery snapshot](host_memory_recovered.txt) preserve the measurements. RSS/limit sampling starts at launch; explicit per-process swap sampling starts at 9.9 minutes. Earlier swap samples and between-signal recovery are not reconstructed.

Full Genus/Innovus artifacts: `/u/yyu9/peon-snapshots/energy-performance-estimation/T91-20261114-asap7-500mhz/adder16_pilot/flow_artifacts.tar.gz`, SHA256 `e651f369724879804bcf19b537e3cb8d534f1278332973d14a3bf0b57ff38656`.

See also [synthesis failure context](../../SYNTHESIS_FAILURES.md). Tables, hardware specification and worklist remain byte-identical to the frozen T98 inputs.
