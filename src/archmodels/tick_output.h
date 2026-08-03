#pragma once
// tick_output.h -- shared helper for archmodels/*/main.cpp: buckets a
// SampleResult's addresses by their own `.tick` field and writes the
// tick-grouped wire format shared by every arch's weight-trace output, so
// this logic lives in exactly one place instead of being duplicated across
// 5 independently-verified native codebases. See
// log/2026-08-02-multinode-core-driven-weight-trace-plan.md.
//
// Requires AddressRow to have public int32_t fields kh, kw, cin,
// cout_start, cout_end, tick -- every arch's <Arch>Gen.h already declares
// this struct with this exact shape (confirmed identical across loas, ptb,
// gustavsnn, prosperity, spinalflow, 2026-08-02).
//
// Output shape, appended to a stream already positioned after this
// (tile, sample)'s own tile_idx/sample_idx/mac_cycles header:
//   num_ticks
//   per tick (num_ticks times, ascending): tick_value, num_addresses_at_tick
//     per address: kh, kw, cin, cout_start, cout_end   (tick omitted -- it's
//     the group key, not repeated per address)
//
// For 4 of 5 archs (loas, ptb, prosperity, spinalflow) every tick has
// exactly one address by construction (strictly sequential tick
// assignment) -- this helper still buckets explicitly rather than assuming
// that, so it's correct for GustavSNN's genuine same-tick multi-address
// case without a separate code path.

#include <cstdint>
#include <fstream>
#include <map>
#include <vector>

template <typename AddressRow>
inline void write_tick_grouped(std::ofstream& out_fh, const std::vector<AddressRow>& addresses) {
    // std::map keeps ticks in ascending order for free. Bucketing
    // explicitly (not assuming addresses already arrive tick-sorted) means
    // this helper is correct regardless of discovery order, not just for
    // the archs where discovery already happens to be tick-ascending.
    std::map<int32_t, std::vector<const AddressRow*>> by_tick;
    for (const auto& row : addresses) {
        by_tick[row.tick].push_back(&row);
    }

    auto write_i32 = [&out_fh](int32_t v) {
        out_fh.write(reinterpret_cast<const char*>(&v), sizeof(v));
    };

    write_i32(static_cast<int32_t>(by_tick.size()));
    for (const auto& kv : by_tick) {
        write_i32(kv.first);                                  // tick value
        write_i32(static_cast<int32_t>(kv.second.size()));     // addresses at this tick
        for (const AddressRow* row : kv.second) {
            write_i32(row->kh);
            write_i32(row->kw);
            write_i32(row->cin);
            write_i32(row->cout_start);
            write_i32(row->cout_end);
        }
    }
}
