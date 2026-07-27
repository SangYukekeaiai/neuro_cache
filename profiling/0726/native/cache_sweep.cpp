// cache_sweep: for one (arch, workload, layer), replay every one of its
// weight-trace samples through the full cache-config grid --
//   cache_type/associativity: direct_mapped, 4/8/16/32-way set_associative, fully_associative
//   size_bytes:               8192, 16384, 32768, 65536
//   inner_dim:                kh, kw, cin, cout
//   line_size_bytes:          16, 32, 64
// (6 x 4 x 4 x 3 = 288 configs) and report the mean hit rate across
// samples for each config. Mirrors src/cachesim's semantics exactly
// (same tag formation as layout.py: one dim collapses via floor-division
// by line_size, the rest stay exact; same set-index rule as cache.py:
// sum(tag components) % num_sets; same LRU eviction as policy.py) but in
// C++, because a pure-Python pass over one sample of the largest layer
// (15M expanded elements) took 20+ minutes for a SINGLE config -- 288
// configs x 100 samples x ~30 layers would not finish in any usable
// time. Same standalone-binary + subprocess pattern as
// src/archmodels/*/native and src/nocsim/eventsim.
//
// Input (stdin, binary, little-endian):
//   uint32 n_samples
//   repeat n_samples:
//     uint32 n_events
//     repeat n_events: int32 kh, kw, cin, cout_start, cout_end
//
// Output (stdout, CSV, one row per config):
//   cache_type,associativity,size_bytes,inner_dim,line_size,mean_hit_rate,n_samples

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>
#include <list>
#include <unordered_map>
#include <iostream>

struct Event { int32_t kh, kw, cin, cout_start, cout_end; };

struct Sample {
    std::vector<int64_t> kh, kw, cin, cout; // one entry per expanded (kh,kw,cin,cout) element
};

static Sample read_sample(FILE *in) {
    uint32_t n_events = 0;
    if (fread(&n_events, sizeof(n_events), 1, in) != 1) {
        throw std::runtime_error("cache_sweep: unexpected EOF reading n_events");
    }
    std::vector<Event> events(n_events);
    if (n_events > 0 && fread(events.data(), sizeof(Event), n_events, in) != n_events) {
        throw std::runtime_error("cache_sweep: unexpected EOF reading events");
    }

    size_t total = 0;
    for (auto &e : events) total += size_t(e.cout_end - e.cout_start);

    Sample s;
    s.kh.reserve(total); s.kw.reserve(total); s.cin.reserve(total); s.cout.reserve(total);
    for (auto &e : events) {
        for (int32_t c = e.cout_start; c < e.cout_end; ++c) {
            s.kh.push_back(e.kh);
            s.kw.push_back(e.kw);
            s.cin.push_back(e.cin);
            s.cout.push_back(c);
        }
    }
    return s;
}

enum InnerDim { KH = 0, KW = 1, CIN = 2, COUT = 3 };
static const char *INNER_DIM_NAMES[4] = {"kh", "kw", "cin", "cout"};
static const int LINE_SIZES[3] = {16, 32, 64};
static const int64_t SIZES_BYTES[4] = {8192, 16384, 32768, 65536};

struct StructConfig { const char *cache_type; int assoc; }; // assoc==0 means N/A
static const StructConfig STRUCTS[6] = {
    {"direct_mapped", 0},
    {"set_associative", 4},
    {"set_associative", 8},
    {"set_associative", 16},
    {"set_associative", 32},
    {"fully_associative", 0},
};

// Direct-mapped / small-associativity LRU: each set is a fixed-size
// MRU-first array (ways is at most 32 here), linear scan + shift. Faster
// than a hashmap+list for such small capacities -- no allocation, good
// cache locality.
struct SmallLRU {
    int ways;
    std::vector<int64_t> slots; // num_sets * ways, -1 == empty

    SmallLRU(int ways_, int num_sets_) : ways(ways_), slots(size_t(ways_) * size_t(num_sets_), -1) {}

    inline bool access(int set_idx, int64_t tag) {
        int64_t *base = &slots[size_t(set_idx) * ways];
        for (int i = 0; i < ways; ++i) {
            if (base[i] == tag) {
                for (int j = i; j > 0; --j) base[j] = base[j - 1];
                base[0] = tag;
                return true;
            }
            if (base[i] == -1) break; // rest of this set is still empty
        }
        for (int j = ways - 1; j > 0; --j) base[j] = base[j - 1];
        base[0] = tag;
        return false;
    }
};

// Fully-associative LRU: capacity can be up to 4096 lines (64KB / 16B),
// too large for linear scan, so real O(1) hashmap + doubly-linked list.
// Only ever used with num_sets == 1 in this sweep (fully_associative
// never has more than one set, by construction of _num_sets_and_ways).
struct BigLRU {
    size_t capacity;
    std::list<int64_t> order; // front == most recently used
    std::unordered_map<int64_t, std::list<int64_t>::iterator> map;

    explicit BigLRU(size_t capacity_) : capacity(capacity_) { map.reserve(capacity_ * 2); }

    inline bool access(int64_t tag) {
        auto it = map.find(tag);
        if (it != map.end()) {
            order.erase(it->second);
            order.push_front(tag);
            it->second = order.begin();
            return true;
        }
        if (order.size() >= capacity) {
            int64_t victim = order.back();
            order.pop_back();
            map.erase(victim);
        }
        order.push_front(tag);
        map[tag] = order.begin();
        return false;
    }
};

int main(int argc, char **argv) {
    // optional argv[1]: comma-separated STRUCTS indices to sweep, e.g.
    // "0,1,3,4" for direct_mapped + 4/16/32-way (skips 8-way and
    // fully_associative). Defaults to all 6 -- unchanged behavior when
    // omitted, so existing callers don't need to change.
    std::vector<int> struct_ids;
    if (argc > 1) {
        std::string arg(argv[1]);
        size_t pos = 0;
        while (pos < arg.size()) {
            size_t comma = arg.find(',', pos);
            if (comma == std::string::npos) comma = arg.size();
            struct_ids.push_back(std::stoi(arg.substr(pos, comma - pos)));
            pos = comma + 1;
        }
    } else {
        struct_ids = {0, 1, 2, 3, 4, 5};
    }

    uint32_t n_samples = 0;
    if (fread(&n_samples, sizeof(n_samples), 1, stdin) != 1) {
        std::cerr << "cache_sweep: failed to read n_samples header\n";
        return 1;
    }

    // running sum of per-sample hit rates, one accumulator per
    // (inner_dim, line_size, struct_idx, size_idx) config
    const int N_INNER = 4, N_LINE = 3, N_STRUCT = 6, N_SIZE = 4;
    std::vector<double> sum_rate(size_t(N_INNER) * N_LINE * N_STRUCT * N_SIZE, 0.0);
    auto idx = [&](int id, int il, int is, int iz) {
        return ((size_t(id) * N_LINE + il) * N_STRUCT + is) * N_SIZE + iz;
    };

    for (uint32_t si = 0; si < n_samples; ++si) {
        Sample s = read_sample(stdin);
        size_t n = s.kh.size();
        if (n == 0) continue; // empty sample contributes nothing (mirrors hit_rate([])==0.0, skip to avoid div-by-zero)

        std::vector<int64_t> tag_sum(n), packed(n);

        for (int il = 0; il < N_LINE; ++il) {
            int line_size = LINE_SIZES[il];
            for (int id = 0; id < N_INNER; ++id) {
                int64_t max_kw = 0, max_cin = 0, max_cout = 0;
                for (size_t i = 0; i < n; ++i) {
                    int64_t kh_t = (id == KH) ? (s.kh[i] / line_size) : s.kh[i];
                    int64_t kw_t = (id == KW) ? (s.kw[i] / line_size) : s.kw[i];
                    int64_t cin_t = (id == CIN) ? (s.cin[i] / line_size) : s.cin[i];
                    int64_t cout_t = (id == COUT) ? (s.cout[i] / line_size) : s.cout[i];
                    tag_sum[i] = kh_t + kw_t + cin_t + cout_t;
                    if (kw_t > max_kw) max_kw = kw_t;
                    if (cin_t > max_cin) max_cin = cin_t;
                    if (cout_t > max_cout) max_cout = cout_t;
                }
                int64_t m_kw = max_kw + 1, m_cin = max_cin + 1, m_cout = max_cout + 1;
                for (size_t i = 0; i < n; ++i) {
                    int64_t kh_t = (id == KH) ? (s.kh[i] / line_size) : s.kh[i];
                    int64_t kw_t = (id == KW) ? (s.kw[i] / line_size) : s.kw[i];
                    int64_t cin_t = (id == CIN) ? (s.cin[i] / line_size) : s.cin[i];
                    int64_t cout_t = (id == COUT) ? (s.cout[i] / line_size) : s.cout[i];
                    packed[i] = ((kh_t * m_kw + kw_t) * m_cin + cin_t) * m_cout + cout_t;
                }

                for (int is : struct_ids) {
                    const StructConfig &sc = STRUCTS[is];
                    for (int iz = 0; iz < N_SIZE; ++iz) {
                        int64_t capacity_lines = SIZES_BYTES[iz] / line_size;
                        if (capacity_lines < 1) capacity_lines = 1;

                        int64_t hits = 0;
                        if (std::strcmp(sc.cache_type, "fully_associative") == 0) {
                            BigLRU cache{size_t(capacity_lines)};
                            for (size_t i = 0; i < n; ++i) hits += cache.access(packed[i]);
                        } else {
                            int ways = (std::strcmp(sc.cache_type, "direct_mapped") == 0) ? 1 : sc.assoc;
                            int64_t num_sets = capacity_lines / ways;
                            if (num_sets < 1) num_sets = 1;
                            SmallLRU cache(ways, int(num_sets));
                            for (size_t i = 0; i < n; ++i) {
                                int set_idx = int(((tag_sum[i] % num_sets) + num_sets) % num_sets);
                                hits += cache.access(set_idx, packed[i]);
                            }
                        }
                        sum_rate[idx(id, il, is, iz)] += double(hits) / double(n);
                    }
                }
            }
        }
    }

    for (int id = 0; id < N_INNER; ++id) {
        for (int il = 0; il < N_LINE; ++il) {
            for (int is : struct_ids) {
                for (int iz = 0; iz < N_SIZE; ++iz) {
                    double mean_rate = n_samples > 0 ? sum_rate[idx(id, il, is, iz)] / n_samples : 0.0;
                    const StructConfig &sc = STRUCTS[is];
                    std::printf("%s,%d,%lld,%s,%d,%.6f,%u\n",
                                sc.cache_type, sc.assoc, (long long)SIZES_BYTES[iz],
                                INNER_DIM_NAMES[id], LINE_SIZES[il], mean_rate, n_samples);
                }
            }
        }
    }
    return 0;
}
