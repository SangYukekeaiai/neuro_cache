// Fixtures shared by the Phase C suites: a trace, a mapper, an event log, and
// an in-run invariant probe.
//
// NAMING: the PLAN's Phase C units are C1 (CacheLevel), C2 (the handlers), C3
// (the core state machine and barrier), C4 (inclusion) and C5 (prefetching);
// PROGRESS.md's DECISIONS are numbered B1-B126. Every "C1".."C5" in the Phase C
// suites is the plan's UNIT unless a decision is named as one. Parts 2.1, 3.1
// and 4.1 of the plan use "C1" and "C2" for two of v3's own CHANGES (the core
// model of 4.5 and the prefetcher of 4.6), which is a third spelling of the
// same two names; where this file has to mean those it says "4.5" or "4.6".
//
// Three fixtures, and the reason each exists:
//
//   FakeTrace       stands in for unit A3, which is unbuilt. trace.h is the
//                   interface half of A3's row and this is a hand-written
//                   implementation of it, so a fixture drives the engine from a
//                   trace it wrote rather than from a corpus file.
//   LinearMapper    one line per COUT coordinate, so a burst's lines are the
//                   ids the fixture names and a test can reason about residency
//                   without going through BlockPackMapper's four radices.
//   Recorder        the observation surface. The engine has no logging hook and
//                   this review does not add one to production code, so the
//                   fixtures observe from where the engine already calls out:
//                   SetAssociativeArray::probe / free_slot / victim_candidates
//                   / insert all reach `mapper.locate` (src/set_associative.cpp
//                   base_slot), and E_Issue and the prefetcher both reach
//                   `mapper.expand`. A recorder on the mapper therefore sees an
//                   ORDERED log of every array operation the run performs, and
//                   sees it while the run is in progress, which is what lets the
//                   invariant soak check after every step rather than at the end.
#pragma once

#include <wcache/cache_level.h>
#include <wcache/engine.h>
#include <wcache/layout.h>
#include <wcache/prefetcher.h>
#include <wcache/trace.h>
#include <wcache/types.h>

#include <algorithm>
#include <optional>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace fx {

using namespace wcache;

// ===========================================================================
// The observation surface
// ===========================================================================

// What the mapper reports as it is used. Two calls, because two of the engine's
// own steps reach the mapper: an array operation (`locate`) and a burst
// expansion (`expand`).
class Recorder {
public:
    virtual ~Recorder() = default;
    virtual void on_locate(std::int64_t num_sets, std::int64_t line) = 0;
    virtual void on_expand(std::int64_t start, std::int32_t count)   = 0;
};

// ===========================================================================
// LinearMapper
// ===========================================================================

// Line id == the COUT coordinate, so `expand` of a burst anchored at `n` with
// count `c` and stride `s` is the ids n, n+s, ..., n+(c-1)s.
//
// It is a conforming AddressMapper and refuses what layout.h says it must: a
// count or stride below 1 is invalid_argument, a coordinate outside the layer
// is out_of_range, and every check runs before the first append.
class LinearMapper final : public AddressMapper {
public:
    // Not a layout under study: these fixtures exist to drive the level and the
    // array, and no test asks a fixture mapper for a neighbour.
    std::optional<LineId> neighbour(LineId, Axis, std::int32_t) const override {
        return std::nullopt;
    }

    explicit LinearMapper(std::int64_t n_lines) : n_lines_(n_lines) {}

    void set_recorder(Recorder* r) const { rec_ = r; }

    void expand(const Burst& b, std::vector<LineId>& out) const override {
        if (b.count < 1) {
            throw std::invalid_argument("LinearMapper: burst count must be >= 1, got " +
                                        std::to_string(b.count));
        }
        if (b.stride < 1) {
            throw std::invalid_argument("LinearMapper: burst stride must be >= 1, got " +
                                        std::to_string(b.stride));
        }
        const std::int64_t start = b.anchor.cout;
        const std::int64_t last  = start + static_cast<std::int64_t>(b.count - 1) * b.stride;
        if (start < 0 || last >= n_lines_) {
            throw std::out_of_range("LinearMapper: burst leaves the layer at " +
                                    std::to_string(last));
        }
        if (rec_ != nullptr) rec_->on_expand(start, b.count);
        for (std::int32_t i = 0; i < b.count; ++i) {
            out.push_back(LineId{start + static_cast<std::int64_t>(i) * b.stride});
        }
    }

    Placement locate(LineId line, std::int64_t num_sets) const override {
        if (line.get() < 0 || line.get() >= n_lines_) {
            throw std::out_of_range("LinearMapper: line " + std::to_string(line.get()) +
                                    " is outside [0, " + std::to_string(n_lines_) + ")");
        }
        if (rec_ != nullptr) rec_->on_locate(num_sets, line.get());
        return Placement{SetIndex{line.get() % num_sets}, TagId{line.get() / num_sets}};
    }

    LineId num_lines() const override { return LineId{n_lines_}; }
    std::int64_t line_size_bytes() const override { return 1; }

private:
    std::int64_t n_lines_;
    mutable Recorder* rec_ = nullptr;
};

// ===========================================================================
// FakeTrace: unit A3's query surface, hand written
// ===========================================================================

class FakeTrace final : public TileTrace {
public:
    struct CoreTile {
        std::vector<std::int64_t> ticks;  // local tick of each burst, in trace order
        std::vector<Burst> bursts;
    };
    struct Tile {
        std::vector<CoreTile> cores;
        std::int64_t tail = 1;  // trace.h: >= 1 by construction
    };

    explicit FakeTrace(std::int32_t n_cores) : n_cores_(n_cores) {}

    // --- construction --------------------------------------------------------

    std::int32_t add_tile(std::int64_t tail = 1) {
        Tile t;
        t.cores.assign(static_cast<std::size_t>(n_cores_), CoreTile{});
        t.tail = tail;
        tiles_.push_back(std::move(t));
        return static_cast<std::int32_t>(tiles_.size()) - 1;
    }

    // One burst of `count` consecutive lines starting at `first_line`.
    void add_burst(std::int32_t tile,
                   std::int32_t core,
                   std::int64_t tick,
                   std::int64_t first_line,
                   std::int32_t count = 1) {
        CoreTile& ct = tiles_.at(static_cast<std::size_t>(tile))
                           .cores.at(static_cast<std::size_t>(core));
        ct.ticks.push_back(tick);
        ct.bursts.push_back(Burst{Coord{0, 0, 0, static_cast<std::int32_t>(first_line)},
                                  Axis::COUT, count, 1});
    }

    // --- TileTrace -----------------------------------------------------------

    std::int32_t n_tiles() const override { return static_cast<std::int32_t>(tiles_.size()); }
    std::int32_t n_cores() const override { return n_cores_; }

    std::int32_t n_bursts(CoreId core, std::int32_t tile) const override {
        return static_cast<std::int32_t>(at(core, tile).bursts.size());
    }

    const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const override {
        return at(core, tile).bursts.at(static_cast<std::size_t>(k.get()));
    }

    LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const override {
        return LocalTick{at(core, tile).ticks.at(static_cast<std::size_t>(k.get()))};
    }

    LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const override {
        const CoreTile& ct = at(core, tile);
        const std::size_t i = static_cast<std::size_t>(k.get());
        return LocalTick{ct.ticks.at(i + 1) - ct.ticks.at(i)};
    }

    LocalTick tile_tail(std::int32_t tile) const override {
        return LocalTick{tiles_.at(static_cast<std::size_t>(tile)).tail};
    }

    // --- what an oracle needs, computed from the trace and nothing else -------

    // `max_tick[N]`, the largest local tick any core reaches in the tile.
    std::int64_t max_tick(std::int32_t tile) const {
        std::int64_t m = 0;
        for (const CoreTile& ct : tiles_.at(static_cast<std::size_t>(tile)).cores) {
            if (!ct.ticks.empty()) m = std::max(m, ct.ticks.back());
        }
        return m;
    }

    // `mac_cycles[N] = max_tick[N] + tile_tail[N]`, the tile's own length, which
    // is what `tick_base[N+1] - tick_base[N]` is on disk (4.5, Q10).
    std::int64_t mac_cycles(std::int32_t tile) const {
        return max_tick(tile) + tiles_.at(static_cast<std::size_t>(tile)).tail;
    }

    // `tick_base[N]`, the trace's own origin for tile N: the running sum of the
    // earlier tiles' lengths. The quantity V1 says `tile_origin[N]` must equal.
    std::int64_t tick_base(std::int32_t tile) const {
        std::int64_t t = 0;
        for (std::int32_t i = 0; i < tile; ++i) t += mac_cycles(i);
        return t;
    }

    // Whether any consecutive pair of bursts shares a local tick. V20's shift is
    // exact only when this is zero, and 4.5 asks for the count rather than the
    // assumption. The corpus half of that obligation is unit A3's.
    std::int64_t gap_zero_pairs() const {
        std::int64_t n = 0;
        for (const Tile& t : tiles_) {
            for (const CoreTile& ct : t.cores) {
                for (std::size_t i = 0; i + 1 < ct.ticks.size(); ++i) {
                    if (ct.ticks[i + 1] - ct.ticks[i] == 0) ++n;
                }
            }
        }
        return n;
    }

private:
    const CoreTile& at(CoreId core, std::int32_t tile) const {
        return tiles_.at(static_cast<std::size_t>(tile))
            .cores.at(static_cast<std::size_t>(core.get()));
    }

    std::int32_t n_cores_;
    std::vector<Tile> tiles_;
};

// ===========================================================================
// Config helpers
// ===========================================================================

// A level of `sets * assoc` lines at one byte per line, so `cache_size_bytes`
// IS the slot count and a fixture names its geometry directly.
inline LevelParams level(std::int64_t sets,
                         std::int32_t assoc,
                         std::int32_t mshrs,
                         std::int32_t tgts,
                         std::int32_t reserve = 0) {
    LevelParams p;
    p.cache_size_bytes = sets * assoc;
    p.associativity    = assoc;
    p.policy           = PolicyKind::LRU;
    p.latency          = SimTime{0};
    p.ii               = SimTime{1};
    p.banks            = 1;
    p.bank_high_bits   = false;
    p.mshrs            = mshrs;
    p.tgts_per_mshr    = tgts;
    p.demand_reserve   = reserve;
    return p;
}

// 2.5's `unbounded`: every port has `ii = 0` and every latency is 0, so no
// access costs anything and the timeline is the trace's own (V1, 4.5). It is
// N13's escape hatch and not a physical setting.
inline EngineParams unbounded_params(std::int64_t sets = 64, std::int32_t assoc = 4) {
    EngineParams p;
    p.l1                = level(sets, assoc, 16, 8);
    p.l1.ii             = SimTime{0};
    p.l2                = level(sets, assoc, 16, 8);
    p.l2.ii             = SimTime{0};
    p.l2_to_l1_latency  = SimTime{0};
    p.dram_ii           = SimTime{0};
    p.l2_miss_latency   = SimTime{0};
    p.core_accept_ii    = SimTime{1};
    p.inclusion         = Inclusion::NonInclusive;
    p.prefetch_policy   = PrefetchKind::None;
    p.prefetch_distance = 0;
    return p;
}

// ===========================================================================
// The event log
// ===========================================================================

// An ordered record of everything the engine asked the mapper, which is every
// array operation and every burst expansion, in the order they happened.
//
// This is the closest observable thing to 3.6's event log that exists without
// adding a hook to production code, and it is strictly finer than the event
// sequence in one way that matters: two events at one timestamp are
// distinguishable here by which array they touched and in what order, which is
// exactly what a flipped class or a reversed key changes.
class EventLog final : public Recorder {
public:
    void on_locate(std::int64_t num_sets, std::int64_t line) override {
        lines.push_back("L" + std::to_string(num_sets) + ":" + std::to_string(line));
    }
    void on_expand(std::int64_t start, std::int32_t count) override {
        lines.push_back("E" + std::to_string(start) + "x" + std::to_string(count));
    }
    std::string text() const {
        std::string s;
        for (const std::string& l : lines) {
            s += l;
            s += ' ';
        }
        return s;
    }
    std::vector<std::string> lines;
};

// ===========================================================================
// The invariant probe
// ===========================================================================

// Appendix A's invariants, checked WHILE the run is in progress.
//
// It runs on every `locate`, which is every array probe, free-slot query,
// victim scan and insert the run performs, so it samples far more often than
// once per event. It reads only const engine state and never probes an array,
// which would recurse back into here.
//
// What it can see bounds what it checks: `slot_wait_` exposes a depth and not
// its members, so I15's "never on a wait index" is checked exactly on the
// line-wait indices, which is where the reachable violation lives.
class InvariantProbe final : public Recorder {
public:
    InvariantProbe(std::int64_t n_lines, std::int32_t lines_per_burst)
        : n_lines_(n_lines), lines_per_burst_(lines_per_burst) {}

    void attach(Engine* e) {
        eng_ = e;
        last_cursor_.assign(static_cast<std::size_t>(e->stats().core_stall.size()), -1);
        last_tile_.assign(static_cast<std::size_t>(e->stats().core_stall.size()), -1);
    }

    void on_expand(std::int64_t, std::int32_t) override {}

    void on_locate(std::int64_t, std::int64_t) override {
        if (eng_ == nullptr) return;
        ++samples;
        const std::int32_t n = static_cast<std::int32_t>(last_cursor_.size());

        for (std::int32_t c = 0; c < n; ++c) {
            const CoreId cid{c};
            const CoreState& cs = eng_->core(cid);

            // I16: a core has exactly one burst in flight, and the phase and the
            // line count cannot disagree about it.
            if ((cs.pending_lines > 0) != (cs.phase == Phase::Stalled)) fail("I16 phase");
            if (cs.pending_lines < 0) fail("I16 negative pending_lines");

            // I13's observable half: within a tile the cursor only advances, and
            // it restarts at a tile.
            const std::size_t i = static_cast<std::size_t>(c);
            if (cs.tile == last_tile_[i] && cs.cursor.get() < last_cursor_[i]) {
                fail("I13 cursor moved backwards");
            }
            if (cs.tile < last_tile_[i]) fail("I13 tile moved backwards");
            last_tile_[i]   = cs.tile;
            last_cursor_[i] = cs.cursor.get();

            // I14's second half: the credit budget, and nothing downstream, is
            // what stops the prefetcher.
            MshrFile& f = eng_->l1(cid).mshrs();
            const std::int32_t budget = f.capacity() - f.demand_reserve();
            const std::int32_t fly    = eng_->stats().pf_outstanding.at(i);
            if (fly < 0 || fly > budget) fail("I14 pf_outstanding out of budget");
            max_pf_outstanding = std::max(max_pf_outstanding, fly);

            // I14's first half, on the concrete policy, because `none` has no
            // cursor and inventing one would make this pass where it has nothing
            // to say.
            if (const auto* nb = dynamic_cast<const NextBurstPrefetcher*>(&eng_->prefetcher())) {
                const std::int32_t d = nb->pf_cursor(cid).get() - cs.cursor.get();
                if (d < 0 || d > 1 + nb->distance()) fail("I14 pf_cursor - cursor");
                max_run_ahead = std::max(max_run_ahead, d);
                // 4.6: "the policy never crosses a tile boundary, since the next
                // tile's activations do not exist until the barrier resolves".
                // The cursor may reach one past the last burst and never beyond.
                if (nb->pf_cursor(cid).get() > eng_->n_bursts_in_tile(cid)) {
                    fail("4.6 pf_cursor crossed the tile boundary");
                }
            }

            check_file(f, /*at_l2=*/false);
        }
        check_file(eng_->l2().mshrs(), /*at_l2=*/true);
    }

    void fail(const std::string& what) {
        if (failures.size() < 20) failures.push_back(what);
    }

    std::vector<std::string> failures;
    std::int64_t samples            = 0;
    std::int32_t max_pf_outstanding = 0;
    std::int32_t max_run_ahead      = 0;
    std::int32_t max_line_wait      = 0;
    std::int32_t max_targets        = 0;
    std::int32_t max_live_l2        = 0;
    // I15, as literally written: "a request with demand == false is never on a
    // wait index". Counted at each level rather than failed, because whether the
    // built code is allowed to reach the L2 half is exactly the question the
    // implementer's P1 opened, and the answer is a finding rather than a check.
    std::int64_t l1_prefetch_waiters = 0;
    std::int64_t l2_prefetch_waiters = 0;

    // 4.6's promotion path (V25): an entry first seen as a prefetch entry and
    // later seen as a demand entry is the late-prefetch case, and the count
    // proves the fixture reached it rather than asserting it did.
    std::int64_t promotions = 0;

private:
    void check_file(MshrFile& f, bool at_l2) {
        // I4: entries plus reservations never exceed the capacity.
        if (f.live() + f.reserved() > f.capacity()) fail("I4 live+reserved > capacity");
        if (f.live() < 0 || f.reserved() < 0) fail("I4 negative count");
        if (at_l2) max_live_l2 = std::max(max_live_l2, f.live());

        const std::int32_t n_cores = static_cast<std::int32_t>(last_cursor_.size());
        for (std::int64_t l = 0; l < n_lines_; ++l) {
            Mshr* e = f.find(LineId{l});
            if (e == nullptr) continue;
            // I1 is structural: the file is keyed by line, so a second live
            // entry for one line is unrepresentable. What is checkable is that
            // the entry found under a key is the entry for that key.
            if (!(e->line == LineId{l})) fail("I1 entry keyed under the wrong line");

            // The promotion of an entry from prefetch to demand, watched rather
            // than asserted: `Mshr::demand` is mutable precisely so that a demand
            // request merging onto a prefetch entry can set it (4.6).
            const std::size_t key =
                static_cast<std::size_t>(l) + (at_l2 ? static_cast<std::size_t>(n_lines_) : 0);
            if (seen_prefetch_entry_.size() <= key) seen_prefetch_entry_.assign(
                static_cast<std::size_t>(2 * n_lines_), 0);
            if (!e->demand) {
                seen_prefetch_entry_[key] = 1;
            } else if (seen_prefetch_entry_[key] == 1) {
                seen_prefetch_entry_[key] = 2;
                ++promotions;
            }

            // I3: the target list is bounded.
            const std::int32_t t = static_cast<std::int32_t>(e->targets.size());
            if (t > f.tgts_per_mshr()) fail("I3 targets over the bound");
            max_targets = std::max(max_targets, t);

            const std::int32_t w = static_cast<std::int32_t>(e->line_wait.size());
            max_line_wait = std::max(max_line_wait, w);

            // I11: the per-entry line-wait bound, which is the credit argument
            // of 4.1 written as a number.
            if (at_l2) {
                if (w > n_cores - f.tgts_per_mshr() && w > 0) fail("I11 L2 line_wait bound");
                // I12: at `l2_tgts_per_mshr >= n_cores` the L2 line-wait sets are
                // provably always empty.
                if (f.tgts_per_mshr() >= n_cores && w != 0) fail("I12 L2 line_wait not empty");
            } else {
                if (w > lines_per_burst_ - f.tgts_per_mshr() && w > 0) {
                    fail("I11 L1 line_wait bound");
                }
            }

            for (const Request* r : e->targets) {
                // I6: holding an L1 entry and being at the L2 are one fact.
                if ((r->level == Level::L2) != (r->mshr1 != nullptr)) fail("I6 level/mshr1");
            }
            for (const Request* r : e->line_wait) {
                if ((r->level == Level::L2) != (r->mshr1 != nullptr)) fail("I6 level/mshr1");
                // I5: a waiter is recorded as waiting.
                if (!r->on_wait_index) fail("I5 waiter not marked");
                if (r->reserved) fail("I5 waiter also holds a reservation");
                // I2: a waiter carries a stamp, written at its first refusal.
                if (r->refusal == NoRefusal) fail("I2 unstamped waiter");
                // I15, as literally written: "a request with demand == false is
                // never on a wait index". Counted rather than failed, because
                // whether the built code is allowed to reach this is exactly the
                // question P1 opened.
                if (!r->demand) {
                    if (at_l2) {
                        ++l2_prefetch_waiters;
                    } else {
                        ++l1_prefetch_waiters;
                    }
                }
            }
        }
    }

    Engine* eng_ = nullptr;
    std::int64_t n_lines_;
    std::int32_t lines_per_burst_;
    std::vector<std::int32_t> last_cursor_;
    std::vector<std::int32_t> last_tile_;
    std::vector<std::uint8_t> seen_prefetch_entry_;
};

// ===========================================================================
// The independent timeline oracle (V1, V20, V22, V27)
// ===========================================================================

// `tile_origin` computed from the TRACE and the plan's recurrence alone, with
// no call into the engine.
//
// 4.5:
//     issue(c, 0)   = tile_origin[tile] + local_tick(c, 0)
//     issue(c, k+1) = served(c, k) + max(gap_k, core_accept_ii)
//     served(c, k)  = issue(c, k) + `cost`, which is 0 on the unbounded baseline
//     tile_origin[N+1] = max over cores of served(c, last) + tile_tail[N]
//
// `per_burst_cost` is the extra cycles every burst pays, which is 0 for V1 and
// 1 for V27's `l1_latency = 1` sensitivity run. That one parameter is the whole
// difference between the two, and N14 accumulating rather than absorbing is why
// it compounds into `tile_origin` instead of sitting in a corner.
inline std::vector<std::int64_t> oracle_tile_origin(const FakeTrace& tr,
                                                    std::int64_t core_accept_ii = 1,
                                                    std::int64_t per_burst_cost = 0) {
    std::vector<std::int64_t> origin(static_cast<std::size_t>(tr.n_tiles()) + 1, 0);
    for (std::int32_t t = 0; t < tr.n_tiles(); ++t) {
        std::int64_t last_service = origin[static_cast<std::size_t>(t)];
        for (std::int32_t c = 0; c < tr.n_cores(); ++c) {
            const CoreId cid{c};
            const std::int32_t n = tr.n_bursts(cid, t);
            if (n == 0) continue;
            std::int64_t served = origin[static_cast<std::size_t>(t)] +
                                  tr.local_tick(cid, t, BurstIndex{0}).get() + per_burst_cost;
            for (std::int32_t k = 1; k < n; ++k) {
                const std::int64_t g = tr.gap(cid, t, BurstIndex{k - 1}).get();
                served += std::max(g, core_accept_ii) + per_burst_cost;
            }
            last_service = std::max(last_service, served);
        }
        origin[static_cast<std::size_t>(t) + 1] = last_service + tr.tile_tail(t).get();
    }
    return origin;
}

}  // namespace fx
