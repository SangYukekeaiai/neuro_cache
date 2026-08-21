// WCTS, the weight cache trace stream, version 1: the wire format as data.
//
// Plan D Task 1. This header is the format and nothing else: the magic, the
// field codes, the little-endian byte helpers, and the stream header's encode
// and decode. It holds no I/O policy (that is byte_source.h) and no trace
// semantics (that is stream_trace.h).
//
// Endianness and alignment. Every multi-byte field is little-endian on the
// wire whatever the host is, matching the existing Python producer in
// src/cachesim/native_bridge.py, which writes `<i` and `<I`. The stream has no
// alignment guarantee, so every load goes through memcpy and never through a
// pointer cast into the buffer.
//
// The header carries the burst axis, the burst stride and the burst span. That
// is ruling R1 of 2026-08-20 (U27) plus ruling Q-D: the generator knows all
// three, the reader must not guess them, and D1 needs the span before the
// first burst has been seen. It also carries `n_cores` explicitly (U25) and
// validates it against the product of the spatial factors (U26, ruling Q-C),
// because `max(core_id) + 1` is provably wrong: prosperity implies 126 cores on
// a resnet19 layer where three other architectures imply 128.
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "wcache/types.h"

#if !defined(__BYTE_ORDER__) || !defined(__ORDER_LITTLE_ENDIAN__)
#error "stream_format.h needs __BYTE_ORDER__ to know the host byte order"
#endif

namespace wcache::stream {

inline constexpr char          kMagic[8]        = {'W', 'C', 'T', 'R', 'A', 'C', 'E', '1'};
inline constexpr std::uint32_t kFormatVersion   = 1;

// magic, version, header_bytes, n_tiles, n_cores, weight_bytes, burst_dim,
// burst_stride, burst_span, n_addr_fields, n_spatial, n_dims, identity_bytes.
inline constexpr std::size_t   kFixedHeaderBytes = 56;
inline constexpr std::int32_t  kEndMagic         = -1;
inline constexpr std::int32_t  kAddrFields       = 5;
inline constexpr std::int32_t  kDims             = 7;

// Wire codes. Deliberately NOT the same enum as `Axis`, so a renumbering of
// `Axis` cannot silently change the format (U28's whole point).
enum class DimCode : std::int32_t { KH = 0, KW = 1, CIN = 2, COUT = 3, HO = 4, WO = 5, T = 6 };
enum class FieldCode : std::int32_t { KH = 0, KW = 1, CIN = 2, RunStart = 3, RunEnd = 4 };

inline constexpr bool kHostIsLittleEndian = (__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__);

// Little-endian, alignment-free. `src` need not be aligned.
template <typename T>
T read_le(const unsigned char* src) {
    unsigned char tmp[sizeof(T)];
    if constexpr (kHostIsLittleEndian) {
        std::memcpy(tmp, src, sizeof(T));
    } else {
        for (std::size_t i = 0; i < sizeof(T); ++i) tmp[i] = src[sizeof(T) - 1 - i];
    }
    T v{};
    std::memcpy(&v, tmp, sizeof(T));
    return v;
}

template <typename T>
void write_le(unsigned char* dst, T v) {
    unsigned char tmp[sizeof(T)];
    std::memcpy(tmp, &v, sizeof(T));
    if constexpr (kHostIsLittleEndian) {
        std::memcpy(dst, tmp, sizeof(T));
    } else {
        for (std::size_t i = 0; i < sizeof(T); ++i) dst[i] = tmp[sizeof(T) - 1 - i];
    }
}

// The burst axis code, as it travels on the wire. Only the four weight axes
// are addressable: a burst walks the weight tensor, so HO, WO and T are dims of
// the workload but never of a burst.
inline Axis axis_of(std::int32_t burst_dim) {
    switch (burst_dim) {
        case 0: return Axis::KH;
        case 1: return Axis::KW;
        case 2: return Axis::CIN;
        case 3: return Axis::COUT;
        default: break;
    }
    throw std::invalid_argument("WCTS header: burst_dim " + std::to_string(burst_dim) +
                                " is not one of the four weight axes 0..3");
}

inline std::int32_t code_of(Axis a) {
    return static_cast<std::int32_t>(a);
}

struct StreamHeader {
    std::int32_t n_tiles      = 0;
    std::int32_t n_cores      = 0;
    std::int32_t weight_bytes = 1;
    Axis         burst_dim    = Axis::COUT;
    std::int32_t burst_stride = 1;
    // Maximum burst span in this layer, used to size l1_demand_reserve; each
    // burst's actual extent is derivable from its own run_start and run_end.
    // Ruling Q-D: D1's `l1_demand_reserve` default is
    // `lines_per_burst = burst_span / cout_block` and validation runs before any
    // burst has been decoded.
    std::int32_t burst_span   = 1;
    std::vector<FieldCode>                        addr_fields;
    std::vector<std::pair<DimCode, std::int32_t>> spatial_factors;
    std::vector<std::pair<DimCode, std::int32_t>> dims;
    std::string  arch;
    std::string  workload;
    std::string  layer;
    std::int32_t sample_idx = 0;
};

namespace detail {

inline std::string identity_block(const StreamHeader& h) {
    std::string s;
    s += h.arch;     s.push_back('\0');
    s += h.workload; s.push_back('\0');
    s += h.layer;    s.push_back('\0');
    s += std::to_string(h.sample_idx);
    s.push_back('\0');
    return s;
}

template <typename T>
void append_le(std::vector<unsigned char>& out, T v) {
    const std::size_t at = out.size();
    out.resize(at + sizeof(T));
    write_le<T>(out.data() + at, v);
}

// A cursor over the header buffer. Every field is read through it, so a length
// that disagrees with the field counts is caught at the field that runs off the
// end rather than by reading whatever follows the buffer.
class Cursor {
public:
    Cursor(const unsigned char* buf, std::size_t len) : buf_(buf), len_(len) {}

    template <typename T>
    T take(const char* field) {
        if (len_ - pos_ < sizeof(T)) {
            throw std::invalid_argument(std::string("WCTS header: ran off the end reading ") +
                                        field);
        }
        const T v = read_le<T>(buf_ + pos_);
        pos_ += sizeof(T);
        return v;
    }

    std::size_t pos() const { return pos_; }

private:
    const unsigned char* buf_;
    std::size_t          len_;
    std::size_t          pos_ = 0;
};

}  // namespace detail

// The inverse of decode_header, for tests and for the C++ side of any future
// dump tool. Appends, and deliberately does NOT validate: a test that could not
// write a malformed header could not test the decoder's refusals.
inline void encode_header(const StreamHeader& h, std::vector<unsigned char>& out) {
    const std::string identity = detail::identity_block(h);
    const std::size_t header_bytes = kFixedHeaderBytes + 4 * h.addr_fields.size() +
                                     8 * h.spatial_factors.size() + 8 * h.dims.size() +
                                     identity.size();

    out.insert(out.end(), kMagic, kMagic + 8);
    detail::append_le<std::uint32_t>(out, kFormatVersion);
    detail::append_le<std::uint32_t>(out, static_cast<std::uint32_t>(header_bytes));
    detail::append_le<std::int32_t>(out, h.n_tiles);
    detail::append_le<std::int32_t>(out, h.n_cores);
    detail::append_le<std::int32_t>(out, h.weight_bytes);
    detail::append_le<std::int32_t>(out, code_of(h.burst_dim));
    detail::append_le<std::int32_t>(out, h.burst_stride);
    detail::append_le<std::int32_t>(out, h.burst_span);
    detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(h.addr_fields.size()));
    detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(h.spatial_factors.size()));
    detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(h.dims.size()));
    detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(identity.size()));

    for (FieldCode f : h.addr_fields) detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(f));
    for (const auto& p : h.spatial_factors) {
        detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(p.first));
        detail::append_le<std::int32_t>(out, p.second);
    }
    for (const auto& p : h.dims) {
        detail::append_le<std::int32_t>(out, static_cast<std::int32_t>(p.first));
        detail::append_le<std::int32_t>(out, p.second);
    }
    out.insert(out.end(), identity.begin(), identity.end());
}

// Decodes and VALIDATES a header from a complete byte buffer. Throws
// std::invalid_argument naming the offending field on any violation.
inline StreamHeader decode_header(const unsigned char* buf, std::size_t len) {
    if (len < kFixedHeaderBytes) {
        throw std::invalid_argument("WCTS header: buffer is " + std::to_string(len) +
                                    " bytes, the fixed header alone is " +
                                    std::to_string(kFixedHeaderBytes));
    }
    if (std::memcmp(buf, kMagic, 8) != 0) {
        throw std::invalid_argument("WCTS header: magic is not WCTRACE1");
    }

    detail::Cursor cur(buf, len);
    (void)cur.take<std::uint64_t>("magic");
    const std::uint32_t version = cur.take<std::uint32_t>("format_version");
    if (version != kFormatVersion) {
        throw std::invalid_argument("WCTS header: format_version is " +
                                    std::to_string(version) + ", this reader speaks " +
                                    std::to_string(kFormatVersion));
    }
    const std::uint32_t header_bytes = cur.take<std::uint32_t>("header_bytes");
    if (header_bytes != len) {
        throw std::invalid_argument("WCTS header: header_bytes is " +
                                    std::to_string(header_bytes) + " but " +
                                    std::to_string(len) + " bytes were supplied");
    }

    StreamHeader h;
    h.n_tiles = cur.take<std::int32_t>("n_tiles");
    if (h.n_tiles < 0) {
        throw std::invalid_argument("WCTS header: n_tiles is " + std::to_string(h.n_tiles) +
                                    ", must be >= 0");
    }
    h.n_cores = cur.take<std::int32_t>("n_cores");
    if (h.n_cores < 1) {
        throw std::invalid_argument("WCTS header: n_cores is " + std::to_string(h.n_cores) +
                                    ", must be >= 1");
    }
    h.weight_bytes = cur.take<std::int32_t>("weight_bytes");
    if (h.weight_bytes < 1) {
        throw std::invalid_argument("WCTS header: weight_bytes is " +
                                    std::to_string(h.weight_bytes) + ", must be >= 1");
    }
    h.burst_dim = axis_of(cur.take<std::int32_t>("burst_dim"));
    h.burst_stride = cur.take<std::int32_t>("burst_stride");
    if (h.burst_stride < 1) {
        throw std::invalid_argument("WCTS header: burst_stride is " +
                                    std::to_string(h.burst_stride) + ", must be >= 1");
    }
    h.burst_span = cur.take<std::int32_t>("burst_span");
    if (h.burst_span < 1) {
        throw std::invalid_argument("WCTS header: burst_span is " +
                                    std::to_string(h.burst_span) + ", must be >= 1");
    }

    const std::int32_t n_addr_fields  = cur.take<std::int32_t>("n_addr_fields");
    const std::int32_t n_spatial      = cur.take<std::int32_t>("n_spatial");
    const std::int32_t n_dims         = cur.take<std::int32_t>("n_dims");
    const std::int32_t identity_bytes = cur.take<std::int32_t>("identity_bytes");
    if (n_addr_fields != kAddrFields) {
        throw std::invalid_argument("WCTS header: n_addr_fields is " +
                                    std::to_string(n_addr_fields) + ", v1 requires " +
                                    std::to_string(kAddrFields));
    }
    if (n_spatial < 0) {
        throw std::invalid_argument("WCTS header: n_spatial is " + std::to_string(n_spatial) +
                                    ", must be >= 0");
    }
    if (n_dims != kDims) {
        throw std::invalid_argument("WCTS header: n_dims is " + std::to_string(n_dims) +
                                    ", v1 requires " + std::to_string(kDims));
    }
    if (identity_bytes < 0) {
        throw std::invalid_argument("WCTS header: identity_bytes is " +
                                    std::to_string(identity_bytes) + ", must be >= 0");
    }

    const std::size_t expect = kFixedHeaderBytes + 4 * static_cast<std::size_t>(n_addr_fields) +
                               8 * static_cast<std::size_t>(n_spatial) +
                               8 * static_cast<std::size_t>(n_dims) +
                               static_cast<std::size_t>(identity_bytes);
    if (expect != header_bytes) {
        throw std::invalid_argument("WCTS header: header_bytes is " +
                                    std::to_string(header_bytes) +
                                    " but the field counts add up to " + std::to_string(expect));
    }

    for (std::int32_t i = 0; i < n_addr_fields; ++i) {
        const std::int32_t code = cur.take<std::int32_t>("addr_field_id");
        if (code != i) {
            throw std::invalid_argument("WCTS header: addr_field_id[" + std::to_string(i) +
                                        "] is " + std::to_string(code) +
                                        ", v1 requires the order {0,1,2,3,4}");
        }
        h.addr_fields.push_back(static_cast<FieldCode>(code));
    }

    std::int64_t product = 1;
    std::int32_t prev_dim = -1;
    for (std::int32_t i = 0; i < n_spatial; ++i) {
        const std::int32_t dim    = cur.take<std::int32_t>("spatial dim_id");
        const std::int32_t factor = cur.take<std::int32_t>("spatial factor");
        if (dim < 0 || dim > 6) {
            throw std::invalid_argument("WCTS header: spatial dim_id " + std::to_string(dim) +
                                        " is outside 0..6");
        }
        if (dim <= prev_dim) {
            throw std::invalid_argument("WCTS header: spatial dim_id " + std::to_string(dim) +
                                        " does not ascend past " + std::to_string(prev_dim));
        }
        if (factor < 1) {
            throw std::invalid_argument("WCTS header: spatial factor for dim " +
                                        std::to_string(dim) + " is " + std::to_string(factor) +
                                        ", must be >= 1");
        }
        prev_dim = dim;
        product *= factor;
        h.spatial_factors.emplace_back(static_cast<DimCode>(dim), factor);
    }
    // Ruling Q-C: n_cores is the explicit field, and the product is the check
    // on it rather than the source of it.
    if (product != h.n_cores) {
        throw std::invalid_argument("WCTS header: prod(spatial_factors) is " +
                                    std::to_string(product) + " but n_cores is " +
                                    std::to_string(h.n_cores));
    }

    for (std::int32_t i = 0; i < n_dims; ++i) {
        const std::int32_t dim    = cur.take<std::int32_t>("workload dim_id");
        const std::int32_t extent = cur.take<std::int32_t>("workload extent");
        if (dim != i) {
            throw std::invalid_argument("WCTS header: workload dim_id[" + std::to_string(i) +
                                        "] is " + std::to_string(dim) +
                                        ", v1 requires the ids 0..6 in order");
        }
        h.dims.emplace_back(static_cast<DimCode>(dim), extent);
    }

    // Four NUL-terminated fields: arch, workload, layer, sample_idx.
    const unsigned char* id_begin = buf + cur.pos();
    std::vector<std::string> fields;
    std::string current;
    for (std::int32_t i = 0; i < identity_bytes; ++i) {
        const char c = static_cast<char>(id_begin[i]);
        if (c == '\0') {
            fields.push_back(current);
            current.clear();
        } else {
            current.push_back(c);
        }
    }
    if (fields.size() != 4 || !current.empty()) {
        throw std::invalid_argument("WCTS header: the identity block holds " +
                                    std::to_string(fields.size()) +
                                    " NUL-terminated fields, v1 requires exactly 4");
    }
    h.arch     = fields[0];
    h.workload = fields[1];
    h.layer    = fields[2];
    try {
        std::size_t used = 0;
        h.sample_idx = std::stoi(fields[3], &used);
        if (used != fields[3].size()) throw std::invalid_argument("trailing characters");
    } catch (const std::exception&) {
        throw std::invalid_argument("WCTS header: sample_idx '" + fields[3] +
                                    "' is not an integer");
    }
    return h;
}

}  // namespace wcache::stream
