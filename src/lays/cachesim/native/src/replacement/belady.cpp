#include "cachesim/replacement/belady.h"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace {

constexpr std::int64_t kNever = INT64_MAX;

}  // namespace

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
    SlotId       victim = candidates.front().slot;
    std::int64_t best   = next_use_[index_or_reject("pick_victim", victim)];
    for (const Candidate& c : candidates) {
        const std::int64_t v = next_use_[index_or_reject("pick_victim", c.slot)];
        if (v > best || (v == best && c.slot.get() < victim.get())) {
            best   = v;
            victim = c.slot;
        }
    }
    return victim;
}

}  // namespace cachesim
