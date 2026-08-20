// Prefetcher: when a line is FETCHED, which is a policy (P6).
//
// Plan v3 Part 7, unit C5: "`Prefetcher` interface, `none`, and `next_burst(d)`;
// the `demand = false` triage rules and the drop rule (4.6, N15, N16)", whose
// exit criterion is that "`none` reproduces C3's event log byte-identically" and
// that "no prefetch ever appears on a wait index".
//
// The whole of 4.6 rests on one boundary and this header is where it is drawn:
// the prefetcher lives at the L1, BELOW the port, and the PE is not changed. It
// has no way to deliver anything to a core, and 3.4b's `E_Issue` reaches it
// through one call that returns nothing. So the service floor
// `served(c, k+1) >= served(c, k) + core_accept_ii` holds by construction rather
// than by enforcement (4.5, N15): a core cannot receive burst `k+1` before it
// has asked for it, and it does not ask before its own recurrence says so.
//
// The other rule the interface exists to make unbreakable is N16: "a prefetcher
// is bounded by a credit budget or it is not admissible". `issue_prefetch`
// returns false when the budget is out and the policy stops; nothing here can
// wait, be refused, or register anywhere, which is what keeps the waiting
// population backed one-for-one by demand credits (4.1) and leaves the v2
// arithmetic standing verbatim at any `prefetch_distance`.
#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "wcache/types.h"

namespace wcache {

// 2.5b's `prefetch_policy`. `none` is the machine as built and is the default.
enum class PrefetchKind : std::uint8_t { None = 0, NextBurst = 1 };

// What a prefetcher may ask of the memory system, and the whole of it.
//
// Deliberately two calls and no more. A prefetcher that could read a core's
// cursor, a cache's contents, or an MSHR's occupancy would be able to make
// decisions the PE can observe, and "the PE is not changed" would become an
// argument rather than a property. It can ask how long the current tile is, and
// it can ask for a burst to be fetched; the answer to the second is the budget,
// not a refusal.
class PrefetchIssuer {
public:
    virtual ~PrefetchIssuer() = default;

    // Bursts in the tile core `core` is on now. The policy needs it to stop at
    // the end of a tile: "the policy never crosses a tile boundary, since the
    // next tile's activations do not exist until the barrier resolves" (4.6).
    virtual std::int32_t n_bursts_in_tile(CoreId core) const = 0;

    // Fetches every line of burst `k` of core `core`'s current tile as
    // `demand = false` requests, each through a REAL L1 port slot.
    //
    // Returns false when the credit budget `l1_mshrs - l1_demand_reserve` ran
    // out part way, which is N16's "bounded HERE": the prefetcher stops on its
    // budget and never on a downstream refusal. A partial burst is what 4.6's
    // pseudocode does too, since its budget check `return`s from inside the
    // per-line loop; the cursor is not advanced, so the remainder is retried on
    // a later demand issue and the lines already in flight are then dropped at
    // their matching entries.
    virtual bool issue_prefetch(CoreId core, BurstIndex k, SimTime now) = 0;

protected:
    PrefetchIssuer()                                 = default;
    PrefetchIssuer(const PrefetchIssuer&)            = default;
    PrefetchIssuer(PrefetchIssuer&&)                 = default;
    PrefetchIssuer& operator=(const PrefetchIssuer&) = default;
    PrefetchIssuer& operator=(PrefetchIssuer&&)      = default;
};

// 4.6's interface: "One hook, called from `E_Issue` (3.4b), returning nothing".
class Prefetcher {
public:
    virtual ~Prefetcher() = default;

    // Called at the end of `E_Issue`, after the demand lines are already on
    // their way. It returns nothing, and that is what "the PE is not changed"
    // means operationally: C5 is reachable from the core only through a call
    // that cannot affect it.
    virtual void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) = 0;

    // A new tile began for `core`, so any fetch-ahead cursor resets.
    //
    // The plan states the BEHAVIOUR -- "the policy never crosses a tile
    // boundary... the first burst of every tile is never prefetched" (4.6) --
    // and not the hook. It is needed rather than convenient: `pf_cursor` is
    // carried across the barrier otherwise, and a tile with more bursts than the
    // last would resume fetching from the old cursor, skipping every burst below
    // it and never fetching them at all.
    virtual void on_tile_start(CoreId core) = 0;

protected:
    Prefetcher()                             = default;
    Prefetcher(const Prefetcher&)            = default;
    Prefetcher(Prefetcher&&)                 = default;
    Prefetcher& operator=(const Prefetcher&) = default;
    Prefetcher& operator=(Prefetcher&&)      = default;
};

// 4.6's `none`: `on_demand_issue(c, k, now): pass`.
//
// A real class rather than a null pointer the engine tests for, so the engine
// has one code path and C5's exit criterion ("`none` reproduces C3's event log
// byte-identically") is a property of a call that does nothing rather than of a
// branch that is not taken.
class NoPrefetcher final : public Prefetcher {
public:
    void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) override;
    void on_tile_start(CoreId core) override;
};

// 4.6's `next_burst(d)`: while the core is stalled on burst `k`, the L1 pulls in
// bursts up to `k + d`.
//
// It does not predict. "Within a tile, the weight address generator walks a
// spike queue that is resolved when the tile begins, so the address run is
// derivable ahead of time" -- which is a claim about the hardware, and 4.6 says
// it belongs in the write-up. A design whose spike queue is produced
// incrementally during the tile cannot run this policy at all.
class NextBurstPrefetcher final : public Prefetcher {
public:
    // `distance` is 4.6's `d` and must be >= 1: `d = 0` is `none` by another
    // name, and a policy that claims to be on while fetching nothing is the
    // configuration D1's row refuses outright. std::invalid_argument, following
    // decision B95's rule that a refused config value is not a stub.
    NextBurstPrefetcher(std::int32_t distance, std::int32_t n_cores);

    void on_demand_issue(PrefetchIssuer& mem, CoreId core, BurstIndex k, SimTime now) override;
    void on_tile_start(CoreId core) override;

    std::int32_t distance() const { return distance_; }

    // The next burst index this core will fetch ahead to. Half of I14,
    // `0 <= pf_cursor(c) - cursor(c) <= 1 + prefetch_distance`; the other half,
    // `pf_outstanding(c) <= l1_mshrs - l1_demand_reserve`, is the engine's,
    // because the budget is a cache credit and not policy state.
    //
    // On the concrete class rather than on `Prefetcher`, because `none` has no
    // cursor and inventing one for it would make I14 pass by construction on the
    // configuration where it has nothing to say.
    BurstIndex pf_cursor(CoreId core) const;

private:
    std::int32_t distance_;
    std::vector<std::int32_t> pf_cursor_;
};

// The `prefetch_policy` config value, as an object.
//
// Throws std::invalid_argument for a `NextBurst` with `distance < 1`, and for
// any negative distance. `make_policy`'s shape and decision B95's reasoning: a
// refused config value must survive `-DNDEBUG` and must read as a rejected
// configuration rather than as unfinished code.
std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind kind,
                                            std::int32_t distance,
                                            std::int32_t n_cores);

}  // namespace wcache
