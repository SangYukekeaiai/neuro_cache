// Tasks 2 and 3: StreamingTileTrace, the one-tile sliding window over a WCTS
// stream, checked against the TileTrace contract trace.h states.
#include <wcache/byte_source.h>
#include <wcache/stream_format.h>
#include <wcache/stream_trace.h>
#include <wcache/trace.h>
#include <wcache/types.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "engine_fixture.h"
#include "stream_builder.h"

using namespace wcache;

namespace {

// The WCTS stream builder is shared with test_hist.cpp (tests/stream_builder.h).
using fx::StreamBuilder;

void test_header_is_read_and_the_window_starts_empty() {
    check::group("Task 2: the constructor reads the header, window_tile() is -1");
    StreamBuilder b(2, 8);
    b.begin_tile(0, 24); b.begin_core(0); b.add_burst(0, 1, 1, 6, 0, 16); b.end_tile();
    b.begin_tile(1, 24); b.begin_core(0); b.add_burst(0, 1, 0, 8, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_EQ(tr.n_tiles(), 2);
    CHECK_EQ(tr.n_cores(), 8);
    CHECK_EQ(tr.window_tile(), -1);
    CHECK_EQ(tr.header().burst_span, 16);
    CHECK_TRUE(tr.header().burst_dim == Axis::COUT);
    CHECK_TRUE(tr.header().arch == "loas");
    CHECK_EQ(tr.tick_base(0), std::int64_t{0});
}

void test_a_query_before_the_first_advance_throws() {
    check::group("Task 2: querying tile 0 before advance() throws");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::out_of_range, tr.n_bursts(CoreId{0}, 0));
    CHECK_THROWS(std::out_of_range, tr.burst(CoreId{0}, 0, BurstIndex{0}));
    CHECK_THROWS(std::out_of_range, tr.local_tick(CoreId{0}, 0, BurstIndex{0}));
    CHECK_THROWS(std::out_of_range, tr.gap(CoreId{0}, 0, BurstIndex{0}));
    CHECK_THROWS(std::out_of_range, tr.tile_tail(0));
    CHECK_THROWS(std::out_of_range, tr.mac_cycles(0));
}

void test_bad_magic_in_the_constructor_throws() {
    check::group("Task 2: a corrupt header throws from the constructor");
    StreamBuilder b(0, 1);
    std::vector<unsigned char> bytes = b.finish();
    bytes[1] = 'Z';
    MemByteSource src(bytes);
    CHECK_THROWS(std::invalid_argument, StreamingTileTrace{src});
}

void test_a_truncated_header_throws() {
    check::group("Task 2: a header cut short is a truncated stream, not a bad header");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    std::vector<unsigned char> bytes = b.finish();
    bytes.resize(40);
    MemByteSource src(bytes);
    CHECK_THROWS(std::runtime_error, StreamingTileTrace{src});
}

void test_one_tile_decodes_and_the_window_moves() {
    check::group("Task 3: advance() decodes a frame and the queries answer for it");
    StreamBuilder b(2, 4);
    b.begin_tile(0, 10);
    b.begin_core(0);
    b.add_burst(0, 1, 1, 6, 0, 16);
    b.add_burst(1, 1, 1, 7, 0, 16);
    b.begin_core(2);
    b.add_burst(3, 0, 0, 0, 16, 32);
    b.end_tile();
    b.begin_tile(1, 8);
    b.begin_core(1);
    b.add_burst(0, 2, 2, 2, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);

    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.window_tile(), 0);
    CHECK_EQ(tr.n_bursts(CoreId{0}, 0), 2);
    CHECK_EQ(tr.n_bursts(CoreId{1}, 0), 0);  // omitted core: zero is legal
    CHECK_EQ(tr.n_bursts(CoreId{2}, 0), 1);
    CHECK_EQ(tr.n_bursts(CoreId{3}, 0), 0);
    CHECK_EQ(tr.local_tick(CoreId{0}, 0, BurstIndex{0}), LocalTick{0});
    CHECK_EQ(tr.local_tick(CoreId{0}, 0, BurstIndex{1}), LocalTick{1});
    CHECK_EQ(tr.gap(CoreId{0}, 0, BurstIndex{0}), LocalTick{1});
    // max_tick is 3 (core 2), mac_cycles is 10, so the tail is 7.
    CHECK_EQ(tr.tile_tail(0), LocalTick{7});
    CHECK_EQ(tr.mac_cycles(0), std::int64_t{10});
    CHECK_EQ(tr.tick_base(0), std::int64_t{0});

    const Burst& first = tr.burst(CoreId{0}, 0, BurstIndex{0});
    CHECK_EQ(first.count, 16);
    CHECK_EQ(first.stride, 1);
    CHECK_TRUE(first.axis == Axis::COUT);
    CHECK_EQ(coord_on(first.anchor, Axis::KH), 1);
    CHECK_EQ(coord_on(first.anchor, Axis::KW), 1);
    CHECK_EQ(coord_on(first.anchor, Axis::CIN), 6);
    CHECK_EQ(coord_on(first.anchor, Axis::COUT), 0);
    CHECK_EQ(coord_on(tr.burst(CoreId{2}, 0, BurstIndex{0}).anchor, Axis::COUT), 16);

    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.window_tile(), 1);
    CHECK_EQ(tr.tick_base(1), std::int64_t{10});
    CHECK_EQ(tr.tick_base(2), std::int64_t{18});
    CHECK_EQ(tr.tile_tail(0), LocalTick{7});   // retained past the window
    CHECK_EQ(tr.mac_cycles(0), std::int64_t{10});
    CHECK_EQ(tr.tile_tail(1), LocalTick{8});
    CHECK_THROWS(std::out_of_range, tr.n_bursts(CoreId{0}, 0));  // payload is not
    CHECK_EQ(tr.n_bursts(CoreId{1}, 1), 1);
    CHECK_TRUE(!tr.advance());                 // clean trailer
    CHECK_TRUE(!tr.advance());                 // and it stays at the end
}

void test_gap_is_a_difference_not_an_absolute_tick() {
    check::group("Task 3: gap is local_tick(k+1) - local_tick(k) (trace.h, D13)");
    StreamBuilder b(1, 1);
    b.begin_tile(0, 20);
    b.begin_core(0);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.add_burst(5, 0, 0, 0, 0, 16);
    b.add_burst(12, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.gap(CoreId{0}, 0, BurstIndex{0}), LocalTick{5});
    CHECK_EQ(tr.gap(CoreId{0}, 0, BurstIndex{1}), LocalTick{7});
    CHECK_THROWS(std::out_of_range, tr.gap(CoreId{0}, 0, BurstIndex{2}));
    CHECK_EQ(tr.tile_tail(0), LocalTick{8});
}

void test_a_tile_with_no_cores_is_legal() {
    check::group("Task 3: a tile in which no core issues is legal (trace.h)");
    StreamBuilder b(1, 4);
    b.begin_tile(0, 5); b.end_tile();  // no core blocks at all
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.n_bursts(CoreId{0}, 0), 0);
    CHECK_EQ(tr.tile_tail(0), LocalTick{5});  // max_tick 0, so the tail is mac_cycles
    CHECK_THROWS(std::out_of_range, tr.burst(CoreId{0}, 0, BurstIndex{0}));
    CHECK_TRUE(!tr.advance());
}

// --- the eight format rejections -------------------------------------------

void test_out_of_order_tile_index_throws() {
    check::group("Task 3 rejection 1: a frame whose tile_index is not the counter");
    StreamBuilder b(2, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.begin_tile(7, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_core_id_at_or_above_n_cores_throws() {
    check::group("Task 3 rejection 2: a core id outside [0, n_cores) (U25)");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4); b.begin_core(2); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_descending_core_id_throws() {
    check::group("Task 3 rejection 3: core blocks must ascend");
    StreamBuilder b(1, 4);
    b.begin_tile(0, 4);
    b.begin_core(2); b.add_burst(0, 0, 0, 0, 0, 16);
    b.begin_core(1); b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_non_ascending_local_tick_throws() {
    check::group("Task 3 rejection 4: local_tick must strictly increase in a core block");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8);
    b.begin_core(0);
    b.add_burst(3, 0, 0, 0, 0, 16);
    b.add_burst(3, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_empty_run_throws() {
    check::group("Task 3 rejection 5: run_end <= run_start rather than a count of 0");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 16, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_tile_tail_below_one_throws() {
    check::group("Task 3 rejection 6: tile_tail >= 1 is checked, not assumed (Q10)");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 3);                                // mac_cycles 3
    b.begin_core(0); b.add_burst(3, 0, 0, 0, 0, 16);   // max_tick 3, tail 0
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_wrong_end_magic_in_the_trailer_throws() {
    check::group("Task 3 rejection 7: the trailer's end magic is checked");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.set_end_magic(0);
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_wrong_total_bursts_in_the_trailer_throws() {
    check::group("Task 3 rejection 8: the trailer's burst count is checked end to end");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.set_total_bursts(99);
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

// --- two further framing faults the frame prefix makes cheap to catch -------

void test_too_many_core_blocks_throws() {
    check::group("Task 3: n_core_blocks above n_cores is refused before decoding");
    StreamBuilder b(1, 2);
    b.set_core_block_bias(2);  // declares 3 blocks where 1 was written
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_payload_bytes_that_disagree_with_the_content_throws() {
    check::group("Task 3: payload_bytes must match what the core blocks consume");
    StreamBuilder b(1, 2);
    b.set_payload_bias(8);  // declares 8 bytes more payload than were written
    b.begin_tile(0, 8); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::runtime_error, tr.advance());
}

void test_a_truncated_frame_throws() {
    check::group("Task 3: a stream cut off inside a frame is truncation, not an end");
    StreamBuilder b(2, 2);
    b.begin_tile(0, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    b.begin_tile(1, 4); b.begin_core(0); b.add_burst(0, 0, 0, 0, 0, 16); b.end_tile();
    std::vector<unsigned char> bytes = b.finish();
    bytes.resize(bytes.size() - 20);
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::runtime_error, tr.advance());
}

// --- the cross-check against the semantic oracle ----------------------------

void test_matches_fake_trace_on_every_interface_method() {
    check::group("Task 3: identical answers to FakeTrace over the same content");
    // FakeTrace (tests/engine_fixture.h) is the hand-written TileTrace the
    // Phase C suites drive the engine with. A stream encoding the same content
    // must be indistinguishable from it through the seven virtuals, because the
    // engine holds only the abstraction (B10, B23).
    fx::FakeTrace fake(4);
    const std::int32_t t0 = fake.add_tile(3);
    fake.add_burst(t0, 0, 0, 0, 16);
    fake.add_burst(t0, 0, 4, 32, 16);
    fake.add_burst(t0, 2, 9, 64, 8);
    const std::int32_t t1 = fake.add_tile(1);
    fake.add_burst(t1, 1, 2, 0, 4);
    fake.add_burst(t1, 3, 6, 128, 16);

    StreamBuilder b(2, 4);
    b.begin_tile(0, fake.mac_cycles(t0));
    b.begin_core(0);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.add_burst(4, 0, 0, 0, 32, 48);
    b.begin_core(2);
    b.add_burst(9, 0, 0, 0, 64, 72);
    b.end_tile();
    b.begin_tile(1, fake.mac_cycles(t1));
    b.begin_core(1);
    b.add_burst(2, 0, 0, 0, 0, 4);
    b.begin_core(3);
    b.add_burst(6, 0, 0, 0, 128, 144);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);

    const TileTrace& streamed = tr;
    const TileTrace& oracle   = fake;
    CHECK_EQ(streamed.n_tiles(), oracle.n_tiles());
    CHECK_EQ(streamed.n_cores(), oracle.n_cores());

    for (std::int32_t tile = 0; tile < oracle.n_tiles(); ++tile) {
        CHECK_TRUE(tr.advance());
        CHECK_EQ(streamed.tile_tail(tile), oracle.tile_tail(tile));
        CHECK_EQ(tr.mac_cycles(tile), fake.mac_cycles(tile));
        for (std::int32_t c = 0; c < oracle.n_cores(); ++c) {
            const CoreId core{c};
            const std::int32_t n = oracle.n_bursts(core, tile);
            CHECK_EQ(streamed.n_bursts(core, tile), n);
            for (std::int32_t k = 0; k < n; ++k) {
                const BurstIndex bi{k};
                CHECK_EQ(streamed.local_tick(core, tile, bi), oracle.local_tick(core, tile, bi));
                const Burst& a = streamed.burst(core, tile, bi);
                const Burst& e = oracle.burst(core, tile, bi);
                CHECK_EQ(a.count, e.count);
                CHECK_EQ(a.stride, e.stride);
                CHECK_TRUE(a.axis == e.axis);
                CHECK_EQ(coord_on(a.anchor, Axis::KH), coord_on(e.anchor, Axis::KH));
                CHECK_EQ(coord_on(a.anchor, Axis::KW), coord_on(e.anchor, Axis::KW));
                CHECK_EQ(coord_on(a.anchor, Axis::CIN), coord_on(e.anchor, Axis::CIN));
                CHECK_EQ(coord_on(a.anchor, Axis::COUT), coord_on(e.anchor, Axis::COUT));
                if (k + 1 < n) {
                    CHECK_EQ(streamed.gap(core, tile, bi), oracle.gap(core, tile, bi));
                }
            }
        }
    }
    CHECK_TRUE(!tr.advance());
}

void test_distinct_addresses_counts_tuples_not_bursts() {
    check::group("Task 14: G14's per-(core, tile) distinct-address count");
    StreamBuilder b(1, 3);
    b.begin_tile(0, 20);
    b.begin_core(0);
    b.add_burst(0, 1, 1, 6, 0, 16);
    b.add_burst(1, 1, 1, 6, 0, 16);      // the SAME address again: not distinct
    b.add_burst(2, 1, 1, 7, 0, 16);      // a different one
    b.begin_core(2);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.distinct_addresses(CoreId{0}), 2);
    CHECK_EQ(tr.distinct_addresses(CoreId{1}), 0);
    CHECK_EQ(tr.distinct_addresses(CoreId{2}), 1);
}

void test_distinct_addresses_separates_bursts_of_different_extent() {
    check::group("Task 14: two runs from one anchor are two addresses");
    StreamBuilder b(1, 1);
    b.begin_tile(0, 20);
    b.begin_core(0);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.add_burst(1, 0, 0, 0, 0, 8);   // same anchor, shorter run: a different record
    b.add_burst(2, 0, 0, 0, 4, 16);  // same end, later start
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.distinct_addresses(CoreId{0}), 3);
}

void test_distinct_addresses_answers_only_for_the_window() {
    check::group("Task 14: distinct_addresses obeys the window and the core range");
    StreamBuilder b(1, 2);
    b.begin_tile(0, 4);
    b.begin_core(0);
    b.add_burst(0, 0, 0, 0, 0, 16);
    b.end_tile();
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource src(bytes);
    StreamingTileTrace tr(src);
    CHECK_THROWS(std::out_of_range, tr.distinct_addresses(CoreId{0}));  // window empty
    CHECK_TRUE(tr.advance());
    CHECK_THROWS(std::out_of_range, tr.distinct_addresses(CoreId{2}));
    CHECK_THROWS(std::out_of_range, tr.distinct_addresses(CoreId{-1}));
}

}  // namespace

int main() {
    test_header_is_read_and_the_window_starts_empty();
    test_a_query_before_the_first_advance_throws();
    test_bad_magic_in_the_constructor_throws();
    test_a_truncated_header_throws();
    test_one_tile_decodes_and_the_window_moves();
    test_gap_is_a_difference_not_an_absolute_tick();
    test_a_tile_with_no_cores_is_legal();
    test_out_of_order_tile_index_throws();
    test_core_id_at_or_above_n_cores_throws();
    test_descending_core_id_throws();
    test_non_ascending_local_tick_throws();
    test_empty_run_throws();
    test_tile_tail_below_one_throws();
    test_wrong_end_magic_in_the_trailer_throws();
    test_wrong_total_bursts_in_the_trailer_throws();
    test_too_many_core_blocks_throws();
    test_payload_bytes_that_disagree_with_the_content_throws();
    test_a_truncated_frame_throws();
    test_matches_fake_trace_on_every_interface_method();
    test_distinct_addresses_counts_tuples_not_bursts();
    test_distinct_addresses_separates_bursts_of_different_extent();
    test_distinct_addresses_answers_only_for_the_window();
    return check::summary();
}
