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
// I14 has the corresponding split responsibility: NextBurst's cursor obeys
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
};

struct PrefetchTarget {
    // The burst tag is retained even for line-oriented policies so the engine
    // can apply timely/late accounting and complete NextBurst feedback at a
    // whole-burst boundary.
    LineId     line;
    BurstIndex burst;
};

enum class PrefetchKind : std::uint8_t { None = 0, NextBurst = 1, Neighbour = 2 };

struct PrefetchParams {
    std::int32_t distance = 0;
    Axis         axis     = Axis::CIN;
    bool         up       = true;
    bool         down     = true;
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
