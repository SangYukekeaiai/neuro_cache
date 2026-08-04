"""CacheConfig: the cache-config input to CacheSim (see
log/2026-07-26-workflow-optimization-plan.md's CacheSim pipeline --
weight trace + cache config -> CacheSim -> analytical results), read from
a YAML file under configs/cache/, mirroring how src/parsers/arch.py reads
each arch's configs/arch/<name>.yaml.

Lives in its own module (not inside cache.py or layout.py) because both
of those need this type: layout.py's tag formation needs `inner_dim`/
`line_size_bytes`, cache.py's cache classes need `cache_size_bytes`/
`line_size_bytes`/`cache_type`/`associativity`. Putting CacheConfig in
either of those two would make the other import it sideways for no
reason; a small shared module avoids that.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Optional

import yaml

DIMS = ("kh", "kw", "cin", "cout")
CACHE_TYPES = ("fully_associative", "set_associative", "direct_mapped")
# "lru" is the only one with a real implementation (policy.py). The rest
# are declared here so CacheConfig/the sweep harness can name and
# validate against them before they're built -- "input_activity" is the
# 2026-07-22 plan's actual hypothesis (eviction informed by spike-input
# hot zones), the reason this whole cache-sim effort exists; "lru" is
# only ever the baseline it's meant to be compared against.
POLICIES = ("lru", "fifo", "lfu", "random", "input_activity")
# How a cache line is formed out of a (kh, kw, cin, cout) coordinate.
# "inner_dim": one dim (`inner_dim`) collapses by line_size_bytes, the
#   other three stay exact -- the single-dimension layout every
#   configs/cache/*.yaml uses today.
# "hybrid": kh/kw stay exact and cin and cout each collapse by their own
#   block size, so one line holds a cin_block x cout_block element block
#   (log/2026-08-03-l1-l2-cache-policy-plan.md). `inner_dim` is ignored
#   under this layout, but stays a required field so the two layouts share
#   one config shape.
LAYOUTS = ("inner_dim", "hybrid")

# The element block one cache line holds under layout == "hybrid", fixed
# at 4x4 by log/2026-08-03-l1-l2-cache-policy-plan.md. Stated here once:
# CacheConfig's cin_block/cout_block default to these, and
# hybrid_config_from_dims derives line_size_bytes from them rather than
# repeating the 16.
CIN_BLOCK = 4
COUT_BLOCK = 4

# Which workload_dims key holds each of the four shape bounds. The layer's
# true shape lives in the sample's own workload_dims (never in a cache
# YAML -- see load_cache_config), so this mapping is the one place the
# trace's key spelling meets CacheConfig's field names.
_DIM_KEYS = {"kh_bound": "KH", "kw_bound": "KW", "cin_bound": "CIN", "cout_bound": "COUT"}


@dataclass(frozen=True)
class CacheConfig:
    cache_size_bytes: int
    line_size_bytes: int
    cache_type: str
    inner_dim: str
    policy: str = "lru"
    associativity: Optional[int] = None  # only meaningful when cache_type == "set_associative"
    layout: str = "inner_dim"
    # Element block one line holds under layout == "hybrid". Fixed at 4x4
    # by the 08-03 plan, so these are not read from YAML; they are named
    # fields rather than literals inside layout.py/layout.h so the block
    # shape is stated in exactly one place.
    cin_block: int = CIN_BLOCK
    cout_block: int = COUT_BLOCK
    # The layer's true KH/KW/CIN/COUT, from the sample's own workload_dims.
    # These are the radices the packed tag flattens with, so a given
    # (kh, kw, cin, cout) line gets the same packed index -- and therefore
    # the same cache set -- in every sample of the layer, instead of an
    # index that shifts with whatever one sample happened to touch.
    # Required by layout == "hybrid", rejected otherwise, so there are two
    # configurations to reason about rather than four.
    kh_bound: Optional[int] = None
    kw_bound: Optional[int] = None
    cin_bound: Optional[int] = None
    cout_bound: Optional[int] = None

    def __post_init__(self) -> None:
        if self.cache_size_bytes <= 0:
            raise ValueError(f"CacheConfig: cache_size_bytes must be positive, got {self.cache_size_bytes}")
        if self.line_size_bytes <= 0:
            raise ValueError(f"CacheConfig: line_size_bytes must be positive, got {self.line_size_bytes}")
        if self.cache_type not in CACHE_TYPES:
            raise ValueError(f"CacheConfig: cache_type must be one of {CACHE_TYPES}, got {self.cache_type!r}")
        if self.inner_dim not in DIMS:
            raise ValueError(f"CacheConfig: inner_dim must be one of {DIMS}, got {self.inner_dim!r}")
        if self.policy not in POLICIES:
            raise ValueError(f"CacheConfig: policy must be one of {POLICIES}, got {self.policy!r}")
        if self.associativity is not None and self.associativity <= 0:
            raise ValueError(f"CacheConfig: associativity must be positive or None, got {self.associativity}")
        if self.cache_type != "set_associative" and self.associativity is not None:
            raise ValueError(
                f"CacheConfig: associativity is only meaningful when "
                f"cache_type == 'set_associative', got cache_type={self.cache_type!r} "
                f"with associativity={self.associativity}"
            )
        if self.layout not in LAYOUTS:
            raise ValueError(f"CacheConfig: layout must be one of {LAYOUTS}, got {self.layout!r}")
        if self.cin_block <= 0 or self.cout_block <= 0:
            raise ValueError(
                f"CacheConfig: cin_block and cout_block must be positive, "
                f"got {self.cin_block} and {self.cout_block}"
            )
        bounds = {
            "kh_bound": self.kh_bound,
            "kw_bound": self.kw_bound,
            "cin_bound": self.cin_bound,
            "cout_bound": self.cout_bound,
        }
        if self.layout == "hybrid":
            missing = sorted(name for name, value in bounds.items() if value is None)
            if missing:
                raise ValueError(
                    f"CacheConfig: layout='hybrid' flattens with the layer's true shape, "
                    f"so it requires {missing} to be set (from the sample's workload_dims)"
                )
            nonpositive = sorted(name for name, value in bounds.items() if value <= 0)
            if nonpositive:
                raise ValueError(f"CacheConfig: shape bounds must be positive, got non-positive {nonpositive}")
            # One line really does hold cin_block x cout_block elements, and
            # capacity_lines divides by line_size_bytes, so a mismatch would
            # silently model a cache of the wrong size.
            if self.line_size_bytes != self.cin_block * self.cout_block:
                raise ValueError(
                    f"CacheConfig: layout='hybrid' packs cin_block x cout_block "
                    f"({self.cin_block} x {self.cout_block} = {self.cin_block * self.cout_block}) "
                    f"elements per line, so line_size_bytes must equal that, got {self.line_size_bytes}"
                )
        else:
            supplied = sorted(name for name, value in bounds.items() if value is not None)
            if supplied:
                raise ValueError(
                    f"CacheConfig: shape bounds are only used by layout='hybrid', "
                    f"got {supplied} with layout={self.layout!r}"
                )
        if self.cache_type == "set_associative":
            if self.associativity is None:
                raise ValueError("CacheConfig: cache_type='set_associative' requires associativity to be set")
            if self.capacity_lines % self.associativity != 0:
                raise ValueError(
                    f"CacheConfig: capacity_lines ({self.capacity_lines}) must be "
                    f"evenly divisible by associativity ({self.associativity}) for "
                    f"a set-associative cache"
                )

    @property
    def capacity_lines(self) -> int:
        """Total resident-line count: cache_size_bytes // line_size_bytes,
        floored, minimum 1."""
        return max(1, self.cache_size_bytes // self.line_size_bytes)


_REQUIRED_KEYS = ("cache_size_bytes", "line_size_bytes", "cache_type", "inner_dim")


def load_cache_config(path: pathlib.Path) -> CacheConfig:
    """Read a cache-config YAML (top-level `cache:` key, mirroring
    parsers/arch.py's top-level `arch:` convention) into a CacheConfig."""
    path = pathlib.Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CacheConfig: config not found: {path}")

    with open(path) as fh:
        raw = yaml.safe_load(fh)

    if not raw or "cache" not in raw:
        raise ValueError(f"CacheConfig: YAML at {path} must have a top-level 'cache' key")
    cache = raw["cache"]

    missing = [k for k in _REQUIRED_KEYS if k not in cache]
    if missing:
        raise ValueError(f"CacheConfig: {path} missing required key(s) {missing}")

    kwargs = dict(
        cache_size_bytes=int(cache["cache_size_bytes"]),
        line_size_bytes=int(cache["line_size_bytes"]),
        cache_type=cache["cache_type"],
        inner_dim=cache["inner_dim"],
        associativity=(int(cache["associativity"]) if cache.get("associativity") is not None else None),
    )
    if cache.get("policy") is not None:
        kwargs["policy"] = cache["policy"]
    if cache.get("layout") is not None:
        kwargs["layout"] = cache["layout"]
    # The shape bounds are deliberately not read from YAML: they belong to
    # the layer being replayed, not to the cache, so they come from the
    # sample's workload_dims. `layout: hybrid` in a YAML therefore fails
    # validation here, pointing the caller at workload_dims.
    return CacheConfig(**kwargs)


def hybrid_config_from_dims(
    workload_dims: dict,
    cache_size_bytes: int,
    cache_type: str,
    associativity: Optional[int] = None,
) -> CacheConfig:
    """A layout='hybrid' CacheConfig for the layer `workload_dims`
    describes, at the given capacity and structure. This is the intended
    way to build a hybrid config: the four shape bounds are the layer's,
    so they cannot come from a cache YAML, and the two-level engine builds
    one of these per level from the sample it is about to replay.

    line_size_bytes is derived, not passed: under this layout a line holds
    exactly CIN_BLOCK x COUT_BLOCK elements at 1 byte each, and
    CacheConfig rejects any other value.

    inner_dim is unused under this layout but is still a required field
    (both layouts share one config shape), so it is fixed to DIMS[0] here
    rather than offered as a knob that changes nothing."""
    bounds = {field: int(workload_dims[key]) for field, key in _DIM_KEYS.items()}
    return CacheConfig(
        cache_size_bytes=cache_size_bytes,
        line_size_bytes=CIN_BLOCK * COUT_BLOCK,
        cache_type=cache_type,
        associativity=associativity,
        inner_dim=DIMS[0],
        layout="hybrid",
        **bounds,
    )
