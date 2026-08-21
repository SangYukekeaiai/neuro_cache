// DistinctAddressHistogram: G14's per-(core, tile) distinct-address diagnostic
// and its sidecar file. Plan D unit D2d, Task 14.
//
// Ruling R6 demoted G14 from an axis-siting gate to an EXPLANATORY diagnostic.
// It explains, per architecture, why each L1 curve has the shape it has, and in
// particular the LoAS/Spinalflow versus PTB cross-tile reuse difference. It
// GATES NOTHING and its outcome does not change the L1 axis. It is free because
// the reader has already touched every burst of the tile by the time it is
// asked.
//
// The histogram is a property of the TRACE, not of a cache configuration, so it
// is collected once per stream and written to its own file rather than smeared
// over every row of a sweep. Two summary columns of the results CSV,
// `distinct_addr_per_core_tile_p50` and `_max`, carry its shape into the row.
//
// It takes no AddressMapper, and that is the substance of the quantity rather
// than an omission. `StreamingTileTrace::distinct_addresses` counts distinct
// address TUPLES; a line count would depend on `cin_block` and `cout_block` and
// so would be a property of the configuration, one number per sweep point
// rather than one per trace. The tuple count is also what §1.3's survey
// measured (24 addresses, 384 B per core per tile), so it is the one comparable
// to it.
#pragma once

#include <algorithm>
#include <cstdint>
#include <ostream>
#include <vector>

#include "wcache/stream_format.h"
#include "wcache/stream_trace.h"

namespace wcache {

class DistinctAddressHistogram {
public:
    // The header supplies both the identity columns of the sidecar and the core
    // count. `n_cores` is not taken separately: the stream states it once, and a
    // second copy is a second place for it to disagree.
    explicit DistinctAddressHistogram(const stream::StreamHeader& hdr)
        : hdr_(hdr), n_cores_(hdr.n_cores) {}

    // Call once per tile, after StreamingTileTrace::advance() returns true.
    // Every core is recorded, including one with no bursts in this tile: an
    // omitted zero would bias the p50 upwards, which for a diagnostic about
    // working-set size is the wrong direction.
    void observe(const StreamingTileTrace& trace) {
        tiles_.push_back(trace.window_tile());
        for (std::int32_t c = 0; c < n_cores_; ++c) {
            counts_.push_back(trace.distinct_addresses(CoreId{c}));
        }
    }

    // "arch,workload,layer,sample_idx,tile,core,distinct_addresses" plus a
    // header line. Rows are tile-major, core-minor, in observation order.
    void write_csv(std::ostream& out) const {
        out << "arch,workload,layer,sample_idx,tile,core,distinct_addresses\n";
        for (std::size_t t = 0; t < tiles_.size(); ++t) {
            for (std::int32_t c = 0; c < n_cores_; ++c) {
                out << hdr_.arch << ',' << hdr_.workload << ',' << hdr_.layer << ','
                    << hdr_.sample_idx << ',' << tiles_[t] << ',' << c << ','
                    << counts_[t * static_cast<std::size_t>(n_cores_) +
                               static_cast<std::size_t>(c)]
                    << '\n';
            }
        }
    }

    // Nearest rank over every (core, tile) sample: the value at index
    // min(n - 1, floor(0.5 * n)) of the sorted samples. The same convention the
    // results CSV uses for the MSHR occupancy percentiles, so the two summaries
    // in one row are read the same way.
    std::int32_t p50() const { return quantile(0.5); }

    std::int32_t max() const {
        if (counts_.empty()) return 0;
        return *std::max_element(counts_.begin(), counts_.end());
    }

    // How many (core, tile) samples were recorded. Reported so a reader can see
    // whether a p50 rests on nine samples or nine hundred.
    std::int64_t samples() const { return static_cast<std::int64_t>(counts_.size()); }

private:
    std::int32_t quantile(double q) const {
        if (counts_.empty()) return 0;
        std::vector<std::int32_t> sorted = counts_;
        std::sort(sorted.begin(), sorted.end());
        std::size_t i = static_cast<std::size_t>(q * static_cast<double>(sorted.size()));
        if (i >= sorted.size()) i = sorted.size() - 1;
        return sorted[i];
    }

    stream::StreamHeader      hdr_;
    std::int32_t              n_cores_;
    std::vector<std::int32_t> tiles_;   // the tile index of each observation
    std::vector<std::int32_t> counts_;  // n_cores_ entries per observation
};

}  // namespace wcache
