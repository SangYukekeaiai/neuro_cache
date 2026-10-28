# cachesim: taxonomy mapping

Companion to `2026-10-27-cachesim-hierarchy-plan.md`. Maps the owner's
cache-technique taxonomy to what `src/cachesim/native/` implements today.

Mapping from the owner's cache-technique taxonomy to what cachesim
implements today. "Partial" means the mechanism exists in a narrower or
different form than the named technique. A blank domain means nothing in
the simulator corresponds. Paths are under `src/cachesim/native/`.

### 1. Replacement and insertion
| Taxonomy item | In cachesim | Where |
|---|---|---|
| RRIP / SRRIP / DRRIP | SRRIP only: static insertion at max-1, hit promotion to 0, no set dueling, no DRRIP | `RripPolicy`, `stamp_policy.h:218`, `src/stamp_policy.cpp:263-306`; key `rrip_bits` |
| Hawkeye / Belady-based | Belady OPT itself (true oracle from an access log), not the Hawkeye learned predictor | `BeladyPolicy`, `stamp_policy.h:132`; `NextUseOracle`, `next_use.h:39`; `--oracle` in `app_support.h:386-437` |
| Frequency-aware (LFU hybrids, ARC, LIRS) | Plain LFU, count reset on fill; no ARC / LIRS | `LfuPolicy`, `stamp_policy.h:177` |
| Reuse-distance prediction | Partial: exact next-use from the oracle, used for Belady; no predictor | `next_use.h:73`; `NextUseOracle::optimal_hit_rate` |
| (not in the list) LRU, FIFO | Stamp-based LRU and FIFO | `StampPolicy`, `LruPolicy`, `FifoPolicy`, `stamp_policy.h:36-106` |
| SHiP, Mockingjay, set dueling, PDP, EVA, cache bypassing | none | `PolicyKind::RANDOM` exists as an enum value but is refused by `make_policy` |

Insertion is not a separate axis today: every policy's `on_fill` is the
insertion rule (RRIP inserts at max-1, LFU at count 0, LRU/FIFO at the
current stamp).

### 2. Indexing and organization
| Taxonomy item | In cachesim | Where |
|---|---|---|
| Set-index hashing / XOR-based indexing | Partial: the set function is plain `line % num_sets` (no hash), but the `split_cin` and `khkw_split` layouts choose which coordinate digits land in the low (set-index) bits, which is the address-side equivalent of choosing an index function | `src/layout_common.h:154-162`; `split_cin.h`, `khkw_split.h`; keys `layout`, `cin_lo_blocks` |
| Pipelined / multi-banked caches (listed under 8, organisational here) | L2 banked by `set % banks`; `bank_high_bits` variant exists in code but is unreachable from config | `CacheLevel::bank_of`, `src/cache_level.cpp:99-105`; key `l2_banks` |
| Way prediction, column-associative, victim caches, Zcache, elastic associativity, VIPT, sector / sub-blocking, trace caches, filter caches | none | plain set-associative array, `set_associative.h` |

### 3. Partitioning and sharing
| Taxonomy item | In cachesim | Where |
|---|---|---|
| (structure only) private L1 per core, one shared L2, no partitioning, no NUCA, no QoS | | `engine.cpp:37-52` |
| UCP, way/set partitioning, Vantage, CAT, TADIP/PIPP, spill-receive, cooperative caching, NUCA, page coloring | none | |

### 4. Inclusion policies
| Taxonomy item | In cachesim | Where |
|---|---|---|
| Inclusive / exclusive / non-inclusive (NINE) | Inclusive and non-inclusive; exclusive is refused explicitly | `Inclusion`, `engine.h:59`; `src/config.cpp:241-252` |
| Back-invalidation costs | Modelled and counted: an L2 eviction under inclusive mode invalidates every L1 copy in core order | `Engine::back_invalidate`, `src/engine.cpp:733`; stat `back_invalidations`, `engine.h:179` |
| TLA inclusion, dirty blocks in exclusive hierarchies | none | |

### 5. Compression and capacity
| Taxonomy item | In cachesim | Where |
|---|---|---|
| FPC / BΔI / C-PACK, CAMP, deduplication, Doppelgänger, cache decay, drowsy caches | none | |

### 6. Prefetching interaction
| Taxonomy item | In cachesim | Where |
|---|---|---|
| Prefetch filtering | Partial: a prefetch to a resident line or to a line already in flight is dropped at triage, and NextBurst's per-core cursor never re-prefetches a burst | `TriageOutcome::DroppedArrayHit / DroppedEntry`, `cache_level.h:64-67`; `NextBurstPrefetcher::pf_cursor_` |
| Prefetcher throttling | Partial, static: L1 in-flight cap `l1_mshrs - l1_demand_reserve`; L2 prefetches may not take the last `l2_demand_reserve` MSHRs | `Engine::issue_prefetch`, `src/engine_core.cpp:340-375`; `MshrFile::has_slot`, `src/mshr.cpp:98-115`; keys `l1_demand_reserve`, `l2_demand_reserve` |
| Feedback-directed prefetching | Partial: the FDP metrics (timely / late / wasted / pollution evictions) are measured per level, but nothing adapts on them | `EngineStats::pf_timely, pf_late, pf_wasted, pf_pollution_evictions`, `engine.h:206-218`; L2 twins at `:254-256`; accounting in `src/engine.cpp:624-675` |
| Prefetch-aware replacement / insertion | Partial: a prefetch that finds its line resident does not call `on_hit`, so it never refreshes recency; otherwise policies cannot tell a prefetch fill from a demand fill | `src/cache_level.cpp:145-153`; `ReplacementPolicy::on_fill` takes only a `SlotId` |
| Dead-block-driven prefetching | none | |
| (not in the list) the prefetchers themselves | L1 next-burst along the trace, L2 neighbour along a layout axis | `prefetcher.h`; Phase 3 of this plan makes them one pluggable axis |

### 7. Write handling
| Taxonomy item | In cachesim | Where |
|---|---|---|
| all items | none: the simulated traffic is weight reads only; there is no dirty state, no writeback, no write-allocate choice | no `dirty` / `writeback` symbol anywhere in `include/` or `src/` |

### 8. Miss handling and latency
| Taxonomy item | In cachesim | Where |
|---|---|---|
| Non-blocking caches, MSHRs | Yes, per level: capacity, targets per entry, demand reserve, slot-wait and line-wait queues | `MshrFile`, `mshr.h:346`; keys `l1_mshrs`, `l1_tgts_per_mshr`, `l2_mshrs`, `l2_tgts_per_mshr` |
| Hit-under-miss, miss-under-miss | Yes: hits proceed while misses are outstanding; a second miss to an outstanding line merges as a target (`Merged`) or waits for a target slot (`BlockedTargets`); a miss with no free MSHR waits (`BlockedPool`) | `CacheLevel::triage`, `src/cache_level.cpp:164-218`; stall causes `L1Slot/L1Line/L2Slot/L2Line`, `mshr.h:89` |
| Pipelined / multi-banked caches | L2 banks, each with its own port of initiation interval `ii` and latency; L1 has one port per core | `Port`, `port.h:57`; `CacheLevel::ports_`; keys `l2_banks`, `l1_ii`, `l2_ii`, `l1_latency`, `l2_latency` |
| Cache banking conflicts | Yes: a request waits for the bank's next accept slot and the wait is charged as a stall | `Port::reserve`, `src/port.cpp:54`; stall causes `L1Port`, `L2Port`, `mshr.h:89` |
| (DRAM side) | one DRAM port with `dram_ii`, latency `l2_miss_latency`; `Channel` stall cause | `Engine::dram_`, `src/engine.cpp:38` |
| Critical-word-first / early restart, line buffers / stream buffers, TLB / page-walk caches | none: fills are whole lines, no address translation | |

### 9. Coherence-adjacent
| Taxonomy item | In cachesim | Where |
|---|---|---|
| all items | none: read-only weights, so no coherence protocol, directory, or snoop filter; the only cross-core interaction is inclusive back-invalidation (domain 4) | |

### 10. Specialized / research
| Taxonomy item | In cachesim | Where |
|---|---|---|
| Cache-conscious data layout / software-managed caches | Both halves: (a) the layout axis is a cache-conscious data layout chosen per run, which is the paper's main lever; (b) the `--oracle-only` "scratchpad" arm is the software-managed baseline whose makespan equals the trace's own tick count | `layout.h`, `block_pack.h`, `split_cin.h`, `khkw_split.h`; `oracle_row`, `src/stats.cpp:452-457`, `cachesim_run.cpp:255` |
| V-Way (decoupled tag/data), Amoeba, Footprint, Unison / Alloy, tagless DRAM caches, Bingo / ISB / IMP, MLP-aware LLC, criticality-aware, persistent-memory flushing | none | |

### Taxonomy-aligned folder names (alternative to section 2 of the hierarchy plan)
If the directories should read like the taxonomy, rename as follows and
keep everything else in the plan unchanged:

| Section 2 name | Taxonomy-aligned name | Holds |
|---|---|---|
| `replacement/` | `replacement/` | domain 1 |
| `index/` | `indexing/` | domain 2: set function, cache array, set-associative array, banking helper |
| `layout/` | `layout/` | domain 10 (cache-conscious data layout); kept separate because it is the paper's axis |
| `prefetch/` | `prefetch/` | domain 6 policies; the throttling and filtering mechanics stay in `miss_handling/` and `engine/` |
| `core/` (request, mshr, port) | `miss_handling/` | domain 8: MSHRs, ports, banking conflicts, request and stall-cause types |
| `core/` (event, cache_level, engine) | `engine/` | the event loop and the level/engine objects; `Inclusion` and `back_invalidate` (domain 4) live here unless an `inclusion/` folder is wanted, which would hold only the enum and one function today |
| `trace/`, `instrument/` | unchanged | not cache techniques; input and output |

Decision 9 (tracked in the hierarchy plan, section 6): section 2 names (`index/`, `core/`) or the taxonomy-aligned
names (`indexing/`, `miss_handling/`, `engine/`)?
