// PTBGen.h -- C++ port of PTB's per-tile weight-address/tick
// reconstruction (src/archmodels/ptb/{reconstruct,address,cycles}.py).
//
// One tile = one fixed (ho, wo) output pixel's full reduction row.
// stSAP compression, two passes, [KH, KW, CIN] nested iteration order:
//
//   Pass 1 (silence removal): a (kh, kw, cin) "line" survives if it
//   fires at least once across the tile's whole T range. Its full
//   length-T bit-vector is kept (needed by Pass 2's overlap test, unlike
//   LoAS which only needs the yes/no).
//
//   Pass 2 (adjacent non-overlap merge): greedy left-to-right walk over
//   Pass-1 survivors -- merge line i with i+1 into one group iff their
//   bit-vectors never both have a 1 at the same timestep (AND is
//   all-zero), else line i is its own group. `ln` = number of Pass-2
//   groups.
//
// event_to_address (address.py): addresses come from Pass-1 lines
// directly (NOT Pass-2 groups), same [KH,KW,CIN] order.
// event_to_ticks: tick i == Pass-1 line i (sequential, matches
// access_cycle_count == len(lines_pass1)).
//
// mac_cycles is NOT len(lines_pass1) here (unlike LoAS/SpinalFlow/
// Prosperity) -- PTB's own cycles.py: total_cycle_count =
// max(access_cycle_count, compute_cycle_count), where
// compute_cycle_count is a systolic-pipeline fill/drain formula using
// `ln` (Pass-2 group count) and the tile's COUT/T bounds. Ported
// verbatim below (TW_SIZE/PE_ROWS_MAX/PE_COLS_MAX match cycles.py's own
// constants for this deployment).
//
// "same" padding, matching reconstruct.py: hin = ho + kh - pad_h,
// win = wo + kw - pad_w, pad_h=(kh_n-1)/2, pad_w=(kw_n-1)/2.

#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

constexpr int32_t TW_SIZE = 8;
constexpr int32_t PE_ROWS_MAX = 16;
constexpr int32_t PE_COLS_MAX = 8;

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

struct Pass1Line {
    int32_t kh, kw, cin;
    std::vector<uint8_t> bits;  // length t_n
};

// compute_cycle_count (cycles.py), ported verbatim.
inline int32_t compute_cycle_count(int32_t ln, int32_t cout_n, int32_t total_t) {
    const int32_t active_rows = std::min(cout_n, PE_ROWS_MAX);
    const int32_t active_cols = std::min((total_t + TW_SIZE - 1) / TW_SIZE, PE_COLS_MAX);  // ceil div
    const int32_t last_col_timesteps = total_t - TW_SIZE * (active_cols - 1);

    const int32_t full_total = ln + active_rows + total_t;
    const int32_t active_drain = ln + active_rows + active_cols + last_col_timesteps;
    return std::max(full_total, active_drain);
}

inline SampleResult reconstruct_sample(
    const uint8_t* trace, const TraceShape& shape, const TileSpec& tile, int32_t sample_idx
) {
    const int32_t pad_h = (tile.kh_n - 1) / 2;
    const int32_t pad_w = (tile.kw_n - 1) / 2;

    // Pass 1: silence removal, [KH, KW, CIN] nested order, keeping each
    // survivor's full T-bit-vector for Pass 2's overlap test.
    std::vector<Pass1Line> lines_pass1;

    for (int32_t kh = 0; kh < tile.kh_n; ++kh) {
        const int32_t hin = tile.ho + kh - pad_h;
        const bool valid_h = (hin >= 0 && hin < shape.Hin_full);

        for (int32_t kw = 0; kw < tile.kw_n; ++kw) {
            const int32_t win = tile.wo + kw - pad_w;
            const bool valid_w = (win >= 0 && win < shape.Win_full);

            for (int32_t cin_local = 0; cin_local < tile.cin_n; ++cin_local) {
                const int32_t cin = tile.cin_off + cin_local;
                Pass1Line line;
                line.kh = kh;
                line.kw = kw;
                line.cin = cin;
                line.bits.assign(tile.t_n, 0);
                bool any_fire = false;
                if (valid_h && valid_w) {
                    for (int32_t ti = 0; ti < tile.t_n; ++ti) {
                        const int32_t t = tile.t_off + ti;
                        const int64_t idx = shape.index(t, sample_idx, cin, hin, win);
                        if (trace[idx] != 0) {
                            line.bits[ti] = 1;
                            any_fire = true;
                        }
                    }
                }
                if (any_fire) {
                    lines_pass1.push_back(std::move(line));
                }
            }
        }
    }

    // Pass 2: greedy adjacent-merge walk.
    int32_t ln = 0;
    {
        size_t i = 0;
        const size_t n = lines_pass1.size();
        while (i < n) {
            bool merge = false;
            if (i + 1 < n) {
                merge = true;
                for (int32_t ti = 0; ti < tile.t_n; ++ti) {
                    if (lines_pass1[i].bits[ti] != 0 && lines_pass1[i + 1].bits[ti] != 0) {
                        merge = false;
                        break;
                    }
                }
            }
            ln += 1;
            i += merge ? 2 : 1;
        }
    }

    SampleResult result;
    result.addresses.reserve(lines_pass1.size());
    for (size_t i = 0; i < lines_pass1.size(); ++i) {
        AddressRow row;
        row.kh = lines_pass1[i].kh;
        row.kw = lines_pass1[i].kw;
        row.cin = lines_pass1[i].cin;
        row.cout_start = tile.cout_off;
        row.cout_end = tile.cout_off + tile.cout_n;
        row.tick = (int32_t)i;
        result.addresses.push_back(row);
    }

    const int32_t access_cycle_count = (int32_t)lines_pass1.size();
    const int32_t compute_cycles = compute_cycle_count(ln, tile.cout_n, tile.t_n);
    result.mac_cycles = std::max(access_cycle_count, compute_cycles);
    return result;
}
