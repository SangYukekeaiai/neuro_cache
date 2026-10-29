// Belady's oracles, one per L1 and one shared for the L2, shared by the native
// drivers rather than written twice. Two copies of a definition are two places
// for it to drift, and an oracle built one way in cachesim_run and another way
// in cachesim_sweep would look like a policy effect.
#pragma once

#include <cstdint>
#include <fstream>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "cachesim/config.h"
#include "cachesim/core/engine.h"
#include "cachesim/instrument/access_log.h"
#include "cachesim/replacement/next_use.h"

namespace cachesim {
namespace app {

// Both levels' reference streams, from ONE pass of the log. The L1's is split
// by core because the L1 is PRIVATE: an oracle over the merged stream would tell
// core 3 the future of core 7's references, and every line would look far more
// often referenced than it is. The L2's is not split, because the L2 is shared
// and belongs to no core.
//
// Only demand records are kept, at either level, matching what `l1_accesses` and
// `l2_accesses` count and what the level's own occurrence counter advances on.
//
// File order is the whole contract: `NextUseOracle` is keyed by (line,
// occurrence), so the k-th record for a line at a level must be the k-th
// reference the level makes to it.
//
// `l1_by_core` is a POINTER, and a null one means the caller wants the L2
// stream alone. That is what `--l2-oracle` wants, and it is not merely a
// convenience: keeping the L1 buckets for a caller that discards them allocates
// the whole per-core L1 stream for nothing, 66 MB of a 70 MB peak on one R10
// sample and 162 MB at the widest layer of the corpus. The null mode also skips
// the core-range refusal below, because with no bucket to subscript there is
// nothing to guard, and `--l2-oracle` against a log written by a WIDER run is a
// combination that worked before the L1 oracles existed and must keep working:
// every committed L2 result was produced with that flag.

inline void read_oracle_lines(const std::string& path,
                              std::int32_t n_cores,
                              std::vector<std::vector<std::int64_t>>* l1_by_core,
                              std::vector<std::int64_t>& l2_lines) {
    if (l1_by_core) {
        l1_by_core->assign(static_cast<std::size_t>(n_cores), std::vector<std::int64_t>{});
    }
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("cannot read " + path);
    std::uint64_t magic = 0;
    in.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    if (!in || magic != AccessLog::kMagic) {
        throw std::runtime_error(path + " is not an access log (magic mismatch)");
    }
    constexpr std::size_t kBatch = 1 << 16;
    std::vector<AccessRecord> buf(kBatch);
    for (;;) {
        in.read(reinterpret_cast<char*>(buf.data()),
                static_cast<std::streamsize>(kBatch * sizeof(AccessRecord)));
        const std::size_t got = static_cast<std::size_t>(in.gcount()) / sizeof(AccessRecord);
        for (std::size_t i = 0; i < got; ++i) {
            if (buf[i].demand != 1) continue;
            if (buf[i].level == 1) {
                l2_lines.push_back(buf[i].line);
                continue;
            }
            if (!l1_by_core) continue;  // an L2-only caller; see the note above
            // Refused rather than indexed out of bounds, in the same style as
            // AccessLog's own two field checks: a log written by a run over a
            // WIDER machine decodes here as a perfectly plausible different run,
            // and the only symptom would be a Belady number nobody can explain.
            if (buf[i].core >= n_cores) {
                throw std::runtime_error(path + " has a record from core " +
                                         std::to_string(static_cast<int>(buf[i].core)) +
                                         " but this stream reports only " +
                                         std::to_string(n_cores) +
                                         " cores; the log is from another run");
            }
            (*l1_by_core)[static_cast<std::size_t>(buf[i].core)].push_back(buf[i].line);
        }
        if (got < kBatch) break;
    }
}

// One oracle per core for the private L1s, one shared for the L2.
//
// A `std::vector<NextUseOracle>` and not a vector of pointers, but the vector is
// RESERVED and filled COMPLETELY before anything attaches to it. `CacheLevel`
// holds a raw non-owning `NextUseOracle*`, so a push_back that reallocated
// would leave every already-attached pointer dangling: the hazard is the
// attached pointer, not the copy. That is the same hazard src/core/engine.cpp:48-50
// solves for the per-core `CacheLevel` vector, and it is solved the same way
// here, twice over, because a reserve alone is one careless later edit away
// from being wrong.
struct OracleSet {
    std::vector<NextUseOracle>   l1;
    std::optional<NextUseOracle> l2;
    // Whether `attach_oracles` handed any of the above to a level. False under
    // `--oracle` with no belady level, which is a legitimate arm of the 0907
    // grid, and it is what keeps report_overruns from warning about occurrence
    // indices nothing is reading.
    bool attached = false;
};

inline OracleSet build_oracles(const std::string& path, std::int32_t n_cores) {
    std::vector<std::vector<std::int64_t>> l1_by_core;
    std::vector<std::int64_t>              l2_lines;
    read_oracle_lines(path, n_cores, &l1_by_core, l2_lines);

    OracleSet oracles;
    oracles.l1.reserve(static_cast<std::size_t>(n_cores));
    for (std::int32_t c = 0; c < n_cores; ++c) {
        const std::size_t i = static_cast<std::size_t>(c);
        oracles.l1.emplace_back(l1_by_core[i]);
        // Freed as soon as its oracle exists, rather than at the end of the
        // function. At the widest layer of the corpus the line vectors are a
        // 162 MB transient against 292 MB of oracles, and holding both peaks
        // needlessly with 16 sweep workers on one machine.
        l1_by_core[i] = std::vector<std::int64_t>{};
    }
    oracles.l2.emplace(l2_lines);
    return oracles;
}

// Attached ONLY at the levels whose policy is actually Belady. An oracle on an
// LRU level is a no-op for the RESULT (cache_level.h, check B4) but not for the
// clock: it costs an unordered_map lookup and insert per demand access. Keeping
// the attach to the belady levels leaves every other arm of a grid identical to
// a run with no --oracle at all by construction rather than by argument.
//
// Validation owns the Belady-with-a-prefetcher warning because it reads only
// RunConfig fields, and both apps already print every Warning with its code.
// Keeping one warning channel preserves one format for the message.
inline void attach_oracles(OracleSet& oracles, const RunConfig& cfg, Engine& engine) {
    if (cfg.policy == PolicyKind::BELADY) {
        // `std::int32_t` and not `std::size_t`, so `CoreId{c}` needs no cast:
        // narrowing to int32 would be a real truncation, while widening a
        // non-negative int32 at the subscript is not.
        for (std::int32_t c = 0; c < static_cast<std::int32_t>(oracles.l1.size()); ++c) {
            engine.l1(CoreId{c}).attach_next_use(&oracles.l1[static_cast<std::size_t>(c)]);
        }
        oracles.attached = true;
    }
    if (cfg.l2_policy == PolicyKind::BELADY) {
        engine.l2().attach_next_use(&*oracles.l2);
        oracles.attached = true;
    }
}

// One line for all the L1 oracles together and one for the L2. Per-core lines
// would be 16 here and 256 at the design ceiling, times every job of a sweep,
// which buries the two lines a driver actually reads: this one and the overrun
// counts. Neither app has a verbosity flag to put the detail behind, and a flag
// invented for it would be a knob nothing asked for.
inline void report_oracles(const char* who, const std::string& path,
                           const OracleSet& oracles) {
    std::int64_t l1_refs  = 0;
    std::int64_t l1_lines = 0;
    for (const NextUseOracle& o : oracles.l1) {
        l1_refs += o.references();
        l1_lines += o.distinct_lines();
    }
    std::cerr << who << ": l1 oracles, " << oracles.l1.size() << " cores, " << l1_refs
              << " references over " << l1_lines << " lines summed over cores\n";
    std::cerr << who << ": l2 oracle " << path << ", " << oracles.l2->references()
              << " references over " << oracles.l2->distinct_lines() << " lines\n";
}

// The only in-band signal that the oracle and the run disagree, so it is
// printed rather than left for someone to ask for.
//
// An L1 overrun should not happen WHILE NOTHING BLOCKS: each core's L1 demand
// stream is then a pure function of the trace, the core and the mapper, so pass
// 2 asks for exactly what pass 1 logged. An L2 overrun CAN happen under
// `policy = belady`, because a Belady L1 changes which references miss, so pass
// 2's L2 stream is a genuinely different sequence rather than a reordering of
// pass 1's. That is what makes the L1 oracle exact under the precondition below
// and the L2 one approximate whether or not it holds.
//
// `max_wait_depth` IS that precondition, and it is checked here because an
// overrun does not catch its failure. A blocked request is re-triaged by
// Engine::reinject with `demand` still set, so one reference advances
// `l1_accesses` and the level's occurrence counter a second time; every later
// occurrence index is then off by one and the oracle answers for the WRONG
// future while every index it is asked for stays in range. A Belady L1 changes
// hits, which changes blocking, so the run that shifts the indices is the run
// that needs them. Warned and not thrown: a rerun of a committed configuration
// has to complete, and the driver is what decides whether to keep the number.
//
// It also returns early when no oracle was built, so neither caller repeats
// that test.
inline void report_overruns(const char* who, const OracleSet& oracles,
                            std::int64_t max_wait_depth) {
    if (!oracles.l2) return;
    std::int64_t l1_overruns = 0;
    for (const NextUseOracle& o : oracles.l1) l1_overruns += o.overruns();
    std::cerr << who << ": oracle overruns, l1 " << l1_overruns << ", l2 "
              << oracles.l2->overruns() << "\n";
    if (oracles.attached && max_wait_depth != 0) {
        std::cerr << who << ": WARNING: max_wait_depth " << max_wait_depth
                  << " with a belady level attached; a refused request re-probes and is "
                     "counted twice, so the oracle's occurrence indices have shifted and "
                     "it is answering for the wrong reference. The overrun counts do NOT "
                     "detect this, so treat this run's belady numbers as unsound.\n";
    }
}

}  // namespace app
}  // namespace cachesim
