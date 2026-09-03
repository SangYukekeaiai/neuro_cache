#include "wcache/prefetcher.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace wcache {

void NoPrefetcher::on_demand_issue(PrefetchIssuer&, CoreId, BurstIndex, SimTime) {}
void NoPrefetcher::on_tile_start(CoreId) {}

NextBurstPrefetcher::NextBurstPrefetcher(std::int32_t distance, std::int32_t n_cores)
    : distance_(distance) {
    if (distance < 1) {
        throw std::invalid_argument(
            "NextBurstPrefetcher: prefetch_distance must be >= 1, got " +
            std::to_string(distance) + " (distance 0 is prefetch_policy = none)");
    }
    if (n_cores < 1) {
        throw std::invalid_argument("NextBurstPrefetcher: n_cores must be >= 1, got " +
                                    std::to_string(n_cores));
    }
    pf_cursor_.assign(static_cast<std::size_t>(n_cores), 0);
}

BurstIndex NextBurstPrefetcher::pf_cursor(CoreId core) const {
    return BurstIndex{pf_cursor_.at(static_cast<std::size_t>(core.get()))};
}

void NextBurstPrefetcher::on_tile_start(CoreId core) {
    // The next tile's activations do not exist until the barrier resolves, so
    // the first burst of every tile is never prefetched and the cursor starts
    // over rather than being carried across the seam (4.6).
    pf_cursor_.at(static_cast<std::size_t>(core.get())) = 0;
}

// 4.6's `next_burst(d)`, line for line.
void NextBurstPrefetcher::on_demand_issue(PrefetchIssuer& mem,
                                          CoreId core,
                                          BurstIndex k,
                                          SimTime now) {
    std::int32_t& cursor = pf_cursor_.at(static_cast<std::size_t>(core.get()));

    // Never behind the core. A demand issue of burst `k` means every burst up to
    // `k` is already the core's business, so a cursor that lagged would spend
    // credits fetching lines the core has already asked for.
    const std::int32_t next = k.get() + 1;
    if (cursor < next) cursor = next;

    const std::int32_t last    = k.get() + distance_;
    const std::int32_t n_burst = mem.n_bursts_in_tile(core);

    while (cursor <= last && cursor < n_burst) {
        // Stops on the BUDGET and never on a refusal (N16). The cursor is not
        // advanced when the budget runs out part way, so the same burst is tried
        // again at the next demand issue, by which time its own fills have
        // returned credits.
        if (!mem.issue_prefetch(core, BurstIndex{cursor}, now)) return;
        ++cursor;
    }
}

std::unique_ptr<Prefetcher> make_prefetcher(PrefetchKind kind,
                                            std::int32_t distance,
                                            std::int32_t n_cores) {
    switch (kind) {
        case PrefetchKind::None:
            // A distance is accepted and ignored here, because 2.5b's default
            // pairs `prefetch_policy = none` with `prefetch_distance = 0` and a
            // sweep grid crosses the two axes. D1's row owns the cross-field
            // rule; what this refuses is a distance that is not a number of
            // bursts at all.
            if (distance < 0) {
                throw std::invalid_argument(
                    "make_prefetcher: prefetch_distance must be >= 0, got " +
                    std::to_string(distance));
            }
            return std::make_unique<NoPrefetcher>();
        case PrefetchKind::NextBurst:
            return std::make_unique<NextBurstPrefetcher>(distance, n_cores);
    }
    // Unreachable: the switch covers every enumerator. Reported rather than
    // defaulted to `none`, which is the one wrong answer here -- a run that
    // silently prefetched nothing would look exactly like a result.
    throw std::logic_error("make_prefetcher: unknown PrefetchKind");
}


// --- the L2 side -------------------------------------------------------------

void NoL2Prefetcher::suggest(const AddressMapper&, LineId, std::vector<LineId>&) const {}

NeighbourL2Prefetcher::NeighbourL2Prefetcher(Axis axis, std::int32_t distance, bool up, bool down)
    : axis_(axis), distance_(distance), up_(up), down_(down) {
    if (distance < 1) {
        throw std::invalid_argument("NeighbourL2Prefetcher: distance " +
                                    std::to_string(distance) +
                                    " is below 1; distance 0 is NoL2Prefetcher");
    }
    // Neither direction is NoL2Prefetcher wearing this class's name, and two
    // spellings of one behaviour is what the distance rule above refuses.
    if (!up && !down) {
        throw std::invalid_argument("NeighbourL2Prefetcher: both directions are off, "
                                    "which is NoL2Prefetcher; set the policy to none");
    }
}

void NeighbourL2Prefetcher::suggest(const AddressMapper& mapper, LineId line,
                                    std::vector<LineId>& out) const {
    // Near first, both ways, so that a budget that runs out part way through
    // spends what it had on the closest lines rather than the furthest.
    for (std::int32_t d = 1; d <= distance_; ++d) {
        if (up_) {
            if (const std::optional<LineId> up = mapper.neighbour(line, axis_, d)) {
                out.push_back(*up);
            }
        }
        if (down_) {
            if (const std::optional<LineId> dn = mapper.neighbour(line, axis_, -d)) {
                out.push_back(*dn);
            }
        }
    }
}

std::unique_ptr<L2Prefetcher> make_l2_prefetcher(L2PrefetchKind kind, Axis axis,
                                                 std::int32_t distance, bool up, bool down) {
    switch (kind) {
        case L2PrefetchKind::None:      return std::make_unique<NoL2Prefetcher>();
        case L2PrefetchKind::Neighbour: return std::make_unique<NeighbourL2Prefetcher>(axis, distance, up, down);
    }
    throw std::invalid_argument("make_l2_prefetcher: unknown L2PrefetchKind");
}

}  // namespace wcache
