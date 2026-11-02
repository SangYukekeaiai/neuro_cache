// Two-class LRU for the L2: protected lines outlive unprotected ones.
//
// Plan docs/plans/2026-11-02-l2-pf-lru-replacement.md: lines filled by the L2
// next_tile prefetch and not yet consumed are the protected class; everything
// else is the normal class. The victim is the LRU line of the normal class;
// only a set whose candidates are all protected victimizes a protected line,
// again by LRU. The stamps are StampPolicy's, so within each class the order
// is exactly plain LRU's; the class bit arrives through note_protected and is
// owned here, never by the array.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cachesim/replacement/stamp.h"

namespace cachesim {

class PfLruPolicy final : public StampPolicy {
public:
    explicit PfLruPolicy(std::int32_t num_slots);

    void on_hit(SlotId slot) override;
    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;
    void note_protected(SlotId slot, bool is_protected) override;
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

private:
    std::size_t index_or_reject(const char* verb, SlotId slot) const;
    std::vector<std::uint8_t> protected_;
};

}  // namespace cachesim
