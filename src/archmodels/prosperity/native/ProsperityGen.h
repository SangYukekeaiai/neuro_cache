// ProsperityGen.h -- C++ port of Prosperity's per-tile weight-address/tick
// reconstruction (src/archmodels/prosperity/{reconstruct,address,cycles}.py).
//
// ProSparsity compression, two parts (reconstruct.py's own docstring,
// Wei et al. HPCA 2025):
//
//   1. Temporal ordering: the tile's M = ho_n*wo_n rows (row-major, ho
//      outer wo inner; each row's k = kh_n*kw_n bits, kh outer kw inner,
//      bit_idx = kh*kw_n+kw) are processed in ASCENDING popcount order,
//      STABLE (ties keep ascending original row index).
//
//   2. Prefix selection + XOR pattern: for each row in that order, among
//      ALREADY-PROCESSED rows whose bit-set is a SUBSET of the current
//      row's, pick the one processed MOST RECENTLY (== largest
//      (popcount, original_index), since `processed` is itself built in
//      that ascending order -- see reconstruct.py's own correctness
//      argument for why the last/most-recent match is always the
//      (popcount, idx)-maximal one, no separate argmax needed). The
//      row's `pattern` = its own bits XOR the chosen prefix's bits (or
//      its own bits unchanged if no valid prefix exists).
//
// CRITICAL ordering detail: reconstruct.py's `ProsperityReconstructed.rows`
// -- and therefore event_to_address's emitted addresses -- are in
// PROCESSING order (ascending popcount), NOT original (ho, wo) row-major
// order. This port replicates that: rows are built row-major first (for
// bit extraction), then iterated/emitted in the popcount-sorted order.
//
// event_to_address (address.py): each row's `pattern`'s set bits become
// address (kh, kw, cin, cout_start, cout_end), kh/kw = divmod(bit_idx,
// kw_n), in row-processing-order then bit-index order.
// event_to_ticks / mac_cycles: strictly sequential, one cycle per
// pattern bit (cycles.py: access_cycle_count == compute_cycle_count ==
// total pattern popcount == len(addresses), no dominance case).
//
// Row bits are packed into a uint64_t bitmask (k is always small in this
// deployment, Table III's k=16; 64 bits comfortably covers any realistic
// kh_n*kw_n), making the subset test and XOR single bitwise ops instead
// of per-bit loops -- this is the one arch whose Python version needed
// its own O(M^2) inner-loop vectorization (M=256) to get any speedup at
// all (reconstruct.py's own docstring), so the equivalent C++ tightness
// matters here more than elsewhere.
//
// "same" padding, matching reconstruct.py: hin = ho + kh - pad_h,
// win = wo + kw - pad_w, pad_h=(kh_n-1)/2, pad_w=(kw_n-1)/2.

#pragma once

#include <algorithm>
#include <cstdint>
#include <vector>

struct TileSpec {
    int32_t dram_i;
    int32_t ho_off, ho_n;
    int32_t wo_off, wo_n;
    int32_t kh_n, kw_n;
    int32_t cin;               // single fixed channel (CIN barred from NodeLevel)
    int32_t t;                 // single fixed tick (T barred from NodeLevel)
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

inline int popcount64(uint64_t x) {
#if defined(__GNUC__) || defined(__clang__)
    return __builtin_popcountll(x);
#else
    int c = 0;
    while (x) { c += x & 1; x >>= 1; }
    return c;
#endif
}

inline SampleResult reconstruct_sample(
    const uint8_t* trace, const TraceShape& shape, const TileSpec& tile, int32_t sample_idx
) {
    const int32_t pad_h = (tile.kh_n - 1) / 2;
    const int32_t pad_w = (tile.kw_n - 1) / 2;
    const int32_t k = tile.kh_n * tile.kw_n;
    const int32_t m = tile.ho_n * tile.wo_n;

    // Row-major (ho, wo) bit extraction, one uint64_t bitmask per row.
    std::vector<uint64_t> row_bits(m, 0);
    for (int32_t ho_local = 0; ho_local < tile.ho_n; ++ho_local) {
        const int32_t ho = tile.ho_off + ho_local;
        for (int32_t wo_local = 0; wo_local < tile.wo_n; ++wo_local) {
            const int32_t wo = tile.wo_off + wo_local;
            const int32_t row = ho_local * tile.wo_n + wo_local;
            uint64_t bits = 0;
            for (int32_t kh = 0; kh < tile.kh_n; ++kh) {
                const int32_t hin = ho + kh - pad_h;
                if (hin < 0 || hin >= shape.Hin_full) continue;
                for (int32_t kw = 0; kw < tile.kw_n; ++kw) {
                    const int32_t win = wo + kw - pad_w;
                    if (win < 0 || win >= shape.Win_full) continue;
                    const int64_t idx = shape.index(tile.t, sample_idx, tile.cin, hin, win);
                    if (trace[idx] != 0) {
                        bits |= (uint64_t)1 << (kh * tile.kw_n + kw);
                    }
                }
            }
            row_bits[row] = bits;
        }
    }

    // Stable sort by (popcount, original row index) ascending.
    std::vector<int32_t> order(m);
    for (int32_t i = 0; i < m; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(), [&](int32_t a, int32_t b) {
        return popcount64(row_bits[a]) < popcount64(row_bits[b]);
    });

    // Sequential ProSparsity walk: processed_bits/processed_idx track
    // steps [0, step) in the SAME order results are emitted in, so
    // scanning backward from step-1 finds the most-recently-processed
    // (== (popcount, idx)-maximal, per reconstruct.py's own correctness
    // argument) subset match first, with no separate max needed.
    std::vector<uint64_t> processed_bits(m);
    std::vector<int32_t> processed_idx(m);

    SampleResult result;
    result.mac_cycles = 0;

    for (int32_t step = 0; step < m; ++step) {
        const int32_t idx = order[step];
        const uint64_t bits = row_bits[idx];

        uint64_t pattern = bits;
        for (int32_t s = step - 1; s >= 0; --s) {
            // Subset test: processed row `s` is a subset of `bits` iff it
            // has no 1-bit where `bits` has a 0, i.e. (processed & ~bits) == 0.
            if ((processed_bits[s] & ~bits) == 0) {
                pattern = bits ^ processed_bits[s];
                break;
            }
        }

        // Emit this row's pattern bits as addresses, kh outer/kw inner
        // (bit_idx = kh*kw_n+kw), matching event_to_address's
        // divmod(bit_idx, kw_n) exactly.
        for (int32_t bit_idx = 0; bit_idx < k; ++bit_idx) {
            if (pattern & ((uint64_t)1 << bit_idx)) {
                AddressRow row;
                row.kh = bit_idx / tile.kw_n;
                row.kw = bit_idx % tile.kw_n;
                row.cin = tile.cin;
                row.cout_start = tile.cout_off;
                row.cout_end = tile.cout_off + tile.cout_n;
                row.tick = result.mac_cycles;
                result.addresses.push_back(row);
                result.mac_cycles += 1;
            }
        }

        processed_bits[step] = bits;
        processed_idx[step] = idx;
    }

    return result;
}
