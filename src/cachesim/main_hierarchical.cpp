// cache_replay_hierarchical: the two-level (private L1 per core, shared
// L2) entry point of log/2026-08-03-l1-l2-cache-policy-plan.md, the
// counterpart of main.cpp's single-level cache_replay. It reads the
// Stage 1 nested weight trace (tiles -> ticks -> cores ->
// weight_addresses, flattened to a tick stream by the bridge), drives
// hierarchy.h's TwoLevelHierarchy, and reports the hit counts behind the
// plan's four rates.
//
// main.cpp is untouched by this and keeps its own semantics: the
// single-level path's results do not move.
//
// Usage:
//   cache_replay_hierarchical
//     <l1_cache_size_bytes> <l1_cache_type> <l1_associativity_or_0>
//     <l2_cache_size_bytes> <l2_cache_type> <l2_associativity_or_0>
//     <line_size_bytes> <order_csv> <layout> <cin_block> <cout_block>
//     <kh_bound> <kw_bound> <cin_bound> <cout_bound>
//     <l2_prefetch_0_or_1> <same_tick_pinning_0_or_1>
//   < ticks.bin > stdout (see "output" below)
//
// The two policy switches are required, not defaulted: the plan's own
// semantics have both on, but every hand-made test needs to run the same
// engine with one of them off, and a default here would be a second copy
// of the one in the Python twin.
//
// The layout arguments are given once, not per level: the plan fixes one
// shared layout formula and one shared line_size_bytes for L1 and L2,
// with only capacity and structure differing between them, so taking
// them once makes a mismatch unrepresentable rather than merely invalid.
// <layout> must be "hybrid" -- the hierarchy is defined on the 4x4
// cin x cout packing, and the inner_dim layout's radices come from a
// per-sample pre-scan that has no meaning here, so it is refused rather
// than silently approximated. That is also why there is no <inner_dim>
// argument: the hybrid layout ignores it.
//
// ticks.bin (stdin, binary, little-endian), one sample, tiles already
// flattened away (a tile boundary is also a tick boundary, so the tick
// stream alone carries everything the hierarchy needs):
//   uint32 n_ticks
//   repeat n_ticks:
//     uint32 n_cores                          (ascending core_id)
//     repeat n_cores:
//       int32  core_id
//       uint32 n_events
//       repeat n_events: int32 v0, v1, v2, v3, v4   (raw address tuple)
//
// output (stdout):
//   <n_cores>
//   repeat n_cores: "<core_id> <l1_hits> <l1_accesses>"   (ascending)
//   "<l1_hits> <l1_accesses> <l2_hits> <l2_accesses>"
// Counts only, no rates: the four rate formulas live in exactly one
// place, src/cachesim/stats.py's HierarchyStats.

#include <cstdint>
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "cache.h"
#include "config.h"
#include "dims.h"
#include "hierarchy.h"
#include "layout.h"

using namespace cachesim;

namespace {

// One core's raw events at one tick: 5 int32 per event, flat.
struct WireCore {
    int32_t core_id;
    std::vector<int32_t> raw;
};

template <typename T>
T read_pod(const char *what) {
    T v;
    if (std::fread(&v, sizeof(v), 1, stdin) != 1) throw std::runtime_error(std::string("failed to read ") + what);
    return v;
}

std::vector<std::vector<WireCore>> read_ticks() {
    uint32_t n_ticks = read_pod<uint32_t>("n_ticks");
    std::vector<std::vector<WireCore>> ticks(n_ticks);
    for (uint32_t t = 0; t < n_ticks; ++t) {
        uint32_t n_cores = read_pod<uint32_t>("n_cores");
        ticks[t].resize(n_cores);
        for (uint32_t c = 0; c < n_cores; ++c) {
            ticks[t][c].core_id = read_pod<int32_t>("core_id");
            uint32_t n_events = read_pod<uint32_t>("n_events");
            std::vector<int32_t> &raw = ticks[t][c].raw;
            raw.resize(size_t(n_events) * 5);
            if (n_events > 0 && std::fread(raw.data(), sizeof(int32_t), raw.size(), stdin) != raw.size())
                throw std::runtime_error("unexpected EOF reading events");
        }
    }
    return ticks;
}

// Per burst, not per weight value, exactly as main.cpp does it: one event
// is one memory transaction, so its expanded elements collapse to the
// DISTINCT consecutive line tags that burst touches. `prev` resets per
// event, so dedup never crosses an event boundary.
std::vector<int64_t> packed_tags(const std::vector<int32_t> &raw, const std::vector<Dim> &order,
                                const CacheConfig &cfg, const TagPacker &packer) {
    std::vector<int64_t> tags;
    for (size_t ei = 0; ei * 5 < raw.size(); ++ei) {
        bool have_prev = false;
        int64_t prev = 0;
        for_each_element(&raw[ei * 5], order, [&](const Element &e) {
            int64_t packed = packer.pack(tag_for_element_hybrid(e, cfg.cin_block, cfg.cout_block));
            if (have_prev && packed == prev) return;
            have_prev = true;
            prev = packed;
            tags.push_back(packed);
        });
    }
    return tags;
}

bool parse_flag(const char *arg, const char *what) {
    std::string s(arg);
    if (s == "0") return false;
    if (s == "1") return true;
    throw std::runtime_error(std::string("cachesim: ") + what + " must be 0 or 1, got '" + s + "'");
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 18) {
        std::cerr << "usage: cache_replay_hierarchical <l1_cache_size_bytes> <l1_cache_type> "
                     "<l1_associativity_or_0> <l2_cache_size_bytes> <l2_cache_type> "
                     "<l2_associativity_or_0> <line_size_bytes> <order_csv> <layout> "
                     "<cin_block> <cout_block> <kh_bound> <kw_bound> <cin_bound> <cout_bound> "
                     "<l2_prefetch_0_or_1> <same_tick_pinning_0_or_1> < ticks.bin\n";
        return 2;
    }
    try {
        CacheConfig l1{}, l2{};
        l1.cache_size_bytes = std::stoll(argv[1]);
        l1.cache_type = cache_type_from_name(argv[2]);
        l1.associativity = std::stoll(argv[3]);
        l2.cache_size_bytes = std::stoll(argv[4]);
        l2.cache_type = cache_type_from_name(argv[5]);
        l2.associativity = std::stoll(argv[6]);

        l1.line_size_bytes = l2.line_size_bytes = std::stoll(argv[7]);
        std::vector<Dim> order = parse_order(argv[8]);
        l1.layout = l2.layout = layout_from_name(argv[9]);
        l1.cin_block = l2.cin_block = std::stoll(argv[10]);
        l1.cout_block = l2.cout_block = std::stoll(argv[11]);
        l1.kh_bound = l2.kh_bound = std::stoll(argv[12]);
        l1.kw_bound = l2.kw_bound = std::stoll(argv[13]);
        l1.cin_bound = l2.cin_bound = std::stoll(argv[14]);
        l1.cout_bound = l2.cout_bound = std::stoll(argv[15]);
        l1.inner_dim = l2.inner_dim = KH; // unused under the hybrid layout
        l1.policy = l2.policy = "lru";
        bool l2_prefetch = parse_flag(argv[16], "l2_prefetch");
        bool same_tick_pinning = parse_flag(argv[17], "same_tick_pinning");

        if (l1.layout != Layout::Hybrid)
            throw std::runtime_error("cachesim: the hierarchical replay is defined on layout=hybrid only");
        // config.py's CacheConfig already rejects these before the bridge
        // shells out, but a zero radix would silently collapse every tag
        // onto one packed value, so the binary refuses it too rather than
        // reporting a plausible wrong hit rate.
        if (l1.cin_block <= 0 || l1.cout_block <= 0)
            throw std::runtime_error("cachesim: layout=hybrid needs positive cin_block/cout_block");
        if (l1.kw_bound <= 0 || l1.cin_bound <= 0 || l1.cout_bound <= 0)
            throw std::runtime_error("cachesim: layout=hybrid needs positive kw/cin/cout bounds");

        std::vector<std::vector<WireCore>> ticks = read_ticks();
        TagPacker packer = hybrid_packer(l1);
        TwoLevelHierarchy hierarchy(l1, l2, l2_prefetch, same_tick_pinning);

        for (const std::vector<WireCore> &tick : ticks) {
            std::vector<CoreRequest> cores;
            cores.reserve(tick.size());
            for (const WireCore &wc : tick)
                cores.push_back(CoreRequest{wc.core_id, packed_tags(wc.raw, order, l1, packer)});
            hierarchy.run_tick(cores);
        }

        std::vector<CoreL1Stats> per_core = hierarchy.per_core_l1();
        std::printf("%lld\n", (long long)per_core.size());
        for (const CoreL1Stats &s : per_core)
            std::printf("%lld %lld %lld\n", (long long)s.core_id, (long long)s.hits, (long long)s.accesses);
        std::printf("%lld %lld %lld %lld\n", (long long)hierarchy.l1_hits(), (long long)hierarchy.l1_accesses(),
                    (long long)hierarchy.l2_hits(), (long long)hierarchy.l2_accesses());
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "cache_replay_hierarchical: " << e.what() << "\n";
        return 1;
    }
}
