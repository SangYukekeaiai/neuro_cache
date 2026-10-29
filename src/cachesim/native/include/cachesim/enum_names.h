// The single source for enum spellings used by config, CSV output and sweeps.
#pragma once

#include <string>

#include "cachesim/core/engine.h"
#include "cachesim/layout/mapper.h"
#include "cachesim/prefetch/prefetcher.h"
#include "cachesim/replacement/policy.h"

namespace cachesim {

// CSV emission treats this sentinel as an invalid enum, so its spelling is a
// shared contract with stats.cpp's csv_name_of guard.
inline constexpr const char* kUnknownEnumName = "unknown";

inline const char* name_of(LayoutKind k) {
    switch (k) {
        case LayoutKind::BlockPack: return "block_pack";
        case LayoutKind::SplitCin:  return "split_cin";
        case LayoutKind::KhkwSplit: return "khkw_split";
    }
    return kUnknownEnumName;
}

inline bool parse(const std::string& text, LayoutKind& out) {
    if (text == "block_pack") out = LayoutKind::BlockPack;
    else if (text == "split_cin") out = LayoutKind::SplitCin;
    else if (text == "khkw_split") out = LayoutKind::KhkwSplit;
    else return false;
    return true;
}

inline const char* name_of(PolicyKind k) {
    switch (k) {
        case PolicyKind::LRU:    return "lru";
        case PolicyKind::FIFO:   return "fifo";
        case PolicyKind::RANDOM: return "random";
        case PolicyKind::BELADY: return "belady";
        case PolicyKind::RRIP:   return "rrip";
        case PolicyKind::LFU:    return "lfu";
    }
    return kUnknownEnumName;
}

inline bool parse(const std::string& text, PolicyKind& out) {
    if (text == "lru") out = PolicyKind::LRU;
    else if (text == "fifo") out = PolicyKind::FIFO;
    else if (text == "random") out = PolicyKind::RANDOM;
    else if (text == "belady") out = PolicyKind::BELADY;
    else if (text == "rrip") out = PolicyKind::RRIP;
    else if (text == "lfu") out = PolicyKind::LFU;
    else return false;
    return true;
}

inline const char* name_of(PrefetchKind k) {
    switch (k) {
        case PrefetchKind::None:      return "none";
        case PrefetchKind::NextBurst: return "next_burst";
        case PrefetchKind::NextTile:  return "next_tile";
        case PrefetchKind::Neighbour: return "neighbour";
    }
    return kUnknownEnumName;
}

inline bool parse(const std::string& text, PrefetchKind& out) {
    if (text == "none") out = PrefetchKind::None;
    else if (text == "next_burst") out = PrefetchKind::NextBurst;
    else if (text == "next_tile") out = PrefetchKind::NextTile;
    else if (text == "neighbour" || text == "neighbor") out = PrefetchKind::Neighbour;
    else return false;
    return true;
}

inline const char* name_of(Inclusion k) {
    switch (k) {
        case Inclusion::NonInclusive: return "non_inclusive";
        case Inclusion::Inclusive:    return "inclusive";
    }
    return kUnknownEnumName;
}

inline bool parse(const std::string& text, Inclusion& out) {
    if (text == "non_inclusive") out = Inclusion::NonInclusive;
    else if (text == "inclusive") out = Inclusion::Inclusive;
    else return false;
    return true;
}

}  // namespace cachesim
