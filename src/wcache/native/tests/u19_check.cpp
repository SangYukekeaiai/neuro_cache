// U19, measured rather than read off the source: is core_stall == fetch_latency
// under every prefetch distance, INCLUDING ones where the prefetcher
// demonstrably hides latency? Built against test_prefetch.cpp's own
// `miss_params` (4.6's worked example, where a full miss costs 110 cycles) so
// the answer is not vacuous on a config where every access is free.
//
// NOT part of `make test`: the Makefile's glob is `tests/test_*.cpp`, and this
// is evidence for an open question rather than a check on built behaviour, so
// it is deliberately named outside that pattern (the Makefile anticipates
// exactly this at line 51). Build and run it by hand:
//
//     g++ -std=c++17 -O1 -Iinclude -Itests -o /tmp/u19 \
//         tests/u19_check.cpp src/*.cpp && /tmp/u19
//
// Result, 2026-08-20: the difference is 0 at d = 0, 1, 2, 4 and 8, while
// `fetch_latency` itself falls 6600 -> 825. The prefetcher hides eight ninths
// of the latency and the metric Part 8 calls "the single number the policy
// should be judged on" reads zero at every point.
#include <wcache/engine.h>

#include "engine_fixture.h"

#include <cstdio>

using namespace wcache;
using fx::FakeTrace;
using fx::LinearMapper;

namespace {
constexpr std::int64_t kL1Sets = 8;
constexpr std::int64_t kL2Sets = 64;

FakeTrace sweep_trace(std::int32_t n, std::int64_t gap) {
    FakeTrace tr(1);
    const std::int32_t t0 = tr.add_tile();
    for (std::int32_t k = 0; k < n; ++k) tr.add_burst(t0, 0, gap * k, k);
    return tr;
}

EngineParams miss_params() {
    EngineParams p     = fx::unbounded_params(kL1Sets, 4);
    p.l1               = fx::level(kL1Sets, 4, 8, 4, 1);
    p.l2               = fx::level(kL2Sets, 4, 8, 4, 1);
    p.l1.ii            = SimTime{1};
    p.l1.latency       = SimTime{0};
    p.l2.ii            = SimTime{1};
    p.l2.latency       = SimTime{10};
    p.l2_to_l1_latency = SimTime{0};
    p.l2_miss_latency  = SimTime{100};
    p.dram_ii          = SimTime{1};
    return p;
}
}  // namespace

int main() {
    std::printf("  d   core_stall   fetch_latency   difference\n");
    int differed = 0;
    for (std::int32_t d : {0, 1, 2, 4, 8}) {
        FakeTrace tr = sweep_trace(60, 4);
        LinearMapper m(64);
        EngineParams p      = miss_params();
        p.prefetch_policy   = d == 0 ? PrefetchKind::None : PrefetchKind::NextBurst;
        p.prefetch_distance = d;
        Engine eng(m, tr, p);
        eng.run();

        std::int64_t stall = 0, lat = 0;
        for (std::size_t c = 0; c < eng.stats().core_stall.size(); ++c) {
            stall += eng.stats().core_stall[c];
            lat += eng.stats().fetch_latency[c];
            if (eng.stats().core_stall[c] != eng.stats().fetch_latency[c]) ++differed;
        }
        std::printf("%3d %12lld %15lld %12lld\n", d, (long long)stall, (long long)lat,
                    (long long)(stall - lat));
    }
    std::printf("\n%s\n", differed == 0 ? "core_stall == fetch_latency for EVERY core at EVERY d"
                                        : "they differed somewhere");
    return 0;
}
