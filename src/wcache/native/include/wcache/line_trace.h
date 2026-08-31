// LineTrace: one row per RESIDENCY EPISODE of a cache line.
//
// This instrument answers one question and no other: what happened to a line
// between the moment it entered a cache and the moment it left. An episode is
// that whole span, so a line fetched, hit twice and evicted is ONE row carrying
// both hits, and the same line fetched again later is a SECOND row. That is
// what makes reuse legible: a table of episodes whose `hits` column is zero
// everywhere is a cache doing no reuse at all, and it says so in one column
// rather than in a hit rate that has to be reasoned back to a cause.
//
// It is deliberately NOT a state log. `CacheStateLog` is that, and the two live
// in separate files because they are read differently: a state log is read down
// its `set` column in time order, an episode table is read down its `hits` and
// `residency` columns and sorts fine by any of them.
//
// A DEBUGGING instrument, not a measurement. No results column is derived from
// it, and an engine with no trace attached pays one null check per site.
//
// MEMORY. Open episodes are bounded by what the caches can hold -- an episode
// opens on a fill and closes on the eviction of that same slot -- so the map
// below cannot exceed `n_cores * l1_lines + l2_lines` entries however long the
// run is. That bound is why this is a map and not a bounded ring buffer.
#pragma once

#include <algorithm>
#include <cstdint>
#include <ostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "wcache/mshr.h"
#include "wcache/types.h"

namespace wcache {

class LineTrace {
public:
    // `out` must outlive the trace.
    //
    // `want_l1` / `want_l2` select the levels, and the default is L1 ONLY. The
    // question this table is kept for is per-core reuse; an L1 episode and an L2
    // episode for the same line are filled at the SAME instant and differ only
    // in how long they survive, so carrying both doubles the file and
    // interleaves two populations whose residencies are not comparable. The
    // L2's own side of that story is in the cache-state log, which keeps both
    // levels, so nothing is lost by leaving it out here.
    //
    // `core` is -1 for every core, `tile` -1 for every tile, `line` -1 for every
    // line, `max_rows` -1 for unbounded. `tile` matches the tile the episode was
    // FILLED in, and keeps each episode whole: one filled in tile 0 that
    // survives into tile 5 reports its real ending time, because a residency is
    // one thing and cutting it at a tile boundary would report a shorter life
    // than the line had.
    //
    // Every filter is applied AT THE FILL, so an episode either exists or does
    // not; a hit on an untracked line finds no episode and is ignored rather
    // than opening a partial one. Filtering at emission instead would leave the
    // map holding every line in both caches in order to throw most of it away.
    LineTrace(std::ostream& out, bool want_l1, bool want_l2, std::int32_t core,
              std::int32_t tile, std::int64_t line, std::int64_t max_rows)
        : out_(&out),
          want_l1_(want_l1),
          want_l2_(want_l2),
          core_(core),
          tile_(tile),
          line_(line),
          max_rows_(max_rows) {}

    void write_header() {
        *out_ << "# wcache line trace: one row per residency episode.\n"
              << "# An episode runs from the fill that installed a line to the eviction,\n"
              << "# invalidation, or end of run that removed it.\n"
              << "# levels: " << (want_l1_ ? "l1" : "") << (want_l1_ && want_l2_ ? "+" : "")
              << (want_l2_ ? "l2" : "") << ".\n";
        // Said only when an l2 row can actually appear. A note explaining a
        // column value the file cannot contain is a reader wondering which rows
        // it applies to.
        if (want_l2_) {
            *out_ << "# core is -1 on an l2 row: the L2 is shared and its lines belong to\n"
                     "# no core.\n";
        }
        *out_
              << "# first_request is when the MSHR entry for this fill was opened, so\n"
              << "# filled_at - first_request is the fetch this episode waited on.\n"
              << "# hits counts probes that HIT this line while it was resident; demand_hits\n"
              << "# is the subset that were demands rather than prefetches.\n"
              << "#\n"
              << "# ROW ORDER IS ended_at, NOT first_request. A row is written when the\n"
              << "# episode CLOSES, because residency, hits and ended_by are not known until\n"
              << "# then, so the file cannot be in fill order. Under LRU the two orders differ\n"
              << "# by design: the line evicted first is the one used least recently, not the\n"
              << "# one fetched first. Sort by first_request or filled_at to read it in\n"
              << "# request order (to_txt.py --sort first_request does this).\n"
              << "# filters: core " << core_ << ", fill_tile " << tile_ << ", line "
              << line_ << " (-1 means no filter).\n"
              << "# Read with pandas.read_csv(path, comment='#').\n"
              << "level,core,line,set,tag,fill_tile,first_request,filled_at,ended_at,"
                 "residency,hits,demand_hits,opened_by,ended_by\n";
    }

    void on_fill(SimTime now, std::int32_t tile, Level level, std::int32_t core, LineId line,
                 SetIndex set, TagId tag, SimTime first_request, bool pf_opened) {
        if (!(level == Level::L1 ? want_l1_ : want_l2_)) return;
        if (core_ >= 0 && core >= 0 && core != core_) return;
        if (tile_ >= 0 && tile >= 0 && tile != tile_) return;
        if (line_ >= 0 && line.get() != line_) return;
        Episode ep;
        ep.tile          = tile;
        ep.set           = set.get();
        ep.tag           = tag.get();
        ep.first_request = first_request.get();
        ep.filled_at     = now.get();
        ep.pf_opened     = pf_opened;
        open_[key(level, core, line)] = ep;
    }

    void on_hit(Level level, std::int32_t core, LineId line, bool demand) {
        auto it = open_.find(key(level, core, line));
        if (it == open_.end()) return;
        ++it->second.hits;
        if (demand) ++it->second.demand_hits;
    }

    // Closes the episode and writes its row. A line with no open episode is one
    // the filters excluded, and is silently nothing.
    void on_leave(SimTime now, Level level, std::int32_t core, LineId line, const char* why) {
        auto it = open_.find(key(level, core, line));
        if (it == open_.end()) return;
        emit(level, core, line, it->second, now.get(), why);
        open_.erase(it);
    }

    // Every episode still open at the end of the run, so the table accounts for
    // every fill rather than silently dropping whatever was resident when the
    // clock stopped.
    //
    // SORTED before emission, and that is not tidiness. `open_` is an
    // unordered_map, so iterating it directly would put these rows in an
    // unspecified order: two runs of the same configuration, or one run under
    // two compilers, would produce files that differ in their tail while
    // describing an identical run. Every row above this point is already in a
    // total order (`ended_at`, since a row is written when its episode closes),
    // so sorting on the same key is what extends that order over the whole
    // file. The key is the packed (line, core, level), which is unique by
    // construction, so the sort is total and no tie-break is needed.
    void flush(SimTime now) {
        std::vector<std::int64_t> keys;
        keys.reserve(open_.size());
        for (const auto& kv : open_) keys.push_back(kv.first);
        std::sort(keys.begin(), keys.end());
        for (const std::int64_t k : keys) {
            emit(static_cast<Level>(k & 1), static_cast<std::int32_t>(((k >> 1) & 0x3f) - 1),
                 LineId{k >> 7}, open_[k], now.get(), "end_of_run");
        }
        open_.clear();
    }

    std::int64_t written() const { return written_; }
    bool truncated() const { return max_rows_ >= 0 && written_ >= max_rows_; }
    std::size_t still_open() const { return open_.size(); }

private:
    struct Episode {
        std::int32_t tile          = -1;
        std::int64_t set           = -1;
        std::int64_t tag           = -1;
        std::int64_t first_request = 0;
        std::int64_t filled_at     = 0;
        std::int32_t hits          = 0;
        std::int32_t demand_hits   = 0;
        bool         pf_opened     = false;
    };

    // (line, core, level) packed into one int64. The core occupies six bits,
    // biased by one so the L2's -1 fits, which bounds this at 63 cores; the
    // engine's own limit is far lower and a wider machine would trip the
    // encoding here rather than silently aliasing two cores onto one key.
    static std::int64_t key(Level level, std::int32_t core, LineId line) {
        return (line.get() << 7) | (static_cast<std::int64_t>(core + 1) << 1) |
               static_cast<std::int64_t>(level == Level::L2 ? 1 : 0);
    }

    void emit(Level level, std::int32_t core, LineId line, const Episode& ep,
              std::int64_t ended_at, const char* why) {
        if (max_rows_ >= 0 && written_ >= max_rows_) return;
        ++written_;
        *out_ << (level == Level::L1 ? "l1" : "l2") << ',' << core << ',' << line.get() << ','
              << ep.set << ',' << ep.tag << ',' << ep.tile << ',' << ep.first_request << ','
              << ep.filled_at << ',' << ended_at << ',' << (ended_at - ep.filled_at) << ','
              << ep.hits << ',' << ep.demand_hits << ','
              << (ep.pf_opened ? "prefetch" : "demand") << ',' << why << '\n';
    }

    std::ostream* out_;
    bool          want_l1_;
    bool          want_l2_;
    std::int32_t  core_;
    std::int32_t  tile_;
    std::int64_t  line_;
    std::int64_t  max_rows_;
    std::int64_t  written_ = 0;
    std::unordered_map<std::int64_t, Episode> open_;
};

}  // namespace wcache
