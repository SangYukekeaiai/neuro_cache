"""Hand-made test 2 of log/2026-08-03-l1-l2-cache-policy-plan.md: the
set-index fix, "flatten using the layer's true KH/KW/CIN/COUT shape, not
per-sample observed maxima, so all sets stay reachable".

The set index is packed_tag % num_sets (cache.h / cache.py), so which
sets a layer can reach is decided entirely by the radices the tag is
flattened with. This test pins both halves of what the old radices got
wrong, contrasting each against the fixed formula on one tiny fixture
layer so the test documents the bug and not only the fix.

  Part A -- unreachable sets. The old radices come from a pre-scan over
  the sample's raw events (src/cachesim/main.cpp), which divides exactly
  one dimension, config.inner_dim, by line_size_bytes. A hybrid tag's cin
  AND cout components are both block indices, so whichever of the two is
  not inner_dim keeps a radix in raw element units. That leaves an
  oversized stride between consecutive packed values, and most sets are
  never reached. The true bounds, counted in blocks, pack the layer onto
  0..n_lines-1 with no gaps instead.

  Part B -- sample-dependent sets. Observed maxima also make the packed
  index a property of one sample rather than of the layer, so the very
  same weight line lands in different sets in two samples of the same
  layer. The layer's true shape does not move between samples, so the
  fixed formula gives it one set.

Fixture layer: KH=2, KW=2, CIN=16, COUT=16 with the fixed 4x4 block, so
2 x 2 x 4 x 4 = 64 cache lines. Cache: 512 bytes of 16-byte lines = 32
lines, 2-way, so 16 sets.
"""

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "dump"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from cachesim.config import CacheConfig  # noqa: E402
from python_reference.cachesim.cache import Cache  # noqa: E402
from python_reference.cachesim.layout import pack_tags  # noqa: E402

KH_BOUND, KW_BOUND, CIN_BOUND, COUT_BOUND = 2, 2, 16, 16
BLOCK = 4

CONFIG = CacheConfig(
    cache_size_bytes=512,  # capacity_lines = 512/16 = 32, 2-way -> 16 sets
    line_size_bytes=16,
    cache_type="set_associative",
    associativity=2,
    inner_dim="cin",  # what the old pre-scan would have divided
    layout="hybrid",
    kh_bound=KH_BOUND,
    kw_bound=KW_BOUND,
    cin_bound=CIN_BOUND,
    cout_bound=COUT_BOUND,
)

# Every cache line the layer has, as hybrid tags (kh, kw, cin_blk, cout_blk).
LAYER_TAGS = [
    (kh, kw, cin_blk, cout_blk)
    for kh in range(KH_BOUND)
    for kw in range(KW_BOUND)
    for cin_blk in range(CIN_BOUND // BLOCK)
    for cout_blk in range(COUT_BOUND // BLOCK)
]

# Hand-derived, fixed formula: kw has 2 values, cin has 16/4 = 4 blocks,
# cout has 16/4 = 4 blocks, so
#   packed = ((kh * 2 + kw) * 4 + cin_blk) * 4 + cout_blk
# Every component is below its own radix, so the 64 lines land on 0..63
# one-to-one, and 64 consecutive values cover all 16 sets evenly.
N_LINES = 64
EXPECTED_NEW_SETS = 16

# Hand-derived, old formula: the pre-scan sees this sample's raw maxima
# kh=1, kw=1, cin=15, cout=15, then divides only inner_dim ("cin") by
# line_size_bytes = 16, giving radices kw=2, cin=15//16+1=1, cout=16. So
#   packed_old = ((kh * 2 + kw) * 1 + cin_blk) * 16 + cout_blk
#              = 16 * (2*kh + kw + cin_blk) + cout_blk
# cout_blk only ever reaches 3, so packed_old % 16 is just cout_blk:
# sets 0-3 and nothing else. The 16x stride also folds the three outer
# components onto their sum, which runs 0..6, so the 64 lines collapse
# onto 7 * 4 = 28 distinct indices, aliasing distinct lines together.
EXPECTED_OLD_SETS = 4
EXPECTED_OLD_SET_IDS = [0, 1, 2, 3]
EXPECTED_OLD_DISTINCT = 28

# Part B. One line of the layer, and the two samples whose observed
# maxima disagree about it.
PROBE_TAG = (1, 1, 1, 3)
# Sample S2 only ever touches cin blocks 0 and 1 (the rest of the layer's
# input channels stay silent), so its observed cin radix is 2, not 4:
#   packed = ((1 * 2 + 1) * 2 + 1) * 4 + 3 = 31   -> set 31 % 16 = 15
S2_TAGS = [t for t in LAYER_TAGS if t[2] <= 1]
EXPECTED_S2_OBSERVED_SET = 15
# Under the layer's true shape the same line is
#   packed = ((1 * 2 + 1) * 4 + 1) * 4 + 3 = 55   -> set 55 % 16 = 7
EXPECTED_TRUE_SET = 7


def pack_old_pre_scan(tags):
    """src/cachesim/main.cpp's pre-scan radices, reproduced here so the
    test states the old rule itself rather than calling anything: raw
    per-dimension maxima over the sample, with only inner_dim divided by
    line_size_bytes."""
    m_kw = max(t[1] for t in tags) + 1
    m_cin = (CIN_BOUND - 1) // CONFIG.line_size_bytes + 1
    m_cout = (COUT_BOUND - 1) + 1
    return [((t[0] * m_kw + t[1]) * m_cin + t[2]) * m_cout + t[3] for t in tags]


def main() -> int:
    num_sets = Cache(CONFIG).num_sets
    failures = []

    if num_sets != EXPECTED_NEW_SETS:
        failures.append(f"fixture cache should have {EXPECTED_NEW_SETS} sets, got {num_sets}")

    # Part A.
    new_packed = pack_tags(LAYER_TAGS, CONFIG)
    if sorted(new_packed) != list(range(N_LINES)):
        failures.append(
            f"true-bound packing should cover 0..{N_LINES - 1} exactly once, "
            f"got {len(set(new_packed))} distinct values in "
            f"[{min(new_packed)}, {max(new_packed)}]"
        )
    new_sets = sorted({p % num_sets for p in new_packed})
    if new_sets != list(range(EXPECTED_NEW_SETS)):
        failures.append(f"true-bound packing should reach all {EXPECTED_NEW_SETS} sets, got {new_sets}")

    old_packed = pack_old_pre_scan(LAYER_TAGS)
    old_sets = sorted({p % num_sets for p in old_packed})
    if old_sets != EXPECTED_OLD_SET_IDS:
        failures.append(f"old formula should reach only sets {EXPECTED_OLD_SET_IDS}, got {old_sets}")
    if len(set(old_packed)) != EXPECTED_OLD_DISTINCT:
        failures.append(
            f"old formula should collapse {N_LINES} lines onto {EXPECTED_OLD_DISTINCT} "
            f"packed indices, got {len(set(old_packed))}"
        )

    # Part B.
    s2_observed_set = pack_tags(S2_TAGS)[S2_TAGS.index(PROBE_TAG)] % num_sets
    if s2_observed_set != EXPECTED_S2_OBSERVED_SET:
        failures.append(
            f"under sample S2's observed maxima, {PROBE_TAG} should land in set "
            f"{EXPECTED_S2_OBSERVED_SET}, got {s2_observed_set}"
        )
    true_set = new_packed[LAYER_TAGS.index(PROBE_TAG)] % num_sets
    s2_true_set = pack_tags(S2_TAGS, CONFIG)[S2_TAGS.index(PROBE_TAG)] % num_sets
    if true_set != EXPECTED_TRUE_SET or s2_true_set != EXPECTED_TRUE_SET:
        failures.append(
            f"under the layer's true shape, {PROBE_TAG} should land in set "
            f"{EXPECTED_TRUE_SET} in every sample, got {true_set} and {s2_true_set}"
        )
    if s2_observed_set == true_set:
        failures.append("Part B fixture is not exercising the bug: both formulas agree on the probe line")

    if failures:
        print(f"FAIL: {len(failures)} issue(s)")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASS: the layer's {N_LINES} lines pack onto 0..{N_LINES - 1} and reach all "
          f"{EXPECTED_NEW_SETS} sets under its true shape, where the old per-sample radices "
          f"reach only sets {EXPECTED_OLD_SET_IDS} and alias the {N_LINES} lines onto "
          f"{EXPECTED_OLD_DISTINCT} indices; line {PROBE_TAG} is set {EXPECTED_TRUE_SET} in "
          f"every sample now, not set {EXPECTED_S2_OBSERVED_SET} in one and "
          f"{EXPECTED_TRUE_SET} in another")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
