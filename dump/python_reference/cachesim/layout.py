"""Generalized address-layout logic for CacheSim: turns a raw persisted
weight-trace event into individual elements, then maps each element to a
cache-line tag under CacheConfig's declared layout (inner_dim, line_size).

Every arch's weight_addresses entry is a fixed 5-tuple
(kh, kw, cin, cout_start, cout_end) -- see src/archmodels/*/address.py,
all five ported to C++ and verified to emit exactly this shape
(2026-07-26). That tuple's raw *positional* layout (expand_events' own
`order` argument) is a separate concern from the *cache's* layout
(CacheConfig.inner_dim): the former describes what each archmodel's real
hardware actually emits, the latter is a CacheSim modeling choice about
which dimension to absorb into a line. See
log/2026-07-26-workflow-optimization-plan.md's CacheSim section for why
these two are kept apart.

Matches log/2026-07-23-input-driven-weight-locality-plan.md section 1.1
(expansion) and 1.2/1.3 (tag formation) exactly, generalizing what was a
single hardcoded inner_dim ("cin") in the informal prototype
(profiling/0723/cin_locality_sweep.py) into a CacheConfig-driven choice.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from cachesim.config import DIMS, CacheConfig

Address = Tuple[int, int, int, int, int]  # 5 raw ints; meaning depends on `order`


class Element(NamedTuple):
    """One individual weight touched by an event, after expanding its
    ranged dimension -- one entry per (kh, kw, cin, cout) value, not per
    event. Always this same shape/field order regardless of what order
    the raw Address tuple came in, this is the point of Element: it's
    the layout-independent representation everything past expand_events
    operates on."""

    kh: int
    kw: int
    cin: int
    cout: int


def expand_events(events: Sequence[Address], order: Sequence[str]) -> List[Element]:
    """Turn each raw Address event into its individual Elements --
    section 1.1's expansion, generalized to any raw tuple layout.

    `order` names all 4 logical dims in the order they appear in the raw
    tuple; its LAST entry is the ranged (start, end) one, so a 5-int
    Address always unpacks as 3 single values (order[0:3]) followed by
    one (start, end) pair for order[3]. E.g. order=["kh","kw","cin","cout"]
    matches today's actual archmodel output (kh, kw, cin, cout_start,
    cout_end); order=["cin","cout","kh","kw"] would instead mean a raw
    tuple shaped (cin, cout, kh_start, kh_end).

    This is deliberately NOT a CacheConfig field (unlike inner_dim below):
    `order` describes an archmodel's real hardware output shape, not a
    CacheSim analysis choice, so it doesn't belong in the cache config.
    This function doesn't know or care WHERE `order` came from (a literal
    passed by a caller today, or an arch.yaml-driven value later) -- that
    plumbing is deliberately out of scope here, this is just the general
    unpacking logic once you have an order.

    Raises ValueError if `order` isn't a permutation of DIMS, a silent
    partial match would misassign real weight coordinates."""
    if sorted(order) != sorted(DIMS):
        raise ValueError(f"order must be a permutation of {DIMS}, got {list(order)}")

    single_dims = order[:3]
    ranged_dim = order[3]

    elements: List[Element] = []
    for addr in events:
        single_vals = dict(zip(single_dims, addr[:3]))
        range_start, range_end = addr[3], addr[4]
        for v in range(range_start, range_end):
            single_vals[ranged_dim] = v
            elements.append(Element(**single_vals))
    return elements


def tag_for_element(element: Element, config: CacheConfig) -> Tuple[int, int, int, int]:
    """Section 1.2/1.3's tag formation. Always a 4-tuple, in DIMS order
    (kh, kw, cin, cout), so tags stay directly comparable across
    CacheConfigs that differ only in how a line is formed (a component
    changes shape between choices, the tuple's arity never does).

    Under config.layout == "inner_dim": the other three dimensions stay
    exact and config.inner_dim collapses to
    inner_dim // config.line_size_bytes, so that many consecutive values
    of inner_dim (holding the other three fixed) share one cache line.

    Under config.layout == "hybrid": kh and kw stay exact and cin and cout
    each collapse by their own block size, so one line holds a
    cin_block x cout_block element block.

    config.layout/inner_dim/line_size_bytes are already validated by
    CacheConfig.__post_init__ (raises there, not here, on a bad value),
    so no re-validation needed at this call site."""
    if config.layout == "hybrid":
        return (element.kh, element.kw, element.cin // config.cin_block, element.cout // config.cout_block)
    values = {"kh": element.kh, "kw": element.kw, "cin": element.cin, "cout": element.cout}
    values[config.inner_dim] = values[config.inner_dim] // config.line_size_bytes
    return (values["kh"], values["kw"], values["cin"], values["cout"])


def element_tags(elements: Sequence[Element], config: CacheConfig) -> List[Tuple[int, int, int, int]]:
    """Tags for a whole element stream, same order as `elements`."""
    return [tag_for_element(e, config) for e in elements]


def hybrid_cout_lines(config: CacheConfig) -> int:
    """How many cout blocks the layer's true COUT spans. Two callers need
    the same number: it is the innermost radix a hybrid tag packs with,
    and it is the bound hierarchy.py's cout prefetch must stay inside, so
    it is derived here once instead of at both call sites. Rounded up, a
    real layer's COUT need not be a multiple of the block. C++ twin:
    src/cachesim/layout.h's hybrid_cout_lines."""
    return (config.cout_bound + config.cout_block - 1) // config.cout_block


def pack_tags(tags: Sequence[Tuple[int, int, int, int]], config: Optional[CacheConfig] = None) -> List[int]:
    """Flatten each 4-int tag into one mixed-radix int, so the packed
    value is both a valid cache-line key and an index cache.py can take
    modulo num_sets. kh needs no radix, it is the outermost component.

    Where the radices come from depends on the layout, and that is the
    set-index fix. A "hybrid" config carries the layer's true KH/KW/CIN/
    COUT, so the radices are the layer's own line counts and every line of
    the layer packs to the same index in every sample, covering the range
    0..n_lines-1 densely. An "inner_dim" config has no layer shape to work
    from and falls back to this sample's own observed per-dimension
    maxima, which is only injective over the tags that sample happened to
    touch.

    This formula is duplicated across languages: the C++ counterpart is
    TagPacker in src/cachesim/layout.h, and they must change together. A
    third copy is inlined in the archived sweep at
    dump/profiling/0726/native/cache_sweep.cpp:276-285; it stays on the
    observed-maxima radices and knows only the single-inner-dim layout,
    since the results it produced were computed that way."""
    if config is not None and config.layout == "hybrid":
        m_kw = config.kw_bound
        # Rounded up: a real layer's CIN/COUT need not be a multiple of the
        # block (a first conv layer's CIN is often 3).
        m_cin = (config.cin_bound + config.cin_block - 1) // config.cin_block
        m_cout = hybrid_cout_lines(config)
    elif tags:
        m_kw = max(t[1] for t in tags) + 1
        m_cin = max(t[2] for t in tags) + 1
        m_cout = max(t[3] for t in tags) + 1
    else:
        return []
    return [((t[0] * m_kw + t[1]) * m_cin + t[2]) * m_cout + t[3] for t in tags]


def tag_histogram(elements: Sequence[Element], config: CacheConfig) -> Dict[Tuple[int, int, int, int], int]:
    """tag -> access count, for the locality diagnostic (section 1.2)."""
    hist: Dict[Tuple[int, int, int, int], int] = {}
    for tag in element_tags(elements, config):
        hist[tag] = hist.get(tag, 0) + 1
    return hist
