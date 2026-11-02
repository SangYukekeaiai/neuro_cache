#include "cachesim/replacement/pf_lru.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {

PfLruPolicy::PfLruPolicy(std::int32_t num_slots) : StampPolicy(num_slots) {
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
    // are all protected falls back to plain LRU over the whole set. The stamp
    // rule, its tie-break and its order-independence are StampPolicy's,
    // applied to the subset, so permuting `candidates` permutes the subset
    // and changes nothing.
    std::vector<Candidate> normal;
    for (const Candidate& c : candidates) {
        if (protected_[index_or_reject("pick_victim", c.slot)] == 0) normal.push_back(c);
    }
    return StampPolicy::pick_victim(normal.empty() ? candidates : normal);
}

}  // namespace cachesim
