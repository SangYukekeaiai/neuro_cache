"""The pure pieces of scripts/demo.py: the nocsim/wcache join, the speedup,
and the per-config geomean summary."""
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import demo  # noqa: E402


def wc(layer, sample, config, cycles):
    return {"tag": layer, "trace_dir": "t", "layer": layer, "sample": sample,
            "config": config, "l2_banks": "1", "total_cycles": str(cycles)}


def test_speedup_is_nocsim_over_wcache():
    assert demo.speedup(300, 150) == 2.0


def test_geomean_of_two_and_eight_is_four():
    assert math.isclose(demo.geomean([2.0, 8.0]), 4.0)


def test_join_pairs_each_wcache_row_with_its_layer_sample_nocsim_cycles():
    nocsim = {("t", "A", 0): 300, ("t", "A", 1): 400}
    rows = demo.join_results(nocsim, [wc("A", 0, "c0", 150), wc("A", 1, "c0", 100)])
    assert [(r["nocsim_total_cycles"], r["wcache_total_cycles"], r["speedup_vs_nocsim"])
            for r in rows] == [(300, 150, 2.0), (400, 100, 4.0)]
    assert rows[0]["config"] == "c0" and rows[0]["l2_banks"] == "1"
    assert "total_cycles" not in rows[0]


def test_join_refuses_a_wcache_row_without_nocsim_cycles():
    with pytest.raises(KeyError):
        demo.join_results({}, [wc("A", 0, "c0", 150)])


def test_summary_is_geomean_per_config_in_first_seen_order():
    rows = [{"config": "c1", "speedup_vs_nocsim": 2.0},
            {"config": "c0", "speedup_vs_nocsim": 1.0},
            {"config": "c1", "speedup_vs_nocsim": 8.0}]
    assert demo.summarize(rows) == [("c1", pytest.approx(4.0), 2), ("c0", 1.0, 1)]
