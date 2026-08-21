#include "wcache/config.h"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace wcache {
namespace {

// --- the JSON subset ------------------------------------------------------
//
// One flat object, string keys, integer or string values. That is the whole of
// what a config document is, so it is the whole of what this reader accepts.
// Everything else -- floats, booleans, null, comments, trailing commas,
// escapes -- is refused with the byte offset, because a config the reader
// guesses at is a run that measures something nobody asked for.
//
// A sweep GRID is an array of those objects, or a `base` object plus an `axes`
// object of arrays, and it is read by this same reader through the same key
// table below. It deliberately does not get a reader of its own: a second
// reader is a second place a knob can be declared, and a knob that parsed in
// one document and not the other is a sweep that silently measures the
// default. Nesting and arrays are therefore accepted exactly where the grid
// forms put them and nowhere else.

[[noreturn]] void fail(const std::string& what, std::size_t pos) {
    throw std::invalid_argument("config: " + what + " at byte " + std::to_string(pos));
}

struct Value {
    bool         is_string = false;
    std::int64_t number    = 0;
    std::string  text;
};

class Reader {
public:
    explicit Reader(const std::string& text) : s_(text) {}

    void skip_space() {
        while (i_ < s_.size() &&
               (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r')) {
            ++i_;
        }
    }

    bool at(char c) {
        skip_space();
        return i_ < s_.size() && s_[i_] == c;
    }

    void expect(char c) {
        skip_space();
        if (i_ >= s_.size() || s_[i_] != c) {
            fail(std::string("expected '") + c + "'", i_);
        }
        ++i_;
    }

    void expect_end() {
        skip_space();
        if (i_ != s_.size()) fail("trailing text after the object", i_);
    }

    std::size_t pos() const { return i_; }

    std::string read_string() {
        skip_space();
        if (i_ >= s_.size() || s_[i_] != '"') fail("expected a quoted string", i_);
        ++i_;
        const std::size_t start = i_;
        while (i_ < s_.size() && s_[i_] != '"') {
            if (s_[i_] == '\\') fail("escape sequences are not accepted", i_);
            ++i_;
        }
        if (i_ >= s_.size()) fail("unterminated string", start);
        const std::string out = s_.substr(start, i_ - start);
        ++i_;
        return out;
    }

    Value read_value() {
        skip_space();
        if (i_ >= s_.size()) fail("expected a value", i_);
        if (s_[i_] == '"') {
            Value v;
            v.is_string = true;
            v.text      = read_string();
            return v;
        }
        if (s_[i_] != '-' && (s_[i_] < '0' || s_[i_] > '9')) {
            fail("expected an integer or a quoted string", i_);
        }
        const std::size_t start = i_;
        if (s_[i_] == '-') ++i_;
        const std::size_t digits = i_;
        while (i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9') ++i_;
        if (i_ == digits) fail("expected a digit", i_);
        if (i_ < s_.size() && (s_[i_] == '.' || s_[i_] == 'e' || s_[i_] == 'E')) {
            fail("every config value is an integer", i_);
        }
        Value v;
        try {
            v.number = std::stoll(s_.substr(start, i_ - start));
        } catch (const std::out_of_range&) {
            fail("integer out of range", start);
        }
        return v;
    }

private:
    const std::string& s_;
    std::size_t        i_ = 0;
};

// --- the key tables -------------------------------------------------------
//
// One row per knob, pointing at the field RunConfig declares. A key appears
// here and nowhere else, and its default appears in RunConfig and nowhere
// else, so the two halves of a knob each have exactly one home.

struct I32Field {
    const char*  key;
    std::int32_t RunConfig::*member;
};

struct I64Field {
    const char*  key;
    std::int64_t RunConfig::*member;
};

const I32Field kI32Fields[] = {
    {"cin_block", &RunConfig::cin_block},
    {"cout_block", &RunConfig::cout_block},
    {"weight_bytes", &RunConfig::weight_bytes},
    {"l1_assoc", &RunConfig::l1_assoc},
    {"l2_assoc", &RunConfig::l2_assoc},
    {"l1_mshrs", &RunConfig::l1_mshrs},
    {"l1_tgts_per_mshr", &RunConfig::l1_tgts_per_mshr},
    {"l2_mshrs", &RunConfig::l2_mshrs},
    {"l2_tgts_per_mshr", &RunConfig::l2_tgts_per_mshr},
    {"l1_demand_reserve", &RunConfig::l1_demand_reserve},
    {"l2_banks", &RunConfig::l2_banks},
    {"prefetch_distance", &RunConfig::prefetch_distance},
};

const I64Field kI64Fields[] = {
    {"l1_size_bytes", &RunConfig::l1_size_bytes},
    {"l2_size_bytes", &RunConfig::l2_size_bytes},
    {"l1_latency", &RunConfig::l1_latency},
    {"l1_ii", &RunConfig::l1_ii},
    {"l2_latency", &RunConfig::l2_latency},
    {"l2_to_l1_latency", &RunConfig::l2_to_l1_latency},
    {"l2_miss_latency", &RunConfig::l2_miss_latency},
    {"l2_ii", &RunConfig::l2_ii},
    {"dram_ii", &RunConfig::dram_ii},
    {"core_accept_ii", &RunConfig::core_accept_ii},
};

std::int32_t to_i32(const std::string& key, const Value& v, std::size_t pos) {
    if (v.is_string) fail("key \"" + key + "\" takes an integer", pos);
    if (v.number < std::numeric_limits<std::int32_t>::min() ||
        v.number > std::numeric_limits<std::int32_t>::max()) {
        fail("key \"" + key + "\" is out of range", pos);
    }
    return static_cast<std::int32_t>(v.number);
}

std::int64_t to_i64(const std::string& key, const Value& v, std::size_t pos) {
    if (v.is_string) fail("key \"" + key + "\" takes an integer", pos);
    return v.number;
}

const std::string& enum_text(const std::string& key, const Value& v, std::size_t pos) {
    if (!v.is_string) fail("key \"" + key + "\" takes a quoted spelling", pos);
    return v.text;
}

void assign(RunConfig& cfg, const std::string& key, const Value& v, std::size_t pos) {
    // Removed knob, refused by name. Letting it fall through to the
    // unknown-key path would tell a sweeper they mistyped when what actually
    // happened is that the dimension no longer exists.
    if (key == "l2_demand_reserve") {
        fail("key \"l2_demand_reserve\" is a removed knob: the L2 demand reserve was "
             "deleted, so it is not a sweep dimension and must not load",
             pos);
    }

    for (const I32Field& f : kI32Fields) {
        if (key == f.key) {
            cfg.*(f.member) = to_i32(key, v, pos);
            return;
        }
    }
    for (const I64Field& f : kI64Fields) {
        if (key == f.key) {
            cfg.*(f.member) = to_i64(key, v, pos);
            return;
        }
    }

    if (key == "policy") {
        const std::string& t = enum_text(key, v, pos);
        if (t == "lru") {
            cfg.policy = PolicyKind::LRU;
        } else if (t == "fifo") {
            cfg.policy = PolicyKind::FIFO;
        } else if (t == "random") {
            cfg.policy = PolicyKind::RANDOM;
        } else {
            fail("unknown policy \"" + t + "\"", pos);
        }
        return;
    }
    if (key == "inclusion") {
        const std::string& t = enum_text(key, v, pos);
        if (t == "non_inclusive") {
            cfg.inclusion = Inclusion::NonInclusive;
        } else if (t == "inclusive") {
            cfg.inclusion = Inclusion::Inclusive;
        } else if (t == "exclusive") {
            fail("inclusion \"exclusive\" is not modelled and is refused rather than "
                 "downgraded to non_inclusive",
                 pos);
        } else {
            fail("unknown inclusion \"" + t + "\"", pos);
        }
        return;
    }
    if (key == "prefetch_policy") {
        const std::string& t = enum_text(key, v, pos);
        if (t == "none") {
            cfg.prefetch_policy = PrefetchKind::None;
        } else if (t == "next_burst") {
            cfg.prefetch_policy = PrefetchKind::NextBurst;
        } else {
            fail("unknown prefetch_policy \"" + t + "\"", pos);
        }
        return;
    }

    fail("unknown key \"" + key + "\"", pos);
}

// --- validation helpers ---------------------------------------------------

[[noreturn]] void reject(const std::string& what) {
    throw std::invalid_argument("config: " + what);
}

void reject_below_one(const char* name, std::int64_t value) {
    if (value < 1) {
        reject(std::string(name) + " = " + std::to_string(value) + " must be at least 1");
    }
}

void reject_negative(const char* name, std::int64_t value) {
    if (value < 0) {
        reject(std::string(name) + " = " + std::to_string(value) + " must not be negative");
    }
}

void check_level_geometry(const char* level, std::int64_t size_bytes, std::int32_t assoc,
                          std::int64_t line_bytes, std::int64_t num_lines) {
    const std::int64_t one_set = static_cast<std::int64_t>(assoc) * line_bytes;
    if (size_bytes < one_set) {
        reject(std::string(level) + "_size_bytes = " + std::to_string(size_bytes) +
               " is below one set of " + std::to_string(one_set) + " bytes (" +
               std::to_string(assoc) + " ways of " + std::to_string(line_bytes) + ")");
    }
    if (size_bytes % line_bytes != 0) {
        reject(std::string(level) + "_size_bytes = " + std::to_string(size_bytes) +
               " is not a whole number of " + std::to_string(line_bytes) + "-byte lines");
    }
    if (num_lines % assoc != 0) {
        reject(std::string(level) + " holds " + std::to_string(num_lines) +
               " lines, which is not a whole number of " + std::to_string(assoc) +
               "-way sets");
    }
}

void warn(std::vector<Warning>& warnings, const char* code, const std::string& message) {
    warnings.push_back(Warning{code, message});
}

// --- the one object reader ------------------------------------------------
//
// Shared by a config document, a grid array's elements and a grid's `base`, so
// all three refuse an unknown key, a duplicate key and a wrong value type
// identically.
void read_object_into(Reader& r, RunConfig& cfg) {
    std::vector<std::string> seen;
    r.expect('{');
    if (!r.at('}')) {
        for (;;) {
            const std::size_t key_pos = r.pos();
            const std::string key     = r.read_string();
            for (const std::string& other : seen) {
                if (other == key) fail("duplicate key \"" + key + "\"", key_pos);
            }
            seen.push_back(key);
            r.expect(':');
            const std::size_t value_pos = r.pos();
            assign(cfg, key, r.read_value(), value_pos);
            if (r.at(',')) {
                r.expect(',');
                continue;
            }
            break;
        }
    }
    r.expect('}');
}

// One swept knob: its key, and the values it takes in declaration order, each
// with the byte offset that names it if it turns out to be the wrong type.
struct GridAxis {
    std::string              key;
    std::vector<Value>       values;
    std::vector<std::size_t> positions;
};

}  // namespace

// --- derived geometry -----------------------------------------------------

std::int64_t RunConfig::line_size_bytes() const {
    return static_cast<std::int64_t>(cin_block) * cout_block * weight_bytes;
}
std::int64_t RunConfig::l1_num_lines() const { return l1_size_bytes / line_size_bytes(); }
std::int64_t RunConfig::l1_num_sets() const { return l1_num_lines() / l1_assoc; }
std::int64_t RunConfig::l2_num_lines() const { return l2_size_bytes / line_size_bytes(); }
std::int64_t RunConfig::l2_num_sets() const { return l2_num_lines() / l2_assoc; }

// --- parse ----------------------------------------------------------------

RunConfig parse_config(const std::string& json_text) {
    RunConfig cfg;
    Reader    r(json_text);
    read_object_into(r, cfg);
    r.expect_end();
    return cfg;
}

// --- parse a grid ---------------------------------------------------------

std::vector<RunConfig> parse_config_grid(const std::string& json_text) {
    Reader                 r(json_text);
    std::vector<RunConfig> grid;

    if (r.at('[')) {
        r.expect('[');
        if (!r.at(']')) {
            for (;;) {
                RunConfig cfg;
                read_object_into(r, cfg);
                grid.push_back(cfg);
                if (r.at(',')) {
                    r.expect(',');
                    continue;
                }
                break;
            }
        }
        r.expect(']');
        r.expect_end();
        return grid;
    }

    RunConfig         base;
    std::vector<GridAxis> axes;
    bool              saw_base = false;
    bool              saw_axes = false;

    r.expect('{');
    if (!r.at('}')) {
        for (;;) {
            const std::size_t key_pos = r.pos();
            const std::string key     = r.read_string();
            r.expect(':');
            if (key == "base") {
                if (saw_base) fail("duplicate key \"base\"", key_pos);
                saw_base = true;
                read_object_into(r, base);
            } else if (key == "axes") {
                if (saw_axes) fail("duplicate key \"axes\"", key_pos);
                saw_axes = true;
                r.expect('{');
                if (!r.at('}')) {
                    for (;;) {
                        const std::size_t axis_pos = r.pos();
                        GridAxis          axis;
                        axis.key = r.read_string();
                        for (const GridAxis& other : axes) {
                            if (other.key == axis.key) {
                                fail("duplicate axis \"" + axis.key + "\"", axis_pos);
                            }
                        }
                        r.expect(':');
                        r.expect('[');
                        if (!r.at(']')) {
                            for (;;) {
                                axis.positions.push_back(r.pos());
                                axis.values.push_back(r.read_value());
                                if (r.at(',')) {
                                    r.expect(',');
                                    continue;
                                }
                                break;
                            }
                        }
                        r.expect(']');
                        axes.push_back(std::move(axis));
                        if (r.at(',')) {
                            r.expect(',');
                            continue;
                        }
                        break;
                    }
                }
                r.expect('}');
            } else {
                fail("a grid is an array of configurations, or an object of \"base\" and "
                     "\"axes\"; key \"" +
                         key + "\" is neither",
                     key_pos);
            }
            if (r.at(',')) {
                r.expect(',');
                continue;
            }
            break;
        }
    }
    r.expect('}');
    r.expect_end();

    // The cross product, with the FIRST declared axis varying SLOWEST, so the
    // row order of a grid file is the order it reads in. An empty axis leaves
    // nothing to run, and an empty product of no axes is the base alone.
    std::size_t points = 1;
    for (const GridAxis& a : axes) points *= a.values.size();
    grid.reserve(points);
    for (std::size_t n = 0; n < points; ++n) {
        RunConfig   cfg = base;
        std::size_t rem = n;
        for (std::size_t i = axes.size(); i-- > 0;) {
            const GridAxis&   a = axes[i];
            const std::size_t j = rem % a.values.size();
            rem /= a.values.size();
            assign(cfg, a.key, a.values[j], a.positions[j]);
        }
        grid.push_back(cfg);
    }
    return grid;
}

// --- validate -------------------------------------------------------------

void validate(RunConfig& cfg, std::int32_t lines_per_burst, std::vector<Warning>& warnings) {
    // Counts first, before anything divides by a line size or a set count.
    reject_below_one("lines_per_burst", lines_per_burst);
    reject_below_one("cin_block", cfg.cin_block);
    reject_below_one("cout_block", cfg.cout_block);
    reject_below_one("weight_bytes", cfg.weight_bytes);
    reject_below_one("l1_assoc", cfg.l1_assoc);
    reject_below_one("l2_assoc", cfg.l2_assoc);
    reject_below_one("l1_mshrs", cfg.l1_mshrs);
    reject_below_one("l1_tgts_per_mshr", cfg.l1_tgts_per_mshr);
    reject_below_one("l2_mshrs", cfg.l2_mshrs);
    reject_below_one("l2_tgts_per_mshr", cfg.l2_tgts_per_mshr);
    reject_below_one("l2_banks", cfg.l2_banks);

    reject_negative("l1_ii", cfg.l1_ii);
    reject_negative("l2_ii", cfg.l2_ii);
    reject_negative("dram_ii", cfg.dram_ii);
    reject_negative("l1_latency", cfg.l1_latency);
    reject_negative("l2_latency", cfg.l2_latency);
    reject_negative("l2_to_l1_latency", cfg.l2_to_l1_latency);
    reject_negative("l2_miss_latency", cfg.l2_miss_latency);

    const std::int64_t line = cfg.line_size_bytes();
    check_level_geometry("l1", cfg.l1_size_bytes, cfg.l1_assoc, line, cfg.l1_num_lines());
    check_level_geometry("l2", cfg.l2_size_bytes, cfg.l2_assoc, line, cfg.l2_num_lines());

    if (cfg.policy == PolicyKind::RANDOM) {
        reject("policy = random is a placeholder and is not implemented");
    }
    if (lines_per_burst > cfg.l1_mshrs) {
        reject("l1_mshrs = " + std::to_string(cfg.l1_mshrs) + " cannot hold a burst of " +
               std::to_string(lines_per_burst) + " lines");
    }
    if (cfg.core_accept_ii < 1) {
        reject("core_accept_ii = " + std::to_string(cfg.core_accept_ii) +
               " must be at least 1");
    }
    if (cfg.prefetch_distance < 0) {
        reject("prefetch_distance = " + std::to_string(cfg.prefetch_distance) +
               " must not be negative");
    }
    if (cfg.prefetch_policy == PrefetchKind::NextBurst && cfg.prefetch_distance == 0) {
        reject("prefetch_policy = next_burst with prefetch_distance = 0 would run as "
               "none, so it is refused rather than silently disabled");
    }

    if (cfg.l1_demand_reserve == -1) cfg.l1_demand_reserve = lines_per_burst;
    if (cfg.l1_demand_reserve < 0) {
        reject("l1_demand_reserve = " + std::to_string(cfg.l1_demand_reserve) +
               " must be -1 for the default or at least 0");
    }
    if (cfg.l1_demand_reserve >= cfg.l1_mshrs) {
        reject("l1_demand_reserve = " + std::to_string(cfg.l1_demand_reserve) +
               " leaves no MSHR for a prefetch under l1_mshrs = " +
               std::to_string(cfg.l1_mshrs));
    }

    if (cfg.l1_mshrs >= cfg.l1_num_lines() / 2) {
        warn(warnings, "W_MSHR_VS_LINES",
             "l1_mshrs = " + std::to_string(cfg.l1_mshrs) + " is at least half of the " +
                 std::to_string(cfg.l1_num_lines()) +
                 " L1 lines, so the MSHR file rather than the array sets what fits");
    }
    if (cfg.l1_num_sets() < 8) {
        warn(warnings, "W_FEW_SETS",
             "the L1 has only " + std::to_string(cfg.l1_num_sets()) +
                 " sets, so a power-of-two address stride aliases most of them onto one");
    }
    if (cfg.l1_mshrs - cfg.l1_demand_reserve < lines_per_burst) {
        warn(warnings, "W_PREFETCH_BUDGET",
             "the prefetch budget of " +
                 std::to_string(cfg.l1_mshrs - cfg.l1_demand_reserve) +
                 " MSHRs is under a burst of " + std::to_string(lines_per_burst) +
                 " lines, so the run measures the pool rather than the policy");
    }
    if (cfg.l1_ii == 0 || cfg.l2_ii == 0) {
        warn(warnings, "W_ZERO_II",
             "an initiation interval of 0 is an unbounded port, which is a baseline "
             "rather than a machine");
    }
}

// --- handoff to the engine ------------------------------------------------

EngineParams to_engine_params(const RunConfig& cfg) {
    if (cfg.l1_demand_reserve < 0) {
        reject("to_engine_params needs a validated config: l1_demand_reserve is still "
               "the -1 sentinel");
    }

    EngineParams p;
    p.l1.cache_size_bytes = cfg.l1_size_bytes;
    p.l1.associativity    = cfg.l1_assoc;
    p.l1.policy           = cfg.policy;
    p.l1.latency          = SimTime{cfg.l1_latency};
    p.l1.ii               = SimTime{cfg.l1_ii};
    p.l1.banks            = 1;
    p.l1.mshrs            = cfg.l1_mshrs;
    p.l1.tgts_per_mshr    = cfg.l1_tgts_per_mshr;
    p.l1.demand_reserve   = cfg.l1_demand_reserve;

    p.l2.cache_size_bytes = cfg.l2_size_bytes;
    p.l2.associativity    = cfg.l2_assoc;
    p.l2.policy           = cfg.policy;
    p.l2.latency          = SimTime{cfg.l2_latency};
    p.l2.ii               = SimTime{cfg.l2_ii};
    p.l2.banks            = cfg.l2_banks;
    p.l2.mshrs            = cfg.l2_mshrs;
    p.l2.tgts_per_mshr    = cfg.l2_tgts_per_mshr;
    // The L2 demand reserve is a removed knob: it is 0 here and there is no
    // config key that can change it.
    p.l2.demand_reserve = 0;

    p.l2_to_l1_latency = SimTime{cfg.l2_to_l1_latency};
    p.dram_ii          = SimTime{cfg.dram_ii};
    p.l2_miss_latency  = SimTime{cfg.l2_miss_latency};
    p.core_accept_ii   = SimTime{cfg.core_accept_ii};
    p.inclusion        = cfg.inclusion;
    p.prefetch_policy  = cfg.prefetch_policy;
    p.prefetch_distance = cfg.prefetch_distance;
    return p;
}

}  // namespace wcache
