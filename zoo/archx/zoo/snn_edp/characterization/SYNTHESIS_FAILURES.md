# ASAP7 synthesis failures: evidence and status

Flow: `auto_syn_pnr` (UnaryLab) @ `d60655d`, identical on Delta (pinned) and the vlsi host (`~/auto_syn_pnr`, clean clone; 143/143 files SHA-equal). Jobs: 24 flat single-module sources under `src/snn_*/`, `i_clk`/`i_rst_n` on every module, `CLK_PERIOD_NS=2` (500 MHz), `bash auto_syn_pnr.sh ASAP7 <module>`.

## Previous failure: Innovus killed at technology import (TT overlay round)

With the two-line overlay then in force (verified TT libs + clock gating off), Genus PASSED and the pilot reached Innovus 21.38. Three attempts each died with exit 137 (SIGKILL) at the same step: pre-route RC extraction setup, importing `Enablements/ASAP7/qrc/ASAP7.tch` (84 MB) for 2 RC corners; RSS grows from ~1.0 GiB to ~10.07 GiB, then the kill.

Cause of the kill: the vlsi host enforces a root-owned cgroup cap, `MemoryMax=10G` per user slice (`/etc/systemd/system/user-.slice.d/50-memory.conf`); shell ulimits are unlimited. The import cost is fixed by the technology data, independent of design size, so a one-gate module hits it identically. Whether >10 GiB is Innovus 21's legitimate ASAP7 footprint or a degenerate parse of an enablement validated only on Innovus 19.10 is unresolved; distinguishing requires one run on an uncapped machine. The cap also forbids any parallel fan-out even if a single run fit. Evidence: `asap7_500mhz/QRC_DIAGNOSIS.md`, RSS curves in the T91 snapshot area.

## Current failure: Genus clock gating (mandatory default round)

Rerun with the exact unmodified default project (default mixed libs, `lp_insert_clock_gating true` as shipped): Genus fails at `POPT-78: Cannot find any usable integrated clock-gating cell` (project.log:742) before netlisting; the script then still launches Innovus with no netlist (flow robustness gap; the orphan was killed, no reports accepted).

Root cause is structural, not environmental:

- `Flows/template_design/scripts/cadence/run_genus_hybrid.tcl:58` hardcodes `lp_insert_clock_gating true` for every technology.
- `Enablements/NanGate45/lib/NangateOpenCellLibrary_typical.lib` contains 8 integrated clock-gating cells, so the flow works on NanGate45 (and the TNN7 branch, which produced all historical report trees on `scooby` with Innovus 19.10).
- All five `Enablements/ASAP7/lib/asap7sc7p5t_*_RVT_FF_nldm_201020.lib` contain ZERO clock-gating cells. Genus therefore fails on ASAP7 for any module, on any host, with default libs and TT libs alike. The repo contains no committed ASAP7 report, consistent with this path never having completed.
- Side finding, upstream: within the shipped 201020 FF set, AO/INVBUF/OA/SEQ declare 0.77 V/0 C while SIMPLE declares 0.70 V/25 C; the corner mix comes with the official release files.

Conclusion: "unmodified default project" and "synthesize on ASAP7" are jointly impossible.

## Options (decision pending)

1. One-line flip `lp_insert_clock_gating true -> false` (proven: Genus passed the full pilot in the TT round; no clock-gate cells are inserted into characterized primitives, which is also scientifically preferable). Recommended.
2. Add an ICG-capable SEQ liberty from a newer official ASAP7 release: keeps clock gating on but changes the library list and inserts clock gates into the measured primitives.

Independently, Innovus needs either the 10 GiB cap raised on the vlsi host (admin, one line) or a different host (`scooby`, the machine of record for all existing report trees).

## Status

24 jobs staged at the vlsi `~/auto_syn_pnr/src/`; no licensed runs until the clock-gating decision; prior workspaces archived with verified SHAs (nested workspace removed per instruction). Stokes stage-1 demo is unaffected and running on the dummy-table path.
