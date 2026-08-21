// RunStats and the results CSV schema. Plan D unit D2c, Task 13.
//
// One row per (arm, arch, n_cores, workload, layer, sample_idx, config). The
// column list is stated once, in `csv_columns()`, and both the header line and
// every row are built from it, so a schema that drifted from its own header
// would be a test failure rather than a silent join break downstream.
//
// The invariants are checked HERE and not only in a test, because a sweep row
// that violates them must fail loudly instead of being written into a CSV that
// an analysis will later average.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "wcache/config.h"
#include "wcache/engine.h"
#include "wcache/stream_format.h"

namespace wcache {

// The identity a row carries that neither the engine nor the trace knows.
struct RowIdentity {
    std::string run_id;
    std::string git_commit;
    std::string arm = "cache";  // spad_oracle | spad_wcache | spad_nocsim | cache
    std::string tier;
};

// The columns, in order. A function-local static, initialised from one brace
// list, so there is exactly one statement of the schema in the tree.
//
// NOTE for the coordinator: the plan's prose once said "91 columns" while the
// ordered list it calls normative had 90, and 90 is what was pinned. The list
// is 91 now, and the 91st column is named and defined: `stall_l1_port`, the
// bucket V21's partition was missing (see `StallCause`).
const std::vector<std::string>& csv_columns();

// The columns joined by commas, with no trailing newline.
std::string csv_header();

// Collects one row.
//
// `total_cycles` is the layer makespan, `engine.tile_origin(trace.n_tiles())`:
// `tile_origin` is sized n_tiles + 1 and its last entry is the end of the run.
// `tick_base_total` comes from the TRACE, which the engine deliberately never
// sees (Part 5: "the engine never uses tick_base"), which is what makes
// `stretch_cycles = total_cycles - tick_base_total` an independent measurement
// rather than a restatement.
//
// `padding_fraction` is supplied by the caller because it is a property of the
// layout and the trace rather than of the run. Its definition is
//
//     (lines_touched * elements_per_line - distinct_elements_touched)
//     / (lines_touched * elements_per_line)
//
// with `elements_per_line = cin_block * cout_block`: the fraction of the weight
// elements pulled into L1 that no burst ever consumed. Equivalently, in bytes,
// 1 - (distinct bytes consumed / total bytes fetched), since every element is
// `weight_bytes` wide. §3.3 says it must be 0 for all four chosen layers, which
// divide exactly, so a nonzero value on them means the address mapper is wrong.
//
// `distinct_p50` and `distinct_max` are DistinctAddressHistogram's summary of
// G14 (hist.h), which under ruling R6 is explanatory and gates nothing.
//
// The constructor reduces everything it is given into the finished cells; it
// holds no reference to `es`, `cfg` or `hdr` past its own body.
class RunStats {
public:
    RunStats(const RowIdentity& id, const RunConfig& cfg, const stream::StreamHeader& hdr,
             const EngineStats& es, std::int64_t total_cycles, std::int64_t tick_base_total,
             double padding_fraction, double sim_wall_seconds, std::int32_t distinct_p50,
             std::int32_t distinct_max);

    // One CSV line, no trailing newline, fields in csv_columns() order.
    // Integers print exactly, doubles with "%.6f", and a ratio with a zero
    // denominator prints as the EMPTY string rather than as a NaN, because NaN
    // is not portable across CSV readers.
    std::string csv_row() const;

    // Throws std::logic_error, naming both sides, on:
    //
    //   V21   the eight stall causes must sum to `stall_total`, at every
    //         `l1_latency` and every `l1_ii`. There is no precondition and no
    //         legal remainder: an L1 hit that was never refused still waited for
    //         the L1 port, which is `stall_l1_port`.
    //   R8    `hidden_latency = fetch_latency_sum - core_stall_sum >= 0`, which
    //         the line anchor makes structural.
    //   4.6   the four prefetch outcomes plus the five drop reasons sum to
    //         `pf_issued`.
    void check_invariants() const;

private:
    std::vector<std::string> cells_;

    // What check_invariants() judges, kept as numbers rather than re-parsed out
    // of the cells.
    std::int64_t stall_causes_    = 0;  // the eight, summed
    std::int64_t stall_total_     = 0;
    std::int64_t hidden_latency_  = 0;
    std::int64_t pf_issued_       = 0;
    std::int64_t pf_accounted_    = 0;
};

// The spad_oracle arm: a row whose `total_cycles` IS `tick_base_total`, with
// every simulated column empty. §2 says the arm costs nothing, and this is why:
// no engine is constructed and no cache is modelled. The identity and the
// configuration are still reported, because an oracle row has to join to its
// cache rows on the same keys.
std::string oracle_row(const RowIdentity& id, const RunConfig& cfg,
                       const stream::StreamHeader& hdr, std::int64_t tick_base_total);

}  // namespace wcache
