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

from typing import Dict, List, NamedTuple, Sequence, Tuple

from .config import DIMS, CacheConfig

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
    """Section 1.2/1.3's tag formation: the other three dimensions stay
    exact, config.inner_dim collapses to inner_dim // config.line_size_bytes,
    so that many consecutive values of inner_dim (holding the other three
    fixed) share one cache line. Always a 4-tuple, in DIMS order
    (kh, kw, cin, cout), so tags stay directly comparable across
    CacheConfigs that only differ in inner_dim (only ONE component
    actually changes shape between choices, not the tuple's arity).

    config.inner_dim/line_size_bytes are already validated by
    CacheConfig.__post_init__ (raises there, not here, on a bad value),
    so no re-validation needed at this call site."""
    values = {"kh": element.kh, "kw": element.kw, "cin": element.cin, "cout": element.cout}
    values[config.inner_dim] = values[config.inner_dim] // config.line_size_bytes
    return (values["kh"], values["kw"], values["cin"], values["cout"])


def element_tags(elements: Sequence[Element], config: CacheConfig) -> List[Tuple[int, int, int, int]]:
    """Tags for a whole element stream, same order as `elements`."""
    return [tag_for_element(e, config) for e in elements]


def tag_histogram(elements: Sequence[Element], config: CacheConfig) -> Dict[Tuple[int, int, int, int], int]:
    """tag -> access count, for the locality diagnostic (section 1.2)."""
    hist: Dict[Tuple[int, int, int, int], int] = {}
    for tag in element_tags(elements, config):
        hist[tag] = hist.get(tag, 0) + 1
    return hist
