// BarrierLog: one row per (tile, core) at every tile barrier.
//
// This instrument answers one question and no other: WHICH CORE ENDS EACH
// TILE, and what its time went to by then. The results row sums every per-core
// counter over cores and the whole run, so "the slowest core is the same one
// every tile" and "the slowest core rotates" produce the same CSV; this file
// is the difference between them.
//
// A DEBUGGING instrument, not a measurement, exactly as the two in
// cache_state_log.h and line_trace.h: no counter and no CSV column of the
// results row is derived from it, and an engine with no log attached pays one
// null check per site.
//
// Each row carries the core's ARRIVAL at the barrier and the tile's END, so
// `tile_end - arrival` is the slack the engine charges to `stall_barrier` at
// that same instant. The stall and fetch counters are the engine's own
// per-core accumulators, snapshotted CUMULATIVE at the barrier; a reader
// diffs consecutive rows of one core to get the per-tile share. They are
// written cumulative rather than diffed here because the engine does not keep
// per-tile copies and this log must not make it.
//
// The four l2_* columns are counted HERE, from one call at the L2 probe,
// because the engine keeps no per-core L2 counters: l2_demand counts demand
// probes (re-probes after a refusal included, as l2_accesses counts them) and
// l2_l1pf counts probes by L1 prefetches, each with its hits beside it. Also
// cumulative.
#pragma once

#include <cstdint>
#include <ostream>
#include <vector>

#include "cachesim/types.h"

namespace cachesim {

class BarrierLog {
public:
    // `out` must outlive the log. `n_cores` sizes the probe counters.
    BarrierLog(std::ostream& out, std::int32_t n_cores)
        : out_(&out), counts_(static_cast<std::size_t>(n_cores)) {}

    void write_header() {
        *out_ << "# wcache barrier log: one row per (tile, core), written when the tile's\n"
              << "# barrier resolves. arrival is the core's own arrival, tile_end the\n"
              << "# barrier, so tile_end - arrival is this tile's stall_barrier share.\n"
              << "# Every column from core_stall rightward is CUMULATIVE since the start\n"
              << "# of the run; diff consecutive rows of one core for the per-tile share.\n"
              << "# l2_demand / l2_l1pf count L2 probes by demands and by L1 prefetches\n"
              << "# for this core, each beside its hits.\n"
              << "# Read with pandas.read_csv(path, comment='#').\n"
              << "tile,core,arrival,tile_end,core_stall,fetch_latency,stall_l1_slot,"
                 "stall_l1_line,stall_l1_port,stall_l2_slot,stall_l2_line,stall_l2_port,"
                 "stall_channel,l2_demand,l2_demand_hits,l2_l1pf,l2_l1pf_hits\n";
    }

    // One L2 probe by `core`: a demand (`demand`) or an L1 prefetch (not an
    // L2-originated one; the caller filters those, since they belong to no
    // burst a core waits on).
    void observe_l2(CoreId core, bool demand, bool hit) {
        Counts& c = counts_.at(static_cast<std::size_t>(core.get()));
        if (demand) {
            ++c.demand;
            if (hit) ++c.demand_hits;
        } else {
            ++c.l1pf;
            if (hit) ++c.l1pf_hits;
        }
    }

    // Called from the barrier, once per core, with the engine's own cumulative
    // per-core accumulators.
    void record(std::int32_t tile, std::int32_t core, SimTime arrival, SimTime tile_end,
                std::int64_t core_stall, std::int64_t fetch_latency, std::int64_t l1_slot,
                std::int64_t l1_line, std::int64_t l1_port, std::int64_t l2_slot,
                std::int64_t l2_line, std::int64_t l2_port, std::int64_t channel) {
        const Counts& c = counts_.at(static_cast<std::size_t>(core));
        ++written_;
        *out_ << tile << ',' << core << ',' << arrival.get() << ',' << tile_end.get() << ','
              << core_stall << ',' << fetch_latency << ',' << l1_slot << ',' << l1_line << ','
              << l1_port << ',' << l2_slot << ',' << l2_line << ',' << l2_port << ','
              << channel << ',' << c.demand << ',' << c.demand_hits << ',' << c.l1pf << ','
              << c.l1pf_hits << '\n';
    }

    std::int64_t written() const { return written_; }

private:
    struct Counts {
        std::int64_t demand = 0, demand_hits = 0, l1pf = 0, l1pf_hits = 0;
    };

    std::ostream* out_;
    std::vector<Counts> counts_;
    std::int64_t written_ = 0;
};

}  // namespace cachesim
