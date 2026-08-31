// Exact LRU stack distance, and the histogram it accumulates into.
//
// Plan unit U1 of log/2026-08-31-reuse-distance-plan.md.
//
// This header has NO dependency on the engine and includes nothing from
// wcache/. That is the point of siting it here rather than in
// include/wcache/: the algorithm is a property of an access SEQUENCE, so it can
// be built and proved against a naive oracle before any engine feeds it. The
// engine's side of the work is a separate unit (U2) and is a dumper only.
//
// THE QUANTITY. For a reference to line X at time t whose previous reference was
// at p, the stack distance is the number of DISTINCT lines referenced in the
// open interval (p, t). A first reference has no previous reference to measure
// from and is COLD, reported as -1 rather than as any finite distance.
//
// Its value: a reference hits in a fully-associative LRU cache of N lines
// exactly when its distance is < N, and a cold reference never hits. So one
// pass over the sequence gives the hit rate at every capacity at once.
//
// THE ALGORITHM (Bennett and Kruskal). Picture one square per reference in time
// order, and put a marker on a square when that reference is the MOST RECENT
// one to its line. The invariant is then: the live markers are exactly one per
// distinct line seen so far, each sitting at that line's latest access. So
// counting markers in (p, t) counts distinct lines, which is the definition.
//
// Counting them by walking the squares costs O(gap), and on a cyclic sweep the
// gap is the whole working set: roughly 2,300 squares per reference at V8, or
// 126 billion steps over the corpus. A Fenwick tree over the timestamp axis
// makes the same count O(log n), about 19 slot touches, which is what brings it
// down to seconds.
//
// The naive back-scan survives as the TEST ORACLE in test_reuse_distance.cpp,
// never as a production path.
#pragma once

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <vector>

namespace reuse {

// One stack. Sixteen of these serve the sixteen private L1s; one more serves the
// shared L2. Each carries its OWN timestamp axis, because a core's squares are
// laid down only by that core's own references and a shared axis would leave
// gaps that no marker can ever occupy.
class StackDistance {
public:
    // Returns -1 for a first reference, else the number of distinct lines
    // referenced since the previous reference to `line`.
    std::int64_t observe(std::int64_t line) {
        const std::int64_t t = ++n_;
        ensure(t);

        std::int64_t d = -1;
        const auto it  = last_.find(line);
        if (it != last_.end()) {
            const std::int64_t p = it->second;
            // Markers strictly inside (p, t). Both prefixes are read BEFORE the
            // marker for t is placed and BEFORE the one at p is lifted, so the
            // window holds exactly the other lines' latest accesses.
            d = prefix(t - 1) - prefix(p);
            // p is no longer the most recent reference to this line.
            add(p, -1);
            it->second = t;
        } else {
            last_.emplace(line, t);
        }
        add(t, +1);
        return d;
    }

    std::int64_t references() const { return n_; }

    // How many times the tree has been rebuilt. Exposed because the growth
    // POLICY is load-bearing and is otherwise unfalsifiable: growing by one
    // square at a time leaves every answer correct and turns the run into
    // O(n^2), which at 55M references is not a slow test but an unusable class.
    // A rebuild count is a structural check on that, where a wall-clock
    // assertion would only be flaky.
    std::int64_t rebuilds() const { return rebuilds_; }

    // Live markers, which by the invariant is the count of distinct lines seen.
    // Exposed for the self-check rather than for the measurement.
    std::int64_t distinct() const { return prefix(n_); }

private:
    // Fenwick slot i holds the sum of the squares in (i - lowbit(i), i]. That
    // one rule is the whole structure: there are no nodes and no pointers, and
    // "tree" describes only how the slot sizes nest.
    static std::int64_t lowbit(std::int64_t i) { return i & -i; }

    // Growth is by doubling with a full O(n) rebuild, and NOT by appending to
    // the tree in place. A slot's coverage depends only on its index, so slots
    // that already exist stay correct, but a slot that comes into existence at
    // an index above the old bound covers squares BELOW it and would be born
    // holding zero where it owes a sum. Rebuilding cannot get that wrong, and
    // it happens about log2(n) times over a whole run, which is nothing.
    void ensure(std::int64_t t) {
        if (t < static_cast<std::int64_t>(slots_.size())) return;
        std::int64_t cap = slots_.empty() ? 2 : static_cast<std::int64_t>(slots_.size());
        while (t >= cap) cap *= 2;
        ++rebuilds_;
        cells_.resize(static_cast<std::size_t>(cap), 0);
        slots_.assign(static_cast<std::size_t>(cap), 0);
        for (std::int64_t i = 1; i < cap; ++i) {
            slots_[static_cast<std::size_t>(i)] += cells_[static_cast<std::size_t>(i)];
            const std::int64_t j = i + lowbit(i);
            if (j < cap) slots_[static_cast<std::size_t>(j)] += slots_[static_cast<std::size_t>(i)];
        }
    }

    // `cells_` is the honest strip of 0s and 1s and `slots_` is the subtotals
    // that encode it. Keeping both costs one extra int per square and is what
    // makes the rebuild above a transcription rather than a derivation.
    void add(std::int64_t i, std::int32_t v) {
        cells_[static_cast<std::size_t>(i)] += v;
        const std::int64_t cap = static_cast<std::int64_t>(slots_.size());
        for (std::int64_t j = i; j < cap; j += lowbit(j)) {
            slots_[static_cast<std::size_t>(j)] += v;
        }
    }

    std::int64_t prefix(std::int64_t i) const {
        std::int64_t r = 0;
        for (std::int64_t j = i; j > 0; j -= lowbit(j)) r += slots_[static_cast<std::size_t>(j)];
        return r;
    }

    std::vector<std::int32_t> cells_;
    std::vector<std::int32_t> slots_;
    std::unordered_map<std::int64_t, std::int64_t> last_;
    std::int64_t n_        = 0;
    std::int64_t rebuilds_ = 0;
};

// One stack plus the tally of what came out of it.
//
// The distribution is kept EXACT: one bucket per distance value, never binned
// here. A distance is bounded by the number of distinct lines, which is 36,864
// at the widest layer, so the vector stays small and binning stays a decision
// the analysis makes rather than one the instrument bakes in.
class ReuseHistogram {
public:
    void observe(std::int64_t line) {
        const std::int64_t d = stack_.observe(line);
        if (d < 0) {
            ++cold_;
            return;
        }
        const std::size_t k = static_cast<std::size_t>(d);
        if (k >= counts_.size()) counts_.resize(k + 1, 0);
        ++counts_[k];
    }

    std::int64_t cold() const { return cold_; }
    std::int64_t references() const { return stack_.references(); }
    const std::vector<std::int64_t>& counts() const { return counts_; }

    // Hit rate in a fully-associative LRU cache of `n_lines`: the fraction of
    // references whose distance is < n_lines. Cold references never hit, and
    // they stay in the denominator, which is what makes this comparable to a
    // measured `l1_hit_rate` rather than to a warm-cache idealisation.
    double hit_rate_at(std::int64_t n_lines) const {
        const std::int64_t total = references();
        if (total == 0) return 0.0;
        std::int64_t hits = 0;
        const std::size_t upto = counts_.size() < static_cast<std::size_t>(n_lines)
                                     ? counts_.size()
                                     : static_cast<std::size_t>(n_lines);
        for (std::size_t d = 0; d < upto; ++d) hits += counts_[d];
        return static_cast<double>(hits) / static_cast<double>(total);
    }

private:
    StackDistance stack_;
    std::vector<std::int64_t> counts_;  // counts_[d] = references at distance d
    std::int64_t cold_ = 0;
};

}  // namespace reuse
