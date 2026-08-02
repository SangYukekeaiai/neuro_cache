// cache_replay: native port of src/cachesim's four reviewed Python
// modules, split the same way -- config.h/layout.h/policy.h/cache.h
// mirror config.py/layout.py/policy.py/cache.py one-to-one; this file is
// the orchestration layer, mirroring sweep.py's sample_hit_rate: load
// one sample's events, expand + tag + replay through one Cache, report
// the hit rate. Same subprocess-bridge pattern as src/archmodels/*/native
// and src/nocsim/eventsim.
//
// Exists because the pure-Python replay in cache.py, while correct and
// the reference implementation, does one Python object (NamedTuple /
// OrderedDict entry) per expanded weight element -- ~15-17x slower per
// (sample, config) than this port on real data (single-config timing;
// dump/profiling/0726/native/cache_sweep.cpp's specialized all-288-at-once
// sweep amortizes further, to ~110x, by sharing tag work across configs).
//
// Usage:
//   cache_replay <cache_size_bytes> <line_size_bytes> <cache_type> \
//                <associativity_or_0> <inner_dim> <order_csv>
//   < events.bin > stdout: "<hits> <total> <hit_rate>\n"
//
// events.bin (stdin, binary, little-endian), one sample:
//   uint32 n_events
//   repeat n_events: int32 v0, v1, v2, v3, v4   (raw address tuple)

#include <cstdint>
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <vector>

#include "cache.h"
#include "config.h"
#include "dims.h"
#include "layout.h"

using namespace cachesim;

int main(int argc, char **argv) {
    if (argc != 7) {
        std::cerr << "usage: cache_replay <cache_size_bytes> <line_size_bytes> <cache_type> "
                     "<associativity_or_0> <inner_dim> <order_csv> < events.bin\n";
        return 2;
    }
    try {
        CacheConfig cfg;
        cfg.cache_size_bytes = std::stoll(argv[1]);
        cfg.line_size_bytes = std::stoll(argv[2]);
        cfg.cache_type = cache_type_from_name(argv[3]);
        cfg.associativity = std::stoll(argv[4]);
        cfg.inner_dim = dim_from_name(argv[5]);
        cfg.policy = "lru";
        std::vector<Dim> order = parse_order(argv[6]);

        // -- read the one sample's raw events --
        uint32_t n_events = 0;
        if (fread(&n_events, sizeof(n_events), 1, stdin) != 1) {
            throw std::runtime_error("failed to read n_events header");
        }
        std::vector<int32_t> raw(size_t(n_events) * 5);
        if (n_events > 0 && fread(raw.data(), sizeof(int32_t), raw.size(), stdin) != raw.size()) {
            throw std::runtime_error("unexpected EOF reading events");
        }

        // Pre-scan (over raw events, not expanded elements -- cheap) for
        // TagPacker's mixed-radix bounds; see layout.h's TagPacker docstring.
        Dim ranged_dim = order[3];
        int64_t max_by_dim[N_DIMS] = {0, 0, 0, 0};
        for (uint32_t ei = 0; ei < n_events; ++ei) {
            int32_t v0 = raw[ei * 5 + 0], v1 = raw[ei * 5 + 1], v2 = raw[ei * 5 + 2],
                    v3 = raw[ei * 5 + 3], v4 = raw[ei * 5 + 4];
            // An empty range expands to no elements, so it must not widen
            // the radices either: the Python pack_tags only ever sees tags
            // that exist.
            if (v3 >= v4) continue;
            if (v0 > max_by_dim[order[0]]) max_by_dim[order[0]] = v0;
            if (v1 > max_by_dim[order[1]]) max_by_dim[order[1]] = v1;
            if (v2 > max_by_dim[order[2]]) max_by_dim[order[2]] = v2;
            if (v4 - 1 > max_by_dim[ranged_dim]) max_by_dim[ranged_dim] = v4 - 1;
        }
        max_by_dim[cfg.inner_dim] /= cfg.line_size_bytes;
        TagPacker packer(max_by_dim[KW], max_by_dim[CIN], max_by_dim[COUT]);

        Cache cache(cfg);
        int64_t hits = 0, total = 0;

        // Per burst, not per weight value: one event is one memory
        // transaction, so its expanded elements collapse to the DISTINCT
        // consecutive line tags that burst touches (a burst spanning
        // several lines still costs one access per line). `prev` resets
        // per event, so dedup never crosses an event boundary.
        for (uint32_t ei = 0; ei < n_events; ++ei) {
            const int32_t *v = &raw[ei * 5];
            bool have_prev = false;
            int64_t prev = 0;
            for_each_element(v, order, [&](const Element &e) {
                Tag t = tag_for_element(e, cfg.inner_dim, cfg.line_size_bytes);
                int64_t packed = packer.pack(t);
                if (have_prev && packed == prev) return;
                have_prev = true;
                prev = packed;
                hits += cache.access(packed) ? 1 : 0;
                ++total;
            });
        }

        double hit_rate = total > 0 ? double(hits) / double(total) : 0.0;
        std::printf("%lld %lld %.6f\n", (long long)hits, (long long)total, hit_rate);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "cache_replay: " << e.what() << "\n";
        return 1;
    }
}
