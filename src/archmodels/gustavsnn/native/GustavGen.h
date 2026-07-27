// GustavGen.h -- C++ port of GustavSNN's per-tile weight-address/tick
// reconstruction (src/archmodels/gustavsnn/{reconstruct,address,cycles}.py).
//
// Faithful port of three Python functions, kept in lockstep with them:
//   reconstruct_tile_sequence_batch (reconstruct.py) -- builds, per
//     (tile, sample), one GustavSubmatrix per resident HO row, each
//     holding the non-zero (kh, kw, cin) "lines" for that row.
//   event_to_address (address.py) -- flattens submatrices/lines into
//     (kh, kw, cin, cout_start, cout_end) address tuples, in
//     submatrix-then-line order.
//   event_to_ticks (address.py) + group_into_waves (cycles.py) -- groups
//     submatrices into waves of up to PE_COUNT_MAX, and assigns each
//     line a tick = wave_start + (its position within its own
//     submatrix's line list).
//
// A "line" is keyed by the FULL (kh, kw, cin) triple, not (kh, cin) --
// kw is a genuine per-line dimension in the Python source (see
// GustavLine's fields), determined by OR-ing across this tile's resident
// WO range only (not KW), matching reconstruct.py's
// `active = (gathered != 0).any(axis=2)` where axis 2 is WO.
//
// "same" padding, matching reconstruct.py's convention: hin = ho + kh -
// pad_h, win = wo + kw - pad_w, pad_h=(kh_n-1)/2, pad_w=(kw_n-1)/2. An
// (hin, win) outside [0, Hin_full)/[0, Win_full) is treated as zero
// (no spike), never indexed out of bounds.

#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

constexpr int PE_COUNT_MAX = 8;  // K': PEs per tile, matches cycles.py's PE_COUNT_MAX.

struct TileSpec {
    int32_t dram_i;
    int32_t t_offset;
    int32_t ho_off, ho_n;
    int32_t wo_off, wo_n;
    int32_t kh_n, kw_n;
    int32_t cin_off, cin_n;
    int32_t cout_off, cout_n;
};

struct TraceShape {
    int32_t T, B_full, Cin_full, Hin_full, Win_full;

    int64_t index(int32_t t, int32_t b, int32_t cin, int32_t hin, int32_t win) const {
        return ((((int64_t)t * B_full + b) * Cin_full + cin) * Hin_full + hin) * Win_full + win;
    }
};

// One address tuple: (kh, kw, cin, cout_start, cout_end, tick). Kept as
// six parallel-width ints (not two separate structs) purely for
// output-format simplicity -- tick_ids stays logically separate
// (weight_ticks is still its own Protocol method on the Python side);
// this struct is just this file's internal result row.
struct AddressRow {
    int32_t kh, kw, cin, cout_start, cout_end, tick;
};

struct SampleResult {
    int32_t mac_cycles;
    std::vector<AddressRow> addresses;
};

// One resident HO row's non-zero (kh, kw, cin) lines, mirroring
// GustavSubmatrix (positions omitted -- not needed for
// addressing/ticks, only .lines and .piece_idx are).
struct Submatrix {
    int32_t piece_idx;
    std::vector<std::array<int32_t, 3>> lines;  // (kh, kw, cin) per line
};

// Reconstructs one tile's submatrices for one sample -- port of
// reconstruct_tile_sequence_batch, specialized to a single sample
// (the C++ side loops samples itself rather than numpy-broadcasting
// across them, since the per-element Python object-construction cost
// numpy broadcasting was working around doesn't exist here).
inline std::vector<Submatrix> reconstruct_tile(
    const uint8_t* trace, const TraceShape& shape, const TileSpec& tile, int32_t sample_idx
) {
    const int32_t pad_h = (tile.kh_n - 1) / 2;
    const int32_t pad_w = (tile.kw_n - 1) / 2;

    std::vector<Submatrix> submatrices;
    submatrices.reserve(tile.ho_n);

    for (int32_t piece_idx = 0; piece_idx < tile.ho_n; ++piece_idx) {
        const int32_t ho = tile.ho_off + piece_idx;
        Submatrix sm;
        sm.piece_idx = piece_idx;

        for (int32_t kh = 0; kh < tile.kh_n; ++kh) {
            const int32_t hin = ho + kh - pad_h;
            const bool valid_h = (hin >= 0 && hin < shape.Hin_full);
            if (!valid_h) continue;

            for (int32_t kw = 0; kw < tile.kw_n; ++kw) {
                for (int32_t cin_local = 0; cin_local < tile.cin_n; ++cin_local) {
                    const int32_t cin = tile.cin_off + cin_local;
                    bool active = false;
                    for (int32_t wo_local = 0; wo_local < tile.wo_n; ++wo_local) {
                        const int32_t wo = tile.wo_off + wo_local;
                        const int32_t win = wo + kw - pad_w;
                        if (win < 0 || win >= shape.Win_full) continue;
                        const int64_t idx = shape.index(tile.t_offset, sample_idx, cin, hin, win);
                        if (trace[idx] != 0) {
                            active = true;
                            break;
                        }
                    }
                    if (active) {
                        sm.lines.push_back({kh, kw, cin});
                    }
                }
            }
        }
        submatrices.push_back(std::move(sm));
    }
    return submatrices;
}

// Groups submatrices (already in piece_idx order by construction) into
// waves of up to PE_COUNT_MAX, assigns each line's tick, and flattens
// into address rows in the same submatrix-then-line order
// event_to_address uses -- port of group_into_waves (cycles.py) +
// event_to_address + event_to_ticks (address.py), fused into one pass
// since they all need the same wave/line traversal.
inline SampleResult addresses_and_ticks(
    const std::vector<Submatrix>& submatrices, const TileSpec& tile
) {
    SampleResult result;
    result.mac_cycles = 0;

    // Per-submatrix tick base: wave_start at the time this submatrix's
    // wave began. Line j in this submatrix fires at wave_start + j.
    std::vector<int32_t> wave_start_of(submatrices.size(), 0);

    for (size_t wave_begin = 0; wave_begin < submatrices.size(); wave_begin += PE_COUNT_MAX) {
        const size_t wave_end = std::min(wave_begin + (size_t)PE_COUNT_MAX, submatrices.size());
        int32_t wave_len = 0;
        for (size_t i = wave_begin; i < wave_end; ++i) {
            wave_len = std::max(wave_len, (int32_t)submatrices[i].lines.size());
        }
        for (size_t i = wave_begin; i < wave_end; ++i) {
            wave_start_of[i] = result.mac_cycles;
        }
        result.mac_cycles += wave_len;
    }

    for (size_t i = 0; i < submatrices.size(); ++i) {
        const auto& sm = submatrices[i];
        for (size_t j = 0; j < sm.lines.size(); ++j) {
            const auto& line = sm.lines[j];  // {kh, kw, cin}
            AddressRow row;
            row.kh = line[0];
            row.kw = line[1];
            row.cin = line[2];
            row.cout_start = tile.cout_off;
            row.cout_end = tile.cout_off + tile.cout_n;
            row.tick = wave_start_of[i] + (int32_t)j;
            result.addresses.push_back(row);
        }
    }
    return result;
}

inline SampleResult reconstruct_sample(
    const uint8_t* trace, const TraceShape& shape, const TileSpec& tile, int32_t sample_idx
) {
    auto submatrices = reconstruct_tile(trace, shape, tile, sample_idx);
    return addresses_and_ticks(submatrices, tile);
}
