# 2026-09-22: what gem5 does when a demand lands on an in-flight prefetch

Status: source-read report. No code was changed to produce it. It answers one
question, "does gem5 upgrade a prefetch MSHR to a demand MSHR", and five
neighbouring cases (A, C, D, E, F) that bound the answer.

Provenance: gem5 stable, commit `f5c5a6e390f55dd5984977815bf9d0bd05da6945`,
sparse clone, read on 2026-09-22. Every gem5 `file:line` below was read from that
checkout. Every wcache `file:line` was read from the working tree of branch
`wcache-rebuild-phase-a` on the same day. Companion document:
`log/2026-09-22-l1-prefetch-vs-gem5-survey.md`, same commit, same date.

Relation to that survey, stated up front so the two do not appear to contradict
each other: the survey's section 4 row "Coalescing of prefetch onto in-flight"
says gem5 does not do it and cites `pfHitInMSHR`. That row is about the opposite
direction, a **prefetch** arriving and finding an existing MSHR, which gem5 drops
(`src/mem/cache/base.cc:966-971`). This document is about a **demand** arriving
and finding an existing **prefetch** MSHR, which gem5 does allow and does merge.
Both statements are true at the same commit; they describe different arrivals.

---

## 1. Short answer

gem5 merges the demand onto the in-flight prefetch's MSHR but does not upgrade
that MSHR in any sense: the demand is appended as an ordinary target hardcoded to
`Target::FromCPU` (`mshr.cc:412-413`), the MSHR's `order` is untouched (written
only at `mshr.cc:307` and `mshr.cc:625`), its `readyTime` and ready-list position
are unchanged because the entry already left the ready list at `markInService`
(`mshr_queue.cc:118`), the one call that would reprioritise it is commented out
with its reasoning in place (`base.cc:408`), and the downstream packet is never
rewritten and never looked like a prefetch on the wire in the first place, since
`createMissPacket` builds `ReadSharedReq`/`ReadCleanReq`/`ReadExReq`
(`cache.cc:550-553`), all of which are demand commands (`packet.hh:261-267`). The
consequence that matters for the paper is on the accounting side: because
`setPrefetched()` is gated on no CPU target having joined (`cache.cc:942-944`, and
`BaseCache::handleFill` never sets the bit at all), a prefetch consumed by a
coalescing demand leaves the block unmarked, so `pfUseful`, `pfUsefulButMiss` and
`pfUnused` all stay zero for it, while `pfLate` is a formula fed only by dropped
*new* prefetches (`prefetch/base.cc:163`) and never fires here either. The event
shows up only as an MSHR hit in the demand command's bucket (`base.cc:391`), and
since `incrDemandMhsrMisses` runs only on the no-MSHR branch (`base.cc:413-417`),
gem5's `coverage = pfUseful / (pfUseful + demandMshrMisses)` moves neither its
numerator nor its denominator: the whole event class is silently absent from
gem5's coverage number.

---

## 2. Case B timeline: a demand lands on an issued, in-flight prefetch MSHR

Base path for this section: `<gem5>/src/mem/cache/`. `<gem5>` is the checkout named
in section 6. Scenario: a hardware prefetch (`MemCmd::HardPFReq`) allocated an
MSHR, the MSHR was sent downstream (`inService == true`), and a demand `ReadReq`
or `WriteReq` for the same block now arrives from the CPU side.

| # | Event | Function | file:line | What state changes |
|---|---|---|---|---|
| B0 | Prefetch packet built | `Queued::DeferredPacket::createPkt` | `prefetch/queued.cc:63-72` | `RequestPtr` with flags `0` and `taskId(Prefetcher)`; `pkt = new Packet(req, MemCmd::HardPFReq)` at `:70`. `Request::PREFETCH` is **not** set. |
| B1 | Prefetch allocates an MSHR | `BaseCache::getNextQueueEntry` -> `allocateMissBuffer` | `base.cc:955`, `base.cc:987`, `base.hh:1175-1183` | Gated on `mshrQueue.canPrefetch() && !isBlocked()`. `mshrMisses[HardPFReq]` bumped at `base.cc:982`. `sched_send = false`. |
| B2 | MSHR fields set | `MSHR::allocate` | `mshr.cc:300-322` | `readyTime = when_ready` (`:306`), `order = _order` (`:307`), `isForward = false` (`:309`); first target added with `source = FromPrefetcher` (`:320-322`). |
| B3 | Queue insert | `MSHRQueue::allocate` | `mshr_queue.cc:62-80` | `readyIter = addToReadyList(mshr)`, sorted by `readyTime` only (`queue.hh:104-117`). |
| B4 | Sent downstream | `BaseCache::sendMSHRQueuePacket` -> `Cache::createMissPacket` | `base.cc:1930-1967`, `cache.cc:493-553` | New packet built at `cache.cc:553` with `cmd` from `cache.cc:550-551`, sharing the prefetch's `RequestPtr`. The `HardPFReq` command is gone on the wire. |
| B5 | markInService | `MSHRQueue::markInService` | `mshr_queue.cc:115-120` | `inService = true`; `readyList.erase(mshr->readyIter)` at `:118`. **The MSHR is no longer in the ready list at all.** |
| **B6** | **Demand arrives** | `BaseCache::recvTimingReq` | `base.cc:453-521` | `access()` returns false (block not in tags), `incMissCount` at `base.cc:1545`; takes the miss arm at `base.cc:511`. The `wasPrefetched()`/`clearPrefetched()` branch at `base.cc:503-507` is on the hit path and is not taken. |
| B7 | MSHR lookup | `Cache::handleTimingReqMiss` | `cache.cc:370`, forwarded at `cache.cc:415` | `mshrQueue.findMatch(blk_addr, ...)` finds the prefetch MSHR. Noncoherent twin at `noncoherent_cache.cc:124`. |
| B8 | Coalesce | `BaseCache::handleTimingReqMiss(pkt, mshr, ...)` | `base.cc:364-410` | `stats.cmdStats(pkt).mshrHits[requestorId]++` at `base.cc:391`, in the **demand** command's bucket. Then `allocateTarget(pkt, forward_time, order++, allocOnFill(pkt->cmd))` at `base.cc:400-401`. The `order++` is the cache-global counter and becomes the *target's* order, not the MSHR's. |
| B9 | Target appended (or deferred) | `MSHR::allocateTarget` | `mshr.cc:372-417` | Normal path: `targets.add(pkt, whenReady, _order, Target::FromCPU, !inService, alloc_on_fill)` at `:412-413`. `markPending` is `!inService`, i.e. false here. Deferral conditions at `:394-401`, see section 3.6. |
| B10 | Flags updated | `TargetList::add` -> `updateFlags` | `mshr.cc:159-182`, `mshr.cc:74-100` | Only `needsWritable`, `hasUpgrade`, `allocOnFill`, `hasFromCache` and the write bitmap are ORed in. No field records "a demand joined". |
| B11 | Targets-full check | `BaseCache::handleTimingReqMiss` | `base.cc:402-409` | `if (getNumTargets() >= numTarget)` -> `setBlocked(Blocked_NoTargets)`. The reprioritisation that would live here is commented out at `base.cc:408`. |
| B12 | Miss probe | `BaseCache::recvTimingReq` | `base.cc:513` -> `prefetch/base.cc:230-256` | `hasBeenPrefetched` is false (no block in tags yet, `base.hh:1257-1265`), so `pfUseful` (`prefetch/base.cc:251`) and `pfUsefulButMiss` (`:255`) do **not** move. |
| B13 | Response arrives | `BaseCache::recvTimingResp` | `base.cc:538-676` | `initial_tgt = mshr->getTarget()` (`base.cc:578`) is still the **prefetch** target, so `miss_latency` is measured from the prefetch's `recvTime` and billed to `mshrMissLatency[HardPFReq]` (`base.cc:586-587`). |
| B14 | Fill | `BaseCache::handleFill` | `base.cc:605-609`, `base.cc:1570-1662` | Block inserted. **`handleFill` never calls `setPrefetched()`** (grep-verified: the only two set sites are `cache.cc:943` and `noncoherent_cache.cc:315`). |
| B15 | Service targets | `Cache::serviceMSHRTargets` | `cache.cc:698-956` | `FromCPU` target sets `from_core = true` (`cache.cc:735-736`) and is satisfied from the block; `FromPrefetcher` target sets `from_pref = true` and is deleted with no response (`cache.cc:910-915`). Per-target `missLatency` uses the demand's own `target.recvTime` (`cache.cc:818-820`). |
| **B16** | **Prefetched-bit decision** | `Cache::serviceMSHRTargets` | `cache.cc:942-944` | `if (blk && !from_core && from_pref) blk->setPrefetched();` and `from_core` is true, so the block is **never marked** `wasPrefetched`. |
| B17 | Wrap up | `BaseCache::recvTimingResp` | `base.cc:637-665` | `promoteDeferredTargets()` and a fresh downstream request if anything was deferred, else `mshrQueue.deallocate(mshr)`. |

Note on B16 and the crux: the block's prefetched bit is the hinge on which every
prefetcher-side statistic turns, and in case B it is never set. `wasPrefetched` /
`clearPrefetched` / `setPrefetched` are at `cache_blk.hh:252-261`; the field is
`cache_blk.hh:508`.

---

## 3. Cases A, C, D, E, F

Base path for this section is also `<gem5>/src/mem/cache/`.

### 3.1 Case A: the demand arrives while the prefetch is still queued in `pfq`

The queued entry is **dropped outright**, deleted rather than converted into a
demand. `Queued::notify` squashes at the very top, before any new candidates are
computed: the guard `if (queueSquash)` is at `prefetch/queued.cc:180`, the match is
on block address plus secure flag, the packet is deleted, the node erased, and
`statsQueued.pfRemovedDemand++` runs at `prefetch/queued.cc:191`. The loop keeps
scanning, so every queued entry on that block is removed, not just the first.
`queue_squash` defaults to `True` (`prefetch/Prefetcher.py:144`).

Scope limit worth naming: the squash loop walks `pfq` only.
`pfqMissingTranslation`, the page-crossing entries awaiting a translation, is
**not** scanned, so an in-translation prefetch to the same block survives the
demand and is only re-checked when the translation completes
(`prefetch/queued.cc:319-338`).

Deduplication is a separate mechanism. `Queued::insert` checks `alreadyInQueue`
against both queues when `queue_filter` is set (`prefetch/queued.cc:388-399`); a
duplicate bumps `pfBufferHit` and, if the new priority is higher, raises the
existing entry's priority and bubbles it forward
(`prefetch/queued.cc:342-368`). **Unverified, code text read only:** in that
function the `for (it = queue.begin(); it != queue.end() && !found; it++)` loop
runs its `it++` on the matching iteration too, so `it` ends up one past the
matching entry and the priority bump appears to be applied to the following entry.
This looks like an upstream off-by-one. We verified the code text, not the intent,
and did not test it.

Pre-issue redundancy filters, three of them at three points:

1. At insert, only when `cache_snoop` is on (default false):
   `cache.inCache(...) || cache.inMissQueue(...)` drops the candidate with
   `pfInCache++` (`prefetch/queued.cc:457-464`).
2. At translation completion, the same test before the entry moves into `pfq`
   (`prefetch/queued.cc:319-338`).
3. At issue time inside the cache, after `getPacket()` already popped the entry and
   counted `pfIssued`: tags, then MSHR queue, then write buffer, each with its own
   stat (`base.cc:957-987`, increments at `:963`, `:969`, `:975`).

The prefetcher-visible accessors are `BaseCache::inCache` (`base.hh:1251`) and
`BaseCache::inMissQueue` (`base.hh:1267`), forwarded through `CacheAccessorImpl` at
`base.hh:332-343`. **`inWriteQueue` does not exist as an accessor in this tree**;
the write-buffer check lives only inline in `getNextQueueEntry`.

One more drop path for completeness: a full `pfq` evicts the lowest-priority,
oldest entry and counts `pfRemovedFull` (`prefetch/queued.cc:490-516`).

### 3.2 Case C: MSHR-queue priority, prefetch versus demand

A demand coalescing onto a prefetch-originated MSHR changes **none** of the three
things one might expect. It does not move the MSHR in the ready list, does not
change its `readyTime`, and does not change its `order`.

- Ready-list position is set only at insert, sorted by `readyTime` ascending, with
  ties going after existing equal entries, that is FIFO within a tick
  (`queue.hh:104-117`). `getNext` returns the front entry only once its `readyTime`
  has arrived (`queue.hh:221-229`). There is **no prefetch-versus-demand term
  anywhere in that ordering**.
- The only post-insert reorderings are `MSHRQueue::moveToFront`
  (`mshr_queue.cc:93-100`) and `MSHRQueue::delay` (`mshr_queue.cc:103-112`). Neither
  runs on the coalesce path; the one candidate call is commented out at
  `base.cc:408` with its reasoning intact:

```
base.cc:402                if (mshr->getNumTargets() >= numTarget) {
base.cc:403                    noTargetMSHR = mshr;
base.cc:404                    setBlocked(Blocked_NoTargets);
base.cc:405                    // need to be careful with this... if this mshr isn't
base.cc:406                    // ready yet (i.e. time > curTick()), we don't want to
base.cc:407                    // move it ahead of mshrs that are ready
base.cc:408                    // mshrQueue.moveToFront(mshr);
base.cc:409                }
```

- The MSHR's own `order` is written in exactly two places: `MSHR::allocate`
  (`mshr.cc:307`) and `MSHR::promoteDeferredTargets` (`mshr.cc:625`). The second
  runs only after a fill, on the re-issue path, never at coalesce time. `order` is
  consulted only for write-buffer conflict ordering (`base.cc:916-923`), never for
  ready-list position; it is declared at `base.hh:969-970`.
- Targets carry their own `const readyTime` and `const order`
  (`queue_entry.hh:91-92`), separate from the MSHR's.

Reserved entries, the real name and the real arithmetic. The gate is
`MSHRQueue::canPrefetch()` (`mshr_queue.hh:158-163`):

```
mshr_queue.hh:158    bool canPrefetch() const
mshr_queue.hh:159    {
mshr_queue.hh:160        // @todo we may want to revisit the +1, currently added to
mshr_queue.hh:161        // keep regressions unchanged
mshr_queue.hh:162        return (allocated < numEntries - (numReserve + 1 + demandReserve));
mshr_queue.hh:163    }
```

The MSHR queue is constructed with `reserve = 0` (`base.cc:87`), so `numEntries ==
mshrs`, and `demand_mshr_reserve` defaults to 1 (`Cache.py:102`). Concretely, a
prefetch may allocate only while `allocated < mshrs - 2`. The call site adds a
second condition: `mshrQueue.canPrefetch() && !isBlocked()` (`base.cc:955`), so a
cache blocked for any cause issues no prefetches at all.

**`demandLookupLatency`, or any latency-based demand reserve, does not exist in
this tree.** The only demand-side reserve is `demandReserve` /
`demand_mshr_reserve`.

### 3.3 Case D: which counters move

Covered in full by section 4's divergence discussion and section 5. In one line:
the demand is counted as an **MSHR hit** in its own command's bucket
(`base.cc:391`, rolled into `demandMshrHits` at `base.cc:2485` and
`overallMshrHits` at `base.cc:2491`); `demandMisses` also moves via `incMissCount`
(`base.hh:1271-1278`, called at `base.cc:1545`); and on the prefetcher side
`pfUseful`, `pfUsefulButMiss`, `pfUnused`, `pfLate`, `pfRemovedDemand`,
`demandMshrMisses`, `accuracy` and `coverage` all stay still.

The `CacheCmdStats` per-command split is total: `cmd(MemCmd::NUM_MEM_CMDS)` at
`base.cc:2339-2342`, indexed by `cmdStats(p)` at `base.hh:1050-1052`, so
`HardPFReq` has its own bucket entirely separate from `ReadReq` and `WriteReq`.
`SUM_DEMAND` and `SUM_NON_DEMAND` at `base.cc:2361-2369` define the rollups, and
`HardPFReq` sits in `SUM_NON_DEMAND`.

### 3.4 Case E: does the soft/hard prefetch split change the upgrade behaviour

**No.** There is no branch on the packet's prefetch-ness anywhere on the
`allocateTarget` path.

The command enum is at `packet.hh:97-101` and the attribute rows at
`packet.cc:104-116`:

```
packet.cc:104    /* SoftPFReq */
packet.cc:105    { {IsRead, IsRequest, IsSWPrefetch, NeedsResponse},
packet.cc:106            SoftPFResp, "SoftPFReq" },
packet.cc:107    /* SoftPFExReq */
packet.cc:108    { {IsRead, NeedsWritable, IsInvalidate, IsRequest,
packet.cc:109           IsSWPrefetch, NeedsResponse}, SoftPFResp, "SoftPFExReq" },
packet.cc:110    /* HardPFReq */
packet.cc:111    { {IsRead, IsRequest, IsHWPrefetch, NeedsResponse, FromCache},
packet.cc:112            HardPFResp, "HardPFReq" },
```

`SoftPFExReq` alone carries `NeedsWritable` plus `IsInvalidate`. `HardPFReq` alone
carries `FromCache`, and it is the only command for which `mustCheckAbove()` is
true (`packet.hh:1425-1428`). None of the three is a demand: `MemCmd::isDemand()`
lists only `ReadReq`, `WriteReq`, `WriteLineReq`, `ReadExReq`, `ReadCleanReq` and
`ReadSharedReq` (`packet.hh:261-267`).

Origin differs. A soft prefetch is a core instruction: `Request::PREFETCH =
0x01000000` and `PF_EXCLUSIVE = 0x02000000` (`request.hh:164-167`), tested by
`isPrefetch()` / `isPrefetchEx()` (`request.hh:1028-1033`), and `makeReadCmd`
turns them into `SoftPFExReq` or `SoftPFReq` (`packet.hh:992-1010`). A hard
prefetch is built inside the cache and hardcoded: `prefetch/queued.cc:70` and
`prefetch/fdp.cc:249`.

Every site in `src/mem/cache/` that branches on soft or hard:

| site | what it does |
|---|---|
| `prefetch/base.cc:238` | `if (pkt->cmd.isSWPrefetch()) return;`, so the prefetcher ignores SW prefetches entirely: no training, no `pfUseful` |
| `prefetch/bop.cc:330` | `if (!pkt->cmd.isHWPrefetch()) return;`, so BOP's `notifyFill` reacts only to HW prefetch fills |
| `prefetch/queued.cc:70`, `prefetch/fdp.cc:249` | construct the `HardPFReq` packet |
| `base.cc:2368-2369` | `SUM_NON_DEMAND` groups all three PF commands |
| `cache.cc:381` | `if (pkt->cmd.isSWPrefetch())` in `Cache::handleTimingReqMiss`: a SW prefetch gets an immediate dummy response to the core, and if an MSHR already exists the prefetch is dropped entirely |
| `cache.cc:744` | `if (tgt_pkt->cmd.isSWPrefetch())` in `serviceMSHRTargets`, for exclusive-copy and dirty handling for `SoftPFExReq` |
| `cache.cc:911` | `assert(tgt_pkt->cmd == MemCmd::HardPFReq);` in the `FromPrefetcher` target arm |
| `cache.cc:1176`, `cache.cc:1398` | comments only |
| `cache.cc:1429` | `if (tgt_pkt->cmd == MemCmd::HardPFReq && forwardSnoops)`, snoop forwarding upward for HW prefetches |
| `mshr.cc:320-321` | `source = (target->cmd == MemCmd::HardPFReq) ? FromPrefetcher : FromCPU` in `MSHR::allocate`, first target only |
| `mshr.cc:378` | `assert(pkt->cmd != MemCmd::HardPFReq);`, the first line of `MSHR::allocateTarget` |
| `noncoherent_cache.cc:298` | the same `HardPFReq` assert in its `FromPrefetcher` arm |

Not one of those sits on the append-or-defer decision. The decision branches only
on cache maintenance, deferred-list state, post-invalidate and `needsWritable`
(`mshr.cc:394-401`), and both arms hardcode `Target::FromCPU` (`mshr.cc:405-406`
and `:412-413`). The PF-ness of the existing first target matters only on the fill
side, where `FromPrefetcher` means "delete the packet instead of responding"
(`cache.cc:910-915`) and gates `setPrefetched()` (`cache.cc:942-944`).

A per-prefetcher difference worth recording: `Request::PREFETCH` is **not** set by
the `Queued` prefetcher on the request that goes downstream
(`prefetch/queued.cc:63-72` constructs it with flags `0`; the flag appears only on
the separate *translation* request at `prefetch/queued.cc:383`), but FDP **does**
set it, at `prefetch/fdp.cc:240`, guarded on its `markReqAsPrefetch` parameter. So
"a hardware prefetch carries no `Request::PREFETCH`" is true of the `Queued` base
path and false of FDP.

### 3.5 Case F: the corner where the demand cannot simply be added

A demand that reaches `BaseCache::recvTimingReq` is **always absorbed**: never
NACKed, never rejected mid-flight. Both the MSHR-full and the targets-full
conditions are detected *after* the current packet has been accepted, and they
block the CPU-side port so the *next* request is refused.

- Rejection happens only in `BaseCache::CpuSidePort::tryTiming`
  (`base.cc:2607-2636`), which returns false when `blocked || mustSendRetry` was
  already true before this packet arrived. `recvTimingReq` returns false only via
  that path.
- A retry is guaranteed once the cause clears: `clearBlocked` reschedules
  `sendRetryEvent` when `mustSendRetry` is set (`base.cc:152-186`). The block mask
  is per cause (`base.hh:1208-1234`).
- The three blocked causes: `Blocked_NoMSHRs`, `Blocked_NoWBBuffers`,
  `Blocked_NoTargets` (`base.hh:119-125`).
- Targets-full is detected **after** the append, with `>=`: `allocateTarget` runs
  at `base.cc:400-401` and only then `if (mshr->getNumTargets() >= numTarget)` at
  `base.cc:402`. So the MSHR fills to exactly `numTarget` and the cache blocks.
  Unblocking happens on that MSHR's response (`base.cc:573-576`). The snoop path
  deliberately over-allocates and only warns (`cache.cc:1302-1303`).
- MSHR-full is the same shape, allocate then test: `allocateMissBuffer` allocates
  and only then checks `mshrQueue.isFull()` (`base.hh:1175-1183`). Unblock at
  `base.cc:653-657` and `base.hh:418-426`.

The full deferral condition, quoted:

```
mshr.cc:394      PacketPtr tgt_pkt = targets.front().pkt;
mshr.cc:395      if (pkt->req->isCacheMaintenance() ||
mshr.cc:396          tgt_pkt->req->isCacheMaintenance() ||
mshr.cc:397          !deferredTargets.empty() ||
mshr.cc:398          (inService &&
mshr.cc:399           (hasPostInvalidate() ||
mshr.cc:400            (pkt->needsWritable() &&
mshr.cc:401             (!isPendingModified() || hasPostDowngrade() || isForward))))) {
mshr.cc:402          // need to put on deferred list
mshr.cc:403          if (inService && hasPostInvalidate())
mshr.cc:404              replaceUpgrade(pkt);
mshr.cc:405          deferredTargets.add(pkt, whenReady, _order, Target::FromCPU, true,
mshr.cc:406                              alloc_on_fill);
mshr.cc:407      } else {
mshr.cc:412          targets.add(pkt, whenReady, _order, Target::FromCPU, !inService,
mshr.cc:413                      alloc_on_fill);
mshr.cc:414      }
```

**`markFullyPending` does not exist in this tree.** The nearest analogues are
`MSHRQueue::markPending` (`mshr_queue.cc:123`) and the `markPending` boolean
argument to `TargetList::add` (`mshr.cc:159-182`), which only sets
`downstreamPending` on an enclosing upstream MSHR.

### 3.6 The writable-demand-on-a-read-only-prefetch case, in full

This is the one sub-case that looks like an upgrade and is not. A plain
`HardPFReq` leaves `targets.needsWritable == false`, so at `markInService`
`pendingModified` is false (`mshr.cc:344`), so `isPendingModified()` is false, so
the predicate at `mshr.cc:400-401` is true and the demand goes to
`deferredTargets` (`mshr.cc:405-406`).

gem5 does **not** re-send or upgrade the outstanding downstream request. There is
no code path that rewrites an in-flight packet's command. What happens instead:

- If the fill comes back writable anyway, `recvTimingResp` splices the deferred
  targets in with `promoteWritable` (`base.cc:629-635`, `mshr.cc:676-702`), no
  re-issue.
- Otherwise the remaining deferred targets are promoted and the MSHR is re-issued
  as a **fresh** downstream request built by `createMissPacket` from the
  now-promoted front target (`mshr.cc:592-630`, `base.cc:641-648`).

`replaceUpgrade` (`mshr.cc:185-215`) rewrites only *target* packets and only on the
deferral path when `hasPostInvalidate()`; it never touches the outstanding
downstream packet.

### 3.7 Correcting the field name the question presupposed

**`hasFromCPU` does not exist in this tree.** `grep -rn "hasFromCPU" src/mem/`
returns nothing. The real `TargetList` flag fields are, read directly off
`mshr.hh:173-181`:

```
mshr.hh:173        bool needsWritable;
mshr.hh:174        bool hasUpgrade;
mshr.hh:175        /** Set when the response should allocate on fill */
mshr.hh:176        bool allocOnFill;
mshr.hh:177        /**
mshr.hh:178         * Determine whether there was at least one non-snooping
mshr.hh:179         * target coming from another cache.
mshr.hh:180         */
mshr.hh:181        bool hasFromCache;
```

plus the private `canMergeWrites` and `writesBitmap`. All four are computed in
`updateFlags` (`mshr.cc:74-100`), which explicitly excludes `FromPrefetcher` from
`hasFromCache` and the write-merge state at `mshr.cc:96`. So there is no
TargetList-level record of "a CPU target joined"; that question is answered only by
the local `bool from_core` inside `serviceMSHRTargets` (`cache.cc:712`,
`noncoherent_cache.cc:248`). There is likewise **no `MSHR::isPrefetch()`** anywhere
in `mshr.hh`, `mshr.cc` or `queue_entry.hh`.

---

## 4. Upgrade behaviour: gem5 versus wcache

gem5 paths in this table are relative to `<gem5>/src/mem/cache/`; wcache paths are
relative to `/home/ya867177/neuro_cache-wcache/src/wcache/native/`.

| aspect | gem5 | wcache |
|---|---|---|
| Can a demand merge onto an in-flight prefetch entry | Yes. `mshrQueue.findMatch` finds it (`cache.cc:370`) and `allocateTarget` appends (`mshr.cc:412-413`) | Yes. A demand on a prefetch-opened entry is an ordinary secondary miss, `add_target` -> `TriageOutcome::Merged` (`src/cache_level.cpp:174-179`) |
| Can a prefetch merge onto an existing entry | Never. `assert(pkt->cmd != MemCmd::HardPFReq)` (`mshr.cc:378`); the prefetch was already dropped at issue with `pfHitInMSHR` (`base.cc:966-971`) | Never. A prefetch hitting any entry is dropped as `DroppedEntry` (`src/cache_level.cpp:168`); queueing is a hard error (`src/mshr.cpp:168-184`) |
| Is any entry field mutated on the merge | No field on the MSHR changes. Only the TargetList ORs move: `needsWritable`, `hasUpgrade`, `allocOnFill`, `hasFromCache` (`mshr.cc:74-100`) | Exactly one field changes: `e.demand = e.demand \|\| r.demand` (`src/mshr.cpp:164`). Nothing is cleared (contract at `include/wcache/mshr.h:416-425`) |
| Is the entry's issue order or priority changed | No. `order` written only at `mshr.cc:307` and `mshr.cc:625`; `moveToFront` commented out at `base.cc:408` | No equivalent concept: there is no ready list and no per-entry order |
| Is the entry's ready time or list position changed | No. It left the ready list at `markInService` (`mshr_queue.cc:118`); ordering is by `readyTime` only, with no prefetch-versus-demand term (`queue.hh:104-117`) | No. Nothing downstream is re-issued: "A secondary miss: no downstream traffic" (`src/cache_level.cpp:170-171`) |
| Is the downstream request rewritten or re-issued | No. It was already `ReadSharedReq`/`ReadCleanReq`/`ReadExReq` (`cache.cc:550-553`), all demand commands (`packet.hh:261-267`) | No. There is no downstream packet to rewrite |
| Does the prefetch origin survive the merge | Only as the first target's `const Source source == FromPrefetcher` (`mshr.hh:140`, set at `mshr.cc:320-322`) | Yes, explicitly. `pf_opened` is written once at allocate and never again (`src/mshr.cpp:144`, comment at `:141-143`) |
| Writable demand on a read-only prefetch entry | Deferred, not upgraded (`mshr.cc:400-406`); resolved by `promoteWritable` (`mshr.cc:676-702`) or by a fresh downstream request after the fill (`mshr.cc:592-630`, `base.cc:641-648`) | No coherence dimension in the model, so no analogue |
| Latency anchor for the merged demand | Split. `mshrMissLatency` is billed against the **prefetch's** `recvTime` via `initial_tgt` (`base.cc:578`, `:586-587`); the per-target `missLatency` uses the demand's own `recvTime` (`cache.cc:818-820`) | Single anchor, the prefetch's issue time: `core_line_done(*t, now, pf_opened ? first_request : t->issued_at)` (`src/engine.cpp:616`) |
| Is the event counted at all | As an MSHR hit in the demand's command bucket (`base.cc:391` -> `demandMshrHits`, `base.cc:2485`). Nothing on the prefetcher side | As `pf_late` at fill, when `pf_opened && demand` (`src/engine.cpp:571-573`) |
| Is there a distinct outcome code for it | No | No. `TriageOutcome::Merged` covers both a merge onto a prefetch-opened entry and a merge onto a demand entry, and triage increments no stats |
| Does the filled block get marked as prefetched | **No.** `handleFill` never sets the bit; the two set sites are guarded by `!from_core` (`cache.cc:942-944`, `noncoherent_cache.cc:314-316`), and the merged demand makes `from_core` true (`cache.cc:736`) | Not applicable at L1: there is no prefetched bit in the tag or line struct. The marker lives on the MSHR entry as `pf_opened`. L2 uses a separate `l2_prefetched_` set (`include/wcache/engine.h:637`, insert `src/engine.cpp:506`, erase `:422`) |
| Does the merged demand count as a cache hit | No: it took the miss arm, `incMissCount` at `base.cc:1545` | No: `++stats_.l1_accesses` for every demand regardless of triage outcome, but `l1_hits` only on `TriageOutcome::Hit` (`src/engine.cpp:270-271`). There is no MSHR-hit counter at all |
| Prefetch admission gate | `canPrefetch()`: `allocated < numEntries - (numReserve + 1 + demandReserve)` (`mshr_queue.hh:158-163`), plus `!isBlocked()` (`base.cc:955`) | `has_slot`: `is_prefetch_at_issue(r) ? free > demand_reserve_ : free > 0` (`src/mshr.cpp:114`), discriminator at `include/wcache/mshr.h:299-301` |

---

## 5. Divergences that affect the paper's late-prefetch and coverage accounting

These are the points where a number printed by wcache and a number printed by gem5
carry different meanings, in descending order of how much a reviewer would care.

### 5.1 gem5 has no late-prefetch counter at all, and `pfLate` is not one

`pfLate` is a **Formula**, not a counter: `pfLate = pfHitInCache + pfHitInMSHR +
pfHitInWB` (`prefetch/base.cc:163`), declared at `prefetch/base.hh:370`. Its three
inputs have exactly three increment sites in the whole of `src/mem/`, all inside
`BaseCache::getNextQueueEntry`, where a **newly generated prefetch packet** is
thrown away because the line is already in tags, already has an MSHR, or is in the
write buffer (`base.cc:963`, `:969`, `:975`). That is the prefetch-arrives-second
direction. Case B is the demand-arrives-second direction, and `pfLate` does not
move for it.

wcache's `pf_late` is the opposite: it counts exactly the case B event, at fill,
when the entry was opened by a prefetch and a demand later promoted it
(`src/engine.cpp:571-573`, definition `include/wcache/engine.h:207`, L2 twin
`engine.h:254` incremented at `src/engine.cpp:510`). **The two statistics share a
name and count disjoint event classes.** Any table putting them in the same column
is wrong. This is the single most important thing for the paper to state.

### 5.2 The coalesced prefetch is accounted as neither useful, nor unused, nor late

The chain, all read off source: the demand is appended as `FromCPU`
(`mshr.cc:412-413`); at fill `serviceMSHRTargets` sets `from_core = true`
(`cache.cc:736`) and `from_pref = true` (`cache.cc:912`); `setPrefetched()` requires
`!from_core` (`cache.cc:942-944`), so it is skipped; `BaseCache::handleFill` never
sets the bit either (only two set sites exist, `cache.cc:943` and
`noncoherent_cache.cc:315`). Therefore:

- `pfUseful` and `pfUsefulButMiss` do not move, now or ever for this block, because
  `hasBeenPrefetched` needs the bit (`base.hh:1257-1265`, increments at
  `prefetch/base.cc:251` and `:255`).
- A *later* demand hitting the same block also gets no `pfUseful` credit: the bit
  is clear.
- On eviction, `invalidateBlock` checks the bit before calling `prefetchUnused()`
  (`base.cc:1729-1732`), so `pfUnused` does not move either.

Inferred consequence: in gem5, a prefetch that was genuinely correct but arrived
late is invisible to every prefetcher-side statistic. It is not just miscounted, it
is absent from both the numerator and the denominator of accuracy
(`prefetch/base.cc:158`).

### 5.3 gem5's coverage silently drops the whole event class

`coverage = pfUseful / (pfUseful + demandMshrMisses)` (`prefetch/base.cc:161`).
`incrDemandMhsrMisses()` has one call site and it is on the **no-MSHR** branch:

```
base.cc:412    } else {
base.cc:413        // no MSHR
base.cc:414        assert(pkt->req->requestorId() < system->maxRequestors());
base.cc:415        stats.cmdStats(pkt).mshrMisses[pkt->req->requestorId()]++;
base.cc:416        if (prefetcher && pkt->isDemand())
base.cc:417            prefetcher->incrDemandMhsrMisses();
```

In case B an MSHR *is* found, so that branch is not taken. Combined with 5.2, the
coalescing demand bumps neither the numerator (`pfUseful`) nor the denominator
(`demandMshrMisses`). The event vanishes from gem5's coverage.

This is the headline divergence. wcache's `pf_coverage` uses `pf_timely + pf_late`
over a per-burst denominator (`src/stats.cpp:328`, emitted at `:311` and `:328`),
so it *includes* the late-but-correct prefetches that gem5 excludes by
construction. Inferred consequence: wcache's coverage will read systematically
higher than a gem5 coverage computed on the same traffic, by roughly the late
fraction, and none of that gap is a prefetcher result. This compounds the
denominator mismatch already recorded as S2 in the companion survey.

### 5.4 A latency-accounting hazard in gem5 that will bite any comparison

`BaseCache::recvTimingResp` bills the miss latency against `initial_tgt->pkt`:

```
base.cc:577    // Initial target is used just for stats
base.cc:578    const QueueEntry::Target *initial_tgt = mshr->getTarget();
base.cc:579    const Tick miss_latency = curTick() - initial_tgt->recvTime;
...
base.cc:586        stats.cmdStats(initial_tgt->pkt)
base.cc:587            .mshrMissLatency[pkt->req->requestorId()] += miss_latency;
```

The initial target is the `HardPFReq`, so the whole interval lands in
`mshrMissLatency[HardPFReq]`, which rolls into `overallMshrMissLatency`
(`base.cc:2515-2516`) but **not** into `demandMshrMissLatency` (`base.cc:2509`,
`SUM_DEMAND` at `base.cc:2361-2365`). Meanwhile the demand contributed a *count* to
`demandMshrHits` (`base.cc:391`, rollup `base.cc:2485`). So in gem5 a case B demand
adds a count to one demand rollup and zero ticks to the demand latency rollup, and
the ticks it did cost appear under a prefetch command. Anyone computing average
demand MSHR latency from gem5 stats on a prefetching configuration is reading a
number with these events removed.

wcache does the opposite and does it deliberately: the burst's completion is
credited from `first_request`, the prefetch's issue time
(`src/engine.cpp:616`), which is preserved precisely because `pf_opened` and
`first_request` are never rewritten on promotion (`src/mshr.cpp:141-144`). The two
simulators therefore attribute the same physical interval to different places.

### 5.5 Smaller items

- **No distinct "merged onto a prefetch entry" outcome on either side.** gem5 has
  no such counter (see 5.1); wcache's `TriageOutcome::Merged` covers both a merge
  onto a `pf_opened` entry and a merge onto a demand entry, and triage increments
  no statistics. Both simulators recover the distinction only at fill time, gem5
  not at all and wcache through `pf_opened && demand`.
- **`pf_useful` and `pf_unused` do not exist in wcache.** A grep returns nothing;
  they are gem5-only names. wcache's nearest counters are `pf_timely`
  (`src/engine.cpp:635`, a demand hit to a still-resident prefetched line) and
  `pf_wasted` (`src/engine.cpp:656`, `:669`). Do not map the names across.
- **`pf_dropped_targets_full` is structurally zero in wcache**, because a prefetch
  is dropped on finding any matching entry before the target bound is consulted
  (`src/cache_level.cpp:168` versus `:183-186`). gem5's equivalent situation blocks
  the port instead (case F).

---

## 6. Sources

**gem5**

- Repository: https://github.com/gem5/gem5
- Branch: `stable`
- Commit: `f5c5a6e390f55dd5984977815bf9d0bd05da6945`
- Obtained with
  `git clone --depth 1 --filter=blob:none --sparse --branch stable https://github.com/gem5/gem5`
  then `git sparse-checkout set src/mem/cache/prefetch src/mem/cache`
- Local checkout:
  `/tmp/claude-1690110567/-home-ya867177-neuro-cache-wcache/ea91e8f5-94a0-4994-b2b0-e1b38eb0cce5/scratchpad/gem5`
- Files read: `src/mem/cache/{base.cc, base.hh, cache.cc, noncoherent_cache.cc,
  mshr.cc, mshr.hh, mshr_queue.cc, mshr_queue.hh, queue.hh, queue_entry.hh,
  cache_blk.hh, Cache.py}`, `src/mem/cache/prefetch/{base.cc, base.hh, queued.cc,
  queued.hh, fdp.cc, bop.cc, Prefetcher.py}`, and `src/mem/{packet.cc, packet.hh,
  request.hh}`.

**wcache**

- Repository: `/home/ya867177/neuro_cache-wcache`, branch `wcache-rebuild-phase-a`,
  working tree as of 2026-09-22.
- Files read: `src/wcache/native/include/wcache/{mshr.h, engine.h}` and
  `src/wcache/native/src/{mshr.cpp, cache_level.cpp, engine.cpp, stats.cpp}`.

**Cite corrections made while writing this document.** The three investigation
notes this report was assembled from disagreed with the source, or with each
other, at six places. In each case the source was re-read and the source value is
what appears above:

| claim | note said | source says |
|---|---|---|
| `if (source != Target::FromPrefetcher)` in `updateFlags` | `mshr.cc:94` in one quoted block, `mshr.cc:96` in the same note's table | `mshr.cc:96` |
| `readyList.erase(mshr->readyIter)` in `MSHRQueue::markInService` | `mshr_queue.cc:119` | `mshr_queue.cc:118` |
| `if (mshr->getNumTargets() >= numTarget)` | `base.cc:401` | `base.cc:402` (the `allocateTarget` call is `base.cc:400-401`) |
| `TargetList` flag fields | `mshr.hh:180-188` | `mshr.hh:173-181` |
| `order = targets.front().order` in `promoteDeferredTargets` | `mshr.cc:626` | `mshr.cc:625` |
| `MemCmd::isDemand()` | `packet.hh:261-268` / `packet.hh:262-268` | `packet.hh:261-267` |

**Carried forward, not found in this tree:** `hasFromCPU`, `markFullyPending`, an
`inWriteQueue` accessor, `demandLookupLatency`, and `MSHR::isPrefetch`.

**Out of scope:** Ruby (`src/mem/ruby/`) was not examined; all cites are the
classic memory system. Atomic and functional access paths (`recvAtomic`,
`functionalAccess`) were not traced; case B as stated is timing mode. A full
snoop-race analysis of a prefetch MSHR that has acquired a demand target was not
done.

**Date:** 2026-09-22.
