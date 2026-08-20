// The core state machine, the tile barrier, and the prefetch hook.
//
// Plan unit C3, which is 3.4b plus Part 5, and the sink half of plan unit C5.
// The memory-side handlers are in `engine.cpp`; the split mirrors the plan's own
// between 3.4 and 3.4b, and it is the boundary v3 exists to draw: "every line
// below would be identical if prefetching did not exist, except the last one,
// and that last one returns nothing."
//
// The rule this file implements is N14, and it is one recurrence:
//
//     issue(c, 0)   = tile_origin[tile] + local_tick(c, 0)
//     issue(c, k+1) = served(c, k) + max(gap_k, core_accept_ii)
//
// The trace contributes SPACING, not appointments. `gap_k` is the MAC work burst
// `k`'s weights feed, so it is a duration the core owes AFTER the weights
// arrive, added to `served(c, k)` and never to an absolute tick. v2 added it to
// an absolute tick, which let a core that had already lost 60 cycles arrive at
// its next burst on schedule anyway and discard the loss (D13). Under v3 a stall
// shifts the whole remainder of the tile by the full stall, and the shifts
// accumulate until the barrier collects them.
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

}  // namespace

// 4.5's `max(gap_k, core_accept_ii)`: the period from the service of burst `k`
// to the issue of burst `k + 1`.
//
// `core_accept_ii` is the floor and its value is 1. Its real job at the 2.5b
// defaults is not modelling but TERMINATION: with `l1_latency = 0` an all-hit
// chain issues, probes and serves inside one timestamp, and this is the only
// thing that advances the clock (2.5b). `gap_k == 0` is measured-absent from the
// corpus rather than assumed-absent (Q11), so the floor is not expected to bind;
// it is not thereby optional.
SimTime Engine::step_after(CoreId c, std::int32_t tile, BurstIndex k) const {
    const SimTime gap = as_duration(trace_.gap(c, tile, k));
    return gap < params_.core_accept_ii ? params_.core_accept_ii : gap;
}

// --- Part 5: the tile barrier ------------------------------------------------

void Engine::start_tile(std::int32_t tile, SimTime now) {
    cores_remaining_ = static_cast<std::int32_t>(cores_.size());

    for (std::size_t c = 0; c < cores_.size(); ++c) {
        const CoreId cid{static_cast<std::int32_t>(c)};
        CoreState& cs    = cores_[c];
        cs.tile          = tile;
        cs.cursor        = BurstIndex{0};
        cs.pending_lines = 0;
        cs.issued_at     = now;
        cs.served_time   = now;
        cs.phase         = Phase::Computing;

        // The fetch-ahead cursor starts over: the next tile's activations do not
        // exist until the barrier resolves, so the first burst of every tile is
        // never prefetched (4.6).
        prefetcher_->on_tile_start(cid);

        // A core that contributes nothing to this tile still has to clear the
        // barrier, and it clears it at the tile origin. The plan does not name
        // this case; the trace format permits it, since `n_bursts` is a count
        // per (core, tile) and nothing makes it positive.
        if (trace_.n_bursts(cid, tile) == 0) {
            barrier_arrive(cid, now);
            continue;
        }

        // The one place an absolute local tick enters, once per tile (4.5, N14).
        // Every later burst gets its spacing as a difference.
        queue_.schedule(now + trace_.local_tick(cid, tile, BurstIndex{0}), EventKind::Issue,
                        NoRefusal, cid, EventPayload{nullptr, nullptr, BurstIndex{0}, tile});
    }
}

void Engine::barrier_arrive(CoreId c, SimTime now) {
    cores_.at(idx(c)).phase = Phase::AtBarrier;

    // A countdown, not a scan (Part 5). No polling, and `barrier_slack_cycles`
    // falls out as the cost of the lock-step assumption.
    --cores_remaining_;
    if (cores_remaining_ > 0) return;

    // `tile_tail[N] = mac_cycles[N] - max_tick[N]`, the compute the tile still
    // owes after its last weights land, charged once at the tile level (Q10,
    // closed with corpus data: 0 across most of the corpus and 20 cycles, 11.7%
    // of the tile, on all 64 tiles of ptb layer_01 and layer_03). It is >= 1 by
    // construction, which is also what makes the seam advance the clock.
    const std::int32_t tile = cores_.at(idx(c)).tile;
    queue_.schedule(now + as_duration(trace_.tile_tail(tile)), EventKind::Barrier, NoRefusal,
                    CoreId{0}, EventPayload{nullptr, nullptr, BurstIndex{0}, tile});
}

void Engine::on_barrier(std::int32_t tile, SimTime now) {
    // `tile_origin` is a MEASURED quantity replacing the derived `tick_base`, and
    // this assignment is the measurement: `max over cores of served(c, last) +
    // tile_tail`, which is what `now` is here because the last service is what
    // scheduled this event.
    //
    // The class order is load-bearing rather than incidental: a core is served
    // inside its last demand fill, which is class 0, and this event is class 1,
    // so a barrier resolving in the same cycle observes the service. Reverse the
    // two and `tile_origin[N+1]` is set one service too early -- an exact-tick
    // effect, and reachable in the unbounded baseline where every latency is
    // zero (3.6, V26).
    tile_origin_.at(static_cast<std::size_t>(tile) + 1) = now;

    if (tile + 1 < trace_.n_tiles()) {
        start_tile(tile + 1, now);
        return;
    }
    for (CoreState& cs : cores_) cs.phase = Phase::Done;
}

// --- 3.4b: the core side -----------------------------------------------------

void Engine::on_issue(CoreId c, BurstIndex k, SimTime now) {
    CoreState& cs = cores_.at(idx(c));

    // I13's "service order is trace order", checked where it could first be
    // broken. The core has one burst in flight under every policy (4.5, I16), so
    // an issue for anything but the cursor is an engine that lost a service.
    if (!(k == cs.cursor)) {
        engine_error("on_issue", "core " + std::to_string(c.get()) + " was issued burst " +
                                     std::to_string(k.get()) + " while on burst " +
                                     std::to_string(cs.cursor.get()));
    }
    if (cs.pending_lines != 0) {
        engine_error("on_issue", "core " + std::to_string(c.get()) + " issued burst " +
                                     std::to_string(k.get()) + " with " +
                                     std::to_string(cs.pending_lines) +
                                     " lines of the previous burst outstanding (I16)");
    }

    const Burst& b = trace_.burst(c, cs.tile, k);
    lines_.clear();
    try {
        // N7: all or nothing. `expand` appends nothing at all when it throws
        // (layout.h), so a burst that leaves the layer cannot leave a partial
        // one behind.
        mapper_.expand(b, lines_);
    } catch (const std::out_of_range& e) {
        // U10 / decision B37, discharged here. `AddressMapper` is context-free by
        // construction: it holds the coordinate and the shape and cannot name the
        // tile, tick and core that V15 and N11 require. This is the ONE wrap
        // site, because `expand` is the only entry point the engine uses and
        // `line_of` is a helper the mapper calls on itself. The type survives, so
        // no downstream handler changes.
        //
        // The partial-tick half of that obligation (`layout.h:67-72`) is
        // discharged by the shape of v3 rather than by a decision here: v3 has no
        // per-tick accumulate buffer at all. A burst is expanded on its own, for
        // one core, inside its own `E_Issue`, so there is no half-filled tick for
        // this catch to decide the fate of.
        throw std::out_of_range(
            "Engine::on_issue: tile " + std::to_string(cs.tile) + ", tick " +
            std::to_string(trace_.local_tick(c, cs.tile, k).get()) + ", core " +
            std::to_string(c.get()) + ", burst " + std::to_string(k.get()) + ": " + e.what());
    }

    cs.pending_lines = static_cast<std::int32_t>(lines_.size());
    cs.issued_at     = now;
    cs.phase         = Phase::Stalled;

    CacheLevel& lvl = l1_.at(idx(c));
    for (const LineId line : lines_) {
        Request& r           = acquire(c, line, k, true);
        const SimTime accept = lvl.port(0).reserve(now);
        queue_.schedule(accept + lvl.port(0).latency(), EventKind::L1Probe, r.refusal, c,
                        EventPayload{&r, nullptr, k, cs.tile});
    }

    // 4.6, and the last line of 3.4b. Below the port; the core does not wait for
    // it and cannot observe it. Everything above would be identical if
    // prefetching did not exist.
    prefetcher_->on_demand_issue(*this, c, k, now);
}

void Engine::core_line_done(Request& r, SimTime now) {
    // A prefetch completes nobody (4.6, I15). The check is here rather than at
    // the two call sites so that neither can forget it.
    if (!r.demand) return;

    CoreState& cs = cores_.at(idx(r.core));
    if (cs.pending_lines <= 0) {
        engine_error("core_line_done", "core " + std::to_string(r.core.get()) +
                                           " completed a line with none outstanding");
    }
    --cs.pending_lines;
    // N7: the burst is atomic, so the core takes delivery only when the last
    // line of it lands.
    if (cs.pending_lines > 0) return;
    serve(r.core, now);
}

void Engine::serve(CoreId c, SimTime now) {
    CoreState& cs = cores_.at(idx(c));

    // `want` is the cycle the core's own schedule says this burst was due. For
    // the first burst of a tile it is the tile origin plus the trace's own tick;
    // after that it is the previous service plus the spacing the trace records.
    //
    // The `cursor == 0` test is 3.3's "served_time is NONE at a tile start". The
    // floor is switched OFF across the seam deliberately (4.5): left on, the one
    // core whose last service DEFINES `tile_origin[N+1]` could not take its
    // first burst of the new tile in that same cycle, and every tile would gain
    // a cycle over the trace.
    const SimTime want = cs.cursor == BurstIndex{0}
                             ? tile_origin_.at(static_cast<std::size_t>(cs.tile)) +
                                   trace_.local_tick(c, cs.tile, BurstIndex{0})
                             : cs.served_time +
                                   step_after(c, cs.tile, BurstIndex{cs.cursor.get() - 1});

    // I13, and the plan asks for it "asserted rather than enforced": it is
    // satisfied BY CONSTRUCTION, because the run-ahead lives in the memory
    // system and never delivers anything to the core, so the core cannot receive
    // burst k+1 before it has asked for it. The floor therefore never binds and
    // this check exists to catch a future core-side policy that would violate it
    // silently. A throw and not an assert: the sweep build is -DNDEBUG, and an
    // assert compiled out turns a violated floor into a plausible timeline.
    if (now < want) {
        engine_error("serve", "core " + std::to_string(c.get()) + " burst " +
                                  std::to_string(cs.cursor.get()) + " was served at " +
                                  std::to_string(now.get()) + ", before its own schedule allows (" +
                                  std::to_string(want.get()) + ") (I13)");
    }

    // The two Part 8 quantities 3.4b writes by name. With prefetching off they
    // are equal by construction and reporting both is a free consistency check;
    // with it on, their DIFFERENCE is the latency the policy hid, and it is the
    // single number the policy should be judged on.
    stats_.core_stall.at(idx(c)) += (now - want).get();
    stats_.fetch_latency.at(idx(c)) += (now - cs.issued_at).get();

    cs.served_time = now;
    cs.cursor      = BurstIndex{cs.cursor.get() + 1};

    if (cs.cursor.get() == trace_.n_bursts(c, cs.tile)) {
        // The core arrives at the barrier at its own last service. The tile's
        // remaining compute is charged once at the tile level instead, which is
        // what keeps `barrier_slack_cycles` measuring what it measures (4.5, Q10).
        barrier_arrive(c, now);
        return;
    }

    cs.phase = Phase::Computing;
    queue_.schedule(now + step_after(c, cs.tile, BurstIndex{cs.cursor.get() - 1}),
                    EventKind::Issue, NoRefusal, c,
                    EventPayload{nullptr, nullptr, cs.cursor, cs.tile});
}

// --- C5's sink ---------------------------------------------------------------

std::int32_t Engine::n_bursts_in_tile(CoreId core) const {
    const CoreState& cs = cores_.at(idx(core));
    return trace_.n_bursts(core, cs.tile);
}

bool Engine::issue_prefetch(CoreId core, BurstIndex k, SimTime now) {
    const CoreState& cs = cores_.at(idx(core));

    pf_lines_.clear();
    // No context wrap here, and that is deliberate rather than an omission: a
    // prefetch walks the same address run the core will walk, so a coordinate
    // that leaves the layer here would leave it at the demand issue too, where
    // `on_issue`'s catch names the tile, tick and core. Wrapping it twice would
    // report the failure against a burst the core has not reached yet.
    mapper_.expand(trace_.burst(core, cs.tile, k), pf_lines_);

    CacheLevel& lvl        = l1_.at(idx(core));
    std::int32_t& in_fly   = stats_.pf_outstanding.at(idx(core));
    const std::int32_t cap = lvl.mshrs().capacity() - lvl.mshrs().demand_reserve();

    for (const LineId line : pf_lines_) {
        // The budget, and nothing downstream, is what stops the prefetcher
        // (N16, I14). It is `l1_mshrs - l1_demand_reserve`, so at
        // `l1_mshrs == lines_per_burst` it is zero and prefetching is off no
        // matter what `prefetch_distance` says (4.2).
        if (in_fly >= cap) {
            ++stats_.pf_budget_exhausted;
            return false;
        }
        Request& r = acquire(core, line, k, false);
        // A REAL port slot: at `l1_ii = 1` every prefetch takes a cycle the
        // demand stream could have used, which is one of the four things 4.6
        // says this costs.
        const SimTime accept = lvl.port(0).reserve(now);
        queue_.schedule(accept + lvl.port(0).latency(), EventKind::L1Probe, r.refusal, core,
                        EventPayload{&r, nullptr, k, cs.tile});
        ++in_fly;
    }
    return true;
}

}  // namespace wcache
