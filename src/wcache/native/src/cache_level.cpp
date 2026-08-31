#include "wcache/cache_level.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

#include "wcache/set_associative.h"

namespace wcache {
namespace {

[[noreturn]] void caller_error(const char* verb, const std::string& what) {
    throw std::logic_error("CacheLevel::" + std::string(verb) + ": " + what);
}

// I5's first half, "a request is on at most one wait index", refused where the
// engine can actually break it.
//
// Here rather than inside `MshrFile::push_*_wait`, and the placement is the
// decision: `MshrFile` holds ONE file, a request can be refused at either of
// two, and its own unit tests legitimately construct a request on two indices to
// exercise the write-once stamp across levels -- a state a fixture may want and
// a run cannot reach. Triage is the only code that pushes during a run and the
// only code with a level in hand, so refusing here covers every reachable path
// without narrowing a contract plan unit B3 already shipped and tested.
//
// The failure it stops is not loud on its own: a request on two indices is woken
// by two different releases, and the second wake re-probes a request that was
// already satisfied and, at the L1, decrements a burst's line count twice.
void refuse_if_waiting(const char* where, const Request& r) {
    if (r.on_wait_index) {
        caller_error(where, "request for line " + std::to_string(r.line.get()) +
                                " is already on a wait index (I5)");
    }
}

// Part 8's stall attribution, in one place so the seven buckets cannot drift
// apart across the six branches below.
//
// A refusal always overwrites, so the cause is the reason the request was LAST
// blocked. A forward, a merge or a hit speaks only for a request nothing has
// refused yet, which is what `refusal == NoRefusal` says: it is written once, at
// the first refusal, and never cleared. So an unrefused request ends up
// attributed to the deepest level it reached, and a refused one to its own last
// refusal, which is the rule Part 8 states.
void charge_path(Request& r, StallCause c) {
    if (r.refusal == NoRefusal) r.cause = c;
}

}  // namespace

CacheLevel::CacheLevel(Level level,
                       const AddressMapper& mapper,
                       const LevelParams& params,
                       RefusalCounter& counter)
    : level_(level),
      mapper_(mapper),
      array_(nullptr),
      policy_(nullptr),
      mshrs_(params.mshrs, params.tgts_per_mshr, params.demand_reserve, counter),
      num_sets_(0),
      bank_high_bits_(params.bank_high_bits),
      sets_per_bank_(1) {
    // Built as the concrete type first so `num_sets()` can be read off it, then
    // moved behind the abstract handle. Recomputing the set count from the
    // config here instead would be the same division written twice, in two
    // places that can disagree about a geometry the array has already refused or
    // accepted -- and decision B63 split that division precisely so the product
    // `line_size_bytes * associativity` is never formed.
    auto array      = std::make_unique<SetAssociativeArray>(mapper, params.cache_size_bytes,
                                                            params.associativity);
    num_sets_       = array->num_sets();
    const std::int32_t slots = array->num_slots();
    array_          = std::move(array);

    // After the array, so a policy is never sized from a geometry the array
    // refused. `make_policy` is what rejects Random (Q5, V29, decision B95).
    policy_ = make_policy(params.policy, slots);

    if (params.banks < 1) {
        throw std::invalid_argument("CacheLevel: banks must be >= 1, got " +
                                    std::to_string(params.banks));
    }
    ports_.reserve(static_cast<std::size_t>(params.banks));
    for (std::int32_t b = 0; b < params.banks; ++b) ports_.emplace_back(params.ii, params.latency);

    // Integer division, so a set count smaller than the bank count gives 0 and
    // would divide by zero in `bank_of`. Clamped rather than refused, because
    // which end of the set index the bank comes from is a knob (Q2) and a
    // configuration with more banks than sets is D1's to reject, not a reason
    // for the arithmetic here to be unsafe. At the clamp every set lands in bank
    // 0, which is the honest answer: there is no high half to select on.
    const std::int64_t per_bank = num_sets_ / params.banks;
    sets_per_bank_              = per_bank > 0 ? per_bank : 1;
}

std::int32_t CacheLevel::bank_of(LineId line) const {
    const std::int32_t banks = static_cast<std::int32_t>(ports_.size());
    if (banks == 1) return 0;  // the L1, and the L2 at its 2.5b default
    const std::int64_t set = mapper_.locate(line, num_sets_).set_index.get();
    const std::int64_t b   = bank_high_bits_ ? set / sets_per_bank_ : set % banks;
    return static_cast<std::int32_t>(b < banks ? b : banks - 1);
}

// 3.4, branch for branch and in 3.4's order. The order is the whole of Part 0's
// surviving verdict: "the probe order, array -> own-level MSHR -> next level.
// Exactly gem5's order and exactly the hardware's. Checking the MSHR file
// BEFORE forwarding is what makes a secondary miss cost zero downstream
// traffic."
TriageOutcome CacheLevel::triage(Request& r, std::vector<Request*>& granted) {
    granted.clear();

    // 4.6's four differences apply to a prefetch AT ISSUE, which is the L1. By
    // I6 a request at the L2 holds an L1 entry, so this is false there and the
    // four drop branches below are unreachable at the L2: "identical below this
    // point" (4.6's own last table row). See `is_prefetch_at_issue` in mshr.h
    // for why dropping at the L2 is not an option the plan leaves open.
    const bool at_issue = is_prefetch_at_issue(r);

    // Belady's occurrence, consumed BEFORE the array is probed and therefore on
    // every demand reference, whether it goes on to hit or to miss.
    //
    // Advancing it inside the hit branch instead was a real bug, caught by check
    // B1: at 16-way the L2 hit rate is 0.00%, so the counter never moved, every
    // fill looked up occurrence 0 for the rest of the run, and Belady came out
    // WORSE than LRU, which is impossible for an optimal policy. It hid at fully
    // associative, where the cache is large enough that the eviction choice
    // barely matters. The guard is `r.demand` and the site is before the probe,
    // which is exactly what engine.cpp's `l2_accesses` counts, so the counter
    // and the access log advance together by construction.
    if (next_use_ != nullptr && r.demand) {
        std::int64_t& occ = occurrence_[r.line.get()];
        // Held for the fill that may follow this probe. The fill happens later,
        // so it cannot recompute the occurrence: other cores' probes for the
        // same line may have advanced it in between.
        pending_next_use_[r.line.get()] = next_use_->next_use(r.line, occ);
        ++occ;
    }

    // --- the array ---------------------------------------------------------
    const SlotId slot = array_->probe(r.line);
    if (slot != NoSlot) {
        // A prefetch is not a use. It drops WITHOUT calling `on_hit`, which is
        // the one thing that would let the prefetcher rewrite LRU order (4.6,
        // I15, decision B11). `probe` being const and not an access (2.2) is
        // what makes this expressible at all.
        if (at_issue) return TriageOutcome::DroppedArrayHit;
        if (next_use_ != nullptr && r.demand) {
            policy_->note_next_use(slot, pending_next_use_[r.line.get()]);
        }
        policy_->on_hit(slot);
        // The hit still cost this level's port: its `ii` to be accepted and its
        // latency to answer, both already paid by the reservation that scheduled
        // this probe. At the L1 that was the one wait with no bucket, which is
        // what made V21 an equality only at `l1_latency == 0`.
        charge_path(r, level_ == Level::L1 ? StallCause::L1Port : StallCause::L2Port);
        if (mshrs_.release_reservation(r)) mshrs_.collect_grants(granted);
        return TriageOutcome::Hit;
    }

    // --- a matching entry --------------------------------------------------
    if (Mshr* e = mshrs_.find(r.line)) {
        // The line is already coming, so nothing is waiting for this copy.
        // Dropped before the target-list bound is even consulted, which is why
        // `DroppedEntry` subsumes 4.6's "targets full" row.
        if (at_issue) return TriageOutcome::DroppedEntry;
        if (mshrs_.release_reservation(r)) mshrs_.collect_grants(granted);
        // A secondary miss: no downstream traffic, and it subscribes rather than
        // computing a completion time (D3). `add_target` also performs 4.6's
        // promotion, so a demand request merging onto a prefetch entry makes the
        // entry a demand entry.
        if (mshrs_.add_target(*e, r)) {
            // Waiting on a fetch that is already below this level, so the cause
            // is that fetch's own next step and not this level.
            charge_path(r, level_ == Level::L1 ? StallCause::L2Port : StallCause::Channel);
            return TriageOutcome::Merged;
        }
        // D5: the target list is full, so this waits on THIS entry, not on any
        // free entry. Waking it on an unrelated retire is the livelock 3.7
        // names. `push_line_wait` stamps the first refusal on the way in (3.8).
        refuse_if_waiting("triage", r);
        mshrs_.push_line_wait(*e, r);
        r.cause = level_ == Level::L1 ? StallCause::L1Line : StallCause::L2Line;
        return TriageOutcome::BlockedTargets;
    }

    // --- no match ----------------------------------------------------------
    if (!mshrs_.has_slot(r)) {
        if (at_issue) {
            // Which of the two refused it, at no cost beyond one comparison: a
            // completely full file, or the demand reserve a prefetch may never
            // take. Part 8 asks for the drops broken out by reason, and this is
            // the only place the two are still distinguishable.
            const std::int32_t free = mshrs_.capacity() - mshrs_.live() - mshrs_.reserved();
            return free > 0 ? TriageOutcome::DroppedReserve : TriageOutcome::DroppedNoSlot;
        }
        // D2: it registers and predicts nothing. There is no correct value for
        // "when will a slot free", so it does not compute one.
        refuse_if_waiting("triage", r);
        mshrs_.push_slot_wait(r);
        r.cause = level_ == Level::L1 ? StallCause::L1Slot : StallCause::L2Slot;
        return TriageOutcome::BlockedPool;
    }

    // --- primary miss ------------------------------------------------------
    Mshr& e = mshrs_.allocate(r.line, r);
    charge_path(r, level_ == Level::L1 ? StallCause::L2Port : StallCause::Channel);
    if (level_ == Level::L1) {
        // 3.5's re-entry rule, written where the request takes the entry: from
        // here on it re-enters at the L2, because a re-triage at the L1 would
        // find its OWN entry, merge the request into itself, and leave it
        // waiting for a fill nobody will request. I6 pairs the two fields, so
        // they are set together and nowhere else.
        r.mshr1 = &e;
        r.level = Level::L2;
    }
    return TriageOutcome::Forwarded;
}

InsertResult CacheLevel::install(LineId line) {
    // I1 makes this impossible: an entry exists for `line` only because a probe
    // missed, and there is at most one live entry per line per level, so no
    // second fill of the same line can be in flight. Checked because a duplicate
    // line in one set is the failure this model can least afford: every later
    // probe finds one of the two copies, nothing crashes, and the hit rate is
    // quietly wrong for the rest of the run.
    if (array_->probe(line) != NoSlot) {
        caller_error("install", "line " + std::to_string(line.get()) + " is already resident (I1)");
    }

    // Free way first, only then the policy (D6). Folding the free case into the
    // candidate list would oblige every policy to re-implement "prefer an empty
    // way", and a policy that got it wrong would evict a live line while a way
    // sat empty (cache.h).
    SlotId slot = array_->free_slot(line);
    if (slot == NoSlot) {
        array_->victim_candidates(line, candidates_);
        slot = policy_->pick_victim(candidates_);
    }

    const InsertResult res = array_->insert(line, slot);
    // The probe that missed already consumed this line's occurrence and left the
    // answer behind, so the fill reads it rather than recomputing.
    if (next_use_ != nullptr) {
        const auto it = pending_next_use_.find(line.get());
        policy_->note_next_use(
            slot, it == pending_next_use_.end() ? NextUseOracle::kNever : it->second);
    }
    policy_->on_fill(slot);

    // 3.4 line 619 calls `policy.on_evict(slot)` here, after `on_fill(slot)` and
    // on the same slot. NOT called: U17. Part 2.2's authoritative interface
    // lists four verbs and does not include it, and for any stamp policy that
    // order clobbers the stamp the fill just wrote, so the freshly filled slot
    // would look like the oldest line in its set. A5 built 2.2's four (decision
    // B97); the ruling belongs to the human.
    //
    // What the caller does with `res` is the other half of the plan's `install`:
    // the back-invalidation loop under `inclusion == inclusive` needs every L1,
    // which is the engine's view and not a level's (4.4, N8, unit C4).
    return res;
}

}  // namespace wcache
