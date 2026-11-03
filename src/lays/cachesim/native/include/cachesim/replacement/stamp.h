// Stamp-based LRU and FIFO replacement policies.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cachesim/replacement/policy.h"

namespace cachesim {

class StampPolicy : public ReplacementPolicy {
public:
    explicit StampPolicy(std::int32_t num_slots);

    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

protected:
    void stamp(SlotId slot);

private:
    std::size_t index_or_reject(const char* verb, SlotId slot) const;
    std::vector<std::int64_t> stamp_;
    std::int64_t next_stamp_;
};

class LruPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;
    void on_hit(SlotId slot) override;
};

class FifoPolicy final : public StampPolicy {
public:
    using StampPolicy::StampPolicy;
    void on_hit(SlotId) override;
};

}  // namespace cachesim
