// The engine loop, the memory-side handlers, and inclusion.
//
// Plan units C2 and C4. The core-side half of C2's handler set and the whole of
// C3 -- `E_Issue`, `core_line_done`, `serve`, the barrier -- is in
// `engine_core.cpp`, which mirrors the plan's own split between 3.4 (triage,
// retire, wake) and 3.4b (the core side). One class, two files, because the two
// halves are two units and read as two subjects.
#include "wcache/engine.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

[[noreturn]] void engine_error(const char* verb, const std::string& what) {
    throw std::logic_error("Engine::" + std::string(verb) + ": " + what);
}

std::size_t idx(CoreId c) { return static_cast<std::size_t>(c.get()); }

// Whether a triage left the request on a wait index, which is the one thing
// that grows the waiting population I11 bounds. Written once because the L1 and
// the L2 halves of the check would otherwise be two copies that can disagree.
bool is_blocked(TriageOutcome result) {
    return result == TriageOutcome::BlockedTargets || result == TriageOutcome::BlockedPool;
}

}  // namespace

Engine::Engine(const AddressMapper& mapper, const TileTrace& trace, const EngineParams& params)
    : mapper_(mapper),
      trace_(trace),
      params_(params),
      l2_(Level::L2, mapper, params.l2, counter_),
      dram_(params.dram_ii, params.l2_miss_latency) {
    const std::int32_t n_cores = trace.n_cores();
    if (n_cores < 1) {
        throw std::invalid_argument("Engine: the trace reports " + std::to_string(n_cores) +
                                    " cores; at least 1 is required");
    }

    // One L1 per core (2.2, "private, one per core"). Reserved first because
    // `CacheLevel` is move-only and each element holds a reference to
    // `counter_`; growth would move them, which is legal, but reserving keeps
    // the addresses the levels hand out stable from the start.
    l1_.reserve(static_cast<std::size_t>(n_cores));
    for (std::int32_t c = 0; c < n_cores; ++c) {
        l1_.emplace_back(Level::L1, mapper, params.l1, counter_);
    }

    prefetcher_ = make_prefetcher(params.prefetch_policy, params.prefetch_distance, n_cores);
    l2_prefetcher_ = make_l2_prefetcher(params.l2_prefetch_policy, params.l2_prefetch_axis,
                                        params.l2_prefetch_distance, params.l2_prefetch_up,
                                        params.l2_prefetch_down);

    const std::size_t n = static_cast<std::size_t>(n_cores);
    cores_.assign(n, CoreState{});
    stats_.core_stall.assign(n, 0);
    stats_.fetch_latency.assign(n, 0);
    stats_.pf_outstanding.assign(n, 0);
    stats_.stall_l1_slot.assign(n, 0);
    stats_.stall_l1_line.assign(n, 0);
    stats_.stall_l1_port.assign(n, 0);
    stats_.stall_l2_slot.assign(n, 0);
    stats_.stall_l2_line.assign(n, 0);
    stats_.stall_l2_port.assign(n, 0);
    stats_.stall_channel.assign(n, 0);
    stats_.stall_barrier.assign(n, 0);
    stats_.stall_total.assign(n, 0);
    pf_resident_.resize(n);
    pf_evicted_.resize(n);

    // n_tiles + 1 entries: the last is the end of the run, so tile N's length is
    // `tile_origin[N+1] - tile_origin[N]` for every tile including the last,
    // which is the form V1 compares against `mac_cycles[N]`.
    const std::int32_t n_tiles = trace.n_tiles();
    if (n_tiles < 0) {
        throw std::invalid_argument("Engine: the trace reports " + std::to_string(n_tiles) +
                                    " tiles");
    }
    tile_origin_.assign(static_cast<std::size_t>(n_tiles) + 1, SimTime{0});
}

SimTime Engine::tile_origin(std::int32_t tile) const {
    return tile_origin_.at(static_cast<std::size_t>(tile));
}

const CoreState& Engine::core(CoreId c) const { return cores_.at(idx(c)); }

CacheLevel& Engine::l1(CoreId c) { return l1_.at(idx(c)); }

// --- request lifetime --------------------------------------------------------

Request& Engine::acquire(CoreId c, LineId line, BurstIndex k, bool demand, SimTime issued_at) {
    if (free_.empty()) {
        arena_.push_back(Request{c, line, k, demand, issued_at});
        return arena_.back();
    }
    Request* r = free_.back();
    free_.pop_back();
    // Assigned whole rather than field by field, so a field added to `Request`
    // later cannot be left carrying the previous occupant's value. That failure
    // is silent: a stale `refusal` would give a fresh request someone else's
    // seniority and reorder the FIFO for the rest of the run.
    *r = Request{c, line, k, demand, issued_at};
    return *r;
}

void Engine::release(Request& r) {
    // Terminal means terminal: nothing may still point at it. I5's bit and the
    // reservation are the two things a wait index leaves behind, and `mshr1` is
    // I6's pairing with the level.
    if (r.on_wait_index || r.reserved || r.mshr1 != nullptr) {
        engine_error("release", "line " + std::to_string(r.line.get()) +
                                    " is still held: on_wait_index=" +
                                    std::to_string(r.on_wait_index) +
                                    " reserved=" + std::to_string(r.reserved) +
                                    " mshr1=" + std::to_string(r.mshr1 != nullptr));
    }
    free_.push_back(&r);
}

// --- the loop (3.2) ----------------------------------------------------------

std::int32_t Engine::run_to_barrier() {
    if (!started_) {
        tile_origin_.at(0) = SimTime{0};
        if (trace_.n_tiles() > 0) start_tile(0, SimTime{0});
        started_ = true;
    } else if (!queue_.empty() && queue_.peek_min().kind == EventKind::Barrier) {
        // The barrier the previous call parked on is this call's first work, so
        // the two calls together dispatch exactly what one uninterrupted loop
        // would have, in the same order.
        const Event<EventPayload> e = queue_.pop_min();
        dispatch(e);
    }

    while (!queue_.empty()) {
        if (queue_.peek_min().kind == EventKind::Barrier) return queue_.peek_min().payload.tile;
        const Event<EventPayload> e = queue_.pop_min();
        dispatch(e);
    }

    close_out_prefetch_stats();
    check_no_work_outstanding();
    // Every episode still resident when the clock stops, so the table accounts
    // for every fill. `tile_origin_.back()` is the makespan, which is the last
    // instant the run had.
    if (line_trace_ != nullptr) line_trace_->flush(tile_origin_.back());
    return -1;
}

void Engine::run() {
    while (run_to_barrier() >= 0) {
    }
}

bool Engine::step_tile() { return run_to_barrier() >= 0; }

void Engine::finish() {
    // The same loop, and deliberately not a second copy of it: draining from a
    // parked barrier and running from the start are the same drain, differing
    // only in how much of it is left.
    run();
}

void Engine::check_no_work_outstanding() {
    // D12. An empty queue with work outstanding is a bug, and it must fail
    // loudly under a sweep build rather than returning a plausible short run.
    for (std::size_t c = 0; c < cores_.size(); ++c) {
        if (cores_[c].phase != Phase::Done) {
            engine_error("run", "deadlock: the queue is empty but core " + std::to_string(c) +
                                    " is on tile " + std::to_string(cores_[c].tile) + " burst " +
                                    std::to_string(cores_[c].cursor.get()) + " with " +
                                    std::to_string(cores_[c].pending_lines) +
                                    " lines outstanding");
        }
        const MshrFile& f = l1_[c].mshrs();
        if (f.live() != 0 || f.slot_wait_depth() != 0) {
            engine_error("run", "deadlock: the queue is empty but core " + std::to_string(c) +
                                    "'s L1 MSHR file holds " + std::to_string(f.live()) +
                                    " live entries and " + std::to_string(f.slot_wait_depth()) +
                                    " slot waiters");
        }
    }
    if (l2_.mshrs().live() != 0 || l2_.mshrs().slot_wait_depth() != 0) {
        engine_error("run", "deadlock: the queue is empty but the L2 MSHR file holds " +
                                std::to_string(l2_.mshrs().live()) + " live entries and " +
                                std::to_string(l2_.mshrs().slot_wait_depth()) + " slot waiters");
    }
}

void Engine::dispatch(const Event<EventPayload>& e) {
    const SimTime now = e.key.time;
    // Part 8 asks for the cost of the event model to be measured rather than
    // claimed, and this is the measurement: one increment per dispatch.
    ++stats_.events;
    switch (e.kind) {
        case EventKind::Issue:   on_issue(e.key.core, e.payload.burst, now); return;
        case EventKind::L1Probe: on_l1_probe(*e.payload.req, now); return;
        case EventKind::L2Probe: on_l2_probe(*e.payload.req, now); return;
        case EventKind::L2Fill:  on_l2_fill(*e.payload.entry, now); return;
        case EventKind::L1Fill:  on_l1_fill(*e.payload.entry, now); return;
        case EventKind::Barrier: on_barrier(e.payload.tile, now); return;
    }
    // Unreachable: the switch covers every enumerator. Reported rather than
    // ignored, since a silently dropped event is a run that ends early and still
    // prints numbers.
    engine_error("dispatch", "unknown EventKind");
}

// --- reinjection (3.4, 3.5) --------------------------------------------------

void Engine::reinject(Request& r, SimTime now) {
    // Back through its level's PORT, because it costs a real lookup, and at
    // `r.level` rather than at the top of the hierarchy. 3.5's trap: a request
    // woken from an L2 index and re-triaged at the L1 would find its OWN entry,
    // merge into itself, and wait for a fill nobody will request.
    //
    // `r.refusal` is NOT touched here, which is what makes the ordering FIFO by
    // FIRST refusal (3.8) and starvation freedom provable (I10).
    if (r.level == Level::L1) {
        CacheLevel& lvl      = l1_.at(idx(r.core));
        const SimTime accept = lvl.port(0).reserve(now);
        queue_.schedule(accept + lvl.port(0).latency(), EventKind::L1Probe, r.refusal, r.core,
                        EventPayload{&r, nullptr, r.burst, 0});
    } else {
        const std::int32_t bank = l2_.bank_of(r.line);
        const SimTime accept    = l2_.port(bank).reserve(now);
        queue_.schedule(accept + l2_.port(bank).latency(), EventKind::L2Probe, r.refusal, r.core,
                        EventPayload{&r, nullptr, r.burst, 0});
    }
}

void Engine::reinject_all(std::vector<Request*>& wake, SimTime now) {
    // Every member of a wake list has just left a wait index, and those are the
    // only two exits either index has, so this is where the waiting population
    // shrinks (I11).
    waiting_ -= static_cast<std::int64_t>(wake.size());
    // In the order handed over, which is already 3.8's key order: `retire`
    // merges the two indices into one list and sorts it, and the sort is not
    // redundant, because a slot waiter can outlive the allocation of an entry it
    // later merges onto and arrive carrying an older stamp than what is already
    // there. Iterating in this order is what makes port reservation order equal
    // key order (I7b).
    for (Request* w : wake) reinject(*w, now);
}

// --- the probes (3.4) --------------------------------------------------------

void Engine::on_l1_probe(Request& r, SimTime now) {
    CacheLevel& lvl = l1_.at(idx(r.core));

    // Read before the triage, which is what clears it: this probe is the
    // re-triage the bit was set for (D4, V6).
    const bool woken_onto_resident = r.line_resident_at_wake;
    r.line_resident_at_wake        = false;

    const TriageOutcome result = lvl.triage(r, granted_);
    if (is_blocked(result)) ++waiting_;
    if (waiting_ > stats_.max_wait_depth) stats_.max_wait_depth = waiting_;
    if (woken_onto_resident && result != TriageOutcome::Hit) ++stats_.hits_downgraded_to_miss;
    if (result == TriageOutcome::Forwarded) {
        stats_.l1_mshr_occupancy.push_back(lvl.mshrs().live());
    }

    if (r.demand) {
        ++stats_.l1_accesses;
        if (result == TriageOutcome::Hit) ++stats_.l1_hits;
        // Plan 0831 U2, inside the SAME guard as the counter above so the log's
        // record count and `l1_accesses` cannot diverge (V1).
        if (access_log_ != nullptr) access_log_->observe(Level::L1, r.core, r.line);
    }

    if (result == TriageOutcome::Hit) note_hit(Level::L1, r.core, r.line, r.demand);

    if (is_dropped(result)) {
        // A prefetch, refused at issue and therefore DROPPED rather than queued
        // (N16, I15). This is the credit coming back: the line never reached an
        // entry, so it is out of flight now.
        --stats_.pf_outstanding.at(idx(r.core));
        switch (result) {
            case TriageOutcome::DroppedArrayHit: ++stats_.pf_dropped_array_hit; break;
            case TriageOutcome::DroppedEntry:    ++stats_.pf_dropped_entry; break;
            case TriageOutcome::DroppedNoSlot:   ++stats_.pf_dropped_no_slot; break;
            default:                             ++stats_.pf_dropped_reserve; break;
        }
        release(r);
        reinject_all(granted_, now);
        return;
    }

    // 4.6's timely hit and pollution term, and R8's anchor for a line that was
    // already resident, all decided at the same instant: whether this demand
    // found a line a prefetch had put there.
    const SimTime anchor =
        r.demand ? demand_anchor_on_probe(r, result == TriageOutcome::Hit) : r.issued_at;

    switch (result) {
        case TriageOutcome::Hit:
            // D8: the L1 access latency has already been paid, by the port
            // reservation that scheduled this probe. The core takes delivery
            // here, inside the probe, because a hit is not a fill.
            core_line_done(r, now, anchor);
            release(r);
            break;

        case TriageOutcome::Merged:
        case TriageOutcome::BlockedTargets:
        case TriageOutcome::BlockedPool:
            // Subscribed, or registered. Nothing computes a completion time
            // (D2, D3): the time is delivered to it by the fill.
            break;

        case TriageOutcome::Forwarded: {
            // P4: a request does not fall through the hierarchy inside one
            // function call. It crosses the boundary as an event, so the L2
            // array state at the moment of the probe is what the probe sees.
            const std::int32_t bank = l2_.bank_of(r.line);
            const SimTime accept    = l2_.port(bank).reserve(now);
            queue_.schedule(accept + l2_.port(bank).latency(), EventKind::L2Probe, r.refusal,
                            r.core, EventPayload{&r, nullptr, r.burst, 0});
            break;
        }

        default:
            engine_error("on_l1_probe", "unknown TriageOutcome");
    }

    // 3.8: "a grantee that turns out not to need its slot releases the
    // reservation, immediately granting the next waiter". Non-empty only on the
    // two outcomes that release one.
    reinject_all(granted_, now);
}

// The L2 policy's issue path (plan 0831-l2-cin-neighbour section 6b).
//
// Every suggestion costs exactly what a demand costs below the L1: an L2 bank
// port slot here, an L2 MSHR entry inside `triage`, and on a miss a DRAM slot
// and the bytes. Nothing is discounted, which is the whole reason the L1
// policy lost cycles at 64-byte lines and is the standard this one is held to.
//
// It does NOT take an L1 port slot or an L1 entry, because it never touches the
// L1. That is `mshr1 == nullptr` seen from the resource side.
void Engine::l2_prefetch_from(LineId line, CoreId core, SimTime now) {
    l2_pf_scratch_.clear();
    l2_prefetcher_->suggest(mapper_, line, l2_pf_scratch_);
    for (const LineId want : l2_pf_scratch_) {
        // The direction, for the split the plan predicts will differ.
        if (want.get() > line.get()) ++stats_.l2_pf_issued_up;
        else                         ++stats_.l2_pf_issued_down;
        ++stats_.l2_pf_issued;

        // demand = false and no L1 entry: the two facts that make `triage`'s
        // `is_prefetch_at_issue` true here, which is what routes this request
        // down the four drop branches instead of ever letting it wait.
        Request& pf = acquire(core, want, BurstIndex{0}, false, now);
        pf.level = Level::L2;
        const std::int32_t bank = l2_.bank_of(want);
        const SimTime accept    = l2_.port(bank).reserve(now);
        queue_.schedule(accept + l2_.port(bank).latency(), EventKind::L2Probe, NoRefusal, core,
                        EventPayload{&pf, nullptr, BurstIndex{0}, 0});
    }
}

void Engine::on_l2_probe(Request& r, SimTime now) {
    // I6, at the one place it can be broken: only a request holding an L1 entry
    // ever reaches the L2, and it still holds it. 4.1's whole argument rests on
    // this, since it is what makes the L2's wait sets views over structures that
    // already exist rather than storage.
    // I6, RESTATED by plan 0831-l2-cin-neighbour: a request that can WAIT at
    // the L2 holds an L1 entry. An L2-originated prefetch never waits -- it is
    // dropped at issue exactly as an L1 prefetch is -- so it needs no L1 entry,
    // and it is the first request in the design to reach here without one.
    // 4.1's argument is untouched: it is about the waiting population, and this
    // request never joins it.
    if (r.level != Level::L2 || (r.mshr1 == nullptr && r.demand)) {
        engine_error("on_l2_probe", "line " + std::to_string(r.line.get()) +
                                        " reached the L2 without holding an L1 entry (I6)");
    }
    const bool l2_prefetch = !r.demand && r.mshr1 == nullptr;

    const bool woken_onto_resident = r.line_resident_at_wake;
    r.line_resident_at_wake        = false;

    const TriageOutcome result = l2_.triage(r, granted_);
    if (is_blocked(result)) ++waiting_;
    if (waiting_ > stats_.max_wait_depth) stats_.max_wait_depth = waiting_;
    if (woken_onto_resident && result != TriageOutcome::Hit) ++stats_.hits_downgraded_to_miss;
    if (result == TriageOutcome::Forwarded) {
        stats_.l2_mshr_occupancy.push_back(l2_.mshrs().live());
    }
    if (r.demand) {
        ++stats_.l2_accesses;
        if (result == TriageOutcome::Hit) ++stats_.l2_hits;
        // Plan 0831 U2, as at the L1 above.
        if (access_log_ != nullptr) access_log_->observe(Level::L2, r.core, r.line);
    }

    if (result == TriageOutcome::Hit) note_hit(Level::L2, r.core, r.line, r.demand);

    // The trigger (plan 0831 section 6). Fires on a DEMAND miss, and on a
    // demand hit to a line a prefetch put there and nobody has used yet.
    //
    // The second row is what keeps the chain alive. On a miss-only rule, line
    // b+1 arrives by prefetch, its demand HITS, that hit fires nothing, and
    // b+2 is never fetched: the chain dies every other line and the hit rate
    // caps at exactly half. Measured on V8: 50.0% miss-only against 96.9%
    // with this row.
    if (r.demand) {
        if (result == TriageOutcome::Forwarded) {
            l2_prefetch_from(r.line, r.core, now);
        } else if (result == TriageOutcome::Hit) {
            const auto tag = l2_prefetched_.find(r.line.get());
            if (tag != l2_prefetched_.end()) {
                // Cleared here, exactly as gem5 clears `_prefetched` inside its
                // `if (satisfied)` branch: the line has now been used, so it is
                // an ordinary line and a later hit fires nothing.
                l2_prefetched_.erase(tag);
                ++stats_.l2_pf_timely;
                ++stats_.l2_pf_retriggers;
                l2_prefetch_from(r.line, r.core, now);
            }
        }
    }

    switch (result) {
        case TriageOutcome::Hit:
            // D7: the order in which simultaneous hits are serviced IS the
            // recency stack, and `triage` has just called `on_hit` in that
            // order. The L1 entry the request still holds is what fills.
            queue_.schedule(now + params_.l2_to_l1_latency, EventKind::L1Fill, NoRefusal, r.core,
                            EventPayload{nullptr, r.mshr1, r.burst, 0});
            break;

        case TriageOutcome::Merged:
        case TriageOutcome::BlockedTargets:
        case TriageOutcome::BlockedPool:
            break;

        case TriageOutcome::Forwarded: {
            // The entry `triage` just allocated. Looked up rather than returned,
            // which costs one hash probe on the coldest path in the model -- a
            // full miss -- and keeps `triage` to a single return value.
            Mshr* e = l2_.mshrs().find(r.line);
            if (e == nullptr) {
                engine_error("on_l2_probe", "line " + std::to_string(r.line.get()) +
                                                " was forwarded but has no L2 entry");
            }
            // Real channel traffic, prefetched or not, which is why this is the
            // one memory counter that is not demand-only.
            ++stats_.dram_accesses;
            const SimTime accept = dram_.reserve(now);
            queue_.schedule(accept + dram_.latency(), EventKind::L2Fill, NoRefusal, r.core,
                            EventPayload{nullptr, e, r.burst, 0});
            break;
        }

        case TriageOutcome::DroppedArrayHit:
        case TriageOutcome::DroppedEntry:
        case TriageOutcome::DroppedNoSlot:
        case TriageOutcome::DroppedReserve:
            // Reachable only for an L2-originated prefetch. For anything else
            // it is still the old error: a demand dropped at the L2 would leave
            // an L1 entry nobody will ever fill, surfacing much later as D12's
            // deadlock rather than here.
            if (!l2_prefetch) {
                engine_error("on_l2_probe",
                             "line " + std::to_string(r.line.get()) +
                                 " was dropped at the L2 while holding an L1 entry, which would "
                                 "leave that entry unfillable");
            }
            if (result == TriageOutcome::DroppedArrayHit) ++stats_.l2_pf_dropped_array_hit;
            else if (result == TriageOutcome::DroppedEntry) ++stats_.l2_pf_dropped_entry;
            else if (result == TriageOutcome::DroppedNoSlot) ++stats_.l2_pf_dropped_no_slot;
            else ++stats_.l2_pf_dropped_reserve;
            release(r);
            break;

        default:
            engine_error("on_l2_probe", "unknown TriageOutcome at the L2");
    }

    reinject_all(granted_, now);
}

// --- the fills (3.4) ---------------------------------------------------------

void Engine::on_l2_fill(Mshr& e, SimTime now) {
    const LineId line = e.line;

    // Install, then retire, in 3.1's order: "install in L2 (victim, evict,
    // back-invalidate if inclusive), retire the entry, wake its waiters."
    const InsertResult res = l2_.install(line);
    if (res.evicted && params_.inclusion == Inclusion::Inclusive) {
        back_invalidate(res.evicted_line, now);
    }

    // The tag bit (plan 0831 U4). Set when a prefetch put this line here and no
    // demand has merged onto the entry; a line that leaves still tagged was
    // never used, which is the waste term gem5 counts as `prefetchUnused`.
    if (e.pf_opened && !e.demand) {
        l2_prefetched_.insert(line.get());
    } else if (e.pf_opened && e.demand) {
        // A demand arrived while the prefetch was still in flight: it hid part
        // of the latency but not all of it.
        ++stats_.l2_pf_late;
    }
    if (res.evicted) {
        const auto gone = l2_prefetched_.find(res.evicted_line.get());
        if (gone != l2_prefetched_.end()) {
            l2_prefetched_.erase(gone);
            ++stats_.l2_pf_wasted;
        }
    }

    if (instrumented()) {
        // The way is probed for the line just installed, and the victim left
        // from that same way: `install` puts the new line where the old one
        // was. Emitted evict-then-fill, in that order, because that is the
        // order the slot actually changed.
        const std::int32_t way = way_of(Level::L2, CoreId{0}, line);
        if (res.evicted) {
            note_leave(Level::L2, CoreId{0}, res.evicted_line, way, now, "evict");
        }
        note_fill(Level::L2, CoreId{0}, line, way, now, e.first_request, e.pf_opened);
    }

    l2_.mshrs().retire(e, retire_);
    stats_.l2_mshr_occupancy.push_back(l2_.mshrs().live());

    // D10: the L2 MSHR frees when the fill lands at the L2, and the core
    // finishes later. The two are separated by `l2_to_l1_latency`, which is the
    // knob that keeps the split structural even at its default of 0.
    for (Request* t : retire_.targets) {
        // An L2-originated prefetch is the entry's primary, so it appears here
        // like any other target, and it is the one target with no L1 entry to
        // fill: nobody is waiting on it, and the line it wanted is now resident
        // in the L2, which was the whole point. Scheduling an L1Fill on its null
        // entry is what a first draft of this did, and it segfaulted on the
        // first prefetch that reached a fill.
        if (t->mshr1 == nullptr) {
            release(*t);
            continue;
        }
        queue_.schedule(now + params_.l2_to_l1_latency, EventKind::L1Fill, NoRefusal, t->core,
                        EventPayload{nullptr, t->mshr1, t->burst, 0});
    }
    reinject_all(retire_.wake, now);
}

void Engine::on_l1_fill(Mshr& e, SimTime now) {
    CacheLevel& lvl   = l1_.at(idx(e.core));
    const LineId line = e.line;

    // Read off the entry before `retire` erases it. `pf_opened` and
    // `first_request` are R8's anchor and 4.6's timely/late split, and `demand`
    // is the promotion: a prefetch entry a demand merged onto is a LATE
    // prefetch, and one nothing merged onto is a line the core has yet to reach.
    const bool pf_opened      = e.pf_opened;
    const bool was_promoted   = e.demand;
    const SimTime first_request = e.first_request;

    const InsertResult res = lvl.install(line);
    // The victim leaving the array is where a prefetched line the core never
    // reached becomes waste (4.6).
    if (res.evicted) note_line_left_l1(e.core, res.evicted_line);
    if (pf_opened) {
        if (was_promoted) {
            ++stats_.pf_late;
        } else {
            note_prefetch_resident(e.core, line, first_request);
        }
    }

    // I6's pairing restored BEFORE the entry is destroyed, which is the other
    // half of the obligation plan unit B3 recorded against C2: `retire` erases
    // the entry and cannot walk the requests that pointed at it, because
    // `mshr1` points from a request at another level's file. Done here, where
    // both the entry and its targets are still alive, so no dangling pointer is
    // ever formed, let alone compared.
    //
    // Every target is cleared, not only the primary. A secondary merged at the
    // L1 never held an entry, so its `mshr1` is already null and its level
    // already L1; assigning both unconditionally is one rule instead of a
    // special case that has to know which target is which.
    for (Request* t : e.targets) {
        t->mshr1 = nullptr;
        t->level = Level::L1;
    }

    if (instrumented()) {
        const std::int32_t way = way_of(Level::L1, e.core, line);
        if (res.evicted) note_leave(Level::L1, e.core, res.evicted_line, way, now, "evict");
        note_fill(Level::L1, e.core, line, way, now, first_request, pf_opened);
    }

    lvl.mshrs().retire(e, retire_);
    stats_.l1_mshr_occupancy.push_back(lvl.mshrs().live());

    for (Request* t : retire_.targets) {
        // A prefetch line has landed and is out of flight, so its credit comes
        // back and the prefetcher may issue again (N16: the budget, not a
        // refusal, is what stops it).
        if (!t->demand) --stats_.pf_outstanding.at(idx(t->core));
        // A demand target completes one line of its core's burst; a prefetch
        // completes nobody (4.6, I15), which `core_line_done` decides.
        //
        // R8: the anchor is the entry's `first_request` when a PREFETCH opened
        // it, which is the late-merge head start, and the target's own burst
        // issue otherwise. It is never an earlier burst's demand, which is what
        // keeps the hidden latency at zero when nothing is prefetched.
        core_line_done(*t, now, pf_opened ? first_request : t->issued_at);
        release(*t);
    }
    reinject_all(retire_.wake, now);
}

// --- Part 8's prefetch outcome accounting (4.6) ------------------------------

SimTime Engine::demand_anchor_on_probe(Request& r, bool hit) {
    auto& resident = pf_resident_.at(idx(r.core));

    if (hit) {
        const auto it = resident.find(r.line);
        if (it == resident.end()) return r.issued_at;
        // 4.6's TIMELY: the core's demand access hit a line the prefetcher had
        // put there, so the whole of that fetch was off the core's critical
        // path. R8 anchors this burst on the prefetch's issue, which is what
        // turns "the core did not stall" into a measured saving rather than a
        // zero.
        ++stats_.pf_timely;
        const SimTime first_request = it->second;
        resident.erase(it);
        return first_request;
    }

    // 4.6's pollution term: a line an earlier prefetch brought in, lost from the
    // array before the core reached it, and now demanded. The prefetch did not
    // just fail to help, it cost the eviction that this miss is paying for.
    if (pf_evicted_.at(idx(r.core)).erase(r.line) != 0) ++stats_.pf_pollution_evictions;
    return r.issued_at;
}

void Engine::note_prefetch_resident(CoreId c, LineId line, SimTime first_request) {
    pf_resident_.at(idx(c)).emplace(line, first_request);
}

void Engine::note_line_left_l1(CoreId c, LineId line) {
    if (pf_resident_.at(idx(c)).erase(line) == 0) return;
    // 4.6's WASTED: fetched, never used, and gone. Remembered for the rest of
    // the tile so that a demand for it can be charged as pollution.
    ++stats_.pf_wasted;
    pf_evicted_.at(idx(c)).insert(line);
}

void Engine::close_out_prefetch_stats() {
    // A prefetched line still sitting in the array when the run ends is a line
    // the core never got to, which is 4.6's own definition of waste. Charging it
    // here is what makes the four outcome states SUM to `pf_issued` rather than
    // fall short of it by however many prefetches happened to survive.
    //
    // Cleared as it is charged, so a second call after the run has already ended
    // adds nothing.
    for (auto& resident : pf_resident_) {
        stats_.pf_wasted += static_cast<std::int64_t>(resident.size());
        resident.clear();
    }
}

// --- inclusion (C4, 4.4, N8) -------------------------------------------------

// --- feeding the two instruments ---------------------------------------------

std::int32_t Engine::current_tile() const {
    return cores_.empty() ? -1 : cores_[0].tile;
}

std::int32_t Engine::way_of(Level level, CoreId core, LineId line) const {
    const CacheLevel& lvl = level == Level::L1 ? l1_.at(idx(core)) : l2_;
    const SlotId slot = lvl.array().probe(line);
    if (slot == NoSlot) return -1;
    // Slots of one set are the `assoc` consecutive ids starting at
    // `set_index * assoc` (set_associative.h), so the way is the offset within
    // that run. `assoc` is derived rather than stored: the abstract CacheArray
    // reports slots and the level reports sets, and widening that interface for
    // a debugging aid would be the wrong trade.
    const std::int64_t sets = lvl.num_sets();
    if (sets <= 0) return -1;
    const std::int64_t assoc = lvl.array().num_slots() / sets;
    return assoc <= 0 ? -1 : static_cast<std::int32_t>(slot.get() % assoc);
}

void Engine::note_fill(Level level, CoreId core, LineId line, std::int32_t way, SimTime now,
                       SimTime first_request, bool pf_opened) {
    const std::int64_t sets = level == Level::L1 ? l1_.at(idx(core)).num_sets() : l2_.num_sets();
    const Placement p = mapper_.locate(line, sets);
    const std::int32_t c = level == Level::L1 ? core.get() : -1;
    if (cache_state_ != nullptr) {
        cache_state_->record("fill", now, current_tile(), level, c, line, p.set_index, p.tag, way);
    }
    if (line_trace_ != nullptr) {
        line_trace_->on_fill(now, current_tile(), level, c, line, p.set_index, p.tag,
                             first_request, pf_opened);
    }
}

void Engine::note_leave(Level level, CoreId core, LineId line, std::int32_t way, SimTime now,
                        const char* why) {
    const std::int64_t sets = level == Level::L1 ? l1_.at(idx(core)).num_sets() : l2_.num_sets();
    const Placement p = mapper_.locate(line, sets);
    const std::int32_t c = level == Level::L1 ? core.get() : -1;
    if (cache_state_ != nullptr) {
        cache_state_->record(why, now, current_tile(), level, c, line, p.set_index, p.tag, way);
    }
    if (line_trace_ != nullptr) line_trace_->on_leave(now, level, c, line, why);
}

void Engine::note_hit(Level level, CoreId core, LineId line, bool demand) {
    // The line trace only. A hit changes what a line has DONE and not what the
    // array HOLDS, so it is not a state transition and does not belong in the
    // state log.
    if (line_trace_ == nullptr) return;
    line_trace_->on_hit(level, level == Level::L1 ? core.get() : -1, line, demand);
}

void Engine::back_invalidate(LineId line, SimTime now) {
    // The scan covers ALL cores because the L2 is shared, so a core's fill can
    // evict a line another core's L1 still holds. Sharedness is why the scan is
    // wide; it is not why you must invalidate at all, which is the correction v2
    // made to D6 and the reason this whole function sits behind a knob.
    //
    // Walked by core id over a vector, so the order is a total order and not an
    // artefact: under LRU an invalidation changes which slot is chosen next, so
    // an unspecified scan order would move victims (D7, D11).
    for (std::size_t c = 0; c < l1_.size(); ++c) {
        const SlotId s = l1_[c].array().probe(line);
        if (s != NoSlot) {
            l1_[c].array().invalidate(s);
            // The policy call is the caller's, exactly as `on_hit` is after a
            // probe (cache.h, policy.h). A5's `on_invalidate` resets the stamp
            // to "never", so the freed slot becomes the preferred victim again
            // rather than sitting live in the recency order (decision B96).
            l1_[c].policy().on_invalidate(s);
            const CoreId cid{static_cast<std::int32_t>(c)};
            if (instrumented()) {
                // The slot is in hand here, so the way comes off it directly
                // rather than from a probe of a line that is no longer there.
                const std::int64_t sets = l1_[c].num_sets();
                const std::int64_t assoc = sets > 0 ? l1_[c].array().num_slots() / sets : 0;
                note_leave(Level::L1, cid, line,
                           assoc > 0 ? static_cast<std::int32_t>(s.get() % assoc) : -1, now,
                           "invalidate");
            }
            note_line_left_l1(cid, line);
            ++stats_.back_invalidations;
        }
    }
}

}  // namespace wcache
