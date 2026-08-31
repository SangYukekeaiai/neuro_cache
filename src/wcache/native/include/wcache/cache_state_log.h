// CacheStateLog: every change to the contents of an array, in time order.
//
// This instrument answers one question and no other: WHAT IS IN THE CACHE, and
// when did that change. One row per slot transition, at both levels, with the
// event time that caused it.
//
// It is deliberately NOT a line life-cycle view. `LineTrace` is that, and the
// two are kept in separate files because they are read for different reasons: a
// state log is read down its `set` column, looking for a set that thrashes, and
// a life-cycle table is read down its `hits` column, looking for reuse that
// never happens. Interleaved, neither is scannable.
//
// A DEBUGGING instrument, not a measurement. No counter and no CSV column of
// the results row is derived from it, and an engine with no log attached pays
// one null check per site.
//
// The array's contents change at exactly three places, and each is a row here:
//
//   fill        a line was installed into a way
//   evict       a line was displaced by an install into its way
//   invalidate  a line was back-invalidated out of an L1 (inclusive only)
//
// An install that displaces a line writes BOTH an `evict` and a `fill`, in that
// order and at the same time, because that is what the slot did.
#pragma once

#include <cstdint>
#include <ostream>
#include <string>
#include <vector>

#include "wcache/mshr.h"
#include "wcache/types.h"

namespace wcache {

class CacheStateLog {
public:
    // `out` must outlive the log. `core` is -1 for every core. `max_rows` is -1
    // for unbounded. The two set counts size the occupancy counters, which are
    // what lets a row report how full its set is WITHOUT walking the ways: the
    // array has no slot-to-line accessor, and adding one for a debugging aid
    // would widen an interface the engine is written against.
    CacheStateLog(std::ostream& out, std::int32_t n_cores, std::int64_t l1_sets,
                  std::int64_t l2_sets, std::int32_t l1_assoc, std::int32_t l2_assoc,
                  std::int32_t core, std::int32_t tile, std::int64_t max_rows)
        : out_(&out),
          n_cores_(n_cores),
          l1_sets_(l1_sets),
          l2_sets_(l2_sets),
          l1_assoc_(l1_assoc),
          l2_assoc_(l2_assoc),
          core_(core),
          tile_(tile),
          max_rows_(max_rows),
          l1_used_(static_cast<std::size_t>(n_cores) * static_cast<std::size_t>(l1_sets), 0),
          l2_used_(static_cast<std::size_t>(l2_sets), 0) {}

    void write_header() {
        *out_ << "# wcache cache-state log: one row per slot transition.\n"
              << "# L1 " << l1_sets_ << " sets x " << l1_assoc_ << " ways, private per core.\n"
              << "# L2 " << l2_sets_ << " sets x " << l2_assoc_ << " ways, shared.\n"
              << "# core is -1 on an L2 row: the L2 is shared and its slots belong to no core.\n"
              << "# ways_used is the occupancy of THAT set at THAT level after this row.\n"
              << "# filters: core " << core_ << ", tile " << tile_
              << " (-1 means no filter).\n"
              << "# Read with pandas.read_csv(path, comment='#').\n"
              << "time,tile,level,core,set,way,action,line,tag,ways_used\n";
    }

    // `way` is -1 when the caller could not determine it, which no current site
    // does; it is accepted rather than asserted so a future site is not forced
    // to invent one.
    void record(const char* action, SimTime now, std::int32_t tile, Level level,
                std::int32_t core, LineId line, SetIndex set, TagId tag, std::int32_t way) {
        // The occupancy counter is bumped BEFORE the filter, and that ordering
        // is the whole correctness of the column: a set's occupancy is a fact
        // about the array, not about the rows a filter kept. Bumped after the
        // filter, a tile-0 file would report every set as empty because the
        // fills that populated it were dropped.
        const std::int32_t used = bump(action, level, core, set);
        if (!wants(core, tile)) return;
        ++written_;
        *out_ << now.get() << ',' << tile << ',' << (level == Level::L1 ? "l1" : "l2") << ','
              << core << ',' << set.get() << ',' << way << ',' << action << ','
              << line.get() << ',' << tag.get() << ',' << used << '\n';
    }

    bool wants(std::int32_t core, std::int32_t tile) const {
        if (max_rows_ >= 0 && written_ >= max_rows_) return false;
        if (core_ >= 0 && core >= 0 && core != core_) return false;
        return !(tile_ >= 0 && tile >= 0 && tile != tile_);
    }

    std::int64_t written() const { return written_; }
    bool truncated() const { return max_rows_ >= 0 && written_ >= max_rows_; }

private:
    // The occupancy of one set, maintained here rather than read off the array.
    // A `fill` raises it and the other two lower it, so it is exact as long as
    // the three verbs are the only transitions -- which is the same claim the
    // header comment makes, checked by the fact that a negative would trip the
    // clamp below.
    std::int32_t bump(const char* action, Level level, std::int32_t core, SetIndex set) {
        std::int32_t* cell = nullptr;
        if (level == Level::L1) {
            if (core < 0 || core >= n_cores_ || set.get() < 0 || set.get() >= l1_sets_) return -1;
            cell = &l1_used_[static_cast<std::size_t>(core) * static_cast<std::size_t>(l1_sets_) +
                             static_cast<std::size_t>(set.get())];
        } else {
            if (set.get() < 0 || set.get() >= l2_sets_) return -1;
            cell = &l2_used_[static_cast<std::size_t>(set.get())];
        }
        if (action[0] == 'f') ++*cell;          // fill
        else if (*cell > 0) --*cell;            // evict, invalidate
        return *cell;
    }

    std::ostream* out_;
    std::int32_t  n_cores_;
    std::int64_t  l1_sets_;
    std::int64_t  l2_sets_;
    std::int32_t  l1_assoc_;
    std::int32_t  l2_assoc_;
    std::int32_t  core_;
    std::int32_t  tile_;
    std::int64_t  max_rows_;
    std::int64_t  written_ = 0;
    std::vector<std::int32_t> l1_used_;
    std::vector<std::int32_t> l2_used_;
};

}  // namespace wcache
