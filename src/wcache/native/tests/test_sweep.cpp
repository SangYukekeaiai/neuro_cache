// Task 17: BroadcastSweep, N engines driven in lockstep over ONE pass of one
// stream.
//
// The claim this file exists to check is the one the design rests on:
// broadcasting a single tile window to N engines must produce exactly what N
// separate runs produce.
//
// The oracle is deliberately NOT another BroadcastSweep. A one-configuration
// sweep shares every line of driving code with an N-configuration sweep, so an
// equality between the two is structural: it would still hold if the window
// moved a tile early or a tile late, because both sides would move it wrongly
// in the same way. The oracle here is a FULLY RESIDENT trace, every tile
// decoded up front, driven by Engine::run(): no window, no advance(), no
// step_tile(). Only the engine's own event loop is shared, and that is the
// thing the equality is asserting about rather than the thing under suspicion.
#include <wcache/block_pack.h>
#include <wcache/byte_source.h>
#include <wcache/config.h>
#include <wcache/engine.h>
#include <wcache/stats.h>
#include <wcache/stream_trace.h>
#include <wcache/sweep.h>
#include <wcache/trace.h>
#include <wcache/types.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

#include "check.h"
#include "stream_builder.h"

using namespace wcache;

namespace {

// --- the fixture stream -------------------------------------------------------
//
// Three tiles, four cores, three bursts per core per tile. The coordinates are
// generated rather than listed so the stream carries both reuse (a line a later
// tile touches again) and conflict (several cores landing in one set of a
// 16-set L1), which is what makes two different cache geometries produce
// different numbers rather than the same number twice.
constexpr std::int32_t kTiles = 3;
constexpr std::int32_t kCores = 4;

std::vector<unsigned char> build_three_tile_stream() {
    fx::StreamBuilder b(kTiles, kCores);
    for (std::int32_t t = 0; t < kTiles; ++t) {
        b.begin_tile(t, 8);  // max tick 4, so tile_tail is 4
        for (std::int32_t c = 0; c < kCores; ++c) {
            b.begin_core(c);
            for (std::int32_t k = 0; k < 3; ++k) {
                const std::int32_t run_start = 16 * ((c + k) % 4);
                b.add_burst(2 * k, (t + c) % 3, (c + k) % 3, (t * 7 + c * 3 + k) % 64,
                            run_start, run_start + 16);
            }
        }
        b.end_tile();
    }
    return b.finish();
}

// --- the oracle ---------------------------------------------------------------
//
// Every tile resident at once, which is exactly what StreamingTileTrace refuses
// to be. Built by replaying the stream once through the reader, so the two
// sides of the comparison are reading the same bytes and any difference is the
// DRIVING and not the decoding.
class BufferedTileTrace final : public TileTrace {
public:
    explicit BufferedTileTrace(const std::vector<unsigned char>& bytes) {
        MemByteSource      src(bytes);
        StreamingTileTrace tr(src);
        n_cores_ = tr.n_cores();
        tiles_.resize(static_cast<std::size_t>(tr.n_tiles()));
        for (Tile& tile : tiles_) tile.cores.resize(static_cast<std::size_t>(n_cores_));
        while (tr.advance()) {
            const std::int32_t t    = tr.window_tile();
            Tile&              tile = tiles_.at(static_cast<std::size_t>(t));
            tile.tail       = tr.tile_tail(t).get();
            tile.mac_cycles = tr.mac_cycles(t);
            for (std::int32_t c = 0; c < n_cores_; ++c) {
                const CoreId       cid = CoreId{c};
                const std::int32_t n   = tr.n_bursts(cid, t);
                CoreTile&          ct  = tile.cores.at(static_cast<std::size_t>(c));
                for (std::int32_t k = 0; k < n; ++k) {
                    ct.bursts.push_back(tr.burst(cid, t, BurstIndex{k}));
                    ct.ticks.push_back(tr.local_tick(cid, t, BurstIndex{k}).get());
                }
            }
        }
    }

    std::int32_t n_tiles() const override { return static_cast<std::int32_t>(tiles_.size()); }
    std::int32_t n_cores() const override { return n_cores_; }

    std::int32_t n_bursts(CoreId core, std::int32_t tile) const override {
        return static_cast<std::int32_t>(at(core, tile).bursts.size());
    }
    const Burst& burst(CoreId core, std::int32_t tile, BurstIndex k) const override {
        return at(core, tile).bursts.at(static_cast<std::size_t>(k.get()));
    }
    LocalTick local_tick(CoreId core, std::int32_t tile, BurstIndex k) const override {
        return LocalTick{at(core, tile).ticks.at(static_cast<std::size_t>(k.get()))};
    }
    LocalTick gap(CoreId core, std::int32_t tile, BurstIndex k) const override {
        const CoreTile&   ct = at(core, tile);
        const std::size_t i  = static_cast<std::size_t>(k.get());
        if (i + 1 >= ct.ticks.size()) {
            throw std::out_of_range("BufferedTileTrace: gap after the last burst");
        }
        return LocalTick{ct.ticks[i + 1] - ct.ticks[i]};
    }
    LocalTick tile_tail(std::int32_t tile) const override {
        return LocalTick{tiles_.at(static_cast<std::size_t>(tile)).tail};
    }

    std::int64_t tick_base_total() const {
        std::int64_t sum = 0;
        for (const Tile& t : tiles_) sum += t.mac_cycles;
        return sum;
    }

private:
    struct CoreTile {
        std::vector<Burst>        bursts;
        std::vector<std::int64_t> ticks;
    };
    struct Tile {
        std::vector<CoreTile> cores;
        std::int64_t          tail       = 1;
        std::int64_t          mac_cycles = 1;
    };

    const CoreTile& at(CoreId core, std::int32_t tile) const {
        return tiles_.at(static_cast<std::size_t>(tile))
            .cores.at(static_cast<std::size_t>(core.get()));
    }

    std::vector<Tile> tiles_;
    std::int32_t      n_cores_ = 0;
};

// --- shared helpers -----------------------------------------------------------

// The widest burst the header declares, expanded under this layout. The same
// quantity wcache_run hands validate(), asked of the mapper for the reason it
// is asked there: the division is only right when the burst walks COUT.
std::int32_t lines_per_burst(const AddressMapper& mapper, const stream::StreamHeader& hdr) {
    const Burst         widest{Coord{0, 0, 0, 0}, hdr.burst_dim, hdr.burst_span,
                       hdr.burst_stride};
    std::vector<LineId> lines;
    mapper.expand(widest, lines);
    return static_cast<std::int32_t>(lines.size());
}

// Three configurations that are genuinely different machines, not one machine
// three times: a small L1, a large L1, and a large L1 with prefetching, a
// slower L2 and a different MSHR budget. They differ in how fast they consume a
// tile, which is what a lockstep bug needs in order to show: N engines that
// ran at identical speeds would clear every barrier together even if the window
// moved at the wrong moment.
const char* const kConfigs[] = {
    R"({"cout_block": 16, "l1_size_bytes": 2048, "l1_assoc": 8,
        "l2_size_bytes": 65536, "l2_assoc": 16, "l2_latency": 10})",
    R"({"cout_block": 16, "l1_size_bytes": 8192, "l1_assoc": 8,
        "l2_size_bytes": 262144, "l2_assoc": 16, "l2_latency": 4,
        "l1_mshrs": 8, "l2_miss_latency": 40})",
    R"({"cout_block": 16, "l1_size_bytes": 8192, "l1_assoc": 4,
        "l2_size_bytes": 65536, "l2_assoc": 16, "l2_latency": 20,
        "l2_miss_latency": 200, "prefetch_policy": "next_burst",
        "prefetch_distance": 2})"};

std::vector<RunConfig> parse_and_validate(const AddressMapper&         mapper,
                                          const stream::StreamHeader&  hdr,
                                          const std::vector<std::string>& texts) {
    std::vector<RunConfig> out;
    for (const std::string& text : texts) {
        RunConfig            cfg = parse_config(text);
        std::vector<Warning> warnings;
        validate(cfg, lines_per_burst(mapper, hdr), warnings);
        out.push_back(cfg);
    }
    return out;
}

// One finished CSV row for a config and the engine that ran it. The three cells
// that are properties of the TRACE and the LAYOUT rather than of the run
// (padding_fraction and the two distinct-address columns) are supplied
// identically to both sides, because a sweep and a single run compute them from
// the same mapper and the same stream; sweep_cli.sh is what checks those
// end to end. Everything else in the row comes from the engine, which is what
// this comparison is about.
std::string row_of(const RunConfig& cfg, const stream::StreamHeader& hdr, const Engine& engine,
                   std::int64_t tick_base_total) {
    RowIdentity id;
    id.run_id = "fixed";
    const RunStats stats(id, cfg, hdr, engine.stats(), engine.tile_origin(hdr.n_tiles).get(),
                         tick_base_total, 0.0, 0.0, 0, 0);
    stats.check_invariants();
    return stats.csv_row();
}

std::vector<std::string> split_row(const std::string& row) {
    std::vector<std::string> cells;
    std::string              cell;
    for (char ch : row) {
        if (ch == ',') {
            cells.push_back(cell);
            cell.clear();
        } else {
            cell.push_back(ch);
        }
    }
    cells.push_back(cell);
    return cells;
}

// Every column of the schema except the two that cannot be equal across two
// runs by construction, named rather than matched loosely: `run_id` is a fresh
// UUID per run and `sim_wall_seconds` is wall clock.
void check_rows_equal(const std::string& lockstep, const std::string& alone, std::size_t index) {
    const std::vector<std::string>& cols = csv_columns();
    const std::vector<std::string>  a    = split_row(lockstep);
    const std::vector<std::string>  b    = split_row(alone);
    CHECK_EQ(check::ssize(a), check::ssize(cols));
    CHECK_EQ(check::ssize(b), check::ssize(cols));
    if (a.size() != cols.size() || b.size() != cols.size()) return;
    for (std::size_t i = 0; i < cols.size(); ++i) {
        if (cols[i] == "run_id" || cols[i] == "sim_wall_seconds") continue;
        ++check::g_checks;
        if (a[i] != b[i]) {
            ++check::g_failures;
            std::printf("FAIL configuration %d, column %s\n  lockstep : %s\n  alone    : %s\n",
                        static_cast<int>(index), cols[i].c_str(), a[i].c_str(), b[i].c_str());
        }
    }
}

// --- the cases ----------------------------------------------------------------

void test_broadcast_lockstep_equals_running_each_config_alone() {
    check::group("Task 17: N engines over one stream == N separate runs");
    const std::vector<unsigned char> bytes = build_three_tile_stream();

    MemByteSource      shared(bytes);
    StreamingTileTrace trace(shared);
    const stream::StreamHeader hdr = trace.header();
    BlockPackMapper            mapper(shape_of(hdr), 1, 16, 1);
    const std::vector<RunConfig> cfgs = parse_and_validate(
        mapper, hdr, std::vector<std::string>(std::begin(kConfigs), std::end(kConfigs)));

    BroadcastSweep sweep(trace, mapper, cfgs, 256);
    sweep.run();
    CHECK_EQ(sweep.size(), std::size_t{3});

    // The oracle: the same bytes, every tile resident, one engine at a time,
    // driven by Engine::run().
    BufferedTileTrace buffered(bytes);
    CHECK_EQ(buffered.tick_base_total(), trace.tick_base(hdr.n_tiles));

    for (std::size_t i = 0; i < cfgs.size(); ++i) {
        Engine alone(mapper, buffered, to_engine_params(cfgs[i]));
        alone.run();
        for (std::int32_t t = 0; t <= hdr.n_tiles; ++t) {
            CHECK_EQ(sweep.engine(i).tile_origin(t), alone.tile_origin(t));
        }
        check_rows_equal(row_of(sweep.config(i), hdr, sweep.engine(i), buffered.tick_base_total()),
                         row_of(cfgs[i], hdr, alone, buffered.tick_base_total()), i);
    }
}

void test_the_three_configs_are_not_the_same_machine() {
    check::group("Task 17: the equality above is not three copies of one row");
    // Without this the case above would pass just as well on three identical
    // configurations, which would prove nothing about broadcasting.
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    const stream::StreamHeader hdr = trace.header();
    BlockPackMapper            mapper(shape_of(hdr), 1, 16, 1);
    const std::vector<RunConfig> cfgs = parse_and_validate(
        mapper, hdr, std::vector<std::string>(std::begin(kConfigs), std::end(kConfigs)));
    BroadcastSweep sweep(trace, mapper, cfgs, 256);
    sweep.run();
    CHECK_TRUE(sweep.engine(0).tile_origin(hdr.n_tiles) !=
               sweep.engine(1).tile_origin(hdr.n_tiles));
    CHECK_TRUE(sweep.engine(1).tile_origin(hdr.n_tiles) !=
               sweep.engine(2).tile_origin(hdr.n_tiles));
}

void test_step_tile_advances_exactly_one_tile() {
    check::group("Task 17: step_tile is one tile of progress, even across an empty tile");
    // A tile in which every core has no bursts clears its barrier the moment it
    // starts, so the next barrier can already be the queue's minimum when the
    // previous one is dispatched. An implementation that popped the pending
    // barrier ITSELF and then called run_to_barrier -- which dispatches a
    // pending barrier too -- would run through both and leave this engine a
    // tile ahead of the window.
    fx::StreamBuilder b(3, 2);
    for (std::int32_t t = 0; t < 3; ++t) {
        // Tile 1 carries no core block at all: the wire format omits an idle
        // core rather than declaring it with zero bursts.
        b.begin_tile(t, 8);
        if (t != 1) {
            for (std::int32_t c = 0; c < 2; ++c) {
                b.begin_core(c);
                b.add_burst(0, 0, 0, c, 0, 16);
            }
        }
        b.end_tile();
    }
    const std::vector<unsigned char> bytes = b.finish();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
    RunConfig            cfg = parse_config(R"({"cout_block": 16})");
    std::vector<Warning> warnings;
    validate(cfg, lines_per_burst(mapper, trace.header()), warnings);

    Engine engine(mapper, trace, to_engine_params(cfg));
    for (std::int32_t t = 0; t < 3; ++t) {
        CHECK_TRUE(trace.advance());
        CHECK_TRUE(engine.step_tile());
        CHECK_EQ(engine.core(CoreId{0}).tile, t);
    }
    CHECK_TRUE(!trace.advance());
    engine.finish();
}

void test_a_mixed_layout_grid_is_rejected() {
    check::group("Task 17: one mapper, so one layout per sweep");
    // Each of the three layout fields on its own, because a guard that checked
    // only two of them would still pass a test that varied the third alongside
    // one it does check. The first point always matches the mapper, so what
    // rejects the second is the layout guard rather than the mapper guard.
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    const char* const kFirst = R"({"cin_block": 1, "cout_block": 16, "weight_bytes": 1})";
    for (const char* second : {R"({"cin_block": 2, "cout_block": 16, "weight_bytes": 1})",
                               R"({"cin_block": 1, "cout_block": 32, "weight_bytes": 1})",
                               R"({"cin_block": 1, "cout_block": 16, "weight_bytes": 2})"}) {
        MemByteSource      src(bytes);
        StreamingTileTrace trace(src);
        BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
        const std::vector<RunConfig> cfgs =
            parse_and_validate(mapper, trace.header(), {kFirst, second});
        CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, cfgs, 256));
    }
}

void test_a_grid_that_changes_the_mapper_class_is_rejected() {
    check::group("W4: `layout` and `cin_lo_blocks` join the layout guard");
    const std::vector<unsigned char> bytes = build_three_tile_stream();

    // 1. The mapper CLASS changes. cin_block, cout_block and weight_bytes all
    //    agree, so the three fields the old guard checked would have passed it.
    {
        MemByteSource      src(bytes);
        StreamingTileTrace trace(src);
        BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
        const std::vector<RunConfig> cfgs = parse_and_validate(
            mapper, trace.header(),
            {R"({"cin_block": 1, "cout_block": 16, "layout": "block_pack"})",
             R"({"cin_block": 1, "cout_block": 16, "layout": "split_cin"})"});
        CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, cfgs, 256));
    }

    // 2. Both points are split_cin and every declared field agrees. What
    //    differs is l1_size_bytes, which validate turns into two different
    //    cin_lo_blocks, which is two different mappers. An L1-size sweep is a
    //    layout sweep under this layout, and that is the point of the check.
    {
        MemByteSource      src(bytes);
        StreamingTileTrace trace(src);
        BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
        const std::vector<RunConfig> cfgs = parse_and_validate(
            mapper, trace.header(),
            {R"({"cin_block": 1, "cout_block": 16, "layout": "split_cin",
                 "l1_size_bytes": 8192})",
             R"({"cin_block": 1, "cout_block": 16, "layout": "split_cin",
                 "l1_size_bytes": 16384})"});
        CHECK_EQ(cfgs[0].cin_lo_blocks, std::int64_t{64});
        CHECK_EQ(cfgs[1].cin_lo_blocks, std::int64_t{128});
        CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, cfgs, 256));
    }

    // 3. The SAME sweep under block_pack is legal, because the field stays -1
    //    at both points and the mapper does not move. Non-vacuous: without this
    //    the guard above could be refusing every L1-size sweep.
    {
        MemByteSource      src(bytes);
        StreamingTileTrace trace(src);
        BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
        const std::vector<RunConfig> cfgs = parse_and_validate(
            mapper, trace.header(),
            {R"({"cin_block": 1, "cout_block": 16, "l1_size_bytes": 8192})",
             R"({"cin_block": 1, "cout_block": 16, "l1_size_bytes": 16384})"});
        CHECK_EQ(cfgs[0].cin_lo_blocks, std::int64_t{-1});
        CHECK_EQ(cfgs[1].cin_lo_blocks, std::int64_t{-1});
        BroadcastSweep sweep(trace, mapper, cfgs, 256);   // must NOT throw
        CHECK_EQ(check::ssize(cfgs), std::int64_t{2});
    }
}

void test_a_layout_the_mapper_does_not_serve_is_rejected() {
    check::group("Task 17: the injected mapper must be the grid's layout");
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    BlockPackMapper    mapper(shape_of(trace.header()), 2, 16, 1);  // 32-byte lines
    const std::vector<RunConfig> cfgs = parse_and_validate(
        mapper, trace.header(), {R"({"cin_block": 1, "cout_block": 16})"});  // 16-byte lines
    CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, cfgs, 256));
}

void test_max_engines_is_enforced_at_construction() {
    check::group("Task 17: an oversized grid fails at startup, not by OOM");
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
    const std::vector<RunConfig> one =
        parse_and_validate(mapper, trace.header(), {R"({"cout_block": 16})"});
    const std::vector<RunConfig> many(9, one[0]);
    CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, many, 8));
    CHECK_THROWS(std::invalid_argument, BroadcastSweep(trace, mapper, {}, 8));
}

void test_the_window_never_holds_more_than_one_tile() {
    check::group("Task 17: a query for a tile off the window still throws");
    // The lockstep loop must never leave an engine one tile behind, and the
    // window is what enforces it: after the run the reader is past every tile
    // and answers for none of them.
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
    const std::vector<RunConfig> cfgs =
        parse_and_validate(mapper, trace.header(), {R"({"cout_block": 16})"});
    BroadcastSweep sweep(trace, mapper, cfgs, 8);
    sweep.run();
    CHECK_THROWS(std::out_of_range, trace.n_bursts(CoreId{0}, 0));
}

void test_the_tile_observer_sees_every_tile_once() {
    check::group("Task 17: the driver owns the loop, so it hands the tile back");
    const std::vector<unsigned char> bytes = build_three_tile_stream();
    MemByteSource      src(bytes);
    StreamingTileTrace trace(src);
    BlockPackMapper    mapper(shape_of(trace.header()), 1, 16, 1);
    const std::vector<RunConfig> cfgs =
        parse_and_validate(mapper, trace.header(), {R"({"cout_block": 16})"});
    BroadcastSweep            sweep(trace, mapper, cfgs, 8);
    std::vector<std::int32_t> seen;
    sweep.run([&](const StreamingTileTrace& t) { seen.push_back(t.window_tile()); });
    CHECK_EQ(check::ssize(seen), std::int64_t{kTiles});
    for (std::int32_t t = 0; t < kTiles; ++t) CHECK_EQ(seen[static_cast<std::size_t>(t)], t);
}

}  // namespace

int main() {
    test_broadcast_lockstep_equals_running_each_config_alone();
    test_the_three_configs_are_not_the_same_machine();
    test_step_tile_advances_exactly_one_tile();
    test_a_mixed_layout_grid_is_rejected();
    test_a_grid_that_changes_the_mapper_class_is_rejected();
    test_a_layout_the_mapper_does_not_serve_is_rejected();
    test_max_engines_is_enforced_at_construction();
    test_the_window_never_holds_more_than_one_tile();
    test_the_tile_observer_sees_every_tile_once();
    return check::summary();
}
