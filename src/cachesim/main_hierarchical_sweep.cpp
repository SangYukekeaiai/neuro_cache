// Fixed 24-point hierarchy sweep for Milestone 4 of
// log/2026-08-03-l1-l2-cache-policy-plan.md. The input is one sample in
// main_hierarchical.cpp's ticks.bin format. It is packed once, then
// replayed through the approved grid:
//   3 shared L1/L2 structures x 2 L1 sizes x 4 L2 sizes.

#include <cstdint>
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "config.h"
#include "dims.h"
#include "hierarchy.h"
#include "layout.h"

using namespace cachesim;

namespace {

template <typename T>
T read_pod(const char *what) {
    T value;
    if (std::fread(&value, sizeof(value), 1, stdin) != 1)
        throw std::runtime_error(std::string("failed to read ") + what);
    return value;
}

std::vector<int64_t> read_packed_events(uint32_t n_events, const std::vector<Dim> &order,
                                        const CacheConfig &cfg, const TagPacker &packer) {
    std::vector<int64_t> tags;
    for (uint32_t event_i = 0; event_i < n_events; ++event_i) {
        int32_t raw[5];
        if (std::fread(raw, sizeof(int32_t), 5, stdin) != 5)
            throw std::runtime_error("unexpected EOF reading events");
        bool have_previous = false;
        int64_t previous = 0;
        for_each_element(raw, order, [&](const Element &element) {
            int64_t packed = packer.pack(tag_for_element_hybrid(element, cfg.cin_block, cfg.cout_block));
            if (have_previous && packed == previous) return;
            tags.push_back(packed);
            have_previous = true;
            previous = packed;
        });
    }
    return tags;
}

std::vector<std::vector<CoreRequest>> read_ticks(const std::vector<Dim> &order,
                                                 const CacheConfig &cfg, const TagPacker &packer) {
    uint32_t n_ticks = read_pod<uint32_t>("n_ticks");
    std::vector<std::vector<CoreRequest>> ticks(n_ticks);
    for (uint32_t tick_i = 0; tick_i < n_ticks; ++tick_i) {
        uint32_t n_cores = read_pod<uint32_t>("n_cores");
        ticks[tick_i].reserve(n_cores);
        int64_t previous_core = -1;
        for (uint32_t core_i = 0; core_i < n_cores; ++core_i) {
            int32_t core_id = read_pod<int32_t>("core_id");
            uint32_t n_events = read_pod<uint32_t>("n_events");
            if (core_i > 0 && core_id <= previous_core)
                throw std::runtime_error("cores must be in ascending core_id order");
            previous_core = core_id;
            ticks[tick_i].push_back(CoreRequest{
                core_id,
                read_packed_events(n_events, order, cfg, packer),
            });
        }
    }
    return ticks;
}

struct Structure {
    const char *name;
    CacheType type;
    int64_t associativity;
};

const Structure STRUCTURES[] = {
    {"fully_associative", CacheType::FullyAssociative, 0},
    {"set_associative", CacheType::SetAssociative, 32},
    {"set_associative", CacheType::SetAssociative, 4},
};
const int64_t L1_SIZES[] = {16 * 1024, 32 * 1024};
const int64_t L2_SIZES[] = {128 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024};

CacheConfig config_for(const CacheConfig &layout, const Structure &structure, int64_t size_bytes) {
    CacheConfig cfg = layout;
    cfg.cache_size_bytes = size_bytes;
    cfg.cache_type = structure.type;
    cfg.associativity = structure.associativity;
    return cfg;
}

} // namespace

int main(int argc, char **argv) {
    if (argc != 6) {
        std::cerr << "usage: cache_sweep_hierarchical <order_csv> <kh_bound> <kw_bound> "
                     "<cin_bound> <cout_bound> < ticks.bin\n";
        return 2;
    }

    try {
        CacheConfig layout{};
        layout.cache_size_bytes = L1_SIZES[0];
        layout.line_size_bytes = 16;
        layout.cache_type = CacheType::FullyAssociative;
        layout.inner_dim = KH;
        layout.associativity = 0;
        layout.policy = "lru";
        layout.layout = Layout::Hybrid;
        layout.cin_block = 4;
        layout.cout_block = 4;
        layout.kh_bound = std::stoll(argv[2]);
        layout.kw_bound = std::stoll(argv[3]);
        layout.cin_bound = std::stoll(argv[4]);
        layout.cout_bound = std::stoll(argv[5]);
        if (layout.kh_bound <= 0 || layout.kw_bound <= 0 || layout.cin_bound <= 0 || layout.cout_bound <= 0)
            throw std::runtime_error("shape bounds must be positive");

        std::vector<Dim> order = parse_order(argv[1]);
        TagPacker packer = hybrid_packer(layout);
        std::vector<std::vector<CoreRequest>> ticks = read_ticks(order, layout, packer);

        constexpr int64_t n_configs = 3 * 2 * 4;
        std::printf("%lld\n", (long long)n_configs);
        for (const Structure &structure : STRUCTURES) {
            for (int64_t l1_size : L1_SIZES) {
                for (int64_t l2_size : L2_SIZES) {
                    CacheConfig l1 = config_for(layout, structure, l1_size);
                    CacheConfig l2 = config_for(layout, structure, l2_size);
                    TwoLevelHierarchy hierarchy(l1, l2, true, true);
                    for (const std::vector<CoreRequest> &tick : ticks) hierarchy.run_tick(tick);

                    std::vector<CoreL1Stats> per_core = hierarchy.per_core_l1();
                    std::printf("%s %lld %lld %lld %lld %lld %lld %lld %lld\n", structure.name,
                                (long long)structure.associativity, (long long)l1_size, (long long)l2_size,
                                (long long)per_core.size(), (long long)hierarchy.l1_hits(),
                                (long long)hierarchy.l1_accesses(), (long long)hierarchy.l2_hits(),
                                (long long)hierarchy.l2_accesses());
                    for (const CoreL1Stats &stats : per_core)
                        std::printf("%lld %lld %lld\n", (long long)stats.core_id,
                                    (long long)stats.hits, (long long)stats.accesses);
                }
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "cache_sweep_hierarchical: " << error.what() << "\n";
        return 1;
    }
}
