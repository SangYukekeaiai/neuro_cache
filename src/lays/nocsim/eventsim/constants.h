// Single source for constants shared with Python: nocsim/core/transaction.py
// parses this file, so keep each value on one `constexpr int NAME = N;` line.
#pragma once

constexpr int FLITS_PER_PACKET = 4;  // payload flits per packet (1 header flit excluded)
