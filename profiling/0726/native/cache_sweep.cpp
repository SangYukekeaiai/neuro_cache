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
// Hit rate is counted PER BURST (one weight_addresses event), not per
// individual expanded (kh,kw,cin,cout) value: a burst is one physical
// memory transaction (address.py's own docstring: "a single contiguous
// line of weight data"), so consecutive expanded elements belonging to
// the same event that resolve to the same line tag are collapsed to
// their first occurrence before replay -- see
// log/2026-07-28-debug-pipeline-plan.md's "Concrete worked example" for
// the derivation this mirrors (2/12 = 1/6, not 38/48).
//
// Input (stdin, binary, little-endian):
//   uint32 n_samples
//   repeat n_samples:
//     uint32 n_events
//     repeat n_events: int32 kh, kw, cin, cout_start, cout_end
//
// Output (stdout, CSV):
//   default: one row per config -- cache_type,associativity,size_bytes,
//     inner_dim,layout,line_size,mean_hit_rate,n_samples
//   argv[2] == "persample": one row per (config, sample) instead --
//     cache_type,associativity,size_bytes,inner_dim,layout,line_size,
//     sample_idx,hit_rate
//
// argv[5] (optional): "cin_cout_2d" to sweep the alternate line layout
//   from log/2026-07-28-set-index-and-cin-cout-layout-plan.md Stage 2
//   instead of the default "cout_only" layout; only affects inner_dim=cout.

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
    std::vector<int32_t> event_id;          // which burst each element came from, for per-burst dedup
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
    s.event_id.reserve(total);
    for (uint32_t ei = 0; ei < n_events; ++ei) {
        const Event &e = events[ei];
        for (int32_t c = e.cout_start; c < e.cout_end; ++c) {
            s.kh.push_back(e.kh);
            s.kw.push_back(e.kw);
            s.cin.push_back(e.cin);
            s.cout.push_back(c);
            s.event_id.push_back(int32_t(ei));
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

static std::vector<int> parse_int_list(const char *s, std::vector<int> default_val) {
    if (s == nullptr || s[0] == '\0') return default_val;
    std::vector<int> out;
    std::string arg(s);
    size_t pos = 0;
    while (pos < arg.size()) {
        size_t comma = arg.find(',', pos);
        if (comma == std::string::npos) comma = arg.size();
        out.push_back(std::stoi(arg.substr(pos, comma - pos)));
        pos = comma + 1;
    }
    return out;
}

int main(int argc, char **argv) {
    // optional argv[1]: comma-separated STRUCTS indices to sweep, e.g.
    // "0,1,3,4" for direct_mapped + 4/16/32-way (skips 8-way and
    // fully_associative). Defaults to all 6 -- unchanged behavior when
    // omitted or empty, so existing callers don't need to change.
    std::vector<int> struct_ids = parse_int_list(argc > 1 ? argv[1] : nullptr, {0, 1, 2, 3, 4, 5});

    // optional argv[2] == "persample": stream one row per (config,
    // sample) as it's computed instead of accumulating into sum_rate
    // and printing only the mean -- for a per-sample distribution view
    // (mirrors profiling/0723's per-sample concentration boxplots).
    // Row format then becomes cache_type,associativity,size_bytes,
    // inner_dim,line_size,sample_idx,hit_rate (no mean/n_samples
    // columns). Off by default -- existing callers see identical output.
    bool per_sample = (argc > 2 && std::string(argv[2]) == "persample");

    // optional argv[3]: comma-separated inner-dim indices (0=kh,1=kw,
    // 2=cin,3=cout) to sweep. Defaults to all 4. Restricting this
    // matters for speed, unlike struct_ids/size filtering below: the
    // O(n_expanded_elements) tag-computation + per-burst-dedup pass
    // (this file's dominant cost for a large layer, not the cache
    // replay itself) runs once per (line_size, inner_dim) regardless of
    // which struct_ids/sizes are requested, so dropping 3 of 4 unwanted
    // inner_dims cuts that dominant pass to a quarter.
    std::vector<int> inner_ids = parse_int_list(argc > 3 ? argv[3] : nullptr, {0, 1, 2, 3});

    // optional argv[4]: comma-separated size_bytes values (must each
    // exactly match one of SIZES_BYTES) to sweep. Defaults to all 4.
    std::vector<int> size_ids;
    if (argc > 4 && argv[4][0] != '\0') {
        for (int requested : parse_int_list(argv[4], {})) {
            bool found = false;
            for (int iz = 0; iz < 4; ++iz) {
                if (SIZES_BYTES[iz] == requested) { size_ids.push_back(iz); found = true; break; }
            }
            if (!found) {
                std::cerr << "cache_sweep: --sizes value " << requested
                           << " is not one of 8192,16384,32768,65536\n";
                return 1;
            }
        }
    } else {
        size_ids = {0, 1, 2, 3};
    }

    // optional argv[5]: "cin_cout_2d" to use the alternate line layout
    // from log/2026-07-28-set-index-and-cin-cout-layout-plan.md Stage 2
    // (Path A): instead of one line holding line_size/W contiguous cout
    // values for one fixed cin (the default "cout_only" layout), a line
    // holds N_cin=max(1,line_size/W) adjacent cin values, each
    // contributing a fixed W-wide run of cout. Only affects id==COUT
    // (inner_dim=cout); kh/kw/cin as inner_dim are untouched by this
    // flag. W is the tile's burst width -- hardcoded to 16 here to match
    // every trace inspected so far (LoAS's node_bound[COUT] tile cap),
    // same "quick test, not fully plumbed" scope as Stage 0a's set-index
    // fix; reading it from the trace is Stage 0b-equivalent follow-up
    // work, not done here.
    bool cin_cout_2d = (argc > 5 && std::string(argv[5]) == "cin_cout_2d");
    const char *layout_name = cin_cout_2d ? "cin_cout_2d" : "cout_only";
    const int64_t BURST_W = 16;

    uint32_t n_samples = 0;
    if (fread(&n_samples, sizeof(n_samples), 1, stdin) != 1) {
        std::cerr << "cache_sweep: failed to read n_samples header\n";
        return 1;
    }

    // running sum of per-sample hit rates, one accumulator per
    // (inner_dim, line_size, struct_idx, size_idx) config -- sized for
    // the FULL grid regardless of filtering, so idx() stays simple;
    // entries for unrequested ids are just never written or read.
    const int N_INNER = 4, N_LINE = 3, N_STRUCT = 6, N_SIZE = 4;
    std::vector<double> sum_rate(size_t(N_INNER) * N_LINE * N_STRUCT * N_SIZE, 0.0);
    auto idx = [&](int id, int il, int is, int iz) {
        return ((size_t(id) * N_LINE + il) * N_STRUCT + is) * N_SIZE + iz;
    };

    for (uint32_t si = 0; si < n_samples; ++si) {
        Sample s = read_sample(stdin);
        size_t n = s.kh.size();
        if (n == 0) continue; // empty sample contributes nothing (mirrors hit_rate([])==0.0, skip to avoid div-by-zero)

        std::vector<int64_t> packed(n);

        for (int il = 0; il < N_LINE; ++il) {
            int line_size = LINE_SIZES[il];
            for (int id : inner_ids) {
                bool use_2d = cin_cout_2d && id == COUT;
                int64_t n_cin_group = use_2d ? std::max<int64_t>(1, line_size / BURST_W) : 1;
                int64_t b_cout = use_2d ? std::min<int64_t>(line_size, BURST_W) : line_size;

                int64_t max_kw = 0, max_cin = 0, max_cout = 0;
                for (size_t i = 0; i < n; ++i) {
                    int64_t kw_t = (id == KW) ? (s.kw[i] / line_size) : s.kw[i];
                    int64_t cin_t = use_2d ? (s.cin[i] / n_cin_group)
                                            : ((id == CIN) ? (s.cin[i] / line_size) : s.cin[i]);
                    int64_t cout_t = use_2d ? (s.cout[i] / b_cout)
                                             : ((id == COUT) ? (s.cout[i] / line_size) : s.cout[i]);
                    if (kw_t > max_kw) max_kw = kw_t;
                    if (cin_t > max_cin) max_cin = cin_t;
                    if (cout_t > max_cout) max_cout = cout_t;
                }
                int64_t m_kw = max_kw + 1, m_cin = max_cin + 1, m_cout = max_cout + 1;
                for (size_t i = 0; i < n; ++i) {
                    int64_t kh_t = (id == KH) ? (s.kh[i] / line_size) : s.kh[i];
                    int64_t kw_t = (id == KW) ? (s.kw[i] / line_size) : s.kw[i];
                    int64_t cin_t = use_2d ? (s.cin[i] / n_cin_group)
                                            : ((id == CIN) ? (s.cin[i] / line_size) : s.cin[i]);
                    int64_t cout_t = use_2d ? (s.cout[i] / b_cout)
                                             : ((id == COUT) ? (s.cout[i] / line_size) : s.cout[i]);
                    packed[i] = ((kh_t * m_kw + kw_t) * m_cin + cin_t) * m_cout + cout_t;
                }

                // Collapse consecutive elements of the SAME burst that
                // resolve to the SAME line tag down to one access (see
                // this file's header): a burst is one memory transaction,
                // so repeat reads of a line it just brought in aren't
                // separate accesses. Never dedupes across an event
                // boundary, even if two different bursts happen to share
                // a tag.
                std::vector<int64_t> dpacked;
                dpacked.reserve(n);
                for (size_t i = 0; i < n; ++i) {
                    bool new_event = (i == 0) || (s.event_id[i] != s.event_id[i - 1]);
                    if (new_event || packed[i] != dpacked.back()) {
                        dpacked.push_back(packed[i]);
                    }
                }
                size_t dn = dpacked.size();

                for (int is : struct_ids) {
                    const StructConfig &sc = STRUCTS[is];
                    for (int iz : size_ids) {
                        int64_t capacity_lines = SIZES_BYTES[iz] / line_size;
                        if (capacity_lines < 1) capacity_lines = 1;

                        int64_t hits = 0;
                        if (std::strcmp(sc.cache_type, "fully_associative") == 0) {
                            BigLRU cache{size_t(capacity_lines)};
                            for (size_t i = 0; i < dn; ++i) hits += cache.access(dpacked[i]);
                        } else {
                            int ways = (std::strcmp(sc.cache_type, "direct_mapped") == 0) ? 1 : sc.assoc;
                            int64_t num_sets = capacity_lines / ways;
                            if (num_sets < 1) num_sets = 1;
                            SmallLRU cache(ways, int(num_sets));
                            for (size_t i = 0; i < dn; ++i) {
                                int set_idx = int(((dpacked[i] % num_sets) + num_sets) % num_sets);
                                hits += cache.access(set_idx, dpacked[i]);
                            }
                        }
                        double rate = double(hits) / double(dn);
                        if (per_sample) {
                            const StructConfig &sc = STRUCTS[is];
                            std::printf("%s,%d,%lld,%s,%s,%d,%u,%.6f\n",
                                        sc.cache_type, sc.assoc, (long long)SIZES_BYTES[iz],
                                        INNER_DIM_NAMES[id], layout_name, LINE_SIZES[il], si, rate);
                        } else {
                            sum_rate[idx(id, il, is, iz)] += rate;
                        }
                    }
                }
            }
        }
    }

    if (!per_sample) {
        for (int id : inner_ids) {
            for (int il = 0; il < N_LINE; ++il) {
                for (int is : struct_ids) {
                    for (int iz : size_ids) {
                        double mean_rate = n_samples > 0 ? sum_rate[idx(id, il, is, iz)] / n_samples : 0.0;
                        const StructConfig &sc = STRUCTS[is];
                        std::printf("%s,%d,%lld,%s,%s,%d,%.6f,%u\n",
                                    sc.cache_type, sc.assoc, (long long)SIZES_BYTES[iz],
                                    INNER_DIM_NAMES[id], layout_name, LINE_SIZES[il], mean_rate, n_samples);
                    }
                }
            }
        }
    }
    return 0;
}
