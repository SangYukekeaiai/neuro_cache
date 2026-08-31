// NextUseOracle: when will this line next be referenced at this level.
//
// Plan unit W2 of log/2026-08-31-belady-l2-plan.md. It exists to feed
// BeladyPolicy, which needs the future and cannot derive it.
//
// WHAT IT IS BUILT FROM. An access log, the file `wcache_run --access-log`
// already writes. For every reference in that log the oracle records where the
// NEXT reference to the same line is, and INT64_MAX where there is none.
//
// KEYED BY (line, occurrence), NOT BY TIME. The engine asks "this is the k-th
// reference to line X, where is the k+1-th", and the oracle answers from a
// per-line list. That indirection is the whole reason this works across runs:
// swapping the L2's replacement policy changes when each core's misses arrive,
// so absolute positions shift, while each core's own reference SEQUENCE does
// not (see the plan's section 3, which rests on V4 plus non_inclusive). Keying
// by occurrence survives a reordered merge; keying by time would not.
//
// The merge order across cores is still policy-dependent, so an oracle built
// from an LRU run is not automatically exact for a Belady run. That is settled
// by iterating to a fixpoint and comparing the two access logs, which is the
// driver's job and check B3's. This class does not claim exactness; it reports
// what it was built from and lets the driver prove it.
//
// SIZE. One entry per reference at the level it serves. The L2 streams are
// 4,608 to 77,824 references, so this is tens of KB.
#pragma once

#include <climits>
#include <cstdint>
#include <istream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "wcache/types.h"

namespace wcache {

class NextUseOracle {
public:
    static constexpr std::int64_t kNever = INT64_MAX;

    // Builds from a level's reference sequence, in order. `lines[i]` is the
    // line referenced at position i.
    explicit NextUseOracle(const std::vector<std::int64_t>& lines) {
        // One backward pass: walking from the end, the last position seen for a
        // line IS its next use for the reference before it. Forward would need
        // a second pass to fill in the tails.
        std::unordered_map<std::int64_t, std::int64_t> seen;
        next_.assign(lines.size(), kNever);
        for (std::size_t i = lines.size(); i-- > 0;) {
            const auto it = seen.find(lines[i]);
            next_[i]      = (it == seen.end()) ? kNever : it->second;
            seen[lines[i]] = static_cast<std::int64_t>(i);
        }
        // Regroup by line, so a lookup is (line, occurrence) rather than
        // (line, absolute position). The per-line lists are in reference order
        // because the forward pass below visits positions in order.
        for (std::size_t i = 0; i < lines.size(); ++i) {
            by_line_[lines[i]].push_back(next_[i]);
        }
    }

    // The next-use position for the `occurrence`-th reference to `line`,
    // counting from zero.
    //
    // Returns kNever past the end of what the oracle knows, which is the safe
    // direction: a line the oracle has run out of history for is treated as
    // never referenced again, so Belady evicts it first. A run whose stream
    // outgrew the oracle degrades toward evicting the unknown rather than
    // silently retaining it, and `overruns()` counts every time that happened so
    // the driver can refuse a result built on too much of it.
    std::int64_t next_use(LineId line, std::int64_t occurrence) {
        const auto it = by_line_.find(line.get());
        if (it == by_line_.end() || occurrence < 0 ||
            occurrence >= static_cast<std::int64_t>(it->second.size())) {
            ++overruns_;
            return kNever;
        }
        return it->second[static_cast<std::size_t>(occurrence)];
    }

    std::int64_t references() const { return static_cast<std::int64_t>(next_.size()); }
    std::int64_t distinct_lines() const { return static_cast<std::int64_t>(by_line_.size()); }
    std::int64_t overruns() const { return overruns_; }

    // Belady's hit rate on the sequence this oracle was built from, for a
    // FULLY-ASSOCIATIVE cache of `n_lines`. It needs no engine, being the
    // definition of MIN applied to a sequence, and that independence is the
    // point: it gives check B2 a number computed a second way, so the engine's
    // Belady is compared against something rather than only against itself.
    double optimal_hit_rate(const std::vector<std::int64_t>& lines,
                            std::int64_t n_lines) const {
        if (lines.empty() || n_lines <= 0) return 0.0;
        // resident maps a line to its next-use position, which is all MIN needs.
        std::unordered_map<std::int64_t, std::int64_t> resident;
        std::int64_t hits = 0;
        for (std::size_t i = 0; i < lines.size(); ++i) {
            const std::int64_t line = lines[i];
            const auto         it   = resident.find(line);
            if (it != resident.end()) {
                ++hits;
                it->second = next_[i];
                continue;
            }
            if (static_cast<std::int64_t>(resident.size()) >= n_lines) {
                // Evict the furthest next use. A line already past its last
                // reference carries kNever and goes first.
                auto worst = resident.begin();
                for (auto j = resident.begin(); j != resident.end(); ++j) {
                    if (j->second > worst->second ||
                        (j->second == worst->second && j->first < worst->first)) {
                        worst = j;
                    }
                }
                resident.erase(worst);
            }
            resident.emplace(line, next_[i]);
        }
        return static_cast<double>(hits) / static_cast<double>(lines.size());
    }

private:
    std::vector<std::int64_t>                                    next_;
    std::unordered_map<std::int64_t, std::vector<std::int64_t>>  by_line_;
    std::int64_t                                                 overruns_ = 0;
};

}  // namespace wcache
