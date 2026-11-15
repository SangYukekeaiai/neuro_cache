# Manual module and event map

Paths below are relative to this document, under `zoo/archx/zoo/snn_edp/docs/`.
Open the linked hardware key for its role, dimensions and inventory. Each row
is one operation; no FIFO or inactive-memory row is hidden.

The [basic class/variant catalog](../characterization/BASIC_MODULES.md) and [quantified composition table](../characterization/MODULE_MAPPING.md#quantified-composition-by-module-and-operation) separate per-unit measured-leaf counts from standing inventory. All48 logic rows price their vectors over24 basics; authored whole tops are reference-only. Nine rows marked **excluded by decision (prefetch control)** retain Stage A counts and are excluded from Stage B pricing. Price/policy links target the current default table field, including null pending prices.

`hardware.json` names operations as `architecture.module.operation` and gives
every physical module an explicit `role`. `description.py:description` creates
one physical leaf `m__architecture__module`. An operation event is
`arm__architecture__module__operation`, where arm is `spad`, `cacheA` or `cacheB`.
The operation has exactly one module child. Read/write or push/pop events share
that module and its standing inventory. Root/category events only group work;
they are not hardware. The `reference__shared__{router,link}__hop` events use the
same shared modules for the chain-only reference quantity.

Graph definition: [description](../designs/snn/description.py#L7). Count callbacks: [branch](../performance.py#L10) sets operation counts; [operation](../performance.py#L25) selects exactly one module child. Formulas/arm selection: [operations](../model.py#L74); counter derivation: [measurements](../model.py#L96); evaluation: [case_counts](../model.py#L124).

## Common count symbols

All counts cover the complete layer/sample. `L = HO*WO*COUT*T` is the LIF sweep;
`O = d_out*L` is expected output spikes. `d_out` comes from the next layer's
capture, with an explicitly labeled own-density proxy on the final layer.
`cout_n` is the realized COUT lane/slab width. `S_win`/`S_sum` count set spikes
weighted by valid convolution-window membership; `S_or` weights the OR across
time. Saved-counter units and required columns are in the
[interface contract](../README.md#saved-counter-interface).

## spinalflow

`A=S_win*COUT`; `R=A/cout_n`, with cout_n capped at four by the divisor rule. Partial-sum/membrane SRAM rows are inactive: no graph event or standing inventory.

Input-count producer: [count_sample](../../../../fig12_edp/counts/spinalflow_counts.py#L111). Energy-side derivation: [measurements](../model.py#L96).

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [adder32](../hardware.json#L1203) | `spinalflow__adder32__add` | spad / cacheA / cacheB: `A` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2158) |
| [cmp32](../hardware.json#L1215) | `spinalflow__cmp32__compare` | spad / cacheA / cacheB: `A` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2182) |
| [input_spike_buffer](../hardware.json#L1228) | `spinalflow__input_spike_buffer__read` | spad / cacheA / cacheB: `R` | [count_expression](../hardware.json#L1229) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2208) |
| [input_spike_buffer](../hardware.json#L1243) | `spinalflow__input_spike_buffer__write` | spad / cacheA / cacheB: `R` | [count_expression](../hardware.json#L1244) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2234) |
| [l1_weight_spad](../hardware.json#L1258) | `spinalflow__l1_weight_spad__read` | spad: `R` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2259) |
| [l1_weight_spad](../hardware.json#L1272) | `spinalflow__l1_weight_spad__write` | spad: `l1_delivery_bytes*8/32.0` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2283) |
| [min_tree4](../hardware.json#L1286) | `spinalflow__min_tree4__compare` | spad / cacheA / cacheB: `R` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2307) |
| [output_spike_queue](../hardware.json#L1300) | `spinalflow__output_spike_queue__read` | spad / cacheA / cacheB: `0` | [count_expression](../hardware.json#L1301) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2334) |
| [output_spike_queue](../hardware.json#L1315) | `spinalflow__output_spike_queue__write` | spad / cacheA / cacheB: `O` | [count_expression](../hardware.json#L1316) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2360) |
| [psum_l1](../hardware.json#L1330) | `spinalflow__psum_l1__read` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2385) |
| [psum_l1](../hardware.json#L1344) | `spinalflow__psum_l1__write` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2409) |
| [psum_l2](../hardware.json#L1358) | `spinalflow__psum_l2__read` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2433) |
| [psum_l2](../hardware.json#L1372) | `spinalflow__psum_l2__write` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2457) |
| [reg32](../hardware.json#L1386) | `spinalflow__reg32__rmw` | spad / cacheA / cacheB: `A+L` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2481) |
| [vmem_l1](../hardware.json#L1398) | `spinalflow__vmem_l1__read` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2505) |
| [vmem_l1](../hardware.json#L1412) | `spinalflow__vmem_l1__write` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2529) |
| [vmem_l2](../hardware.json#L1426) | `spinalflow__vmem_l2__read` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2553) |
| [vmem_l2](../hardware.json#L1440) | `spinalflow__vmem_l2__write` (not emitted) | inactive; no event | [operations](../model.py#L74) | [energy field](../energy_table.json#L2577) |

Visible operation rows: 18/18.

## ptb

`A=S_sum*COUT`; `B=S_or*COUT/cout_n`. `spike_mask_overlap.check` is the T-bit disjointness check, not an integer threshold comparator.

Input-count producer: [count_sample](../../../../fig12_edp/counts/ptb_counts.py#L8). Energy-side derivation: [measurements](../model.py#L96).

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [adder16](../hardware.json#L907) | `ptb__adder16__add` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L908) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1624) |
| [l1_weight_spad](../hardware.json#L920) | `ptb__l1_weight_spad__read` | spad: `B` | [count_expression](../hardware.json#L921) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1650) |
| [l1_weight_spad](../hardware.json#L935) | `ptb__l1_weight_spad__write` | spad: `l1_delivery_bytes*8/32.0` | [operations](../model.py#L74) | [energy field](../energy_table.json#L1676) |
| [lif_unit](../hardware.json#L950) | `ptb__lif_unit__step` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L951) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1701) |
| [output_spike_queue](../hardware.json#L964) | `ptb__output_spike_queue__read` | spad / cacheA / cacheB: `0` | [count_expression](../hardware.json#L965) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1729) |
| [output_spike_queue](../hardware.json#L979) | `ptb__output_spike_queue__write` | spad / cacheA / cacheB: `O` | [count_expression](../hardware.json#L980) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1755) |
| [reg16](../hardware.json#L994) | `ptb__reg16__read` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L995) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1780) |
| [reg16](../hardware.json#L1007) | `ptb__reg16__rmw` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L1008) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1805) |
| [spike_fifo](../hardware.json#L1020) | `ptb__spike_fifo__pop` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1021) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1829) |
| [spike_fifo](../hardware.json#L1034) | `ptb__spike_fifo__push` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1035) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1855) |
| [spike_mask_overlap](../hardware.json#L1048) | `ptb__spike_mask_overlap__check` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1049) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1882) |
| [spike_vector_buffer](../hardware.json#L1062) | `ptb__spike_vector_buffer__read` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1063) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1909) |
| [spike_vector_buffer](../hardware.json#L1077) | `ptb__spike_vector_buffer__write` | spad / cacheA / cacheB: `0` | [count_expression](../hardware.json#L1078) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1934) |
| [weight_fifo](../hardware.json#L1092) | `ptb__weight_fifo__pop` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1093) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1958) |
| [weight_fifo](../hardware.json#L1106) | `ptb__weight_fifo__push` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L1107) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1984) |

Visible operation rows: 15/15.

## loas

`A=S_sum*COUT`; `B=S_or*COUT/cout_n`; `W_o=O/T` packed words. `spike_prefix_scan32` counts spike-mask prefix ranks, not partial-sum SRAM accesses.

Input-count producer: [count_sample](../../../../fig12_edp/counts/loas_counts.py#L7). Energy-side derivation: [measurements](../model.py#L96).

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [adder16](../hardware.json#L444) | `loas__adder16__add` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L445) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L777) |
| [and_gate](../hardware.json#L457) | `loas__and_gate__and` | spad / cacheA / cacheB: `32*B` | [count_expression](../hardware.json#L458) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L802) |
| [bsf32](../hardware.json#L470) | `loas__bsf32__scan` | spad / cacheA / cacheB: `A/cout_n` | [count_expression](../hardware.json#L471) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L828) |
| [l1_weight_spad](../hardware.json#L483) | `loas__l1_weight_spad__read` | spad: `B` | [count_expression](../hardware.json#L484) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L855) |
| [l1_weight_spad](../hardware.json#L498) | `loas__l1_weight_spad__write` | spad: `l1_delivery_bytes*8/32.0` | [operations](../model.py#L74) | [energy field](../energy_table.json#L881) |
| [lif_unit](../hardware.json#L513) | `loas__lif_unit__step` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L514) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L906) |
| [output_fifo](../hardware.json#L527) | `loas__output_fifo__push` | spad / cacheA / cacheB: `W_o` | [count_expression](../hardware.json#L528) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L933) |
| [reg16](../hardware.json#L541) | `loas__reg16__read` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L542) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L960) |
| [reg16](../hardware.json#L554) | `loas__reg16__rmw` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L555) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L985) |
| [spike_fifo](../hardware.json#L567) | `loas__spike_fifo__pop` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L568) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1009) |
| [spike_fifo](../hardware.json#L581) | `loas__spike_fifo__push` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L582) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1035) |
| [spike_prefix_scan32](../hardware.json#L595) | `loas__spike_prefix_scan32__scan` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L596) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1062) |
| [weight_fifo](../hardware.json#L608) | `loas__weight_fifo__pop` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L609) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1087) |
| [weight_fifo](../hardware.json#L622) | `loas__weight_fifo__push` | spad / cacheA / cacheB: `B` | [count_expression](../hardware.json#L623) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1113) |

Visible operation rows: 14/14.

## gustavsnn

`A=S_win*COUT`; `R_g=A/cout_n` with cout_n capped at two; `W_o=O` bits. The FIFO count divides bits by32. `lif_core` excludes state; `potential_regfile` supplies its RMW.

Input-count producer: [count_sample](../../../../fig12_edp/counts/gustavsnn_counts.py#L8). Energy-side derivation: [measurements](../model.py#L96).

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [adder16](../hardware.json#L304) | `gustavsnn__adder16__add` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L305) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L515) |
| [l1_weight_spad](../hardware.json#L317) | `gustavsnn__l1_weight_spad__read` | spad: `R_g` | [count_expression](../hardware.json#L318) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L541) |
| [l1_weight_spad](../hardware.json#L332) | `gustavsnn__l1_weight_spad__write` | spad: `l1_delivery_bytes*8/16.0` | [operations](../model.py#L74) | [energy field](../energy_table.json#L567) |
| [leading_spike_detector](../hardware.json#L347) | `gustavsnn__leading_spike_detector__scan` | spad / cacheA / cacheB: `R_g` | [count_expression](../hardware.json#L348) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L591) |
| [lif_core](../hardware.json#L360) | `gustavsnn__lif_core__step` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L361) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L617) |
| [merger_tree2](../hardware.json#L375) | `gustavsnn__merger_tree2__merge` | spad / cacheA / cacheB: `R_g` | [count_expression](../hardware.json#L376) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L645) |
| [output_fifo](../hardware.json#L389) | `gustavsnn__output_fifo__push` | spad / cacheA / cacheB: `W_o/32` | [count_expression](../hardware.json#L390) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L672) |
| [potential_regfile](../hardware.json#L403) | `gustavsnn__potential_regfile__rmw` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L404) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L699) |
| [reg16](../hardware.json#L417) | `gustavsnn__reg16__rmw` | spad / cacheA / cacheB: `A` | [count_expression](../hardware.json#L418) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L726) |
| [spike_fifo](../hardware.json#L430) | `gustavsnn__spike_fifo__pop` | spad / cacheA / cacheB: `R_g` | [count_expression](../hardware.json#L431) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L750) |

Visible operation rows: 10/10.

## prosperity

`R_p` is the exact `(capture,layer,sample)` record_count.csv join; `A_p=R_p*cout_n`; `N_rows=HO*WO*T*CIN`; `seed_reads_bound=psum_writes=N_rows*COUT`. `SORT=sum_tile(2*m*log2(m)*CIN)`, where m is the actual T×HO×WO tile extent; counts/prosperity_counts.py computes this field. `tcam` is the flop-based subset matcher; `ps_table` holds prefix/pattern descriptors. `lif_core` and `lif_state` are separate.

Input-count producer: [count_sample](../../../../fig12_edp/counts/prosperity_counts.py#L16). Energy-side derivation: [measurements](../model.py#L96).

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [adder16](../hardware.json#L636) | `prosperity__adder16__add` | spad / cacheA / cacheB: `A_p` | [count_expression](../hardware.json#L637) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1140) |
| [bitonic_cmp](../hardware.json#L649) | `prosperity__bitonic_cmp__compare` | spad / cacheA / cacheB: `SORT` | [count_expression](../hardware.json#L650) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1165) |
| [bsf16](../hardware.json#L662) | `prosperity__bsf16__scan` | spad / cacheA / cacheB: `R_p` | [count_expression](../hardware.json#L663) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1190) |
| [l1_weight_spad](../hardware.json#L675) | `prosperity__l1_weight_spad__read` | spad: `R_p` | [count_expression](../hardware.json#L676) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1217) |
| [l1_weight_spad](../hardware.json#L690) | `prosperity__l1_weight_spad__write` | spad: `l1_delivery_bytes*8/32.0` | [operations](../model.py#L74) | [energy field](../energy_table.json#L1243) |
| [lif_core](../hardware.json#L705) | `prosperity__lif_core__step` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L706) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1268) |
| [lif_state](../hardware.json#L720) | `prosperity__lif_state__rmw` | spad / cacheA / cacheB: `L` | [count_expression](../hardware.json#L721) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1296) |
| [popcount16](../hardware.json#L733) | `prosperity__popcount16__count` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L734) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1320) |
| [pruner](../hardware.json#L746) | `prosperity__pruner__prune` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L747) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1346) |
| [ps_table](../hardware.json#L760) | `prosperity__ps_table__read` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L761) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1374) |
| [ps_table](../hardware.json#L775) | `prosperity__ps_table__write` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L776) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1400) |
| [psum_buffer](../hardware.json#L790) | `prosperity__psum_buffer__read` | spad / cacheA / cacheB: `seed_reads_bound` | [count_expression](../hardware.json#L791) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1426) |
| [psum_buffer](../hardware.json#L805) | `prosperity__psum_buffer__write` | spad / cacheA / cacheB: `psum_writes` | [count_expression](../hardware.json#L806) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1452) |
| [reg16](../hardware.json#L820) | `prosperity__reg16__rmw` | spad / cacheA / cacheB: `A_p` | [count_expression](../hardware.json#L821) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1477) |
| [spike_row_buffer](../hardware.json#L833) | `prosperity__spike_row_buffer__read` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L834) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1503) |
| [spike_row_buffer](../hardware.json#L848) | `prosperity__spike_row_buffer__write` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L849) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1529) |
| [tcam](../hardware.json#L863) | `prosperity__tcam__search` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L864) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1554) |
| [tcam](../hardware.json#L885) | `prosperity__tcam__write` | spad / cacheA / cacheB: `N_rows` | [count_expression](../hardware.json#L886) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L1589) |

Visible operation rows: 18/18.

## cache

Counts come from the selected arm's cache CSV. `pf_issued` includes dropped candidates; subtracting the five named drop counters gives accepted L1 prefetches. L1 fills include demand misses; L2 fills equal dram_accesses. Extra tag probes have no additional standing inventory. Config A uses next_access/distance-aware; Config B uses NextLine physical-line additions `line+1` through `line+d`; production d1 emits only `line+1` at both L1 and L2. The next-line rows remain excluded at zero price.

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [distance_logic](../hardware.json#L2) | `cache__distance_logic__step` — excluded by decision (prefetch control) | cacheA: `l2_pf_issued` | [count_expression](../hardware.json#L6) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L17) |
| [distance_metadata](../hardware.json#L19) | `cache__distance_metadata__read` — excluded by decision (prefetch control) | cacheA: `l1_accesses` | [count_expression](../hardware.json#L23) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L53) |
| [distance_metadata](../hardware.json#L44) | `cache__distance_metadata__write` — excluded by decision (prefetch control) | cacheA: `l1_accesses` | [count_expression](../hardware.json#L48) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L91) |
| [l1](../hardware.json#L69) | `cache__l1__read` | cacheA / cacheB: `l1_accesses` | [count_expression](../hardware.json#L70) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L112) |
| [l1](../hardware.json#L86) | `cache__l1__write` | cacheA / cacheB: `l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | [count_expression](../hardware.json#L87) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L140) |
| [l1_tags](../hardware.json#L103) | `cache__l1_tags__read` — excluded by decision (prefetch control) | cacheA / cacheB: `2*pf_issued+pf_budget_exhausted` | [count_expression](../hardware.json#L104) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L176) |
| [l2](../hardware.json#L119) | `cache__l2__read` | cacheA / cacheB: `l2_accesses` | [count_expression](../hardware.json#L120) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L197) |
| [l2](../hardware.json#L136) | `cache__l2__write` | cacheA / cacheB: `dram_accesses` | [count_expression](../hardware.json#L137) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L225) |
| [l2_tags](../hardware.json#L153) | `cache__l2_tags__read` — excluded by decision (prefetch control) | cacheA / cacheB: `l2_pf_issued+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | [count_expression](../hardware.json#L154) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L261) |
| [mshr_cam_l1](../hardware.json#L169) | `cache__mshr_cam_l1__search` | cacheA / cacheB: `l1_accesses-l1_hits+l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve` | [count_expression](../hardware.json#L170) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L280) |
| [mshr_cam_l2](../hardware.json#L184) | `cache__mshr_cam_l2__search` | cacheA / cacheB: `l2_accesses-l2_hits+dram_accesses` | [count_expression](../hardware.json#L185) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L307) |
| [mshr_targets_l1](../hardware.json#L199) | `cache__mshr_targets_l1__write` | cacheA / cacheB: `l1_accesses-l1_hits` | [count_expression](../hardware.json#L200) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L335) |
| [mshr_targets_l2](../hardware.json#L214) | `cache__mshr_targets_l2__write` | cacheA / cacheB: `l2_accesses-l2_hits` | [count_expression](../hardware.json#L215) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L363) |
| [next_access_logic](../hardware.json#L229) | `cache__next_access_logic__step` — excluded by decision (prefetch control) | cacheA: `pf_issued` | [count_expression](../hardware.json#L233) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L409) |
| [next_access_state](../hardware.json#L253) | `cache__next_access_state__rmw` — excluded by decision (prefetch control) | cacheA: `3*pf_issued` | [count_expression](../hardware.json#L257) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L439) |
| [next_line_l1](../hardware.json#L270) | `cache__next_line_l1__add` — excluded by decision (prefetch control) | cacheB: `pf_issued` | [count_expression](../hardware.json#L274) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L468) |
| [next_line_l2](../hardware.json#L287) | `cache__next_line_l2__add` — excluded by decision (prefetch control) | cacheB: `l2_pf_issued` | [count_expression](../hardware.json#L291) → [case_counts](../model.py#L124) | [excluded policy](../energy_table.json#L497) |

Visible operation rows: 17/17.

## shared

Scratchpad DDR4 counts come from noc/result.json; cache DDR4 counts come from cache_a/b.csv. A read is one64-byte burst; IO counts bytes. Scratchpad router/link counts include weight+chain hops; cache arms count chain hops only. Global-buffer SRAM is scratchpad-only.

| Module / definition | Operation event suffix | Count by arm | Formula source | Price / policy |
|---|---|---|---|---|
| [ddr4](../hardware.json#L1120) | `shared__ddr4__read` | spad / cacheA / cacheB: `dram_accesses` | [count_expression](../hardware.json#L1121) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2015) |
| [ddr4_io](../hardware.json#L1134) | `shared__ddr4_io__byte` | spad / cacheA / cacheB: `dram_bytes` | [count_expression](../hardware.json#L1135) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2038) |
| [gb](../hardware.json#L1141) | `shared__gb__read` | spad: `gb_reads` | [count_expression](../hardware.json#L1145) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2056) |
| [gb](../hardware.json#L1160) | `shared__gb__write` | spad: `gb_writes` | [count_expression](../hardware.json#L1164) → [case_counts](../model.py#L124) | [energy field](../energy_table.json#L2083) |
| [link](../hardware.json#L1179) | `shared__link__hop` | spad: `weight_packet_hops+chain_packet_hops`; cacheA: `chain_packet_hops`; cacheB: `chain_packet_hops` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2113) |
| [router](../hardware.json#L1191) | `shared__router__hop` | spad: `weight_packet_hops+chain_packet_hops`; cacheA: `chain_packet_hops`; cacheB: `chain_packet_hops` | [operations](../model.py#L74) | [energy field](../energy_table.json#L2137) |

Visible operation rows: 6/6.

## Count and price are separate invocations

From `zoo/archx`, after local backend setup in [VENDOR.md](../../../VENDOR.md):

```bash
export PYTHONPATH="$PWD/src:$PWD/zoo"
export ARCHX_DISABLE_PERFORMANCE_CACHE=1
python -B -m snn_edp.run count --case /absolute/counters --out /absolute/counts
python -B -m snn_edp.run price --counts /absolute/counts --table /absolute/table.json --out /absolute/energy
```

Count reads counter files plus hardware/performance definitions, requires no
price table, and saves graphs with operation counts and zero metrics. Price
reads those saved graphs and the supplied table; the counter directory need
not exist. A synthesis/table update reruns only the second command, with a new
energy output directory. The count files and their fingerprint do not change.

