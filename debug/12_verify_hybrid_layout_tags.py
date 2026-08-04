"""Hand-made test 1 of log/2026-08-03-l1-l2-cache-policy-plan.md: the
hybrid 4x4 cin x cout cache-line layout.

Two parts, both against tags and counts derived by hand below and written
out literally, never by calling the code under test:

  Part A -- tag formation. Every line packs a fixed cin_block x cout_block
  element block at one exact (kh, kw), so
  tag = (kh, kw, cin // 4, cout // 4). Checked element by element, along
  with the packed mixed-radix index each tag flattens to.

  Part B -- one whole replay. The same tiny layer, four bursts, run
  through both the Python reference twin (dump/python_reference/cachesim)
  and the native cache_replay binary via cachesim.native_bridge. Both must
  land on the hand-derived 2 hits out of 7 accesses. The cache is
  set-associative so the set index, and therefore the packed tag's
  radices, are exercised too, not only the tag tuple.

The fixture layer is KH=2, KW=3, CIN=6, COUT=10, deliberately not a
multiple of the 4x4 block in either cin or cout, so the block count has to
round up (2 cin blocks, 3 cout blocks) the way a real first conv layer's
CIN=3 forces it to.
"""

import gzip
import json
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import DIMS, CacheConfig  # noqa: E402
from cachesim.native_bridge import native_sample_hit_counts  # noqa: E402
from python_reference.cachesim.cache import Cache, replay  # noqa: E402
from python_reference.cachesim.layout import Element, element_tags, expand_events, pack_tags  # noqa: E402

# The fixture layer's true shape.
KH_BOUND, KW_BOUND, CIN_BOUND, COUT_BOUND = 2, 3, 6, 10

CONFIG = CacheConfig(
    cache_size_bytes=64,  # capacity_lines = 64/16 = 4, 2-way -> 2 sets
    line_size_bytes=16,   # 4 cin x 4 cout elements at 1 byte per weight
    cache_type="set_associative",
    associativity=2,
    inner_dim="cout",     # ignored under layout="hybrid"
    layout="hybrid",
    kh_bound=KH_BOUND,
    kw_bound=KW_BOUND,
    cin_bound=CIN_BOUND,
    cout_bound=COUT_BOUND,
)

# Part A. (kh, kw, cin, cout) -> tag (kh, kw, cin//4, cout//4) -> packed.
#
# Radices, by hand: kw has KW_BOUND = 3 values; cin has ceil(6/4) = 2
# blocks; cout has ceil(10/4) = 3 blocks. kh is outermost and needs none.
# So packed = ((kh * 3 + kw) * 2 + cin_blk) * 3 + cout_blk, and the whole
# layer occupies packed 0 through 2*3*2*3 - 1 = 35.
HAND_DERIVED = [
    # element,        tag,            packed
    ((0, 0, 0, 0), (0, 0, 0, 0), 0),   # ((0*3+0)*2+0)*3+0
    ((0, 0, 3, 3), (0, 0, 0, 0), 0),   # last element of that same 4x4 block
    ((0, 0, 4, 3), (0, 0, 1, 0), 3),   # cin steps into the next block
    ((0, 0, 3, 4), (0, 0, 0, 1), 1),   # cout steps into the next block
    ((0, 1, 5, 9), (0, 1, 1, 2), 11),  # ((0*3+1)*2+1)*3+2
    ((0, 2, 2, 8), (0, 2, 0, 2), 14),  # ((0*3+2)*2+0)*3+2
    ((1, 0, 4, 7), (1, 0, 1, 1), 22),  # ((1*3+0)*2+1)*3+1
    ((1, 2, 5, 9), (1, 2, 1, 2), 35),  # ((1*3+2)*2+1)*3+2, the last line
]

# Part B. Four bursts in the archmodels' raw 5-tuple shape
# (kh, kw, cin, cout_start, cout_end).
EVENTS = [
    (0, 0, 0, 0, 8),
    (0, 0, 3, 0, 8),
    (0, 0, 4, 0, 8),
    (1, 2, 5, 8, 10),
]

# Hand-derived replay of EVENTS. One access per DISTINCT consecutive line
# tag within a burst (a burst is one memory transaction), so:
#
#   burst 1: cin 0 -> block 0; cout 0..7 -> blocks 0 then 1  -> packed 0, 1
#   burst 2: cin 3 -> block 0, same tags as burst 1          -> packed 0, 1
#   burst 3: cin 4 -> block 1; cout 0..7 -> blocks 0 then 1  -> packed 3, 4
#   burst 4: cout 8, 9 -> both block 2, so one access only    -> packed 35
#
# 2 sets, 2 ways, set = packed % 2:
#   0  -> set 0, miss   set 0: [0]
#   1  -> set 1, miss   set 1: [1]
#   0  -> set 0, HIT    set 0: [0]
#   1  -> set 1, HIT    set 1: [1]
#   3  -> set 1, miss   set 1: [3, 1]
#   4  -> set 0, miss   set 0: [4, 0]
#   35 -> set 1, miss, set 1 is full so its LRU line (1) is evicted
EXPECTED_HITS, EXPECTED_ACCESSES = 2, 7


def python_hit_counts() -> tuple:
    """The reference twin's replay of EVENTS, composed the same way
    sweep._burst_hits does (inlined here only to skip its
    tracegen/gurobipy import, which this fixture does not need)."""
    order = list(DIMS)
    tags = []
    for event in EVENTS:
        prev = None
        for tag in element_tags(expand_events([event], order), CONFIG):
            if tag != prev:
                tags.append(tag)
                prev = tag
    hits = replay(Cache(CONFIG), pack_tags(tags, CONFIG))
    return sum(hits), len(hits)


def native_hit_counts() -> tuple:
    """The same replay through the production path: cache_replay, driven
    by cachesim.native_bridge, over a one-tile trace holding EVENTS."""
    with tempfile.TemporaryDirectory() as tmp:
        sample = pathlib.Path(tmp) / "sample_00000.json.gz"
        with gzip.open(sample, "wt") as fh:
            json.dump({"tiles": [{"weight_addresses": [list(e) for e in EVENTS]}]}, fh)
        return native_sample_hit_counts(sample, CONFIG, list(DIMS))


def main() -> int:
    failures = []

    for element, expected_tag, expected_packed in HAND_DERIVED:
        tag = element_tags([Element(*element)], CONFIG)[0]
        if tag != expected_tag:
            failures.append(f"tag for {element}: expected {expected_tag}, got {tag}")
        packed = pack_tags([tag], CONFIG)[0]
        if packed != expected_packed:
            failures.append(f"packed for {element}: expected {expected_packed}, got {packed}")

    py_counts = python_hit_counts()
    if py_counts != (EXPECTED_HITS, EXPECTED_ACCESSES):
        failures.append(f"python reference replay: expected {(EXPECTED_HITS, EXPECTED_ACCESSES)}, got {py_counts}")
    native_counts = native_hit_counts()
    if native_counts != (EXPECTED_HITS, EXPECTED_ACCESSES):
        failures.append(f"native replay: expected {(EXPECTED_HITS, EXPECTED_ACCESSES)}, got {native_counts}")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASS: {len(HAND_DERIVED)} hand-derived 4x4 tags and their packed indices match, "
          f"and both the python reference and the native cache_replay replay EVENTS as "
          f"{EXPECTED_HITS}/{EXPECTED_ACCESSES} hits, as hand-derived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
