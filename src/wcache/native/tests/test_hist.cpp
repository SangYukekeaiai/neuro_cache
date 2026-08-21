// Task 14 (D2d): the G14 per-(core, tile) distinct-address histogram and its
// sidecar file.
//
// Ruling R6: this is EXPLANATORY only. It gates nothing and its outcome does
// not move the L1 axis, so nothing here asserts a threshold; it asserts that
// the diagnostic reports what the trace actually contains.
#include <wcache/byte_source.h>
#include <wcache/hist.h>
#include <wcache/stream_format.h>
#include <wcache/stream_trace.h>

#include <cstdint>
#include <sstream>
#include <string>
#include <vector>

#include "check.h"
#include "stream_builder.h"

using namespace wcache;

namespace {

std::vector<std::string> lines_of(const std::string& text) {
    std::vector<std::string> out;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) out.push_back(line);
    return out;
}

// Three tiles, three cores, with a hand-known distinct count per (core, tile).
//
//   tile 0: core 0 -> {(1,1,6,0..16), repeated, (1,1,7,0..16)} = 2
//           core 1 -> absent                                   = 0
//           core 2 -> {(0,0,0,0..16)}                          = 1
//   tile 1: core 0 -> {(0,0,0,0..16), (0,0,1,0..16), (0,0,2,0..16)} = 3
//           core 1 -> {(0,0,0,0..16)}                          = 1
//           core 2 -> absent                                   = 0
//   tile 2: core 1 -> {(5,5,5,0..16)}                          = 1
//           cores 0 and 2 -> absent                            = 0
//
// The nine samples sorted are 0 0 0 0 1 1 1 2 3, so max is 3 and the p50
// (nearest rank, index min(n-1, floor(0.5*n)) = 4) is 1.
std::vector<unsigned char> three_tile_stream() {
    fx::StreamBuilder b(3, 3);
    b.begin_tile(0, 20);
    b.begin_core(0);
    b.add_burst(0, 1, 1, 6, 0, 16);
    b.add_burst(1, 1, 1, 6, 0, 16);  // the SAME address again: not distinct
    b.add_burst(2, 1, 1, 7, 0, 16);  // a different one
    b.begin_core(2);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();

    b.begin_tile(1, 20);
    b.begin_core(0);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.add_burst(1, 0, 0, 1, 0, 16);
    b.add_burst(2, 0, 0, 2, 0, 16);
    b.begin_core(1);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();

    b.begin_tile(2, 20);
    b.begin_core(1);
    b.add_burst(0, 5, 5, 5, 0, 16);
    b.end_tile();
    return b.finish();
}

void test_the_sidecar_has_a_row_per_core_per_tile() {
    check::group("Task 14: the sidecar is n_tiles * n_cores data rows plus a header");
    const std::vector<unsigned char> bytes = three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    DistinctAddressHistogram hist(tr.header());
    while (tr.advance()) hist.observe(tr);

    std::ostringstream out;
    hist.write_csv(out);
    const std::vector<std::string> rows = lines_of(out.str());
    CHECK_EQ(check::ssize(rows), std::int64_t{1 + 3 * 3});
    CHECK_TRUE(rows.front() ==
               "arch,workload,layer,sample_idx,tile,core,distinct_addresses");
}

void test_a_core_absent_from_a_tile_reports_zero() {
    check::group("Task 14: an absent core appears as 0, never omitted");
    const std::vector<unsigned char> bytes = three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    DistinctAddressHistogram hist(tr.header());
    while (tr.advance()) hist.observe(tr);

    std::ostringstream out;
    hist.write_csv(out);
    const std::vector<std::string> rows = lines_of(out.str());
    // Row order is tile-major, core-minor, so row 1 + tile*3 + core.
    const std::string prefix = "loas,vgg16,layer_01,0,";
    CHECK_TRUE(rows.at(1) == prefix + "0,0,2");
    CHECK_TRUE(rows.at(2) == prefix + "0,1,0");  // absent from tile 0
    CHECK_TRUE(rows.at(3) == prefix + "0,2,1");
    CHECK_TRUE(rows.at(4) == prefix + "1,0,3");
    CHECK_TRUE(rows.at(5) == prefix + "1,1,1");
    CHECK_TRUE(rows.at(6) == prefix + "1,2,0");  // absent from tile 1
    CHECK_TRUE(rows.at(7) == prefix + "2,0,0");
    CHECK_TRUE(rows.at(8) == prefix + "2,1,1");
    CHECK_TRUE(rows.at(9) == prefix + "2,2,0");
}

void test_p50_and_max_match_the_hand_computed_answer() {
    check::group("Task 14: p50 and max over the nine samples");
    const std::vector<unsigned char> bytes = three_tile_stream();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    DistinctAddressHistogram hist(tr.header());
    while (tr.advance()) hist.observe(tr);
    // sorted: 0 0 0 0 1 1 1 2 3
    CHECK_EQ(hist.p50(), std::int32_t{1});
    CHECK_EQ(hist.max(), std::int32_t{3});
    CHECK_EQ(hist.samples(), std::int64_t{9});
}

void test_an_unobserved_histogram_is_empty_rather_than_wrong() {
    check::group("Task 14: nothing observed reports 0 and writes only a header");
    stream::StreamHeader hdr;
    hdr.n_tiles = 4;
    hdr.n_cores = 2;
    DistinctAddressHistogram hist(hdr);
    CHECK_EQ(hist.samples(), std::int64_t{0});
    CHECK_EQ(hist.p50(), std::int32_t{0});
    CHECK_EQ(hist.max(), std::int32_t{0});
    std::ostringstream out;
    hist.write_csv(out);
    CHECK_EQ(check::ssize(lines_of(out.str())), std::int64_t{1});
}

}  // namespace

int main() {
    test_the_sidecar_has_a_row_per_core_per_tile();
    test_a_core_absent_from_a_tile_reports_zero();
    test_p50_and_max_match_the_hand_computed_answer();
    test_an_unobserved_histogram_is_empty_rather_than_wrong();
    return check::summary();
}
