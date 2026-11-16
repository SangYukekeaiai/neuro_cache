#include "cachesim/replacement/rrip.h"

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace cachesim {
namespace {

constexpr std::int32_t kRripMaxBits = 8;

[[noreturn]] void reject(const char* who, const std::string& what) {
    throw std::invalid_argument(std::string(who) + ": " + what);
}

}  // namespace

RripPolicy::RripPolicy(std::int32_t num_slots, std::int32_t bits) {
    if (num_slots < 1) {
        reject("RripPolicy", "num_slots must be >= 1, got " + std::to_string(num_slots));
    }
    if (bits < 1 || bits > kRripMaxBits) {
        reject("RripPolicy", "rrip_bits must be in [1, " + std::to_string(kRripMaxBits) +
                             "], got " + std::to_string(bits));
    }
    max_rrpv_ = static_cast<std::uint8_t>((1u << static_cast<unsigned>(bits)) - 1u);
    insert_rrpv_ = static_cast<std::uint8_t>(max_rrpv_ - (max_rrpv_ > 0 ? 1 : 0));
    rrpv_.assign(static_cast<std::size_t>(num_slots), max_rrpv_);
}

std::size_t RripPolicy::index_or_reject(const char* verb, SlotId slot) const {
    const std::int32_t s = slot.get();
    if (s < 0 || static_cast<std::size_t>(s) >= rrpv_.size()) {
        throw std::out_of_range("RripPolicy::" + std::string(verb) + ": slot " +
                                std::to_string(s) + " is outside [0, " +
                                std::to_string(rrpv_.size()) + ")");
    }
    return static_cast<std::size_t>(s);
}

void RripPolicy::on_hit(SlotId slot) { rrpv_[index_or_reject("on_hit", slot)] = 0; }

void RripPolicy::on_fill(SlotId slot) {
    rrpv_[index_or_reject("on_fill", slot)] = insert_rrpv_;
}

void RripPolicy::on_invalidate(SlotId slot) {
    rrpv_[index_or_reject("on_invalidate", slot)] = max_rrpv_;
}

SlotId RripPolicy::pick_victim(const std::vector<Candidate>& candidates) {
    if (candidates.empty()) reject("RripPolicy::pick_victim", "the candidate set is empty");

    std::uint8_t highest = 0;
    for (const Candidate& c : candidates) {
        const std::uint8_t v = rrpv_[index_or_reject("pick_victim", c.slot)];
        if (v > highest) highest = v;
    }
    const std::uint8_t rise = static_cast<std::uint8_t>(max_rrpv_ - highest);

    SlotId victim = candidates.front().slot;
    bool   found  = false;
    for (const Candidate& c : candidates) {
        std::uint8_t& v = rrpv_[index_or_reject("pick_victim", c.slot)];
        v = static_cast<std::uint8_t>(v + rise);
        if (v == max_rrpv_ && (!found || c.slot < victim)) {
            victim = c.slot;
            found  = true;
        }
    }
    return victim;
}

}  // namespace cachesim
