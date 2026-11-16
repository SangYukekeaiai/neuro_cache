# Bounded INNOVUS211 adder16 probe

The single P&R-only probe used `/home/net/cadence/installs/INNOVUS211/bin/innovus`, banner **v21.19-s058_1**, with the banked Genus netlist. Command: `export CLK_PERIOD_NS=2; bash auto_pnr.sh ASAP7 snn_adder16` in `~/auto_syn_pnr`. PATH selection is launcher-only; the workspace diff remains the single authorized clock-gating-off line. Default libraries are unchanged.

The resident watchdog stopped owned PGID **1432059** at the **9.5 GiB RSS bound**, after **230.06 seconds**. Peak sampled group RSS was **9.5258 GiB**; sampling overshoot was 27,048 KiB. Peak sampled swap was 16,104 KiB. TERM was followed by group cleanup; the group was confirmed absent. The 20-minute bound did not fire.

The last phase is `init_design`, importing `ASAP7.tch` for preRoute extraction. There is no post-route report pair and no CSV price. This tool version also reaches the memory bound at technology import; the result does not establish the eventual memory requirement or prove a specific parser defect. No additional P&R job is armed.

[RSS curve](rss_curve.pdf), [raw samples](rss.tsv), [full log](project.log), [provenance and archive SHA](provenance.json). [Nine banked Genus results](../midbit_genus/README.md). [Synthesis failure context](../../SYNTHESIS_FAILURES.md).
