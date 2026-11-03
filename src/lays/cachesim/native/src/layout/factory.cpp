#include "cachesim/layout/factory.h"

#include <memory>
#include <string>

#include "cachesim/layout/block_pack.h"
#include "cachesim/layout/khkw_split.h"
#include "cachesim/layout/split_cin.h"

namespace cachesim {

// The one place `cfg.layout` becomes a mapper.
//
// Both drivers call it, so the branch over LayoutKind is written once. Adding a
// third layout is an enumerator in layout.h, a spelling in config.cpp, and a
// case here; no driver learns the list.
//
// It also appends the layout warning that needs the LAYER, and the two are one
// function on purpose. validate() is handed a config and a burst span and never
// a shape, so it cannot ask how many CIN blocks the layer has; this function
// must ask, because it is building the mapper that answers. A separate
// `warn_layout_vs_layer` would be a second call a driver could forget, and the
// thing it would forget to say is that the run is measuring a degenerate
// layout.
//
// PRECONDITION: validate() has run. Under `split_cin` it is what turns
// cin_lo_blocks from the -1 sentinel into a width, and SplitCinMapper refuses a
// non-positive n_cin_lo, so calling this too early throws rather than building
// a mapper out of a sentinel.
std::unique_ptr<AddressMapper> make_mapper(const RunConfig& cfg,
                                           const WeightShape& shape,
                                           std::vector<Warning>& warnings) {
    if (cfg.layout == LayoutKind::BlockPack) {
        return std::unique_ptr<AddressMapper>(
            new BlockPackMapper(shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes));
    }
    if (cfg.layout == LayoutKind::KhkwSplit) {
        // No width to warn about: khkw_split takes no split argument, so there
        // is no config field that can disagree with the layer.
        return std::unique_ptr<AddressMapper>(
            new KhkwSplitMapper(shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes));
    }

    std::unique_ptr<SplitCinMapper> m(new SplitCinMapper(
        shape, cfg.cin_block, cfg.cout_block, cfg.weight_bytes, cfg.cin_lo_blocks));
    // The split width above the layer's block count: cin_lo never reaches its
    // radix, so the top of the L1 set index is unreachable and the cache runs
    // smaller than its geometry says. A quality problem and not a configuration
    // error, which is why split_cin.h keeps it out of the constructor: the
    // flatten stays correct, it just places worse.
    if (m->n_cin_lo() > m->n_cin_blocks()) {
        warnings.push_back(
            {"W_CIN_LO_UNREACHABLE",
             "cin_lo_blocks = " + std::to_string(m->n_cin_lo()) + " is above the layer's " +
                 std::to_string(m->n_cin_blocks()) +
                 " CIN blocks, so the top of the L1 set index is unreachable and the run "
                 "uses " + std::to_string(m->n_cin_blocks()) + " of its sets"});
    }
    return std::unique_ptr<AddressMapper>(m.release());
}

}  // namespace cachesim
