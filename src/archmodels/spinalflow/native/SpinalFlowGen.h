// SpinalFlowGen.h -- C++ port of SpinalFlow's per-tile weight-address/tick
// reconstruction (src/archmodels/spinalflow/{reconstruct,address,cycles}.py).
//
// Much simpler than GustavSNN: one tile = one fixed (ho, wo) output pixel
// (no per-row waves), so a "spine" is just every (t, kh, kw, cin) with a
// real spike, visited in t-outermost, kh, kw, cin-innermost order --
// exactly reconstruct_tile_sequence_batch's own iteration order (the
// Python source builds this via one big numpy nonzero() and a
// transpose that puts axes in this same order; here it's a direct
// nested loop, no vectorization trick needed since there's no per-element
// Python object construction cost to dodge with numpy in the first
// place -- C++ loops are cheap either way).
//
// event_to_address (address.py): each spike event (t, cin, kh, kw)
// becomes address (kh, kw, cin, cout_start, cout_end), t dropped.
// event_to_ticks: strictly sequential, tick i == event i (cycles.py:
// access_cycle_count == compute_cycle_count == len(events), one spike
// event consumed per cycle, no dominance case, no parallelism).
//
// "same" padding, matching reconstruct.py: hin = ho + kh - pad_h,
// win = wo + kw - pad_w, pad_h=(kh_n-1)/2, pad_w=(kw_n-1)/2. Out-of-range
// (hin, win) is padding (zero, never a spike), never indexed OOB.

#pragma once

#include <cstdint>
#include <vector>

struct TileSpec {
    int32_t dram_i;
    int32_t ho, wo;           // fixed output pixel for this tile
    int32_t kh_n, kw_n;
    int32_t cin_off, cin_n;
    int32_t t_off, t_n;
    int32_t cout_off, cout_n;
};

struct TraceShape {
    int32_t T, B_full, Cin_full, Hin_full, Win_full;

    int64_t index(int32_t t, int32_t b, int32_t cin, int32_t hin, int32_t win) const {
        return ((((int64_t)t * B_full + b) * Cin_full + cin) * Hin_full + hin) * Win_full + win;
    }
};

struct AddressRow {
    int32_t kh, kw, cin, cout_start, cout_end, tick;
};

struct SampleResult {
    int32_t mac_cycles;
    std::vector<AddressRow> addresses;
};

inline SampleResult reconstruct_sample(
    const uint8_t* trace, const TraceShape& shape, const TileSpec& tile, int32_t sample_idx
) {
    const int32_t pad_h = (tile.kh_n - 1) / 2;
    const int32_t pad_w = (tile.kw_n - 1) / 2;

    SampleResult result;
    result.mac_cycles = 0;

    // t outermost, then kh, kw, cin innermost -- matches
    // reconstruct_tile_sequence_batch's own event order exactly, so
    // ticks (== event position) line up the same way they would from
    // the Python path.
    for (int32_t t = tile.t_off; t < tile.t_off + tile.t_n; ++t) {
        for (int32_t kh = 0; kh < tile.kh_n; ++kh) {
            const int32_t hin = tile.ho + kh - pad_h;
            if (hin < 0 || hin >= shape.Hin_full) continue;
            for (int32_t kw = 0; kw < tile.kw_n; ++kw) {
                const int32_t win = tile.wo + kw - pad_w;
                if (win < 0 || win >= shape.Win_full) continue;
                for (int32_t cin_local = 0; cin_local < tile.cin_n; ++cin_local) {
                    const int32_t cin = tile.cin_off + cin_local;
                    const int64_t idx = shape.index(t, sample_idx, cin, hin, win);
                    if (trace[idx] != 0) {
                        AddressRow row;
                        row.kh = kh;
                        row.kw = kw;
                        row.cin = cin;
                        row.cout_start = tile.cout_off;
                        row.cout_end = tile.cout_off + tile.cout_n;
                        row.tick = result.mac_cycles;
                        result.addresses.push_back(row);
                        result.mac_cycles += 1;
                    }
                }
            }
        }
    }
    return result;
}
