# 2026-09-22: the wcache L1 prefetcher against gem5's prefetcher framework

Status: survey, read from source on both sides. No code was changed to produce it.

Scope note on the earlier survey: the only gem5 survey artifact in this repo is the
plan `log/2026-08-04-gem5-l2-cache-survey-plan.md`, whose own header (lines 3-5)
says "Nothing has been executed yet (gem5 not yet cloned, no survey started)", so no
prior gem5 survey output exists and nothing below builds on one.

Provenance: gem5 was really cloned for this report (sparse clone, branch `stable`,
commit `f5c5a6e390f55dd5984977815bf9d0bd05da6945`), and every gem5 `file:line`
below was read from that checkout, not recalled. Every wcache `file:line` was read
from the working tree of branch `wcache-rebuild-phase-a` on 2026-09-22.

---

## 1. Summary

The two designs disagree at the most basic level: gem5's prefetcher *predicts*
addresses and then spends a whole layer of machinery deciding which predictions are
worth issuing, while wcache's L1 prefetcher *reads the future out of the trace* and
spends almost no machinery on the decision. wcache's `NextBurstPrefetcher` fires on
exactly one event, the demand issue of a burst (`src/wcache/native/src/engine_core.cpp:216`),
walks the trace's own burst descriptors for bursts `k+1 .. k+d` and expands every
line of them through the same address mapper the demand path uses
(`src/wcache/native/src/prefetcher.cpp:48-61`, `engine_core.cpp:341-377`), so it has
no predictor, no table, no confidence, and by construction cannot be inaccurate
about *what* the core will ask for, only about *when*. gem5 instead funnels every
policy through `Base::probeNotify` and `Queued::notify`, which add, for free to the
policy author, a filter stack (`on_miss` / `on_read` / `on_write` / `on_data` /
`on_inst` / `prefetch_on_access` / `prefetch_on_pf_hit`, `prefetch/base.cc:166-192`),
a priority prefetch queue with duplicate filtering, demand squashing and full-queue
eviction (`prefetch/queued.cc:171-236, 387-534`), a page-crossing guard
(`queued.cc:212-221`), a fixed generation latency (`queued.cc:469`), an
accuracy-driven throttle (`queued.cc:141-169`), a per-block `_prefetched` tag bit
(`cache_blk.hh:508`), and a late-prefetch filter applied at issue time inside the
cache against the tags, the MSHR queue and the write buffer
(`src/mem/cache/base.cc:955-989`). wcache has exactly one of those mechanisms in a
recognizable form, the MSHR admission gate, and implements it twice
(`src/wcache/native/src/mshr.cpp:98-115` and the per-core credit budget at
`engine_core.cpp:352-364`); it has no prefetch queue at all, so a prefetch takes a
real L1 port slot as an ordinary probe, and every redundancy is resolved by
*dropping* the prefetch rather than merging or deferring it
(`src/wcache/native/src/cache_level.cpp:149,168,190-198`). The practical consequence
is that wcache's numbers are not comparable to a gem5 baseline without saying so:
its coverage ceiling is structurally capped (the first burst of each tile is never
prefetched, `engine_core.cpp:201-203`), its accuracy is near-perfect by construction
rather than by prediction quality, its prefetches are indistinguishable from demand
fills at replacement insertion (`cache_level.cpp:222-251`), and it has no throttle,
no queue occupancy effect, and no page bound to tune.

---

## 2. The wcache L1 prefetcher as built

All paths in this section are relative to `/home/ya867177/neuro_cache-wcache`.
The class is `NextBurstPrefetcher` (`src/wcache/native/include/wcache/prefetcher.h:122`).

### 2.1 Trigger

One trigger only: the demand issue of a burst. `Engine::on_issue` schedules the
demand probes for burst `k` and then calls the hook as its last statement
(`src/wcache/native/src/engine_core.cpp:205-217`, the call at `:216`). The hook sits
below the port and after the demand lines are already scheduled, so the core cannot
observe it (comment and placement at `engine_core.cpp:213-216`; the interface
contract at `include/wcache/prefetcher.h:74-92`).

There is no miss-triggered, fill-triggered, or prefetch-hit-triggered L1 prefetch:
not implemented. An L1 array hit or an L1 MSHR match by a prefetch is a drop, never
a re-trigger (`src/wcache/native/src/cache_level.cpp:149,168`). By contrast the L2
prefetcher does re-trigger on a demand hit to a line still tagged prefetched
(`src/wcache/native/src/engine.cpp:413-428`).

A second, non-issuing hook exists: `on_tile_start(core)`, called at the tile barrier
(`engine_core.cpp:77`), resets the lookahead cursor to 0
(`src/wcache/native/src/prefetcher.cpp:31-36`). Consequence, stated by the code
itself: the first burst of every tile is never prefetched, which is the coverage
ceiling (`engine_core.cpp:201-203`).

### 2.2 Address generation

Not next-line, not stride detection, not tensor-index arithmetic: it is trace
replay lookahead.

- The policy selects *burst indices* in `[k+1, k+d]`
  (`prefetcher.cpp:48-61`), never addresses.
- The engine converts a burst index to lines exactly as the demand path does:
  `mapper_.expand(trace_.burst(core, cs.tile, k), pf_lines_)`
  (`engine_core.cpp:350`) against the same virtual `AddressMapper::expand`
  (`include/wcache/layout.h:154`) the demand issue uses (`engine_core.cpp:206`
  region).
- A `Burst` is `{anchor Coord, axis, count, stride}`
  (`include/wcache/types.h:284-289`), so the address run is given by the trace,
  not predicted.
- Bounds: the tile bound `cursor < mem.n_bursts_in_tile(core)`
  (`prefetcher.cpp:52,54`, the query at `engine_core.cpp:336-339`), so the policy
  never crosses a tile boundary; and "never behind the core",
  `cursor = max(cursor, k+1)` (`prefetcher.cpp:48-49`).
- Tensor-shape bounds are not checked in the prefetcher: they belong to the mapper,
  and the prefetch path deliberately does not wrap the expand in a context message
  (`engine_core.cpp:344-350`).
- There is no page-equivalent bound, because the model has no pages: not
  implemented.

### 2.3 Degree and distance

- Distance `d` is the `prefetch_distance` config knob, stored in
  `NextBurstPrefetcher::distance_` (`prefetcher.h:146`, constructor
  `prefetcher.cpp:13-25`), measured in **bursts**, not lines or blocks. `d >= 1` is
  enforced in the constructor (`prefetcher.cpp:15-19`), and `next_burst` with
  distance 0 is rejected at config validation (`src/wcache/native/src/config.cpp:653-656`).
- Degree is not a separate knob. The loop runs bursts `cursor .. k+d`
  (`prefetcher.cpp:54-61`) and every burst expands to *all* of its lines
  (`engine_core.cpp:356-375`). Lines per trigger = (bursts still ahead, up to `d`)
  times lines-per-burst, capped by the credit budget.
- The real cap is the credit budget `l1_mshrs - l1_demand_reserve`
  (`engine_core.cpp:354`, per-core counter at `:353`). When it runs out mid-burst,
  `issue_prefetch` returns false, the cursor is *not* advanced, and the same burst
  is retried at the next demand issue (`prefetcher.cpp:54-61`,
  `engine_core.cpp:361-364`).

### 2.4 MSHR interaction

There is **no prefetch queue**. A prefetch reserves a real L1 port slot and is
scheduled as an ordinary `L1Probe` event, exactly like a demand
(`engine_core.cpp:365-374`, and the comment at `:368-370` noting that at
`l1_ii = 1` every prefetch costs the demand stream a cycle). It then enters the same
`CacheLevel::triage`.

The discriminator is `is_prefetch_at_issue(r) := !r.demand && r.mshr1 == nullptr`
(`include/wcache/mshr.h:299-301`), true only for an L1-issued prefetch not yet
forwarded. Triage outcomes for such a request are all drops, never waits:

- array hit: `DroppedArrayHit`, taken *before* `policy_->on_hit` runs
  (`cache_level.cpp:144-149`);
- matching MSHR entry: `DroppedEntry`, taken *before* the target-list bound is
  consulted (`cache_level.cpp:164-168`);
- no admissible slot: `DroppedReserve` if free entries remain but they are the
  reserve, else `DroppedNoSlot` (`cache_level.cpp:190-198`);
- otherwise a primary miss, allocating an ordinary MSHR entry
  (`cache_level.cpp:208`) with `pf_opened = !primary.demand` recorded on it
  (`src/wcache/native/src/mshr.cpp:144`).

So a prefetch is never merged onto an existing entry and never queued on a wait
index; the latter is enforced by hard errors in `MshrFile::push_line_wait` and
`push_slot_wait` (`mshr.cpp:168-184`).

Late prefetch (a demand reaching an in-flight prefetch entry) goes down the ordinary
secondary-miss path and merges, and `add_target` performs the promotion
`e.demand = e.demand || r.demand` (`mshr.cpp:158-166`, caller at
`cache_level.cpp:164-179`). At fill, an entry with `pf_opened && demand` is counted
`pf_late` (`engine.cpp:560-577`, increment at `:573`), and the latency anchor for
that burst is the entry's `first_request`, that is the prefetch's issue time, so the
partial head start is credited (`mshr.cpp:141-144`).

Occupancy control is two independent mechanisms:
1. `MshrFile::has_slot` refuses a prefetch-at-issue unless `free > demand_reserve_`
   (`mshr.cpp:98-115`, the decision at `:114`), reserving the last
   `l1_demand_reserve` entries for demands;
2. the prefetcher-side per-core credit budget in `issue_prefetch`
   (`engine_core.cpp:352-364`). Credits return when a prefetch is dropped
   (`engine.cpp:284`) or when its fill lands (`engine.cpp:608`).

### 2.5 Tagging

At the L1 there is **no bit in the tag or line struct**. `Candidate` carries only
`{SlotId, LineId}` (`include/wcache/cache.h:38-41`) and `insert` takes no demand
flag (`cache.h:107`). Tagging is held outside the array:

- on the MSHR entry, `Mshr::pf_opened`, written once at allocate
  (`mshr.cpp:141-144`);
- per core, `pf_resident_`: line to the prefetch's issue time, for lines a prefetch
  brought in that no demand has reached (`include/wcache/engine.h:611`, filled at
  `engine.cpp:571-576`, `note_prefetch_resident` at `engine.cpp:648-650`);
- per core, `pf_evicted_`: prefetched lines lost from the L1 this tile, for the
  pollution term (`engine.h:616`, written at `engine.cpp:652-657`, cleared per tile
  at `engine_core.cpp:69-72`).

Uses: `pf_timely` on a demand hit to a still-untouched prefetched line
(`engine.cpp:625-635`); `pf_wasted` when such a line is evicted
(`engine.cpp:653-657`) or is still resident at end of run (`engine.cpp:668-669`);
`pf_pollution_evictions` when a demand misses on a line an earlier prefetch had
brought in and lost this tile (`engine.cpp:644`).

The L2 side does keep an explicit tag set mirroring gem5's `CacheBlk::_prefetched`:
`l2_prefetched_` (`engine.h:637`), set at fill (`engine.cpp:506`), cleared on the
first demand hit (`engine.cpp:417-424`), charged as `l2_pf_wasted` on eviction
(`engine.cpp:513-516`).

### 2.6 Replacement insertion

Prefetch fills and demand fills are indistinguishable at insertion.
`CacheLevel::install(LineId)` takes no demand or prefetch flag
(`cache_level.cpp:222`), prefers a free way and otherwise calls
`policy_->pick_victim` (`cache_level.cpp:237-241`), inserts, then calls
`policy_->on_fill(slot)` (`cache_level.cpp:251`). There is therefore **no distinct
insertion position for prefetches** in any policy: not implemented. Concretely, for
the policies present (`include/wcache/stamp_policy.h:257-264`: LRU, FIFO, RANDOM
placeholder, BELADY, RRIP, LFU):

- stamp policies (LRU, FIFO): `StampPolicy::on_fill` is `stamp(slot)`
  (`src/wcache/native/src/stamp_policy.cpp:65`), so a prefetch fill lands at MRU
  exactly as a demand fill does;
- RRIP: `rrpv_[slot] = kRripInsertRrpv` for both (`stamp_policy.cpp:255-257`);
- LFU: `count_[slot] = 0` for both (`stamp_policy.cpp:195`);
- Belady: `on_fill` only bounds-checks (`stamp_policy.cpp:141`), and the next-use
  stamp is written in `install` guarded on the oracle alone, not on `r.demand`
  (`cache_level.cpp:246-250`), the interaction warned about as `W_BELADY_PREFETCH`
  (`config.cpp:706`).

What *is* different is that a prefetch never counts as a use: a prefetch hitting the
array is dropped without `policy_->on_hit` (`cache_level.cpp:144-153`, the `probe`
contract being const and side-effect free at `cache.h:79`). So the prefetcher can
change recency order only on a fill, never on a hit.

### 2.7 Throttling and feedback

**Not implemented.** There is no accuracy tracking fed back into issue, no
confidence counter, no adaptive degree or distance, and no throttle state anywhere in
`prefetcher.cpp` or `prefetcher.h`. The only thing that stops the L1 prefetcher is
the fixed MSHR credit budget (`engine_core.cpp:361-364`). The interface makes
feedback impossible by construction: a prefetcher may only call `n_bursts_in_tile`
and `issue_prefetch` (`prefetcher.h:51,63`) and cannot read a core cursor, cache
contents, or MSHR occupancy. The accuracy statistics of section 2.9 are report-only.

### 2.8 Config knobs, with defaults

L1:

| name | type | default | declared | parsed |
|---|---|---|---|---|
| `prefetch_policy` | `none` / `next_burst` | `none` | `include/wcache/config.h:100` | `config.cpp:256-266` |
| `prefetch_distance` | int, in bursts | `0` | `config.h:101` | `config.cpp:149` |
| `l1_mshrs` | int | `16` | `config.h:63` | `config.cpp:141` |
| `l1_demand_reserve` | int, `-1` resolves to `lines_per_burst` | `-1` | `config.h:70` | `config.cpp:145`, resolved `config.cpp:658` |

L2, for contrast:

| name | default | declared |
|---|---|---|
| `l2_prefetch_policy` (`none` / `neighbour`) | `none` | `config.h:93` |
| `l2_prefetch_axis` | `cin` | `config.h:94` |
| `l2_prefetch_distance` | `1` | `config.h:95` |
| `l2_prefetch_up` | `true` | `config.h:96` |
| `l2_prefetch_down` | `true` | `config.h:97` |
| `l2_demand_reserve` | `-1`, resolved from `lines_per_burst` | `config.h:98` |

Validation touching prefetching: `prefetch_distance >= 0` (`config.cpp:619-620`);
`next_burst` with distance 0 refused (`config.cpp:653-654`);
`l1_demand_reserve >= l1_mshrs` refused (`config.cpp:663-664`); warning
`W_PREFETCH_BUDGET` when `l1_mshrs - l1_demand_reserve < lines_per_burst`
(`config.cpp:687-690`); warning `W_BELADY_PREFETCH` (`config.cpp:706`).

### 2.9 Stats, exact emitted names

Config echo: `prefetch_policy`, `prefetch_distance` (`src/wcache/native/src/stats.cpp:180-181`).

L1 counters, emitted at `stats.cpp:309-333`: `pf_issued` (`:309`), `pf_timely`
(`:310`), `pf_late` (`:311`), `pf_wasted` (`:312`), `pf_dropped_array_hit` (`:313`),
`pf_dropped_matching` (`:314`), `pf_dropped_no_slot` (`:315`),
`pf_dropped_targets_full` (`:320`, structurally 0, reason at `:316-319`),
`pf_dropped_reserve` (`:321`), the ratio `pf_coverage` (`:328-329`),
`pf_coverage_ceiling` (`:330-331`), `pf_budget_exhausted` (`:332`),
`pf_pollution_evictions` (`:333`). Backing fields at `include/wcache/engine.h:183-218`,
with the stated invariant that the four outcomes plus the five drop counts sum to
`pf_issued` (`engine.h:198-200`).

L2 counters (`stats.cpp:336-355`): `l2_prefetch_policy`, `l2_prefetch_axis`,
`l2_prefetch_distance`, `l2_prefetch_up`, `l2_prefetch_down`, `l2_pf_issued`,
`l2_pf_issued_up`, `l2_pf_issued_down`, `l2_pf_timely`, `l2_pf_late`,
`l2_pf_wasted`, `l2_pf_retriggers`, `l2_pf_dropped_array_hit`,
`l2_pf_dropped_entry`, `l2_pf_dropped_no_slot`, `l2_pf_dropped_reserve`,
`l2_pf_coverage`.

### 2.10 Contrast with the L2 cin-neighbour prefetcher

`NeighbourL2Prefetcher` (`prefetcher.h:213-233`, `prefetcher.cpp:94-125`) is a
sibling class, not a subclass (`prefetcher.h:170-175`), and differs on every axis:

- **Address generation**: `mapper.neighbour(line, axis, +/-d)` for `d = 1..distance`,
  near first, both directions (`prefetcher.cpp:109-125`). A tensor-axis step on line
  ids, not a byte stride, and the mapper returns `nullopt` when the neighbour leaves
  the layer.
- **Trigger**: an L2 demand miss (`Forwarded`), plus a demand hit to a line still
  tagged in `l2_prefetched_`, which re-triggers the chain (`engine.cpp:405-428`).
  The in-code comment records 50.0% hit rate miss-only against 96.9% with the
  re-trigger row (`engine.cpp:408-412`). This is tagged prefetching in gem5's sense;
  the L1 has no such re-trigger.
- **It suggests, never issues**: the engine owns the port slot, the entry and the
  channel charge (`prefetcher.h:170-175`).
- **Budget**: `l2_demand_reserve` inside `MshrFile::has_slot` (`mshr.cpp:114`), with
  no L2 analogue of the per-core `pf_outstanding` credit counter.
- **Tagging**: an explicit tag set (`engine.h:637`) rather than the L1's
  `pf_resident_` / `pf_evicted_` pair.
- **Unit**: the L1 prefetches whole bursts, a core-timeline concept; the L2
  prefetches individual lines, an address-space concept.

### 2.11 The older simulator under `src/cachesim/`

`src/cachesim/` has **no L1 prefetcher at all**. Its only prefetching is an
`l2_prefetch` switch on `TwoLevelHierarchy` (`src/cachesim/hierarchy.h:49-57`, CLI
argument 16 at `src/cachesim/main_hierarchical.cpp:160,176`) that, on an L2 miss
only, queues the next COUT block as a fill, degree 1, with no chaining
(`hierarchy.h:106-117`). That model is tick-atomic and functional, with no ports and
no MSHRs, so none of the budget or drop machinery above applies to it.

---

## 3. gem5's prefetcher framework

Paths in this section are relative to `src/mem/cache/` in the gem5 checkout named in
section 7.

### 3.1 The Base / Queued split

`BasePrefetcher` (`prefetch/Prefetcher.py:64-131`) owns the observation filter and
the probe wiring. `QueuedPrefetcher` (`Prefetcher.py:133-167`) owns the prefetch
queue, translation handling, throttling and the issue interface. A policy subclasses
`Queued` and implements one method, `calculatePrefetch(pfi, addresses, cache)`,
returning `(Addr, priority)` candidates. Everything in sections 3.2 through 3.7 is
inherited, not written per policy. FDP is the one shipped exception: it derives from
`BasePrefetcher` directly (`prefetch/fdp.hh`).

### 3.2 Filter gates and defaults

`BasePrefetcher` parameters (`Prefetcher.py:64-94`), all verified at those lines:

| param | default | line |
|---|---|---|
| `sys` | `Parent.any` | 70 |
| `block_size` | `Parent.cache_line_size` | 73 |
| `on_miss` | `False` | 75 |
| `on_read` | `True` | 76 |
| `on_write` | `True` | 77 |
| `on_data` | `True` | 78 |
| `on_inst` | `True` | 79 |
| `prefetch_on_access` | `False` | 80-83 |
| `prefetch_on_pf_hit` | `True` | 84-87 |
| `use_virtual_addresses` | `False` | 88-90 |
| `page_bytes` | `"4KiB"` | 91-93 |

`QueuedPrefetcher` parameters (`Prefetcher.py:133-167`): `latency` 1 (137),
`queue_size` 32 (138), `max_prefetch_requests_with_pending_translation` 32 (139),
`queue_squash` `True` (143), `queue_filter` `True` (144), `cache_snoop` `False`
(145-147), `tag_prefetch` `True` (149-151), `throttle_control_percentage` 0
(162-166). `degree` is per policy, not on either base class: Tagged 2
(`Prefetcher.py:230`), Stride 4 (203), IrregularStreamBuffer 4 (486), BOP 1 (594),
AMPM uses `start_degree` (387).

`Base::observeAccess` (`prefetch/base.cc:166-192`) applies these in order: on a hit,
return `prefetched` if `prefetchOnPfHit`, else `false` if `!prefetchOnAccess`; then
drop uncacheable, drop instruction fetches if `!onInst`, drop data if `!onData`,
drop data reads if `!onRead`, drop data writes if `!onWrite`, drop data
invalidates, drop `CleanEvict`; finally, if `onMiss`, return `miss`. The consequence
of the defaults, read off that function: because `prefetch_on_pf_hit` defaults true,
a hit is observed whenever the line was itself prefetched regardless of
`prefetch_on_access`, so a shipped-default Tagged or Stride L1 prefetcher trains on
misses **plus** hits to prefetched lines.

### 3.3 Probe and notify

`Base::regProbeListeners` (`base.cc:270-288`): if the config script registered no
explicit probes, the prefetcher attaches four listeners on the parent cache,
`"Miss"`, `"Fill"`, `"Hit"` and `"Data Update"`. `PrefetchListener::notify`
(`base.cc:84-92`) routes fills to `notifyFill()` and everything else to
`probeNotify(arg, miss)`; `notifyFill` and `notifyEvict` are no-ops in the base
class (`base.hh:396-401`). Explicit probes can be added from Python via
`listenFromProbe` / `addEventProbe` (`Prefetcher.py:57-62, 110-115`,
`base.cc:290-295`), which is how PIF listens to retired-instruction probes.

`Base::probeNotify` (`base.cc:230-268`) is the single funnel:

- early drops at `base.cc:238-241`: software prefetch commands, cache maintenance
  operations, clean evictions, and writes the cache is coalescing; `base.cc:242-244`
  panics if the request has no physical address;
- usefulness accounting at `base.cc:246-256`:
  `cache.hasBeenPrefetched(addr, secure, requestorId)` decides whether this access
  consumed a prefetched line; if so `pfUseful++` (`:250`), plus `pfUsefulButMiss++`
  when the access still missed because the block was in an unusable coherence state
  (`:252-255`). This is requestor-scoped;
- filtering at `base.cc:259`, then `PrefetchInfo` construction at `base.cc:260-266`.

### 3.4 PrefetchInfo, page check, virtual addresses

`PrefetchInfo` (`base.cc:60-82`) carries the address, the PC (with `validPC=false`
when the request has no PC), requestorId, the secure flag, size, a write flag, the
physical address, `cacheMiss`, and a copy of the data payload when available
(`base.cc:66-73`).

Addressing: a virtual address is used only if `use_virtual_addresses` *and* the
request actually has a vaddr (`base.cc:261-266`); if `use_virtual_addresses` is set
and there is no vaddr, the access is silently dropped, because neither branch of
that `if` matches.

Page helpers live at `base.cc:194-228` (`samePage`, `blockAddress`, `blockIndex`,
`pageAddress`, `pageOffset`, `pageIthBlockAddress`), but the page check itself is
enforced in `Queued::notify` (`queued.cc:212-221`), not in base: a candidate leaving
the page increments `pfSpanPage` and is kept only if an MMU was registered
(`can_cross_page = (mmu != nullptr)`, `queued.cc:220`); otherwise it is dropped with
no further stat.

### 3.5 HardPFReq, Request::PREFETCH, and the `_prefetched` bit

The packet is built in `Queued::DeferredPacket::createPkt` (`queued.cc:58-77`) as
`MemCmd::HardPFReq` with `taskId(context_switch_task_id::Prefetcher)`, plus the
`Request::SECURE` flag when applicable. `Request::PREFETCH` is set on the
*translation* request in `Queued::createPrefetchRequest` (`queued.cc:377-385`). With
`tag_prefetch` true (the default) the packet's request is tagged with the PC of the
training access (`queued.cc:72-75`), which is what lets a downstream L2 prefetcher do
PC-based training on L1 prefetch traffic.

The per-block tag is `CacheBlk::_prefetched` (`cache_blk.hh:508`), with
`wasPrefetched` / `clearPrefetched` / `setPrefetched` at `cache_blk.hh:252-261`.
`BaseCache::recvTimingReq` notifies the `"Hit"` probe *before* clearing the bit
(`base.cc:498-507`), so the prefetcher sees the line as still prefetched on the first
demand hit and only then is the bit cleared; a second hit on the same line no longer
counts as useful. If a block is invalidated while still marked,
`BaseCache::invalidateBlock` (`base.cc:1727-1732`) calls `prefetcher->prefetchUnused()`.

Replacement insertion: prefetch fills allocate through the ordinary cache allocation
path, so they update replacement state like any other fill. gem5 ships no
prefetch-specific insertion position at this commit; the `_prefetched` bit is
bookkeeping, not an input to the replacement policy.

### 3.6 The prefetch queue

Two lists, `pfq` (ready packets) and `pfqMissingTranslation` (waiting on the MMU),
bounded by `queue_size` and `max_prefetch_requests_with_pending_translation`.

`Queued::notify` (`queued.cc:171-236`), in order:
1. **Squash** (`queued.cc:179-196`): with `queue_squash`, every queued entry whose
   block address and secure flag match the incoming demand is deleted and
   `pfRemovedDemand++` (`:191`). This is the "a demand beat us to it" path.
2. `calculatePrefetch(pfi, addresses, cache)` (`:200`), the per-policy hook.
3. **Throttle** (`:202-203`) via `getMaxPermittedPrefetches` (`queued.cc:141-169`):
   `max_pfs = min_pfs + (total - min_pfs) * usefulPrefetches / issuedPrefetches`,
   where `min_pfs = total - total*throttleControlPct/100`, floored at 1
   (`:160-167`). With the default `throttle_control_percentage = 0` this is a no-op.
4. **Per candidate** (`:207-235`): block-align; page check as in section 3.4;
   surviving candidates increment `pfIdentified` (`:223`) and go to `insert()`; the
   loop stops after `max_pfs` insertions (`:229-231`).

`Queued::insert` (`queued.cc:388-484`):
- **Dedup** (`:391-398`): with `queue_filter`, `alreadyInQueue` is checked against
  both queues; a duplicate bumps `pfBufferHit++` (`:353`) and, if the new priority is
  higher, re-sorts the entry forward (`queued.cc:342-374`).
- **Address computation** (`:400-456`): same-page prefetches get their physical
  address directly (or PA plus signed stride when training on VAs); page-crossing
  ones build a translation request and go to `pfqMissingTranslation`. A page-crossing
  request with no contextId, or PA training with no vaddr, is dropped.
- **Redundancy snoop** (`:457-464`): only if `cache_snoop` (default false),
  `cache.inCache()` or `cache.inMissQueue()` drops the candidate with `pfInCache++`
  (`:460`). The same check is repeated after a late translation completes
  (`:321-326`).
- **Latency** (`:469`): `pf_time = curTick() + clockPeriod() * latency`. The packet
  is invisible to the cache until then, via `nextPrefetchReadyTime()`
  (`queued.hh:208`). This is a per-entry ready time on a priority-ordered queue, so
  `latency` is a fixed delay from generation, not a throughput limit.

`Queued::addToQueue` (`queued.cc:487-534`): if the queue is full, the lowest
priority (oldest within that priority) entry is evicted with `pfRemovedFull++`
(`:492`), and the new entry is inserted in priority order.

`Queued::getPacket` (`queued.cc:239-264`) pops the head, increments `pfIssued` and
`issuedPrefetches`, and pumps `processMissingTranslations` around the pop.

### 3.7 MSHR gating and the redundancy filter at issue time

Hand-off to the cache is on the cache side, not in the prefetcher.
`BaseCache::getNextQueueEntry` (`base.cc:953-989`) calls `prefetcher->getPacket()`
only when `mshrQueue.canPrefetch() && !isBlocked()` (`:955`), that is when a
reserved MSHR slot exists. It then re-checks the packet against the tags
(`:960-963`, `pfHitInCache()`), the MSHR queue (`:966-969`, `pfHitInMSHR()`) and the
write buffer (`:972-975`, `pfHitInWB()`), dropping and deleting it in each case. With
the shipped default `cache_snoop = False` this is the real redundancy and
late-prefetch filter. A surviving prefetch counts as an `mshrMisses` for its
requestor and allocates a miss buffer (`:978-987`). Demand misses that allocate a
fresh MSHR call `prefetcher->incrDemandMhsrMisses()` (`base.cc:416-417`), which feeds
the coverage formula.

Stat names on the base group (`prefetch/base.hh:344-370`, constructed
`base.cc:127-164`): `demandMshrMisses`, `pfIssued`, `pfUnused`, `pfUseful`,
`pfUsefulButMiss`, the formulas `accuracy = pfUseful / pfIssued` and
`coverage = pfUseful / (pfUseful + demandMshrMisses)`, `pfHitInCache`, `pfHitInMSHR`,
`pfHitInWB`, and the formula `pfLate = pfHitInCache + pfHitInMSHR + pfHitInWB`.
Queue-side stats (`queued.cc:266-284`): `pfIdentified`, `pfBufferHit`, `pfInCache`,
`pfRemovedDemand`, `pfRemovedFull`, `pfSpanPage`, `pfUsefulSpanPage`. Naming note:
this commit has `pfHitInCache` on the base group and `pfInCache` on the queue group;
there is no `pfInCachePrefetched` anywhere in it.

### 3.8 Tagged, in detail

`prefetch/tagged.{hh,cc}`. The entire policy is `tagged.cc:50-61`:

```
Addr blkAddr = blockAddress(pfi.getAddr());
for (int d = 1; d <= degree; d++) {
    Addr newAddr = blkAddr + d*(blkSize);
    addresses.push_back(AddrPriority(newAddr,0));
}
```

Block-align the training address, emit `degree` consecutive next-line addresses at
priority 0, unconditionally, on every observed access. No table, no confidence, no
state beyond the const `degree` (`tagged.hh:51`). Default `degree = 2`
(`Prefetcher.py:230`). Everything else (page check, dedup, queue, throttle, latency)
is inherited from `Queued`. `on_inst` is left at the base default `True`, so with
`prefetch_on_pf_hit` default true a Tagged L1 prefetcher is effectively a next-2-line
prefetcher trained on all misses plus prefetched-line hits.

### 3.9 Stride, in detail

`prefetch/stride.{hh,cc}`. Parameters (`Prefetcher.py:176-223`):
`confidence_counter_bits = 3`, `initial_confidence = 4`,
`confidence_threshold = 50` percent, `use_requestor_id = True`,
`use_cache_line_address = True`, `degree = 4` (`:203`), `distance = 0` (`:204`),
`table_assoc = 4`, `table_entries = "64"`,
`table_indexing_policy = StridePrefetcherHashedSetAssociative`,
`table_replacement_policy = RandomRP()`. It overrides `on_inst = False`
(`Prefetcher.py:182`), so it never trains on instruction fetches.

Table entry (`stride.hh:143-145`): `lastAddr`, signed `stride`, `SatCounter8
confidence`. The confidence counter is a 3-bit saturating counter starting at 4 of 7,
and the threshold is a *saturation fraction*: `threshConf = confidence_threshold/100.0`
(`stride.cc:85`) compared against `confidence.calcSaturation()`. One table per
context (per requestorId when `use_requestor_id`), created lazily in `findTable` /
`allocateNewContext` (`stride.cc:95-125`); indexing hashes the PC,
`(pc>>1) ^ ((pc>>1)>>tagShift)` (`stride.cc:211-218`).

`Stride::calculatePrefetch` (`stride.cc:128-209`):
- no PC, return (`:132-135`). This matters for an L1 comparison: an access without a
  PC trains nothing and prefetches nothing;
- the address is the block address when `use_cache_line_address` (the default), else
  the word address (`:138-139`);
- table hit: `new_stride = pf_addr - entry->lastAddr` (`:155`); a zero stride in
  cacheline mode returns immediately (`:158`); on match `confidence++`, on mismatch
  `confidence--`, and only once saturation has fallen below the threshold does the
  entry retrain to `new_stride` (`:161-172`); `lastAddr` is always updated;
- generation (`:181-197`): abort if saturation is still below the threshold (`:182`);
  round `|stride|` up to at least one block; start at `pf_addr + distance*stride`
  (`:192`) and emit `degree` addresses at `stride` spacing, all at priority 0
  (`:194`);
- table miss (`:198-208`): allocate a victim via the replacement policy (RandomRP by
  default), record `lastAddr`, prefetch nothing this access.

### 3.10 The remaining shipped policies

| Policy | File(s) | One line |
|---|---|---|
| MultiPrefetcher | `multi.{hh,cc}` | Composition wrapper: holds a vector of prefetchers, round-robins `getPacket()` over those that are ready (`multi.cc:73-91`), and fans `prefetchUnused` and `incrDemandMhsrMisses` out to all of them. |
| AMPM | `access_map_pattern_matching.{hh,cc}` | Access Map Pattern Matching (Ishii et al., JILP 2011): per-page access map, stride patterns matched in it; the matcher is a separate SimObject reused by SlimAMPM. |
| BOP | `bop.{hh,cc}` | Best-Offset Prefetcher (Michaud, DPC2 2015): scores candidate offsets against a recent-requests table, prefetches at the single best offset. Default `degree = 1`. |
| DCPT | `delta_correlating_prediction_tables.{hh,cc}` | Delta Correlating Prediction Tables (Grannaes et al., HiPEAC 2010): per-PC circular buffer of address deltas matched by delta pairs. |
| IndirectMemory | `indirect_memory.{hh,cc}` | IMP (Yu et al., MICRO 2015): detects `A[B[i]]` indirect patterns by learning a base address and shift from a streaming index. |
| IrregularStreamBuffer | `irregular_stream_buffer.{hh,cc}` | ISB (Jain and Lin, MICRO 2013): remaps irregular addresses into a linear structural space and prefetches along it. Default `degree = 4`. |
| PIF | `pif.{hh,cc}` | Proactive Instruction Fetch (Ferdman et al., MICRO 2011): instruction prefetcher driven by retired-instruction probes. |
| SBOOE | `sbooe.{hh,cc}` | Sandbox Based Optimal Offset Estimation: evaluates candidate offsets in a sandbox before committing. |
| SignaturePath / SPPv2 | `signature_path.{hh,cc}`, `signature_path_v2.{hh,cc}` | SPP and its path-confidence follow-up (MICRO 2016): compresses a page's delta history into a signature and follows the chain with lookahead, gated by path confidence. |
| SlimAMPM | `slim_ampm.{hh,cc}` | Slim AMPM (Young and Krishna, DPC2 2015): bandwidth-efficient combination of an AMPM access map and DCPT delta tables. |
| SMS | `sms.{hh,cc}` | Spatial Memory Streaming: records per-page spatial footprints keyed on a trigger access and replays them. |
| STeMS | `spatio_temporal_memory_streaming.{hh,cc}` | Spatio-Temporal Memory Streaming (Somogyi et al., 2009): spatial footprints plus temporal stream ordering. |
| FDP | `fdp.{hh,cc}` | Fetch-Directed instruction Prefetcher: derives from `BasePrefetcher` rather than `Queued`, driven by the branch predictor's fetch-target queue. |

---

## 4. Side-by-side comparison

| Dimension | wcache L1 | gem5 |
|---|---|---|
| Trigger events | Demand *issue* of a burst only (`engine_core.cpp:216`); plus a tile-start cursor reset (`engine_core.cpp:77`). No miss, fill, or hit trigger. | Probe listeners on Miss, Fill, Hit, Data Update (`base.cc:270-288`); gated by `on_miss`/`on_read`/`on_write`/`on_data`/`on_inst`/`prefetch_on_access`/`prefetch_on_pf_hit` (`base.cc:166-192`). Defaults train on misses plus prefetched-line hits. |
| Training input | None. The trace's burst descriptors are read directly (`prefetcher.cpp:48-61`). | `PrefetchInfo`: address, PC, requestorId, secure, size, write flag, `cacheMiss`, data payload (`base.cc:60-82`). |
| Address generation | `mapper_.expand(trace_.burst(core, tile, cursor))`, all lines of bursts `k+1..k+d` (`engine_core.cpp:350`, `layout.h:154`). | Policy-specific `calculatePrefetch`; Tagged emits `blkAddr + d*blkSize` for `d=1..degree` (`tagged.cc:55-60`); Stride emits `addr + (distance+d)*stride` gated on confidence (`stride.cc:181-197`). |
| Degree | Not a knob. Equals (bursts ahead, up to `d`) times lines-per-burst (`prefetcher.cpp:54-61`, `engine_core.cpp:356-375`). | Per-policy `degree`: Tagged 2 (`Prefetcher.py:230`), Stride 4 (`:203`), ISB 4, BOP 1. |
| Distance / lookahead | `prefetch_distance`, in **bursts** (`prefetcher.h:146`, `config.h:101`, default 0). | Stride `distance` in strides (`Prefetcher.py:204`, default 0); SPP uses path-confidence lookahead. No generic base-class distance. |
| Prefetch queue | None. A prefetch is scheduled as an ordinary `L1Probe` on a real port slot (`engine_core.cpp:365-374`). | `pfq` plus `pfqMissingTranslation`, priority-ordered, `queue_size` 32; full-queue eviction with `pfRemovedFull` (`queued.cc:487-534`). |
| MSHR interaction | Prefetch takes an ordinary MSHR entry on a primary miss (`cache_level.cpp:208`); never merges onto an existing entry (dropped instead, `:164-168`); never queued on a wait index (`mshr.cpp:168-184`). | Issue gated on `mshrQueue.canPrefetch()` (`base.cc:955`); a surviving prefetch allocates a miss buffer (`base.cc:987`); coalescing is the cache's normal MSHR behavior. |
| Coalescing of prefetch onto in-flight | Not done: prefetch meeting a matching entry is `DroppedEntry` (`cache_level.cpp:168`). | Not done either: dropped at issue with `pfHitInMSHR` (`base.cc:966-969`). Queued dedup also drops duplicates already in the queue (`queued.cc:391-398`). |
| Late-prefetch handling | Demand merges onto the prefetch entry and promotes it (`mshr.cpp:158-166`); counted `pf_late` at fill (`engine.cpp:573`); latency anchored on the prefetch's issue time. | Queued entry squashed by a matching demand (`queued.cc:179-196`, `pfRemovedDemand`); a too-late prefetch is dropped at issue and counted in the `pfLate` formula (`base.cc:959-975`, `base.hh:370`). |
| Prefetch tagging | No bit in the array (`cache.h:38-41,107`). Side structures: `Mshr::pf_opened` (`mshr.cpp:144`), `pf_resident_` (`engine.h:611`), `pf_evicted_` (`engine.h:616`). L2 has an explicit tag set (`engine.h:637`). | Per-block `_prefetched` bit (`cache_blk.hh:508`), cleared on the first demand hit after the Hit probe fires (`base.cc:498-507`); carried when a block moves; drives `pfUseful` and `pfUnused`. |
| Replacement insertion | Identical to a demand fill in every policy (`cache_level.cpp:222-251`; LRU/FIFO MRU at `stamp_policy.cpp:65`, RRIP at `:255-257`, LFU at `:195`). A prefetch hit is not a use (`cache_level.cpp:144-149`). | Also the ordinary allocation path, so replacement state is updated like any fill; no prefetch-specific insertion position at this commit. |
| Throttling / feedback | Not implemented. Only the fixed credit budget `l1_mshrs - l1_demand_reserve` stops it (`engine_core.cpp:352-364`). Interface forbids feedback (`prefetcher.h:51,63`). | Accuracy-driven candidate throttle `getMaxPermittedPrefetches` (`queued.cc:141-169`), off by default (`throttle_control_percentage = 0`). |
| Page / bounds check | Tile bound and "never behind the core" only (`prefetcher.cpp:48-54`). No pages exist in the model; tensor bounds are the mapper's. | `samePage` check in `Queued::notify`; a page-crossing candidate survives only with an MMU registered (`queued.cc:212-221`), counted `pfSpanPage`. |
| Virtual vs physical addressing | Neither. Addresses are `LineId`s in a tensor layout (`layout.h:154`). No translation step. | Physical by default; `use_virtual_addresses` switches training to vaddrs, and page-crossing prefetches go through the MMU (`base.cc:260-266`, `queued.cc:400-456`). |
| Config knobs | `prefetch_policy` (`none`/`next_burst`, default `none`), `prefetch_distance` (0), `l1_mshrs` (16), `l1_demand_reserve` (-1 to `lines_per_burst`). | 11 base params plus 8 queued params (`Prefetcher.py:64-167`), plus per-policy tables, degrees and confidence settings. |
| Stats | `pf_issued`, `pf_timely`, `pf_late`, `pf_wasted`, `pf_dropped_{array_hit,matching,no_slot,targets_full,reserve}`, `pf_coverage`, `pf_coverage_ceiling`, `pf_budget_exhausted`, `pf_pollution_evictions` (`stats.cpp:309-333`). | `demandMshrMisses`, `pfIssued`, `pfUnused`, `pfUseful`, `pfUsefulButMiss`, `accuracy`, `coverage`, `pfHitInCache`, `pfHitInMSHR`, `pfHitInWB`, `pfLate` (`base.hh:344-370`); `pfIdentified`, `pfBufferHit`, `pfInCache`, `pfRemovedDemand`, `pfRemovedFull`, `pfSpanPage`, `pfUsefulSpanPage` (`queued.cc:266-284`). |
| Composing several prefetchers | Not supported: one `Prefetcher` per engine and one `L2Prefetcher`, chosen by config (`prefetcher.h:74,175`). | `MultiPrefetcher` holds a vector and round-robins `getPacket()` (`multi.cc:73-91`). |

---

## 5. Gaps

### 5.1 What wcache has that gem5 does not

1. **Oracle address generation.** wcache reads the exact future address run from the
   trace (`engine_core.cpp:350`), so it cannot mispredict an address. gem5 has no
   equivalent, and no gem5 policy could have one. This is a deliberate design choice
   given the trace-driven burst model: the spike queue is resolved when the tile
   begins, so the address run is genuinely known ahead of time. It is also the single
   biggest reason wcache numbers are not directly comparable to gem5 numbers.
2. **A burst-level unit.** Distance is measured in bursts, not blocks or strides
   (`prefetcher.h:146`). gem5 has no notion of a multi-line demand group. Deliberate,
   and appropriate for the model.
3. **A drop taxonomy with a checked sum.** Five distinct drop reasons that, with the
   four outcomes, are required to sum to `pf_issued` (`engine.h:198-200`, checked in
   `stats.cpp`). gem5 has overlapping counters (`pfIdentified`, `pfIssued`,
   `pfBufferHit`, `pfInCache`, `pfHitIn*`) with no such invariant. This is a genuine
   strength of the wcache accounting.
4. **An explicit coverage ceiling stat.** `pf_coverage_ceiling`
   (`stats.cpp:330-331`) reports the structural limit (first burst of each tile never
   prefetched). gem5 reports coverage with no ceiling term. Deliberate and worth
   keeping.
5. **A pollution counter.** `pf_pollution_evictions` (`stats.cpp:333`) counts demands
   that miss on a line an earlier prefetch evicted this tile. gem5's `pfUnused` is
   about the prefetched line, not its victim. Genuine strength.
6. **Two independent occupancy limits.** The MSHR demand reserve
   (`mshr.cpp:114`) plus a per-core credit budget (`engine_core.cpp:352-364`). gem5
   has only the MSHR-side `canPrefetch()` gate.

### 5.2 What gem5 has that wcache does not

Grouping by whether the absence is a deliberate consequence of the model or a
missing mechanism.

**Deliberate, given the trace-driven burst model:**

1. *No PC-based or address-based training tables.* There are no PCs in the model and
   no need to learn an address run that the trace already states.
2. *No page check and no virtual/physical split.* The model has no pages and no MMU;
   `LineId`s are tensor coordinates (`layout.h:154`).
3. *No `Request::PREFETCH` / `HardPFReq` packet marking.* There is no packet type
   system to mark; `is_prefetch_at_issue` (`mshr.h:299-301`) carries the same
   information structurally.
4. *No `MultiPrefetcher` composition.* One policy per level is a design choice
   recorded in the interface (`prefetcher.h:74,175`).
5. *No `tag_prefetch` PC propagation to a lower level.* No PCs, and the L2
   prefetcher trains on line ids (`prefetcher.cpp:109-125`).

**Missing mechanisms, not model-forced:**

6. **No prefetch queue.** wcache's prefetches contend for the real L1 port at the
   moment they are generated (`engine_core.cpp:365-374`). gem5 buffers them,
   prioritizes them, and issues them only when the cache is idle enough
   (`base.cc:955`). A queue is expressible in wcache's event model; its absence is a
   simplification, and it changes the port-contention result materially at
   `l1_ii = 1` (which the code itself notes, `engine_core.cpp:368-370`).
7. **No demand squash of pending prefetches.** With no queue there is nothing to
   squash, but the effect gem5 gets from `pfRemovedDemand` (not wasting an issue slot
   on a line the core just asked for) is absent. wcache instead pays the slot and
   drops at triage (`cache_level.cpp:149,168`).
8. **No throttle or accuracy feedback.** Not implemented (section 2.7), and the
   interface forbids it by construction (`prefetcher.h:51,63`). gem5's throttle is
   off by default, so this is not fairness-critical against the *shipped* gem5
   defaults, but it is a missing mechanism.
9. **No generation latency.** gem5 charges `clockPeriod() * latency` between training
   and visibility (`queued.cc:469`, default 1 cycle). wcache issues in the same
   event as the demand (`engine_core.cpp:216`), so its prefetches are strictly
   earlier than gem5's by that amount. Expressible in wcache's event queue; absent.
10. **No prefetch-specific replacement insertion, and no path to add one.** `install`
    does not carry the demand flag (`cache_level.cpp:222`), so no policy can
    implement, for example, LRU-insert-at-LRU for prefetches. gem5 does not ship this
    either, so it is not a gap *against gem5*, but it is a missing degree of freedom
    that the Belady warning (`config.cpp:706`) shows already bites.
11. **No write-buffer check.** gem5 drops a prefetch that hits the write buffer
    (`base.cc:972-975`). wcache has no write buffer in this model, so this is
    model-forced rather than missing, listed here for completeness.
12. **No requestor-scoped usefulness.** gem5's `hasBeenPrefetched` requires
    `getSrcRequestorId() == requestor` (`base.hh:1260-1265`), so in a multi-core
    shared cache a prefetch is credited only to its issuer. wcache's `pf_resident_`
    is per core (`engine.h:611`), so the L1 case is equivalent; the L2 tag set
    `l2_prefetched_` is **not** per core (`engine.h:637`), so at the shared L2 any
    core's demand clears any core's prefetch tag. Inferred consequence: `l2_pf_timely`
    is credited across cores. This looks like a real, if small, accounting gap.

---

## 6. Prioritized suggestions

Ordered by value divided by effort. Effort estimates are for implementation plus
tests in this codebase, and are estimates, not measurements.

### Fairness-critical if a paper claims a "gem5-like baseline"

**S1. Stop calling it a prefetcher baseline, or state the oracle explicitly.**
*What:* one paragraph in the evaluation methodology saying the L1 prefetcher reads
the trace's future burst descriptors (`engine_core.cpp:350`) rather than predicting,
so its accuracy is structural; and report `pf_coverage_ceiling`
(`stats.cpp:330-331`) alongside `pf_coverage`.
*Why:* a reviewer comparing this against a Tagged or Stride baseline will read
near-100% accuracy as a result rather than as a definition. This is the single
highest-value item and it costs no code.
*Effort:* 1 to 2 hours.

**S2. Match gem5's `coverage` denominator before printing any comparison.**
*What:* gem5's `coverage = pfUseful / (pfUseful + demandMshrMisses)`
(`base.hh:355-356`, `base.cc:160-161`), where `demandMshrMisses` counts only demands
that allocated a *new* MSHR (`base.cc:416-417`). wcache's `pf_coverage` is
`(pf_timely + pf_late) / demand_bursts` (`stats.cpp:328-329`), a per-burst
denominator that includes demands which coalesce. Add a second emitted ratio using
gem5's definition, keeping the existing one.
*Why:* the two numbers differ by whatever the secondary-miss rate is, and that
difference will be read as a prefetching result. Fairness-critical.
*Effort:* 3 to 4 hours (a new per-core counter incremented where a demand allocates
a primary entry, plus the ratio in `stats.cpp`).

**S3. Add a baseline mode with a gem5-shaped address generator.**
*What:* a third `prefetch_policy` value, `next_line(degree)`, that ignores the trace
and emits the next `degree` `LineId`s from the demand line, plus, if useful, a
stride variant. The `Prefetcher` interface already supports a second class
(`prefetcher.h:74-92`), and the L2 neighbour prefetcher shows the shape
(`prefetcher.cpp:109-125`).
*Why:* without one, there is no honest in-model baseline to compare `next_burst`
against, and a cross-simulator comparison against actual gem5 numbers is not
credible given the different memory system. Fairness-critical for any claim of the
form "our prefetcher beats next-line".
*Effort:* 1 to 2 days including tests and a sweep config.

**S4. Charge a generation latency to prefetch issue.**
*What:* schedule the prefetch probe at `now + pf_latency` rather than at `now`
(`engine_core.cpp:371-373`), with a `prefetch_latency` knob defaulting to 1 to match
gem5's `latency` default (`Prefetcher.py:137`).
*Why:* wcache currently issues the prefetch in the same event as the demand, so
every prefetch is one cycle earlier than the equivalent gem5 prefetch. That is a
systematic bias in wcache's favor on the timely/late split. Fairness-critical if the
timely fraction is a headline number.
*Effort:* 4 to 6 hours.

### Optional improvements

**S5. Per-core scoping for the L2 prefetch tag set.**
*What:* make `l2_prefetched_` (`engine.h:637`) a per-core structure, or store the
issuing core with each tag, mirroring gem5's requestor scoping
(`base.hh:1260-1265`).
*Why:* today a demand from core A clears a tag set by core B's prefetch, crediting
`l2_pf_timely` across cores (`engine.cpp:417-424`). Small but real accounting
correctness.
*Effort:* 3 to 4 hours.

**S6. A bounded prefetch queue in front of the L1 port.**
*What:* buffer generated prefetches, issue them only when the L1 port has slack,
evict the oldest on overflow, and squash an entry when a demand for the same line
issues. This is gem5's `Queued` layer reduced to its two load-bearing parts
(`queued.cc:179-196, 487-534`).
*Why:* it removes the port-contention artifact the code already flags
(`engine_core.cpp:368-370`) and makes `l1_ii` sweeps interpretable. It also gives
two new stats analogous to `pfRemovedDemand` and `pfRemovedFull`.
*Effort:* 3 to 5 days. This is the largest item here and it touches the port
reservation path, so it needs care.

**S7. Prefetch-aware replacement insertion.**
*What:* thread the demand flag through `CacheLevel::install` (`cache_level.cpp:222`)
into `policy_->on_fill`, and give RRIP a distinct prefetch insertion RRPV.
*Why:* it fixes the `W_BELADY_PREFETCH` interaction properly (`config.cpp:706`) and
opens a knob the pollution stat already measures the need for
(`stats.cpp:333`). Note gem5 does not ship this, so it is an improvement over both,
not a fairness fix.
*Effort:* 1 to 2 days, mostly because `install`'s signature is load-bearing and the
policy interface is documented as exactly four verbs (`cache_level.cpp:253-258`).

**S8. An accuracy-driven throttle.**
*What:* gem5's formula (`queued.cc:160-167`) applied to the per-trigger burst count,
behind a knob defaulting to off, matching gem5's default of 0
(`Prefetcher.py:162`).
*Why:* low value while the address generator is an oracle, since there is little
inaccuracy to throttle. It becomes worth having only after S3 introduces a
predicting policy. Adding it would require relaxing the deliberate no-feedback
interface contract (`prefetcher.h:36-63`), which is a design decision for the human,
not a mechanical change.
*Effort:* 1 day for the mechanism, plus the interface decision.

**S9. Multi-prefetcher composition.**
*What:* a wrapper holding several `Prefetcher`s, round-robin over their issues,
mirroring `MultiPrefetcher` (`multi.cc:73-91`).
*Why:* only useful once more than one L1 policy exists (S3). Listed for
completeness; no value today.
*Effort:* 4 to 6 hours, after S3.

---

## 7. Sources

**gem5**
- Repository: https://github.com/gem5/gem5
- Branch: `stable`
- Commit: `f5c5a6e390f55dd5984977815bf9d0bd05da6945` (verified with `git rev-parse HEAD`
  in the clone)
- Obtained with
  `git clone --depth 1 --filter=blob:none --sparse --branch stable https://github.com/gem5/gem5`
  then `git sparse-checkout set src/mem/cache/prefetch src/mem/cache`
- Local checkout:
  `/tmp/claude-1690110567/-home-ya867177-neuro-cache-wcache/ea91e8f5-94a0-4994-b2b0-e1b38eb0cce5/scratchpad/gem5`
- Files read: `src/mem/cache/prefetch/{Prefetcher.py, base.cc, base.hh, queued.cc,
  queued.hh, tagged.cc, tagged.hh, stride.cc, stride.hh, multi.cc, multi.hh}` and
  `src/mem/cache/{base.cc, base.hh, cache_blk.hh}`, plus the header doc comments of
  the remaining policy files listed in section 3.10.

**wcache**, repository `/home/ya867177/neuro_cache-wcache`, branch
`wcache-rebuild-phase-a`, working tree as of 2026-09-22:
- `src/wcache/native/include/wcache/{prefetcher.h, config.h, engine.h, mshr.h,
  cache.h, types.h, layout.h, stamp_policy.h}`
- `src/wcache/native/src/{prefetcher.cpp, engine_core.cpp, engine.cpp,
  cache_level.cpp, mshr.cpp, stamp_policy.cpp, config.cpp, stats.cpp}`
- `src/cachesim/{hierarchy.h, main_hierarchical.cpp}`
- `log/2026-08-04-gem5-l2-cache-survey-plan.md` (plan only, never executed)

**Date of survey:** 2026-09-22.
