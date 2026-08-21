// TileTrace: the per-(core, tile) burst lists the core state machine reads.
//
// Plan v3 Part 7, unit A3, whose contents row is "`TraceReader`: format v2
// headers, tile/tick/core/burst decode, `spatial_factors` core decode, **plus
// the per-(core, tile) ordered burst list that 4.5 needs**: `n_bursts(c, tile)`,
// `local_tick(c, k)`, `gap(c, k)` as a difference, and the tile's `mac_cycles`,
// from which `tile_tail` is derived (Q10)".
//
// This header is the INTERFACE half of that row and nothing else. Unit A3 is
// unbuilt, and the plan's own critical path says "C3 cannot finish without A3's
// burst lists", so C3 is built against the abstract query surface A3's row
// names and A3 implements it over the real corpus. That is the same split A2
// already uses, `AddressMapper` in layout.h against `BlockPackMapper` in
// block_pack.h (decisions B10, B23): the engine holds the abstraction and never
// learns which trace reader it has, so a fixture can drive the engine from a
// hand-written trace without a corpus file.
//
// Part 5 is why every query below is tile-local. "Trace time is only ever
// tile-local. The engine never uses `tick_base`", and the engine's own
// recurrence is
//
//     issue(c, 0)   = tile_origin[tile] + local_tick(c, 0)
//     issue(c, k+1) = served(c, k) + max(gap_k, core_accept_ii)
//
// so an absolute trace tick enters exactly once per tile and every later burst
// gets its spacing as a DIFFERENCE (4.5, N14, D13). An implementation that
// returned an absolute tick from `gap` would be caught by neither the types nor
// the engine: it would produce a plausible timeline in which stalls are
// absorbed rather than carried, which is the defect D13 exists to close.
#pragma once

#include <cstdint>

#include "wcache/types.h"

namespace wcache {

// Read-only, and one instance serves the whole run.
//
// Tiles and cores are plain `std::int32_t` indices rather than tagged scalars,
// with the exception of `CoreId`, which already exists. A tile index has no
// tagged type today and adding one is A3's call, not this header's: the engine
// holds the tile index in one field of one struct (`CoreState::tile`) and
// passes it straight back here.
class TileTrace {
public:
    virtual ~TileTrace() = default;

    // How many tiles this trace holds, and how many cores it describes. The
    // barrier is machine-wide (N4), so every core walks the same tile sequence
    // and `n_cores` is a property of the trace rather than of a core.
    virtual std::int32_t n_tiles() const = 0;
    virtual std::int32_t n_cores() const = 0;

    // How many bursts core `core` issues inside `tile`. Zero is legal: a core
    // that contributes nothing to a tile still has to clear the barrier.
    virtual std::int32_t n_bursts(CoreId core, std::int32_t tile) const = 0;

    // Burst `k` of core `core` inside `tile`, in TRACE ORDER, which is also
    // service order (I13). Returned by reference because the engine hands it
    // straight to `AddressMapper::expand` and never keeps it.
    //
    // Precondition: `0 <= k < n_bursts(core, tile)`.
    virtual const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const = 0;

    // The trace's own tick for burst `k`, as an OFFSET inside the tile.
    //
    // The engine reads this for `k == 0` only, which is 4.5's "absolute local
    // ticks enter only at the first burst of a tile". It is on the interface for
    // every `k` because the diagnostic path wants the tick of the burst that
    // failed (N11, V15) and because `gap` is defined from it.
    virtual LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const = 0;

    // `local_tick(k+1) - local_tick(k)`: the spacing the trace records between
    // two consecutive bursts, which 4.5 reads as the MAC work burst `k`'s
    // weights feed. A DURATION the core owes after the weights arrive, never an
    // appointment it can be late for.
    //
    // Precondition: `0 <= k < n_bursts(core, tile) - 1`.
    //
    // Exactly 1 over the corpus, min and max alike (Q11, discharged 2026-08-20
    // by the survey of 124 format v2 layers and 76,150,578 bursts: no (core,
    // tick) pair anywhere carries more than one burst, so burst index and local
    // tick are in bijection inside a (core, tile)). The `gap == 0` count A3 owed
    // is therefore 0 and V20's shift is exact; the engine does not assume it,
    // since `max(gap, core_accept_ii)` is what advances the clock either way.
    virtual LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const = 0;

    // `mac_cycles[tile] - max_tick[tile]`, the compute the tile still owes after
    // its last weight burst is served (Q10, closed 2026-08-17 with corpus data,
    // numbers corrected 2026-08-20 by the full survey).
    //
    // Charged once at the tile level rather than per core, because the trace
    // stores `mac_cycles` already reduced to the max over that tile's cores, so
    // per-core tails do not exist on disk. Over the 124 format v2 layers the
    // tail is never 0: it is 1 on 116 of them, and runs 1 to 22 on the other 8,
    // all ptb, the largest being 17 to 22 over 64 tiles with mode 21. So
    // charging nothing was not a safe default.
    //
    // `>= 1` by construction, which the engine relies on for more than accuracy:
    // it is what makes the tile seam advance the clock, so a tile whose cores
    // all issue nothing cannot leave the barrier firing at its own timestamp
    // forever.
    virtual LocalTick tile_tail(std::int32_t tile) const = 0;

protected:
    // Protected and defaulted, for the reason decision B67 settled at
    // `CacheArray` and decision B92 reused at `ReplacementPolicy`: through two
    // base references `t1 = t2` would compile and assign the base subobject
    // only. Protected keeps a derived reader copyable as itself and leaves the
    // base unusable as either side of an assignment.
    TileTrace()                            = default;
    TileTrace(const TileTrace&)            = default;
    TileTrace(TileTrace&&)                 = default;
    TileTrace& operator=(const TileTrace&) = default;
    TileTrace& operator=(TileTrace&&)      = default;
};

}  // namespace wcache
