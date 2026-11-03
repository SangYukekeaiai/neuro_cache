// Pluggable prefetch policy interface.
#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "cachesim/core/request.h"
#include "cachesim/layout/mapper.h"
#include "cachesim/trace/tile_trace.h"
#include "cachesim/types.h"

namespace cachesim {

// Prefetch policies suggest targets; the owning CacheLevel and Engine issue
// them. This separation is the Phase 3 boundary: a policy may inspect the
// resolved trace and mapper, but it cannot reserve a port, allocate an MSHR,
// inspect cache contents, or add anything to a wait index.
//
// That one-way boundary is the reason the PE is not changed. The core has
// already issued its demand lines before this hook runs, and the hook can only
// append descriptions of optional work. Consequently the service floor still
// comes from the core's own recurrence rather than from a prefetch callback.
//
// N16 is enforced at the issue site, where the level knows its credit budget:
// L1 uses `l1_mshrs - l1_demand_reserve`, while L2 uses its bank and triage
// path. A budget can run out in the middle of a burst; the policy receives
// feedback only for a burst whose targets were all accepted, so a partial
// burst does not advance its cursor. This keeps the budget boundary out of the
// policy interface and leaves the level responsible for all resource effects.
//
// I14 has the corresponding split responsibility: NextAccess's cursor obeys
// `0 <= pf_cursor(c) - cursor(c) <= 1 + prefetch_distance`, while the engine
// bounds outstanding L1 work by the credit budget. Keeping those two facts in
// separate objects prevents a policy from accidentally changing timing or
// admission semantics when it is selected at the other cache level.
struct PrefetchContext {
    Level                level;
    CoreId               core;
    int                  tile;
    BurstIndex           k;
    LineId               line;
    SimTime              now;
    const AddressMapper& mapper;
    const TileTrace&     trace;
    // True only for the L2 retrigger (a demand hit on a still-unused
    // prefetched line). DistanceAware's touch filter exempts it: the filter gates
    // which lines start a prefetch chain, and a started chain sustains itself
    // through retriggers (the miss-only pathology at engine.cpp's trigger).
    bool                 retrigger = false;
};

struct PrefetchTarget {
    // The burst tag is retained even for line-oriented policies so the engine
    // can apply timely/late accounting and complete NextAccess feedback at a
    // whole-burst boundary.
    LineId     line;
    BurstIndex burst;
};

enum class PrefetchKind : std::uint8_t { None = 0, NextAccess = 1, Neighbour = 2, DistanceAware = 3 };

struct PrefetchParams {
    std::int32_t distance = 0;
    Axis         axis     = Axis::CIN;
    bool         up       = true;
    bool         down     = true;
    // DistanceAware's touch filter: a line may trigger only once the cores have
    // touched it at least this many times in the current tile. 0 = off.
    // Read only by DistanceAware; every other policy ignores it.
    std::int32_t min_touches = 0;
};

class Prefetcher {
public:
    virtual ~Prefetcher() = default;

    // A tile boundary is a real policy boundary: a prefetcher must not carry a
    // cursor into activations that are not present in the one-tile trace window.
    virtual void on_tile_start(CoreId) {}

    // Called once per demand line and appends ordered targets to `out`. The
    // caller owns the scratch vector and all issue mechanics; a policy never
    // waits, refuses, or registers a target itself.
    virtual void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) = 0;

    // Feedback arrives only after every target in a burst was accepted. A
    // partial issue, including one stopped by N16's budget, deliberately has
    // no completion callback.
    virtual void on_issued(CoreId, BurstIndex) {}

    // One demand touch of `line` in `tile`, as the CORES see it: the engine
    // calls this on every demand L1 probe (the same guard as `l1_accesses`),
    // so L1 hits count and an L2 eviction cannot erase a line's evidence of
    // reuse. Returns true when this touch fires the policy's trigger (once
    // per line and tile); the base is a no-op that never fires. Wired for
    // the L2 policy only.
    virtual bool on_access(LineId, std::int32_t /*tile*/) { return false; }

    // How many on_demand triggers a policy's own filter suppressed, for the
    // run's close-out (`l2_pf_filtered`). 0 for every unfiltered policy.
    virtual std::int64_t filtered_triggers() const { return 0; }

protected:
    Prefetcher()                             = default;
    Prefetcher(const Prefetcher&)            = default;
    Prefetcher(Prefetcher&&)                 = default;
    Prefetcher& operator=(const Prefetcher&) = default;
    Prefetcher& operator=(Prefetcher&&)      = default;
};

std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind kind,
                                            PrefetchParams params,
                                            std::int32_t n_cores);

}  // namespace cachesim
