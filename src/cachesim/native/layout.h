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

// sum(tag) from cache.py's _set_index -- kept here since it's purely a
// function of the Tag, used by cache.h to pick a set.
inline int64_t tag_sum(const Tag &t) { return t.kh + t.kw + t.cin + t.cout; }

// TagPacker: no equivalent in layout.py, which just hands Python's
// native tuple hashing a 4-tuple. C++ needs an explicit hashable key for
// policy.h's unordered_map, so this mixed-radix-encodes a Tag into one
// int64 using this sample's own observed per-dim maxima (found by the
// caller's own pre-scan over its raw events, see main.cpp), guaranteeing
// distinct Tags pack to distinct ints without guessing fixed bit-widths.
class TagPacker {
public:
    TagPacker(int64_t max_kw, int64_t max_cin, int64_t max_cout)
        : m_kw_(max_kw + 1), m_cin_(max_cin + 1), m_cout_(max_cout + 1) {}

    int64_t pack(const Tag &t) const { return ((t.kh * m_kw_ + t.kw) * m_cin_ + t.cin) * m_cout_ + t.cout; }

private:
    int64_t m_kw_, m_cin_, m_cout_;
};

} // namespace cachesim
