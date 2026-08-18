# 2026-08-04 gem5 L2 Cache Survey Plan

Status: DRAFT, awaiting review. Nothing has been executed yet (gem5 not
yet cloned, no survey started). This plan follows
`log/2026-08-03-l1-l2-cache-policy-plan.md` (COMPLETE), which built this
repo's own two-level L1/L2 replay engine (`src/cachesim/hierarchy.h`,
`cache.h`) as a **tick-atomic, functional (non-timing) replay model**: no
ports, no MSHRs, no per-cycle contention -- every L1-missed core's L2
lookup within a tick is resolved against a snapshot, with no notion of a
request queue or limited concurrency at the L2.

## Goal

Survey how gem5 models its classic (non-Ruby) L2 cache -- structural
parameters and, specifically, how it handles multiple concurrent
requests arriving from L1 (ports, MSHRs, blocking/non-blocking
behavior) -- and use that as a reference point to decide whether/how to
add a bounded-concurrency model on top of this repo's existing
tick-atomic L2, trading added realism against replay speed and
implementation cost. The output is a design decision, not a full
gem5-fidelity reimplementation: this project's cache is a **read-only,
weight-streaming cache** (no writebacks, no coherence, no dirty state),
which is a strictly simpler problem than gem5's general-purpose
read/write coherent cache, so most of gem5's machinery (coherence
protocol, write-back paths, snooping) is expected to be irrelevant and
should be explicitly marked out-of-scope rather than ported.

## Standing requirement: every finding cites its source

Every claim made in the survey output about how gem5 works must be
tied to a specific file/line (or file + function name) in the cloned
gem5 source, not stated from general recollection. Same discipline for
checkpoint 3's cross-reference half: every "this maps to our code"
claim cites the matching `src/cachesim/*` file/line. A finding with no
locatable source reference doesn't go in the survey note; it gets
flagged as unverified instead.

## Checkpoints (rephrased from the original ask)

1. **Structural parameters and concurrent-request handling.** For
   gem5's classic `Cache` SimObject: capacity, associativity, and --
   the part most relevant to us -- how it services multiple
   simultaneous read requests arriving from L1 (or from multiple L1s,
   in a multi-core config). Concretely: what a "port" is in gem5's
   memory system, how MSHRs (Miss Status Handling Registers) let a
   nominally single-port cache stay non-blocking under several
   in-flight misses, and what limits exist (`mshrs`, `tgts_per_mshr`,
   `write_buffers` params) that would cap how many concurrent L1 misses
   an L2 can actually track before it stalls upstream requesters. This
   is the mechanism our tick-atomic snapshot model currently has no
   analogue for.
2. **A reference point for "what counts as a good L2 hit rate."** Not
   a gem5-specific number (hit rate is workload-dependent), but what
   gem5's own example/default configs and commonly-cited results treat
   as typical L2 sizing and hit-rate ranges, to sanity-check our
   read-only weight-cache hit rates against a known general-purpose
   baseline -- while being explicit in the writeup that the comparison
   is qualitative (different traffic pattern entirely) rather than a
   target to hit.
3. **Scope filter for our own model.** Given the read-only,
   no-coherence nature of this project's cache, explicitly classify
   each gem5 mechanism found in (1) as: *relevant and portable*
   (e.g. bounded concurrent-miss tracking, port contention), *relevant
   but needs adaptation* (e.g. MSHR target-merging doesn't apply the
   same way to pure reads), or *irrelevant, skip* (coherence protocol,
   dirty writeback, snooping, MOESI states). This filtered list is the
   actual deliverable driving what gets added to `hierarchy.h`.

## Search contents (what will actually be checked, and how)

Clone gem5 locally first (`https://github.com/gem5/gem5`, shallow
clone) so the checkpoints above are answered from source, not from
memory or secondary summaries. Planned to check, in order, each with
its exact file/function cited in the survey output:

1. **SimObject parameter definitions** -- `src/mem/cache/Cache.py` (or
   `BaseCache.py` depending on gem5 version) for the declared params:
   `size`, `assoc`, `tag_latency`, `data_latency`, `response_latency`,
   `mshrs`, `tgts_per_mshr`, `write_buffers`, `mshr_latency`. This
   answers checkpoint 1's "size/associativity/ports" part directly from
   the param list and its doc comments.
2. **MSHR implementation** -- `src/mem/cache/mshr.hh` / `mshr.cc` and
   `src/mem/cache/base.cc` (`BaseCache::allocateMissBuffer`,
   `handleFill`, the blocking/non-blocking request path). This is where
   "how does gem5 deal with multiple reads arriving before earlier ones
   resolve" actually lives -- need to read how a second request to an
   already-pending line merges into an existing MSHR versus how a
   request to a *different* line queues when all MSHR slots are full.
3. **Port model** -- `src/mem/port.hh` and how `CpuSidePort` /
   `MemSidePort` are wired in `src/mem/cache/base.hh`, specifically
   whether/how many requests can be outstanding on one port
   simultaneously (this is what "multiple reads from L1" resolves to
   structurally: one port object, concurrency handled by MSHRs behind
   it, not by multiple physical ports).
4. **Typical example configs** -- `configs/common/Caches.py` (the
   `L1Cache`/`L2Cache` example classes with their default `size`,
   `assoc`, `mshrs`, `tgts_per_mshr` values used across gem5's SE-mode
   example scripts) as the "what does a normal gem5 run actually use"
   reference for checkpoint 1, and any hit-rate numbers reported in
   gem5's own documentation/regression outputs or standard
   architecture references for checkpoint 2 (flagged as a rough,
   workload-dependent sanity range, not a target, and cited to whatever
   doc/file it came from).
5. **Cross-reference against our code** -- `src/cachesim/hierarchy.h`,
   `cache.h`, `config.h`/`config.py` to produce the concrete "what, if
   anything, changes here" list called for in checkpoint 3, each item
   citing both the gem5 source location and the matching (or missing)
   `src/cachesim` location.

## Deliverable

A survey note (via `/unarylab-research:obsidian-survey`, filed to the
vault as usual) covering the above, ending in a short, explicit
recommendation: which gem5 mechanisms to adapt into
`src/cachesim/hierarchy.h`, which to skip and why, and the expected
performance/accuracy tradeoff of each adaptation -- not an
implementation. Implementation would be a separate, later plan.

## Explicitly out of scope for this survey

- Ruby (gem5's detailed coherence-protocol memory system) -- classic
  `Cache` is the relevant comparison since our cache has no coherence
  protocol at all.
- Any write-back / dirty-data / eviction-to-memory path -- this
  project's cache never writes.
- Prefetcher variety beyond what's needed to sanity-check our existing
  single-block cout-prefetch (already implemented per the 08-03 plan).

## Status / next step

Confirmed by user 2026-08-04: checkpoints and search-content list
approved, with the added standing requirement above (every finding
cited to a specific file/line). Next step: clone gem5 locally and run
the survey via `/unarylab-research:obsidian-survey`.
