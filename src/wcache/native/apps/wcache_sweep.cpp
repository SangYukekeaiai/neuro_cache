// wcache_sweep: one config grid, one trace, one CSV row per grid point, in
// broadcast lockstep over a SINGLE pass of the stream. Plan D Task 18.
//
// A stream can be read once and a grid has many points, so the reader holds
// one tile window and every engine consumes that same tile before it moves.
// BroadcastSweep owns that loop; this file is the CLI around it, and, with
// wcache_run, the only place that knows which TileTrace and which mapper the
// engines are running (decisions B10 and B23).
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
#include "wcache/hist.h"
#include "wcache/stats.h"
#include "wcache/stream_trace.h"
#include "wcache/sweep.h"
#include "wcache/types.h"

namespace {

using namespace wcache;
using namespace wcache::app;

const char* const kUsage =
    "wcache_sweep --config-grid <path.json> --trace <path|-> [options]\n"
    "\n"
    "  --config-grid PATH     required. A JSON array of run configurations, OR an\n"
    "                         object with `base` (one config) and `axes`\n"
    "                         (name -> list of values), expanded to the full cross\n"
    "                         product with the first axis varying slowest.\n"
    "  --trace PATH           required. A WCTS stream. `-` means stdin, `fd:N`\n"
    "                         an already-open file descriptor N.\n"
    "  --out PATH             where the CSV goes. Default `-` (stdout).\n"
    "  --header               emit the CSV header line. Default on for a sweep.\n"
    "  --no-header            never emit the header line.\n"
    "  --arm NAME             the `arm` column, applied to every row: spad_oracle |\n"
    "                         spad_wcache | spad_nocsim | cache. Default `cache`.\n"
    "  --tier NAME            the `tier` column, free text. Default empty.\n"
    "  --run-id STRING        the `run_id` column. Every row of one sweep shares it.\n"
    "                         Default a UUIDv4 generated here.\n"
    "  --git-commit STRING    the `git_commit` column. Default empty; the driver\n"
    "                         fills it, because the binary must not shell out.\n"
    "  --hist PATH            write the per-(core, tile) distinct-address histogram\n"
    "                         here as CSV. The histogram is a property of the trace,\n"
    "                         so it is written once per sweep. Off by default.\n"
    "  --max-engines N        refuse a grid larger than N live engines, so an\n"
    "                         oversized grid fails at startup rather than by OOM\n"
    "                         three hours in. Default 256.\n"
    "  --progress             one line per completed tile on stderr.\n"
    "  --help                 this text on stdout, exit 0.\n";

struct Options {
    std::string  grid_path;
    std::string  trace_path;
    std::string  out_path = "-";
    std::string  hist_path;
    RowIdentity  id;
    std::int32_t max_engines = 256;
    bool         header      = true;
    bool         progress    = false;
};

// Throws UsageError. Returns false when --help was given and the caller should
// exit 0 without running anything.
bool parse_args(int argc, char** argv, Options& opt) {
    for (int i = 1; i < argc; ++i) {
        const std::string flag = argv[i];
        if (flag == "--help") return false;
        else if (flag == "--config-grid") opt.grid_path   = value_of(argc, argv, i);
        else if (flag == "--trace")       opt.trace_path  = value_of(argc, argv, i);
        else if (flag == "--out")         opt.out_path    = value_of(argc, argv, i);
        else if (flag == "--hist")        opt.hist_path   = value_of(argc, argv, i);
        else if (flag == "--arm")         opt.id.arm      = value_of(argc, argv, i);
        else if (flag == "--tier")        opt.id.tier     = value_of(argc, argv, i);
        else if (flag == "--run-id")      opt.id.run_id   = value_of(argc, argv, i);
        else if (flag == "--git-commit")  opt.id.git_commit = value_of(argc, argv, i);
        else if (flag == "--max-engines") {
            const std::string n = value_of(argc, argv, i);
            try {
                opt.max_engines = std::stoi(n);
            } catch (const std::exception&) {
                throw UsageError("--max-engines takes a number, got " + n);
            }
        }
        else if (flag == "--header")    opt.header   = true;
        else if (flag == "--no-header") opt.header   = false;
        else if (flag == "--progress")  opt.progress = true;
        else throw UsageError("unknown option " + flag);
    }
    if (opt.grid_path.empty()) throw UsageError("--config-grid is required");
    if (opt.trace_path.empty()) throw UsageError("--trace is required");
    check_arm(opt.id.arm);
    return true;
}

std::string read_file(const std::string& path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot read " + path);
    std::stringstream text;
    text << in.rdbuf();
    return text.str();
}

void run(Options& opt) {
    std::vector<RunConfig> grid = parse_config_grid(read_file(opt.grid_path));
    if (grid.empty()) {
        throw std::runtime_error("the grid in " + opt.grid_path +
                                 " expands to no configurations");
    }

    TraceFd            fd(opt.trace_path);
    FdByteSource       src(fd.get());
    StreamingTileTrace trace(src);
    const stream::StreamHeader& hdr = trace.header();

    // One mapper for the whole grid, built from the FIRST point's layout.
    // BroadcastSweep then refuses any point that disagrees with it, because a
    // layout change would change what a line is mid-stream.
    const WeightShape shape = shape_of(hdr);
    BlockPackMapper   mapper(shape, grid[0].cin_block, grid[0].cout_block,
                             grid[0].weight_bytes);
    const std::int32_t reserve_default = lines_per_burst(mapper, hdr);

    for (std::size_t i = 0; i < grid.size(); ++i) {
        std::vector<Warning> warnings;
        validate(grid[i], reserve_default, warnings);
        for (const Warning& w : warnings) {
            std::cerr << "wcache_sweep: configuration " << i << " warning [" << w.code
                      << "] " << w.message << "\n";
        }
    }

    if (opt.id.run_id.empty()) opt.id.run_id = uuid4();

    DistinctAddressHistogram hist(hdr);
    PaddingMeter padding(mapper, shape,
                         static_cast<std::int64_t>(grid[0].cin_block) * grid[0].cout_block);

    BroadcastSweep sweep(trace, mapper, grid, opt.max_engines);
    sweep.run([&](const StreamingTileTrace& window) {
        // The driver owns the loop, so everything that has to see a tile sees
        // it here, once, for the whole grid. Both of these are properties of
        // the trace and the layout rather than of a configuration.
        hist.observe(window);
        padding.observe_tile(window);
        if (opt.progress) {
            std::cerr << "wcache_sweep: tile " << window.window_tile() << " of "
                      << hdr.n_tiles << " done on " << sweep.size() << " engines\n";
        }
    });

    const std::int64_t tick_base_total = trace.tick_base(hdr.n_tiles);
    const double       padding_fraction = padding.fraction();

    std::string text;
    if (opt.header) text = csv_header() + "\n";
    for (std::size_t i = 0; i < sweep.size(); ++i) {
        const RunStats stats(opt.id, sweep.config(i), hdr, sweep.engine(i).stats(),
                             sweep.engine(i).tile_origin(hdr.n_tiles).get(), tick_base_total,
                             padding_fraction, sweep.wall_seconds(i), hist.p50(), hist.max());
        stats.check_invariants();
        text += stats.csv_row();
        text += "\n";
    }
    write_out(opt.out_path, text);

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
        std::cerr << "wcache_sweep: " << e.what() << "\n\n" << kUsage;
        return 2;
    }
    try {
        run(opt);
    } catch (const std::exception& e) {
        std::cerr << "wcache_sweep: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
