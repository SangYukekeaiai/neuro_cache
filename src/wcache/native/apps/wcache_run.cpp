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
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "app_support.h"
#include "wcache/block_pack.h"
#include "wcache/byte_source.h"
#include "wcache/config.h"
#include "wcache/engine.h"
#include "wcache/hist.h"
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
    "  --oracle-only          decode the stream, compute tick_base_total, emit a row\n"
    "                         with total_cycles == tick_base_total and every\n"
    "                         simulated column empty, and run no engine.\n"
    "  --help                 this text on stdout, exit 0.\n";

struct Options {
    std::string config_path;
    std::string trace_path;
    std::string out_path = "-";
    std::string hist_path;
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

    BlockPackMapper mapper(shape_of(hdr), cfg.cin_block, cfg.cout_block, cfg.weight_bytes);

    std::vector<Warning> warnings;
    validate(cfg, lines_per_burst(mapper, hdr), warnings);
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
        PaddingMeter padding(mapper, shape_of(hdr),
                             static_cast<std::int64_t>(cfg.cin_block) * cfg.cout_block);
        Engine engine(mapper, trace, to_engine_params(cfg));
        double engine_seconds = 0.0;

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
