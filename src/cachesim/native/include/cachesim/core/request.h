// Request state and the small enums shared by the hierarchy and instruments.
#pragma once

#include <cstdint>

#include "cachesim/types.h"

namespace cachesim {

struct Mshr;

enum class Level : std::uint8_t { L1 = 0, L2 = 1 };
enum class WaitReason : std::uint8_t { None = 0, Slot = 1, Line = 2 };

enum class StallCause : std::uint8_t {
    None    = 0,
    L1Slot  = 1,
    L1Line  = 2,
    L1Port  = 3,
    L2Slot  = 4,
    L2Line  = 5,
    L2Port  = 6,
    Channel = 7,
    Barrier = 8,
};

struct Request {
    CoreId     core;
    LineId     line;
    BurstIndex burst;
    bool       demand = true;
    SimTime    issued_at{0};
    RefusalOrder refusal = NoRefusal;
    WaitReason reason = WaitReason::None;
    Level level = Level::L1;
    Mshr* mshr1 = nullptr;
    bool reserved = false;
    bool on_wait_index = false;
    StallCause cause = StallCause::None;
    bool line_resident_at_wake = false;
};

}  // namespace cachesim
