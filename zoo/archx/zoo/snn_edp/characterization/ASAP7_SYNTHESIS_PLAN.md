# ASAP7 basic characterization and composition plan

## Scope and catalog

Current T91 scope is **24 basics, zero whole-top synthesis jobs**. All48 logic-operation vectors are the pricing basis, including one-term direct operations. The18 active worklist families remain included. Coverage is **48 RTL +41 physical-model +9 excluded =98 visible rows**. The frozen T95 archive retains the previous catalog; current working metadata follows this scope.

[BASIC_MODULES.md](BASIC_MODULES.md) is the single catalog:8 adder widths1/2/3/4/5/13/16/32;7 register widths1/2/3/5/16/32/64; FIFO16x8,32x8,64x2; and_gate,and_gate_5,or_gate,xor_gate,not_gate,mux2. register4/6/8/9/13/33 and adder64 have no active vector consumers. Repo primitives remain pinned to3e6135c9cb8c735439e2968cd3446dbd10fe55b3. Four authored one-assignment glue leaves are present. The13 authored whole tops, helpers and staged tests are [unsynthesized references only](rtl_tops/README.md); no further functional work or tests are scheduled.

## Native project execution and target

Use only the project's own `auto_syn_pnr.sh ASAP7 <flat-basic-top>` from the parent-owned project copy. Set `CLK_PERIOD_NS=2` (2000ps). Target TT RVT0.70V25C, official `PVT_0P7V_25C`, is pinned by verified [ASAP7_TT_LIBRARIES.json](ASAP7_TT_LIBRARIES.json). Installed library bytes must match; no library-header edits. Prior FF probe facts remain historical. Parent owns detached licensed runs on net1580 and the flat-derived basic sources; this documentation task changes no flow or RTL.

Each `src/<top>/` job contains exactly one fixed-parameter `.v` file, one module and no hierarchy; its `rtl_list.tcl` names only that file. [basic_variants.json](rtl_tops/basic_variants.json) is the source of record for the24 flat-derived files, original repo/glue hashes and derivations. Rename only existing clock/reset ports to `i_clk`/`i_rst_n`; add no clock to combinational gates. Original sources remain unchanged.

The source configuration diff is limited to TT library paths in `lib_setup.tcl` and authorized `lp_insert_clock_gating=false` in `run_genus_hybrid.tcl`. CPU/thread edits are reverted, with no CPU environment knob; `run_invs.tcl` remains native. Preserve the original70% square floorplan, native I/O/activity defaults and project driver. No replacement TCL, SDC rewrite or timing adapters.

Native attempt1 failed Genus POPT-78/no ICG; authorized clock-gating-off attempt2 exited137 at QRC; strict flat-source pilot3 is awaiting QRC import under the account RAM cap. No successful or accepted result is claimed.

## Native I/O and activity defaults

The existing ASAP7 SDC creates a core clock when the named port exists and a virtual clock otherwise. Its explicit input/output delays, output load and uncertainty commands are commented out. Retain those defaults; record the resulting constraints and unconstrained-path reports. A500MHz environment setting alone does not prove constrained input-to-output timing or whole-module timing closure.

No operation-specific VCD is supplied. The native Genus/Innovus no-VCD branches log a50% switch-activity fallback; retain actual tool/report activity provenance rather than claiming verified per-event annotation. N×register array estimates do not model inactive-word gating. Additive prices omit composed interconnect, fanout and optimization effects. Label all composed prices as estimates from individually measured basics, not physically routed whole-module results.

## Harvest and accounting

`STRUCTURAL_AUDIT.json.quantified_composition.operations` holds integer primitive_counts, named terms, dynamic_event_cycles and separate standing_inventory. All48 entries use `pricing_mode=composition`, `structural_vector_usage=pricing`; there is no whole-top report branch. The Markdown table is rendered from these unchanged vectors. No gate-equivalent conversion constants or unpriced miscellaneous-glue buckets are used.

At500MHz, leaf energy per cycle(nJ)=dynamic power(mW)/500. Dynamic event energy=`dynamic_event_cycles * sum(N * leaf_energy_per_cycle)`; leakage/area=`sum(N * leaf_leakage/area)`. All event cycles are1 except router hop:320-bit packet=5×64-bit flits. That factor5 never multiplies router area/leakage. Standing inventory is applied once per shared physical module. TCAM vectors describe one256×16 bank; the two banks/node are inventory, shared by search/write. Router depth is fixed2, with5 FIFO64x2 and register5 masks; native FIFO output64 already holds head data.

Harvest with archx's own `csv_cmos_extract`; do not introduce a custom report parser. Preserve original-source/flat-derived-file, native-flow configuration, library and report hashes. Only accepted native reports supply Stage B prices; count checkpoints remain immutable.

## Excluded by decision

The nine prefetch-control exclusions are `cache.next_access_logic.step`, `cache.distance_logic.step`, `cache.next_access_state.rmw`, `cache.distance_metadata.read`, `cache.distance_metadata.write`, `cache.l1_tags.read`, `cache.next_line_l1.add`, `cache.next_line_l2.add`, and `cache.l2_tags.read`. All Stage A formulas/counts remain; Stage B pricing excludes these rows. Archived controller and tag-probe contracts remain in MODULE_MAPPING and the audit. L1/L2 data-array reads/fill writes remain charged.

The41 physical-model rows retain SRAM/cache/GB, DRAM/IO and wire models. Query-frequency metadata is500MHz; DDR4 bus frequency remains1600MHz. Policy and price-table changes reprice Stage B from immutable saved counts.
