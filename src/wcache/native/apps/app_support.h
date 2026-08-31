// What wcache_run and wcache_sweep both need, stated once.
//
// This is CLI support and not library code: it is descriptors, usage errors,
// a run id and an output file, none of which the engine, the reader or the
// stats have any business knowing about. It lives under apps/ for that reason,
// and `make test` does not build it -- tests/run_cli.sh and tests/sweep_cli.sh
// are what cover it.
//
// The one piece here that is not plumbing is PaddingMeter, which is shared for
// the same reason a knob's default is: two copies of a definition are two
// places for it to drift, and a padding fraction that differed between a run
// and a sweep of the same configuration would look like a cache effect.
#pragma once

#include <fcntl.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

#include "wcache/block_pack.h"
#include "wcache/config.h"
#include "wcache/khkw_split.h"
#include "wcache/layout.h"
#include "wcache/split_cin.h"
#include "wcache/stream_format.h"
#include "wcache/stream_trace.h"
#include "wcache/types.h"

namespace wcache {
namespace app {

// A usage error, which exits 2, as distinct from every run-time failure, which
// exits 1. Separated by TYPE rather than by an error code threaded through the
// call chain, so a new caller cannot forget which of the two it is.
struct UsageError : std::runtime_error {
    explicit UsageError(const std::string& what) : std::runtime_error(what) {}
};

inline std::string value_of(int argc, char** argv, int& i) {
    if (i + 1 >= argc) throw UsageError(std::string(argv[i]) + " needs a value");
    return argv[++i];
}

// A CLI integer, refused rather than silently taken as 0. `std::stoll` stops at
// the first character it cannot use, so `--line-trace-core x` would otherwise be
// core 0 and the trace would look filtered to a core the user never named.
inline std::int64_t int_value_of(int argc, char** argv, int& i) {
    const std::string flag = argv[i];
    const std::string text = value_of(argc, argv, i);
    std::size_t used = 0;
    long long v = 0;
    try {
        v = std::stoll(text, &used);
    } catch (const std::exception&) {
        throw UsageError(flag + " needs an integer, got \"" + text + "\"");
    }
    if (used != text.size()) throw UsageError(flag + " needs an integer, got \"" + text + "\"");
    return static_cast<std::int64_t>(v);
}

// Checked rather than passed through, because an unknown arm produces a row
// that joins to nothing and is only noticed in the analysis.
inline void check_arm(const std::string& arm) {
    if (arm != "cache" && arm != "spad_oracle" && arm != "spad_wcache" &&
        arm != "spad_nocsim") {
        throw UsageError("--arm " + arm +
                         " is not one of cache, spad_oracle, spad_wcache, spad_nocsim");
    }
}

// Version 4, variant 1, from std::random_device. The run id only has to be
// unique across a campaign's rows, so there is nothing here to seed or record.
inline std::string uuid4() {
    std::random_device rd;
    std::uniform_int_distribution<unsigned> nibble(0, 15);
    static const char* const hex = "0123456789abcdef";
    std::string s = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
    for (char& c : s) {
        if (c == 'x') c = hex[nibble(rd)];
        else if (c == 'y') c = hex[8u + (nibble(rd) & 3u)];
    }
    return s;
}

// The one place `cfg.layout` becomes a mapper.
//
// Both drivers call it, so the branch over LayoutKind is written once. Adding a
// third layout is an enumerator in layout.h, a spelling in config.cpp, and a
// case here; no driver learns the list.
//
// It also appends the layout warning that needs the LAYER, and the two are one
// function on purpose. validate() is handed a config and a burst span and never
// a shape, so it cannot ask how many CIN blocks the layer has; this function
// must ask, because it is building the mapper that answers. A separate
// `warn_layout_vs_layer` would be a second call a driver could forget, and the
// thing it would forget to say is that the run is measuring a degenerate
// layout.
//
// PRECONDITION: validate() has run. Under `split_cin` it is what turns
// cin_lo_blocks from the -1 sentinel into a width, and SplitCinMapper refuses a
// non-positive n_cin_lo, so calling this too early throws rather than building
// a mapper out of a sentinel.
inline std::unique_ptr<AddressMapper> make_mapper(const RunConfig& cfg,
                                                  const WeightShape& shape,
                                                  std::vector<Warning>& warnings) {
    if (cfg.layout == LayoutKind::BlockPack) {
        return std::unique_ptr<AddressMapper>(
            new BlockPackMapper(shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes));
    }
    if (cfg.layout == LayoutKind::KhkwSplit) {
        // No width to warn about: khkw_split takes no split argument, so there
        // is no config field that can disagree with the layer.
        return std::unique_ptr<AddressMapper>(
            new KhkwSplitMapper(shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes));
    }

    std::unique_ptr<SplitCinMapper> m(new SplitCinMapper(
        shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes, cfg.cin_lo_blocks));

    // The split width above the layer's block count: cin_lo never reaches its
    // radix, so the top of the L1 set index is unreachable and the cache runs
    // smaller than its geometry says. A quality problem and not a configuration
    // error, which is why split_cin.h keeps it out of the constructor: the
    // flatten stays correct, it just places worse.
    if (m->n_cin_lo() > m->n_cin_blocks()) {
        warnings.push_back(
            {"W_CIN_LO_UNREACHABLE",
             "cin_lo_blocks = " + std::to_string(m->n_cin_lo()) + " is above the layer's " +
                 std::to_string(m->n_cin_blocks()) +
                 " CIN blocks, so the top of the L1 set index is unreachable and the run "
                 "uses " + std::to_string(m->n_cin_blocks()) + " of its sets"});
    }
    return std::unique_ptr<AddressMapper>(m.release());
}

// D1's `l1_demand_reserve` default, which validate() needs before any burst has
// been decoded. Asked of the MAPPER rather than computed as
// `burst_span / cout_block`: the division is only right when the burst walks
// COUT, and a trace that bursts along CIN or KH would silently get a reserve
// sized for the wrong axis. Ruling Q-D put `burst_span` in the header, so the
// widest burst the layer can hold is expandable here, at the origin.
//
// The mapper handed in need not be the one the run will use, and both drivers
// pass a BlockPackMapper here even when cfg.layout says split_cin. A burst
// covers a fixed set of BLOCK coordinates, and every mapper is injective on
// those, so the COUNT is the same under any nesting; only the ids differ. The
// alternative is a chicken and egg, since validate() is what resolves the
// width the real mapper is built from. test_split_cin pins the equality this
// rests on over the corpus burst and a sweep of others.
inline std::int32_t lines_per_burst(const AddressMapper& mapper,
                                    const stream::StreamHeader& hdr) {
    const Burst widest{Coord{0, 0, 0, 0}, hdr.burst_dim, hdr.burst_span, hdr.burst_stride};
    std::vector<LineId> lines;
    mapper.expand(widest, lines);
    return static_cast<std::int32_t>(lines.size());
}

// The `padding_fraction` column: the share of the weight elements pulled into
// L1 that no burst ever consumed,
//
//   (lines_touched * elements_per_line - distinct_elements) / (lines_touched * elements_per_line)
//
// Per RUN and not per burst, which is the reading ruled at open question Q-G:
// two bursts sharing a line pay for that line's padding once. It is a property
// of the LAYOUT and the trace rather than of a cache, so one meter serves a
// whole sweep: every point of a sweep shares one mapper by construction.
//
// Both sets are bitmaps rather than hash sets because they are dense and known
// in size: a 3x3x512x512 layer is 2.4M elements, which is 300 KB as bits and
// well over a hundred megabytes as an unordered_set.
class PaddingMeter {
public:
    PaddingMeter(const AddressMapper& mapper, const WeightShape& shape,
                 std::int64_t elements_per_line)
        : mapper_(mapper),
          shape_(shape),
          elements_per_line_(elements_per_line),
          line_seen_(static_cast<std::size_t>(mapper.num_lines().get()), false),
          element_seen_(static_cast<std::size_t>(shape.KH) * static_cast<std::size_t>(shape.KW) *
                            static_cast<std::size_t>(shape.CIN) *
                            static_cast<std::size_t>(shape.COUT),
                        false) {}

    void observe(const Burst& b) {
        mapper_.expand(b, lines_);
        for (const LineId& l : lines_) line_seen_[static_cast<std::size_t>(l.get())] = true;
        lines_.clear();
        for (std::int32_t k = 0; k < b.count; ++k) {
            Coord c = b.anchor;
            const std::int32_t step = k * b.stride;
            switch (b.axis) {
                case Axis::KH:   c.kh += step;   break;
                case Axis::KW:   c.kw += step;   break;
                case Axis::CIN:  c.cin += step;  break;
                case Axis::COUT: c.cout += step; break;
            }
            element_seen_[element_index(c)] = true;
        }
    }

    // Every burst of the window tile, for a driver that has just advanced it.
    void observe_tile(const StreamingTileTrace& trace) {
        const std::int32_t tile = trace.window_tile();
        for (std::int32_t c = 0; c < trace.n_cores(); ++c) {
            const CoreId core{c};
            const std::int32_t n = trace.n_bursts(core, tile);
            for (std::int32_t k = 0; k < n; ++k) observe(trace.burst(core, tile, BurstIndex{k}));
        }
    }

    // Zero when nothing was touched: there is no padding in a layer no burst
    // read, and the alternative is a NaN in a column an analysis averages.
    double fraction() const {
        std::int64_t lines = 0;
        for (bool seen : line_seen_) lines += seen ? 1 : 0;
        std::int64_t elements = 0;
        for (bool seen : element_seen_) elements += seen ? 1 : 0;
        const std::int64_t fetched = lines * elements_per_line_;
        if (fetched == 0) return 0.0;
        return static_cast<double>(fetched - elements) / static_cast<double>(fetched);
    }

private:
    std::size_t element_index(const Coord& c) const {
        const std::int64_t i =
            ((static_cast<std::int64_t>(c.kh) * shape_.KW + c.kw) * shape_.CIN + c.cin) *
                shape_.COUT +
            c.cout;
        return static_cast<std::size_t>(i);
    }

    const AddressMapper& mapper_;
    WeightShape          shape_;
    std::int64_t         elements_per_line_;
    std::vector<bool>    line_seen_;
    std::vector<bool>    element_seen_;
    std::vector<LineId>  lines_;
};

// Owns the descriptor only when it opened one, so `-` and `fd:N` hand back a
// descriptor this class must not close.
class TraceFd {
public:
    explicit TraceFd(const std::string& spec) {
        if (spec == "-") {
            fd_ = STDIN_FILENO;
        } else if (spec.rfind("fd:", 0) == 0) {
            fd_ = std::stoi(spec.substr(3));
        } else {
            fd_ = ::open(spec.c_str(), O_RDONLY);
            if (fd_ < 0) {
                throw std::runtime_error("cannot open trace " + spec + ": " +
                                         std::strerror(errno));
            }
            owned_ = true;
        }
    }
    ~TraceFd() { if (owned_) ::close(fd_); }
    TraceFd(const TraceFd&)            = delete;
    TraceFd& operator=(const TraceFd&) = delete;

    int get() const { return fd_; }

private:
    int  fd_    = -1;
    bool owned_ = false;
};

inline bool path_exists(const std::string& path) {
    return ::access(path.c_str(), F_OK) == 0;
}

inline void write_out(const std::string& out_path, const std::string& text) {
    if (out_path == "-") {
        std::cout << text;
        std::cout.flush();
        return;
    }
    std::ofstream out(out_path);
    if (!out) throw std::runtime_error("cannot write " + out_path);
    out << text;
}

}  // namespace app
}  // namespace wcache
