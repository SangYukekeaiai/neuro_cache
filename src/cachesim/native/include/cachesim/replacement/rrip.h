// Static re-reference interval prediction replacement policy.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cachesim/replacement/policy.h"

namespace cachesim {

class RripPolicy final : public ReplacementPolicy {
public:
    explicit RripPolicy(std::int32_t num_slots, std::int32_t bits = 2);

    void on_hit(SlotId slot) override;
    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

private:
    std::size_t index_or_reject(const char* verb, SlotId slot) const;
    std::vector<std::uint8_t> rrpv_;
    std::uint8_t max_rrpv_;
    std::uint8_t insert_rrpv_;
};

}  // namespace cachesim
