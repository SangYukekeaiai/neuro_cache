#include "wcache/stamp_policy.h"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace wcache {
namespace {

// One spelling of the prefix, so every message this file produces is findable
// by grepping for it and no two of them disagree about the punctuation.
// block_pack.cpp set the convention and set_associative.cpp follows it; the
// class name is a parameter here because three classes share the file.
[[noreturn]] void reject(const char* who, const std::string& what) {
    throw std::invalid_argument(std::string(who) + ": " + what);
}

// The stamp of a slot that has never been filled. Zero, and the counter starts
// at one, so "never stamped" is smaller than every stamp ever handed out and a
// never-filled slot is therefore the preferred victim. That is the right
// preference rather than an accident of the sentinel: such a slot holds no
// line, so evicting it costs nothing.
constexpr std::int64_t kNeverStamped = 0;

}  // namespace

StampPolicy::StampPolicy(std::int32_t num_slots) : next_stamp_(kNeverStamped + 1) {
    if (num_slots < 1) {
        reject("StampPolicy",
               "num_slots must be >= 1, got " + std::to_string(num_slots));
    }
    stamp_.assign(static_cast<std::size_t>(num_slots), kNeverStamped);
}

// std::out_of_range and not invalid_argument: layout.h's vocabulary gives
// out_of_range to an argument that is well formed but names something outside
// THIS layer, and a slot id belonging to a different array is exactly that. It
// is the same rule and the same tier SetAssociativeArray's insert applies to
// the same quantity.
//
// It is checked on every verb, including on_hit, which is the hottest call in
// the model. The check is one predictable compare against a member that is
// already in cache, and what it prevents is an out-of-bounds write into stamp_:
// a policy handed the slot ids of a differently sized array would otherwise
// corrupt memory silently rather than say so.
std::size_t StampPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= stamp_.size()) {
        throw std::out_of_range("StampPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(stamp_.size()) + ")");
    }
    return static_cast<std::size_t>(s);
}

void StampPolicy::stamp(SlotId slot) {
    stamp_[index_or_reject("stamp", slot)] = next_stamp_;
    ++next_stamp_;
}

void StampPolicy::on_fill(SlotId slot) { stamp(slot); }

// Back to "never stamped" rather than left alone, and this verb is therefore
// observable rather than a formality. The slot now holds nothing, so if it is
// ever offered as a candidate it should be taken first, which is exactly what
// the smallest possible stamp means. Leaving the previous occupant's stamp
// would make an invalidated slot compete on the age of a line that is gone.
void StampPolicy::on_invalidate(SlotId slot) {
    stamp_[index_or_reject("on_invalidate", slot)] = kNeverStamped;
}

SlotId StampPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) {
        reject("StampPolicy::pick_victim", "the candidate set is empty");
    }

    // Seeded from the first candidate rather than from a sentinel stamp, so
    // there is no "no victim yet" state to get wrong and the answer is always
    // one of the candidates by construction.
    SlotId       victim     = candidates[0].slot;
    std::int64_t oldest     = stamp_[index_or_reject("pick_victim", victim)];

    for (std::size_t i = 1; i < candidates.size(); ++i) {
        const SlotId       slot = candidates[i].slot;
        const std::int64_t age  = stamp_[index_or_reject("pick_victim", slot)];
        // Strictly smaller stamp wins; an equal stamp is decided by the smaller
        // slot id. Comparing the slot ids rather than keeping the first one
        // seen is what makes the result independent of the order `candidates`
        // arrives in, which policy.h requires of every implementation.
        if (age < oldest || (age == oldest && slot < victim)) {
            oldest = age;
            victim = slot;
        }
    }
    return victim;
}

void LruPolicy::on_hit(SlotId slot) { stamp(slot); }

// Empty on purpose: FIFO orders by install time, and a hit is the event it is
// defined to ignore. The parameter is unnamed so the empty body does not need a
// cast-to-void to stay warning-clean.
void FifoPolicy::on_hit(SlotId) {}

// --- Belady's MIN ------------------------------------------------------------
//
// The sign flip. Everything below mirrors StampPolicy with `<` replaced by `>`
// and the counter replaced by what the engine supplies.

namespace {
constexpr std::int64_t kNever = INT64_MAX;
}

BeladyPolicy::BeladyPolicy(std::int32_t num_slots) {
    if (num_slots <= 0) {
        throw std::invalid_argument("BeladyPolicy: num_slots must be positive, got " +
                                    std::to_string(num_slots));
    }
    next_use_.assign(static_cast<std::size_t>(num_slots), kNever);
}

std::size_t BeladyPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int64_t i = slot.get();
    if (i < 0 || i >= static_cast<std::int64_t>(next_use_.size())) {
        throw std::out_of_range("BeladyPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(i) + " is outside the " +
                                std::to_string(next_use_.size()) + " this policy has");
    }
    return static_cast<std::size_t>(i);
}

// Both empty on purpose. MIN consults the future and nothing else, and the
// engine has already supplied it through note_next_use by the time either of
// these runs. The bound check is still made, so a bad slot id is refused here
// exactly as it would be by a policy that stored something.
void BeladyPolicy::on_hit(SlotId slot) { index_or_reject("on_hit", slot); }
void BeladyPolicy::on_fill(SlotId slot) { index_or_reject("on_fill", slot); }

void BeladyPolicy::on_invalidate(SlotId slot) {
    next_use_[index_or_reject("on_invalidate", slot)] = kNever;
}

void BeladyPolicy::note_next_use(SlotId slot, std::int64_t next_use) {
    next_use_[index_or_reject("note_next_use", slot)] = next_use;
}

SlotId BeladyPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) {
        throw std::invalid_argument("BeladyPolicy::pick_victim: no candidates");
    }
    SlotId       victim{candidates.front().slot};
    std::int64_t best = next_use_[index_or_reject("pick_victim", victim)];
    for (const Candidate& c : candidates) {
        const std::int64_t v = next_use_[index_or_reject("pick_victim", c.slot)];
        // Strictly greater keeps the FIRST maximum seen, and the tie-break below
        // then makes that independent of order. Both halves are needed: several
        // slots holding lines never referenced again all carry kNever.
        if (v > best || (v == best && c.slot.get() < victim.get())) {
            best   = v;
            victim = c.slot;
        }
    }
    return victim;
}

std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots) {
    switch (kind) {
        case PolicyKind::LRU:    return std::make_unique<LruPolicy>(num_slots);
        case PolicyKind::FIFO:   return std::make_unique<FifoPolicy>(num_slots);
        case PolicyKind::BELADY: return std::make_unique<BeladyPolicy>(num_slots);
        case PolicyKind::RANDOM:
            reject("make_policy",
                   "policy 'random' is a placeholder and is not implemented; use 'lru' or 'fifo'");
    }
    // Unreachable: the switch covers every enumerator, and each arm either
    // returns or throws. Reported rather than papered over with a fallback to
    // LRU, which is the one wrong answer here: a config naming a policy this
    // build does not have would then run to completion under a policy nobody
    // selected, and the results row would attribute a hit rate to the wrong
    // one. types.h's Axis accessors refuse the same way for the same reason.
    throw std::logic_error("make_policy: unknown PolicyKind");
}

}  // namespace wcache
