#include "cachesim/replacement/pf_lru.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace {

// splitmix64's output mixer (Steele, Lea, Flood, "Fast splittable
// pseudorandom number generators", OOPSLA 2014; the reference java.util
// constants). A stateless bijection on 64 bits built from fixed-width
// unsigned arithmetic with pinned constants, so it computes the same value
// on every platform and every run.
std::uint64_t splitmix64(std::uint64_t x) {
    x += 0x9E3779B97F4A7C15ull;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ull;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBull;
    return x ^ (x >> 31);
}

// Arbitrary and pinned: the one seed every pf_lru_rand run uses, so results
// are reproducible by construction rather than by a recorded seed.
constexpr std::uint64_t kRandFallbackSeed = 0xA0761D6478BD642Full;

}  // namespace

PfLruPolicy::PfLruPolicy(std::int32_t num_slots, Fallback fallback)
    : StampPolicy(num_slots), fallback_(fallback) {
    // StampPolicy has already refused num_slots < 1, so the cast is safe.
    protected_.assign(static_cast<std::size_t>(num_slots), 0);
}

std::size_t PfLruPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= protected_.size()) {
        throw std::out_of_range("PfLruPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(protected_.size()) + ")");
    }
    return static_cast<std::size_t>(s);
}

void PfLruPolicy::on_hit(SlotId slot) { stamp(slot); }

void PfLruPolicy::on_fill(SlotId slot) {
    // The new occupant starts normal: the bit describes the slot's CURRENT
    // line, and whatever an eviction displaced is gone.
    protected_[index_or_reject("on_fill", slot)] = 0;
    StampPolicy::on_fill(slot);
}

void PfLruPolicy::on_invalidate(SlotId slot) {
    protected_[index_or_reject("on_invalidate", slot)] = 0;
    StampPolicy::on_invalidate(slot);
}

void PfLruPolicy::note_protected(SlotId slot, bool is_protected) {
    protected_[index_or_reject("note_protected", slot)] = is_protected ? 1 : 0;
}

SlotId PfLruPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    // Minimum stamp among the unprotected candidates; a set whose candidates
    // are all protected falls back over the whole set, by plain LRU
    // (Fallback::Lru) or by a pseudo-random draw (Fallback::Rand). The stamp
    // rule, its tie-break and its order-independence are StampPolicy's,
    // applied to the subset, so permuting `candidates` permutes the subset
    // and changes nothing. An EMPTY candidate vector takes the Lru line in
    // both modes, so the refusal is StampPolicy's one message.
    std::vector<Candidate> normal;
    for (const Candidate& c : candidates) {
        if (protected_[index_or_reject("pick_victim", c.slot)] == 0) normal.push_back(c);
    }
    if (fallback_ == Fallback::Rand && normal.empty() && !candidates.empty()) {
        return rand_fallback_victim(candidates);
    }
    return StampPolicy::pick_victim(normal.empty() ? candidates : normal);
}

SlotId PfLruPolicy::rand_fallback_victim(const std::vector<Candidate>& candidates) {
    // victim = argmin over the candidates of splitmix64(line ^ seed ^ draw),
    // ties broken toward the smaller slot id.
    //
    // Why argmin-of-hash satisfies the pick_victim order-independence
    // contract: each candidate's key is a function of the candidate itself
    // (its line id) and of policy state (the fixed seed and the draw
    // counter), never of its position in the vector, and argmin under the
    // total order (key, slot) is a function of the candidate SET. Permuting
    // `candidates` permutes the keys with their owners and the minimum does
    // not move. The draw counter advances exactly once per fallback draw,
    // whatever the set size, so repeated forced evictions re-key the whole
    // set and the victims spread instead of pinning one slot.
    const std::uint64_t draw = rand_draws_++;
    SlotId        victim   = candidates.front().slot;
    std::uint64_t best_key = splitmix64(
        static_cast<std::uint64_t>(candidates.front().line.get()) ^ kRandFallbackSeed ^ draw);
    for (std::size_t i = 1; i < candidates.size(); ++i) {
        const Candidate&    c   = candidates[i];
        const std::uint64_t key = splitmix64(
            static_cast<std::uint64_t>(c.line.get()) ^ kRandFallbackSeed ^ draw);
        if (key < best_key || (key == best_key && c.slot < victim)) {
            best_key = key;
            victim   = c.slot;
        }
    }
    return victim;
}

}  // namespace cachesim
