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


@dataclass(frozen=True)
class CacheConfig:
    cache_size_bytes: int
    line_size_bytes: int
    cache_type: str
    inner_dim: str
    policy: str = "lru"
    associativity: Optional[int] = None  # only meaningful when cache_type == "set_associative"

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
    return CacheConfig(**kwargs)
