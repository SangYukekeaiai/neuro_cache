#include "wcache/stream_trace.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <stdexcept>
#include <string>

namespace wcache {

namespace {

// tile_index, n_core_blocks, mac_cycles, payload_bytes.
constexpr std::size_t kFramePrefixBytes = 24;
// local_tick plus the five address fields.
constexpr std::size_t kBurstRecordBytes = 8 + 4 * 5;
// end_magic, total_bursts.
constexpr std::size_t kTrailerBytes = 12;

std::string span(std::int32_t core, std::int32_t tile) {
    return "core " + std::to_string(core) + ", tile " + std::to_string(tile);
}

}  // namespace

StreamingTileTrace::StreamingTileTrace(ByteSource& src) : src_(&src) {
    std::vector<unsigned char> buf(stream::kFixedHeaderBytes);
    if (!src_->read_exact(buf.data(), buf.size())) {
        throw std::runtime_error("StreamingTileTrace: the stream is empty, expected a "
                                 "WCTS header of at least " +
                                 std::to_string(stream::kFixedHeaderBytes) + " bytes");
    }
    const std::uint32_t header_bytes = stream::read_le<std::uint32_t>(buf.data() + 12);
    if (header_bytes < stream::kFixedHeaderBytes) {
        throw std::invalid_argument("WCTS header: header_bytes is " +
                                    std::to_string(header_bytes) +
                                    ", below the fixed header length " +
                                    std::to_string(stream::kFixedHeaderBytes));
    }
    const std::size_t rest = header_bytes - stream::kFixedHeaderBytes;
    if (rest > 0) {
        buf.resize(header_bytes);
        if (!src_->read_exact(buf.data() + stream::kFixedHeaderBytes, rest)) {
            throw std::runtime_error("StreamingTileTrace: the stream ended after the fixed "
                                     "header, " + std::to_string(rest) +
                                     " further header bytes were declared");
        }
    }
    header_ = stream::decode_header(buf.data(), buf.size());

    const std::size_t tiles = static_cast<std::size_t>(header_.n_tiles);
    mac_cycles_.assign(tiles, 0);
    tile_tail_.assign(tiles, 0);
    tick_base_.assign(tiles + 1, 0);
    core_begin_.assign(static_cast<std::size_t>(header_.n_cores), 0);
    core_end_.assign(static_cast<std::size_t>(header_.n_cores), 0);
}

std::int32_t StreamingTileTrace::n_tiles() const { return header_.n_tiles; }

std::int32_t StreamingTileTrace::n_cores() const { return header_.n_cores; }

void StreamingTileTrace::require_window(std::int32_t tile) const {
    if (tile != window_) {
        throw std::out_of_range(
            "StreamingTileTrace: tile " + std::to_string(tile) +
            " is outside the window, which holds tile " + std::to_string(window_) +
            ". A one-tile sliding window answers only for the tile it holds.");
    }
}

void StreamingTileTrace::require_core(CoreId core) const {
    if (core.get() < 0 || core.get() >= header_.n_cores) {
        throw std::out_of_range("StreamingTileTrace: core " + std::to_string(core.get()) +
                                " is outside [0, " + std::to_string(header_.n_cores) + ")");
    }
}

void StreamingTileTrace::require_streamed(std::int32_t tile, const char* what) const {
    if (tile < 0 || tile >= streamed_) {
        throw std::out_of_range(std::string("StreamingTileTrace: ") + what + " asked for tile " +
                                std::to_string(tile) + ", but only tiles [0, " +
                                std::to_string(streamed_) + ") have been streamed");
    }
}

std::int32_t StreamingTileTrace::n_bursts(CoreId core, std::int32_t tile) const {
    require_window(tile);
    require_core(core);
    const std::size_t c = static_cast<std::size_t>(core.get());
    return core_end_[c] - core_begin_[c];
}

const Burst& StreamingTileTrace::burst(CoreId core, std::int32_t tile, BurstIndex k) const {
    const std::int32_t n = n_bursts(core, tile);
    if (k.get() < 0 || k.get() >= n) {
        throw std::out_of_range("StreamingTileTrace: burst " + std::to_string(k.get()) +
                                " of " + span(core.get(), tile) + " is outside [0, " +
                                std::to_string(n) + ")");
    }
    const std::size_t c = static_cast<std::size_t>(core.get());
    return bursts_[static_cast<std::size_t>(core_begin_[c] + k.get())];
}

LocalTick StreamingTileTrace::local_tick(CoreId core, std::int32_t tile, BurstIndex k) const {
    const std::int32_t n = n_bursts(core, tile);
    if (k.get() < 0 || k.get() >= n) {
        throw std::out_of_range("StreamingTileTrace: local_tick of burst " +
                                std::to_string(k.get()) + " of " + span(core.get(), tile) +
                                " is outside [0, " + std::to_string(n) + ")");
    }
    const std::size_t c = static_cast<std::size_t>(core.get());
    return LocalTick{ticks_[static_cast<std::size_t>(core_begin_[c] + k.get())]};
}

LocalTick StreamingTileTrace::gap(CoreId core, std::int32_t tile, BurstIndex k) const {
    const std::int32_t n = n_bursts(core, tile);
    if (k.get() < 0 || k.get() + 1 >= n) {
        throw std::out_of_range("StreamingTileTrace: gap after burst " +
                                std::to_string(k.get()) + " of " + span(core.get(), tile) +
                                " is outside [0, " + std::to_string(n - 1) + ")");
    }
    const std::size_t i = static_cast<std::size_t>(core_begin_[static_cast<std::size_t>(
                                                       core.get())] +
                                                   k.get());
    // A DIFFERENCE, never an absolute tick (trace.h, D13).
    return LocalTick{ticks_[i + 1] - ticks_[i]};
}

std::int32_t StreamingTileTrace::distinct_addresses(CoreId core) const {
    require_core(core);
    if (window_ < 0) {
        throw std::out_of_range("StreamingTileTrace: distinct_addresses asked for core " +
                                std::to_string(core.get()) +
                                " while the window is empty; call advance() first");
    }
    const std::size_t   c     = static_cast<std::size_t>(core.get());
    const std::int32_t  begin = core_begin_[c];
    const std::int32_t  end   = core_end_[c];

    // Sort and unique a small local vector rather than a hash set: §1.3
    // measured 24 addresses per core per tile, at which size the copy is
    // cheaper than the hashing and the answer does not depend on a hash order.
    // The key is the on-disk 5-tuple; `count` stands for run_end - run_start
    // over a fixed run_start, so (anchor, count) and the 5-tuple are the same
    // key.
    std::vector<std::array<std::int64_t, 5>> keys;
    keys.reserve(static_cast<std::size_t>(end - begin));
    for (std::int32_t i = begin; i < end; ++i) {
        const Burst& b = bursts_[static_cast<std::size_t>(i)];
        keys.push_back({b.anchor.kh, b.anchor.kw, b.anchor.cin, b.anchor.cout, b.count});
    }
    std::sort(keys.begin(), keys.end());
    return static_cast<std::int32_t>(std::unique(keys.begin(), keys.end()) - keys.begin());
}

LocalTick StreamingTileTrace::tile_tail(std::int32_t tile) const {
    require_streamed(tile, "tile_tail");
    return LocalTick{tile_tail_[static_cast<std::size_t>(tile)]};
}

std::int64_t StreamingTileTrace::mac_cycles(std::int32_t tile) const {
    require_streamed(tile, "mac_cycles");
    return mac_cycles_[static_cast<std::size_t>(tile)];
}

std::int64_t StreamingTileTrace::tick_base(std::int32_t tile) const {
    if (tile < 0 || tile > streamed_) {
        throw std::out_of_range("StreamingTileTrace: tick_base asked for tile " +
                                std::to_string(tile) + ", but only tiles [0, " +
                                std::to_string(streamed_) + "] are defined");
    }
    return tick_base_[static_cast<std::size_t>(tile)];
}

bool StreamingTileTrace::advance() {
    if (at_end_) return false;
    if (streamed_ >= header_.n_tiles) {
        read_trailer();
        at_end_ = true;
        return false;
    }

    unsigned char prefix[kFramePrefixBytes];
    if (!src_->read_exact(prefix, sizeof(prefix))) {
        throw std::runtime_error("WCTS: the stream ended before tile frame " +
                                 std::to_string(streamed_) + " of " +
                                 std::to_string(header_.n_tiles));
    }
    const std::int32_t  tile_index    = stream::read_le<std::int32_t>(prefix);
    const std::int32_t  n_core_blocks = stream::read_le<std::int32_t>(prefix + 4);
    const std::int64_t  mac           = stream::read_le<std::int64_t>(prefix + 8);
    const std::uint64_t payload_bytes = stream::read_le<std::uint64_t>(prefix + 16);

    if (tile_index != streamed_) {
        throw std::runtime_error("WCTS frame: tile_index is " + std::to_string(tile_index) +
                                 " but the reader is at tile " + std::to_string(streamed_));
    }
    if (n_core_blocks < 0 || n_core_blocks > header_.n_cores) {
        throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                 ": n_core_blocks is " + std::to_string(n_core_blocks) +
                                 ", outside [0, " + std::to_string(header_.n_cores) + "]");
    }
    if (mac < 1) {
        throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                 ": mac_cycles is " + std::to_string(mac) + ", must be >= 1");
    }

    const std::size_t payload = static_cast<std::size_t>(payload_bytes);
    frame_.resize(payload);
    if (payload > 0 && !src_->read_exact(frame_.data(), payload)) {
        throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                 ": the stream ended before its " +
                                 std::to_string(payload) + " payload bytes");
    }

    bursts_.clear();
    ticks_.clear();
    core_begin_.assign(static_cast<std::size_t>(header_.n_cores), 0);
    core_end_.assign(static_cast<std::size_t>(header_.n_cores), 0);

    const Axis         axis   = header_.burst_dim;
    const std::int32_t stride = header_.burst_stride;
    std::size_t  pos      = 0;
    std::int32_t prev_core = -1;
    std::int64_t max_tick  = 0;

    auto need = [&](std::size_t n, const char* what) {
        if (payload - pos < n) {
            throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                     ": the payload ran out reading " + what);
        }
    };

    for (std::int32_t blk = 0; blk < n_core_blocks; ++blk) {
        need(8, "a core block header");
        const std::int32_t core_id = stream::read_le<std::int32_t>(frame_.data() + pos);
        const std::int32_t n_bursts_here = stream::read_le<std::int32_t>(frame_.data() + pos + 4);
        pos += 8;

        if (core_id < 0 || core_id >= header_.n_cores) {
            throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core_id " +
                                     std::to_string(core_id) + " is outside [0, " +
                                     std::to_string(header_.n_cores) + ")");
        }
        if (core_id <= prev_core) {
            throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core_id " +
                                     std::to_string(core_id) + " does not ascend past " +
                                     std::to_string(prev_core));
        }
        // A core with nothing to issue is omitted, never written as an empty
        // block, which is tracegen's own rule and keeps `n_bursts == 0` a fact
        // about the tile rather than a shape on the wire.
        if (n_bursts_here < 1) {
            throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core " +
                                     std::to_string(core_id) + " declares " +
                                     std::to_string(n_bursts_here) +
                                     " bursts, an idle core is omitted instead");
        }
        prev_core = core_id;

        const std::size_t c = static_cast<std::size_t>(core_id);
        core_begin_[c] = static_cast<std::int32_t>(ticks_.size());
        std::int64_t prev_tick = -1;
        for (std::int32_t i = 0; i < n_bursts_here; ++i) {
            need(kBurstRecordBytes, "a burst record");
            const unsigned char* rec = frame_.data() + pos;
            pos += kBurstRecordBytes;
            const std::int64_t tick      = stream::read_le<std::int64_t>(rec);
            const std::int32_t kh        = stream::read_le<std::int32_t>(rec + 8);
            const std::int32_t kw        = stream::read_le<std::int32_t>(rec + 12);
            const std::int32_t cin       = stream::read_le<std::int32_t>(rec + 16);
            const std::int32_t run_start = stream::read_le<std::int32_t>(rec + 20);
            const std::int32_t run_end   = stream::read_le<std::int32_t>(rec + 24);

            if (tick < 0) {
                throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core " +
                                         std::to_string(core_id) + " burst " +
                                         std::to_string(i) + " has local_tick " +
                                         std::to_string(tick) + ", must be >= 0");
            }
            if (tick <= prev_tick) {
                throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core " +
                                         std::to_string(core_id) + " local_tick " +
                                         std::to_string(tick) + " does not ascend past " +
                                         std::to_string(prev_tick));
            }
            if (run_end <= run_start) {
                throw std::runtime_error("WCTS frame " + std::to_string(tile_index) + ": core " +
                                         std::to_string(core_id) + " burst " +
                                         std::to_string(i) + " runs [" +
                                         std::to_string(run_start) + ", " +
                                         std::to_string(run_end) + "), which is empty");
            }
            prev_tick = tick;
            if (tick > max_tick) max_tick = tick;

            // The address record is [kh, kw, cin, run_start, run_end] and the
            // run walks `burst_dim`, so the anchor's coordinate along that axis
            // is run_start. For v1's COUT bursts this is Coord{kh, kw, cin,
            // run_start}, which is what the format section states.
            const Coord anchor =
                with_coord_on(Coord{kh, kw, cin, run_start}, axis, run_start);
            ticks_.push_back(tick);
            bursts_.push_back(Burst{anchor, axis, run_end - run_start, stride});
        }
        core_end_[c] = static_cast<std::int32_t>(ticks_.size());
    }

    if (pos != payload) {
        throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                 ": payload_bytes is " + std::to_string(payload) +
                                 " but its core blocks consume " + std::to_string(pos));
    }

    // trace.h: `>= 1` by construction, and the engine relies on it to advance
    // the tile seam, so it is checked rather than assumed (Q10).
    const std::int64_t tail = mac - max_tick;
    if (tail < 1) {
        throw std::runtime_error("WCTS frame " + std::to_string(tile_index) +
                                 ": tile_tail is mac_cycles " + std::to_string(mac) +
                                 " minus max_tick " + std::to_string(max_tick) + " = " +
                                 std::to_string(tail) + ", must be >= 1");
    }

    const std::size_t t = static_cast<std::size_t>(tile_index);
    mac_cycles_[t] = mac;
    tile_tail_[t]  = tail;
    tick_base_[t + 1] = tick_base_[t] + mac;
    bursts_seen_ += ticks_.size();
    window_   = tile_index;
    streamed_ = tile_index + 1;
    return true;
}

void StreamingTileTrace::read_trailer() {
    unsigned char buf[kTrailerBytes];
    if (!src_->read_exact(buf, sizeof(buf))) {
        throw std::runtime_error("WCTS: the stream ended before its trailer");
    }
    const std::int32_t  end_magic    = stream::read_le<std::int32_t>(buf);
    const std::uint64_t total_bursts = stream::read_le<std::uint64_t>(buf + 4);
    if (end_magic != stream::kEndMagic) {
        throw std::runtime_error("WCTS trailer: end magic is " + std::to_string(end_magic) +
                                 ", expected " + std::to_string(stream::kEndMagic));
    }
    if (total_bursts != bursts_seen_) {
        throw std::runtime_error("WCTS trailer: it declares " + std::to_string(total_bursts) +
                                 " bursts, the reader decoded " + std::to_string(bursts_seen_));
    }
}

WeightShape shape_of(const stream::StreamHeader& hdr) {
    auto extent = [&hdr](stream::DimCode code) {
        for (const auto& d : hdr.dims) {
            if (d.first == code) return d.second;
        }
        throw std::invalid_argument("WCTS header: no extent for dim code " +
                                    std::to_string(static_cast<int>(code)));
    };
    return WeightShape{extent(stream::DimCode::KH), extent(stream::DimCode::KW),
                       extent(stream::DimCode::CIN), extent(stream::DimCode::COUT)};
}

}  // namespace wcache
