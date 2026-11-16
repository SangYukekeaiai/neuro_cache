// Belady's offline MIN replacement policy.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cachesim/replacement/policy.h"

namespace cachesim {

class BeladyPolicy final : public ReplacementPolicy {
public:
    explicit BeladyPolicy(std::int32_t num_slots);

    void on_hit(SlotId slot) override;
    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;
    void note_next_use(SlotId slot, std::int64_t next_use) override;
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

private:
    std::size_t index_or_reject(const char* verb, SlotId slot) const;
    std::vector<std::int64_t> next_use_;
};

}  // namespace cachesim
