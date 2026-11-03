#include "cachesim/replacement/lfu.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace {

[[noreturn]] void reject(const char* who, const std::string& what) {
    throw std::invalid_argument(std::string(who) + ": " + what);
}

}  // namespace

LfuPolicy::LfuPolicy(std::int32_t num_slots) {
    if (num_slots < 1) {
        reject("LfuPolicy", "num_slots must be >= 1, got " + std::to_string(num_slots));
    }
    count_.assign(static_cast<std::size_t>(num_slots), 0);
}

std::size_t LfuPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= count_.size()) {
        throw std::out_of_range("LfuPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(count_.size()) + ")");
    }
    return static_cast<std::size_t>(s);
}

void LfuPolicy::on_hit(SlotId slot) { ++count_[index_or_reject("on_hit", slot)]; }

void LfuPolicy::on_fill(SlotId slot) { count_[index_or_reject("on_fill", slot)] = 0; }

void LfuPolicy::on_invalidate(SlotId slot) {
    count_[index_or_reject("on_invalidate", slot)] = 0;
}

SlotId LfuPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) reject("LfuPolicy::pick_victim", "the candidate set is empty");

    SlotId       victim = candidates.front().slot;
    std::int64_t fewest = count_[index_or_reject("pick_victim", victim)];
    for (std::size_t i = 1; i < candidates.size(); ++i) {
        const SlotId       slot = candidates[i].slot;
        const std::int64_t uses = count_[index_or_reject("pick_victim", slot)];
        if (uses < fewest || (uses == fewest && slot < victim)) {
            fewest = uses;
            victim = slot;
        }
    }
    return victim;
}

}  // namespace cachesim
