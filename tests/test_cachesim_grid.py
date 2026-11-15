"""python -m lays.cachesim grid: the khkw grid built from examples/cache/*.json writes
the files the demo writes."""
import pathlib
import subprocess
import sys

import pytest

from lays.cachesim.grid import full_grid, write_grid

REPO = pathlib.Path(__file__).resolve().parents[1]
DEMO_GRID = REPO / "data/demo/loas/grid"
# Same bytes as DEMO_GRID/khkw_{0,1,2}.json, for checkouts without data/demo.
BASELINE_GRID = {"khkw_0.json": "khkw_16b.json", "khkw_1.json": "khkw_32b.json",
                 "khkw_2.json": "khkw_64b.json"}
BASELINE_DIR = REPO / ".baseline/wcache/_khkw_grid"


def test_next_line_at_both_levels_in_sweep():
    base = {"cout_block": 4, "weight_bytes": 1}
    points = full_grid(base, {"line_bytes": [64], "l2_banks": [1],
                            "prefetch": [["next_line", 1], ["next_line", 3]],
                            "l2_prefetch": [["next_line", 1]]})
    assert points == [dict(base, cin_block=16, l2_banks=1, l2_prefetch_policy="next_line",
                           l2_prefetch_distance=1, prefetch_policy="next_line",
                           prefetch_distance=distance) for distance in (1, 3)]


def test_grid_files_equal_demo_grid(tmp_path):
    if (DEMO_GRID / "khkw_0.json").is_file():
        ref = {name: DEMO_GRID / name for name in BASELINE_GRID}
    elif (BASELINE_DIR / "khkw_16b.json").is_file():
        ref = {name: BASELINE_DIR / b for name, b in BASELINE_GRID.items()}
    else:
        pytest.skip(f"no reference grid under {DEMO_GRID} or {BASELINE_DIR}")
    paths = write_grid(tmp_path)
    assert sorted(p.name for p in paths.values()) == sorted(ref)
    for p in paths.values():
        assert p.read_bytes() == ref[p.name].read_bytes(), p.name


def test_cli_grid_writes_three_files(tmp_path):
    r = subprocess.run([sys.executable, "-m", "lays.cachesim", "grid", "--out", str(tmp_path)],
                       capture_output=True, text=True, cwd="/")
    assert r.returncode == 0, r.stderr
    names = ["khkw_0.json", "khkw_1.json", "khkw_2.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == names
    assert r.stdout.split() == [str(tmp_path / n) for n in names]
