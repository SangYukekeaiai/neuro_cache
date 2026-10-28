#include "cachesim/replacement/policy.h"

#include <memory>
#include <stdexcept>
#include <string>

#include "cachesim/replacement/belady.h"
#include "cachesim/replacement/lfu.h"
#include "cachesim/replacement/rrip.h"
#include "cachesim/replacement/stamp.h"

namespace cachesim {
namespace {

[[noreturn]] void reject(const char* who, const std::string& what) {
    throw std::invalid_argument(std::string(who) + ": " + what);
}

}  // namespace

std::unique_ptr<ReplacementPolicy> make_policy(PolicyKind kind, std::int32_t num_slots,
                                               std::int32_t rrip_bits) {
    switch (kind) {
        case PolicyKind::LRU:    return std::make_unique<LruPolicy>(num_slots);
        case PolicyKind::FIFO:   return std::make_unique<FifoPolicy>(num_slots);
        case PolicyKind::BELADY: return std::make_unique<BeladyPolicy>(num_slots);
        case PolicyKind::RRIP:   return std::make_unique<RripPolicy>(num_slots, rrip_bits);
        case PolicyKind::LFU:    return std::make_unique<LfuPolicy>(num_slots);
        case PolicyKind::RANDOM:
            reject("make_policy",
                   "policy 'random' is a placeholder and is not implemented; use 'lru' or 'fifo'");
    }
    throw std::logic_error("make_policy: unknown PolicyKind");
}

}  // namespace cachesim
