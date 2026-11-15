#include <cachesim/core/engine.h>
#include <cachesim/prefetch/next_access.h>
#include <cachesim/trace/byte_source.h>
#include <cachesim/trace/stream_trace.h>
#include "check.h"
#include "engine_fixture.h"
#include "stream_builder.h"
using namespace cachesim;

void single_empty() {
    fx::StreamBuilder b(1, 2);
    b.begin_tile(0, 0); b.end_tile();
    const auto bytes = b.finish(); MemByteSource src(bytes); StreamingTileTrace tr(src);
    fx::LinearMapper map(64); Engine e(map, tr, fx::unbounded_params());
    CHECK_TRUE(tr.advance());
    CHECK_EQ(tr.tile_tail(0), LocalTick{0}); CHECK_EQ(tr.tick_base(1), std::int64_t{0});
    CHECK_EQ(e.run_to_barrier(), 0);
    CHECK_TRUE(!tr.advance()); e.finish();
    CHECK_EQ(e.tile_origin(1), SimTime{0}); CHECK_EQ(e.stats().l1_accesses, std::int64_t{0});
}

struct Result { std::int64_t cycles, accesses, pf, events; };
Result boundaries(int empties) {
    fx::StreamBuilder b(empties+2, 2);
    b.begin_tile(0, 3); b.begin_core(0);
    b.add_burst(0,0,0,0,0,1); b.add_burst(1,0,0,0,1,2); b.end_tile();
    for(int t=1;t<=empties;++t) { b.begin_tile(t,0); b.end_tile(); }
    b.begin_tile(empties+1,3); b.begin_core(0);
    b.add_burst(0,0,0,0,2,3); b.add_burst(1,0,0,0,3,4); b.end_tile();
    const auto bytes=b.finish(); MemByteSource src(bytes); StreamingTileTrace tr(src);
    fx::LinearMapper map(64); auto p=fx::unbounded_params();
    p.prefetch_policy=PrefetchKind::NextAccess; p.prefetch_distance=1;
    Engine e(map,tr,p);
    int tile=0;
    while(tr.advance()) {
        CHECK_EQ(e.run_to_barrier(),tile);
        auto& pf=dynamic_cast<NextAccessPrefetcher&>(e.l1(CoreId{0}).prefetcher());
        if(tile>=1 && tile<=empties) {
            CHECK_EQ(tr.tick_base(tile),std::int64_t{3});
            CHECK_EQ(tr.tick_base(tile+1),std::int64_t{3});
            CHECK_EQ(e.tile_origin(tile),e.tile_origin(1));
            CHECK_EQ(pf.pf_cursor(CoreId{0}),BurstIndex{0});
        } else CHECK_EQ(pf.pf_cursor(CoreId{0}),BurstIndex{2});
        ++tile;
        CHECK_TRUE(tile<=empties+2);
    }
    e.finish(); CHECK_EQ(tile,empties+2);
    for(int t=1;t<=empties;++t) CHECK_EQ(e.tile_origin(t+1),e.tile_origin(1));
    return {e.tile_origin(tile).get(),e.stats().l1_accesses,e.stats().pf_issued,e.stats().events};
}

void malformed() {
    for(int mutation=0;mutation<5;++mutation) {
        fx::StreamBuilder b(1,2);
        b.begin_tile(0,mutation==0 ? -1 : mutation==4 ? 1 : 0);
        if(mutation==1) b.set_core_block_bias(1);
        if(mutation==2) b.set_payload_bias(1);
        if(mutation>=3) {
            b.begin_core(0); b.add_burst(mutation==4 ? 1 : 0,0,0,0,0,1);
        }
        b.end_tile();
        const auto bytes=b.finish(); MemByteSource src(bytes); StreamingTileTrace tr(src);
        CHECK_THROWS(std::runtime_error,tr.advance());
    }
}
int main() {
    single_empty(); malformed();
    const auto base=boundaries(0), inserted=boundaries(4);
    CHECK_EQ(inserted.cycles,base.cycles); CHECK_EQ(inserted.accesses,std::int64_t{4});
    CHECK_EQ(inserted.accesses,base.accesses); CHECK_EQ(base.pf,std::int64_t{2});
    CHECK_EQ(inserted.pf,base.pf); CHECK_EQ(inserted.events,base.events+4);
    return check::summary();
}
