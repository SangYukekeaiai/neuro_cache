# RTL source roles

`basic/` contains the24 active flat-derived, fixed-parameter sources: one `.v`, one module and no hierarchy per `src/<top>/` job; `rtl_list.tcl` lists only that file. [basic_variants.json](basic_variants.json) records each derived file and its original pinned repo or `common/` glue source, hashes and derivation. Existing clock/reset ports are renamed `i_clk`/`i_rst_n`; combinational gates have no added clock ports. Original sources remain unchanged. Execute only through the project's own `auto_syn_pnr.sh` and harvest with archx `csv_cmos_extract`.

`helpers.v`, `whole_tops.v`, `test_whole_tops.sv` and `test_whole_tops.py` are **unsynthesized reference-only artifacts**. The13 whole tops are not characterization jobs; their reports are not used for pricing. Functional authoring and tests are stopped. The staged bench has not been compiled or simulated by this task. Preserve these files; do not include them in active basic RTL lists or launch the test runner as part of T91.

All48 logic prices use the integer primitive-count vectors in `STRUCTURAL_AUDIT.json`, with24 measured basics. No whole-module routing, timing or operation-specific activity is claimed by those sums.
