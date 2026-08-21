// StreamBuilder: a WCTS stream assembled in memory, for the reader's tests and
// for anything else that needs a real stream to read.
//
// Deliberately a SECOND implementation of the format rather than a call into
// stream_format.h's writer: a reader tested against its own writer tests only
// that the two agree with each other.
//
// It lives in its own header rather than inside one test file because two
// suites now need a stream (Tasks 2 and 3's reader, and Task 14's histogram),
// and a second hand-written copy of a binary format is a second place for it to
// drift.
#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace fx {

class StreamBuilder {
public:
    StreamBuilder(std::int32_t n_tiles, std::int32_t n_cores)
        : n_tiles_(n_tiles), n_cores_(n_cores) {
        write_header();
    }

    void begin_tile(std::int32_t tile_index, std::int64_t mac_cycles) {
        tile_index_   = tile_index;
        mac_cycles_   = mac_cycles;
        payload_.clear();
        core_open_    = false;
        n_core_blocks_ = 0;
    }

    void begin_core(std::int32_t core_id) {
        flush_core();
        core_id_    = core_id;
        core_open_  = true;
        core_burst_bytes_.clear();
        core_n_bursts_ = 0;
    }

    void add_burst(std::int64_t tick, std::int32_t kh, std::int32_t kw, std::int32_t cin,
                   std::int32_t run_start, std::int32_t run_end) {
        put64(core_burst_bytes_, static_cast<std::uint64_t>(tick));
        put32(core_burst_bytes_, kh);
        put32(core_burst_bytes_, kw);
        put32(core_burst_bytes_, cin);
        put32(core_burst_bytes_, run_start);
        put32(core_burst_bytes_, run_end);
        ++core_n_bursts_;
        ++total_bursts_;
    }

    void end_tile() {
        flush_core();
        put32(buf_, tile_index_);
        put32(buf_, n_core_blocks_ + core_block_bias_);
        put64(buf_, static_cast<std::uint64_t>(mac_cycles_));
        put64(buf_, static_cast<std::uint64_t>(payload_.size()) + payload_bias_);
        buf_.insert(buf_.end(), payload_.begin(), payload_.end());
    }

    std::vector<unsigned char> finish() {
        std::vector<unsigned char> out = buf_;
        put32(out, end_magic_);
        put64(out, total_bursts_override_ ? *total_bursts_override_ : total_bursts_);
        return out;
    }

    // Escape hatches the negative cases need.
    void set_end_magic(std::int32_t v) { end_magic_ = v; }
    void set_total_bursts(std::uint64_t v) { total_bursts_override_ = v; }
    void set_core_block_bias(std::int32_t v) { core_block_bias_ = v; }
    void set_payload_bias(std::uint64_t v) { payload_bias_ = v; }

private:
    static void put32(std::vector<unsigned char>& v, std::int32_t x) {
        const std::uint32_t u = static_cast<std::uint32_t>(x);
        for (int i = 0; i < 4; ++i)
            v.push_back(static_cast<unsigned char>((u >> (8 * i)) & 0xffu));
    }
    static void put64(std::vector<unsigned char>& v, std::uint64_t u) {
        for (int i = 0; i < 8; ++i)
            v.push_back(static_cast<unsigned char>((u >> (8 * i)) & 0xffu));
    }

    void flush_core() {
        if (!core_open_) return;
        put32(payload_, core_id_);
        put32(payload_, core_n_bursts_);
        payload_.insert(payload_.end(), core_burst_bytes_.begin(), core_burst_bytes_.end());
        ++n_core_blocks_;
        core_open_ = false;
    }

    void write_header() {
        const std::string identity = std::string("loas") + '\0' + "vgg16" + '\0' + "layer_01" +
                                     '\0' + "0" + '\0';
        const std::int32_t identity_bytes = static_cast<std::int32_t>(identity.size());
        const char magic[8] = {'W', 'C', 'T', 'R', 'A', 'C', 'E', '1'};
        for (char c : magic) buf_.push_back(static_cast<unsigned char>(c));
        put32(buf_, 1);                                // format_version
        put32(buf_, 56 + 4 * 5 + 8 * 1 + 8 * 7 + identity_bytes);  // header_bytes
        put32(buf_, n_tiles_);
        put32(buf_, n_cores_);
        put32(buf_, 1);   // weight_bytes
        put32(buf_, 3);   // burst_dim, COUT
        put32(buf_, 1);   // burst_stride
        put32(buf_, 16);  // burst_span
        put32(buf_, 5);   // n_addr_fields
        put32(buf_, 1);   // n_spatial
        put32(buf_, 7);   // n_dims
        put32(buf_, identity_bytes);
        for (std::int32_t i = 0; i < 5; ++i) put32(buf_, i);
        put32(buf_, 3);  // spatial dim COUT
        put32(buf_, n_cores_);
        const std::int32_t extents[7] = {3, 3, 64, 64, 32, 32, 4};
        for (std::int32_t i = 0; i < 7; ++i) {
            put32(buf_, i);
            put32(buf_, extents[static_cast<std::size_t>(i)]);
        }
        for (char c : identity) buf_.push_back(static_cast<unsigned char>(c));
    }

    std::int32_t n_tiles_;
    std::int32_t n_cores_;
    std::vector<unsigned char> buf_;
    std::vector<unsigned char> payload_;
    std::vector<unsigned char> core_burst_bytes_;
    std::int32_t tile_index_    = 0;
    std::int64_t mac_cycles_    = 1;
    std::int32_t n_core_blocks_ = 0;
    std::int32_t core_id_       = 0;
    std::int32_t core_n_bursts_ = 0;
    bool         core_open_     = false;
    std::uint64_t total_bursts_ = 0;
    std::int32_t end_magic_     = -1;
    std::int32_t core_block_bias_ = 0;
    std::uint64_t payload_bias_ = 0;
    std::optional<std::uint64_t> total_bursts_override_;
};

}  // namespace fx
