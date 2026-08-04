#pragma once
// Two-level cache orchestration: one private L1 Cache per core plus one
// shared L2 Cache, driven one tick at a time out of the Stage 1 nested
// weight trace (tiles -> ticks -> cores -> weight_addresses). Implements
// the "Two-level hierarchy semantics" and "L2 cout-prefetch policy"
// sections of log/2026-08-03-l1-l2-cache-policy-plan.md.
//
// The cout prefetch and the same-tick pinning are switches, not fixed
// behavior: with both off this engine reproduces its own pre-prefetch,
// pre-pinning results exactly, which is what makes each of the two
// separately testable.
//
// cache.h's Cache is the single-cache building block, reused unchanged
// and instantiated once per core plus once shared. Nothing here
// reimplements replacement logic; this file only sequences accesses
// across those instances.
//
// Twin of dump/python_reference/cachesim/hierarchy.py -- same class and
// method names, same order of operations, same statistics. The two are
// meant to be read side by side and changed together.

#include <cstdint>
#include <map>
#include <stdexcept>
#include <vector>

#include "cache.h"
#include "config.h"
#include "layout.h"

namespace cachesim {

// One core's weight fetches at one tick, already expanded to packed
// cache-line tags in issue order (per-burst deduped, the same rule
// main.cpp's single-level replay uses).
struct CoreRequest {
    int64_t core_id;
    std::vector<int64_t> packed_tags;
};

struct CoreL1Stats {
    int64_t core_id;
    int64_t hits;
    int64_t accesses;
};

class TwoLevelHierarchy {
public:
    // l2_prefetch: insert the next cout block alongside every L2 demand
    // miss. same_tick_pinning: protect a line that was read as an L2 hit
    // this tick from this tick's own fills. Both are required arguments,
    // in this language and in the Python twin, so neither side owns a
    // default the other could drift from.
    TwoLevelHierarchy(const CacheConfig &l1_config, const CacheConfig &l2_config, bool l2_prefetch,
                      bool same_tick_pinning)
        : l1_config_(l1_config), l2_(l2_config), l2_prefetch_(l2_prefetch), same_tick_pinning_(same_tick_pinning),
          cout_lines_(hybrid_cout_lines(l2_config)) {}

    // One tick of lock-step execution. `cores` must be in ascending
    // core_id order: that is both the order the L2 lookups are recorded
    // in and the order this tick's fills are applied in, which the plan
    // fixes as core-ascending. The on-disk order within a tick is not
    // guaranteed to be sorted (tracegen.merge_cores_by_tick appends in
    // whatever order the per-core results were collected), so the caller
    // sorts and this checks.
    void run_tick(const std::vector<CoreRequest> &cores) {
        for (size_t i = 1; i < cores.size(); ++i) {
            if (cores[i - 1].core_id >= cores[i].core_id)
                throw std::runtime_error("cachesim: run_tick needs cores in ascending core_id order");
        }

        // -- Lookup phase ------------------------------------------------
        // Every L1 check and every resulting L2 lookup for this tick is
        // resolved here, against L2 exactly as it stood when the tick
        // began. Cores in one tick run in lock-step, so they are
        // concurrent, not sequential: none of them may observe another
        // core's same-tick fill. That is why the L2 question is asked
        // with contains(), a pure residency test, and not with access():
        // access() moves recency and inserts on a miss, so core k's miss
        // would turn into core k+1's hit inside the same tick.
        pending_fills_.clear();
        pins_.clear();
        for (const CoreRequest &req : cores) {
            CoreLevel1 &core = l1_for(req.core_id);
            for (int64_t tag : req.packed_tags) {
                ++core.accesses;
                if (core.cache.access(tag)) {
                    ++core.hits;
                    continue;
                }
                // That access() already inserted the line, which IS the
                // inclusive L1 fill: whether the line comes back from L2
                // or from off chip, the requesting core's L1 gets it.
                // Filling an L1 in place is safe where filling L2 in
                // place is not, because an L1 is private to one core.
                ++l2_accesses_;
                pending_fills_.push_back(tag);
                if (l2_.contains(tag)) {
                    ++l2_hits_;
                    // Pin it, carrying the stamp it has right now: L2 is
                    // still in its start-of-tick state, so this is the
                    // recency the overflow fallback is defined against.
                    // A repeated hit on one tag re-reads the same stamp,
                    // so which core wins the insert does not matter.
                    if (same_tick_pinning_) pins_.emplace(tag, l2_.stamp(tag));
                } else if (l2_prefetch_) {
                    // Prefetch on an L2 MISS only, one cout block ahead,
                    // no chaining. Queued as a fill rather than inserted
                    // here: an insert during the lookup phase would be
                    // visible to the same tick's later lookups and would
                    // break the tick-atomic snapshot the whole phase
                    // split exists to keep. It is also not counted as an
                    // access or a hit anywhere, so a prefetch can never
                    // move the reported L2 hit rate by itself.
                    int64_t target = prefetch_target(tag);
                    if (target >= 0) pending_fills_.push_back(target);
                }
            }
        }

        // -- Fill phase --------------------------------------------------
        // Only now do this tick's L2 updates land, producing the state the
        // NEXT tick's lookups see. pending_fills_ was built in
        // core-ascending order above, so replaying it in order is the
        // core-ascending application the plan specifies. Every kind of
        // fill replays as one access_pinned(): a lookup that hit becomes a
        // hit-touch, a lookup that missed becomes a demand insert, a
        // prefetch becomes an insert right behind the demand insert that
        // triggered it, and an L2 miss fills L2 as well as L1 (the
        // off-chip fetch itself is unmodeled). They all take the pin set,
        // including the prefetches: a prefetch is one of this tick's own
        // fills, so it may not throw out a line another core read this
        // tick either.
        //
        // With pins_ empty (pinning off, or a tick with no L2 hit) this
        // loop is byte for byte the plain-access() fill phase it replaces.
        // With pins_ non-empty, a line read as a hit is no longer evicted
        // and re-fetched inside its own tick, except in the overflow case
        // policy.h's choose_victim spells out.
        for (int64_t tag : pending_fills_) l2_.access_pinned(tag, pins_);
    }

    // Ascending by core_id, one entry per core seen at least once.
    std::vector<CoreL1Stats> per_core_l1() const {
        std::vector<CoreL1Stats> out;
        out.reserve(l1_.size());
        for (const auto &kv : l1_) out.push_back(CoreL1Stats{kv.first, kv.second.hits, kv.second.accesses});
        return out;
    }

    int64_t l1_hits() const {
        int64_t n = 0;
        for (const auto &kv : l1_) n += kv.second.hits;
        return n;
    }

    int64_t l1_accesses() const {
        int64_t n = 0;
        for (const auto &kv : l1_) n += kv.second.accesses;
        return n;
    }

    int64_t l2_hits() const { return l2_hits_; }
    int64_t l2_accesses() const { return l2_accesses_; }

private:
    struct CoreLevel1 {
        Cache cache;
        int64_t hits = 0;
        int64_t accesses = 0;
        explicit CoreLevel1(const CacheConfig &cfg) : cache(cfg) {}
    };

    // Cores are created the first time they appear. std::map both keeps
    // them in ascending core_id order for the per-core report and keeps
    // references stable as later cores are added.
    CoreLevel1 &l1_for(int64_t core_id) {
        auto it = l1_.find(core_id);
        if (it == l1_.end()) it = l1_.try_emplace(core_id, l1_config_).first;
        return it->second;
    }

    // The tag one cout block ahead of `tag`, or -1 when there is none.
    // cout is the packed tag's innermost component (layout.h's TagPacker
    // multiplies it by nothing), so the neighbouring cout block is simply
    // the next packed value, and the packing is what keeps this cheap:
    // no unpack/repack per L2 miss. The layer ends where tag's own cout
    // component is the last block of the layer's true COUT, and there the
    // prefetch is a no-op rather than a wrap into the next cin block.
    // Distance is one block, fixed by the plan, so it is written here
    // rather than made a knob; the Python twin says the same thing in
    // dump/python_reference/cachesim/hierarchy.py.
    int64_t prefetch_target(int64_t tag) const {
        return (tag % cout_lines_) + 1 < cout_lines_ ? tag + 1 : -1;
    }

    CacheConfig l1_config_;
    std::map<int64_t, CoreLevel1> l1_;
    Cache l2_;
    bool l2_prefetch_, same_tick_pinning_;
    int64_t cout_lines_;
    std::vector<int64_t> pending_fills_;
    PinStamps pins_;
    int64_t l2_hits_ = 0, l2_accesses_ = 0;
};

} // namespace cachesim
