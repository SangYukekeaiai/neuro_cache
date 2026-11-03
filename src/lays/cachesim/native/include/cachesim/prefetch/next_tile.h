#pragma once

#include <cstdint>
#include <unordered_map>

#include "cachesim/prefetch/prefetcher.h"

namespace cachesim {

// L2 policy: emit the next distance COUT blocks, forward only.
// PrefetchParams::axis, up and down are ignored; the axis is always COUT
// and each step is one block. Targets outside the COUT extent are skipped.
//
// The touch filter (plan 2026-11-01): a line may trigger only once the cores
// have touched it at least `min_touches` times in the current tile. A touch
// is a demand L1 probe fed through on_access, so L1 hits count and cache
// state cannot erase it; counts reset lazily at the tile boundary; the
// comparison is `count >= min_touches`, so 0 disables the filter and is the
// pre-filter policy exactly; a retrigger (ctx.retrigger) bypasses the filter
// so a chain started by a qualifying line stays alive.
class NextTilePrefetcher final : public Prefetcher {
public:
    explicit NextTilePrefetcher(std::int32_t distance, std::int32_t min_touches = 0);

    void on_demand(const PrefetchContext&, std::vector<PrefetchTarget>& out) override;
    // Returns true exactly when the post-increment count for (line, tile)
    // equals max(min_touches, 1): once per line per tile, re-armed by the
    // lazy reset at a tile change.
    bool on_access(LineId line, std::int32_t tile) override;
    std::int64_t filtered_triggers() const override { return filtered_; }

private:
    struct TouchRecord {
        std::int32_t tile  = -1;
        std::int32_t count = 0;
    };

    std::int32_t distance_;
    std::int32_t min_touches_;
    std::int64_t filtered_ = 0;
    std::unordered_map<std::int64_t, TouchRecord> touches_;
};

}  // namespace cachesim
