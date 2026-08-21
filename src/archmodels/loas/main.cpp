// loasgen -- CLI wrapper around LoASGen.h's reconstruction port.
//
// Usage:
//   loasgen <trace.bin> <task.bin> <out.bin>
//
// task.bin (all int32, native-endian):
//   T, B_full, Cin_full, Hin_full, Win_full
//   num_tiles
//   num_samples
//   per tile (num_tiles times): dram_i, ho, wo, kh_n, kw_n, cin_off,
//     cin_n, t_off, t_n, cout_off, cout_n  (11 int32)
//   per sample (num_samples times): sample_idx
//
// trace.bin: flat uint8, row-major [T, B_full, Cin_full, Hin_full, Win_full].
//
// out.bin (all int32): for each sample (outer), for each tile (inner):
//   tile_idx, sample_idx, mac_cycles, num_ticks
//   per tick (ascending): tick_value, num_addresses_at_tick
//     per address: kh, kw, cin, cout_start, cout_end  (5 int32, tick omitted --
//     it's the group key above, not repeated per address)
// See src/archmodels/tick_output.h for the shared tick-grouping helper this
// uses -- LoAS's own tick assignment (LoASGen.h) is strictly sequential, so
// every tick group here has exactly one address, but the wire format and
// the grouping logic are the same shared shape every arch writes.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <vector>

#include "LoASGen.h"
#include "../tick_output.h"

namespace {

int32_t read_i32(std::ifstream& fh) {
    int32_t v;
    fh.read(reinterpret_cast<char*>(&v), sizeof(v));
    if (!fh) {
        std::cerr << "loasgen: unexpected EOF reading task file\n";
        std::exit(2);
    }
    return v;
}

void write_i32(std::ostream& fh, int32_t v) {
    fh.write(reinterpret_cast<const char*>(&v), sizeof(v));
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: loasgen <trace.bin> <task.bin> <out.bin>\n";
        return 2;
    }
    const std::string trace_path = argv[1];
    const std::string task_path = argv[2];
    const std::string out_path = argv[3];

    std::ifstream task_fh(task_path, std::ios::binary);
    if (!task_fh) {
        std::cerr << "loasgen: cannot open task file " << task_path << "\n";
        return 2;
    }

    TraceShape shape;
    shape.T = read_i32(task_fh);
    shape.B_full = read_i32(task_fh);
    shape.Cin_full = read_i32(task_fh);
    shape.Hin_full = read_i32(task_fh);
    shape.Win_full = read_i32(task_fh);

    const int32_t num_tiles = read_i32(task_fh);
    const int32_t num_samples = read_i32(task_fh);

    std::vector<TileSpec> tiles(num_tiles);
    for (auto& tile : tiles) {
        tile.dram_i = read_i32(task_fh);
        tile.ho = read_i32(task_fh);
        tile.wo = read_i32(task_fh);
        tile.kh_n = read_i32(task_fh);
        tile.kw_n = read_i32(task_fh);
        tile.cin_off = read_i32(task_fh);
        tile.cin_n = read_i32(task_fh);
        tile.t_off = read_i32(task_fh);
        tile.t_n = read_i32(task_fh);
        tile.cout_off = read_i32(task_fh);
        tile.cout_n = read_i32(task_fh);
    }

    std::vector<int32_t> sample_indices(num_samples);
    for (auto& s : sample_indices) {
        s = read_i32(task_fh);
    }

    const int64_t trace_elems =
        (int64_t)shape.T * shape.B_full * shape.Cin_full * shape.Hin_full * shape.Win_full;
    std::vector<uint8_t> trace(trace_elems);
    {
        std::ifstream trace_fh(trace_path, std::ios::binary);
        if (!trace_fh) {
            std::cerr << "loasgen: cannot open trace file " << trace_path << "\n";
            return 2;
        }
        trace_fh.read(reinterpret_cast<char*>(trace.data()), trace_elems);
        if (!trace_fh) {
            std::cerr << "loasgen: trace file shorter than expected shape\n";
            return 2;
        }
    }

    // `-` means stdout, which is what makes this binary a stream producer with
    // no change to what it writes (see the Phase D campaign plan, 10.3(b)).
    std::ofstream out_file;
    std::ostream* out = nullptr;
    if (out_path == "-") {
        out = &std::cout;
    } else {
        out_file.open(out_path, std::ios::binary);
        if (!out_file) {
            std::cerr << "loasgen: cannot open output file " << out_path << "\n";
            return 2;
        }
        out = &out_file;
    }
    std::ostream& out_fh = *out;

    // Sample-outer, tile-inner. A stream consumer needs one sample's tiles
    // contiguously; under the old nesting it would have to buffer every sample
    // before it could emit tile 1. See the Phase D campaign plan, 10.4.
    for (int32_t sample_idx : sample_indices) {
        for (int32_t tile_idx = 0; tile_idx < num_tiles; ++tile_idx) {
            const TileSpec& tile = tiles[tile_idx];
            SampleResult result = reconstruct_sample(trace.data(), shape, tile, sample_idx);
            write_i32(out_fh, tile_idx);
            write_i32(out_fh, sample_idx);
            write_i32(out_fh, result.mac_cycles);
            write_tick_grouped(out_fh, result.addresses);
        }
    }

    return 0;
}
