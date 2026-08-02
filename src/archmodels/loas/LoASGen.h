// LoASGen.h -- C++ port of LoAS's per-tile weight-address/tick
// reconstruction (src/archmodels/loas/{reconstruct,address,cycles}.py).
//
// One tile = one fixed (ho, wo) output pixel's full reduction row. A
// "line" is one (kh, kw, cin) position that fires at least once across
// the tile's whole T range (bitmask == 1, "non-silent") -- silent
// positions (never fire) contribute nothing. Iteration order is
// [KH, KW, CIN] nested (kh outermost, cin innermost), matching
// reconstruct.py's own bitmask layout
// (`non_silent.reshape(num_batch, -1)` flattens a [KH,KW,CIN] array with
// CIN fastest).
//
// Neither the row-level bitmask nor each line's own length-T spike
// bit-vector is needed downstream: cycles.py/address.py both read only
// `.lines`' (kh, kw, cin) identity, not `.bitmask`/`.ptr`/`.bits` (see
// address.py's own module docstring: "this module doesn't read
// reconstructed.bitmask/.ptr -- only .lines matters"). So this port
// skips building either, it only needs the yes/no "did this (kh,kw,cin)
// fire at all in this tile's T range" test.
//
// event_to_address (address.py): each line (kh, kw, cin) becomes address
// (kh, kw, cin, cout_start, cout_end), same [KH,KW,CIN] order as above.
// event_to_ticks: strictly sequential, tick i == line i (cycles.py:
// access_cycle_count == compute_cycle_count == popcount(bitmask) ==
// len(lines), one weight-fetch cycle per non-silent row, no dominance
// case, no parallelism).
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

    for (int32_t kh = 0; kh < tile.kh_n; ++kh) {
        const int32_t hin = tile.ho + kh - pad_h;
        const bool valid_h = (hin >= 0 && hin < shape.Hin_full);

        for (int32_t kw = 0; kw < tile.kw_n; ++kw) {
            const int32_t win = tile.wo + kw - pad_w;
            const bool valid_w = (win >= 0 && win < shape.Win_full);

            for (int32_t cin_local = 0; cin_local < tile.cin_n; ++cin_local) {
                const int32_t cin = tile.cin_off + cin_local;
                bool non_silent = false;
                if (valid_h && valid_w) {
                    for (int32_t t = tile.t_off; t < tile.t_off + tile.t_n; ++t) {
                        const int64_t idx = shape.index(t, sample_idx, cin, hin, win);
                        if (trace[idx] != 0) {
                            non_silent = true;
                            break;
                        }
                    }
                }
                if (non_silent) {
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
    return result;
}
