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
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "wcache/cache_level.h"
#include "wcache/access_log.h"
#include "wcache/cache_state_log.h"
#include "wcache/event.h"
#include "wcache/layout.h"
#include "wcache/line_trace.h"
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

    // Ruling R8's line anchor for the burst in flight: the minimum, over the
    // lines of THIS burst, of each line's `Mshr::first_request`. Reset to
    // `issued_at` at every issue and lowered as each line resolves, so
    // `served - burst_anchor` is R8's per-burst term.
    //
    // It is lowered only for a line a PREFETCH of this core brought in or that
    // merged onto one; a line another request already had in flight leaves it
    // at this burst's own issue. That is what makes `hidden_latency` identically
    // zero at `prefetch_distance = 0` instead of crediting the policy with a
    // head start no prefetcher gave it.
    SimTime burst_anchor{0};

    // When this core reached the tile barrier, so `on_barrier` can charge it
    // `tile_origin[N+1] - arrival` (Part 8's `barrier_slack_cycles`). The
    // subtraction cannot happen at the arrival, because `tile_origin[N+1]` is
    // measured by the barrier event the last arrival schedules.
    SimTime barrier_arrival{0};

    // `served(c, cursor - 1)`. 3.3 gives it a NONE at a tile start; here that
    // state is spelled `cursor == 0` instead, and the two are the same state
    // because the cursor is reset at every tile start and advanced at every
    // service. One field carrying its own validity cannot disagree with a second
    // field that says whether it is valid (the shape decision B89 made
    // unrepresentable for `InsertResult::evicted`), and it is why the service
    // floor stops at the tile seam without anything having to clear it (4.5).
    SimTime served_time{0};
};

// What one run reports (Part 8), which unit D2 turns into a CSV row.
//
// The first group is the counters Part 3's own pseudocode increments by name.
// The rest is Part 8's: the stall breakdown by cause, the four prefetch outcome
// states, the memory counters and the model-health counters. Per-bank
// utilisation is still absent, and so is the reduction of the occupancy samples
// below into percentiles, which is D2c's.
struct EngineStats {
    // Per core. `core_stall[c] = sum over k of served(c, k) - want(c, k)`, the
    // cycles the core waited past its OWN self-timed schedule, which is the
    // quantity that integrates to the tile stretch (4.5, Part 8, V21).
    std::vector<std::int64_t> core_stall;

    // Per core, and LINE-ANCHORED (ruling R8, closing Q5):
    //
    //     fetch_latency[c] = sum over k of served(c, k) - t_first_request(k)
    //
    // where `t_first_request` is the PREFETCH's issue time when the line was
    // brought in by a prefetch or merged onto one, and this burst's own demand
    // issue otherwise. For a burst spanning several lines it is the earliest
    // anchor among them, so each burst contributes exactly one term.
    //
    // The anchor never reaches back to an EARLIER burst's demand, and that is
    // the half of the ruling the arithmetic rests on: a burst that merges onto a
    // line another core already had in flight would otherwise report a head
    // start at `prefetch_distance = 0`, where by definition nothing was hidden.
    //
    //     hidden_latency  = fetch_latency - core_stall,  guaranteed >= 0
    //     hidden_fraction = hidden_latency / fetch_latency
    //
    // The guarantee is structural rather than observed: `burst_anchor` starts at
    // the burst's own issue, which IS `want` under N14's recurrence, and only
    // ever moves earlier. `serve` refuses a run where it does not hold.
    //
    // This supersedes the definition `served - issued_at`, under which the
    // difference was identically zero at every distance (U19) and the prefetch
    // study therefore had no metric (G7).
    std::vector<std::int64_t> fetch_latency;

    // --- Part 8 "Time": the stall breakdown, per core.
    //
    // V21: the eight causes sum to `stall_total`, which is accumulated
    // independently from `served - want` plus the barrier slack. The partition
    // is exhaustive at every `l1_latency`: the two feeders that once had no
    // bucket, the L1 port's `ii` occupancy and its access latency, are
    // `stall_l1_port` (see `StallCause`).
    std::vector<std::int64_t> stall_l1_slot;
    std::vector<std::int64_t> stall_l1_line;
    std::vector<std::int64_t> stall_l1_port;
    std::vector<std::int64_t> stall_l2_slot;
    std::vector<std::int64_t> stall_l2_line;
    std::vector<std::int64_t> stall_l2_port;
    std::vector<std::int64_t> stall_channel;
    std::vector<std::int64_t> stall_barrier;
    std::vector<std::int64_t> stall_total;

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

    // --- Part 8 "Prefetch": every prefetch issued ends in exactly one of four
    // states, and the four sum to `pf_issued`:
    //
    //     pf_timely + pf_late + pf_wasted + (the five drop counts) == pf_issued
    //
    // A prefetched line still resident and still undemanded when the run ends is
    // charged as WASTED, since the core never got there. Without that the sum is
    // only an inequality.
    std::int64_t pf_issued = 0;
    std::int64_t pf_timely = 0;  // the demand access hit the prefetched line
    std::int64_t pf_late   = 0;  // the demand merged onto it while outstanding
    std::int64_t pf_wasted = 0;  // evicted, invalidated, or never demanded

    // The fifth drop reason the CSV schema names. Structurally zero in this
    // engine and reported anyway, because zero is the answer the schema needs: a
    // prefetch meeting a matching entry is dropped before the target-list bound
    // is ever consulted, so `DroppedEntry` subsumes it (4.6, cache_level.cpp).
    std::int64_t pf_dropped_targets_full = 0;

    // An L1 line evicted while it was a prefetched, undemanded line, and then
    // demanded before the tile ended. 4.6's pollution term.
    std::int64_t pf_pollution_evictions = 0;

    // Bursts that are not first in their tile, which is the ceiling on coverage:
    // the first burst of a tile can never be prefetched, because the next tile's
    // activations do not exist until the barrier resolves (4.6). A property of
    // the trace, so it is reported whether or not a prefetcher is on.
    std::int64_t pf_bursts_eligible = 0;

    // Every demand burst issued, which is the DENOMINATOR Part 8 gives both
    // coverage terms: "coverage is timely plus late over all bursts, and its
    // ceiling is the fraction of bursts that are not first-in-tile". Neither
    // ratio is computable without it, and nothing else in this struct counts
    // bursts: `l1_accesses` counts demand PROBES, which a refused request
    // repeats.
    std::int64_t demand_bursts = 0;

    // --- Part 8's memory counters. Hits and accesses are DEMAND only, which is
    // what makes the ratio a hit rate: a prefetch that finds its line resident
    // is a drop rather than a hit, and counting it would move the denominator
    // without moving the numerator. `dram_accesses` is every line the L2 sent to
    // the channel, prefetched or not, because that is real traffic.
    std::int64_t l1_hits = 0, l1_accesses = 0;
    std::int64_t l2_hits = 0, l2_accesses = 0;
    std::int64_t dram_accesses = 0;

    // --- Part 8 "Model health".
    //
    // D4/V6: a request released from a LINE-wait index is woken onto a resident
    // line, so its re-probe is a hit unless the line is evicted in between. This
    // counts the times it was.
    std::int64_t hits_downgraded_to_miss = 0;

    // The high-water mark of the waiting population across both levels, against
    // I11's bound.
    std::int64_t max_wait_depth = 0;

    // Events dispatched: the cost measure Part 8 asks to be measured rather than
    // claimed.
    std::int64_t events = 0;

    // Occupancy samples, one at every allocate and every retire, per level. Kept
    // as samples rather than reduced on the fly so the percentile reduction
    // stays out of the hot path; D2c turns them into p50/p95/max.
    std::vector<std::int32_t> l1_mshr_occupancy;
    std::vector<std::int32_t> l2_mshr_occupancy;
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

    // The same loop, driven one tile at a time.
    //
    // Seeds the queue on the first call, then dispatches events until the next
    // event in the queue is a Barrier, which it leaves UNDISPATCHED, or until
    // the queue empties. Returns that pending barrier's tile, or -1 when the run
    // is complete, in which case the D12 checks `run` makes have already run.
    //
    // The pause point is before the barrier rather than after it because
    // `on_barrier` calls `start_tile`, which reads the NEXT tile's bursts, while
    // `barrier_arrive` has already read this tile's tail. Parking here is
    // therefore the one point at which tile N is fully read and tile N+1 is
    // untouched, which is what a driver sharing one trace window across engines
    // needs in order to advance that window.
    //
    // The next call dispatches the parked barrier and runs on, so `run` is
    // exactly `while (run_to_barrier() >= 0) {}` and the dispatch order is the
    // one `run` always had.
    //
    // Throws what `run` throws, at the same points.
    std::int32_t run_to_barrier();

    // Exactly one tile of progress, for a driver that shares ONE trace window
    // across several engines: it dispatches the barrier a previous call parked
    // on, runs to the next barrier and parks there. Returns false when the run
    // is complete.
    //
    // It does not pop the parked barrier itself, because `run_to_barrier`
    // already does that as its first act. Doing both would dispatch two
    // barriers whenever one immediately follows another -- a tile in which
    // every core has no bursts clears its barrier the moment it starts -- and
    // the engine would then be a tile ahead of the window it is sharing.
    bool step_tile();

    // The other end of a `run_to_barrier` drive. Dispatches the pending
    // barrier, if any, then drains the queue and runs the D12 checks. Calling
    // it when nothing is pending is legal and is a no-op plus the checks. After
    // it returns, `tile_origin(n_tiles)` is the layer makespan.
    //
    // A driver that moves a shared trace window has to advance the window
    // BEFORE it runs the engine, so the last tile's barrier is left queued with
    // no further advance to resume it. This is what dispatches it.
    //
    // Throws what `run` throws, at the same points.
    void finish();

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

    // --- the two debugging instruments ---------------------------------------
    //
    // Both are optional, both are off by default, and they are SEPARATE on
    // purpose: `CacheStateLog` records what is in the arrays and when that
    // changed, `LineTrace` records what happened to a line between entering a
    // cache and leaving it. Either may be attached without the other.
    //
    // Neither changes what the engine computes. Every site below is guarded on
    // the pointer, reads state that already exists, and writes no engine field,
    // so a run with either instrument attached produces the same CSV row as one
    // without. That is the property that makes them usable as evidence about a
    // run rather than about themselves.
    //
    // The pointee must outlive the engine; neither is owned.
    void set_cache_state_log(CacheStateLog* log) { cache_state_ = log; }
    void set_line_trace(LineTrace* trace) { line_trace_ = trace; }

    // The third instrument (plan 0831 U2). It is fed from the two sites that
    // count `l1_accesses` and `l2_accesses` rather than from the three array
    // transitions the other two share, because a reference and an array change
    // are different events: a hit changes nothing and is still a reference.
    void set_access_log(AccessLog* log) { access_log_ = log; }

    // --- PrefetchIssuer (C5) -------------------------------------------------
    std::int32_t n_bursts_in_tile(CoreId core) const override;
    bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) override;

private:
    // --- the loop and the six handlers (C2) ----------------------------------
    void dispatch(const Event<EventPayload>& e);

    // D12's checks, run when the queue empties.
    void check_no_work_outstanding();
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
    void back_invalidate(LineId line, SimTime now);

    // --- the core state machine (C3) -----------------------------------------
    //
    // `anchor` is ruling R8's `t_first_request` for the line that just landed:
    // the prefetch's issue time when a prefetch fetched it, and the request's
    // own burst issue otherwise. The caller passes it because only the caller
    // still holds the entry the line came out of.
    void core_line_done(Request& r, SimTime now, SimTime anchor);
    void serve(CoreId c, SimTime now, StallCause cause);
    void barrier_arrive(CoreId c, SimTime now);
    void start_tile(std::int32_t tile, SimTime now);

    // --- Part 8's prefetch outcome accounting (4.6) --------------------------
    //
    // R8's anchor for a demand that found its line already resident, and 4.6's
    // `timely` at the same moment: a hit on a prefetched, still undemanded line
    // is the prefetch that made it. Returns the prefetch's issue time when it
    // was one, and `r.issued_at` otherwise, so the caller has R8's anchor either
    // way. Also charges 4.6's pollution term, which is a demand for a line an
    // earlier prefetch had brought in and then lost.
    SimTime demand_anchor_on_probe(Request& r, bool hit);

    // Records a prefetched line that landed with no demand waiting on it, so a
    // later hit can be called timely and a later eviction wasted.
    void note_prefetch_resident(CoreId c, LineId line, SimTime first_request);

    // An L1 line leaving the array, by eviction or by back-invalidation. Charges
    // `pf_wasted` when it was a prefetched line no demand ever reached.
    void note_line_left_l1(CoreId c, LineId line);

    // Charges every prefetched line still resident and still undemanded at the
    // end of the run as wasted, which is what makes 4.6's four states sum.
    void close_out_prefetch_stats();

    // 4.5's `max(gap_k, core_accept_ii)`, the period from one service to the
    // next issue.
    SimTime step_after(CoreId c, std::int32_t tile, BurstIndex k) const;

    // --- feeding the two instruments (see set_cache_state_log above) ---------
    //
    // Three verbs, because the array has exactly three transitions, and BOTH
    // instruments are fed from them. Fed from one place rather than two so the
    // state log and the episode table can never disagree about what the array
    // did; written to two FILES so that neither has to be read through the
    // other.
    bool instrumented() const { return cache_state_ != nullptr || line_trace_ != nullptr; }

    // The way `line` occupies at `level`, by probing the array for it. Costs one
    // probe and one division, so it is called only under `instrumented()`.
    // Returns -1 when the line is not resident, which no caller should see.
    std::int32_t way_of(Level level, CoreId core, LineId line) const;

    // The tile every core is on. One number rather than a per-core field
    // because `start_tile` moves all of them together, so the L2 -- which
    // belongs to no core -- still has an unambiguous tile to be stamped with.
    std::int32_t current_tile() const;

    void note_fill(Level level, CoreId core, LineId line, std::int32_t way, SimTime now,
                   SimTime first_request, bool pf_opened);
    void note_leave(Level level, CoreId core, LineId line, std::int32_t way, SimTime now,
                    const char* why);
    void note_hit(Level level, CoreId core, LineId line, bool demand);

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
    Request& acquire(CoreId c, LineId line, BurstIndex k, bool demand, SimTime issued_at);
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

    // Whether tile 0 has been seeded. The seeding is `run`'s first two lines and
    // has to happen once per run, not once per `run_to_barrier` call.
    bool started_ = false;

    // Part 5's countdown, not a scan: "each tile holds `cores_remaining`; a core
    // clearing the tile decrements it and parks in `AtBarrier`; the decrement
    // reaching zero schedules `E_Barrier`."
    std::int32_t cores_remaining_ = 0;

    EngineStats stats_;

    // Per core, the lines a prefetch brought into that core's L1 that no demand
    // has reached yet, each against the prefetch's issue time (R8's anchor).
    // A line leaves on the first demand hit (timely), on eviction or
    // invalidation (wasted), or at the end of the run (wasted).
    //
    // Never iterated, for the reason `MshrFile::entries_` is never iterated: an
    // unordered container's order is unspecified and nothing that reaches a
    // victim choice may depend on it. Every access below is a lookup, an insert,
    // an erase or a size.
    std::vector<std::unordered_map<LineId, SimTime>> pf_resident_;

    // Per core, the prefetched lines this tile has already lost from the L1. A
    // demand for one of them is 4.6's pollution term. Cleared at every tile
    // start, because "demanded soon after" is scoped to the tile.
    std::vector<std::unordered_set<LineId>> pf_evicted_;

    // The waiting population across both levels, for I11's high-water mark. A
    // request joins on a refusal and leaves in a wake list, which are the only
    // two ways in or out.
    std::int64_t waiting_ = 0;

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

    // Null unless a driver attached one. Never owned, and never read by
    // anything that decides what the engine does.
    CacheStateLog* cache_state_ = nullptr;
    AccessLog*     access_log_  = nullptr;
    LineTrace*     line_trace_  = nullptr;
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
