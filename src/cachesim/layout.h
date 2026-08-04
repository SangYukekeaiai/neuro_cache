#pragma once
// Port of layout.py: turns one raw weight-trace event into its
// individual (kh, kw, cin, cout) Elements (expand_events), then maps
// each Element to a cache-line Tag under a given inner_dim/line_size
// (tag_for_element). Same two-step split as layout.py, same semantics:
// `order`'s last entry is the ranged (start, end) dim; tag_for_element
// collapses only `inner_dim` via floor division, the other 3 stay exact.
//
// for_each_element takes a callback instead of returning a
// std::vector<Element> (unlike layout.py's expand_events, which returns
// a real list) because one event from the largest cached layer expands
// to ~16 elements and a sample has ~1M events -- materializing all of
// them (~15M Elements) before processing was the original Python path's
// actual bottleneck (millions of NamedTuple objects); streaming avoids
// reintroducing that in C++ even though the interpreter overhead is gone.

#include <cstdint>
#include <vector>

#include "config.h"
#include "dims.h"

namespace cachesim {

struct Element {
    int64_t kh, kw, cin, cout;
};

struct Tag {
    int64_t kh, kw, cin, cout;
};

// expand_events, one raw 5-int event at a time: order[0:3] are the 3
// single-valued dims (v[0:3]), order[3] is the ranged dim (v[3]=start,
// v[4]=end).
template <typename F>
inline void for_each_element(const int32_t v[5], const std::vector<Dim> &order, F &&fn) {
    int64_t single[N_DIMS];
    single[order[0]] = v[0];
    single[order[1]] = v[1];
    single[order[2]] = v[2];
    Dim ranged_dim = order[3];

    for (int32_t rv = v[3]; rv < v[4]; ++rv) {
        int64_t vals[N_DIMS];
        vals[order[0]] = single[order[0]];
        vals[order[1]] = single[order[1]];
        vals[order[2]] = single[order[2]];
        vals[ranged_dim] = rv;
        fn(Element{vals[KH], vals[KW], vals[CIN], vals[COUT]});
    }
}

// tag_for_element_hybrid: kh/kw stay exact, cin and cout each collapse by
// their own block size, so one line holds a cin_block x cout_block
// element block instead of a run along a single dim -- identical rule to
// layout.py's Layout "hybrid" branch.
inline Tag tag_for_element_hybrid(const Element &e, int64_t cin_block, int64_t cout_block) {
    return Tag{e.kh, e.kw, e.cin / cin_block, e.cout / cout_block};
}

// tag_for_element: the other three dims stay exact, inner_dim collapses
// to inner_dim // line_size_bytes -- identical rule to layout.py's.
inline Tag tag_for_element(const Element &e, Dim inner_dim, int64_t line_size_bytes) {
    Tag t{e.kh, e.kw, e.cin, e.cout};
    switch (inner_dim) {
        case KH: t.kh /= line_size_bytes; break;
        case KW: t.kw /= line_size_bytes; break;
        case CIN: t.cin /= line_size_bytes; break;
        case COUT: t.cout /= line_size_bytes; break;
        default: break;
    }
    return t;
}

// TagPacker: mixed-radix-encodes a Tag into one int64, serving as both
// policy.h's unordered_map key and cache.h's set index. kh needs no
// radix, it is the outermost component.
//
// The radices are the caller's, not this class's, because the two
// layouts derive them differently (see main.cpp): InnerDim has no layer
// shape to work from and falls back to this sample's own observed maxima
// plus one, while Hybrid uses the layer's true shape in block units.
// That difference is the set-index fix: under observed maxima the packed
// value depends on what one sample happened to touch, and the cin radix
// stays in raw element units even though a Hybrid tag's cin component is
// a block index, which leaves most sets unreachable.
//
// This formula is duplicated across languages: the Python counterpart is
// pack_tags in dump/python_reference/cachesim/layout.py, and they must
// change together. A third copy is inlined in the archived sweep at
// dump/profiling/0726/native/cache_sweep.cpp:276-285; it stays on the
// observed-maxima radices and knows only the single-inner-dim layout,
// since the results it produced were computed that way.
class TagPacker {
public:
    // r_kw/r_cin/r_cout: how many distinct values each of those three tag
    // components can take, not the maximum value.
    TagPacker(int64_t r_kw, int64_t r_cin, int64_t r_cout) : m_kw_(r_kw), m_cin_(r_cin), m_cout_(r_cout) {}

    int64_t pack(const Tag &t) const { return ((t.kh * m_kw_ + t.kw) * m_cin_ + t.cin) * m_cout_ + t.cout; }

private:
    int64_t m_kw_, m_cin_, m_cout_;
};

// How many cout blocks the layer's true COUT spans. Two callers need the
// same number: it is the innermost radix a Hybrid tag packs with, and it
// is the bound hierarchy.h's cout prefetch must stay inside, so it is
// derived here once instead of at both call sites. The Python
// counterpart is hybrid_cout_lines in
// dump/python_reference/cachesim/layout.py.
inline int64_t hybrid_cout_lines(const CacheConfig &cfg) {
    return (cfg.cout_bound + cfg.cout_block - 1) / cfg.cout_block;
}

// The radices a Hybrid tag packs with: the layer's true shape, counted in
// lines rather than elements, since a Hybrid tag's cin/cout components
// are block indices. Rounded up, because a real layer's CIN/COUT need not
// be a multiple of the block (a first conv layer's CIN is often 3).
// Shared by both entry points (main.cpp, main_hierarchical.cpp) so the
// derivation is written once; the Python counterpart is the hybrid branch
// of pack_tags in dump/python_reference/cachesim/layout.py.
inline TagPacker hybrid_packer(const CacheConfig &cfg) {
    return TagPacker(cfg.kw_bound, (cfg.cin_bound + cfg.cin_block - 1) / cfg.cin_block, hybrid_cout_lines(cfg));
}

} // namespace cachesim
