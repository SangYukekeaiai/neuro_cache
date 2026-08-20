// CacheLevel: one level of the hierarchy, and the triage of 3.4.
//
// Plan v3 Part 7, unit C1: "`CacheLevel` = array + policy + port + MSHR file;
// `triage()` per level", whose exit criterion is "the 3.4 triage table exercised
// branch by branch".
//
// One class for both levels. Plan 3.4 says the two triage functions are of
// "identical shape", and they are: the only differences are what a HIT and a
// FORWARDED mean afterwards, and both of those are the ENGINE's business rather
// than the level's, because both end in scheduling an event (P4). So `triage`
// below classifies and mutates level-local state, and returns which of 3.7's
// outcomes happened; the engine reacts.
//
// What this class deliberately does NOT do, and the boundary is the reason the
// engine is testable at all: it never schedules an event, never touches another
// level, and never touches a core. Following 3.4 literally would have put
// `core_line_done` inside `triage_L1` and `schedule(E_L2Probe(r), ...)` at the
// bottom of it, which reaches across two boundaries from inside a level.
//
//     3.4's triage_L1                          here
//     ---------------------------------------  ------------------------------
//     probe, on_hit, release, core_line_done    -> returns Hit
//     find, release, targets.push               -> returns Merged
//     find, mark_refused, line_wait.push        -> returns BlockedTargets
//     mark_refused, slot_wait.push              -> returns BlockedPool
//     allocate, mshr1 = e, level = L2,          -> returns Forwarded, having set
//       consume_reservation, reserve, schedule     mshr1 and level; the port
//                                                  reservation is the engine's
//
// Every state change 3.4 makes is made here, in 3.4's order. What is left to the
// engine is exactly the two lines that cross a boundary.
#pragma once

#include <cstdint>
#include <memory>
#include <vector>

#include "wcache/cache.h"
#include "wcache/layout.h"
#include "wcache/mshr.h"
#include "wcache/policy.h"
#include "wcache/port.h"
#include "wcache/stamp_policy.h"
#include "wcache/types.h"

namespace wcache {

// 3.7's five outcomes, plus 4.6's drops.
//
// The five are "distinguished ONLY by what releases them" (3.7), and the two
// collapses the plan warns about are unrepresentable here rather than merely
// avoided: `Merged` and `BlockedTargets` are separate enumerators although both
// wait on the same entry, and `BlockedPool` and `BlockedTargets` are separate
// although both are "blocked".
//
// The four drops are 4.6's, and they are separate enumerators for the same
// reason: Part 8 asks for prefetch drops "broken out by reason", and a single
// `Dropped` would make that a statistic nobody can recover. Each names the step
// that refused, so the four partition the prefetch path exactly once:
//
//   DroppedArrayHit  the line is already resident. NOT counted as a hit and NOT
//                    reported to the policy: "a prefetch is not a use" (4.6,
//                    I15, decision B11)
//   DroppedEntry     the line is already coming, so nothing is waiting for this
//                    copy. This subsumes 4.6's "the entry's targets full" row,
//                    because a prefetch never reaches the target-list bound: it
//                    is dropped at the matching entry, one step earlier
//   DroppedNoSlot    the file is completely full
//   DroppedReserve   free entries remain but they are the demand reserve, which
//                    a prefetch may never take (4.6, decision B12)
enum class TriageOutcome : std::uint8_t {
    Hit             = 0,
    Merged          = 1,
    BlockedTargets  = 2,
    BlockedPool     = 3,
    Forwarded       = 4,
    DroppedArrayHit = 5,
    DroppedEntry    = 6,
    DroppedNoSlot   = 7,
    DroppedReserve  = 8,
};

// True for the four 4.6 drops, which is the test the engine's counters and its
// request-lifetime rule both dispatch on.
constexpr bool is_dropped(TriageOutcome o) {
    return o == TriageOutcome::DroppedArrayHit || o == TriageOutcome::DroppedEntry ||
           o == TriageOutcome::DroppedNoSlot || o == TriageOutcome::DroppedReserve;
}

// The config fields one level is built from (2.2, 2.3, 2.5b).
//
// A plain struct with no validation. D1 owns "config load + validation, single
// source of truth for the parameter set" (Part 7), so every rule of the D1 row
// -- `lines_per_burst > l1_mshrs` throws, `demand_reserve >= mshrs` throws,
// `policy = random` throws -- belongs there and not here. What the constructors
// reached from this struct still refuse are their own preconditions:
// `SetAssociativeArray` refuses a geometry that does not divide, `Port` refuses
// a negative `ii`, `MshrFile` refuses a `demand_reserve` above its capacity, and
// `make_policy` refuses Random. Those survive `-DNDEBUG` because they are
// throws, so a sweep grid point nobody typed by hand is refused rather than
// simulated.
struct LevelParams {
    std::int64_t cache_size_bytes = 0;
    std::int32_t associativity    = 1;
    PolicyKind   policy           = PolicyKind::LRU;

    // The port's two numbers (4.3). `ii = 0` is N13's escape hatch, which is how
    // the unbounded baseline of V1 is built; `latency = 0` is 2.5b's default for
    // `l1_latency`, which is what makes a 100% hit run reproduce the scratchpad
    // timeline exactly.
    SimTime latency{0};
    SimTime ii{1};

    // 1 at the L1, `l2_banks` at the L2, which defaults to 1 (2.3, 2.5b). Note
    // the trap 2.3 records: at `l2_banks = 1` the two settings of
    // `bank_high_bits` are indistinguishable by construction, so a fixture
    // asserting bank behaviour must set this to 2 or more or it passes
    // vacuously.
    std::int32_t banks = 1;

    // Q2, closed 2026-08-17: the bank index comes from the LOW bits of the set
    // index, kept as a knob because the bank-conflict statistic exists to tell
    // layouts apart and cannot do that if the banking is hardwired.
    bool bank_high_bits = false;

    std::int32_t mshrs          = 1;
    std::int32_t tgts_per_mshr  = 1;
    std::int32_t demand_reserve = 0;
};

class CacheLevel {
public:
    // Builds the level: a set-associative array, a policy sized from it, one
    // Port per bank, and an MshrFile.
    //
    // `mapper` and `counter` must outlive the level. One mapper serves the whole
    // hierarchy (layout.h) and one refusal counter serves the whole run
    // (mshr.h), so both already outlive every level by construction.
    //
    // Throws whatever the four constructors throw, in the order they run:
    // std::invalid_argument for a geometry that is not a whole number of lines,
    // for a negative `ii` or `latency`, for a `demand_reserve` above the
    // capacity, and for `policy = random`.
    CacheLevel(Level level,
               const AddressMapper& mapper,
               const LevelParams& params,
               RefusalCounter& counter);

    // 3.4's triage, called on FIRST arrival and again on EVERY wake (D4).
    //
    // Re-triage is the whole point and is not an optimisation: "anything that
    // waits re-triages from the top of its level when it wakes. It never acts on
    // the classification it held when it blocked." A request classified as a
    // miss can wake to find the line resident (V5) and a request classified as a
    // hit can wake to find its line evicted (V6). It carries its original
    // refusal stamp either way, which `mark_refused`'s write-once rule keeps
    // true without this function doing anything (3.8).
    //
    // `granted` is REPLACED, not appended to, and is non-empty only on the two
    // outcomes that release a reservation. 3.8: "a grantee that turns out not to
    // need its slot (it re-triaged into a hit or a merge) releases the
    // reservation, immediately granting the next waiter." The next waiter cannot
    // be injected from here, because injecting reserves a port (B120), so it is
    // handed back for the engine to reinject.
    //
    // Sets `r.mshr1` and `r.level` on a Forwarded at the L1, which is 3.5's
    // re-entry rule written at the one place that knows the request has just
    // taken an L1 entry.
    TriageOutcome triage(Request& r, std::vector<Request*>& granted);

    // 3.4's `install`: free way first, only then the policy (D6).
    //
    // Returns what was displaced, because the caller needs it: under
    // `inclusion = inclusive` an L2 eviction has to be back-invalidated out of
    // every L1 that holds the line (4.4, N8, C4), and that scan is the engine's
    // because only the engine sees the other level.
    //
    // The plan's `install` pseudocode calls `cache.policy.on_evict(slot)` here,
    // after `on_fill(slot)` and on the SAME slot. That call is NOT made, and the
    // reason is U17 rather than an oversight: Part 2.2's authoritative interface
    // lists four verbs and does not include `on_evict`, while 3.4 line 619 calls
    // a fifth. For any stamp policy the pseudocode's order clobbers the stamp
    // the fill just wrote, so the freshly filled slot would look like the oldest
    // line in its set. A5 built 2.2's four (decision B97) and this call site
    // stays with 2.2 until the human rules.
    //
    // Throws std::logic_error when `line` is already resident, which I1 makes
    // impossible: an entry exists for it only because a probe missed, and a
    // second entry for one line cannot exist. Checked rather than assumed
    // because a duplicate line in one set is the silent failure this model can
    // least afford -- every later probe finds one of the two copies, and the
    // symptom is a hit rate slightly wrong for the rest of the run.
    InsertResult install(LineId line);

    // Which bank port `line` uses. Always 0 at the L1, which has one port.
    //
    // Q2, closed: the low bits of the set index by default, the high bits under
    // `bank_high_bits`. The two are opposite conflict behaviours -- low bits
    // spread consecutive lines across banks, high bits keep a contiguous run
    // inside one -- and which is right interacts with the `cin_block` /
    // `cout_block` sweep, which is why it stayed a knob.
    std::int32_t bank_of(LineId line) const;

    Level level() const { return level_; }
    CacheArray& array() { return *array_; }
    const CacheArray& array() const { return *array_; }
    ReplacementPolicy& policy() { return *policy_; }
    MshrFile& mshrs() { return mshrs_; }
    const MshrFile& mshrs() const { return mshrs_; }
    Port& port(std::int32_t bank) { return ports_.at(static_cast<std::size_t>(bank)); }
    std::int32_t banks() const { return static_cast<std::int32_t>(ports_.size()); }
    std::int64_t num_sets() const { return num_sets_; }

private:
    Level level_;
    const AddressMapper& mapper_;
    std::unique_ptr<CacheArray> array_;
    std::unique_ptr<ReplacementPolicy> policy_;

    // One per bank. A vector rather than a single Port so that the L1 and the L2
    // are the same class: the L1 is the `banks = 1` case, exactly as a
    // direct-mapped array is `SetAssociativeArray` at associativity 1.
    std::vector<Port> ports_;

    MshrFile mshrs_;

    // Read by `bank_of` only, and derived from the array at construction rather
    // than recomputed, so the set count the banking uses is by construction the
    // one the array actually has.
    std::int64_t num_sets_;
    bool bank_high_bits_;

    // Sets per bank, for the high-bits banking. Precomputed so `bank_of` does
    // one division rather than two, and clamped to at least 1 so that a set
    // count smaller than the bank count divides rather than dividing by zero.
    std::int64_t sets_per_bank_;

    // Scratch for `install`'s candidate list, so a fill does not allocate. It is
    // per level rather than per engine because `victim_candidates` REPLACES its
    // out-parameter (cache.h), so two levels filling in the same dispatch cannot
    // interleave through it.
    std::vector<Candidate> candidates_;
};

}  // namespace wcache
