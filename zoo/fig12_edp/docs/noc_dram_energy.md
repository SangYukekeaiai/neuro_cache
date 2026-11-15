# Shared NoC/DRAM energy model (Fig 12, 7 nm): GB, mesh, off-chip

Status: for user review; dispatching with the core-level set 2026-11-12.
Parent plan: `docs/plans/2026-11-11-fig12-edp-plan.md`. Sources: nocsim
(`src/lays/nocsim/{sim.py,combine.py,steps.py}`, tc.csv schema), cachesim
counter schema, archx `noc_router.csv` (32 nm) + ASAP7 wire data,
cacti7 ddr4; prosperity_base.md for the psum/vmem facts.
Shared by ALL five archs; arch-specific terms live in the per-arch docs.

## 1. Scope split

- Spad (baseline) design: GB (L2 2 MB sram) + 4x4 mesh NoC + DRAM.
  Counts from tc.csv; delay from nocsim total_cycles.
- Cache design: no WEIGHT mesh traffic (the cache hierarchy replaces
  it); DRAM counts from cachesim (dram_accesses, dram_bytes); L1/L2
  cache energies live in cache_energy.md. The NON-weight NoC component,
  the k_chain/t_chain neighbor links (rows 5-6), is design-invariant
  (same schedule, same node array) and IS charged in the cache arms too,
  with the same tc.csv counts as the spad arm. So the cache design uses
  rows 5-9; only rows 1-4 (weight movement) drop out.
- Node-internal energy: per-arch docs, NOT here.

## 2. Components and per-event energies

| # | Component | Energy source | Count source |
|---|-----------|---------------|--------------|
| 1 | Mesh router, per packet-hop | PENDING characterization (standard placeholder contract: null trio + marker). The archx noc_router.csv 32 nm source is unusable: ~0.2 aJ/cycle dynamic and zero leakage, orders of magnitude below any plausible router (upstream unit error, reported to archx). Replacement: published 7 nm router energy or synthesized router, via the worklist. Applies to BOTH arms (k_chain/t_chain in cache arms; arm difference lives in the count, never in applies_to) | tc.csv: packets x hop count per transaction (unicast route length; multicast tree edges) |
| 2 | Mesh link, per hop | ASAP7 wire energy/mm x link length (mesh pitch from arch.yaml floorplan assumption, footnote) | same packet-hops as row 1 |
| 3 | GB (global buffer / L2 spad 2 MB) read per send, write per fill | cacti_fn sram tech 7 (already in table as l2 rows) | tc.csv: GB-endpoint transactions (weight sends; fills from DRAM) |
| 4 | Node L1 spad write on weight delivery | cacti_fn sram tech 7 (l1 row) | tc.csv deliveries (one burst write per record delivered) |
| 5 | k_chain links (cross-PE psum reduction, intra-step) | neighbor hop: row 1+2 energies at hop=1 | tc.csv: k_chain transactions, EVERY step (prosperity_base.md: these are real and mode-invariant) |
| 6 | t_chain links (LIF carry, intra-step) | neighbor hop at hop=1 | tc.csv: t_chain transactions, every step |
| 7 | DRAM access | cacti7 ddr4 (22 nm): activate + read/write + precharge per burst | spad: tc.csv DRAM transactions; cache: dram_accesses |
| 8 | DRAM IO | pJ/bit x bytes | spad: tc.csv DRAM bytes; cache: dram_bytes |
| 9 | DRAM standing power | refresh + IO idle power x T | both designs, T from the design's own sim |
| 10 | psum/vmem GB/DRAM boundary movement | ZERO: all 749 schedules decode psum/vmem free flags True; no boundary transactions exist (prosperity_base.md) | - |

## 3. Formula (per case, spad design; cache design uses rows 5-9: the
## k_chain/t_chain line plus DRAM, weight-movement terms dropped)

```
E_noc  = sum over tc.csv transactions of
           packets x hops x (e_router_hop + e_link_hop)
       + sends x e_gb_rd + fills x e_gb_wr + deliveries x e_l1_wr
       + (kchain + tchain) x (e_router_hop + e_link_hop)   # hop = 1
E_dram = dram_tx x e_ddr4_access + dram_bytes x 8 x e_pJ_per_bit
       + P_dram_standing x T / f
```

## 4. Workflow

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/shared.architecture.yaml`: router row (scaled
   CSV, the scaling factor and its citation recorded in the row comment),
   link row (ASAP7 wire), ddr4 rows via cacti7. GB/L1 rows already exist.
2. Harvest -> energy_table.json keys shared.* (router, link, ddr4).
3. Counts come from the T68 tc.csv parser (spad) and the cachesim CSVs
   (cache): NO new count machinery here; this doc only defines the rows
   and the events consumed by `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/designs/snn/description.py`.
4. Validation: (a) packet-hop totals vs nocsim's own
   unicast/multicast/count cycle split (order-of-magnitude agreement);
   (b) DRAM bytes identity dram_bytes = dram_accesses x burst size;
   (c) router energy/packet within published 7 nm router range.

## 5. Caveats

1. The 32->7 nm router scaling factor is first-order (capacitance/V^2
   chain); record the exact factor + citation in the table row; the
   validation (4c) bounds the damage. Supplying synthesized router data
   later only swaps one row.
2. Link length needs a floorplan assumption (mesh pitch ~ sqrt(node
   area)); footnote it; link energy is subdominant to router + SRAM.
3. Multicast counting follows combine.py's tree decode, not a star
   approximation; the T68 parser must count tree EDGES, not destinations.
4. DRAM standing power x T couples energy to delay (same caveat as the
   cache doc); slow configs pay more standing DRAM energy, intentionally.
5. tc.csv carries weight movement + k_chain/t_chain ONLY (psum/vmem
   boundary is structurally zero); never read schedule temporal_traffic
   as a count (standing guard).
6. **Standing inventory is the FIXED campaign mesh** (decision
   2026-11-12): every case, every arm, is charged the full 4x4 mesh's 16
   routers + 48 directed links of leakage, regardless of how many nodes
   its schedule touches (a smoke case ran 4x1). Same iso-hardware
   principle as LoAS's 32 idle psum lanes: utilization differences are
   dynamic, the hardware leaks either way. State in the methodology,
   since this is the number that moves most when the router placeholder
   is characterized, and it moves the cache arms proportionally more.
7. **Per-arch chain zeros are physical, state them**: SpinalFlow, LoAS
   and PTB have zero k_chain/t_chain traffic (potentials are lane/column
   local; no cross-PE reduction, no LIF carry), so their CACHE arms show
   an identically zero NoC dynamic term: weight mesh replaced by the
   cache hierarchy, no chains left. GustavSNN (t_chain) and Prosperity
   (k_chain) keep nonzero chain terms in all arms. A zero NoC column for
   three of five archs is correct, not a bug; one methodology sentence
   prevents the question.
