// Two-class LRU for the L2: protected lines outlive unprotected ones.
//
// Plan docs/plans/2026-11-02-l2-pf-lru-replacement.md: lines filled by the L2
// distance_aware prefetch and not yet consumed are the protected class; everything
// else is the normal class. The victim is the LRU line of the normal class;
// only a set whose candidates are all protected victimizes a protected line,
// again by LRU. The stamps are StampPolicy's, so within each class the order
// is exactly plain LRU's; the class bit arrives through note_protected and is
// owned here, never by the array.
//
// T24 (same plan, follow-up): pf_lru_rand is this policy with ONE difference,
// the all-protected fallback. LRU there victimizes the same slot in every
// set under the deterministic core-ascending fill order, stripping one core's
// coverage; the rand mode instead draws the forced victim pseudo-randomly:
// victim = argmin over the candidates of splitmix64(line ^ seed ^ draw), the
// draw counter advancing once per fallback draw. Order-independent because
// each candidate's key depends only on the candidate itself and on policy
// state, never on its position, and argmin with a slot-id tie-break is a
// function of the set; deterministic across runs and platforms because
// splitmix64 is fixed-width integer arithmetic with pinned constants and the
// seed is a compile-time constant, no std::rand and no global state.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "cachesim/replacement/stamp.h"

namespace cachesim {

class PfLruPolicy final : public StampPolicy {
public:
    // What pick_victim does when EVERY candidate is protected. Lru is
    // PolicyKind::PF_LRU, Rand is PolicyKind::PF_LRU_RAND; everywhere an
    // unprotected candidate exists the two modes are byte-identical.
    enum class Fallback : std::uint8_t { Lru, Rand };

    explicit PfLruPolicy(std::int32_t num_slots, Fallback fallback = Fallback::Lru);

    void on_hit(SlotId slot) override;
    void on_fill(SlotId slot) override;
    void on_invalidate(SlotId slot) override;
    void note_protected(SlotId slot, bool is_protected) override;
    SlotId pick_victim(const std::vector<Candidate>& candidates) override;

private:
    std::size_t index_or_reject(const char* verb, SlotId slot) const;
    SlotId rand_fallback_victim(const std::vector<Candidate>& candidates);
    std::vector<std::uint8_t> protected_;
    Fallback fallback_;
    // One per fallback draw taken, Rand mode only: consecutive forced
    // evictions draw different victims instead of pinning one slot. This is
    // the state pick_victim's non-const signature exists for.
    std::uint64_t rand_draws_ = 0;
};

}  // namespace cachesim
