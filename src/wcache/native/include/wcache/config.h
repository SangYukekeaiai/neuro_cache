// RunConfig: the one authoritative definition of the sweepable parameter set.
//
// Every knob a sweep may vary is declared here exactly once, with its default
// as a member initializer. Nothing else in the tree may carry a second copy of
// a default: the CLI, the sweep grid and the Slurm scripts all reach a value by
// parsing a config through this file, so changing a default means editing this
// struct and nothing else. LevelParams and EngineParams have defaults of their
// own, but they are the engine's constructor preconditions and are always
// overwritten by to_engine_params, so they are not a second source.
//
// The derived geometry is deliberately computed rather than declared: a config
// that stated both a line size and its factors could state them inconsistently.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "wcache/cache_level.h"
#include "wcache/engine.h"
#include "wcache/layout.h"
#include "wcache/prefetcher.h"
#include "wcache/stamp_policy.h"

namespace wcache {

struct RunConfig {
    // --- layout, which fixes line_size_bytes = cin_block*cout_block*weight_bytes
    std::int32_t cin_block    = 1;
    std::int32_t cout_block   = 16;
    std::int32_t weight_bytes = 1;
    LayoutKind   layout       = LayoutKind::BlockPack;

    // Under `split_cin`, the radix of the innermost CIN digit, which is what
    // the L1 set index becomes. -1 means "the default, l1_num_sets()", and
    // validate() resolves it, for l1_demand_reserve's reason: the value is a
    // number the layout alone does not carry.
    //
    // It resolves ONLY under split_cin. Under block_pack the sentinel is the
    // only value the field accepts, so a block_pack row reports -1 and says in
    // its own cell that no split happened. Resolving it under both would put a
    // width in the CSV that the run never used, and two rows measuring
    // different things would then look configured the same way.
    std::int64_t cin_lo_blocks = -1;

    // --- geometry
    std::int64_t l1_size_bytes = 8 * 1024;
    std::int32_t l1_assoc      = 8;
    std::int64_t l2_size_bytes = 512 * 1024;
    std::int32_t l2_assoc      = 16;
    PolicyKind   policy        = PolicyKind::LRU;

    // The L2's policy, when it differs from `policy`. Defaults to a sentinel
    // meaning "same as `policy`", so every existing config is unchanged and no
    // committed result moves. Split from `policy` for Belady, which is an
    // offline bound worth measuring at one level while the other stays real
    // (plan 0831-belady section 4).
    PolicyKind l2_policy   = PolicyKind::RANDOM;  // RANDOM = "unset, follow `policy`"
    bool       l2_policy_set = false;   // one knob, both levels
    Inclusion    inclusion     = Inclusion::NonInclusive;

    // --- concurrency
    std::int32_t l1_mshrs         = 16;
    std::int32_t l1_tgts_per_mshr = 20;
    std::int32_t l2_mshrs         = 20;
    std::int32_t l2_tgts_per_mshr = 12;
    // -1 means "the default, the trace's maximum burst span in lines", resolved by
    // validate(). A sentinel rather than an optional, because a config that
    // DECLARES 0 and a config that omits the field must not be the same config.
    std::int32_t l1_demand_reserve = -1;

    // --- timing
    std::int64_t l1_latency       = 0;
    std::int64_t l1_ii            = 1;
    std::int64_t l2_latency       = 10;
    std::int64_t l2_to_l1_latency = 0;
    std::int64_t l2_miss_latency  = 100;
    std::int32_t l2_banks         = 1;
    std::int64_t l2_ii            = 1;
    std::int64_t dram_ii          = 1;
    std::int64_t core_accept_ii   = 1;

    // --- prefetch
    PrefetchKind prefetch_policy   = PrefetchKind::None;
    std::int32_t prefetch_distance = 0;

    std::int64_t line_size_bytes() const;
    std::int64_t l1_num_lines() const;
    std::int64_t l1_num_sets() const;
    std::int64_t l2_num_lines() const;
    std::int64_t l2_num_sets() const;
};

// A validation finding. Warnings are RETURNED rather than printed, so the caller
// decides where they go: a run puts them on stderr, a sweep folds them into a
// column, and a test reads them without capturing a stream.
struct Warning {
    std::string code;
    std::string message;
};

// Parses a flat JSON object. Every field is optional and falls back to the
// struct's default above. An UNKNOWN key is an ERROR, not a warning: a typo in a
// swept knob that loads silently is a run that measures the default while
// claiming to measure the sweep. `l2_demand_reserve` is rejected by name with
// its own message, since a knob that was removed must not load quietly.
//
// Throws std::invalid_argument, naming the byte offset, on anything outside the
// accepted subset: one object, string keys, and integer or string values.
RunConfig parse_config(const std::string& json_text);

// Parses a sweep GRID, in either of the two accepted forms:
//
//   1. An ARRAY of complete configurations, used verbatim and in order:
//        [ {...}, {...} ]
//
//   2. An OBJECT with `base` and `axes`, expanded to the full cross product
//      with the FIRST declared axis varying SLOWEST, so the row order of a
//      grid file is stable and readable:
//        {"base": {"cout_block": 16},
//         "axes": {"l1_size_bytes": [2048, 4096], "prefetch_distance": [0, 2]}}
//      gives four configurations in the order (2048,0) (2048,2) (4096,0)
//      (4096,2). An axis naming a key `base` does not carry is still legal:
//      `base` is a partial config and every key falls back to the defaults
//      above. An axis with no values leaves an empty grid.
//
// Every object in either form is read by parse_config's own reader and key
// table, so a knob is declared in exactly one place and an unknown key, a
// duplicate key or a wrong value type is refused identically in both
// documents. Throws std::invalid_argument naming the byte offset.
std::vector<RunConfig> parse_config_grid(const std::string& json_text);

// Checks every rule and RESOLVES l1_demand_reserve from `lines_per_burst` when
// it is the -1 sentinel. `lines_per_burst` is the trace's MAXIMUM burst span under
// this config's layout, which is the right size for a reserve, and is supplied by
// the caller from the stream header, so
// validation is not possible before that header is read.
//
// Throws std::invalid_argument, naming the offending field and the rule, on any
// rejection. Appends to `warnings` on any warning.
void validate(RunConfig& cfg, std::int32_t lines_per_burst,
              std::vector<Warning>& warnings);

// The engine's knobs, from a validated config. Precondition: validate() has run,
// enforced by throwing when l1_demand_reserve is still the sentinel.
EngineParams to_engine_params(const RunConfig& cfg);

}  // namespace wcache
