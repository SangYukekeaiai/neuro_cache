# Cache-design energy plan: two configurations (Fig 12, 7 nm)

Status: for user review (plan only, nothing dispatched). Parent plan:
`docs/plans/2026-11-11-fig12-edp-plan.md`. Sources: cachesim counter schema
`src/lays/cachesim/native/src/instrument/stats.cpp`; L1 pilot results
(PAUSE-2026-11-11.md); tech-mapping rule 2026-11-12 (compute ASAP7, sram
cacti_fn tech 7, DRAM cacti7 ddr4); user config message 2026-11-12.

## 1. The two configurations

Common hardware (both configs, from the user):

```
L1: 16 KB, 8-way, LRU, khkw_split indexing (shared L1/L2 layout)
L2: 512 KB, 16-way            # "L1 way number: 16" read as the L2 ways
```

Differences (user's three bullets, interpreted; CONFIRM in review):

```
Config A (pilot-style):  L1 prefetch next_access (distance 4)
                         L2 prefetch distance_aware (threshold 9)
                         L2 replacement pf_aware (= pf_lru)
Config B (next-line):    L1 prefetch next-line
                         L2 prefetch next-line
                         L2 replacement: pf_aware too, or plain LRU?  <- open
```

RESOLVED 2026-11-12 (user: follow recommendation):
Config A = {L1 next_access d4, L2 distance_aware t9, L2 pf_lru};
Config B = {L1 next-line, L2 next-line, L2 plain LRU}.

`next_line` proposes physical lines `line+1` through `line+d` within the layer extent, independent of layout; B uses d1 at both levels (+64 bytes with its 64-byte lines). Omitted distance defaults to 1 at both levels; explicit zero or negative distance is rejected. Explicit axis/up/down and L2 min_touches fields under `next_line` produce `W_NEXT_LINE_IGNORED_OPTION` warnings and do not affect candidates.
Capacity parity: the paper claim is reworded to "iso-core-count, cache
sizes from the pilot study" (supervisor can still override); sizes stay
16 KB + 512 KB vs spad 32 KB + 2 MB.

## 2. Key structural fact: one energy table serves both configs

The two configs share identical cache geometry (sizes, ways, line size).
Prefetch and replacement policies change WHICH accesses happen (counts,
from the sim), not the per-access energy of the arrays. So:

- energy_table.json gets ONE set of cache.* rows (plus per-policy
  prefetcher-logic rows, below).
- The two energy models differ only through the cachesim counters of two
  separate simulation arms, one per config. Every case therefore runs
  cachesim twice. The duplicate-arm drop planned in T70 frees exactly the
  wave budget the second config costs.
- Node compute, spine buffers, psum/vmem, LIF: identical to the spad
  design (same counts, same energies, from the per-arch docs). The cache
  design swaps ONLY the weight-memory side: L1/L2 weight spad + NoC weight
  movement OUT; L1/L2 cache + DRAM path IN. Delay T comes from cachesim
  total_cycles instead of nocsim total_cycles.

## 3. Components and per-event energies (7 nm rules applied)

| # | Component | Geometry | Energy source | Count (cachesim counters) |
|---|-----------|----------|---------------|---------------------------|
| 1 | L1 cache (data+tag) | 16 KB, 8-way | cacti_fn class `cache`, tech 7 (associativity-aware whole-access energy) | l1_accesses reads (demand probes) + L1 fills writes (fills = misses + pf fills, derived) |
| 2 | L2 cache (data+tag) | 512 KB, 16-way | cacti_fn class `cache`, tech 7 | l2_accesses reads + L2 fills writes (~= dram_accesses) |
| 3 | Tag-only probes | L1/L2 tag arrays | separate cacti_fn sram row sized as the tag array (cacti_fn `cache` does not split tag/data energy) | dropped/filtered prefetch probes (prefetch counters) |
| 4 | MSHR | from the performance model (`src/lays/cachesim/native/include/cachesim/config.h:71-74`): L1 16 entries x 20 targets/entry; L2 20 entries x 12 targets/entry. Each entry = line-address CAM tag + target-list registers | ASAP7 auto_syn_pnr small-CAM blocks `mshr_cam_l1` (16-entry) and `mshr_cam_l2` (20-entry); target lists as register files | 1 CAM search per miss + 1 per fill return, per level; target-register write per coalesced request |
| 5 | Prefetcher logic, per policy | next-line: address adder (trivial); next_access d4 / distance_aware t9: stateful metadata table + compare logic | ASAP7 logic + cacti_fn sram row for the metadata table (size from the cachesim implementation, to be read off during implementation) | prefetch counters (issued / filled / dropped) |
| 6 | Replacement metadata (LRU / pf_lru state update) | per-set state bits | folded into rows 1-2 (array access includes state RMW), footnote | - |
| 7 | DRAM | cacti7 ddr4, 22 nm | activate/read/precharge per access + pJ/bit x dram_bytes + refresh and IO power x T | dram_accesses, dram_bytes |
| 8 | khkw_split indexing | index bit permutation | wiring, zero energy, footnote | - |
| 9 | Leakage | both cache arrays + MSHR + prefetcher | cacti_fn leakage mW x T; compute-side leakage identical to spad design | P_leak x total_cycles / f |

## 4. Energy formula (per case, per config)

```
E_cache_side = l1_acc*e_l1_rd + l1_fill*e_l1_wr
             + l2_acc*e_l2_rd + l2_fill*e_l2_wr
             + pf_probe*e_tag + miss*e_mshr + pf_evt*e_pf_logic
             + dram_acc*e_dram_access + dram_bytes*e_dram_io
E_total      = E_cache_side + E_compute(arch)   # arch docs, unchanged
             + P_leak(cache design) * T_cfg / f
EDP          = E_total * T_cfg,  T_cfg = cachesim total_cycles (per config)
```

## 5. Workflow

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/cache.architecture.yaml` at technology 7:
   cacti_fn `cache` rows for L1 (16K/8w) and L2 (512K/16w), tag-array sram
   rows, prefetcher metadata sram row(s), ddr4 rows; `mshr_cam` +
   prefetcher-logic blocks to the ASAP7 worklist.
2. Harvest -> energy_table.json keys cache.* (one table, both configs) +
   area/leakage for the area and power panels.
3. Counts: straight from the per-case cachesim result CSVs of the two
   config arms (the CSVs are kept, so cache energy is computable post-hoc;
   T70's in-flight columns just make it free at wave time).
4. Config JSONs: write the two production configs for `sim_shard.py
   --config` (this is the gate the campaign has waited on; the exact
   policy names must match the simulator's registry: pf_aware = pf_lru,
   next_access is L1-only, distance_aware is L2-only, as established in
   the pilot).
5. The archx description in `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/` defines one cache arm per
   configuration. Native performance models count events, and native metric
   aggregation prices the saved checkpoints for spad, cacheA and cacheB.
6. Validation: (a) counter identities per case (hits + misses = accesses;
   fills <= accesses; dram_bytes = dram_accesses x line size); (b) pilot
   cross-check: config-A EDP ordering on loas VGG16 must reproduce the L1
   pilot's direction; (c) energy sanity vs the spad design (same compute
   terms, different memory terms).

## 6. Caveats

0. **L2 read/write asymmetry is physical, state it in the methodology**:
   l2_accesses counts DEMAND accesses only (engine.cpp:487 guards on
   r.demand), and demand misses coalesce heavily in the MSHRs (~68x on
   the heaviest vgg16 layer: 1152 L2 data reads vs 77824 L1 misses),
   while prefetch traffic reads only the TAG array (l2_tags row) and
   WRITES the data array on fill. So the L2 data array can show orders
   of magnitude more writes than reads (1152 reads vs 1.52M writes on
   that layer). Correct by construction; looks wrong in a table; one
   methodology sentence prevents the question.

1. **Capacity parity is broken, deliberately or not**: the spad design has
   L1 32 KB + L2 2 MB; this cache design has 16 KB + 512 KB. The paper's
   operating-point sentence ("equal on-chip capacity and core count")
   cannot stand as written: either the claim changes (iso-policy, chosen
   cache sizes from the pilot) or the sizes do. Supervisor-level call;
   the energy model itself is indifferent.
2. **l1_accesses counts demand probes**: a stalled request that retries is
   recounted, so L1 read energy is an upper bound under stall-heavy
   configs. Footnote; fills are derived, not counted.
3. **cacti_fn `cache` gives whole-access energy only**: no hit/miss or
   tag/data split. Hits and misses cost the same on the probe side; misses
   add MSHR + L2 + fill terms. Tag-only probes are approximated by a
   separate tag-sram row (row 3).
4. **Prefetcher metadata RESOLVED 2026-11-12** (read from the source, T76):
   next_access state is tiny fixed vectors, 192 B total across 16 cores
   (registers, negligible). distance_aware in the SIMULATOR is an
   unbounded map (line-id -> {tile32, count32}): no finite capacity
   exists in code. Physical model decision: an 8192-entry x 64-bit
   direct-indexed SRAM (64 KB, cacti_fn tech 7), entry = tag + tile32 +
   count32, sized to match the L2's 8192 lines (512 KB / 64 B): metadata
   for more lines than the L2 holds has no hardware justification.
   FOOTNOTE the idealization: the simulator tracks unboundedly, the
   charged hardware could not, so prefetch quality is idealized while
   energy stays physical; counts are taken from the sim unchanged. Do
   NOT size to the campaign weight address space (up to ~384 KB of
   metadata: dwarfs the L2 it serves).
5. **Per-config counts, shared energies**: never fork the energy table per
   config; policy differences must flow only through counters, or the two
   bars silently diverge in hardware instead of policy.
6. **Two cachesim arms double the wave cost**; the T70 duplicate-arm
   removal pays for it. The waves still need the heavy-tail window
   machinery before shards 130-136 simulate.
7. **DRAM refresh/IO power x T** makes slow configs pay standing DRAM
   energy: intended, but it couples the energy panel to total_cycles, so
   delay bugs contaminate energy. Validation 6(a) guards it.
8. 7 nm caveat unchanged: finfet_7nm_0p7.xml is a synthetic first-order
   device file (footnote or switch to the validated 0.45 V point).
9. MSHR geometry RESOLVED from the simulator config (config.h defaults,
   used unchanged by both production configs): L1 16x20, L2 20x12. If a
   config JSON ever overrides l1_mshrs/l2_mshrs, the CAM rows must be
   re-sized to match.
