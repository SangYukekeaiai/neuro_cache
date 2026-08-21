// Task 1: the WCTS wire format header and the byte sources that carry it.
//
// Every case here works on a byte buffer built by encode_header and then
// corrupted by hand, so a decoder that trusted the producer is caught by the
// same test that pins the round trip.
#include <wcache/byte_source.h>
#include <wcache/stream_format.h>
#include <wcache/types.h>

#include <unistd.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"

using namespace wcache;
using wcache::stream::DimCode;
using wcache::stream::FieldCode;
using wcache::stream::StreamHeader;

namespace {

StreamHeader good_header() {
    StreamHeader h;
    h.n_tiles      = 2;
    h.n_cores      = 8;
    h.weight_bytes = 1;
    h.burst_dim    = Axis::COUT;
    h.burst_stride = 1;
    h.burst_span   = 16;
    h.addr_fields  = {FieldCode::KH, FieldCode::KW, FieldCode::CIN,
                      FieldCode::RunStart, FieldCode::RunEnd};
    h.spatial_factors = {{DimCode::COUT, 8}};
    h.dims = {{DimCode::KH, 3},    {DimCode::KW, 3},  {DimCode::CIN, 64},
              {DimCode::COUT, 64}, {DimCode::HO, 32}, {DimCode::WO, 32},
              {DimCode::T, 4}};
    h.arch = "loas";
    h.workload = "vgg16_T4_all";
    h.layer = "layer_01_features_3";
    h.sample_idx = 0;
    return h;
}

std::vector<unsigned char> encoded(const StreamHeader& h) {
    std::vector<unsigned char> buf;
    stream::encode_header(h, buf);
    return buf;
}

void test_header_round_trips() {
    check::group("Task 1: encode_header then decode_header is the identity");
    const std::vector<unsigned char> buf = encoded(good_header());
    const StreamHeader got = stream::decode_header(buf.data(), buf.size());
    CHECK_EQ(got.n_tiles, 2);
    CHECK_EQ(got.n_cores, 8);
    CHECK_EQ(got.weight_bytes, 1);
    CHECK_EQ(got.burst_stride, 1);
    CHECK_EQ(got.burst_span, 16);
    CHECK_TRUE(got.burst_dim == Axis::COUT);
    CHECK_EQ(check::ssize(got.addr_fields), std::int64_t{5});
    CHECK_TRUE(got.addr_fields[0] == FieldCode::KH);
    CHECK_TRUE(got.addr_fields[4] == FieldCode::RunEnd);
    CHECK_EQ(check::ssize(got.spatial_factors), std::int64_t{1});
    CHECK_TRUE(got.spatial_factors[0].first == DimCode::COUT);
    CHECK_EQ(got.spatial_factors[0].second, 8);
    CHECK_EQ(check::ssize(got.dims), std::int64_t{7});
    CHECK_EQ(got.dims[3].second, 64);
    CHECK_TRUE(got.arch == "loas");
    CHECK_TRUE(got.workload == "vgg16_T4_all");
    CHECK_TRUE(got.layer == "layer_01_features_3");
    CHECK_EQ(got.sample_idx, 0);
    CHECK_EQ(static_cast<std::int64_t>(buf.size()),
             static_cast<std::int64_t>(stream::kFixedHeaderBytes) + 4 * 5 + 8 * 1 + 8 * 7 +
                 std::int64_t{4 + 1 + 12 + 1 + 19 + 1 + 1 + 1});
}

void test_header_bytes_mismatch_throws() {
    check::group("Task 1: a header_bytes that disagrees with the field counts throws");
    std::vector<unsigned char> buf = encoded(good_header());
    // header_bytes lives at offset 12. Corrupt it by one.
    const std::uint32_t bad = stream::read_le<std::uint32_t>(buf.data() + 12) + 1u;
    stream::write_le<std::uint32_t>(buf.data() + 12, bad);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_spatial_product_must_equal_n_cores() {
    check::group("Task 1: prod(spatial_factors) != n_cores throws (U25, U26, ruling Q-C)");
    StreamHeader h = good_header();
    h.spatial_factors = {{DimCode::COUT, 4}};  // 4 != n_cores 8
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_spatial_dims_must_ascend() {
    check::group("Task 1: spatial factor dim ids must ascend");
    StreamHeader h = good_header();
    h.n_cores = 8;
    h.spatial_factors = {{DimCode::COUT, 4}, {DimCode::CIN, 2}};  // descending
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_bad_magic_throws() {
    check::group("Task 1: a wrong magic throws rather than decoding garbage");
    std::vector<unsigned char> buf = encoded(good_header());
    buf[0] = 'X';
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_bad_version_throws() {
    check::group("Task 1: a format_version other than 1 throws");
    std::vector<unsigned char> buf = encoded(good_header());
    stream::write_le<std::uint32_t>(buf.data() + 8, 2u);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_short_buffer_throws() {
    check::group("Task 1: a buffer shorter than the fixed header throws");
    const std::vector<unsigned char> buf = encoded(good_header());
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), 16));
}

void test_burst_span_must_be_positive() {
    check::group("Task 1: burst_span >= 1 (ruling Q-D: D1 needs it before the first burst)");
    StreamHeader h = good_header();
    h.burst_span = 0;
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_burst_stride_must_be_positive() {
    check::group("Task 1: burst_stride >= 1");
    StreamHeader h = good_header();
    h.burst_stride = 0;
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_burst_dim_out_of_range_throws() {
    check::group("Task 1: a burst_dim outside the four weight axes throws");
    std::vector<unsigned char> buf = encoded(good_header());
    stream::write_le<std::int32_t>(buf.data() + 28, 6);  // HO is not a weight axis
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_addr_field_order_is_pinned() {
    check::group("Task 1: v1 address field order must be exactly {0,1,2,3,4} (U28)");
    StreamHeader h = good_header();
    h.addr_fields = {FieldCode::KW, FieldCode::KH, FieldCode::CIN,
                     FieldCode::RunStart, FieldCode::RunEnd};
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_dims_must_be_zero_through_six() {
    check::group("Task 1: the seven workload dims must be ids 0..6 ascending");
    StreamHeader h = good_header();
    h.dims[6].first = DimCode::WO;  // 5 repeated, so 6 is missing
    const std::vector<unsigned char> buf = encoded(h);
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_identity_must_hold_four_fields() {
    check::group("Task 1: the identity block is exactly four NUL-terminated fields");
    std::vector<unsigned char> buf = encoded(good_header());
    buf.back() = 'x';  // eat the trailing NUL, leaving three terminators
    CHECK_THROWS(std::invalid_argument, stream::decode_header(buf.data(), buf.size()));
}

void test_axis_code_round_trip() {
    check::group("Task 1: axis_of and code_of are inverses over the four weight axes");
    CHECK_TRUE(stream::axis_of(0) == Axis::KH);
    CHECK_TRUE(stream::axis_of(1) == Axis::KW);
    CHECK_TRUE(stream::axis_of(2) == Axis::CIN);
    CHECK_TRUE(stream::axis_of(3) == Axis::COUT);
    CHECK_EQ(stream::code_of(Axis::KH), 0);
    CHECK_EQ(stream::code_of(Axis::COUT), 3);
    CHECK_THROWS(std::invalid_argument, stream::axis_of(4));
    CHECK_THROWS(std::invalid_argument, stream::axis_of(-1));
}

void test_read_le_is_alignment_free() {
    check::group("Task 1: read_le works from an odd offset");
    std::vector<unsigned char> buf(24, 0);
    stream::write_le<std::int64_t>(buf.data() + 3, std::int64_t{-1234567890123LL});
    CHECK_EQ(stream::read_le<std::int64_t>(buf.data() + 3), std::int64_t{-1234567890123LL});
    stream::write_le<std::int32_t>(buf.data() + 13, std::int32_t{-77});
    CHECK_EQ(stream::read_le<std::int32_t>(buf.data() + 13), std::int32_t{-77});
    stream::write_le<std::uint64_t>(buf.data() + 15, std::uint64_t{0xfeedfacecafebeefULL});
    CHECK_EQ(stream::read_le<std::uint64_t>(buf.data() + 15), std::uint64_t{0xfeedfacecafebeefULL});
}

void test_write_le_is_little_endian_on_the_wire() {
    check::group("Task 1: the wire bytes are little-endian whatever the host is");
    std::vector<unsigned char> buf(4, 0);
    stream::write_le<std::uint32_t>(buf.data(), 0x01020304u);
    CHECK_EQ(static_cast<int>(buf[0]), 0x04);
    CHECK_EQ(static_cast<int>(buf[1]), 0x03);
    CHECK_EQ(static_cast<int>(buf[2]), 0x02);
    CHECK_EQ(static_cast<int>(buf[3]), 0x01);
}

void test_mem_byte_source_partial_read_throws() {
    check::group("Task 1: a truncated record throws, a clean end returns false");
    const std::vector<unsigned char> v(4, 0);
    MemByteSource src(v);
    std::int32_t out = 0;
    CHECK_TRUE(src.read_exact(&out, 4));
    CHECK_EQ(static_cast<std::int64_t>(src.consumed()), std::int64_t{4});
    CHECK_TRUE(!src.read_exact(&out, 4));  // clean end
    MemByteSource short_src(v);
    std::int64_t wide = 0;
    CHECK_THROWS(std::runtime_error, short_src.read_exact(&wide, 8));  // truncated
}

void test_fd_byte_source_reads_a_pipe() {
    check::group("Task 1: FdByteSource reads a pipe, ends cleanly, throws on truncation");
    int fds[2] = {-1, -1};
    CHECK_EQ(::pipe(fds), 0);
    const std::vector<unsigned char> v(8, 7);
    CHECK_EQ(static_cast<std::int64_t>(::write(fds[1], v.data(), v.size())), std::int64_t{8});
    CHECK_EQ(::close(fds[1]), 0);
    FdByteSource src(fds[0]);
    std::int64_t wide = 0;
    CHECK_TRUE(src.read_exact(&wide, 8));
    CHECK_TRUE(!src.read_exact(&wide, 8));  // clean end
    CHECK_EQ(::close(fds[0]), 0);

    CHECK_EQ(::pipe(fds), 0);
    CHECK_EQ(static_cast<std::int64_t>(::write(fds[1], v.data(), 4)), std::int64_t{4});
    CHECK_EQ(::close(fds[1]), 0);
    FdByteSource truncated(fds[0]);
    CHECK_THROWS(std::runtime_error, truncated.read_exact(&wide, 8));
    CHECK_EQ(::close(fds[0]), 0);
}

}  // namespace

int main() {
    test_header_round_trips();
    test_header_bytes_mismatch_throws();
    test_spatial_product_must_equal_n_cores();
    test_spatial_dims_must_ascend();
    test_bad_magic_throws();
    test_bad_version_throws();
    test_short_buffer_throws();
    test_burst_span_must_be_positive();
    test_burst_stride_must_be_positive();
    test_burst_dim_out_of_range_throws();
    test_addr_field_order_is_pinned();
    test_dims_must_be_zero_through_six();
    test_identity_must_hold_four_fields();
    test_axis_code_round_trip();
    test_read_le_is_alignment_free();
    test_write_le_is_little_endian_on_the_wire();
    test_mem_byte_source_partial_read_throws();
    test_fd_byte_source_reads_a_pipe();
    return check::summary();
}
