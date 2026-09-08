// wcache_run: one config, one trace, one CSV row. Plan D Task 15.
//
// This file lives under apps/ and not under src/ because the Makefile's
// library is `$(wildcard src/*.cpp)`: a main() there would be archived into
// libwcache.a and collide with every test binary's own main().
//
// It is also the ONLY place that knows which TileTrace the engine is running.
// Decisions B10 and B23 keep that knowledge out of the engine, so the wiring of
// a StreamingTileTrace to an Engine happens here and nowhere below.
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "app_support.h"
#include "wcache/block_pack.h"
#include "wcache/byte_source.h"
#include "wcache/access_log.h"
#include "wcache/next_use.h"
#include "wcache/cache_state_log.h"
#include "wcache/config.h"
#include "wcache/engine.h"
#include "wcache/hist.h"
#include "wcache/line_trace.h"
#include "wcache/stats.h"
#include "wcache/stream_trace.h"
#include "wcache/types.h"

namespace {

using namespace wcache;
using namespace wcache::app;

const char* const kUsage =
    "wcache_run --config <path.json> --trace <path|-> [options]\n"
    "\n"
    "  --config PATH          required. The run configuration as JSON.\n"
    "  --trace PATH           required. A WCTS stream. `-` means stdin, `fd:N`\n"
    "                         an already-open file descriptor N.\n"
    "  --out PATH             where the CSV goes. Default `-` (stdout).\n"
    "  --header               emit the CSV header line before the row. Default on\n"
    "                         when --out is a path that does not exist, off otherwise.\n"
    "  --no-header            never emit the header line.\n"
    "  --arm NAME             the `arm` column: spad_oracle | spad_wcache |\n"
    "                         spad_nocsim | cache. Default `cache`.\n"
    "  --tier NAME            the `tier` column, free text. Default empty.\n"
    "  --run-id STRING        the `run_id` column. Default a UUIDv4 generated here.\n"
    "  --git-commit STRING    the `git_commit` column. Default empty; the driver\n"
    "                         fills it, because the binary must not shell out.\n"
    "  --hist PATH            write the per-(core, tile) distinct-address histogram\n"
    "                         here as CSV. Off by default.\n"
    "\n"
    "  Two DEBUGGING instruments, both off by default, both CSV, and deliberately\n"
    "  separate files: one says what is IN the caches, the other says what happened\n"
    "  TO a line. Neither changes any counter or any column of the results row.\n"
    "\n"
    "  --cache-state PATH     every change to the contents of an array, in time\n"
    "                         order: one row per fill, evict or invalidate, at both\n"
    "                         levels, with the set, the way and the event time.\n"
    "  --cache-state-core N   only core N's L1. L2 rows are always kept, since the\n"
    "                         L2 belongs to no core. Default -1, every core.\n"
    "  --cache-state-tile N   only tile N. Default -1, every tile.\n"
    "  --cache-state-limit N  stop after N rows. Default -1, unbounded.\n"
    "\n"
    "  --line-trace PATH      one row per residency episode: a line from the fill\n"
    "                         that installed it to the eviction that removed it,\n"
    "                         carrying how long it stayed and how often it was hit.\n"
    "  --line-trace-level L   which levels to follow: l1 | l2 | both. Default l1,\n"
    "                         because an L1 and an L2 episode for one line are filled\n"
    "                         at the same instant and differ only in how long they\n"
    "                         last; the L2's side is in --cache-state, which keeps\n"
    "                         both levels.\n"
    "  --line-trace-core N    only core N's L1 episodes. Default -1, every core.\n"
    "  --line-trace-tile N    only episodes FILLED in tile N; each is kept whole,\n"
    "                         so one may end in a later tile. Default -1, all.\n"
    "  --line-trace-line N    only this line id, at both levels. Default -1, all.\n"
    "  --line-trace-limit N   stop after N rows. Default -1, unbounded.\n"
    "\n"
    "  --oracle PATH          an access log from a PRIOR run over the SAME trace and\n"
    "                         the SAME layout, used to build the next-use oracles\n"
    "                         Belady needs: one per core for the private L1s, one\n"
    "                         shared for the L2. Required by policy = belady or\n"
    "                         l2_policy = belady, and inert under any other policy.\n"
    "                         The L1 oracles are exact WHILE NOTHING BLOCKS: each\n"
    "                         core's L1 demand stream is then a pure function of the\n"
    "                         trace, the core and the mapper. A refused request\n"
    "                         re-probes and is counted twice, which shifts every\n"
    "                         later occurrence index, so check max_wait_depth == 0\n"
    "                         in the row; the binary warns on stderr when it is not.\n"
    "                         The L2 one is APPROXIMATE under policy = belady, no\n"
    "                         matter what blocks, because a Belady L1 changes which\n"
    "                         references miss, so this run's L2 stream is a\n"
    "                         different sequence and not a reordering of the log's.\n"
    "                         The overrun counts on stderr are how far apart they\n"
    "                         turned out to be.\n"
    "  --l2-oracle PATH       an access log from a PRIOR run, used to build the\n"
    "                         next-use oracle Belady needs. Required by\n"
    "                         l2_policy = belady and inert under any other\n"
    "                         policy. Only the L2 records of the log are read.\n"
    "\n"
    "  --access-log PATH      the demand reference stream in time order, as\n"
    "                         fixed-width BINARY: 8 bytes per reference, carrying\n"
    "                         level, core and line id, after an 8-byte magic.\n"
    "                         One record per demand probe, at both levels, under\n"
    "                         the same guard that counts l1_accesses, so the file\n"
    "                         and the row agree by construction. Consumed by\n"
    "                         profiling/0831_reuse_distance/reuse_tool. Off by\n"
    "                         default.\n"
    "  --oracle-only          decode the stream, compute tick_base_total, emit a row\n"
    "                         with total_cycles == tick_base_total and every\n"
    "                         simulated column empty, and run no engine.\n"
    "  --help                 this text on stdout, exit 0.\n";

struct Options {
    std::string config_path;
    std::string trace_path;
    std::string out_path = "-";
    std::string hist_path;

    std::string  state_path;
    std::string  access_log_path;
    std::string  oracle_path;
    std::string  l2_oracle_path;
    std::int32_t state_core  = -1;
    std::int32_t state_tile  = -1;
    std::int64_t state_limit = -1;

    std::string  trace_path_out;
    bool         trace_l1    = true;   // the default is L1 only; see --line-trace-level
    bool         trace_l2    = false;
    std::int32_t trace_core  = -1;
    std::int32_t trace_tile  = -1;
    std::int64_t trace_line  = -1;
    std::int64_t trace_limit = -1;

    RowIdentity id;
    bool header      = false;
    bool header_set  = false;
    bool oracle_only = false;
};

// --- argument parsing --------------------------------------------------------

// Throws UsageError. Returns false when --help was given and the caller should
// exit 0 without running anything.
bool parse_args(int argc, char** argv, Options& opt) {
    for (int i = 1; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--help") return false;
        else if (flag == "--config")     opt.config_path    = value_of(argc, argv, i);
        else if (flag == "--trace")      opt.trace_path     = value_of(argc, argv, i);
        else if (flag == "--out")        opt.out_path       = value_of(argc, argv, i);
        else if (flag == "--hist")       opt.hist_path      = value_of(argc, argv, i);
        else if (flag == "--cache-state") opt.state_path    = value_of(argc, argv, i);
        else if (flag == "--access-log") opt.access_log_path = value_of(argc, argv, i);
        else if (flag == "--oracle")    opt.oracle_path    = value_of(argc, argv, i);
        else if (flag == "--l2-oracle") opt.l2_oracle_path = value_of(argc, argv, i);
        else if (flag == "--cache-state-core")
            opt.state_core = static_cast<std::int32_t>(int_value_of(argc, argv, i));
        else if (flag == "--cache-state-tile")
            opt.state_tile = static_cast<std::int32_t>(int_value_of(argc, argv, i));
        else if (flag == "--cache-state-limit") opt.state_limit = int_value_of(argc, argv, i);
        else if (flag == "--line-trace") opt.trace_path_out = value_of(argc, argv, i);
        else if (flag == "--line-trace-level") {
            const std::string lv = value_of(argc, argv, i);
            if (lv == "l1")        { opt.trace_l1 = true;  opt.trace_l2 = false; }
            else if (lv == "l2")   { opt.trace_l1 = false; opt.trace_l2 = true;  }
            else if (lv == "both") { opt.trace_l1 = true;  opt.trace_l2 = true;  }
            else throw UsageError("--line-trace-level " + lv + " is not l1, l2 or both");
        }
        else if (flag == "--line-trace-core")
            opt.trace_core = static_cast<std::int32_t>(int_value_of(argc, argv, i));
        else if (flag == "--line-trace-tile")
            opt.trace_tile = static_cast<std::int32_t>(int_value_of(argc, argv, i));
        else if (flag == "--line-trace-line")  opt.trace_line  = int_value_of(argc, argv, i);
        else if (flag == "--line-trace-limit") opt.trace_limit = int_value_of(argc, argv, i);
        else if (flag == "--arm")        opt.id.arm         = value_of(argc, argv, i);
        else if (flag == "--tier")       opt.id.tier        = value_of(argc, argv, i);
        else if (flag == "--run-id")     opt.id.run_id      = value_of(argc, argv, i);
        else if (flag == "--git-commit") opt.id.git_commit  = value_of(argc, argv, i);
        else if (flag == "--header")     { opt.header = true;  opt.header_set = true; }
        else if (flag == "--no-header")  { opt.header = false; opt.header_set = true; }
        else if (flag == "--oracle-only") opt.oracle_only = true;
        else throw UsageError("unknown option " + flag);
    }
    if (opt.config_path.empty()) throw UsageError("--config is required");
    if (opt.trace_path.empty()) throw UsageError("--trace is required");
    // A narrowing flag with no file to narrow is refused rather than ignored: a
    // silent no-op is a run the user believes produced something.
    if (opt.state_path.empty() &&
        (opt.state_core >= 0 || opt.state_tile >= 0 || opt.state_limit >= 0)) {
        throw UsageError("--cache-state-core / --cache-state-tile / --cache-state-limit "
                         "need --cache-state");
    }
    if (opt.trace_path_out.empty() &&
        (opt.trace_core >= 0 || opt.trace_tile >= 0 || opt.trace_line >= 0 ||
         opt.trace_limit >= 0 || opt.trace_l2)) {
        throw UsageError("--line-trace-level / --line-trace-core / --line-trace-tile / "
                         "--line-trace-line / --line-trace-limit need --line-trace");
    }
    // Refused rather than resolved by precedence: the two flags build different
    // oracle sets from the same file, and a run that silently used one of them
    // would report a number the command line does not explain.
    if (!opt.oracle_path.empty() && !opt.l2_oracle_path.empty()) {
        throw UsageError("--oracle and --l2-oracle name the same kind of file for "
                         "different levels; give one or the other");
    }
    check_arm(opt.id.arm);
    return true;
}

// --- the run -----------------------------------------------------------------

void run(Options& opt) {
    std::ifstream cfg_in(opt.config_path);
    if (!cfg_in) throw std::runtime_error("cannot read config " + opt.config_path);
    std::stringstream cfg_text;
    cfg_text << cfg_in.rdbuf();
    RunConfig cfg = parse_config(cfg_text.str());

    TraceFd       fd(opt.trace_path);
    FdByteSource  src(fd.get());
    StreamingTileTrace trace(src);
    const stream::StreamHeader& hdr = trace.header();

    const WeightShape shape = shape_of(hdr);

    // Two mappers, in this order, because the dependency runs both ways.
    // validate() needs a burst span in LINES, which only a mapper can give; and
    // the mapper the run actually uses needs cin_lo_blocks, which only
    // validate() resolves. The probe breaks the cycle: a burst covers the same
    // block coordinates under either nesting, so the COUNT it yields is the one
    // the real mapper would have given (see lines_per_burst).
    const BlockPackMapper probe(shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes);

    std::vector<Warning> warnings;
    validate(cfg, lines_per_burst(probe, hdr), warnings);

    const std::unique_ptr<AddressMapper> owned = make_mapper(cfg, shape, warnings);
    const AddressMapper& mapper = *owned;

    for (const Warning& w : warnings) {
        std::cerr << "wcache_run: warning [" << w.code << "] " << w.message << "\n";
    }

    if (opt.id.run_id.empty()) opt.id.run_id = uuid4();
    if (!opt.header_set) opt.header = opt.out_path != "-" && !path_exists(opt.out_path);

    DistinctAddressHistogram hist(hdr);
    std::string row;

    if (opt.oracle_only) {
        while (trace.advance()) hist.observe(trace);
        row = oracle_row(opt.id, cfg, hdr, trace.tick_base(hdr.n_tiles));
    } else {
        PaddingMeter padding(mapper, shape,
                             static_cast<std::int64_t>(cfg.cin_block) * cfg.cout_block);
        // Declared BEFORE the engine, so they are destroyed after it. The
        // engine and its levels hold raw non-owning NextUseOracle pointers, and
        // an oracle that died first would leave those dangling through the
        // engine's own teardown. Nothing dereferences them there today, but
        // only because neither Engine nor CacheLevel declares a destructor,
        // which is an invariant resting on the absence of code. wcache_sweep
        // already orders them this way; the two now agree.
        //
        // Filled below, after the engine exists, since attaching needs it.
        OracleSet                      oracles;
        std::unique_ptr<NextUseOracle> l2_oracle;

        Engine engine(mapper, trace, to_engine_params(cfg));
        double engine_seconds = 0.0;

        // The two instruments, each into its own file. Declared here so their
        // streams outlive the engine, and attached before the first tile so
        // both start where the run does.
        //
        // `--oracle-only` never reaches this branch, which is correct: that
        // mode runs no engine, so there is no array to watch and no line to
        // follow.
        std::ofstream state_file;
        std::unique_ptr<CacheStateLog> state_log;
        if (!opt.state_path.empty()) {
            state_file.open(opt.state_path);
            if (!state_file) throw std::runtime_error("cannot write " + opt.state_path);
            state_log.reset(new CacheStateLog(state_file, hdr.n_cores, cfg.l1_num_sets(),
                                              cfg.l2_num_sets(), cfg.l1_assoc, cfg.l2_assoc,
                                              opt.state_core, opt.state_tile,
                                              opt.state_limit));
            state_log->write_header();
            engine.set_cache_state_log(state_log.get());
        }

        // Belady's oracles, built from a prior run's access log. Attached before
        // the first tile so every level that needs a future has one for its
        // first reference.
        //
        // A config naming belady without an oracle is refused rather than run:
        // silently falling back would report a Belady hit rate that is really
        // an every-slot-looks-dead policy, which is the one wrong answer here.
        //
        // The L1's half of that refusal stands OUTSIDE the chain below, and must
        // stay outside it. As the chain's last arm it was unreachable whenever
        // an earlier arm matched, so `policy = belady` with `--l2-oracle` took
        // the L2 branch, left every L1 slot reading kNever, picked an arbitrary
        // victim and exited 0 with a row still labelled policy = belady. Only
        // `--oracle` builds the per-core L1 oracles, so only `--oracle` can
        // satisfy `policy = belady`, and saying that here makes it true for
        // every combination of flags rather than for the ones the chain reaches.
        if (opt.oracle_path.empty() && cfg.policy == PolicyKind::BELADY) {
            throw std::runtime_error("policy = belady needs --oracle; --l2-oracle covers "
                                     "l2_policy only: without a per-core future every L1 "
                                     "slot looks dead and the run would report a hit rate "
                                     "no policy produced");
        }
        if (!opt.oracle_path.empty()) {
            oracles = build_oracles(opt.oracle_path, hdr.n_cores);
            attach_oracles(oracles, cfg, engine);
            report_oracles("wcache_run", opt.oracle_path, oracles);
        } else if (!opt.l2_oracle_path.empty()) {
            // Its own branch, not merged with `--oracle`. It is the flag every
            // committed L2 result was produced with, and a separate branch is
            // the cheapest guarantee that none of those results moves. The null
            // `l1_by_core` is what keeps it reading the L2 records alone, as the
            // reader it replaced did: it neither builds the per-core stream it
            // would throw away nor refuses a log written by a wider run.
            std::vector<std::int64_t> l2_lines;
            read_oracle_lines(opt.l2_oracle_path, hdr.n_cores, nullptr, l2_lines);
            l2_oracle.reset(new NextUseOracle(l2_lines));
            engine.l2().attach_next_use(l2_oracle.get());
            std::cerr << "wcache_run: l2 oracle " << opt.l2_oracle_path << ", "
                      << l2_oracle->references() << " references over "
                      << l2_oracle->distinct_lines() << " lines\n";
        } else if (cfg.l2_policy == PolicyKind::BELADY) {
            // `policy` is already settled above, so this arm covers `l2_policy`
            // alone, which either flag can satisfy.
            throw std::runtime_error("l2_policy = belady needs --oracle or --l2-oracle: "
                                     "without a future every slot looks dead and the run "
                                     "would report a hit rate no policy produced");
        }

        // Binary, so the reader can size its own buffer from the file length.
        // Opened with std::ios::binary because on a platform that translates
        // newlines a 0x0A byte inside a line id would silently gain a byte.
        std::ofstream access_file;
        std::unique_ptr<AccessLog> access_log;
        if (!opt.access_log_path.empty()) {
            access_file.open(opt.access_log_path, std::ios::binary);
            if (!access_file) throw std::runtime_error("cannot write " + opt.access_log_path);
            access_log.reset(new AccessLog(access_file));
            access_log->write_header();
            engine.set_access_log(access_log.get());
        }

        std::ofstream trace_file;
        std::unique_ptr<LineTrace> line_trace;
        if (!opt.trace_path_out.empty()) {
            trace_file.open(opt.trace_path_out);
            if (!trace_file) throw std::runtime_error("cannot write " + opt.trace_path_out);
            line_trace.reset(new LineTrace(trace_file, opt.trace_l1, opt.trace_l2,
                                           opt.trace_core, opt.trace_tile, opt.trace_line,
                                           opt.trace_limit));
            line_trace->write_header();
            engine.set_line_trace(line_trace.get());
        }

        // The window must move BEFORE the engine runs, because the engine has to
        // consume tile N while the window still holds it. That makes this the
        // degenerate case of the broadcast driver, with one engine: the barrier
        // for the tile just finished is left queued, the next advance moves the
        // window, and the FOLLOWING run_to_barrier dispatches it.
        for (;;) {
            if (!trace.advance()) break;
            hist.observe(trace);
            padding.observe_tile(trace);
            const auto t0 = std::chrono::steady_clock::now();
            const std::int32_t pending = engine.run_to_barrier();
            engine_seconds += std::chrono::duration<double>(
                                  std::chrono::steady_clock::now() - t0).count();
            if (pending < 0) break;
        }
        const auto t0 = std::chrono::steady_clock::now();
        engine.finish();
        engine_seconds +=
            std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

        report_overruns("wcache_run", oracles, engine.stats().max_wait_depth);

        // Said in each file and on stderr both: a truncated instrument that says
        // so nowhere reads as a run that simply stopped early.
        if (state_log) {
            state_file << "# " << state_log->written() << " rows"
                       << (state_log->truncated() ? ", TRUNCATED at --cache-state-limit\n"
                                                  : "\n");
            std::cerr << "wcache_run: cache state " << opt.state_path << ", "
                      << state_log->written() << " rows"
                      << (state_log->truncated() ? " (truncated)\n" : "\n");
        }
        if (line_trace) {
            trace_file << "# " << line_trace->written() << " episodes"
                       << (line_trace->truncated() ? ", TRUNCATED at --line-trace-limit\n"
                                                   : "\n");
            std::cerr << "wcache_run: line trace " << opt.trace_path_out << ", "
                      << line_trace->written() << " episodes"
                      << (line_trace->truncated() ? " (truncated)\n" : "\n");
        }

        const RunStats stats(opt.id, cfg, hdr, engine.stats(),
                             engine.tile_origin(hdr.n_tiles).get(),
                             trace.tick_base(hdr.n_tiles), padding.fraction(), engine_seconds,
                             hist.p50(), hist.max());
        stats.check_invariants();
        row = stats.csv_row();
    }

    std::string text;
    if (opt.header) text = csv_header() + "\n";
    write_out(opt.out_path, text + row + "\n");

    if (!opt.hist_path.empty()) {
        std::ofstream out(opt.hist_path);
        if (!out) throw std::runtime_error("cannot write " + opt.hist_path);
        hist.write_csv(out);
    }
}

}  // namespace


int main(int argc, char** argv) {
    Options opt;
    try {
        if (!parse_args(argc, argv, opt)) {
            std::cout << kUsage;
            return 0;
        }
    } catch (const UsageError& e) {
        std::cerr << "wcache_run: " << e.what() << "\n\n" << kUsage;
        return 2;
    }
    try {
        run(opt);
    } catch (const std::exception& e) {
        std::cerr << "wcache_run: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
