// AccessLog: the demand reference stream, in time order, as fixed-width binary.
//
// Plan unit U2 of log/2026-08-31-reuse-distance-plan.md.
//
// This instrument answers one question and no other: WHICH LINE was referenced,
// at which level, by which core, and in what order. It computes nothing. The
// reuse-distance analysis that consumes it lives entirely outside the engine, in
// profiling/0831_reuse_distance/, and that split is deliberate: a stack-distance
// tree inside the engine would put a second stateful data structure next to the
// caches for no gain, while a dumper leaves the engine with one more write and
// nothing to be wrong about.
//
// It is the THIRD debugging instrument, alongside `CacheStateLog` and
// `LineTrace`, and it is separate from both for the reason they are separate
// from each other: a state log says what is IN a cache, an episode table says
// what happened TO a line, and this says what was ASKED FOR. None is derivable
// from the others. In particular neither existing instrument records hits at
// all, so neither can reconstruct a reference sequence.
//
// A DEBUGGING instrument, not a measurement. No counter and no CSV column of the
// results row is derived from it, and an engine with no log attached pays one
// null check per site.
//
// WHAT COUNTS AS A REFERENCE. Exactly what `l1_accesses` and `l2_accesses`
// count, because the two sites are the same site: a DEMAND probe at that level.
// A prefetch is excluded, matching the rule that a prefetch is not a use and
// does not touch LRU order (I15, decision B11). Writing the record beside the
// counter rather than near it is what makes the histogram's total equal the
// results row's access count by construction rather than by coincidence (V1).
//
// RE-TRIAGE. `l1_accesses` counts probes, which a refused request repeats, so a
// blocking configuration emits one record per probe and not one per reference.
// That is the honest thing for this file to do, since it reports what the array
// was asked and nothing more. Measured at the 0831 best config: `max_wait_depth`
// is 0 on all four layers, so nothing blocks, nothing re-triages, and the two
// readings coincide. The consumer asserts that rather than assuming it.
//
// SIZE. Eight bytes per record. The widest run in the 0831 corpus is V9 at
// 4,995,072 L1 references, so 40 MB; the whole corpus is under 450 MB and the
// driver deletes each log once consumed. Binary rather than CSV because CSV is
// roughly five times larger and slower to parse, and the consumer can dump a
// readable slice on demand when something looks wrong.
#pragma once

#include <cstdint>
#include <cstdio>
#include <ostream>
#include <stdexcept>
#include <vector>

// For `Level`, which lives in mshr.h. Included here rather than left to the
// caller: this header compiled only because every existing includer happened to
// reach mshr.h first, and app_support.h, which does not, found that out.
#include "wcache/mshr.h"
#include "wcache/types.h"

namespace wcache {

// One reference. Eight bytes, laid out so the natural alignment gives exactly
// eight with no padding the writer has to reason about.
//
// `line` is 32 bits, which is not a guess: a line id is bounded by the layer's
// weight set in lines, 36,864 at the widest layer of the 0831 corpus. The
// constructor checks the bound rather than truncating silently.
struct AccessRecord {
    std::uint8_t  level;  // 0 = L1, 1 = L2
    std::uint8_t  core;
    std::uint8_t  demand;  // always 1 today; a byte kept so the reader never guesses
    std::uint8_t  pad;
    std::uint32_t line;
};
static_assert(sizeof(AccessRecord) == 8, "AccessRecord must be exactly 8 bytes");

class AccessLog {
public:
    // `out` must outlive the log and must be opened in BINARY mode. Not owned.
    explicit AccessLog(std::ostream& out) : out_(&out) { buf_.reserve(kBatch); }

    ~AccessLog() { flush(); }

    AccessLog(const AccessLog&)            = delete;
    AccessLog& operator=(const AccessLog&) = delete;

    // A magic number and a version, so a truncated or stale log is caught by the
    // reader rather than silently decoded as garbage. Written once, before any
    // record.
    void write_header() {
        const std::uint64_t magic = kMagic;
        out_->write(reinterpret_cast<const char*>(&magic), sizeof(magic));
    }

    // Called at the two sites that increment `l1_accesses` and `l2_accesses`,
    // under the same `r.demand` guard, so the count here and the count there
    // cannot diverge.
    void observe(Level level, CoreId core, LineId line) {
        const std::int64_t id = line.get();
        if (id < 0 || id > kMaxLine) {
            // A line id outside 32 bits means the corpus outgrew this record and
            // the file would be silently wrong. Refusing is the only safe
            // outcome, and it is checked rather than assumed because a truncated
            // id decodes as a perfectly plausible different line.
            throw std::out_of_range("AccessLog::observe: line id " + std::to_string(id) +
                                    " does not fit the 32-bit record field");
        }
        const std::int32_t c = core.get();
        if (c < 0 || c > kMaxCore) {
            // Checked for the same reason the line id above is, and it became
            // worth checking when the per-core L1 oracles arrived: those are
            // built by splitting this file on the core field, so a truncated id
            // folds core 256's references into core 0's oracle and the run gets
            // a future that belongs to another core. policy.h:116 gives the
            // design range as 8 to 256 cores, which puts 256 exactly here.
            throw std::out_of_range("AccessLog::observe: core id " + std::to_string(c) +
                                    " does not fit the 8-bit record field");
        }
        AccessRecord r;
        r.level  = level == Level::L1 ? std::uint8_t{0} : std::uint8_t{1};
        r.core   = static_cast<std::uint8_t>(c);
        r.demand = 1;
        r.pad    = 0;
        r.line   = static_cast<std::uint32_t>(id);
        buf_.push_back(r);
        if (buf_.size() >= kBatch) flush();
        ++n_;
    }

    std::int64_t records() const { return n_; }

    void flush() {
        if (buf_.empty()) return;
        out_->write(reinterpret_cast<const char*>(buf_.data()),
                    static_cast<std::streamsize>(buf_.size() * sizeof(AccessRecord)));
        buf_.clear();
    }

    static constexpr std::uint64_t kMagic   = 0x5743414C4F473031ULL;  // "WCALOG01"
    static constexpr std::int64_t  kMaxLine = 0xFFFFFFFF;
    static constexpr std::int32_t  kMaxCore = 0xFF;

private:
    // Batched because the alternative is one ostream::write per reference across
    // 55M references, which is the difference between seconds and minutes.
    static constexpr std::size_t kBatch = 1 << 16;

    std::ostream*             out_;
    std::vector<AccessRecord> buf_;
    std::int64_t              n_ = 0;
};

}  // namespace wcache
