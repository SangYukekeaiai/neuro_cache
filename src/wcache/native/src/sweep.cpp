#include "wcache/sweep.h"

#include <chrono>
#include <stdexcept>
#include <string>

namespace wcache {
namespace {

// The spelling for a refusal message. A local switch and not a ternary: a
// two-way ternary over a three-valued enum reports the wrong layout the day a
// fourth one lands, and this message exists to tell a sweeper which grid point
// disagreed.
const char* layout_text(LayoutKind l) {
    switch (l) {
        case LayoutKind::BlockPack: return "block_pack";
        case LayoutKind::SplitCin:  return "split_cin";
        case LayoutKind::KhkwSplit: return "khkw_split";
    }
    return "unknown";
}

// Names the grid point a throw came from without losing the type the caller
// distinguishes on. Called from a `catch (...)`, so the bare `throw;` inside
// re-raises the live exception and the clauses below re-wrap it; anything they
// do not name propagates unchanged rather than being flattened.
[[noreturn]] void rethrow_with_index(std::size_t i) {
    const std::string at = "sweep: configuration " + std::to_string(i) + ": ";
    try {
        throw;
    } catch (const std::out_of_range& e) {
        throw std::out_of_range(at + e.what());
    } catch (const std::invalid_argument& e) {
        throw std::invalid_argument(at + e.what());
    } catch (const std::logic_error& e) {
        throw std::logic_error(at + e.what());
    } catch (const std::runtime_error& e) {
        throw std::runtime_error(at + e.what());
    }
}

}  // namespace

BroadcastSweep::BroadcastSweep(StreamingTileTrace& trace, const AddressMapper& mapper,
                               std::vector<RunConfig> configs, std::int32_t max_engines)
    : trace_(&trace), configs_(std::move(configs)) {
    if (configs_.empty()) {
        throw std::invalid_argument("sweep: the configuration grid is empty");
    }
    if (max_engines < 1) {
        throw std::invalid_argument("sweep: max_engines = " + std::to_string(max_engines) +
                                    " must be at least 1");
    }
    // Checked BEFORE a single engine is constructed, which is the whole reason
    // the limit exists.
    if (configs_.size() > static_cast<std::size_t>(max_engines)) {
        throw std::invalid_argument("sweep: the grid has " + std::to_string(configs_.size()) +
                                    " configurations, over the limit of " +
                                    std::to_string(max_engines) + " live engines");
    }

    const RunConfig& first = configs_[0];
    for (std::size_t i = 1; i < configs_.size(); ++i) {
        const RunConfig& c = configs_[i];
        // Everything the mapper is built from, which is now five fields and not
        // three: `layout` picks the class and `cin_lo_blocks` is a constructor
        // argument to one of them. A point that disagreed on either would be
        // scored against a mapper built for a different point, and the row
        // would name the layout it did not run.
        //
        // `cin_lo_blocks` is compared AFTER validate has resolved it, so this
        // also refuses a split_cin grid that varies l1_size_bytes: the width
        // follows the set count, so the layout would change mid-stream. The
        // same grid under block_pack is fine, where the field stays -1 at every
        // point.
        if (c.cin_block != first.cin_block || c.cout_block != first.cout_block ||
            c.weight_bytes != first.weight_bytes || c.layout != first.layout ||
            c.cin_lo_blocks != first.cin_lo_blocks) {
            const auto shape_of_point = [](const RunConfig& p) {
                return "cin_block " + std::to_string(p.cin_block) + ", cout_block " +
                       std::to_string(p.cout_block) + ", weight_bytes " +
                       std::to_string(p.weight_bytes) + ", layout " +
                       layout_text(p.layout) +
                       ", cin_lo_blocks " + std::to_string(p.cin_lo_blocks);
            };
            throw std::invalid_argument(
                "sweep: configuration " + std::to_string(i) + " has (" + shape_of_point(c) +
                ") but configuration 0 has (" + shape_of_point(first) +
                "): one mapper serves the whole grid, so a layout sweep is one sweep per "
                "layout, each over its own pass of the stream");
        }
    }
    if (mapper.line_size_bytes() != first.line_size_bytes()) {
        throw std::invalid_argument("sweep: the mapper serves " +
                                    std::to_string(mapper.line_size_bytes()) +
                                    "-byte lines but the grid asks for " +
                                    std::to_string(first.line_size_bytes()));
    }

    engines_.reserve(configs_.size());
    for (std::size_t i = 0; i < configs_.size(); ++i) {
        try {
            engines_.push_back(
                std::make_unique<Engine>(mapper, trace, to_engine_params(configs_[i])));
        } catch (...) {
            rethrow_with_index(i);
        }
    }
    wall_.assign(configs_.size(), 0.0);
}

void BroadcastSweep::run(const TileObserver& on_tile) {
    for (;;) {
        // The window must move BEFORE the engines run, because each of them has
        // to consume tile N while the window still holds it.
        if (!trace_->advance()) break;
        if (on_tile) on_tile(*trace_);
        for (std::size_t i = 0; i < engines_.size(); ++i) {
            const auto t0 = std::chrono::steady_clock::now();
            try {
                // Dispatches the barrier of the PREVIOUS tile (there is none on
                // the first pass), then runs this tile to its own barrier and
                // parks there. Its return is not read: the loop ends when the
                // STREAM ends, and an engine that finished early would still
                // have to be carried to `finish` below.
                (void)engines_[i]->step_tile();
            } catch (...) {
                rethrow_with_index(i);
            }
            wall_[i] += std::chrono::duration<double>(std::chrono::steady_clock::now() - t0)
                            .count();
        }
    }
    for (std::size_t i = 0; i < engines_.size(); ++i) {
        const auto t0 = std::chrono::steady_clock::now();
        try {
            engines_[i]->finish();
        } catch (...) {
            rethrow_with_index(i);
        }
        wall_[i] +=
            std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    }
}

const Engine& BroadcastSweep::engine(std::size_t i) const { return *engines_.at(i); }

Engine& BroadcastSweep::engine(std::size_t i) { return *engines_.at(i); }

const RunConfig& BroadcastSweep::config(std::size_t i) const { return configs_.at(i); }

double BroadcastSweep::wall_seconds(std::size_t i) const { return wall_.at(i); }

}  // namespace wcache
