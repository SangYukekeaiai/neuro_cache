// Engine: the event loop, the six handlers, and the core state machine.
//
// Plan v3 Part 7, Phase C:
//
//   C2  "The seven event handlers; `retire`/`reinject` with the re-entry-level
//        rule (3.5)"
//   C3  "Tile barrier, `tile_origin`, core state machine: `core_line_done` /
//        `serve` / `E_Issue` of 3.4b, the self-timed recurrence, and the service
//        floor asserted rather than enforced (4.5, N14, N15)"
//   C4  "Two-valued inclusion: back-invalidation across L1s under `inclusive`,
//        and the `non_inclusive` path (N8, 4.4)"
//
// C1 is `cache_level.h` and C5 is `prefetcher.h`; this file is what joins them.
//
// The loop is 3.2 and nothing else:
//
//     while (!queue.empty()) { e = queue.pop_min(); now = e.time; dispatch(e); }
//
// There is no tick, no horizon, no scan over cores, and no condition
// re-evaluated on a schedule (D1). A stalled core has no scheduled event at all:
// it is referenced by the structure it waits on, and that structure schedules
// its wake-up (D2, P2).
//
// Determinism is a property of the key and of what this file refuses to iterate.
// 3.6's key is total -- `seq` is unique across the run, so no two events compare
// equal and the heap's internal arrangement is unobservable -- and every loop
// below walks a `std::vector` in index order. `MshrFile::entries_` is an
// `unordered_map` and is never iterated (decision B117); the back-invalidation
// scan of 4.4, the only O(cores) loop in the model, walks the L1 vector by core
// id. So no unspecified order reaches a victim choice, which matters because
// under LRU the service order IS the recency order (D7): one flipped tie leaves
// a different victim and every access after it diverges.
#pragma once

#include <cstdint>
#include <deque>
#include <memory>
#include <vector>

#include "wcache/cache_level.h"
#include "wcache/event.h"
#include "wcache/layout.h"
#include "wcache/mshr.h"
#include "wcache/prefetcher.h"
#include "wcache/trace.h"
#include "wcache/types.h"

namespace wcache {

// 4.4, N8. A knob and not an invariant: "inclusion has no job in this study",
// since weights are read-only and there are no invalidations to filter, so the
// tradeoff is effective capacity against guaranteed L2 hits on peer-L1-resident
// lines and it is a result to report. `exclusive` is not offered (G1, Q7).
enum class Inclusion : std::uint8_t { NonInclusive = 0, Inclusive = 1 };

// 3.3's `CoreState.phase`, the four states of the compute stage.
//
// A state field rather than a time field, which 2.1 argues at length: at the
// instant a core is refused you must record THAT it is stalled, and when it
// resumes is unknowable then. A single `ready_time` cannot express "waiting,
// resume time unknown", and that representational gap is what forced D2's
// polling. v3 removes `ready_time` outright.
enum class Phase : std::uint8_t { Computing = 0, Stalled = 1, AtBarrier = 2, Done = 3 };

// 3.3's `CoreState`, revised by v3: `ready_time` is gone.
//
// One cursor and one `pending_lines`, because the core has one burst in flight
// under EVERY policy (4.5). The second cursor lives in the prefetcher, on the
// other side of the L1 port, and keeping them in separate structs is not
// tidiness: it is the statement that the PE is unchanged, checkable by the fact
// that no field here mentions prefetching.
struct CoreState {
    std::int32_t tile = 0;

    // The ONE burst the core is on, in trace order, always.
    BurstIndex cursor{0};

    Phase phase = Phase::Done;

    // Lines of THIS burst still outstanding. N7: a burst is atomic, so the core
    // is served when the last of them lands and not before. I16 pairs it with
    // the phase: `pending_lines > 0 <=> phase == Stalled`.
    std::int32_t pending_lines = 0;

    // When the current burst was issued, for `fetch_latency` (Part 8).
    SimTime issued_at{0};

    // `served(c, cursor - 1)`. 3.3 gives it a NONE at a tile start; here that
    // state is spelled `cursor == 0` instead, and the two are the same state
    // because the cursor is reset at every tile start and advanced at every
    // service. One field carrying its own validity cannot disagree with a second
    // field that says whether it is valid (the shape decision B89 made
    // unrepresentable for `InsertResult::evicted`), and it is why the service
    // floor stops at the tile seam without anything having to clear it (4.5).
    SimTime served_time{0};
};

// The quantities Part 3's own pseudocode writes, and nothing else.
//
// Part 8 asks for far more than this -- occupancy histograms, per-bank
// utilisation, the timely/late/wasted/dropped prefetch split, the stall
// breakdown by cause -- and all of it is D2's ("Statistics and the results
// CSV"). What is here is the four counters the plan's pseudocode increments by
// name (`stats.core_stall`, `stats.fetch_latency`, `stats.back_invalidations`,
// `stats.pf_budget_exhausted`) plus the prefetch drop counts 4.6 asks to be
// "counted by reason", because the reason is only distinguishable at the moment
// of the drop and is gone afterwards.
struct EngineStats {
    // Per core. `core_stall[c] = sum over k of served(c, k) - want(c, k)`, the
    // cycles the core waited past its OWN self-timed schedule, which is the
    // quantity that integrates to the tile stretch (4.5, Part 8, V21).
    std::vector<std::int64_t> core_stall;

    // Per core. `fetch_latency[c] = sum over k of served(c, k) - issued_at(c, k)`,
    // the memory system's latency for the same bursts. With prefetching off the
    // two are equal by construction and reporting both is a free consistency
    // check; with it on, their DIFFERENCE is the latency the policy hid.
    std::vector<std::int64_t> fetch_latency;

    // 4.4's instrument, and C4's exit criterion is that it is 0 under
    // `non_inclusive`.
    std::int64_t back_invalidations = 0;

    // 4.6's `pf_budget_exhausted`, which says whether `prefetch_distance` or
    // `l1_mshrs` was the binding constraint (4.2).
    std::int64_t pf_budget_exhausted = 0;

    // 4.6's drops, by reason, indexed by TriageOutcome minus DroppedArrayHit.
    std::int64_t pf_dropped_array_hit = 0;
    std::int64_t pf_dropped_entry     = 0;
    std::int64_t pf_dropped_no_slot   = 0;
    std::int64_t pf_dropped_reserve   = 0;

    // Prefetch lines in flight, per core. I14's second half,
    // `pf_outstanding(c) <= l1_mshrs - l1_demand_reserve`. Held here rather than
    // in the prefetcher because it is a cache credit and not policy state (3.3's
    // `PrefetchState` is memory-side).
    std::vector<std::int32_t> pf_outstanding;
};

// What an event is about.
//
// One struct rather than a variant, in the tree's plain-struct style. Each kind
// reads one field and the rest are inert:
//
//   Issue            `burst`, plus the key's `core`
//   L1Probe/L2Probe  `req`
//   L1Fill/L2Fill    `entry`
//   Barrier          `tile`
//
// The core is read out of the KEY rather than duplicated here, because 3.6's key
// already carries `core_id` for every event and two spellings of one core id is
// one place for them to disagree. The barrier is the one event with no core;
// it is scheduled under `CoreId{0}` and nothing reads it, since only one barrier
// event exists per tile and there is no tie for it to break.
struct EventPayload {
    Request* req       = nullptr;
    Mshr*    entry     = nullptr;
    BurstIndex burst{0};
    std::int32_t tile  = 0;
};

using EngineQueue = EventQueue<EventPayload>;

// The knobs the engine reads.
//
// A plain struct with NO validation, deliberately. D1 owns "config load +
// validation, single source of truth for the parameter set" (Part 7), including
// every cross-field rule its row names: `lines_per_burst > l1_mshrs` throws,
// `inclusion = exclusive` is rejected, `core_accept_ii < 1` throws,
// `prefetch_policy = next_burst` with `prefetch_distance = 0` throws,
// `demand_reserve >= mshrs` throws, and a prefetch budget below
// `lines_per_burst` warns. Duplicating any of that here would be the second
// source of truth that row exists to prevent.
//
// What the constructors underneath still refuse are their own preconditions, and
// they are throws rather than asserts so they survive the sweep build's
// `-DNDEBUG`.
struct EngineParams {
    LevelParams l1;
    LevelParams l2;

    // 2.5b: its own knob, default 0, so D10's split between "the L2 MSHR frees"
    // and "the core finishes" stays structural and reopens by setting it
    // nonzero (Q3, closed).
    SimTime l2_to_l1_latency{0};

    // 2.4's memory channel. `ii = line_bytes / dram_bytes_per_cycle` is what
    // lets requests pipeline: a channel with 100 cycles of latency and an `ii`
    // of 2 has 50 requests in flight, and `ii = latency` recovers the
    // non-pipelined case from the same structure.
    SimTime dram_ii{1};
    SimTime l2_miss_latency{0};

    // 4.5, and its value is 1. In the config rather than the source for D8's
    // reason: a structural constant nobody can find is a structural assumption.
    // It is also the termination guard of 2.5b -- with `l1_latency = 0` an
    // all-hit chain runs inside one timestamp, and `max(gap_k, core_accept_ii)`
    // is the only thing advancing the clock.
    SimTime core_accept_ii{1};

    Inclusion inclusion = Inclusion::NonInclusive;

    PrefetchKind prefetch_policy   = PrefetchKind::None;
    std::int32_t prefetch_distance = 0;
};

class Engine final : public PrefetchIssuer {
public:
    // `mapper` and `trace` must outlive the engine. One mapper serves the whole
    // hierarchy (layout.h) and one trace serves the whole run.
    //
    // Throws whatever the level, policy, port and prefetcher constructors throw:
    // std::invalid_argument, naming the offending value.
    Engine(const AddressMapper& mapper, const TileTrace& trace, const EngineParams& params);

    // 3.2. Seeds the queue with tile 0 and runs until the queue is empty.
    //
    // Throws std::logic_error when the queue empties with work outstanding --
    // a core not Done, an MSHR still live, or a wait index still occupied.
    // D12 asks for exactly this and asks for a throw rather than an assert,
    // because the sweep build is `-DNDEBUG` and a deadlocked run that returns
    // quietly still produces numbers.
    void run();

    // Part 5's measured quantity, replacing the derived `tick_base`. Sized
    // `n_tiles + 1`, so the last entry is the end of the run and
    // `tile_origin[N+1] - tile_origin[N]` is tile N's length, which is the form
    // V1 checks against `mac_cycles[N]`.
    SimTime tile_origin(std::int32_t tile) const;

    const CoreState& core(CoreId c) const;
    const EngineStats& stats() const { return stats_; }
    const EngineQueue& queue() const { return queue_; }

    CacheLevel& l1(CoreId c);
    CacheLevel& l2() { return l2_; }
    const Prefetcher& prefetcher() const { return *prefetcher_; }

    // --- PrefetchIssuer (C5) -------------------------------------------------
    std::int32_t n_bursts_in_tile(CoreId core) const override;
    bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) override;

private:
    // --- the loop and the six handlers (C2) ----------------------------------
    void dispatch(const Event<EventPayload>& e);
    void on_issue(CoreId c, BurstIndex k, SimTime now);
    void on_l1_probe(Request& r, SimTime now);
    void on_l2_probe(Request& r, SimTime now);
    void on_l2_fill(Mshr& e, SimTime now);
    void on_l1_fill(Mshr& e, SimTime now);
    void on_barrier(std::int32_t tile, SimTime now);

    // 3.4's `reinject`: re-enter at `r.level`, through that level's PORT,
    // carrying the ORIGINAL refusal stamp (3.5, 3.8).
    void reinject(Request& r, SimTime now);

    // Reinjects a wake list in the order it was handed over, which is already
    // key order (3.4's merge and sort). Reservation order then equals key order,
    // which is I7b and is testable only at `ii >= 1` (4.3, N13).
    void reinject_all(std::vector<Request*>& wake, SimTime now);

    // 4.4's back-invalidation, under `inclusion == inclusive` only. The scan
    // covers all cores because the L2 is shared, which is why sharedness is the
    // reason the scan is wide and not the reason invalidation is needed at all.
    void back_invalidate(LineId line);

    // --- the core state machine (C3) -----------------------------------------
    void core_line_done(Request& r, SimTime now);
    void serve(CoreId c, SimTime now);
    void barrier_arrive(CoreId c, SimTime now);
    void start_tile(std::int32_t tile, SimTime now);

    // 4.5's `max(gap_k, core_accept_ii)`, the period from one service to the
    // next issue.
    SimTime step_after(CoreId c, std::int32_t tile, BurstIndex k) const;

    // --- request lifetime ----------------------------------------------------
    //
    // The plan does not say where a `Request` lives, and it has to live
    // somewhere stable: the wait indices, the target lists and `Request::mshr1`
    // all hold raw pointers into it (P5, mshr.h). A deque never moves what it
    // already holds, and a free list keeps a full-corpus run from growing one
    // request per line forever.
    //
    // A request reaches a terminal state at exactly three places and is released
    // at those three and nowhere else: an L1 array hit, a prefetch drop, and the
    // target loop of an L1 retire. Everything else -- merged, blocked at either
    // level, forwarded, a target of an L2 entry -- ends up in that same L1 retire.
    Request& acquire(CoreId c, LineId line, BurstIndex k, bool demand);
    void release(Request& r);

    const AddressMapper& mapper_;
    const TileTrace& trace_;
    EngineParams params_;

    // One per run, shared by both levels, because a request refused at the L1
    // and again at the L2 keeps its original stamp and so carries L2 seniority
    // reflecting how long it has genuinely waited (3.8). Declared before the
    // levels, which hold a reference to it.
    RefusalCounter counter_;

    std::vector<CacheLevel> l1_;
    CacheLevel l2_;
    Port dram_;

    std::unique_ptr<Prefetcher> prefetcher_;

    EngineQueue queue_;

    std::vector<CoreState> cores_;
    std::vector<SimTime> tile_origin_;

    // Part 5's countdown, not a scan: "each tile holds `cores_remaining`; a core
    // clearing the tile decrements it and parks in `AtBarrier`; the decrement
    // reaching zero schedules `E_Barrier`."
    std::int32_t cores_remaining_ = 0;

    EngineStats stats_;

    std::deque<Request> arena_;
    std::vector<Request*> free_;

    // Scratch, so no event handler allocates on a hot path. Separate buffers
    // rather than one shared: `lines_` is live across `E_Issue`'s scheduling
    // loop, and the prefetcher hook at the end of that handler reaches
    // `issue_prefetch`, which expands a second burst.
    std::vector<LineId> lines_;
    std::vector<LineId> pf_lines_;
    std::vector<Request*> granted_;
    RetireResult retire_;
};

// The one place a trace SPACING becomes a simulated duration.
//
// N12 asks that `SimTime` and `LocalTick` be mutually uncomparable, and they
// are: no operator compares them and nothing yields a `LocalTick` from a
// `SimTime`. What 4.5 needs is different, and it is a comparison of two
// DURATIONS rather than of two clocks: `max(gap_k, core_accept_ii)`, where
// `gap_k` is a difference of two ticks and `core_accept_ii` is a number of
// cycles. `SimTime{0} + d` is the crossing types.h already permits, used here
// with the origin that makes it the identity, and it is written once so the
// crossing is one reviewable site rather than a cast at every call.
constexpr SimTime as_duration(LocalTick d) { return SimTime{0} + d; }

}  // namespace wcache
