// reuse_tool: an access log in, a reuse-distance histogram out.
//
// Plan unit U3 of log/2026-08-31-reuse-distance-plan.md.
//
//     reuse_tool <access.log> <out.csv> [--dump N]
//
// The log is what `wcache_run --access-log` wrote: an 8-byte magic followed by
// fixed-width 8-byte records. `--dump N` prints the first N records in readable
// form and writes no CSV, which is the escape hatch that makes a binary format
// affordable.
//
// SEVENTEEN STACKS, not one. Each of the sixteen L1s is private, so a core's
// references are the only ones that can displace its own lines; feeding them all
// into one stack would count other cores' references as distinct lines and
// inflate every distance. The L2 is shared and gets exactly one stack, which is
// the point of measuring it at a fixed config: its interleaving is set by
// timing.
//
// Cores are discovered from the log rather than configured, so a corpus with a
// different core count needs no flag and cannot be silently mismatched.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "reuse_distance.h"

namespace {

constexpr std::uint64_t kMagic = 0x5743414C4F473031ULL;  // "WCALOG01", as written

struct Record {
    std::uint8_t  level;
    std::uint8_t  core;
    std::uint8_t  demand;
    std::uint8_t  pad;
    std::uint32_t line;
};
static_assert(sizeof(Record) == 8, "record must match the writer's 8 bytes");

[[noreturn]] void die(const std::string& what) {
    std::fprintf(stderr, "reuse_tool: %s\n", what.c_str());
    std::exit(EXIT_FAILURE);
}

// One stack plus the identity it reports under.
struct Stack {
    reuse::ReuseHistogram hist;
    std::int64_t          refs = 0;
};

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) die("usage: reuse_tool <access.log> <out.csv> [--dump N]");
    const std::string in_path(argv[1]);
    const std::string out_path(argv[2]);
    std::int64_t dump = 0;
    for (int i = 3; i < argc; ++i) {
        if (std::strcmp(argv[i], "--dump") == 0 && i + 1 < argc) dump = std::atoll(argv[++i]);
        else die("unknown argument " + std::string(argv[i]));
    }

    std::ifstream in(in_path, std::ios::binary);
    if (!in) die("cannot read " + in_path);

    std::uint64_t magic = 0;
    in.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    if (!in || magic != kMagic) {
        die(in_path + " is not an access log (magic mismatch); a truncated or stale "
                      "file decodes as plausible garbage, so this is refused rather than parsed");
    }

    // L1 stacks are keyed by core and created on first sight; the L2 has one.
    std::map<std::int32_t, Stack> l1;
    Stack                         l2;
    std::int64_t                  n = 0, n_l1 = 0, n_l2 = 0, non_demand = 0;

    // Batched reads for the same reason the writer batches: 55M single-record
    // reads is the difference between seconds and minutes.
    constexpr std::size_t kBatch = 1 << 16;
    std::vector<Record>   buf(kBatch);

    if (dump > 0) std::printf("%10s %6s %6s %12s\n", "index", "level", "core", "line");

    for (;;) {
        in.read(reinterpret_cast<char*>(buf.data()),
                static_cast<std::streamsize>(kBatch * sizeof(Record)));
        const std::size_t got = static_cast<std::size_t>(in.gcount()) / sizeof(Record);
        if (in.gcount() % static_cast<std::streamsize>(sizeof(Record)) != 0) {
            die(in_path + " has a trailing partial record, so the run that wrote it "
                          "did not finish");
        }
        for (std::size_t i = 0; i < got; ++i) {
            const Record& r = buf[i];
            if (dump > 0 && n < dump) {
                std::printf("%10lld %6s %6u %12u\n", static_cast<long long>(n),
                            r.level == 0 ? "l1" : "l2", static_cast<unsigned>(r.core),
                            static_cast<unsigned>(r.line));
            }
            ++n;
            if (r.demand != 1) { ++non_demand; continue; }
            if (r.level == 0) {
                Stack& s = l1[static_cast<std::int32_t>(r.core)];
                s.hist.observe(static_cast<std::int64_t>(r.line));
                ++s.refs;
                ++n_l1;
            } else {
                l2.hist.observe(static_cast<std::int64_t>(r.line));
                ++l2.refs;
                ++n_l2;
            }
        }
        if (got < kBatch) break;
    }

    if (non_demand != 0) {
        // The writer only ever emits demand references today. A non-demand
        // record means the engine's guard changed and the distances would then
        // include prefetch probes, which are not uses.
        die("log contains " + std::to_string(non_demand) +
            " non-demand records; distances would include probes that are not uses");
    }

    if (dump > 0) {
        std::fprintf(stderr, "reuse_tool: %lld records (%lld l1, %lld l2), no CSV written\n",
                     static_cast<long long>(n), static_cast<long long>(n_l1),
                     static_cast<long long>(n_l2));
        return EXIT_SUCCESS;
    }

    std::ofstream out(out_path);
    if (!out) die("cannot write " + out_path);

    // Sparse: only distances that actually occurred. Cold is distance -1 and is
    // a bucket rather than an omission, because a run's cold count is the
    // distinct-line count and it sets the ceiling of the hit-rate curve.
    out << "level,core,distance,count\n";
    auto emit = [&out](const char* level, std::int32_t core, const reuse::ReuseHistogram& h) {
        out << level << ',' << core << ",-1," << h.cold() << '\n';
        const std::vector<std::int64_t>& c = h.counts();
        for (std::size_t d = 0; d < c.size(); ++d) {
            if (c[d] != 0) out << level << ',' << core << ',' << d << ',' << c[d] << '\n';
        }
    };
    for (const auto& kv : l1) emit("l1", kv.first, kv.second.hist);
    emit("l2", -1, l2.hist);

    std::fprintf(stderr,
                 "reuse_tool: %lld records -> %s   l1 %lld refs over %zu cores, l2 %lld refs\n",
                 static_cast<long long>(n), out_path.c_str(), static_cast<long long>(n_l1),
                 l1.size(), static_cast<long long>(n_l2));
    return EXIT_SUCCESS;
}
